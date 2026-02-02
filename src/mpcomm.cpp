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
#include <pthread.h>
#include <sched.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
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

        std::lock_guard<std::mutex> lock(ctx.mr_mutex);
        ctx.memory_regions.push_back(info);
    }

    printf("MPComm: Registered memory %p, length %zu\n", addr, length);
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
// Buffer Publishing and Query
// ============================================================================

int MPComm::publishBuffer(void *addr, size_t length) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    if (!addr || length == 0) return MPCOMM_ERR_INVALID_ARG;

    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    // Create or update published buffer info
    auto info = std::make_unique<PublishedBufferInfo>();
    info->addr = reinterpret_cast<uint64_t>(addr);
    info->length = length;
    
    // Get rkeys for all NICs
    info->rkeys.reserve(nic_contexts_.size());
    for (size_t i = 0; i < nic_contexts_.size(); ++i) {
        uint32_t rkey = getRkey(i, addr);
        if (rkey == 0) {
            fprintf(stderr, "MPComm: Buffer not registered on NIC %zu\n", i);
            return MPCOMM_ERR_MEMORY;
        }
        info->rkeys.push_back(rkey);
    }
    
    published_buffer_ = std::move(info);
    printf("MPComm: Published buffer addr=%p, length=%zu, rkeys=[",
           addr, length);
    for (size_t i = 0; i < published_buffer_->rkeys.size(); ++i) {
        printf("%u%s", published_buffer_->rkeys[i],
               i < published_buffer_->rkeys.size() - 1 ? "," : "");
    }
    printf("]\n");
    
    return MPCOMM_SUCCESS;
}

int MPComm::unpublishBuffer(void *addr) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    
    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    if (published_buffer_ && 
        published_buffer_->addr == reinterpret_cast<uint64_t>(addr)) {
        published_buffer_.reset();
        printf("MPComm: Unpublished buffer addr=%p\n", addr);
        return MPCOMM_SUCCESS;
    }
    
    return MPCOMM_ERR_INVALID_ARG;
}

int MPComm::queryRemoteBuffer(const std::string &remote_host_id,
                              const std::string &remote_tcp_addr,
                              int remote_tcp_port,
                              RemoteBufferInfo &out_info) {
    if (!initialized_) return MPCOMM_ERR_CONTEXT;

    printf("MPComm: Querying buffer from %s at %s:%d\n",
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

    // Receive response: success flag
    uint32_t success;
    if (recv(sock_fd, &success, sizeof(success), MSG_WAITALL) != sizeof(success)) {
        perror("MPComm: Failed to receive buffer query response");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    if (success == 0) {
        fprintf(stderr, "MPComm: Remote host has no published buffer\n");
        close(sock_fd);
        return MPCOMM_ERR_INVALID_ARG;
    }

    // Receive buffer address
    uint64_t buf_addr;
    if (recv(sock_fd, &buf_addr, sizeof(buf_addr), MSG_WAITALL) != sizeof(buf_addr)) {
        perror("MPComm: Failed to receive buffer address");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive buffer length
    uint64_t buf_length;
    if (recv(sock_fd, &buf_length, sizeof(buf_length), MSG_WAITALL) != sizeof(buf_length)) {
        perror("MPComm: Failed to receive buffer length");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive number of NICs
    uint32_t num_nics;
    if (recv(sock_fd, &num_nics, sizeof(num_nics), MSG_WAITALL) != sizeof(num_nics)) {
        perror("MPComm: Failed to receive num_nics");
        close(sock_fd);
        return MPCOMM_ERR_CONNECTION;
    }

    // Receive rkeys and GIDs, then match by GID
    std::vector<uint32_t> remote_rkeys(num_nics);
    std::vector<std::string> remote_gids(num_nics);
    for (uint32_t i = 0; i < num_nics; ++i) {
        // Receive rkey
        uint32_t rkey;
        if (recv(sock_fd, &rkey, sizeof(rkey), MSG_WAITALL) != sizeof(rkey)) {
            perror("MPComm: Failed to receive rkey");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        remote_rkeys[i] = rkey;
        // Receive GID (64 bytes to match RemoteEndpointInfo.gid)
        char gid_buf[64];
        if (recv(sock_fd, gid_buf, sizeof(gid_buf), MSG_WAITALL) != sizeof(gid_buf)) {
            perror("MPComm: Failed to receive GID");
            close(sock_fd);
            return MPCOMM_ERR_CONNECTION;
        }
        remote_gids[i] = std::string(gid_buf);
        printf("MPComm: Received NIC %u: rkey=%u, GID=%s\n", i, rkey, gid_buf);
    }

    close(sock_fd);

    // Match rkeys to connection endpoints by GID
    std::lock_guard<std::mutex> lock(connections_mutex_);
    auto conn_it = connections_.find(remote_host_id);
    if (conn_it != connections_.end()) {
        printf("MPComm: Matching rkeys for %zu endpoints\n", 
               conn_it->second.nic_endpoints.size());
        // For each NIC endpoint in the connection, find the matching rkey by GID
        for (size_t ep_idx = 0; ep_idx < conn_it->second.nic_endpoints.size(); ++ep_idx) {
            const std::string &ep_gid = conn_it->second.nic_endpoints[ep_idx].gid;
            printf("MPComm: Endpoint %zu has stored GID=%s\n", ep_idx, ep_gid.c_str());
            // Find matching remote GID
            bool matched = false;
            for (uint32_t remote_idx = 0; remote_idx < num_nics; ++remote_idx) {
                if (remote_gids[remote_idx] == ep_gid) {
                    conn_it->second.nic_endpoints[ep_idx].rkey = remote_rkeys[remote_idx];
                    printf("MPComm: Matched endpoint %zu (GID=%s) -> rkey=%u\n",
                           ep_idx, ep_gid.c_str(), remote_rkeys[remote_idx]);
                    matched = true;
                    break;
                }
            }
            if (!matched) {
                printf("MPComm: WARNING: No matching GID found for endpoint %zu\n", ep_idx);
            }
        }
    } else {
        printf("MPComm: WARNING: Connection not found for %s\n", remote_host_id.c_str());
    }

    // Fill output with raw remote info
    out_info.host_id = remote_host_id;
    out_info.addr = buf_addr;
    out_info.length = buf_length;
    out_info.rkeys = std::move(remote_rkeys);

    printf("MPComm: Received buffer info from %s: addr=0x%lx, length=%lu, rkeys=[",
           remote_host_id.c_str(), out_info.addr, out_info.length);
    for (size_t i = 0; i < out_info.rkeys.size(); ++i) {
        printf("%u%s", out_info.rkeys[i],
               i < out_info.rkeys.size() - 1 ? "," : "");
    }
    printf("]\n");

    return MPCOMM_SUCCESS;
}

const PublishedBufferInfo* MPComm::getPublishedBufferInfo() const {
    // Note: This is not thread-safe for simplicity
    return published_buffer_.get();
}

void MPComm::handleBufferQuery(int client_fd) {
    std::lock_guard<std::mutex> lock(published_buffer_mutex_);
    
    if (!published_buffer_) {
        uint32_t success = 0;
        send(client_fd, &success, sizeof(success), 0);
        return;
    }

    // Send success flag
    uint32_t success = 1;
    if (send(client_fd, &success, sizeof(success), 0) != sizeof(success)) {
        perror("MPComm: Failed to send success flag");
        return;
    }

    // Send buffer address
    uint64_t buf_addr = published_buffer_->addr;
    if (send(client_fd, &buf_addr, sizeof(buf_addr), 0) != sizeof(buf_addr)) {
        perror("MPComm: Failed to send buffer address");
        return;
    }

    // Send buffer length
    uint64_t buf_length = published_buffer_->length;
    if (send(client_fd, &buf_length, sizeof(buf_length), 0) != sizeof(buf_length)) {
        perror("MPComm: Failed to send buffer length");
        return;
    }

    // Send number of NICs (rkeys and GIDs)
    uint32_t num_nics = static_cast<uint32_t>(published_buffer_->rkeys.size());
    if (send(client_fd, &num_nics, sizeof(num_nics), 0) != sizeof(num_nics)) {
        perror("MPComm: Failed to send num_nics");
        return;
    }

    // Send rkeys and corresponding GIDs for matching
    for (uint32_t i = 0; i < num_nics; ++i) {
        // Send rkey
        uint32_t rkey = published_buffer_->rkeys[i];
        if (send(client_fd, &rkey, sizeof(rkey), 0) != sizeof(rkey)) {
            perror("MPComm: Failed to send rkey");
            return;
        }
        // Send GID string (for matching NIC on remote side)
        // Use same buffer size as RemoteEndpointInfo.gid (64 bytes)
        std::string gid_str = gidToString(nic_contexts_[i]->gid);
        char gid_buf[64];
        memset(gid_buf, 0, sizeof(gid_buf));
        strncpy(gid_buf, gid_str.c_str(), sizeof(gid_buf) - 1);
        if (send(client_fd, gid_buf, sizeof(gid_buf), 0) != sizeof(gid_buf)) {
            perror("MPComm: Failed to send GID");
            return;
        }
        printf("MPComm: Sending NIC %u: rkey=%u, GID=%s\n", i, rkey, gid_buf);
    }

    printf("MPComm: Sent buffer info to client: addr=0x%lx, length=%lu, num_nics=%u\n",
           buf_addr, buf_length, num_nics);
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

    // Exchange NIC info (min of local and remote NICs)
    size_t exchange_count = std::min(num_nics, remote_num_nics);
    conn_info.nic_endpoints.resize(exchange_count);

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

    for (size_t i = 0; i < exchange_count; ++i) {
        auto &ctx = *nic_contexts_[i];
        std::string key = remote_host_id + ":" + std::to_string(i);
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

            // Prepare local info
            RemoteEndpointInfo local_info;
            memset(&local_info, 0, sizeof(local_info));
            strncpy(local_info.gid, gidToString(ctx.gid).c_str(),
                    sizeof(local_info.gid) - 1);
            local_info.lid = ctx.lid;
            local_info.qp_num = qp->qp_num;
            // rkey will be filled when memory is registered

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

            printf("MPComm: NIC %zu QP[%zu]: Local QPN=%u, Remote QPN=%u\n",
                   i, qp_idx, local_info.qp_num, remote_info.qp_num);

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

            // Store first remote_info for endpoint (all QPs connect to same remote)
            if (qp_idx == 0) {
                conn_info.nic_endpoints[i] = remote_info;
            }
        }

        // Store QP list
        {
            std::lock_guard<std::mutex> lock(ctx.qp_mutex);
            ctx.qp_map[key] = std::move(qp_list);
        }
    }

    close(sock_fd);

    // Store connection info
    {
        std::lock_guard<std::mutex> lock(connections_mutex_);
        connections_[remote_host_id] = conn_info;
    }

    printf("MPComm: Connected to %s with %zu NICs, %zu QPs each\n",
           remote_host_id.c_str(), exchange_count, actual_qps);
    
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

        size_t exchange_count = std::min(num_nics, remote_num_nics);
        conn_info.nic_endpoints.resize(exchange_count);

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

        bool success = true;
        for (size_t i = 0; i < exchange_count && success; ++i) {
            auto &ctx = *nic_contexts_[i];
            std::string key = remote_host_id + ":" + std::to_string(i);
            std::vector<struct ibv_qp *> qp_list;
            qp_list.reserve(actual_qps);

            for (size_t qp_idx = 0; qp_idx < actual_qps && success; ++qp_idx) {
                // Receive remote info first (passive side)
                RemoteEndpointInfo remote_info;
                if (recv(client_fd, &remote_info, sizeof(remote_info),
                         MSG_WAITALL) != sizeof(remote_info)) {
                    perror("MPComm: Failed to receive remote_info");
                    success = false;
                    break;
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

                // Store first remote_info for endpoint
                if (qp_idx == 0) {
                    conn_info.nic_endpoints[i] = remote_info;
                }

                printf("MPComm: NIC %zu QP[%zu]: Passive side QPN=%u, Remote QPN=%u\n",
                       i, qp_idx, local_info.qp_num, remote_info.qp_num);
            }

            if (success) {
                // Store QP list
                std::lock_guard<std::mutex> lock(ctx.qp_mutex);
                ctx.qp_map[key] = std::move(qp_list);
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
            printf("MPComm: Passive connection established with %s (%zu QPs per NIC)\n",
                   remote_host_id.c_str(), actual_qps);
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

// Background poll thread function
void MPComm::asyncPollThreadFunc(AsyncRdmaContext *async_ctx) {
    struct ibv_wc wc_array[32];
    
    while (!async_ctx->finished.load()) {
        // Check if all chunks are completed
        size_t total = async_ctx->total_chunks.load();
        size_t completed = async_ctx->completed_chunks.load();
        
        if (total > 0 && completed >= total && async_ctx->post_finished.load()) {
            async_ctx->finished.store(true);
            break;
        }
        
        // Poll CQ for completions
        int n = ibv_poll_cq(async_ctx->cq, 32, wc_array);
        if (n < 0) {
            fprintf(stderr, "MPComm: ibv_poll_cq failed in poll thread\n");
            async_ctx->error_code.store(MPCOMM_ERR_TRANSFER);
            async_ctx->finished.store(true);
            break;
        }
        
        for (int i = 0; i < n; ++i) {
            if (wc_array[i].status != IBV_WC_SUCCESS) {
                fprintf(stderr, "MPComm: WC error in poll thread: status=%d, wr_id=%lu\n",
                        wc_array[i].status, wc_array[i].wr_id);
                async_ctx->error_code.store(MPCOMM_ERR_TRANSFER);
                async_ctx->finished.store(true);
                return;
            }
            
            // Update per-QP completed counter if in multi-QP mode
            // wr_id encoding: (qp_index << 56) | original_addr
            if (async_ctx->num_qps > 0) {
                size_t qp_index = (wc_array[i].wr_id >> 56) & 0xFF;
                if (qp_index < AsyncRdmaContext::MAX_QPS) {
                    async_ctx->per_qp_completed[qp_index].fetch_add(1);
                }
            }
            
            async_ctx->completed_chunks.fetch_add(1);
        }
        
        // If no completions and not all posted yet, yield to let post thread work
        if (n == 0) {
            std::this_thread::yield();
        }
    }
}

int MPComm::postRdmaWriteAsync(NicContext &ctx, struct ibv_qp *qp,
                               void *local_addr, uint32_t lkey,
                               uint64_t remote_addr, uint32_t rkey,
                               size_t length, AsyncRdmaContext &async_ctx) {
    // Initialize async context
    async_ctx.total_chunks.store(0);
    async_ctx.posted_chunks.store(0);
    async_ctx.completed_chunks.store(0);
    async_ctx.error_code.store(0);
    async_ctx.post_finished.store(false);
    async_ctx.finished.store(false);
    async_ctx.cq = ctx.cq;

    // Calculate number of chunks needed
    size_t num_chunks = (length + max_rdma_transfer_size_ - 1) / max_rdma_transfer_size_;
    async_ctx.total_chunks.store(num_chunks);

    // Start background poll thread
    async_ctx.poll_thread = std::thread(asyncPollThreadFunc, &async_ctx);

    // Flow control: max outstanding WRs (leave headroom from kMaxSendWR=512)
    const size_t max_outstanding = 256;

    // Post chunks with flow control
    size_t offset = 0;
    for (size_t chunk_idx = 0; chunk_idx < num_chunks; ++chunk_idx) {
        // Flow control: wait if too many outstanding WRs
        while (async_ctx.posted_chunks.load() - async_ctx.completed_chunks.load() >= max_outstanding) {
            if (async_ctx.error_code.load() != 0) {
                // Poll thread detected an error
                async_ctx.post_finished.store(true);
                if (async_ctx.poll_thread.joinable()) {
                    async_ctx.poll_thread.join();
                }
                return async_ctx.error_code.load();
            }
            std::this_thread::yield();
        }

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
            fprintf(stderr, "MPComm: ibv_post_send (WRITE async) failed: %d, "
                    "chunk_idx=%zu, chunk_offset=%zu, chunk_size=%zu\n",
                    ret, chunk_idx, offset, chunk_size);
            async_ctx.error_code.store(MPCOMM_ERR_TRANSFER);
            async_ctx.post_finished.store(true);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_TRANSFER;
        }

        async_ctx.posted_chunks.fetch_add(1);
        offset += chunk_size;
    }

    // All chunks posted
    async_ctx.post_finished.store(true);
    return MPCOMM_SUCCESS;
}

int MPComm::postRdmaReadAsync(NicContext &ctx, struct ibv_qp *qp,
                              void *local_addr, uint32_t lkey,
                              uint64_t remote_addr, uint32_t rkey,
                              size_t length, AsyncRdmaContext &async_ctx) {
    // Initialize async context
    async_ctx.total_chunks.store(0);
    async_ctx.posted_chunks.store(0);
    async_ctx.completed_chunks.store(0);
    async_ctx.error_code.store(0);
    async_ctx.post_finished.store(false);
    async_ctx.finished.store(false);
    async_ctx.cq = ctx.cq;

    // Calculate number of chunks needed
    size_t num_chunks = (length + max_rdma_transfer_size_ - 1) / max_rdma_transfer_size_;
    async_ctx.total_chunks.store(num_chunks);

    // Start background poll thread
    async_ctx.poll_thread = std::thread(asyncPollThreadFunc, &async_ctx);

    // Flow control: max outstanding WRs (leave headroom from kMaxSendWR=512)
    const size_t max_outstanding = 256;

    // Post chunks with flow control
    size_t offset = 0;
    for (size_t chunk_idx = 0; chunk_idx < num_chunks; ++chunk_idx) {
        // Flow control: wait if too many outstanding WRs
        while (async_ctx.posted_chunks.load() - async_ctx.completed_chunks.load() >= max_outstanding) {
            if (async_ctx.error_code.load() != 0) {
                // Poll thread detected an error
                async_ctx.post_finished.store(true);
                if (async_ctx.poll_thread.joinable()) {
                    async_ctx.poll_thread.join();
                }
                return async_ctx.error_code.load();
            }
            std::this_thread::yield();
        }

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
            fprintf(stderr, "MPComm: ibv_post_send (READ async) failed: %d, "
                    "chunk_idx=%zu, chunk_offset=%zu, chunk_size=%zu\n",
                    ret, chunk_idx, offset, chunk_size);
            async_ctx.error_code.store(MPCOMM_ERR_TRANSFER);
            async_ctx.post_finished.store(true);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_TRANSFER;
        }

        async_ctx.posted_chunks.fetch_add(1);
        offset += chunk_size;
    }

    // All chunks posted
    async_ctx.post_finished.store(true);
    return MPCOMM_SUCCESS;
}

int MPComm::postRdmaWriteAsyncMultiQP(NicContext &ctx, const std::string &host_id,
                                      size_t nic_index, void *local_addr, uint32_t lkey,
                                      uint64_t remote_addr, uint32_t rkey,
                                      size_t length, AsyncRdmaContext &async_ctx) {
    // Initialize async context
    async_ctx.total_chunks.store(0);
    async_ctx.posted_chunks.store(0);
    async_ctx.completed_chunks.store(0);
    async_ctx.error_code.store(0);
    async_ctx.post_finished.store(false);
    async_ctx.finished.store(false);
    async_ctx.cq = ctx.cq;
    
    // Enable multi-QP mode with per-QP tracking
    async_ctx.num_qps = qps_per_connection_;
    for (size_t i = 0; i < AsyncRdmaContext::MAX_QPS; ++i) {
        async_ctx.per_qp_completed[i].store(0);
    }

    // Calculate number of chunks needed
    size_t num_chunks = (length + max_rdma_transfer_size_ - 1) / max_rdma_transfer_size_;
    async_ctx.total_chunks.store(num_chunks);

    // Start background poll thread
    async_ctx.poll_thread = std::thread(asyncPollThreadFunc, &async_ctx);

    // Flow control: max outstanding WRs per QP (leave headroom from kMaxSendWR=512)
    // kMaxSendWR is 512 in createQP, so we use 256 to leave headroom
    const size_t max_outstanding_per_qp = 256;
    
    // Per-QP posted counters for proper flow control
    // Now using accurate per-QP completed counters from poll thread (via wr_id encoding)
    std::vector<size_t> per_qp_posted(qps_per_connection_, 0);

    // Post chunks with flow control, rotating across all QPs for this NIC
    size_t offset = 0;
    for (size_t chunk_idx = 0; chunk_idx < num_chunks; ++chunk_idx) {
        // Round-robin QP selection for each chunk/slice
        size_t qp_index = chunk_idx % qps_per_connection_;
        
        // Per-QP flow control using accurate per-QP completed counters
        size_t qp_completed = async_ctx.per_qp_completed[qp_index].load();
        size_t qp_outstanding = per_qp_posted[qp_index] > qp_completed ? 
                                per_qp_posted[qp_index] - qp_completed : 0;
        
        // Wait if this specific QP has too many outstanding WRs
        while (qp_outstanding >= max_outstanding_per_qp) {
            if (async_ctx.error_code.load() != 0) {
                async_ctx.post_finished.store(true);
                if (async_ctx.poll_thread.joinable()) {
                    async_ctx.poll_thread.join();
                }
                return async_ctx.error_code.load();
            }
            std::this_thread::yield();
            
            // Re-read accurate per-QP completed counter after yield
            qp_completed = async_ctx.per_qp_completed[qp_index].load();
            qp_outstanding = per_qp_posted[qp_index] > qp_completed ? 
                             per_qp_posted[qp_index] - qp_completed : 0;
        }
        struct ibv_qp *qp = getOrCreateQP(nic_index, host_id, nic_index, qp_index);
        if (!qp) {
            fprintf(stderr, "MPComm: No QP for %s on NIC %zu (qp_index=%zu)\n",
                    host_id.c_str(), nic_index, qp_index);
            async_ctx.error_code.store(MPCOMM_ERR_CONNECTION);
            async_ctx.post_finished.store(true);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_CONNECTION;
        }

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
        // Encode qp_index in upper 8 bits of wr_id for poll thread to track per-QP completions
        // wr_id = (qp_index << 56) | (addr & 0x00FFFFFFFFFFFFFF)
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
            fprintf(stderr, "MPComm: ibv_post_send (WRITE async multi-QP) failed: %d, "
                    "chunk_idx=%zu, qp_index=%zu, chunk_offset=%zu, chunk_size=%zu\n",
                    ret, chunk_idx, qp_index, offset, chunk_size);
            async_ctx.error_code.store(MPCOMM_ERR_TRANSFER);
            async_ctx.post_finished.store(true);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_TRANSFER;
        }

        per_qp_posted[qp_index]++;
        async_ctx.posted_chunks.fetch_add(1);
        offset += chunk_size;
    }

    // All chunks posted
    async_ctx.post_finished.store(true);
    return MPCOMM_SUCCESS;
}

int MPComm::postRdmaReadAsyncMultiQP(NicContext &ctx, const std::string &host_id,
                                     size_t nic_index, void *local_addr, uint32_t lkey,
                                     uint64_t remote_addr, uint32_t rkey,
                                     size_t length, AsyncRdmaContext &async_ctx) {
    // Initialize async context
    async_ctx.total_chunks.store(0);
    async_ctx.posted_chunks.store(0);
    async_ctx.completed_chunks.store(0);
    async_ctx.error_code.store(0);
    async_ctx.post_finished.store(false);
    async_ctx.finished.store(false);
    async_ctx.cq = ctx.cq;
    
    // Enable multi-QP mode with per-QP tracking
    async_ctx.num_qps = qps_per_connection_;
    for (size_t i = 0; i < AsyncRdmaContext::MAX_QPS; ++i) {
        async_ctx.per_qp_completed[i].store(0);
    }

    // Calculate number of chunks needed
    size_t num_chunks = (length + max_rdma_transfer_size_ - 1) / max_rdma_transfer_size_;
    async_ctx.total_chunks.store(num_chunks);

    // Start background poll thread
    async_ctx.poll_thread = std::thread(asyncPollThreadFunc, &async_ctx);

    // Flow control: max outstanding WRs per QP (leave headroom from kMaxSendWR=512)
    // kMaxSendWR is 512 in createQP, so we use 256 to leave headroom
    const size_t max_outstanding_per_qp = 256;
    
    // Per-QP posted counters for proper flow control
    // Now using accurate per-QP completed counters from poll thread (via wr_id encoding)
    std::vector<size_t> per_qp_posted(qps_per_connection_, 0);

    // Post chunks with flow control, rotating across all QPs for this NIC
    size_t offset = 0;
    for (size_t chunk_idx = 0; chunk_idx < num_chunks; ++chunk_idx) {
        // Round-robin QP selection for each chunk/slice
        size_t qp_index = chunk_idx % qps_per_connection_;
        
        // Per-QP flow control using accurate per-QP completed counters
        size_t qp_completed = async_ctx.per_qp_completed[qp_index].load();
        size_t qp_outstanding = per_qp_posted[qp_index] > qp_completed ? 
                                per_qp_posted[qp_index] - qp_completed : 0;
        
        // Wait if this specific QP has too many outstanding WRs
        while (qp_outstanding >= max_outstanding_per_qp) {
            if (async_ctx.error_code.load() != 0) {
                async_ctx.post_finished.store(true);
                if (async_ctx.poll_thread.joinable()) {
                    async_ctx.poll_thread.join();
                }
                return async_ctx.error_code.load();
            }
            std::this_thread::yield();
            
            // Re-read accurate per-QP completed counter after yield
            qp_completed = async_ctx.per_qp_completed[qp_index].load();
            qp_outstanding = per_qp_posted[qp_index] > qp_completed ? 
                             per_qp_posted[qp_index] - qp_completed : 0;
        }

        struct ibv_qp *qp = getOrCreateQP(nic_index, host_id, nic_index, qp_index);
        if (!qp) {
            fprintf(stderr, "MPComm: No QP for %s on NIC %zu (qp_index=%zu)\n",
                    host_id.c_str(), nic_index, qp_index);
            async_ctx.error_code.store(MPCOMM_ERR_CONNECTION);
            async_ctx.post_finished.store(true);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_CONNECTION;
        }

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
        // Encode qp_index in upper 8 bits of wr_id for poll thread to track per-QP completions
        // wr_id = (qp_index << 56) | (addr & 0x00FFFFFFFFFFFFFF)
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
            fprintf(stderr, "MPComm: ibv_post_send (READ async multi-QP) failed: %d, "
                    "chunk_idx=%zu, qp_index=%zu, chunk_offset=%zu, chunk_size=%zu\n",
                    ret, chunk_idx, qp_index, offset, chunk_size);
            async_ctx.error_code.store(MPCOMM_ERR_TRANSFER);
            async_ctx.post_finished.store(true);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_TRANSFER;
        }

        per_qp_posted[qp_index]++;
        async_ctx.posted_chunks.fetch_add(1);
        offset += chunk_size;
    }

    // All chunks posted
    async_ctx.post_finished.store(true);
    return MPCOMM_SUCCESS;
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

int MPComm::pollAsyncCompletion(NicContext &ctx, AsyncRdmaContext &async_ctx) {
    (void)ctx;  // Poll thread already polls the CQ
    
    if (async_ctx.finished.load()) {
        // Join poll thread if not already joined
        if (async_ctx.poll_thread.joinable()) {
            async_ctx.poll_thread.join();
        }
        return async_ctx.error_code.load();
    }

    // Check if all chunks completed
    if (async_ctx.completed_chunks.load() >= async_ctx.total_chunks.load() &&
        async_ctx.post_finished.load()) {
        async_ctx.finished.store(true);
        if (async_ctx.poll_thread.joinable()) {
            async_ctx.poll_thread.join();
        }
        return MPCOMM_SUCCESS;
    }

    // Still in progress
    return MPCOMM_ERR_TIMEOUT;
}

int MPComm::waitAsyncCompletion(NicContext &ctx, AsyncRdmaContext &async_ctx,
                                int timeout_ms) {
    (void)ctx;  // Poll thread already polls the CQ
    
    if (async_ctx.finished.load()) {
        if (async_ctx.poll_thread.joinable()) {
            async_ctx.poll_thread.join();
        }
        return async_ctx.error_code.load();
    }

    auto start = std::chrono::steady_clock::now();

    while (!async_ctx.finished.load()) {
        // Check if all chunks completed
        if (async_ctx.completed_chunks.load() >= async_ctx.total_chunks.load() &&
            async_ctx.post_finished.load()) {
            async_ctx.finished.store(true);
            break;
        }

        // Check for errors
        int err = async_ctx.error_code.load();
        if (err != 0) {
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return err;
        }

        // Check timeout
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - start).count();
        if (elapsed >= timeout_ms) {
            fprintf(stderr, "MPComm: Async wait timeout after %dms, "
                    "completed=%zu/%zu, posted=%zu\n",
                    timeout_ms, async_ctx.completed_chunks.load(),
                    async_ctx.total_chunks.load(), async_ctx.posted_chunks.load());
            async_ctx.error_code.store(MPCOMM_ERR_TIMEOUT);
            async_ctx.finished.store(true);
            if (async_ctx.poll_thread.joinable()) {
                async_ctx.poll_thread.join();
            }
            return MPCOMM_ERR_TIMEOUT;
        }

        // Brief yield
        std::this_thread::yield();
    }

    // Join poll thread
    if (async_ctx.poll_thread.joinable()) {
        async_ctx.poll_thread.join();
    }

    return async_ctx.error_code.load();
}

struct ibv_qp *MPComm::getOrCreateQP(size_t local_nic_index,
                                     const std::string &remote_host_id,
                                     size_t remote_nic_index,
                                     size_t qp_index) {
    if (local_nic_index >= nic_contexts_.size()) {
        return nullptr;
    }

    auto &ctx = *nic_contexts_[local_nic_index];
    std::string key = remote_host_id + ":" + std::to_string(remote_nic_index);

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

// ============================================================================
// Scatter / Gather Implementation
// ============================================================================

int MPComm::transferImpl(uintptr_t local_addr,
                         const std::vector<std::string> &host_list,
                         const std::vector<uintptr_t> &remote_addrs,
                         const std::vector<size_t> &lengths,
                         int num_threads,
                         TransferDirection direction) {
    // Transfer operation name for logging
    const char* op_name = (direction == TransferDirection::SCATTER) ? "Scatter" : "Gather";
    
    // Timing: function entry
    auto t_start = std::chrono::steady_clock::now();
    
    if (!initialized_) return MPCOMM_ERR_CONTEXT;
    
    size_t host_count = host_list.size();
    if (host_count == 0 || remote_addrs.size() != host_count ||
        lengths.size() != host_count) {
        return MPCOMM_ERR_INVALID_ARG;
    }

    // Timing: after validation
    auto t_after_validation = std::chrono::steady_clock::now();

    // Thread count: use user-specified value, default to NIC count
    size_t num_nics = nic_contexts_.size();
    size_t actual_num_threads = (num_threads > 0) ? static_cast<size_t>(num_threads) : num_nics;
    
    // Each thread is assigned a NIC in round-robin fashion:
    // thread 0 -> NIC 0, thread 1 -> NIC 1, thread 2 -> NIC 0, ...
    auto getThreadNic = [num_nics](size_t thread_id) -> size_t {
        return thread_id % num_nics;
    };

    // Prepare transfer sub-tasks: each host transfer is split across all threads
    // Each thread handles a portion of the data using its assigned NIC
    struct TransferSubTask {
        std::string host_id;
        uintptr_t local_chunk_addr;
        uintptr_t remote_addr;
        size_t length;
        size_t thread_id;   // Which thread handles this sub-task
        size_t nic_index;   // Which NIC to use (derived from thread_id)
    };

    // Create sub-tasks: for each host, split data across all threads
    std::vector<TransferSubTask> tasks;
    tasks.reserve(host_count * actual_num_threads);

    size_t local_offset = 0;
    for (size_t i = 0; i < host_count; ++i) {
        size_t total_len = lengths[i];
        size_t per_thread_len = total_len / actual_num_threads;
        size_t remainder = total_len % actual_num_threads;
        
        size_t host_local_offset = 0;
        for (size_t tid = 0; tid < actual_num_threads; ++tid) {
            TransferSubTask task;
            task.host_id = host_list[i];
            // Distribute remainder to first threads
            size_t this_len = per_thread_len + (tid < remainder ? 1 : 0);
            if (this_len == 0) continue;  // Skip if no data for this thread
            
            task.local_chunk_addr = local_addr + local_offset + host_local_offset;
            task.remote_addr = remote_addrs[i] + host_local_offset;
            task.length = this_len;
            task.thread_id = tid;
            task.nic_index = getThreadNic(tid);
            tasks.push_back(std::move(task));
            host_local_offset += this_len;
        }
        local_offset += lengths[i];
    }

    // Timing: after task preparation
    auto t_after_task_prep = std::chrono::steady_clock::now();

    // Get remote rkey (from connection info)
    auto getRkey = [this](const std::string &host_id, size_t nic_index) -> uint32_t {
        std::lock_guard<std::mutex> lock(connections_mutex_);
        auto it = connections_.find(host_id);
        if (it == connections_.end()) return 0;
        if (nic_index >= it->second.nic_endpoints.size()) return 0;
        return it->second.nic_endpoints[nic_index].rkey;
    };

    // Atomic error flag
    std::atomic<int> global_error{0};

    // Per-thread statistics
    struct ThreadStats {
        size_t thread_id;
        std::string nic_name;
        size_t total_bytes;
        double elapsed_ms;
        double bandwidth_gbps;
    };
    std::vector<ThreadStats> thread_stats(actual_num_threads);
    std::mutex stats_mutex;

    // Worker function: each thread handles all sub-tasks assigned to it
    // Using synchronous Post-Poll loop (no separate poll thread)
    auto workerFunc = [this, &tasks, &global_error, &getRkey, &thread_stats,
                       &stats_mutex, actual_num_threads, &getThreadNic, direction, op_name](size_t thread_id) {
        // Record start time
        auto start_time = std::chrono::steady_clock::now();
        size_t nic_index = getThreadNic(thread_id);
        std::string nic_name = nic_contexts_[nic_index]->device_name;
        size_t total_bytes = 0;

        for (size_t i = 0; i < tasks.size() && global_error == 0; ++i) {
            auto &task = tasks[i];
            // Each thread only handles sub-tasks assigned to it
            if (task.thread_id != thread_id) continue;
            
            nic_index = task.nic_index;
            auto &ctx = *nic_contexts_[nic_index];

            // Get lkey
            uint32_t lkey = getLkey(nic_index,
                                    reinterpret_cast<void *>(task.local_chunk_addr));
            if (lkey == 0) {
                fprintf(stderr, "MPComm: No lkey for address %p\n",
                        reinterpret_cast<void *>(task.local_chunk_addr));
                global_error = MPCOMM_ERR_MEMORY;
                return;
            }

            // Get rkey
            uint32_t rkey = getRkey(task.host_id, nic_index);
            if (rkey == 0) {
                fprintf(stderr, "MPComm: No rkey for %s\n",
                        task.host_id.c_str());
                global_error = MPCOMM_ERR_CONNECTION;
                return;
            }

            printf("MPComm: %s sub-task %zu: host=%s, thread=%zu, nic=%zu, "
                   "local=%p, remote=0x%lx, len=%zu, lkey=%u, rkey=%u\n",
                   op_name, i, task.host_id.c_str(), thread_id, nic_index,
                   reinterpret_cast<void *>(task.local_chunk_addr),
                   task.remote_addr, task.length, lkey, rkey);

            // Synchronous RDMA operation with Post-Poll loop
            int ret;
            if (direction == TransferDirection::SCATTER) {
                ret = rdmaWriteSyncMultiQP(ctx, task.host_id, nic_index,
                                           reinterpret_cast<void *>(task.local_chunk_addr),
                                           lkey, task.remote_addr, rkey, task.length);
            } else {
                ret = rdmaReadSyncMultiQP(ctx, task.host_id, nic_index,
                                          reinterpret_cast<void *>(task.local_chunk_addr),
                                          lkey, task.remote_addr, rkey, task.length);
            }
            if (ret != 0) {
                global_error = ret;
                return;
            }
            total_bytes += task.length;
        }

        // Record end time and calculate statistics
        auto end_time = std::chrono::steady_clock::now();
        double elapsed_ms = std::chrono::duration<double, std::milli>(end_time - start_time).count();
        double bandwidth_gbps = (total_bytes * 8.0) / (elapsed_ms * 1e6);  // Gbps

        // Store stats
        {
            std::lock_guard<std::mutex> lock(stats_mutex);
            thread_stats[thread_id].thread_id = thread_id;
            thread_stats[thread_id].nic_name = nic_name;
            thread_stats[thread_id].total_bytes = total_bytes;
            thread_stats[thread_id].elapsed_ms = elapsed_ms;
            thread_stats[thread_id].bandwidth_gbps = bandwidth_gbps;
        }
    };

    // Timing: after lambda definitions
    auto t_after_lambda = std::chrono::steady_clock::now();

    // Submit tasks to thread pool
    size_t pool_size = thread_pool_->size();
    for (size_t tid = 0; tid < actual_num_threads; ++tid) {
        size_t worker_id = tid % pool_size;
        thread_pool_->submitToThread(worker_id, [&workerFunc, tid]() {
            workerFunc(tid);
        });
    }

    // Timing: after submit
    auto t_after_submit = std::chrono::steady_clock::now();

    // Wait for all tasks to complete
    thread_pool_->waitAll();

    // Timing: after wait
    auto t_after_wait = std::chrono::steady_clock::now();

    // Print per-thread statistics
    printf("\n========== %s Statistics ==========\n", op_name);
    printf("%-8s %-20s %15s %12s %12s\n", 
           "Thread", "NIC", "Bytes", "Time(ms)", "BW(Gbps)");
    printf("--------------------------------------------------------\n");
    size_t total_bytes_all = 0;
    double max_elapsed_ms = 0.0;
    for (const auto &stat : thread_stats) {
        printf("%-8zu %-20s %15zu %12.2f %12.2f\n",
               stat.thread_id, stat.nic_name.c_str(), stat.total_bytes,
               stat.elapsed_ms, stat.bandwidth_gbps);
        total_bytes_all += stat.total_bytes;
        if (stat.elapsed_ms > max_elapsed_ms) {
            max_elapsed_ms = stat.elapsed_ms;
        }
    }
    double total_bandwidth_gbps = (total_bytes_all * 8.0) / (max_elapsed_ms * 1e6);
    printf("--------------------------------------------------------\n");
    printf("%-8s %-20s %15zu %12.2f %12.2f\n",
           "Total", "-", total_bytes_all, max_elapsed_ms, total_bandwidth_gbps);
    printf("=========================================\n\n");

    // Timing: after print stats
    auto t_end = std::chrono::steady_clock::now();

    // Print overhead timing (in microseconds)
    auto us = [](auto start, auto end) {
        return std::chrono::duration<double, std::micro>(end - start).count();
    };
    printf("========== %s Overhead (us) ==========\n", op_name);
    printf("  Validation:        %10.2f us\n", us(t_start, t_after_validation));
    printf("  Task preparation:  %10.2f us\n", us(t_after_validation, t_after_task_prep));
    printf("  Lambda definition: %10.2f us\n", us(t_after_task_prep, t_after_lambda));
    printf("  Thread pool submit:%10.2f us\n", us(t_after_lambda, t_after_submit));
    printf("  Worker execution:  %10.2f us\n", us(t_after_submit, t_after_wait));
    printf("  Print stats:       %10.2f us\n", us(t_after_wait, t_end));
    printf("  -----------------------------------\n");
    printf("  Total overhead:    %10.2f us (excl. worker)\n", 
           us(t_start, t_after_submit) + us(t_after_wait, t_end));
    printf("  Total function:    %10.2f us\n", us(t_start, t_end));
    printf("===========================================\n\n");

    return global_error.load();
}

int MPComm::scatter(uintptr_t local_addr,
                    const std::vector<std::string> &host_list,
                    const std::vector<uintptr_t> &remote_addrs,
                    const std::vector<size_t> &lengths,
                    int num_threads) {
    return transferImpl(local_addr, host_list, remote_addrs, lengths,
                        num_threads, TransferDirection::SCATTER);
}

int MPComm::gather(uintptr_t local_addr,
                   const std::vector<std::string> &host_list,
                   const std::vector<uintptr_t> &remote_addrs,
                   const std::vector<size_t> &lengths,
                   int num_threads) {
    return transferImpl(local_addr, host_list, remote_addrs, lengths,
                        num_threads, TransferDirection::GATHER);
}

}  // namespace mpcomm
