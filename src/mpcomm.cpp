// Copyright 2024 KVCache.AI
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "mpcomm.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/tcp.h>
#include <numaif.h>
#include <pthread.h>
#include <sched.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <thread>

namespace mpcomm {

// ============================================================================
// ThreadPool Implementation
// A simple, efficient thread pool that supports:
// - Fixed number of worker threads with CPU affinity
// - Task submission with thread-specific routing
// - Barrier synchronization for batch operations
// ============================================================================

// Environment variable name for thread pool size
static const char* kThreadPoolSizeEnvVar = "MPCOMM_THREAD_POOL_SIZE";

class ThreadPool {
public:
    // Create a thread pool with the specified number of worker threads
    // If bind_cpu is true, each worker will be bound to its corresponding CPU core
    explicit ThreadPool(size_t num_threads, bool bind_cpu = false, int cpu_base_offset = 0)
        : stop_(false), bind_cpu_(bind_cpu), cpu_base_offset_(cpu_base_offset) {
        workers_.reserve(num_threads);
        for (size_t i = 0; i < num_threads; ++i) {
            workers_.emplace_back(&ThreadPool::workerLoop, this, i);
        }
    }

    ~ThreadPool() {
        shutdown();
    }

    // Disable copy
    ThreadPool(const ThreadPool&) = delete;
    ThreadPool& operator=(const ThreadPool&) = delete;

    // Submit a task to be executed by a specific worker thread
    // thread_id: the worker thread that should execute this task (0 to num_threads-1)
    void submitToThread(size_t thread_id, std::function<void()> task) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (stop_) return;
            task_queues_[thread_id].push(std::move(task));
        }
        cv_.notify_all();
    }

    // Wait for all submitted tasks to complete
    // Call this after submitting a batch of tasks
    void waitAll() {
        std::unique_lock<std::mutex> lock(mutex_);
        done_cv_.wait(lock, [this] {
            if (stop_) return true;
            // Check if all queues are empty and no tasks are running
            for (const auto& q : task_queues_) {
                if (!q.second.empty()) return false;
            }
            return active_tasks_ == 0;
        });
    }

    // Get the number of worker threads
    size_t size() const { return workers_.size(); }

    // Shutdown the thread pool
    void shutdown() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (stop_) return;
            stop_ = true;
        }
        cv_.notify_all();
        for (auto& worker : workers_) {
            if (worker.joinable()) {
                worker.join();
            }
        }
    }

private:
    void workerLoop(size_t thread_id) {
        // Bind to CPU if enabled
        if (bind_cpu_) {
            cpu_set_t cpuset;
            CPU_ZERO(&cpuset);
            CPU_SET(static_cast<int>(thread_id) + cpu_base_offset_, &cpuset);
            pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset);
        }

        while (true) {
            std::function<void()> task;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                cv_.wait(lock, [this, thread_id] {
                    return stop_ || !task_queues_[thread_id].empty();
                });

                if (stop_ && task_queues_[thread_id].empty()) {
                    return;
                }

                if (!task_queues_[thread_id].empty()) {
                    task = std::move(task_queues_[thread_id].front());
                    task_queues_[thread_id].pop();
                    ++active_tasks_;
                }
            }

            if (task) {
                task();
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    --active_tasks_;
                }
                done_cv_.notify_all();
            }
        }
    }

    std::vector<std::thread> workers_;
    std::unordered_map<size_t, std::queue<std::function<void()>>> task_queues_;
    std::mutex mutex_;
    std::condition_variable cv_;
    std::condition_variable done_cv_;
    std::atomic<size_t> active_tasks_{0};
    bool stop_;
    bool bind_cpu_;
    int cpu_base_offset_;
};

// ============================================================================
// Environment Variables and Helper Functions
// ============================================================================

// Environment variable name for CPU binding enable/disable
static const char* kCpuBindEnabledEnvVar = "MPCOMM_CPU_BIND_ENABLED";
// Environment variable name for CPU base offset
static const char* kCpuBaseOffsetEnvVar = "MPCOMM_CPU_BASE_OFFSET";

// Helper function to check if CPU binding is enabled
// Returns true if MPCOMM_CPU_BIND_ENABLED is set to "1" or "true" (case-insensitive)
// Default: disabled (false)
static bool isCpuBindEnabled() {
    const char* env_val = getenv(kCpuBindEnabledEnvVar);
    if (env_val == nullptr) {
        return false;  // Default: disabled
    }
    // Check for "1" or "true" (case-insensitive)
    if (strcmp(env_val, "1") == 0) {
        return true;
    }
    if (strcasecmp(env_val, "true") == 0) {
        return true;
    }
    return false;
}

// Helper function to get CPU base offset from environment variable
static int getCpuBaseOffset() {
    const char* env_val = getenv(kCpuBaseOffsetEnvVar);
    if (env_val != nullptr) {
        int offset = atoi(env_val);
        if (offset >= 0) {
            return offset;
        }
    }
    return 0;  // Default: no offset
}

// Environment variable name for NIC filtering
static const char* kNicFilterEnvVar = "MPCOMM_NIC_FILTER";
// Environment variable name for max RDMA transfer size
static const char* kMaxRdmaTransferSizeEnvVar = "MPCOMM_MAX_RDMA_TRANSFER_SIZE";
// Environment variable name for QPs per connection
static const char* kQpsPerConnectionEnvVar = "MPCOMM_QPS_PER_CONNECTION";

// Constants for QP setup
static const uint8_t kMaxHopLimit = 16;
static const uint8_t kTimeout = 14;
static const uint8_t kRetryCnt = 7;
static const int kMaxCQE = 1024;
static const int kMaxSendWR = 512;
static const int kMaxRecvWR = 128;
static const int kMaxSGE = 1;

// QP UDP source port list for multi-path ECMP load balancing
// These ports are used in round-robin fashion for each QP
#if defined(USE_BNXT) || defined(USE_MLNX)
static const uint16_t qp_port_list[] = {60000,60051,57663,57804};
static std::atomic<int> qp_port_index{0};
#endif

// TCP message types for metadata exchange
// Use high values (magic numbers) to avoid conflict with NIC counts
// NIC count is typically 1-16, so values > 0x10000000 are safe
static const uint32_t kMsgTypeBufferQuery = 0x4D504251;  // "MPBQ" in hex

// ============================================================================
// Utility Functions
// ============================================================================

std::string gidToString(const union ibv_gid &gid) {
    char buf[64];
    snprintf(buf, sizeof(buf),
             "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x:"
             "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x",
             (unsigned)gid.raw[0], (unsigned)gid.raw[1], 
             (unsigned)gid.raw[2], (unsigned)gid.raw[3],
             (unsigned)gid.raw[4], (unsigned)gid.raw[5], 
             (unsigned)gid.raw[6], (unsigned)gid.raw[7],
             (unsigned)gid.raw[8], (unsigned)gid.raw[9], 
             (unsigned)gid.raw[10], (unsigned)gid.raw[11],
             (unsigned)gid.raw[12], (unsigned)gid.raw[13], 
             (unsigned)gid.raw[14], (unsigned)gid.raw[15]);
    return std::string(buf);
}

void stringToGid(const std::string &str, union ibv_gid &gid) {
    unsigned int values[16];
    sscanf(str.c_str(),
           "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x:"
           "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x",
           &values[0], &values[1], &values[2], &values[3],
           &values[4], &values[5], &values[6], &values[7],
           &values[8], &values[9], &values[10], &values[11],
           &values[12], &values[13], &values[14], &values[15]);
    for (int i = 0; i < 16; ++i) {
        gid.raw[i] = static_cast<uint8_t>(values[i]);
    }
}

// Helper to check if GID is null
static bool isNullGid(const union ibv_gid *gid) {
    for (int i = 0; i < 16; ++i) {
        if (gid->raw[i] != 0) return false;
    }
    return true;
}

// ============================================================================
// MPComm Implementation
// ============================================================================

MPComm::MPComm()
    : tcp_port_(0),
      listen_fd_(-1),
      max_rdma_transfer_size_(MPCOMM_DEFAULT_MAX_RDMA_TRANSFER_SIZE),
      qps_per_connection_(MPCOMM_DEFAULT_QPS_PER_CONNECTION),
      accept_running_(false),
      thread_pool_size_(0),  // 0 means auto-detect based on NIC count
      initialized_(false) {
    // Read max RDMA transfer size from environment variable
    const char* env_val = std::getenv(kMaxRdmaTransferSizeEnvVar);
    if (env_val && env_val[0] != '\0') {
        char* endptr = nullptr;
        unsigned long long val = strtoull(env_val, &endptr, 10);
        if (endptr != env_val && *endptr == '\0' && val > 0) {
            max_rdma_transfer_size_ = static_cast<size_t>(val);
            printf("MPComm: Using max RDMA transfer size from %s: %zu bytes\n",
                   kMaxRdmaTransferSizeEnvVar, max_rdma_transfer_size_);
        } else {
            fprintf(stderr, "MPComm: Invalid %s value '%s', using default %zu\n",
                    kMaxRdmaTransferSizeEnvVar, env_val,
                    max_rdma_transfer_size_);
        }
    }

    // Read QPs per connection from environment variable
    env_val = std::getenv(kQpsPerConnectionEnvVar);
    if (env_val && env_val[0] != '\0') {
        char* endptr = nullptr;
        unsigned long val = strtoul(env_val, &endptr, 10);
        if (endptr != env_val && *endptr == '\0' && val > 0 && val <= 64) {
            qps_per_connection_ = static_cast<size_t>(val);
            printf("MPComm: Using QPs per connection from %s: %zu\n",
                   kQpsPerConnectionEnvVar, qps_per_connection_);
        } else {
            fprintf(stderr, "MPComm: Invalid %s value '%s' (must be 1-64), using default %zu\n",
                    kQpsPerConnectionEnvVar, env_val,
                    qps_per_connection_);
        }
    }

    // Read thread pool size from environment variable
    env_val = std::getenv(kThreadPoolSizeEnvVar);
    if (env_val && env_val[0] != '\0') {
        char* endptr = nullptr;
        unsigned long val = strtoul(env_val, &endptr, 10);
        if (endptr != env_val && *endptr == '\0' && val > 0 && val <= 128) {
            thread_pool_size_ = static_cast<size_t>(val);
            printf("MPComm: Using thread pool size from %s: %zu\n",
                   kThreadPoolSizeEnvVar, thread_pool_size_);
        } else {
            fprintf(stderr, "MPComm: Invalid %s value '%s' (must be 1-128), using auto-detect\n",
                    kThreadPoolSizeEnvVar, env_val);
        }
    }
}

MPComm::~MPComm() {
    shutdown();
}

int MPComm::init(const std::string &local_host_id,
                 const std::string &device_names,
                 int tcp_port) {
    if (initialized_) {
        fprintf(stderr, "MPComm: Already initialized\n");
        return MPCOMM_ERR_CONTEXT;
    }

    local_host_id_ = local_host_id;
    tcp_port_ = tcp_port;

    // Open RDMA devices
    int ret = openDevices(device_names);
    if (ret != 0) {
        fprintf(stderr, "MPComm: Failed to open devices\n");
        return ret;
    }

    if (nic_contexts_.empty()) {
        fprintf(stderr, "MPComm: No RDMA devices found\n");
        return MPCOMM_ERR_DEVICE;
    }

    // Setup TCP listener if port specified
    if (tcp_port > 0) {
        listen_fd_ = socket(AF_INET, SOCK_STREAM, 0);
        if (listen_fd_ < 0) {
            perror("MPComm: Failed to create socket");
            shutdown();
            return MPCOMM_ERR_CONNECTION;
        }

        int opt = 1;
        setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        struct sockaddr_in addr;
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(tcp_port);

        if (bind(listen_fd_, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
            perror("MPComm: Failed to bind");
            close(listen_fd_);
            listen_fd_ = -1;
            shutdown();
            return MPCOMM_ERR_CONNECTION;
        }

        if (listen(listen_fd_, 16) < 0) {
            perror("MPComm: Failed to listen");
            close(listen_fd_);
            listen_fd_ = -1;
            shutdown();
            return MPCOMM_ERR_CONNECTION;
        }

        // Get actual port if tcp_port was 0
        struct sockaddr_in bound_addr;
        socklen_t len = sizeof(bound_addr);
        getsockname(listen_fd_, (struct sockaddr *)&bound_addr, &len);
        tcp_port_ = ntohs(bound_addr.sin_port);
    }

    initialized_ = true;
    
    // Create thread pool
    // Default size: 2 * NIC count (for post and wait threads)
    // Can be overridden via MPCOMM_THREAD_POOL_SIZE environment variable
    size_t pool_size = thread_pool_size_;
    if (pool_size == 0) {
        pool_size = nic_contexts_.size() * 2;  // Default: 2x NIC count
    }
    
    // Get CPU binding settings
    bool bind_cpu = isCpuBindEnabled();
    int cpu_base_offset = getCpuBaseOffset();
    
    thread_pool_ = std::make_unique<ThreadPool>(pool_size, bind_cpu, cpu_base_offset);
    printf("MPComm: Created thread pool with %zu workers (cpu_bind=%s, cpu_base_offset=%d)\n",
           pool_size, bind_cpu ? "true" : "false", cpu_base_offset);
    
    // Discover NUMA topology and print results
    discoverTopology();
    printTopologyInfo();
    
    printf("MPComm: Initialized with %zu NICs, TCP port %d\n",
           nic_contexts_.size(), tcp_port_);
    
    return MPCOMM_SUCCESS;
}

void MPComm::shutdown() {
    stopAcceptThread();

    // Shutdown thread pool first (before cleaning up NIC contexts)
    if (thread_pool_) {
        thread_pool_->shutdown();
        thread_pool_.reset();
    }

    if (listen_fd_ >= 0) {
        close(listen_fd_);
        listen_fd_ = -1;
    }

    // Cleanup NIC contexts
    for (auto &ctx_ptr : nic_contexts_) {
        cleanupNicContext(*ctx_ptr);
    }
    nic_contexts_.clear();

    connections_.clear();
    initialized_ = false;
}

int MPComm::openDevices(const std::string &device_names) {
    int num_devices = 0;
    struct ibv_device **devices = ibv_get_device_list(&num_devices);
    if (!devices || num_devices <= 0) {
        fprintf(stderr, "MPComm: No RDMA devices found\n");
        return MPCOMM_ERR_DEVICE;
    }

    // Parse device filter from parameter
    std::vector<std::string> filter;
    if (!device_names.empty()) {
        std::istringstream iss(device_names);
        std::string token;
        while (std::getline(iss, token, ',')) {
            // Trim whitespace
            size_t start = token.find_first_not_of(" \t");
            size_t end = token.find_last_not_of(" \t");
            if (start != std::string::npos && end != std::string::npos) {
                filter.push_back(token.substr(start, end - start + 1));
            }
        }
    }

    // Check environment variable for additional/override filter
    const char* env_filter = std::getenv(kNicFilterEnvVar);
    if (env_filter != nullptr && strlen(env_filter) > 0) {
        // If env var is set, it takes precedence (overrides device_names if provided)
        // Clear existing filter and use env var
        filter.clear();
        std::istringstream iss(env_filter);
        std::string token;
        while (std::getline(iss, token, ',')) {
            // Trim whitespace
            size_t start = token.find_first_not_of(" \t");
            size_t end = token.find_last_not_of(" \t");
            if (start != std::string::npos && end != std::string::npos) {
                filter.push_back(token.substr(start, end - start + 1));
            }
        }
        printf("MPComm: Using NIC filter from environment variable %s: %s\n",
               kNicFilterEnvVar, env_filter);
    }

    // Log the active filter
    if (!filter.empty()) {
        printf("MPComm: NIC filter active, allowed devices: ");
        for (size_t i = 0; i < filter.size(); ++i) {
            printf("%s%s", filter[i].c_str(), (i < filter.size() - 1) ? ", " : "\n");
        }
    }

    for (int i = 0; i < num_devices; ++i) {
        const char *name = ibv_get_device_name(devices[i]);
        
        // Apply filter if specified
        if (!filter.empty()) {
            bool found = false;
            for (const auto &f : filter) {
                if (f == name) {
                    found = true;
                    break;
                }
            }
            if (!found) continue;
        }

        auto ctx = std::make_unique<NicContext>();
        ctx->device_name = name;
        ctx->context = nullptr;
        ctx->pd = nullptr;
        ctx->cq = nullptr;
        ctx->port = 1;
        ctx->gid_index = 3;  // Default to GID index 3 (RoCEv2)

        int ret = setupNicContext(name, *ctx);
        if (ret == 0) {
            printf("MPComm: Opened device %s, GID=%s\n",
                   name, gidToString(ctx->gid).c_str());
            nic_contexts_.push_back(std::move(ctx));
        }
    }

    ibv_free_device_list(devices);
    return MPCOMM_SUCCESS;
}

int MPComm::setupNicContext(const std::string &device_name, NicContext &ctx) {
    int num_devices = 0;
    struct ibv_device **devices = ibv_get_device_list(&num_devices);
    if (!devices) return MPCOMM_ERR_DEVICE;

    struct ibv_device *target_device = nullptr;
    for (int i = 0; i < num_devices; ++i) {
        if (device_name == ibv_get_device_name(devices[i])) {
            target_device = devices[i];
            break;
        }
    }

    if (!target_device) {
        ibv_free_device_list(devices);
        return MPCOMM_ERR_DEVICE;
    }

    // Open device
    ctx.context = ibv_open_device(target_device);
    ibv_free_device_list(devices);
    
    if (!ctx.context) {
        fprintf(stderr, "MPComm: Failed to open device %s\n",
                device_name.c_str());
        return MPCOMM_ERR_CONTEXT;
    }

    // Query port
    struct ibv_port_attr port_attr;
    if (ibv_query_port(ctx.context, ctx.port, &port_attr) != 0) {
        fprintf(stderr, "MPComm: Failed to query port on %s\n",
                device_name.c_str());
        ibv_close_device(ctx.context);
        ctx.context = nullptr;
        return MPCOMM_ERR_CONTEXT;
    }

    if (port_attr.state != IBV_PORT_ACTIVE) {
        fprintf(stderr, "MPComm: Port not active on %s\n",
                device_name.c_str());
        ibv_close_device(ctx.context);
        ctx.context = nullptr;
        return MPCOMM_ERR_CONTEXT;
    }

    ctx.lid = port_attr.lid;

    // Find best GID index (prefer RoCEv2 with network device)
    if (ctx.gid_index < 0) {
        for (int i = 0; i < port_attr.gid_tbl_len; ++i) {
            union ibv_gid gid;
            if (ibv_query_gid(ctx.context, ctx.port, i, &gid) != 0) continue;
            if (isNullGid(&gid)) continue;
            
            ctx.gid_index = i;
            ctx.gid = gid;
            break;
        }
    } else {
        if (ibv_query_gid(ctx.context, ctx.port, ctx.gid_index, &ctx.gid) != 0) {
            fprintf(stderr, "MPComm: Failed to query GID on %s\n",
                    device_name.c_str());
            ibv_close_device(ctx.context);
            ctx.context = nullptr;
            return MPCOMM_ERR_CONTEXT;
        }
    }

    if (ctx.gid_index < 0) {
        fprintf(stderr, "MPComm: No valid GID found on %s\n",
                device_name.c_str());
        ibv_close_device(ctx.context);
        ctx.context = nullptr;
        return MPCOMM_ERR_CONTEXT;
    }

    // Allocate PD
    ctx.pd = ibv_alloc_pd(ctx.context);
    if (!ctx.pd) {
        fprintf(stderr, "MPComm: Failed to allocate PD on %s\n",
                device_name.c_str());
        ibv_close_device(ctx.context);
        ctx.context = nullptr;
        return MPCOMM_ERR_CONTEXT;
    }

    // Create CQ
    ctx.cq = ibv_create_cq(ctx.context, kMaxCQE, nullptr, nullptr, 0);
    if (!ctx.cq) {
        fprintf(stderr, "MPComm: Failed to create CQ on %s\n",
                device_name.c_str());
        ibv_dealloc_pd(ctx.pd);
        ctx.pd = nullptr;
        ibv_close_device(ctx.context);
        ctx.context = nullptr;
        return MPCOMM_ERR_CONTEXT;
    }

    return MPCOMM_SUCCESS;
}

void MPComm::cleanupNicContext(NicContext &ctx) {
    // Destroy QPs
    {
        std::lock_guard<std::mutex> lock(ctx.qp_mutex);
        for (auto &kv : ctx.qp_map) {
            for (auto *qp : kv.second) {
                if (qp) {
                    ibv_destroy_qp(qp);
                }
            }
        }
        ctx.qp_map.clear();
    }

    // Deregister memory regions
    {
        std::lock_guard<std::mutex> lock(ctx.mr_mutex);
        for (auto &mr_info : ctx.memory_regions) {
            if (mr_info.mr) {
                ibv_dereg_mr(mr_info.mr);
            }
        }
        ctx.memory_regions.clear();
    }

    if (ctx.cq) {
        ibv_destroy_cq(ctx.cq);
        ctx.cq = nullptr;
    }

    if (ctx.pd) {
        ibv_dealloc_pd(ctx.pd);
        ctx.pd = nullptr;
    }

    if (ctx.context) {
        ibv_close_device(ctx.context);
        ctx.context = nullptr;
    }
}

int MPComm::registerMemory(void *addr, size_t length) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    if (!addr || length == 0) return MPCOMM_ERR_INVALID_ARG;

    int access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_READ |
                       IBV_ACCESS_REMOTE_WRITE;

    // Detect NUMA node for this memory region using move_pages()
    int numa_node = -1;
    int status = -1;
    void* pages[1] = { addr };
    if (move_pages(0, 1, pages, nullptr, &status, 0) == 0 && status >= 0) {
        numa_node = status;
    }

    // Register on all NICs
    for (size_t i = 0; i < nic_contexts_.size(); ++i) {
        auto &ctx = *nic_contexts_[i];
        
        struct ibv_mr *mr = ibv_reg_mr(ctx.pd, addr, length, access_flags);
        if (!mr) {
            fprintf(stderr, "MPComm: Failed to register memory on %s\n",
                    ctx.device_name.c_str());
            // Unregister from previous NICs
            for (size_t j = 0; j < i; ++j) {
                auto &prev_ctx = *nic_contexts_[j];
                std::lock_guard<std::mutex> lock(prev_ctx.mr_mutex);
                for (auto it = prev_ctx.memory_regions.begin();
                     it != prev_ctx.memory_regions.end(); ++it) {
                    if (it->addr == addr) {
                        ibv_dereg_mr(it->mr);
                        prev_ctx.memory_regions.erase(it);
                        break;
                    }
                }
            }
            return MPCOMM_ERR_MEMORY;
        }

        MemoryRegionInfo info;
        info.addr = addr;
        info.length = length;
        info.mr = mr;
        info.lkey = mr->lkey;
        info.rkey = mr->rkey;
        info.numa_node = numa_node;

        std::lock_guard<std::mutex> lock(ctx.mr_mutex);
        ctx.memory_regions.push_back(info);
    }

    printf("MPComm: Registered memory %p, length %zu, NUMA node %d\n", addr, length, numa_node);
    return MPCOMM_SUCCESS;
}

int MPComm::unregisterMemory(void *addr) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    if (!addr) return MPCOMM_ERR_INVALID_ARG;

    for (auto &ctx_ptr : nic_contexts_) {
        auto &ctx = *ctx_ptr;
        std::lock_guard<std::mutex> lock(ctx.mr_mutex);
        for (auto it = ctx.memory_regions.begin();
             it != ctx.memory_regions.end(); ++it) {
            if (it->addr == addr) {
                ibv_dereg_mr(it->mr);
                ctx.memory_regions.erase(it);
                break;
            }
        }
    }

    return MPCOMM_SUCCESS;
}

uint32_t MPComm::getLkey(size_t nic_index, void *addr) const {
    if (nic_index >= nic_contexts_.size()) return 0;

    const auto &ctx = *nic_contexts_[nic_index];
    // Note: We can't lock here in const method, assume read-only after init
    
    for (const auto &mr_info : ctx.memory_regions) {
        char *mr_start = static_cast<char *>(mr_info.addr);
        char *mr_end = mr_start + mr_info.length;
        char *target = static_cast<char *>(addr);
        
        if (target >= mr_start && target < mr_end) {
            return mr_info.lkey;
        }
    }
    
    return 0;
}

uint32_t MPComm::getRkey(size_t nic_index, void *addr) const {
    if (nic_index >= nic_contexts_.size()) return 0;

    const auto &ctx = *nic_contexts_[nic_index];
    
    for (const auto &mr_info : ctx.memory_regions) {
        char *mr_start = static_cast<char *>(mr_info.addr);
        char *mr_end = mr_start + mr_info.length;
        char *target = static_cast<char *>(addr);
        
        if (target >= mr_start && target < mr_end) {
            return mr_info.rkey;
        }
    }
    
    return 0;
}

int MPComm::updateRemoteMemoryInfo(const std::string &remote_host_id,
                                   const std::vector<uint32_t> &rkeys) {
    std::lock_guard<std::mutex> lock(connections_mutex_);
    
    auto it = connections_.find(remote_host_id);
    if (it == connections_.end()) {
        fprintf(stderr, "MPComm: Host %s not connected\n", remote_host_id.c_str());
        return MPCOMM_ERR_CONNECTION;
    }

    size_t count = std::min(rkeys.size(), it->second.nic_endpoints.size());
    for (size_t i = 0; i < count; ++i) {
        it->second.nic_endpoints[i].rkey = rkeys[i];
    }

    printf("MPComm: Updated rkeys for %s\n", remote_host_id.c_str());
    return MPCOMM_SUCCESS;
}

std::string MPComm::getGid(size_t nic_index) const {
    if (nic_index >= nic_contexts_.size()) return "";
    return gidToString(nic_contexts_[nic_index]->gid);
}

std::string MPComm::getDeviceName(size_t nic_index) const {
    if (nic_index >= nic_contexts_.size()) return "";
    return nic_contexts_[nic_index]->device_name;
}

std::vector<std::string> MPComm::getActiveDevices() const {
    std::vector<std::string> devices;
    devices.reserve(nic_contexts_.size());
    for (const auto &ctx : nic_contexts_) {
        devices.push_back(ctx->device_name);
    }
    return devices;
}

const char* MPComm::getNicFilterEnvVarName() {
    return kNicFilterEnvVar;
}

const char* MPComm::getMaxRdmaTransferSizeEnvVarName() {
    return kMaxRdmaTransferSizeEnvVar;
}

size_t MPComm::getMaxRdmaTransferSize() const {
    return max_rdma_transfer_size_;
}

const char* MPComm::getQpsPerConnectionEnvVarName() {
    return kQpsPerConnectionEnvVar;
}

size_t MPComm::getQpsPerConnection() const {
    return qps_per_connection_;
}

// Global helper function for header - max RDMA transfer size
size_t getMaxRdmaTransferSize() {
    const char* env_val = std::getenv(kMaxRdmaTransferSizeEnvVar);
    if (env_val && env_val[0] != '\0') {
        char* endptr = nullptr;
        unsigned long long val = strtoull(env_val, &endptr, 10);
        if (endptr != env_val && *endptr == '\0' && val > 0) {
            return static_cast<size_t>(val);
        }
    }
    return MPCOMM_DEFAULT_MAX_RDMA_TRANSFER_SIZE;
}

// Global helper function for header - QPs per connection
size_t getQpsPerConnection() {
    const char* env_val = std::getenv(kQpsPerConnectionEnvVar);
    if (env_val && env_val[0] != '\0') {
        char* endptr = nullptr;
        unsigned long val = strtoul(env_val, &endptr, 10);
        if (endptr != env_val && *endptr == '\0' && val > 0 && val <= 64) {
            return static_cast<size_t>(val);
        }
    }
    return MPCOMM_DEFAULT_QPS_PER_CONNECTION;
}

// ============================================================================
// NUMA Topology Discovery
// ============================================================================

// Extract trailing numeric suffix from NIC name (e.g., "mlx5_bond_0" -> 0, "mlx5_2" -> 2)
// Returns -1 if no numeric suffix found
static int extractNicSuffix(const std::string& nic_name) {
    if (nic_name.empty()) return -1;
    
    // Find the last sequence of digits
    size_t end = nic_name.length();
    size_t start = end;
    
    // Scan backwards to find digits
    while (start > 0 && std::isdigit(nic_name[start - 1])) {
        --start;
    }
    
    if (start == end) {
        return -1;  // No digits found
    }
    
    // Extract the number
    std::string num_str = nic_name.substr(start, end - start);
    return std::stoi(num_str);
}

// Get the number of NUMA nodes in the system
int MPComm::getNumaNodeCount() {
    int count = 0;
    for (int i = 0; i < 256; i++) {
        std::string path = "/sys/devices/system/node/node" + std::to_string(i);
        if (access(path.c_str(), F_OK) == 0) {
            count = i + 1;
        } else {
            break;
        }
    }
    return std::max(1, count);
}

// Read the NUMA node of a NIC from sysfs
int MPComm::readNicNumaNode(const std::string& nic_name) {
    std::string path = "/sys/class/infiniband/" + nic_name + "/device/numa_node";
    std::ifstream file(path);
    if (file.is_open()) {
        int numa_node;
        file >> numa_node;
        return numa_node;  // May return -1 if unknown
    }
    return -1;  // Failed to read
}

// Get candidate NICs (either from MPCOMM_NIC_FILTER or all available)
std::vector<std::string> MPComm::getCandidateNics() {
    std::vector<std::string> candidates;
    
    // Check MPCOMM_NIC_FILTER environment variable
    const char* filter = std::getenv(kNicFilterEnvVar);
    if (filter && strlen(filter) > 0) {
        // Parse comma-separated list
        std::istringstream iss(filter);
        std::string token;
        while (std::getline(iss, token, ',')) {
            // Trim whitespace
            size_t start = token.find_first_not_of(" \t");
            size_t end = token.find_last_not_of(" \t");
            if (start != std::string::npos && end != std::string::npos) {
                candidates.push_back(token.substr(start, end - start + 1));
            }
        }
    } else {
        // Get all available RDMA NICs
        int num_devices = 0;
        struct ibv_device **devices = ibv_get_device_list(&num_devices);
        if (devices) {
            for (int i = 0; i < num_devices; i++) {
                candidates.push_back(ibv_get_device_name(devices[i]));
            }
            ibv_free_device_list(devices);
        }
    }
    return candidates;
}

// Discover NUMA topology and build NIC-to-NUMA mappings
void MPComm::discoverTopology() {
    int numa_count = getNumaNodeCount();
    std::vector<std::string> candidates = getCandidateNics();
    
    // Initialize NUMA topology for each node
    numa_topology_.resize(numa_count);
    for (int i = 0; i < numa_count; i++) {
        numa_topology_[i].numa_node = i;
    }
    
    // Build NIC topology info and assign NICs to NUMA nodes
    nic_topology_.clear();
    nic_topology_.reserve(candidates.size());
    
    for (const auto& nic : candidates) {
        int numa_node = readNicNumaNode(nic);
        
        // Store NIC topology info
        NicTopologyInfo info;
        info.nic_name = nic;
        info.numa_node = numa_node;
        nic_topology_.push_back(info);
        
        // Assign NIC to appropriate NUMA node
        if (numa_node >= 0 && numa_node < numa_count) {
            // NIC is local to this NUMA node
            numa_topology_[numa_node].local_nics.push_back(nic);
        } else {
            // NUMA node unknown (-1), add to all NUMA nodes as remote
            for (int i = 0; i < numa_count; i++) {
                numa_topology_[i].remote_nics.push_back(nic);
            }
        }
    }
    
    // For NUMA nodes without local NICs, populate remote_nics as fallback
    for (int i = 0; i < numa_count; i++) {
        if (numa_topology_[i].local_nics.empty()) {
            // No local NICs, add all NICs from other NUMA nodes as remote
            for (const auto& info : nic_topology_) {
                if (info.numa_node != i && info.numa_node >= 0) {
                    numa_topology_[i].remote_nics.push_back(info.nic_name);
                }
            }
        }
    }
}

// Print topology discovery results
void MPComm::printTopologyInfo() {
    printf("\n================== MPCOMM Topology Discovery ==================\n");
    printf("System: %zu NUMA nodes, %zu candidate NICs\n", 
           numa_topology_.size(), nic_topology_.size());
    
    // Print NIC Filter setting
    const char* filter = std::getenv(kNicFilterEnvVar);
    if (filter && strlen(filter) > 0) {
        printf("NIC Filter: %s\n", filter);
    } else {
        printf("NIC Filter: (none, using all available NICs)\n");
    }
    printf("\n");
    
    // Print NUMA topology
    for (const auto& topo : numa_topology_) {
        printf("NUMA Node %d:\n", topo.numa_node);
        
        if (!topo.local_nics.empty()) {
            printf("  Local NICs (optimal): ");
            for (size_t i = 0; i < topo.local_nics.size(); i++) {
                printf("%s%s", topo.local_nics[i].c_str(), 
                       (i < topo.local_nics.size() - 1) ? ", " : "");
            }
            printf(" (%zu NICs)\n", topo.local_nics.size());
        } else {
            printf("  Local NICs: (none)\n");
        }
        
        if (!topo.remote_nics.empty() && topo.local_nics.empty()) {
            printf("  Fallback NICs (cross-NUMA): ");
            for (size_t i = 0; i < topo.remote_nics.size(); i++) {
                printf("%s%s", topo.remote_nics[i].c_str(),
                       (i < topo.remote_nics.size() - 1) ? ", " : "");
            }
            printf("\n");
        }
        printf("\n");
    }
    
    // Print NIC-to-NUMA mapping
    printf("NIC -> NUMA Mapping:\n");
    for (const auto& info : nic_topology_) {
        if (info.numa_node >= 0) {
            printf("  %s -> NUMA %d\n", info.nic_name.c_str(), info.numa_node);
        } else {
            printf("  %s -> NUMA unknown\n", info.nic_name.c_str());
        }
    }
    printf("================================================================\n\n");
}

// Get NUMA topology information
const std::vector<NumaTopology>& MPComm::getNumaTopology() const {
    return numa_topology_;
}

// Get NIC topology information
const std::vector<NicTopologyInfo>& MPComm::getNicTopology() const {
    return nic_topology_;
}

// Get the NUMA node for a specific NIC
int MPComm::getNicNumaNode(const std::string& nic_name) const {
    for (const auto& info : nic_topology_) {
        if (info.nic_name == nic_name) {
            return info.numa_node;
        }
    }
    return -1;
}

// Get local NICs for a specific NUMA node
std::vector<std::string> MPComm::getLocalNicsForNuma(int numa_node) const {
    if (numa_node >= 0 && static_cast<size_t>(numa_node) < numa_topology_.size()) {
        return numa_topology_[numa_node].local_nics;
    }
    return {};
}

// Get NUMA node for a given memory address (check registered memory regions)
int MPComm::getNumaNodeForAddr(void* addr) const {
    if (!addr || nic_contexts_.empty()) return -1;
    
    uintptr_t target = reinterpret_cast<uintptr_t>(addr);
    
    // Check the first NIC's memory regions (all NICs share the same regions)
    const auto& ctx = *nic_contexts_[0];
    for (const auto& mr : ctx.memory_regions) {
        uintptr_t start = reinterpret_cast<uintptr_t>(mr.addr);
        uintptr_t end = start + mr.length;
        if (target >= start && target < end) {
            return mr.numa_node;
        }
    }
    return -1;  // Not found in registered regions
}

// Get local NIC indices for a specific NUMA node
std::vector<size_t> MPComm::getLocalNicIndicesForNuma(int numa_node) const {
    std::vector<size_t> indices;
    
    // If numa_node is invalid, return empty (will fallback to all NICs)
    if (numa_node < 0) {
        return indices;
    }
    
    // Find NIC indices that belong to this NUMA node
    for (size_t i = 0; i < nic_contexts_.size(); ++i) {
        const auto& device_name = nic_contexts_[i]->device_name;
        for (const auto& topo : nic_topology_) {
            if (topo.nic_name == device_name && topo.numa_node == numa_node) {
                indices.push_back(i);
                break;
            }
        }
    }
    
    return indices;
}

// Get remote NIC indices for a specific remote NUMA node
std::vector<size_t> MPComm::getRemoteNicIndicesForNuma(const std::string& remote_host_id,
                                                       int remote_numa_node) const {
    std::vector<size_t> indices;
    
    std::lock_guard<std::mutex> lock(connections_mutex_);
    auto it = connections_.find(remote_host_id);
    if (it == connections_.end()) {
        return indices;  // Host not found
    }
    
    const auto& conn = it->second;
    if (remote_numa_node < 0) {
        return indices;  // Invalid NUMA node
    }
    
    // Find remote NIC indices that belong to the specified NUMA node
    for (size_t i = 0; i < conn.remote_nic_numa_nodes.size(); ++i) {
        if (conn.remote_nic_numa_nodes[i] == remote_numa_node) {
            indices.push_back(i);
        }
    }
    
    return indices;
}

// Get NUMA node for a specific remote NIC
int MPComm::getRemoteNicNumaNode(const std::string& remote_host_id, size_t nic_index) const {
    std::lock_guard<std::mutex> lock(connections_mutex_);
    auto it = connections_.find(remote_host_id);
    if (it == connections_.end()) {
        return -1;  // Host not found
    }
    
    const auto& conn = it->second;
    if (nic_index >= conn.remote_nic_numa_nodes.size()) {
        return -1;  // Invalid NIC index
    }
    
    return conn.remote_nic_numa_nodes[nic_index];
}

// ============================================================================
// Buffer Publishing and Query (Multi-buffer with NUMA support)
// ============================================================================

int MPComm::publishBuffer(void *addr, size_t length, int numa_node) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    if (!addr || length == 0) return MPCOMM_ERR_INVALID_ARG;

    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    // Create published buffer info if not exists
    if (!published_buffer_) {
        published_buffer_ = std::make_unique<PublishedBufferInfo>();
    }
    
    // Check if buffer already published (update if so)
    uint64_t buf_addr = reinterpret_cast<uint64_t>(addr);
    for (auto &entry : published_buffer_->buffers) {
        if (entry.addr == buf_addr) {
            // Update existing entry
            entry.length = length;
            entry.numa_node = (numa_node >= 0) ? numa_node : getNumaNodeForAddr(addr);
            printf("MPComm: Updated published buffer addr=%p, length=%zu, numa=%d\n",
                   addr, length, entry.numa_node);
            return MPCOMM_SUCCESS;
        }
    }
    
    // Create new buffer entry
    PublishedBufferEntry entry;
    entry.addr = buf_addr;
    entry.length = length;
    entry.numa_node = (numa_node >= 0) ? numa_node : getNumaNodeForAddr(addr);
    
    // Get rkeys for all NICs
    entry.rkeys.reserve(nic_contexts_.size());
    for (size_t i = 0; i < nic_contexts_.size(); ++i) {
        uint32_t rkey = getRkey(i, addr);
        if (rkey == 0) {
            fprintf(stderr, "MPComm: Buffer not registered on NIC %zu\n", i);
            return MPCOMM_ERR_MEMORY;
        }
        entry.rkeys.push_back(rkey);
    }
    
    published_buffer_->buffers.push_back(std::move(entry));
    
    const auto &added = published_buffer_->buffers.back();
    printf("MPComm: Published buffer addr=%p, length=%zu, numa=%d, rkeys=[",
           addr, length, added.numa_node);
    for (size_t i = 0; i < added.rkeys.size(); ++i) {
        printf("%u%s", added.rkeys[i],
               i < added.rkeys.size() - 1 ? "," : "");
    }
    printf("] (total %zu buffers)\n", published_buffer_->buffers.size());
    
    return MPCOMM_SUCCESS;
}

int MPComm::unpublishBuffer(void *addr) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    
    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    if (!published_buffer_) {
        return MPCOMM_ERR_INVALID_ARG;
    }
    
    uint64_t buf_addr = reinterpret_cast<uint64_t>(addr);
    auto &buffers = published_buffer_->buffers;
    
    for (auto it = buffers.begin(); it != buffers.end(); ++it) {
        if (it->addr == buf_addr) {
            buffers.erase(it);
            printf("MPComm: Unpublished buffer addr=%p (remaining %zu buffers)\n",
                   addr, buffers.size());
            return MPCOMM_SUCCESS;
        }
    }
    
    return MPCOMM_ERR_INVALID_ARG;
}

void MPComm::unpublishAllBuffers() {
    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    if (published_buffer_) {
        size_t count = published_buffer_->buffers.size();
        published_buffer_->buffers.clear();
        printf("MPComm: Unpublished all %zu buffers\n", count);
    }
}

size_t MPComm::getPublishedBufferCount() const {
    // Note: Not fully thread-safe, but adequate for informational purposes
    if (!published_buffer_) return 0;
    return published_buffer_->buffers.size();
}

int MPComm::queryRemoteBuffer(const std::string &remote_host_id,
                              const std::string &remote_tcp_addr,
                              int remote_tcp_port,
                              RemoteBufferInfo &out_info) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;

    printf("MPComm: Querying buffers from %s at %s:%d\n",
           remote_host_id.c_str(), remote_tcp_addr.c_str(), remote_tcp_port);

    // Create TCP connection
    int sock_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (sock_fd < 0) {
        perror("MPComm: Failed to create socket");
        return MPCOMM_ERR_CONNECTION;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(remote_tcp_port);
    
    if (inet_pton(AF_INET, remote_tcp_addr.c_str(), &addr.sin_addr) <= 0) {
        struct hostent *he = gethostbyname(remote_tcp_addr.c_str());
        if (!he) {
            fprintf(stderr, "MPComm: Failed to resolve %s\n",
                    remote_tcp_addr.c_str());
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        memcpy(&addr.sin_addr, he->h_addr, he->h_length);
    }

    if (::connect(sock_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("MPComm: Failed to connect for buffer query");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    int flag = 1;
    setsockopt(sock_fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

    // Send message type: buffer query
    uint32_t msg_type = kMsgTypeBufferQuery;
    if (send(sock_fd, &msg_type, sizeof(msg_type), 0) != sizeof(msg_type)) {
        perror("MPComm: Failed to send message type");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive response: number of buffers (0 = no published buffers)
    uint32_t num_buffers;
    if (recv(sock_fd, &num_buffers, sizeof(num_buffers), MSG_WAITALL) != sizeof(num_buffers)) {
        perror("MPComm: Failed to receive buffer count");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    if (num_buffers == 0) {
        fprintf(stderr, "MPComm: Remote host has no published buffers\n");
        close(sock_fd);
        return MPCOMM_ERR_INVALID_ARG;
    }

    printf("MPComm: Remote has %u published buffer(s)\n", num_buffers);

    // Receive number of NICs (same for all buffers)
    uint32_t num_nics;
    if (recv(sock_fd, &num_nics, sizeof(num_nics), MSG_WAITALL) != sizeof(num_nics)) {
        perror("MPComm: Failed to receive num_nics");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive GIDs for NIC matching (once, same for all buffers)
    std::vector<std::string> remote_gids(num_nics);
    for (uint32_t i = 0; i < num_nics; ++i) {
        char gid_buf[64];
        if (recv(sock_fd, gid_buf, sizeof(gid_buf), MSG_WAITALL) != sizeof(gid_buf)) {
            perror("MPComm: Failed to receive GID");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        remote_gids[i] = std::string(gid_buf);
    }

    // Receive each buffer's info
    out_info.host_id = remote_host_id;
    out_info.buffers.clear();
    out_info.buffers.reserve(num_buffers);

    for (uint32_t buf_idx = 0; buf_idx < num_buffers; ++buf_idx) {
        RemoteBufferEntry entry;

        // Receive buffer address
        if (recv(sock_fd, &entry.addr, sizeof(entry.addr), MSG_WAITALL) != sizeof(entry.addr)) {
            perror("MPComm: Failed to receive buffer address");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }

        // Receive buffer length
        if (recv(sock_fd, &entry.length, sizeof(entry.length), MSG_WAITALL) != sizeof(entry.length)) {
            perror("MPComm: Failed to receive buffer length");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }

        // Receive NUMA node
        int32_t numa_node;
        if (recv(sock_fd, &numa_node, sizeof(numa_node), MSG_WAITALL) != sizeof(numa_node)) {
            perror("MPComm: Failed to receive NUMA node");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        entry.numa_node = numa_node;

        // Receive rkeys for each NIC
        entry.rkeys.resize(num_nics);
        for (uint32_t nic_idx = 0; nic_idx < num_nics; ++nic_idx) {
            uint32_t rkey;
            if (recv(sock_fd, &rkey, sizeof(rkey), MSG_WAITALL) != sizeof(rkey)) {
                perror("MPComm: Failed to receive rkey");
                close(sock_fd);
                return MPCOMM_ERR_CONNECTION;
            }
            entry.rkeys[nic_idx] = rkey;
        }

        printf("MPComm: Buffer %u: addr=0x%lx, length=%lu, numa=%d, rkeys=[",
               buf_idx, entry.addr, entry.length, entry.numa_node);
        for (size_t i = 0; i < entry.rkeys.size(); ++i) {
            printf("%u%s", entry.rkeys[i], i < entry.rkeys.size() - 1 ? "," : "");
        }
        printf("]\n");

        out_info.buffers.push_back(std::move(entry));
    }

    close(sock_fd);

    // Match rkeys to connection endpoints by GID (use first buffer's rkeys for connection)
    // Also store all buffers in remote_buffers for multi-NUMA parallel access
    if (!out_info.buffers.empty()) {
        std::lock_guard<std::mutex> lock(connections_mutex_);
        auto conn_it = connections_.find(remote_host_id);
        if (conn_it != connections_.end()) {
            printf("MPComm: Matching rkeys for %zu endpoints\n", 
                   conn_it->second.nic_endpoints.size());
            
            // Store all remote buffers for multi-NUMA parallel access
            conn_it->second.remote_buffers.clear();
            for (const auto &buf : out_info.buffers) {
                // Map GID to local NIC index to get correct rkey order
                RemoteBufferEntry reordered_entry;
                reordered_entry.addr = buf.addr;
                reordered_entry.length = buf.length;
                reordered_entry.numa_node = buf.numa_node;
                reordered_entry.rkeys.resize(conn_it->second.nic_endpoints.size());
                
                // Reorder rkeys to match local NIC endpoint indices
                for (size_t ep_idx = 0; ep_idx < conn_it->second.nic_endpoints.size(); ++ep_idx) {
                    const std::string &ep_gid = conn_it->second.nic_endpoints[ep_idx].gid;
                    for (uint32_t remote_idx = 0; remote_idx < num_nics; ++remote_idx) {
                        if (remote_gids[remote_idx] == ep_gid) {
                            reordered_entry.rkeys[ep_idx] = buf.rkeys[remote_idx];
                            break;
                        }
                    }
                }
                
                conn_it->second.remote_buffers[buf.addr] = reordered_entry;
                printf("MPComm: Stored remote buffer: addr=0x%lx, numa=%d, rkeys=[",
                       buf.addr, buf.numa_node);
                for (size_t i = 0; i < reordered_entry.rkeys.size(); ++i) {
                    printf("%u%s", reordered_entry.rkeys[i], 
                           i < reordered_entry.rkeys.size() - 1 ? "," : "");
                }
                printf("]\n");
            }
            
            // Also update nic_endpoints with first buffer's rkeys for backward compatibility
            const auto &first_buf = out_info.buffers[0];
            for (size_t ep_idx = 0; ep_idx < conn_it->second.nic_endpoints.size(); ++ep_idx) {
                const std::string &ep_gid = conn_it->second.nic_endpoints[ep_idx].gid;
                bool matched = false;
                for (uint32_t remote_idx = 0; remote_idx < num_nics; ++remote_idx) {
                    if (remote_gids[remote_idx] == ep_gid) {
                        conn_it->second.nic_endpoints[ep_idx].rkey = first_buf.rkeys[remote_idx];
                        printf("MPComm: Matched endpoint %zu (GID=%s) -> rkey=%u\n",
                               ep_idx, ep_gid.c_str(), first_buf.rkeys[remote_idx]);
                        matched = true;
                        break;
                    }
                }
                if (!matched) {
                    printf("MPComm: WARNING: No matching GID found for endpoint %zu\n", ep_idx);
                }
            }
        }
    }

    printf("MPComm: Received %zu buffer(s) from %s\n",
           out_info.buffers.size(), remote_host_id.c_str());

    return MPCOMM_SUCCESS;
}

int MPComm::queryRemoteBufferByNuma(const std::string &remote_host_id,
                                    const std::string &remote_tcp_addr,
                                    int remote_tcp_port,
                                    int numa_node,
                                    RemoteBufferEntry &out_entry) {
    RemoteBufferInfo all_buffers;
    int ret = queryRemoteBuffer(remote_host_id, remote_tcp_addr, remote_tcp_port, all_buffers);
    if (ret != MPCOMM_SUCCESS) {
        return ret;
    }

    if (all_buffers.buffers.empty()) {
        return MPCOMM_ERR_INVALID_ARG;
    }

    // If numa_node < 0, return first buffer
    if (numa_node < 0) {
        out_entry = all_buffers.buffers[0];
        return MPCOMM_SUCCESS;
    }

    // Find buffer matching NUMA node
    for (const auto &buf : all_buffers.buffers) {
        if (buf.numa_node == numa_node) {
            out_entry = buf;
            return MPCOMM_SUCCESS;
        }
    }

    // Not found, return first buffer as fallback
    fprintf(stderr, "MPComm: No buffer found for NUMA node %d, using first buffer\n", numa_node);
    out_entry = all_buffers.buffers[0];
    return MPCOMM_SUCCESS;
}

const PublishedBufferInfo* MPComm::getPublishedBufferInfo() const {
    // Note: This is not thread-safe for simplicity
    return published_buffer_.get();
}

void MPComm::handleBufferQuery(int client_fd) {
    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    // Check if any buffers are published
    uint32_t num_buffers = 0;
    if (published_buffer_) {
        num_buffers = static_cast<uint32_t>(published_buffer_->buffers.size());
    }

    // Send number of buffers (0 = no published buffers)
    if (send(client_fd, &num_buffers, sizeof(num_buffers), 0) != sizeof(num_buffers)) {
        perror("MPComm: Failed to send buffer count");
        return;
    }

    if (num_buffers == 0) {
        return;
    }

    // Send number of NICs (same for all buffers)
    uint32_t num_nics = static_cast<uint32_t>(nic_contexts_.size());
    if (send(client_fd, &num_nics, sizeof(num_nics), 0) != sizeof(num_nics)) {
        perror("MPComm: Failed to send num_nics");
        return;
    }

    // Send GIDs for all NICs (once, for NIC matching)
    for (uint32_t i = 0; i < num_nics; ++i) {
        std::string gid_str = gidToString(nic_contexts_[i]->gid);
        char gid_buf[64];
        memset(gid_buf, 0, sizeof(gid_buf));
        strncpy(gid_buf, gid_str.c_str(), sizeof(gid_buf) - 1);
        if (send(client_fd, gid_buf, sizeof(gid_buf), 0) != sizeof(gid_buf)) {
            perror("MPComm: Failed to send GID");
            return;
        }
    }

    // Send each buffer's info
    for (uint32_t buf_idx = 0; buf_idx < num_buffers; ++buf_idx) {
        const auto &entry = published_buffer_->buffers[buf_idx];

        // Send buffer address
        if (send(client_fd, &entry.addr, sizeof(entry.addr), 0) != sizeof(entry.addr)) {
            perror("MPComm: Failed to send buffer address");
            return;
        }

        // Send buffer length
        if (send(client_fd, &entry.length, sizeof(entry.length), 0) != sizeof(entry.length)) {
            perror("MPComm: Failed to send buffer length");
            return;
        }

        // Send NUMA node
        int32_t numa_node = entry.numa_node;
        if (send(client_fd, &numa_node, sizeof(numa_node), 0) != sizeof(numa_node)) {
            perror("MPComm: Failed to send NUMA node");
            return;
        }

        // Send rkeys for each NIC
        for (uint32_t nic_idx = 0; nic_idx < num_nics; ++nic_idx) {
            uint32_t rkey = entry.rkeys[nic_idx];
            if (send(client_fd, &rkey, sizeof(rkey), 0) != sizeof(rkey)) {
                perror("MPComm: Failed to send rkey");
                return;
            }
        }

        printf("MPComm: Sent buffer %u: addr=0x%lx, length=%lu, numa=%d\n",
               buf_idx, entry.addr, entry.length, entry.numa_node);
    }

    printf("MPComm: Sent %u buffer(s) to client\n", num_buffers);
}

// ============================================================================
// QP Management
// ============================================================================

int MPComm::createQP(NicContext &ctx, struct ibv_qp **qp) {
    struct ibv_qp_init_attr init_attr;
    memset(&init_attr, 0, sizeof(init_attr));
    
    init_attr.send_cq = ctx.cq;
    init_attr.recv_cq = ctx.cq;
    init_attr.qp_type = IBV_QPT_RC;
    init_attr.sq_sig_all = 0;
    init_attr.cap.max_send_wr = kMaxSendWR;
    init_attr.cap.max_recv_wr = kMaxRecvWR;
    init_attr.cap.max_send_sge = kMaxSGE;
    init_attr.cap.max_recv_sge = kMaxSGE;

    *qp = ibv_create_qp(ctx.pd, &init_attr);
    if (!*qp) {
        perror("MPComm: Failed to create QP");
        return MPCOMM_ERR_CONTEXT;
    }

    return MPCOMM_SUCCESS;
}

int MPComm::modifyQPToInit(NicContext &ctx, struct ibv_qp *qp) {
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    
    attr.qp_state = IBV_QPS_INIT;
    attr.port_num = ctx.port;
    attr.pkey_index = 0;
    attr.qp_access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_READ |
                           IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_ATOMIC;

    int flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT |
                IBV_QP_ACCESS_FLAGS;
    
    if (ibv_modify_qp(qp, &attr, flags) != 0) {
        perror("MPComm: Failed to modify QP to INIT");
        return MPCOMM_ERR_CONNECTION;
    }

    return MPCOMM_SUCCESS;
}

int MPComm::modifyQPToRTR(NicContext &ctx, struct ibv_qp *qp,
                          const RemoteEndpointInfo &remote) {
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    
    attr.qp_state = IBV_QPS_RTR;
    attr.path_mtu = IBV_MTU_4096;
    attr.dest_qp_num = remote.qp_num;
    attr.rq_psn = 0;
    attr.max_dest_rd_atomic = 16;
    attr.min_rnr_timer = 12;

    // Parse remote GID
    stringToGid(remote.gid, attr.ah_attr.grh.dgid);
    attr.ah_attr.grh.sgid_index = ctx.gid_index;
    attr.ah_attr.grh.hop_limit = kMaxHopLimit;
    attr.ah_attr.dlid = remote.lid;
    attr.ah_attr.sl = 0;
    attr.ah_attr.src_path_bits = 0;
    attr.ah_attr.is_global = 1;
    attr.ah_attr.port_num = ctx.port;

    int flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN |
                IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;

    if (ibv_modify_qp(qp, &attr, flags) != 0) {
        perror("MPComm: Failed to modify QP to RTR");
        return MPCOMM_ERR_CONNECTION;
    }

    return MPCOMM_SUCCESS;
}

int MPComm::modifyQPToRTS(struct ibv_qp *qp) {
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    
    attr.qp_state = IBV_QPS_RTS;
    attr.timeout = kTimeout;
    attr.retry_cnt = kRetryCnt;
    attr.rnr_retry = 7;
    attr.sq_psn = 0;
    attr.max_rd_atomic = 16;

    int flags = IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
                IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC;

    if (ibv_modify_qp(qp, &attr, flags) != 0) {
        perror("MPComm: Failed to modify QP to RTS");
        return MPCOMM_ERR_CONNECTION;
    }

    // Set QP UDP source port for multi-path ECMP load balancing
    // This helps distribute traffic across multiple network paths
#ifdef USE_BNXT
    {
        int port_idx = qp_port_index.fetch_add(1) % (sizeof(qp_port_list) / sizeof(qp_port_list[0]));
        bnxt_re_dv_modify_qp_udp_sport(qp, qp_port_list[port_idx]);
    }
#elif defined(USE_MLNX)
    {
        int port_idx = qp_port_index.fetch_add(1) % (sizeof(qp_port_list) / sizeof(qp_port_list[0]));
        mlx5dv_modify_qp_udp_sport(qp, qp_port_list[port_idx]);
    }
#endif

    return MPCOMM_SUCCESS;
}

void MPComm::destroyQP(struct ibv_qp *qp) {
    if (qp) {
        ibv_destroy_qp(qp);
    }
}

// ============================================================================
// TCP Handshake for Metadata Exchange
// ============================================================================

int MPComm::connect(const std::string &remote_host_id,
                    const std::string &remote_tcp_addr,
                    int remote_tcp_port) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;

    printf("MPComm: Connecting to %s at %s:%d\n",
           remote_host_id.c_str(), remote_tcp_addr.c_str(), remote_tcp_port);

    // Create TCP connection
    int sock_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (sock_fd < 0) {
        perror("MPComm: Failed to create socket");
        return MPCOMM_ERR_CONNECTION;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(remote_tcp_port);
    
    if (inet_pton(AF_INET, remote_tcp_addr.c_str(), &addr.sin_addr) <= 0) {
        // Try hostname resolution
        struct hostent *he = gethostbyname(remote_tcp_addr.c_str());
        if (!he) {
            fprintf(stderr, "MPComm: Failed to resolve %s\n",
                    remote_tcp_addr.c_str());
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        memcpy(&addr.sin_addr, he->h_addr, he->h_length);
    }

    if (::connect(sock_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("MPComm: Failed to connect");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Disable Nagle's algorithm
    int flag = 1;
    setsockopt(sock_fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

    // Exchange metadata for each NIC
    ConnectionInfo conn_info;
    conn_info.host_id = remote_host_id;
    conn_info.tcp_port = remote_tcp_port;

    // Send number of local NICs
    uint32_t num_nics = static_cast<uint32_t>(nic_contexts_.size());
    if (send(sock_fd, &num_nics, sizeof(num_nics), 0) != sizeof(num_nics)) {
        perror("MPComm: Failed to send num_nics");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive number of remote NICs
    uint32_t remote_num_nics;
    if (recv(sock_fd, &remote_num_nics, sizeof(remote_num_nics), MSG_WAITALL) !=
        sizeof(remote_num_nics)) {
        perror("MPComm: Failed to receive remote_num_nics");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    printf("MPComm: Local NICs=%u, Remote NICs=%u, QPs per connection=%zu\n",
           num_nics, remote_num_nics, qps_per_connection_);

    // Exchange NUMA topology information for NUMA-aware NIC selection
    // Send local NUMA count and per-NIC NUMA node info
    int32_t local_numa_count = static_cast<int32_t>(numa_topology_.size());
    if (send(sock_fd, &local_numa_count, sizeof(local_numa_count), 0) != sizeof(local_numa_count)) {
        perror("MPComm: Failed to send local_numa_count");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Send per-NIC NUMA node info
    std::vector<int32_t> local_nic_numa(num_nics);
    for (size_t i = 0; i < num_nics; ++i) {
        local_nic_numa[i] = getNicNumaNode(nic_contexts_[i]->device_name);
    }
    if (send(sock_fd, local_nic_numa.data(), num_nics * sizeof(int32_t), 0) !=
        static_cast<ssize_t>(num_nics * sizeof(int32_t))) {
        perror("MPComm: Failed to send local_nic_numa");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive remote NUMA topology
    int32_t remote_numa_count;
    if (recv(sock_fd, &remote_numa_count, sizeof(remote_numa_count), MSG_WAITALL) !=
        sizeof(remote_numa_count)) {
        perror("MPComm: Failed to receive remote_numa_count");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    std::vector<int32_t> remote_nic_numa(remote_num_nics);
    if (recv(sock_fd, remote_nic_numa.data(), remote_num_nics * sizeof(int32_t), MSG_WAITALL) !=
        static_cast<ssize_t>(remote_num_nics * sizeof(int32_t))) {
        perror("MPComm: Failed to receive remote_nic_numa");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Store remote NUMA topology in connection info
    conn_info.remote_numa_count = remote_numa_count;
    conn_info.remote_nic_numa_nodes.resize(remote_num_nics);
    for (size_t i = 0; i < remote_num_nics; ++i) {
        conn_info.remote_nic_numa_nodes[i] = remote_nic_numa[i];
    }

    printf("MPComm: Remote NUMA count=%d, Remote NIC NUMA mapping: ", remote_numa_count);
    for (size_t i = 0; i < remote_num_nics; ++i) {
        printf("NIC%zu->NUMA%d%s", i, remote_nic_numa[i], 
               (i < remote_num_nics - 1) ? ", " : "\n");
    }

    // Exchange NIC names for name-based matching
    // Send local NIC names (format: length-prefixed strings)
    for (size_t i = 0; i < num_nics; ++i) {
        const std::string& name = nic_contexts_[i]->device_name;
        uint32_t name_len = static_cast<uint32_t>(name.size());
        if (send(sock_fd, &name_len, sizeof(name_len), 0) != sizeof(name_len)) {
            perror("MPComm: Failed to send nic_name length");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        if (name_len > 0 && send(sock_fd, name.c_str(), name_len, 0) != static_cast<ssize_t>(name_len)) {
            perror("MPComm: Failed to send nic_name");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
    }

    // Receive remote NIC names
    std::vector<std::string> remote_nic_names(remote_num_nics);
    for (size_t i = 0; i < remote_num_nics; ++i) {
        uint32_t name_len;
        if (recv(sock_fd, &name_len, sizeof(name_len), MSG_WAITALL) != sizeof(name_len)) {
            perror("MPComm: Failed to receive nic_name length");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        if (name_len > 0) {
            std::vector<char> buf(name_len + 1, 0);
            if (recv(sock_fd, buf.data(), name_len, MSG_WAITALL) != static_cast<ssize_t>(name_len)) {
                perror("MPComm: Failed to receive nic_name");
                close(sock_fd);
                return MPCOMM_ERR_CONNECTION;
            }
            remote_nic_names[i] = std::string(buf.data());
        }
    }
    conn_info.remote_nic_names = remote_nic_names;

    // Build suffix-to-index mapping for remote NICs
    std::map<int, std::vector<size_t>> remote_suffix_to_nics;  // suffix -> list of remote NIC indices
    for (size_t i = 0; i < remote_num_nics; ++i) {
        int suffix = extractNicSuffix(remote_nic_names[i]);
        if (suffix >= 0) {
            remote_suffix_to_nics[suffix].push_back(i);
        }
    }

    printf("MPComm: Remote NIC names: ");
    for (size_t i = 0; i < remote_num_nics; ++i) {
        int suffix = extractNicSuffix(remote_nic_names[i]);
        printf("%s(suffix=%d)%s", remote_nic_names[i].c_str(), suffix,
               (i < remote_num_nics - 1) ? ", " : "\n");
    }

    // Check how many distinct NUMA nodes the remote NICs actually span
    // This is different from remote_numa_count (system NUMA count)
    std::set<int> remote_nic_numa_set;
    for (size_t i = 0; i < remote_num_nics; ++i) {
        if (remote_nic_numa[i] >= 0) {
            remote_nic_numa_set.insert(remote_nic_numa[i]);
        }
    }
    size_t actual_remote_numa_count = remote_nic_numa_set.size();
    
    // Build per-NUMA NIC lists for remote side
    std::map<int, std::vector<size_t>> remote_numa_to_nics;
    for (size_t i = 0; i < remote_num_nics; ++i) {
        int numa = remote_nic_numa[i];
        if (numa >= 0) {
            remote_numa_to_nics[numa].push_back(i);
        }
    }
    
    printf("MPComm: Remote NICs span %zu distinct NUMA node(s)\n", actual_remote_numa_count);
    
    // Store all remote endpoints (one per remote NIC)
    conn_info.nic_endpoints.resize(remote_num_nics);

    // First, send number of QPs per connection
    uint32_t qps_per_conn = static_cast<uint32_t>(qps_per_connection_);
    if (send(sock_fd, &qps_per_conn, sizeof(qps_per_conn), 0) != sizeof(qps_per_conn)) {
        perror("MPComm: Failed to send qps_per_conn");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive remote's QPs per connection (use min of both)
    uint32_t remote_qps_per_conn;
    if (recv(sock_fd, &remote_qps_per_conn, sizeof(remote_qps_per_conn), MSG_WAITALL) !=
        sizeof(remote_qps_per_conn)) {
        perror("MPComm: Failed to receive remote_qps_per_conn");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    size_t actual_qps = std::min(static_cast<size_t>(qps_per_conn),
                                  static_cast<size_t>(remote_qps_per_conn));
    printf("MPComm: Using %zu QPs per NIC connection\n", actual_qps);

    // Name-based NUMA-aware connection strategy:
    // - Match local and remote NICs by their name suffix (e.g., mlx5_bond_0 matches with mlx5_0)
    // - If remote NICs span multiple NUMA nodes: connect to matching NIC AND 
    //   corresponding NIC in other NUMA nodes with same suffix offset
    //   Example: local aa0 connects to remote bb0 (same suffix) and bb4 (same position in NUMA1)
    // - If all remote NICs are on the same NUMA node: simple suffix-based matching
    
    size_t total_connections = 0;
    
    // Simple suffix-based matching strategy:
    // Local NIC with suffix N connects to remote NIC with suffix N and N+4 (if they exist)
    // Example: local mlx5_bond_1 -> remote mlx5_bond_1 + mlx5_bond_5
    //          local mlx5_bond_2 -> remote mlx5_bond_2 + mlx5_bond_6
    
    printf("MPComm: Using suffix-based matching (N -> N and N+4)\n");
    
    for (size_t local_nic = 0; local_nic < num_nics; ++local_nic) {
        auto &ctx = *nic_contexts_[local_nic];
        const std::string& local_name = ctx.device_name;
        int local_suffix = extractNicSuffix(local_name);
        
        // Calculate which remote NICs this local NIC should connect to
        std::vector<size_t> target_remote_nics;
        
        // Primary: find remote NIC with same suffix N
        auto it = remote_suffix_to_nics.find(local_suffix);
        if (it != remote_suffix_to_nics.end() && !it->second.empty()) {
            target_remote_nics.push_back(it->second[0]);
        }
        
        // Secondary: find remote NIC with suffix N+4
        int paired_suffix = local_suffix + 4;
        auto it2 = remote_suffix_to_nics.find(paired_suffix);
        if (it2 != remote_suffix_to_nics.end() && !it2->second.empty()) {
            target_remote_nics.push_back(it2->second[0]);
        }
        
        if (target_remote_nics.empty()) {
            // No matching suffix found, skip this local NIC
            printf("MPComm: Local NIC%zu (%s, suffix=%d) has no matching remote NIC (checked %d and %d), skipping\n",
                   local_nic, local_name.c_str(), local_suffix, local_suffix, paired_suffix);
            continue;
        }
        
        if (target_remote_nics.empty()) {
            continue;  // No remote NICs to connect to
        }
        
        printf("MPComm: Local NIC%zu (%s, suffix=%d) connecting to remote NICs: ", 
               local_nic, local_name.c_str(), local_suffix);
        for (size_t idx = 0; idx < target_remote_nics.size(); ++idx) {
            size_t r = target_remote_nics[idx];
            printf("%zu(%s)%s", r, remote_nic_names[r].c_str(),
                   (idx < target_remote_nics.size() - 1) ? ", " : "\n");
        }
        
        // Store the local-to-remote NIC mapping for later use in transfers
        conn_info.local_to_remote_nic_map[local_nic] = target_remote_nics;
        
        // Create connections to each target remote NIC
        for (size_t remote_nic : target_remote_nics) {
            std::string key = remote_host_id + ":" + std::to_string(local_nic) + 
                              ":" + std::to_string(remote_nic);
            std::vector<struct ibv_qp *> qp_list;
            qp_list.reserve(actual_qps);

            // Create multiple QPs for this NIC connection
            for (size_t qp_idx = 0; qp_idx < actual_qps; ++qp_idx) {
                // Create QP for this connection
                struct ibv_qp *qp = nullptr;
                int ret = createQP(ctx, &qp);
                if (ret != 0) {
                    // Cleanup already created QPs
                    for (auto *created_qp : qp_list) {
                        destroyQP(created_qp);
                    }
                    close(sock_fd);
                    return ret;
                }

                ret = modifyQPToInit(ctx, qp);
                if (ret != 0) {
                    destroyQP(qp);
                    for (auto *created_qp : qp_list) {
                        destroyQP(created_qp);
                    }
                    close(sock_fd);
                    return ret;
                }

                // Prepare local info with target remote NIC index
                RemoteEndpointInfo local_info;
                memset(&local_info, 0, sizeof(local_info));
                strncpy(local_info.gid, gidToString(ctx.gid).c_str(),
                        sizeof(local_info.gid) - 1);
                local_info.lid = ctx.lid;
                local_info.qp_num = qp->qp_num;
                // Encode target remote NIC in addr field for passive side to know
                local_info.addr = remote_nic;
                // Encode source local NIC in length field for passive side to track
                local_info.length = local_nic;

                // Send local info
                if (send(sock_fd, &local_info, sizeof(local_info), 0) !=
                    sizeof(local_info)) {
                    perror("MPComm: Failed to send local_info");
                    destroyQP(qp);
                    for (auto *created_qp : qp_list) {
                        destroyQP(created_qp);
                    }
                    close(sock_fd);
                    return MPCOMM_ERR_CONNECTION;
                }

                // Receive remote info
                RemoteEndpointInfo remote_info;
                if (recv(sock_fd, &remote_info, sizeof(remote_info), MSG_WAITALL) !=
                    sizeof(remote_info)) {
                    perror("MPComm: Failed to receive remote_info");
                    destroyQP(qp);
                    for (auto *created_qp : qp_list) {
                        destroyQP(created_qp);
                    }
                    close(sock_fd);
                    return MPCOMM_ERR_CONNECTION;
                }

                printf("MPComm: NIC %s->%s QP[%zu]: Local QPN=%u, Remote QPN=%u\n",
                       nic_contexts_[local_nic]->device_name.c_str(),
                       remote_nic_names[remote_nic].c_str(),
                       qp_idx, local_info.qp_num, remote_info.qp_num);

                // Complete QP setup
                ret = modifyQPToRTR(ctx, qp, remote_info);
                if (ret != 0) {
                    destroyQP(qp);
                    for (auto *created_qp : qp_list) {
                        destroyQP(created_qp);
                    }
                    close(sock_fd);
                    return ret;
                }

                ret = modifyQPToRTS(qp);
                if (ret != 0) {
                    destroyQP(qp);
                    for (auto *created_qp : qp_list) {
                        destroyQP(created_qp);
                    }
                    close(sock_fd);
                    return ret;
                }

                qp_list.push_back(qp);

                // Store remote endpoint info for this remote NIC
                if (qp_idx == 0) {
                    conn_info.nic_endpoints[remote_nic] = remote_info;
                }
            }

            // Store QP list with new key format: "host:local_nic:remote_nic"
            {
                std::lock_guard<std::mutex> lock(ctx.qp_mutex);
                ctx.qp_map[key] = std::move(qp_list);
            }
            total_connections++;
        }
    }

    close(sock_fd);

    // Store connection info
    {
        std::lock_guard<std::mutex> lock(connections_mutex_);
        connections_[remote_host_id] = conn_info;
    }

    printf("MPComm: Connected to %s with %zu NIC connections (NUMA-aware), %zu QPs each\n",
           remote_host_id.c_str(), total_connections, actual_qps);
    
    return MPCOMM_SUCCESS;
}

int MPComm::startAcceptThread() {
    if (listen_fd_ < 0) {
        fprintf(stderr, "MPComm: TCP listener not initialized\n");
        return MPCOMM_ERR_CONNECTION;
    }

    accept_running_ = true;
    accept_thread_ = std::make_unique<std::thread>(&MPComm::acceptLoop, this);
    return MPCOMM_SUCCESS;
}

void MPComm::stopAcceptThread() {
    accept_running_ = false;
    
    // Interrupt accept() by connecting to ourselves
    if (listen_fd_ >= 0 && accept_thread_) {
        int dummy_sock = socket(AF_INET, SOCK_STREAM, 0);
        if (dummy_sock >= 0) {
            struct sockaddr_in addr;
            memset(&addr, 0, sizeof(addr));
            addr.sin_family = AF_INET;
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            addr.sin_port = htons(tcp_port_);
            ::connect(dummy_sock, (struct sockaddr *)&addr, sizeof(addr));
            close(dummy_sock);
        }
    }

    if (accept_thread_ && accept_thread_->joinable()) {
        accept_thread_->join();
    }
    accept_thread_.reset();
}

void MPComm::acceptLoop() {
    while (accept_running_) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);
        
        int client_fd = accept(listen_fd_, (struct sockaddr *)&client_addr,
                               &addr_len);
        if (client_fd < 0) {
            if (accept_running_) {
                perror("MPComm: Accept failed");
            }
            continue;
        }

        if (!accept_running_) {
            close(client_fd);
            break;
        }

        // Handle client in same thread (simple implementation)
        printf("MPComm: Accepted connection from %s:%d\n",
               inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));

        // Disable Nagle's algorithm
        int flag = 1;
        setsockopt(client_fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

        // Receive message type (first 4 bytes)
        uint32_t msg_type;
        if (recv(client_fd, &msg_type, sizeof(msg_type), MSG_WAITALL) !=
            sizeof(msg_type)) {
            perror("MPComm: Failed to receive message type");
            close(client_fd);
            continue;
        }

        if (msg_type == kMsgTypeBufferQuery) {
            // Handle buffer query request
            handleBufferQuery(client_fd);
            close(client_fd);
            continue;
        }

        // Treat as connection request (backward compatible: msg_type is num_nics)
        uint32_t remote_num_nics = msg_type;

        // Send number of local NICs
        uint32_t num_nics = static_cast<uint32_t>(nic_contexts_.size());
        if (send(client_fd, &num_nics, sizeof(num_nics), 0) !=
            sizeof(num_nics)) {
            perror("MPComm: Failed to send num_nics");
            close(client_fd);
            continue;
        }

        // Generate temporary remote host ID
        char remote_id_buf[64];
        snprintf(remote_id_buf, sizeof(remote_id_buf), "%s:%d",
                 inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));
        std::string remote_host_id = remote_id_buf;

        ConnectionInfo conn_info;
        conn_info.host_id = remote_host_id;
        conn_info.tcp_port = ntohs(client_addr.sin_port);

        // Receive remote NUMA topology (part of new protocol)
        int32_t remote_numa_count;
        if (recv(client_fd, &remote_numa_count, sizeof(remote_numa_count), MSG_WAITALL) !=
            sizeof(remote_numa_count)) {
            perror("MPComm: Failed to receive remote_numa_count");
            close(client_fd);
            continue;
        }

        std::vector<int32_t> remote_nic_numa(remote_num_nics);
        if (recv(client_fd, remote_nic_numa.data(), remote_num_nics * sizeof(int32_t), MSG_WAITALL) !=
            static_cast<ssize_t>(remote_num_nics * sizeof(int32_t))) {
            perror("MPComm: Failed to receive remote_nic_numa");
            close(client_fd);
            continue;
        }

        // Send local NUMA topology
        int32_t local_numa_count = static_cast<int32_t>(numa_topology_.size());
        if (send(client_fd, &local_numa_count, sizeof(local_numa_count), 0) !=
            sizeof(local_numa_count)) {
            perror("MPComm: Failed to send local_numa_count");
            close(client_fd);
            continue;
        }

        std::vector<int32_t> local_nic_numa(num_nics);
        for (size_t i = 0; i < num_nics; ++i) {
            local_nic_numa[i] = getNicNumaNode(nic_contexts_[i]->device_name);
        }
        if (send(client_fd, local_nic_numa.data(), num_nics * sizeof(int32_t), 0) !=
            static_cast<ssize_t>(num_nics * sizeof(int32_t))) {
            perror("MPComm: Failed to send local_nic_numa");
            close(client_fd);
            continue;
        }

        // Store remote NUMA topology
        conn_info.remote_numa_count = remote_numa_count;
        conn_info.remote_nic_numa_nodes.resize(remote_num_nics);
        for (size_t i = 0; i < remote_num_nics; ++i) {
            conn_info.remote_nic_numa_nodes[i] = remote_nic_numa[i];
        }

        printf("MPComm: Passive side: Remote NUMA count=%d, Remote NIC NUMA mapping: ", remote_numa_count);
        for (size_t i = 0; i < remote_num_nics; ++i) {
            printf("NIC%zu->NUMA%d%s", i, remote_nic_numa[i], 
                   (i < remote_num_nics - 1) ? ", " : "\n");
        }

        // Receive remote NIC names (passive side receives first, then sends)
        std::vector<std::string> remote_nic_names(remote_num_nics);
        for (size_t i = 0; i < remote_num_nics; ++i) {
            uint32_t name_len;
            if (recv(client_fd, &name_len, sizeof(name_len), MSG_WAITALL) != sizeof(name_len)) {
                perror("MPComm: Failed to receive nic_name length");
                close(client_fd);
                continue;
            }
            if (name_len > 0) {
                std::vector<char> buf(name_len + 1, 0);
                if (recv(client_fd, buf.data(), name_len, MSG_WAITALL) != static_cast<ssize_t>(name_len)) {
                    perror("MPComm: Failed to receive nic_name");
                    close(client_fd);
                    continue;
                }
                remote_nic_names[i] = std::string(buf.data());
            }
        }
        conn_info.remote_nic_names = remote_nic_names;

        // Send local NIC names
        for (size_t i = 0; i < num_nics; ++i) {
            const std::string& name = nic_contexts_[i]->device_name;
            uint32_t name_len = static_cast<uint32_t>(name.size());
            if (send(client_fd, &name_len, sizeof(name_len), 0) != sizeof(name_len)) {
                perror("MPComm: Failed to send nic_name length");
                close(client_fd);
                continue;
            }
            if (name_len > 0 && send(client_fd, name.c_str(), name_len, 0) != static_cast<ssize_t>(name_len)) {
                perror("MPComm: Failed to send nic_name");
                close(client_fd);
                continue;
            }
        }

        // Build suffix-to-index mapping for remote NICs
        std::map<int, std::vector<size_t>> remote_suffix_to_nics;
        for (size_t i = 0; i < remote_num_nics; ++i) {
            int suffix = extractNicSuffix(remote_nic_names[i]);
            if (suffix >= 0) {
                remote_suffix_to_nics[suffix].push_back(i);
            }
        }

        printf("MPComm: Passive side: Remote NIC names: ");
        for (size_t i = 0; i < remote_num_nics; ++i) {
            int suffix = extractNicSuffix(remote_nic_names[i]);
            printf("%s(suffix=%d)%s", remote_nic_names[i].c_str(), suffix,
                   (i < remote_num_nics - 1) ? ", " : "\n");
        }

        // Store all remote endpoints (one per remote NIC)
        conn_info.nic_endpoints.resize(remote_num_nics);

        // Receive remote's QPs per connection
        uint32_t remote_qps_per_conn;
        if (recv(client_fd, &remote_qps_per_conn, sizeof(remote_qps_per_conn),
                 MSG_WAITALL) != sizeof(remote_qps_per_conn)) {
            perror("MPComm: Failed to receive remote_qps_per_conn");
            close(client_fd);
            continue;
        }

        // Send our QPs per connection
        uint32_t qps_per_conn = static_cast<uint32_t>(qps_per_connection_);
        if (send(client_fd, &qps_per_conn, sizeof(qps_per_conn), 0) !=
            sizeof(qps_per_conn)) {
            perror("MPComm: Failed to send qps_per_conn");
            close(client_fd);
            continue;
        }

        size_t actual_qps = std::min(static_cast<size_t>(qps_per_conn),
                                      static_cast<size_t>(remote_qps_per_conn));
        printf("MPComm: Passive side: Using %zu QPs per NIC connection\n", actual_qps);

        // Check how many distinct NUMA nodes the remote NICs actually span
        // Must match the logic in connect() on active side
        std::set<int> remote_nic_numa_set;
        for (size_t i = 0; i < remote_num_nics; ++i) {
            if (remote_nic_numa[i] >= 0) {
                remote_nic_numa_set.insert(remote_nic_numa[i]);
            }
        }
        
        // Build per-NUMA NIC lists for remote side
        std::map<int, std::vector<size_t>> remote_numa_to_nics;
        for (size_t i = 0; i < remote_num_nics; ++i) {
            int numa = remote_nic_numa[i];
            if (numa >= 0) {
                remote_numa_to_nics[numa].push_back(i);
            }
        }
        
        // Build suffix to local NIC mapping for quick lookup
        std::map<int, size_t> local_suffix_to_nic;
        for (size_t i = 0; i < num_nics; ++i) {
            int suffix = extractNicSuffix(nic_contexts_[i]->device_name);
            if (suffix >= 0) {
                local_suffix_to_nic[suffix] = i;
            }
        }
        
        printf("MPComm: Passive side: Using suffix-based matching (N -> N and N+4)\n");
        
        // Calculate expected number of connections (must match active side exactly)
        // Active side: for each local NIC with suffix N, connects to remote NICs with suffix N and N+4
        // On passive side, we need to calculate how many remote NICs will connect to us
        size_t expected_connections = 0;
        
        // For each remote NIC (which is the active side's local NIC)
        for (size_t remote_nic = 0; remote_nic < remote_num_nics; ++remote_nic) {
            int remote_suffix = extractNicSuffix(remote_nic_names[remote_nic]);
            
            // Active side with suffix N will try to connect to local NICs with suffix N and N+4
            // Count connections where we have matching suffix N (same as remote)
            if (local_suffix_to_nic.count(remote_suffix) > 0) {
                expected_connections++;  // Primary: N -> N
            }
            
            // Count connections where we have suffix N+4 (remote N connects to our N+4)
            int paired_suffix = remote_suffix + 4;
            if (local_suffix_to_nic.count(paired_suffix) > 0) {
                expected_connections++;  // Secondary: N -> N+4
            }
        }
        
        printf("MPComm: Passive side: Expecting %zu connections\n", expected_connections);

        bool success = true;
        size_t total_connections = 0;
        
        // Receive connections from active side - the active side determines which
        // local NIC connects to which remote NIC (encoded in remote_info)
        // remote_info.addr = target local NIC on passive side
        // remote_info.length = source remote NIC (active side's local NIC)
        while (total_connections < expected_connections && success) {
            // Receive first QP info to determine connection mapping
            RemoteEndpointInfo remote_info;
            if (recv(client_fd, &remote_info, sizeof(remote_info), MSG_WAITALL) !=
                sizeof(remote_info)) {
                perror("MPComm: Failed to receive remote_info");
                success = false;
                break;
            }

            // Decode: remote_info.addr contains the target local NIC index on passive side
            size_t local_nic = static_cast<size_t>(remote_info.addr);
            if (local_nic >= num_nics) {
                fprintf(stderr, "MPComm: Invalid local NIC index %zu from active side\n", local_nic);
                success = false;
                break;
            }

            // Decode: remote_info.length contains the source remote NIC (active side's local NIC)
            size_t remote_nic = static_cast<size_t>(remote_info.length);
            if (remote_nic >= remote_num_nics) {
                fprintf(stderr, "MPComm: Invalid remote NIC index %zu from active side\n", remote_nic);
                success = false;
                break;
            }

            auto &ctx = *nic_contexts_[local_nic];
            std::string key = remote_host_id + ":" + std::to_string(local_nic) + 
                              ":" + std::to_string(remote_nic);
            std::vector<struct ibv_qp *> qp_list;
            qp_list.reserve(actual_qps);

            // Process first QP (already received remote_info)
            for (size_t qp_idx = 0; qp_idx < actual_qps && success; ++qp_idx) {
                // For subsequent QPs, receive remote_info
                if (qp_idx > 0) {
                    if (recv(client_fd, &remote_info, sizeof(remote_info), MSG_WAITALL) !=
                        sizeof(remote_info)) {
                        perror("MPComm: Failed to receive remote_info");
                        success = false;
                        break;
                    }
                }

                // Create QP
                struct ibv_qp *qp = nullptr;
                if (createQP(ctx, &qp) != 0) {
                    success = false;
                    break;
                }

                if (modifyQPToInit(ctx, qp) != 0) {
                    destroyQP(qp);
                    success = false;
                    break;
                }

                // Prepare local info
                RemoteEndpointInfo local_info;
                memset(&local_info, 0, sizeof(local_info));
                strncpy(local_info.gid, gidToString(ctx.gid).c_str(),
                        sizeof(local_info.gid) - 1);
                local_info.lid = ctx.lid;
                local_info.qp_num = qp->qp_num;

                // Send local info
                if (send(client_fd, &local_info, sizeof(local_info), 0) !=
                    sizeof(local_info)) {
                    perror("MPComm: Failed to send local_info");
                    destroyQP(qp);
                    success = false;
                    break;
                }

                // Complete QP setup
                if (modifyQPToRTR(ctx, qp, remote_info) != 0 ||
                    modifyQPToRTS(qp) != 0) {
                    destroyQP(qp);
                    success = false;
                    break;
                }

                qp_list.push_back(qp);

                // Store remote endpoint info
                if (qp_idx == 0) {
                    // Clear the encoded local_nic from addr field
                    remote_info.addr = 0;
                    conn_info.nic_endpoints[remote_nic] = remote_info;
                }

                printf("MPComm: Passive NIC %s<-%s QP[%zu]: Local QPN=%u, Remote QPN=%u\n",
                       nic_contexts_[local_nic]->device_name.c_str(),
                       remote_nic_names[remote_nic].c_str(),
                       qp_idx, local_info.qp_num, remote_info.qp_num);
            }

            if (success) {
                // Store QP list with new key format
                std::lock_guard<std::mutex> lock(ctx.qp_mutex);
                ctx.qp_map[key] = std::move(qp_list);
                total_connections++;
                
                // Store the local-to-remote NIC mapping
                // On passive side: local_nic is our NIC, remote_nic is the active side's NIC
                conn_info.local_to_remote_nic_map[local_nic].push_back(remote_nic);
            } else {
                // Cleanup on failure
                for (auto *qp : qp_list) {
                    destroyQP(qp);
                }
            }
        }

        close(client_fd);

        if (success) {
            std::lock_guard<std::mutex> lock(connections_mutex_);
            connections_[remote_host_id] = conn_info;
            printf("MPComm: Passive connection established with %s (%zu NIC connections, NUMA-aware)\n",
                   remote_host_id.c_str(), total_connections);
        }
    }
}

// ============================================================================
// RDMA Operations
// ============================================================================

int MPComm::postRdmaWrite(NicContext &ctx, struct ibv_qp *qp,
                          void *local_addr, uint32_t lkey,
                          uint64_t remote_addr, uint32_t rkey,
                          size_t length) {
    // For large transfers, split into chunks <= max_rdma_transfer_size_
    // Each chunk is posted and completed before the next one
    size_t offset = 0;
    while (offset < length) {
        size_t chunk_size = std::min(length - offset, max_rdma_transfer_size_);
        
        uint8_t *chunk_local_addr = reinterpret_cast<uint8_t *>(local_addr) + offset;
        uint64_t chunk_remote_addr = remote_addr + offset;

        struct ibv_sge sge;
        memset(&sge, 0, sizeof(sge));
        sge.addr = reinterpret_cast<uint64_t>(chunk_local_addr);
        sge.length = static_cast<uint32_t>(chunk_size);
        sge.lkey = lkey;

        struct ibv_send_wr wr;
        memset(&wr, 0, sizeof(wr));
        wr.wr_id = reinterpret_cast<uint64_t>(chunk_local_addr);
        wr.opcode = IBV_WR_RDMA_WRITE;
        wr.sg_list = &sge;
        wr.num_sge = 1;
        wr.send_flags = IBV_SEND_SIGNALED;
        wr.wr.rdma.remote_addr = chunk_remote_addr;
        wr.wr.rdma.rkey = rkey;

        struct ibv_send_wr *bad_wr = nullptr;
        int ret = ibv_post_send(qp, &wr, &bad_wr);
        if (ret != 0) {
            fprintf(stderr, "MPComm: ibv_post_send (WRITE) failed: %d, "
                    "chunk_offset=%zu, chunk_size=%zu\n", ret, offset, chunk_size);
            return MPCOMM_ERR_TRANSFER;
        }

        // Wait for this chunk to complete before posting the next one
        ret = pollCompletion(ctx);
        if (ret != 0) {
            fprintf(stderr, "MPComm: WRITE completion failed at offset=%zu\n", offset);
            return ret;
        }

        offset += chunk_size;
    }

    return MPCOMM_SUCCESS;
}

int MPComm::postRdmaRead(NicContext &ctx, struct ibv_qp *qp,
                         void *local_addr, uint32_t lkey,
                         uint64_t remote_addr, uint32_t rkey,
                         size_t length) {
    // For large transfers, split into chunks <= max_rdma_transfer_size_
    // Each chunk is posted and completed before the next one
    size_t offset = 0;
    while (offset < length) {
        size_t chunk_size = std::min(length - offset, max_rdma_transfer_size_);
        
        uint8_t *chunk_local_addr = reinterpret_cast<uint8_t *>(local_addr) + offset;
        uint64_t chunk_remote_addr = remote_addr + offset;

        struct ibv_sge sge;
        memset(&sge, 0, sizeof(sge));
        sge.addr = reinterpret_cast<uint64_t>(chunk_local_addr);
        sge.length = static_cast<uint32_t>(chunk_size);
        sge.lkey = lkey;

        struct ibv_send_wr wr;
        memset(&wr, 0, sizeof(wr));
        wr.wr_id = reinterpret_cast<uint64_t>(chunk_local_addr);
        wr.opcode = IBV_WR_RDMA_READ;
        wr.sg_list = &sge;
        wr.num_sge = 1;
        wr.send_flags = IBV_SEND_SIGNALED;
        wr.wr.rdma.remote_addr = chunk_remote_addr;
        wr.wr.rdma.rkey = rkey;

        struct ibv_send_wr *bad_wr = nullptr;
        int ret = ibv_post_send(qp, &wr, &bad_wr);
        if (ret != 0) {
            fprintf(stderr, "MPComm: ibv_post_send (READ) failed: %d, "
                    "chunk_offset=%zu, chunk_size=%zu\n", ret, offset, chunk_size);
            return MPCOMM_ERR_TRANSFER;
        }

        // Wait for this chunk to complete before posting the next one
        ret = pollCompletion(ctx);
        if (ret != 0) {
            fprintf(stderr, "MPComm: READ completion failed at offset=%zu\n", offset);
            return ret;
        }

        offset += chunk_size;
    }

    return MPCOMM_SUCCESS;
}

int MPComm::pollCompletion(NicContext &ctx, int timeout_ms) {
    struct ibv_wc wc;
    auto start = std::chrono::steady_clock::now();

    while (true) {
        int n = ibv_poll_cq(ctx.cq, 1, &wc);
        if (n < 0) {
            fprintf(stderr, "MPComm: ibv_poll_cq failed\n");
            return MPCOMM_ERR_TRANSFER;
        }
        
        if (n > 0) {
            if (wc.status != IBV_WC_SUCCESS) {
                fprintf(stderr, "MPComm: WC error: status=%d, wr_id=%lu\n",
                        wc.status, wc.wr_id);
                return MPCOMM_ERR_TRANSFER;
            }
            return MPCOMM_SUCCESS;
        }

        // Check timeout
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - start).count();
        if (elapsed >= timeout_ms) {
            fprintf(stderr, "MPComm: Poll timeout after %dms\n", timeout_ms);
            return MPCOMM_ERR_TIMEOUT;
        }

        // Brief yield to avoid busy-waiting too aggressively
        std::this_thread::yield();
    }
}

// ============================================================================
// Synchronous Post-Poll RDMA functions (no separate poll thread)
// These functions perform Post-Poll loop in a single thread for better efficiency
// ============================================================================

int MPComm::rdmaWriteSyncMultiQP(NicContext &ctx, const std::string &host_id,
                                 size_t nic_index, void *local_addr, uint32_t lkey,
                                 uint64_t remote_addr, uint32_t rkey, size_t length) {
    // Flow control parameters
    const size_t max_outstanding_per_qp = 256;
    const int poll_batch_size = 32;
    
    // Calculate number of chunks
    size_t num_chunks = (length + max_rdma_transfer_size_ - 1) / max_rdma_transfer_size_;
    if (num_chunks == 0) return MPCOMM_SUCCESS;
    
    // Per-QP counters for flow control
    std::vector<size_t> per_qp_posted(qps_per_connection_, 0);
    std::vector<size_t> per_qp_completed(qps_per_connection_, 0);
    
    struct ibv_wc wc_array[32];
    size_t total_completed = 0;
    size_t offset = 0;
    
    for (size_t chunk_idx = 0; chunk_idx < num_chunks; ++chunk_idx) {
        // Round-robin QP selection
        size_t qp_index = chunk_idx % qps_per_connection_;
        
        // Flow control: poll CQ if this QP has too many outstanding WRs
        while (per_qp_posted[qp_index] - per_qp_completed[qp_index] >= max_outstanding_per_qp) {
            int n = ibv_poll_cq(ctx.cq, poll_batch_size, wc_array);
            if (n < 0) {
                fprintf(stderr, "MPComm: ibv_poll_cq failed in rdmaWriteSyncMultiQP\n");
                return MPCOMM_ERR_TRANSFER;
            }
            for (int i = 0; i < n; ++i) {
                if (wc_array[i].status != IBV_WC_SUCCESS) {
                    fprintf(stderr, "MPComm: WC error in rdmaWriteSyncMultiQP: status=%d\n",
                            wc_array[i].status);
                    return MPCOMM_ERR_TRANSFER;
                }
                // Decode qp_index from wr_id
                size_t completed_qp = (wc_array[i].wr_id >> 56) & 0xFF;
                if (completed_qp < qps_per_connection_) {
                    per_qp_completed[completed_qp]++;
                }
                total_completed++;
            }
            if (n == 0) {
                std::this_thread::yield();
            }
        }
        
        // Get QP
        struct ibv_qp *qp = getOrCreateQP(nic_index, host_id, nic_index, qp_index);
        if (!qp) {
            fprintf(stderr, "MPComm: No QP for %s on NIC %zu (qp_index=%zu)\n",
                    host_id.c_str(), nic_index, qp_index);
            return MPCOMM_ERR_CONNECTION;
        }
        
        size_t chunk_size = std::min(length - offset, max_rdma_transfer_size_);
        uint8_t *chunk_local_addr = reinterpret_cast<uint8_t *>(local_addr) + offset;
        uint64_t chunk_remote_addr = remote_addr + offset;
        
        // Prepare SGE and WR
        struct ibv_sge sge;
        memset(&sge, 0, sizeof(sge));
        sge.addr = reinterpret_cast<uint64_t>(chunk_local_addr);
        sge.length = static_cast<uint32_t>(chunk_size);
        sge.lkey = lkey;
        
        struct ibv_send_wr wr;
        memset(&wr, 0, sizeof(wr));
        // Encode qp_index in upper 8 bits of wr_id
        uint64_t addr_part = reinterpret_cast<uint64_t>(chunk_local_addr) & 0x00FFFFFFFFFFFFFFULL;
        wr.wr_id = (static_cast<uint64_t>(qp_index) << 56) | addr_part;
        wr.opcode = IBV_WR_RDMA_WRITE;
        wr.sg_list = &sge;
        wr.num_sge = 1;
        wr.send_flags = IBV_SEND_SIGNALED;
        wr.wr.rdma.remote_addr = chunk_remote_addr;
        wr.wr.rdma.rkey = rkey;
        
        struct ibv_send_wr *bad_wr = nullptr;
        int ret = ibv_post_send(qp, &wr, &bad_wr);
        if (ret != 0) {
            fprintf(stderr, "MPComm: ibv_post_send (WRITE sync) failed: %d\n", ret);
            return MPCOMM_ERR_TRANSFER;
        }
        
        per_qp_posted[qp_index]++;
        offset += chunk_size;
    }
    
    // Drain remaining completions
    while (total_completed < num_chunks) {
        int n = ibv_poll_cq(ctx.cq, poll_batch_size, wc_array);
        if (n < 0) {
            fprintf(stderr, "MPComm: ibv_poll_cq failed in rdmaWriteSyncMultiQP (drain)\n");
            return MPCOMM_ERR_TRANSFER;
        }
        for (int i = 0; i < n; ++i) {
            if (wc_array[i].status != IBV_WC_SUCCESS) {
                fprintf(stderr, "MPComm: WC error in rdmaWriteSyncMultiQP (drain): status=%d\n",
                        wc_array[i].status);
                return MPCOMM_ERR_TRANSFER;
            }
            total_completed++;
        }
        if (n == 0) {
            std::this_thread::yield();
        }
    }
    
    return MPCOMM_SUCCESS;
}

int MPComm::rdmaReadSyncMultiQP(NicContext &ctx, const std::string &host_id,
                                size_t nic_index, void *local_addr, uint32_t lkey,
                                uint64_t remote_addr, uint32_t rkey, size_t length) {
    // Flow control parameters
    const size_t max_outstanding_per_qp = 256;
    const int poll_batch_size = 32;
    
    // Calculate number of chunks
    size_t num_chunks = (length + max_rdma_transfer_size_ - 1) / max_rdma_transfer_size_;
    if (num_chunks == 0) return MPCOMM_SUCCESS;
    
    // Per-QP counters for flow control
    std::vector<size_t> per_qp_posted(qps_per_connection_, 0);
    std::vector<size_t> per_qp_completed(qps_per_connection_, 0);
    
    struct ibv_wc wc_array[32];
    size_t total_completed = 0;
    size_t offset = 0;
    
    for (size_t chunk_idx = 0; chunk_idx < num_chunks; ++chunk_idx) {
        // Round-robin QP selection
        size_t qp_index = chunk_idx % qps_per_connection_;
        
        // Flow control: poll CQ if this QP has too many outstanding WRs
        while (per_qp_posted[qp_index] - per_qp_completed[qp_index] >= max_outstanding_per_qp) {
            int n = ibv_poll_cq(ctx.cq, poll_batch_size, wc_array);
            if (n < 0) {
                fprintf(stderr, "MPComm: ibv_poll_cq failed in rdmaReadSyncMultiQP\n");
                return MPCOMM_ERR_TRANSFER;
            }
            for (int i = 0; i < n; ++i) {
                if (wc_array[i].status != IBV_WC_SUCCESS) {
                    fprintf(stderr, "MPComm: WC error in rdmaReadSyncMultiQP: status=%d\n",
                            wc_array[i].status);
                    return MPCOMM_ERR_TRANSFER;
                }
                // Decode qp_index from wr_id
                size_t completed_qp = (wc_array[i].wr_id >> 56) & 0xFF;
                if (completed_qp < qps_per_connection_) {
                    per_qp_completed[completed_qp]++;
                }
                total_completed++;
            }
            if (n == 0) {
                std::this_thread::yield();
            }
        }
        
        // Get QP
        struct ibv_qp *qp = getOrCreateQP(nic_index, host_id, nic_index, qp_index);
        if (!qp) {
            fprintf(stderr, "MPComm: No QP for %s on NIC %zu (qp_index=%zu)\n",
                    host_id.c_str(), nic_index, qp_index);
            return MPCOMM_ERR_CONNECTION;
        }
        
        size_t chunk_size = std::min(length - offset, max_rdma_transfer_size_);
        uint8_t *chunk_local_addr = reinterpret_cast<uint8_t *>(local_addr) + offset;
        uint64_t chunk_remote_addr = remote_addr + offset;
        
        // Prepare SGE and WR
        struct ibv_sge sge;
        memset(&sge, 0, sizeof(sge));
        sge.addr = reinterpret_cast<uint64_t>(chunk_local_addr);
        sge.length = static_cast<uint32_t>(chunk_size);
        sge.lkey = lkey;
        
        struct ibv_send_wr wr;
        memset(&wr, 0, sizeof(wr));
        // Encode qp_index in upper 8 bits of wr_id
        uint64_t addr_part = reinterpret_cast<uint64_t>(chunk_local_addr) & 0x00FFFFFFFFFFFFFFULL;
        wr.wr_id = (static_cast<uint64_t>(qp_index) << 56) | addr_part;
        wr.opcode = IBV_WR_RDMA_READ;
        wr.sg_list = &sge;
        wr.num_sge = 1;
        wr.send_flags = IBV_SEND_SIGNALED;
        wr.wr.rdma.remote_addr = chunk_remote_addr;
        wr.wr.rdma.rkey = rkey;
        
        struct ibv_send_wr *bad_wr = nullptr;
        int ret = ibv_post_send(qp, &wr, &bad_wr);
        if (ret != 0) {
            fprintf(stderr, "MPComm: ibv_post_send (READ sync) failed: %d\n", ret);
            return MPCOMM_ERR_TRANSFER;
        }
        
        per_qp_posted[qp_index]++;
        offset += chunk_size;
    }
    
    // Drain remaining completions
    while (total_completed < num_chunks) {
        int n = ibv_poll_cq(ctx.cq, poll_batch_size, wc_array);
        if (n < 0) {
            fprintf(stderr, "MPComm: ibv_poll_cq failed in rdmaReadSyncMultiQP (drain)\n");
            return MPCOMM_ERR_TRANSFER;
        }
        for (int i = 0; i < n; ++i) {
            if (wc_array[i].status != IBV_WC_SUCCESS) {
                fprintf(stderr, "MPComm: WC error in rdmaReadSyncMultiQP (drain): status=%d\n",
                        wc_array[i].status);
                return MPCOMM_ERR_TRANSFER;
            }
            total_completed++;
        }
        if (n == 0) {
            std::this_thread::yield();
        }
    }
    
    return MPCOMM_SUCCESS;
}

struct ibv_qp *MPComm::getOrCreateQP(size_t local_nic_index,
                                     const std::string &remote_host_id,
                                     size_t remote_nic_index,
                                     size_t qp_index) {
    if (local_nic_index >= nic_contexts_.size()) {
        return nullptr;
    }

    auto &ctx = *nic_contexts_[local_nic_index];
    // New key format: "host_id:local_nic:remote_nic" for NUMA-aware connections
    std::string key = remote_host_id + ":" + std::to_string(local_nic_index) + 
                      ":" + std::to_string(remote_nic_index);

    std::lock_guard<std::mutex> lock(ctx.qp_mutex);
    auto it = ctx.qp_map.find(key);
    if (it != ctx.qp_map.end()) {
        const auto &qp_list = it->second;
        if (qp_index < qp_list.size()) {
            return qp_list[qp_index];
        }
        // If qp_index is out of range, return first QP (fallback)
        if (!qp_list.empty()) {
            return qp_list[0];
        }
    }

    return nullptr;  // QP should be created during connect()
}

// ==================== Async Transfer Implementation ====================

TransferHandle MPComm::scatterAsync(uintptr_t local_addr,
                                    const std::vector<std::string> &host_list,
                                    const std::vector<uintptr_t> &remote_addrs,
                                    const std::vector<size_t> &lengths) {
    return transferAsyncStart(local_addr, host_list, remote_addrs, lengths,
                              TransferDirection::SCATTER);
}

TransferHandle MPComm::gatherAsync(uintptr_t local_addr,
                                   const std::vector<std::string> &host_list,
                                   const std::vector<uintptr_t> &remote_addrs,
                                   const std::vector<size_t> &lengths) {
    return transferAsyncStart(local_addr, host_list, remote_addrs, lengths,
                              TransferDirection::GATHER);
}

TransferHandle MPComm::transferAsyncStart(uintptr_t local_addr,
                                          const std::vector<std::string> &host_list,
                                          const std::vector<uintptr_t> &remote_addrs,
                                          const std::vector<size_t> &lengths,
                                          TransferDirection direction) {
    const char* op_name = (direction == TransferDirection::SCATTER) ? "ScatterAsync" : "GatherAsync";
    
    // Validation
    if (!initialized_) {
        fprintf(stderr, "MPComm: %s failed - not initialized\n", op_name);
        return INVALID_TRANSFER_HANDLE;
    }
    
    size_t host_count = host_list.size();
    if (host_count == 0 || remote_addrs.size() != host_count ||
        lengths.size() != host_count) {
        fprintf(stderr, "MPComm: %s failed - invalid arguments\n", op_name);
        return INVALID_TRANSFER_HANDLE;
    }

    size_t num_nics = nic_contexts_.size();
    if (num_nics == 0) {
        fprintf(stderr, "MPComm: %s failed - no NICs available\n", op_name);
        return INVALID_TRANSFER_HANDLE;
    }

    // Create transfer context
    auto ctx = std::make_unique<TransferContext>();
    ctx->handle = next_transfer_handle_.fetch_add(1);
    ctx->local_addr = local_addr;
    ctx->host_list = host_list;
    ctx->remote_addrs = remote_addrs;
    ctx->lengths = lengths;
    ctx->is_scatter = (direction == TransferDirection::SCATTER);
    ctx->start_time = std::chrono::steady_clock::now();
    
    // Prepare all chunks (same logic as transferImplDynamic)
    const size_t max_chunk_size = max_rdma_transfer_size_;
    size_t total_chunks = 0;
    
    // Calculate total chunks and local offsets
    std::vector<size_t> host_chunk_starts(host_count);
    std::vector<size_t> host_local_offsets(host_count);
    
    size_t running_local_offset = 0;
    for (size_t i = 0; i < host_count; ++i) {
        host_chunk_starts[i] = total_chunks;
        host_local_offsets[i] = running_local_offset;
        total_chunks += (lengths[i] + max_chunk_size - 1) / max_chunk_size;
        running_local_offset += lengths[i];
    }
    
    // Handle empty transfer
    if (total_chunks == 0) {
        ctx->total_chunks.store(0);
        ctx->total_completed.store(0);
        ctx->finished.store(true);
        ctx->error_code.store(MPCOMM_SUCCESS);
        ctx->end_time = std::chrono::steady_clock::now();
        
        TransferHandle handle = ctx->handle;
        {
            std::lock_guard<std::mutex> lock(transfers_mutex_);
            active_transfers_[handle] = std::move(ctx);
        }
        return handle;
    }
    
    // Fill chunks
    ctx->all_chunks.resize(total_chunks);
    for (size_t host_idx = 0; host_idx < host_count; ++host_idx) {
        const size_t host_len = lengths[host_idx];
        const uintptr_t base_local = local_addr + host_local_offsets[host_idx];
        const uintptr_t base_remote = remote_addrs[host_idx];
        size_t chunk_idx = host_chunk_starts[host_idx];
        
        size_t full_chunks = host_len / max_chunk_size;
        for (size_t i = 0; i < full_chunks; ++i) {
            ctx->all_chunks[chunk_idx++] = {
                host_idx,
                base_local + i * max_chunk_size,
                base_remote + i * max_chunk_size,
                max_chunk_size
            };
        }
        
        size_t remainder = host_len % max_chunk_size;
        if (remainder > 0) {
            ctx->all_chunks[chunk_idx] = {
                host_idx,
                base_local + full_chunks * max_chunk_size,
                base_remote + full_chunks * max_chunk_size,
                remainder
            };
        }
    }
    
    ctx->total_chunks.store(total_chunks);
    ctx->next_chunk_idx.store(0);
    
    // NUMA-aware NIC selection
    int memory_numa_node = getNumaNodeForAddr(reinterpret_cast<void*>(local_addr));
    ctx->candidate_nic_indices = getLocalNicIndicesForNuma(memory_numa_node);
    
    if (ctx->candidate_nic_indices.empty()) {
        ctx->candidate_nic_indices.reserve(num_nics);
        for (size_t i = 0; i < num_nics; ++i) {
            ctx->candidate_nic_indices.push_back(i);
        }
    }
    
    // Initialize per-NIC flow control state
    ctx->per_nic_posted.resize(num_nics, 0);
    ctx->per_nic_completed.resize(num_nics, 0);
    ctx->per_nic_bytes.resize(num_nics, 0);
    ctx->per_nic_qp_posted.resize(num_nics);
    ctx->per_nic_qp_completed.resize(num_nics);
    for (size_t nic = 0; nic < num_nics; ++nic) {
        ctx->per_nic_qp_posted[nic].resize(qps_per_connection_, 0);
        ctx->per_nic_qp_completed[nic].resize(qps_per_connection_, 0);
    }
    
    printf("MPComm: %s started with %zu chunks across %zu candidate NICs (handle=%lu)\n",
           op_name, total_chunks, ctx->candidate_nic_indices.size(), ctx->handle);
    
    // Post initial chunks (synchronously post all, then return)
    // This is "Mode A": sync post + async poll
    TransferHandle handle = ctx->handle;
    TransferContext* ctx_ptr = ctx.get();  // Keep raw pointer before moving
    
    // Store context first so progress can access it
    {
        std::lock_guard<std::mutex> lock(transfers_mutex_);
        active_transfers_[handle] = std::move(ctx);
    }
    
    // Post all chunks now (blocking post, but fast)
    // The actual transfer happens in the background via RDMA
    // NOTE: Must not hold transfers_mutex_ while calling transferAsyncProgress
    //       because it calls pollAllNicsForAsync which may need to acquire the lock
    int ret = transferAsyncProgress(*ctx_ptr);
    // If error during initial post, mark as finished with error
    if (ret != MPCOMM_SUCCESS && ret != MPCOMM_ERR_PENDING) {
        ctx_ptr->error_code.store(ret);
        ctx_ptr->finished.store(true);
    }
    
    return handle;
}

size_t MPComm::selectBestNicForAsync(TransferContext& ctx) {
    size_t num_nics = nic_contexts_.size();
    size_t num_candidate_nics = ctx.candidate_nic_indices.size();
    const size_t max_outstanding_per_nic = 256 * qps_per_connection_;
    
    size_t best_nic = num_nics;  // Invalid initially
    size_t min_outstanding = SIZE_MAX;
    
    for (size_t idx = 0; idx < num_candidate_nics; ++idx) {
        size_t nic = ctx.candidate_nic_indices[idx];
        size_t outstanding = ctx.per_nic_posted[nic] - ctx.per_nic_completed[nic];
        
        if (outstanding >= max_outstanding_per_nic) {
            continue;
        }
        
        if (outstanding < min_outstanding) {
            min_outstanding = outstanding;
            best_nic = nic;
        } else if (outstanding == min_outstanding) {
            if (idx == (ctx.rr_nic_index % num_candidate_nics)) {
                best_nic = nic;
            }
        }
    }
    
    ctx.rr_nic_index++;
    
    if (best_nic == num_nics) {
        best_nic = ctx.candidate_nic_indices[(ctx.rr_nic_index - 1) % num_candidate_nics];
    }
    
    return best_nic;
}

int MPComm::pollAllNicsForAsync(TransferContext& ctx) {
    // Poll only candidate NICs for better performance in single-transfer scenarios
    // When parallel transfers share the same NICs, completions will still be properly routed
    // because we poll CQs (shared per NIC) and decode the transfer handle from wr_id
    const int poll_batch_size = 64;  // Increased batch size for better efficiency
    struct ibv_wc wc_array[64];
    size_t num_nics = nic_contexts_.size();
    size_t num_candidate_nics = ctx.candidate_nic_indices.size();
    
    // Poll only candidate NICs for better performance
    for (size_t idx = 0; idx < num_candidate_nics; ++idx) {
        size_t nic = ctx.candidate_nic_indices[idx];
        auto &nic_ctx = *nic_contexts_[nic];
        int n = ibv_poll_cq(nic_ctx.cq, poll_batch_size, wc_array);
        if (n < 0) {
            fprintf(stderr, "MPComm: ibv_poll_cq failed on NIC %zu in async transfer\n", nic);
            return MPCOMM_ERR_TRANSFER;
        }
        for (int i = 0; i < n; ++i) {
            if (wc_array[i].status != IBV_WC_SUCCESS) {
                fprintf(stderr, "MPComm: WC error on NIC %zu in async transfer: status=%d, wr_id=0x%lx\n",
                        nic, wc_array[i].status, wc_array[i].wr_id);
                // Mark error on the transfer that owns this completion
                TransferHandle wc_handle = WrIdEncoding::decodeHandle(wc_array[i].wr_id);
                if (wc_handle == ctx.handle) {
                    return MPCOMM_ERR_TRANSFER;
                }
                // Error belongs to another transfer, mark it there
                std::lock_guard<std::mutex> lock(transfers_mutex_);
                auto it = active_transfers_.find(wc_handle);
                if (it != active_transfers_.end()) {
                    it->second->error_code.store(MPCOMM_ERR_TRANSFER);
                    it->second->finished.store(true);
                }
                continue;
            }
            
            // Decode nic_index, qp_index, and transfer_handle from wr_id
            size_t completed_nic = WrIdEncoding::decodeNic(wc_array[i].wr_id);
            size_t completed_qp = WrIdEncoding::decodeQp(wc_array[i].wr_id);
            TransferHandle wc_handle = WrIdEncoding::decodeHandle(wc_array[i].wr_id);
            
            // Route completion to the correct TransferContext
            if (wc_handle == ctx.handle) {
                // Completion belongs to current context
                if (completed_nic < num_nics) {
                    ctx.per_nic_completed[completed_nic]++;
                    if (completed_qp < qps_per_connection_) {
                        ctx.per_nic_qp_completed[completed_nic][completed_qp]++;
                    }
                }
                ctx.total_completed.fetch_add(1);
            } else {
                // Completion belongs to another transfer - route it there
                std::lock_guard<std::mutex> lock(transfers_mutex_);
                auto it = active_transfers_.find(wc_handle);
                if (it != active_transfers_.end()) {
                    TransferContext* other_ctx = it->second.get();
                    if (completed_nic < num_nics) {
                        other_ctx->per_nic_completed[completed_nic]++;
                        if (completed_qp < qps_per_connection_) {
                            other_ctx->per_nic_qp_completed[completed_nic][completed_qp]++;
                        }
                    }
                    other_ctx->total_completed.fetch_add(1);
                }
                // If transfer not found, completion is orphaned (transfer already released)
                // This is OK - just ignore it
            }
        }
    }
    return MPCOMM_SUCCESS;
}

int MPComm::transferAsyncProgress(TransferContext& ctx) {
    if (ctx.finished.load()) {
        return ctx.error_code.load();
    }
    
    const size_t max_outstanding_per_nic = 256 * qps_per_connection_;
    constexpr size_t kMaxOutstandingPerQP = 256;
    constexpr size_t kPollInterval = 64;  // Poll after every N posts for better batching
    
    size_t total_chunks = ctx.total_chunks.load();
    size_t posts_since_last_poll = 0;
    
    // Cache connection info to avoid repeated lock acquisitions
    // This is safe because connection info doesn't change during transfer
    // Key: (host_idx << 16) | local_nic, supports multi-host with up to 65536 NICs per host
    struct NicConnInfo {
        size_t remote_nic;
        uint32_t rkey;
    };
    std::unordered_map<uint64_t, NicConnInfo> nic_conn_cache;  // (host_idx, local_nic) -> cached info
    
    // Pre-cache connection info for all hosts and all candidate NICs
    {
        std::lock_guard<std::mutex> lock(connections_mutex_);
        for (size_t host_idx = 0; host_idx < ctx.host_list.size(); ++host_idx) {
            const std::string& host_id = ctx.host_list[host_idx];
            auto conn_it = connections_.find(host_id);
            if (conn_it != connections_.end()) {
                for (size_t local_nic : ctx.candidate_nic_indices) {
                    NicConnInfo info;
                    info.remote_nic = local_nic;  // Default: same index
                    const auto& nic_map = conn_it->second.local_to_remote_nic_map;
                    auto map_it = nic_map.find(local_nic);
                    if (map_it != nic_map.end() && !map_it->second.empty()) {
                        info.remote_nic = map_it->second[0];
                    }
                    // Get rkey for this host's remote_addr
                    info.rkey = conn_it->second.getRkeyForAddr(ctx.remote_addrs[host_idx], info.remote_nic);
                    uint64_t cache_key = (static_cast<uint64_t>(host_idx) << 16) | local_nic;
                    nic_conn_cache[cache_key] = info;
                }
            }
        }
    }
    
    // Post remaining chunks
    while (ctx.next_chunk_idx.load() < total_chunks) {
        size_t chunk_idx = ctx.next_chunk_idx.load();
        auto &chunk = ctx.all_chunks[chunk_idx];
        
        // Try to find a NIC with available slots (without polling first)
        size_t best_nic = selectBestNicForAsync(ctx);
        size_t outstanding = ctx.per_nic_posted[best_nic] - ctx.per_nic_completed[best_nic];
        
        // Only poll when NICs are getting full
        if (outstanding >= max_outstanding_per_nic) {
            // Poll to make room
            int poll_ret = pollAllNicsForAsync(ctx);
            if (poll_ret != MPCOMM_SUCCESS) {
                return poll_ret;
            }
            continue;  // Re-select NIC after polling
        }
        
        // Select QP with lowest outstanding within this NIC
        size_t qp_index = 0;
        size_t min_qp_outstanding = SIZE_MAX;
        bool found_available_qp = false;
        
        for (size_t qp = 0; qp < qps_per_connection_; ++qp) {
            size_t qp_outstanding = ctx.per_nic_qp_posted[best_nic][qp] - 
                                    ctx.per_nic_qp_completed[best_nic][qp];
            if (qp_outstanding < kMaxOutstandingPerQP && qp_outstanding < min_qp_outstanding) {
                min_qp_outstanding = qp_outstanding;
                qp_index = qp;
                found_available_qp = true;
            }
        }
        
        if (!found_available_qp) {
            // All QPs full, poll and retry
            pollAllNicsForAsync(ctx);
            continue;
        }
        
        // Get lkey for this NIC
        uint32_t lkey = getLkey(best_nic, reinterpret_cast<void *>(chunk.local_addr));
        if (lkey == 0) {
            fprintf(stderr, "MPComm: No lkey for address %p on NIC %zu\n",
                    reinterpret_cast<void *>(chunk.local_addr), best_nic);
            return MPCOMM_ERR_MEMORY;
        }
        
        // Use cached connection info (fast path)
        size_t host_idx_for_qp = chunk.host_idx;
        uint64_t cache_key = (static_cast<uint64_t>(host_idx_for_qp) << 16) | best_nic;
        auto cache_it = nic_conn_cache.find(cache_key);
        size_t remote_nic;
        uint32_t rkey;
        
        if (cache_it != nic_conn_cache.end()) {
            // Fast path: use cached info
            remote_nic = cache_it->second.remote_nic;
            rkey = cache_it->second.rkey;
        } else {
            // Slow path: lookup from connection (cache miss)
            const std::string& chunk_host_id = ctx.host_list[host_idx_for_qp];
            remote_nic = best_nic;
            
            {
                std::lock_guard<std::mutex> lock(connections_mutex_);
                auto it = connections_.find(chunk_host_id);
                if (it != connections_.end()) {
                    const auto& nic_map = it->second.local_to_remote_nic_map;
                    auto map_it = nic_map.find(best_nic);
                    if (map_it != nic_map.end() && !map_it->second.empty()) {
                        remote_nic = map_it->second[0];
                    }
                    rkey = it->second.getRkeyForAddr(chunk.remote_addr, remote_nic);
                } else {
                    rkey = 0;
                }
            }
        }
        
        if (rkey == 0) {
            fprintf(stderr, "MPComm: No rkey for remote NIC %zu (remote_addr=0x%lx)\n",
                    remote_nic, chunk.remote_addr);
            return MPCOMM_ERR_CONNECTION;
        }
        
        struct ibv_qp *qp = getOrCreateQP(best_nic, ctx.host_list[host_idx_for_qp], remote_nic, qp_index);
        if (!qp) {
            fprintf(stderr, "MPComm: No QP for local NIC %zu -> remote NIC %zu\n",
                    best_nic, remote_nic);
            return MPCOMM_ERR_CONNECTION;
        }
        
        // Prepare SGE and WR
        struct ibv_sge sge;
        memset(&sge, 0, sizeof(sge));
        sge.addr = chunk.local_addr;
        sge.length = static_cast<uint32_t>(chunk.length);
        sge.lkey = lkey;
        
        struct ibv_send_wr wr;
        memset(&wr, 0, sizeof(wr));
        // Encode nic_index, qp_index, transfer_handle, and chunk_index in wr_id
        // This enables routing completions to the correct TransferContext
        wr.wr_id = WrIdEncoding::encode(best_nic, qp_index, ctx.handle, chunk_idx);
        wr.opcode = ctx.is_scatter ? IBV_WR_RDMA_WRITE : IBV_WR_RDMA_READ;
        wr.sg_list = &sge;
        wr.num_sge = 1;
        wr.send_flags = IBV_SEND_SIGNALED;
        wr.wr.rdma.remote_addr = chunk.remote_addr;
        wr.wr.rdma.rkey = rkey;
        
        struct ibv_send_wr *bad_wr = nullptr;
        int ret = ibv_post_send(qp, &wr, &bad_wr);
        if (ret != 0) {
            fprintf(stderr, "MPComm: ibv_post_send failed on NIC %zu: %d\n", best_nic, ret);
            return MPCOMM_ERR_TRANSFER;
        }
        
        ctx.per_nic_posted[best_nic]++;
        ctx.per_nic_qp_posted[best_nic][qp_index]++;
        ctx.per_nic_bytes[best_nic] += chunk.length;
        ctx.next_chunk_idx.fetch_add(1);
        posts_since_last_poll++;
        
        // Proactive polling to release slots early (improves pipeline efficiency)
        if (posts_since_last_poll >= kPollInterval) {
            pollAllNicsForAsync(ctx);
            posts_since_last_poll = 0;
        }
    }
    
    // Check if all completions received
    if (ctx.total_completed.load() >= total_chunks) {
        ctx.finished.store(true);
        ctx.error_code.store(MPCOMM_SUCCESS);
        ctx.end_time = std::chrono::steady_clock::now();
        return MPCOMM_SUCCESS;
    }
    
    return MPCOMM_ERR_PENDING;
}

bool MPComm::isTransferComplete(TransferHandle handle) {
    TransferContext* ctx_ptr = nullptr;
    
    // First, quickly check if transfer exists and get pointer (with lock)
    {
        std::lock_guard<std::mutex> lock(transfers_mutex_);
        auto it = active_transfers_.find(handle);
        if (it == active_transfers_.end()) {
            return true;  // Invalid handle is considered "complete"
        }
        ctx_ptr = it->second.get();
        
        // If already finished, return immediately (still under lock)
        if (ctx_ptr->finished.load()) {
            return true;
        }
    }
    // Lock released here - safe to call pollAllNicsForAsync
    
    TransferContext& ctx = *ctx_ptr;
    
    // Poll for completions (without holding transfers_mutex_)
    int ret = pollAllNicsForAsync(ctx);
    if (ret != MPCOMM_SUCCESS) {
        ctx.error_code.store(ret);
        ctx.finished.store(true);
        ctx.end_time = std::chrono::steady_clock::now();
        return true;
    }
    
    // Check if all completions received
    size_t total_chunks = ctx.total_chunks.load();
    if (ctx.total_completed.load() >= total_chunks) {
        ctx.finished.store(true);
        ctx.error_code.store(MPCOMM_SUCCESS);
        ctx.end_time = std::chrono::steady_clock::now();
        return true;
    }
    
    return false;
}

int MPComm::waitTransfer(TransferHandle handle, int timeout_ms) {
    auto start_time = std::chrono::steady_clock::now();
    
    while (true) {
        if (isTransferComplete(handle)) {
            // Get the error code
            std::lock_guard<std::mutex> lock(transfers_mutex_);
            auto it = active_transfers_.find(handle);
            if (it == active_transfers_.end()) {
                return MPCOMM_ERR_INVALID_HANDLE;
            }
            return it->second->error_code.load();
        }
        
        // Check timeout
        if (timeout_ms >= 0) {
            auto elapsed = std::chrono::steady_clock::now() - start_time;
            auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
            if (elapsed_ms >= timeout_ms) {
                return MPCOMM_ERR_TIMEOUT;
            }
        }
        
        // Yield to avoid busy spinning
        std::this_thread::yield();
    }
}

TransferResult MPComm::getTransferResult(TransferHandle handle) {
    TransferResult result = {MPCOMM_ERR_INVALID_HANDLE, 0, 0.0};
    
    std::lock_guard<std::mutex> lock(transfers_mutex_);
    auto it = active_transfers_.find(handle);
    if (it == active_transfers_.end()) {
        return result;
    }
    
    TransferContext& ctx = *it->second;
    result.error_code = ctx.error_code.load();
    
    // Calculate bytes transferred
    size_t total_bytes = 0;
    for (size_t bytes : ctx.per_nic_bytes) {
        total_bytes += bytes;
    }
    result.bytes_transferred = total_bytes;
    
    // Calculate elapsed time
    auto end = ctx.finished.load() ? ctx.end_time : std::chrono::steady_clock::now();
    result.elapsed_ms = std::chrono::duration<double, std::milli>(end - ctx.start_time).count();
    
    return result;
}

void MPComm::releaseTransfer(TransferHandle handle) {
    std::lock_guard<std::mutex> lock(transfers_mutex_);
    auto it = active_transfers_.find(handle);
    if (it != active_transfers_.end()) {
        // Print statistics if transfer was completed
        TransferContext& ctx = *it->second;
        if (ctx.finished.load() && ctx.error_code.load() == MPCOMM_SUCCESS) {
            const char* op_name = ctx.is_scatter ? "ScatterAsync" : "GatherAsync";
            double transfer_ms = std::chrono::duration<double, std::milli>(
                ctx.end_time - ctx.start_time).count();
            
            size_t total_bytes = 0;
            for (size_t bytes : ctx.per_nic_bytes) {
                total_bytes += bytes;
            }
            double total_bandwidth_gbps = (total_bytes * 8.0) / (transfer_ms * 1e6);
            
            printf("\n========== %s Statistics (handle=%lu) ==========\n", op_name, handle);
            printf("%-20s %15s %12s %12s %12s\n", 
                   "NIC", "Bytes", "Chunks", "Share(%)", "BW(Gbps)");
            printf("------------------------------------------------------------------------\n");
            size_t num_nics = nic_contexts_.size();
            for (size_t nic = 0; nic < num_nics; ++nic) {
                double share_pct = (total_bytes > 0) ? 
                                   (100.0 * ctx.per_nic_bytes[nic] / total_bytes) : 0.0;
                double nic_bandwidth_gbps = (ctx.per_nic_bytes[nic] * 8.0) / (transfer_ms * 1e6);
                printf("%-20s %15zu %12zu %11.1f%% %12.2f\n",
                       nic_contexts_[nic]->device_name.c_str(),
                       ctx.per_nic_bytes[nic], ctx.per_nic_posted[nic], share_pct, nic_bandwidth_gbps);
            }
            printf("------------------------------------------------------------------------\n");
            printf("%-20s %15zu %12zu %12s %12.2f\n",
                   "Total", total_bytes, ctx.total_chunks.load(), "-", total_bandwidth_gbps);
            printf("Time: %.2f ms\n", transfer_ms);
            printf("==============================================================\n\n");
        }
        
        active_transfers_.erase(it);
    }
}

// ==================== End Async Transfer Implementation ====================

}  // namespace mpcomm
