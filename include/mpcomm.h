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

#ifndef MPCOMM_MPCOMM_H_
#define MPCOMM_MPCOMM_H_

#include <infiniband/verbs.h>
#include <stdint.h>
#include <string.h>

// Vendor-specific headers for QP UDP source port modification
#ifdef USE_MLNX
#include <infiniband/mlx5dv.h>
#elif defined(USE_BNXT)
#include <infiniband/bnxt_re_dv.h>
#endif

#include <atomic>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace mpcomm {

// Error codes
enum MPCommError {
    MPCOMM_SUCCESS = 0,
    MPCOMM_ERR_DEVICE = -1,
    MPCOMM_ERR_CONTEXT = -2,
    MPCOMM_ERR_MEMORY = -3,
    MPCOMM_ERR_CONNECTION = -4,
    MPCOMM_ERR_TRANSFER = -5,
    MPCOMM_ERR_TIMEOUT = -6,
    MPCOMM_ERR_INVALID_ARG = -7,
};

// Maximum size for a single RDMA transfer (default: 1 GB)
// InfiniBand hardware typically limits single RDMA operations to 1 GB
// Larger transfers are automatically split into chunks
// Can be configured via environment variable MPCOMM_MAX_RDMA_TRANSFER_SIZE
// Value should be in bytes (e.g., 1073741824 for 1GB, 536870912 for 512MB)
static constexpr size_t MPCOMM_DEFAULT_MAX_RDMA_TRANSFER_SIZE = 1ULL << 30;  // 1 GB

// Number of QPs per NIC per connection (default: 1)
// Can be configured via environment variable MPCOMM_QPS_PER_CONNECTION
// Higher values can improve throughput by utilizing more hardware parallelism
static constexpr size_t MPCOMM_DEFAULT_QPS_PER_CONNECTION = 1;

// Get the number of QPs per connection (reads from env var or uses default)
size_t getQpsPerConnection();

// Get the actual max RDMA transfer size (reads from env var or uses default)
size_t getMaxRdmaTransferSize();

// Remote endpoint information exchanged via TCP
struct RemoteEndpointInfo {
    char gid[64];           // GID as hex string (xx:xx:...:xx format, 47 chars + null)
    uint16_t lid;           // Local ID
    uint32_t qp_num;        // Queue Pair number
    uint32_t rkey;          // Remote key for RDMA access
    uint64_t addr;          // Remote buffer address
    uint64_t length;        // Remote buffer length
};

// Memory region info
struct MemoryRegionInfo {
    void *addr;
    size_t length;
    struct ibv_mr *mr;
    uint32_t lkey;
    uint32_t rkey;
};

// Per-NIC context (one per RDMA device)
struct NicContext {
    std::string device_name;
    struct ibv_context *context;
    struct ibv_pd *pd;
    struct ibv_cq *cq;
    uint8_t port;
    int gid_index;
    uint16_t lid;
    union ibv_gid gid;
    
    // Memory regions registered on this NIC
    std::vector<MemoryRegionInfo> memory_regions;
    std::mutex mr_mutex;
    
    // QPs to remote hosts (key: "host:nic_index", value: list of QPs)
    // Each connection can have multiple QPs for better parallelism
    std::unordered_map<std::string, std::vector<struct ibv_qp *>> qp_map;
    std::mutex qp_mutex;
};

// Connection info for a remote host
struct ConnectionInfo {
    std::string host_id;
    int tcp_port;
    std::vector<RemoteEndpointInfo> nic_endpoints;  // One per remote NIC
};

// Published buffer information (for metadata exchange)
struct PublishedBufferInfo {
    uint64_t addr;              // Buffer address
    uint64_t length;            // Buffer length
    std::vector<uint32_t> rkeys;  // Remote keys for each NIC
};

// Forward declaration for thread pool
class ThreadPool;

// Remote buffer info received from peer
struct RemoteBufferInfo {
    std::string host_id;        // Remote host identifier
    uint64_t addr;              // Remote buffer address
    uint64_t length;            // Remote buffer length
    std::vector<uint32_t> rkeys;  // Remote keys for each NIC
};

// Async RDMA operation context
// Used to track the state of an asynchronous RDMA transfer
struct AsyncRdmaContext {
    std::atomic<size_t> total_chunks;      // Total number of chunks to post
    std::atomic<size_t> posted_chunks;     // Number of chunks posted so far
    std::atomic<size_t> completed_chunks;  // Number of chunks completed
    std::atomic<int> error_code;           // Error code (0 if no error)
    std::atomic<bool> post_finished;       // True when all chunks are posted
    std::atomic<bool> finished;            // True when all chunks completed or error
    struct ibv_cq *cq;                     // CQ for poll thread to poll
    std::thread poll_thread;               // Background poll thread
    
    // Per-QP completed counters for multi-QP flow control
    // wr_id encoding: (qp_index << 56) | original_addr
    // This allows poll thread to accurately track completions per QP
    static constexpr size_t MAX_QPS = 16;
    std::atomic<size_t> per_qp_completed[MAX_QPS];
    size_t num_qps;                        // Number of QPs in use (0 for single-QP mode)

    AsyncRdmaContext() : total_chunks(0), posted_chunks(0), completed_chunks(0),
                         error_code(0), post_finished(false), finished(false), 
                         cq(nullptr), num_qps(0) {
        for (size_t i = 0; i < MAX_QPS; ++i) {
            per_qp_completed[i].store(0);
        }
    }
    
    // Disable copy, enable move
    AsyncRdmaContext(const AsyncRdmaContext&) = delete;
    AsyncRdmaContext& operator=(const AsyncRdmaContext&) = delete;
    AsyncRdmaContext(AsyncRdmaContext&&) = default;
    AsyncRdmaContext& operator=(AsyncRdmaContext&&) = default;
};

/**
 * MPComm - Multi-Path Communication using native ibverbs
 * 
 * This class implements scatter/gather operations across multiple hosts
 * using multiple NICs, without depending on mooncake's TransferEngine.
 * 
 * Each thread directly calls ibv_post_send for data transfer.
 * 
 * Environment Variables:
 *   MPCOMM_NIC_FILTER - Comma-separated list of allowed NIC device names.
 *                       If set, overrides the device_names parameter in init().
 *                       Example: export MPCOMM_NIC_FILTER="mlx5_0,mlx5_2"
 */
class MPComm {
public:
    MPComm();
    ~MPComm();

    // Disable copy
    MPComm(const MPComm &) = delete;
    MPComm &operator=(const MPComm &) = delete;

    /**
     * Initialize RDMA resources
     * @param local_host_id  Unique identifier for this host (e.g., "host1:12345")
     * @param device_names   Comma-separated list of device names (e.g., "mlx5_0,mlx5_1")
     *                       If empty, use all available devices
     * @param tcp_port       TCP port for metadata exchange (0 = auto select)
     * @return 0 on success, negative error code on failure
     */
    int init(const std::string &local_host_id,
             const std::string &device_names = "",
             int tcp_port = 0);

    /**
     * Shutdown and cleanup resources
     */
    void shutdown();

    /**
     * Register local memory for RDMA operations
     * Memory must be registered before it can be used in scatter/gather
     * @param addr    Memory address
     * @param length  Memory length in bytes
     * @return 0 on success, negative error code on failure
     */
    int registerMemory(void *addr, size_t length);

    /**
     * Unregister previously registered memory
     * @param addr  Memory address
     * @return 0 on success, negative error code on failure
     */
    int unregisterMemory(void *addr);

    /**
     * Connect to a remote host
     * Establishes QP connections via TCP metadata exchange
     * @param remote_host_id  Remote host identifier (e.g., "host2:12346")
     * @param remote_tcp_addr Remote TCP address for handshake (e.g., "192.168.1.2")
     * @param remote_tcp_port Remote TCP port
     * @return 0 on success, negative error code on failure
     */
    int connect(const std::string &remote_host_id,
                const std::string &remote_tcp_addr,
                int remote_tcp_port);

    /**
     * Accept incoming connections (run in background)
     * Must call init() with tcp_port > 0 before this
     * @return 0 on success, negative error code on failure
     */
    int startAcceptThread();

    /**
     * Stop the accept thread
     */
    void stopAcceptThread();

    /**
     * Update remote memory info (rkey and address) for a connected host
     * This should be called after memory is registered on the remote side
     * @param remote_host_id  Remote host identifier
     * @param rkeys           Remote keys for each NIC (must match getNumNics())
     * @return 0 on success, negative error code on failure
     */
    int updateRemoteMemoryInfo(const std::string &remote_host_id,
                               const std::vector<uint32_t> &rkeys);

    /**
     * Publish a local buffer for remote access
     * After calling this, remote hosts can query this buffer's info via TCP
     * @param addr    Buffer address (must be registered)
     * @param length  Buffer length
     * @return 0 on success, negative error code on failure
     */
    int publishBuffer(void *addr, size_t length);

    /**
     * Unpublish a previously published buffer
     * @param addr  Buffer address
     * @return 0 on success, negative error code on failure
     */
    int unpublishBuffer(void *addr);

    /**
     * Query remote host's published buffer information via TCP
     * @param remote_host_id  Remote host identifier (must be connected)
     * @param remote_tcp_addr Remote TCP address
     * @param remote_tcp_port Remote TCP port
     * @param out_info        Output: remote buffer information
     * @return 0 on success, negative error code on failure
     */
    int queryRemoteBuffer(const std::string &remote_host_id,
                          const std::string &remote_tcp_addr,
                          int remote_tcp_port,
                          RemoteBufferInfo &out_info);

    /**
     * Get local published buffer info (for debugging/display)
     * @return Published buffer info, or nullptr if not published
     */
    const PublishedBufferInfo* getPublishedBufferInfo() const;

    /**
     * Get rkey for local memory region (for exchanging with remote)
     * @param nic_index  NIC index
     * @param addr       Memory address
     * @return rkey, or 0 if not found
     */
    uint32_t getRkey(size_t nic_index, void *addr) const;

    /**
     * Scatter: distribute local data to multiple remote hosts
     * 
     * Data layout:
     *   local_buffer[0..lengths[0]] -> host_list[0]:remote_addrs[0]
     *   local_buffer[lengths[0]..lengths[0]+lengths[1]] -> host_list[1]:remote_addrs[1]
     *   ...
     * 
     * @param local_addr       Local buffer address (must be registered)
     * @param host_list        List of destination host IDs
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @param num_threads      Number of threads (each uses different NIC)
     * @return 0 on success, negative error code on failure
     */
    int scatter(uintptr_t local_addr,
                const std::vector<std::string> &host_list,
                const std::vector<uintptr_t> &remote_addrs,
                const std::vector<size_t> &lengths,
                int num_threads = 1);

    /**
     * Gather: collect data from multiple remote hosts to local buffer
     * 
     * Data layout:
     *   host_list[0]:remote_addrs[0] -> local_buffer[0..lengths[0]]
     *   host_list[1]:remote_addrs[1] -> local_buffer[lengths[0]..lengths[0]+lengths[1]]
     *   ...
     * 
     * @param local_addr       Local buffer address (must be registered)
     * @param host_list        List of source host IDs
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @param num_threads      Number of threads (each uses different NIC)
     * @return 0 on success, negative error code on failure
     */
    int gather(uintptr_t local_addr,
               const std::vector<std::string> &host_list,
               const std::vector<uintptr_t> &remote_addrs,
               const std::vector<size_t> &lengths,
               int num_threads = 1);

    /**
     * Get number of available NICs
     */
    size_t getNumNics() const { return nic_contexts_.size(); }

    /**
     * Get local host ID
     */
    const std::string &getLocalHostId() const { return local_host_id_; }

    /**
     * Get TCP port for metadata exchange
     */
    int getTcpPort() const { return tcp_port_; }

    /**
     * Get GID string for a specific NIC
     * @param nic_index  Index of NIC (0 to getNumNics()-1)
     * @return GID as hex string, or empty string if invalid
     */
    std::string getGid(size_t nic_index) const;

    /**
     * Get device name for a specific NIC
     * @param nic_index  Index of NIC (0 to getNumNics()-1)
     * @return Device name (e.g., "mlx5_0"), or empty string if invalid
     */
    std::string getDeviceName(size_t nic_index) const;

    /**
     * Get all active device names
     * @return Vector of device names currently in use
     */
    std::vector<std::string> getActiveDevices() const;

    /**
     * Get the NIC filter environment variable name
     * @return Environment variable name ("MPCOMM_NIC_FILTER")
     */
    static const char* getNicFilterEnvVarName();

    /**
     * Get the max RDMA transfer size environment variable name
     * @return Environment variable name ("MPCOMM_MAX_RDMA_TRANSFER_SIZE")
     */
    static const char* getMaxRdmaTransferSizeEnvVarName();

    /**
     * Get the current max RDMA transfer size
     * @return Max transfer size in bytes
     */
    size_t getMaxRdmaTransferSize() const;

    /**
     * Get the number of QPs per connection
     * @return Number of QPs per NIC per connection
     */
    size_t getQpsPerConnection() const;

    /**
     * Get the QPs per connection environment variable name
     * @return Environment variable name ("MPCOMM_QPS_PER_CONNECTION")
     */
    static const char* getQpsPerConnectionEnvVarName();

private:
    // Internal helper functions
    int openDevices(const std::string &device_names);
    int setupNicContext(const std::string &device_name, NicContext &ctx);
    void cleanupNicContext(NicContext &ctx);
    
    int createQP(NicContext &ctx, struct ibv_qp **qp);
    int modifyQPToInit(NicContext &ctx, struct ibv_qp *qp);
    int modifyQPToRTR(NicContext &ctx, struct ibv_qp *qp,
                      const RemoteEndpointInfo &remote);
    int modifyQPToRTS(struct ibv_qp *qp);
    void destroyQP(struct ibv_qp *qp);

    int doHandshake(int sock_fd, size_t nic_index,
                    RemoteEndpointInfo &local_info,
                    RemoteEndpointInfo &remote_info);
    
    // Post RDMA WRITE/READ (synchronous - posts all chunks and waits)
    int postRdmaWrite(NicContext &ctx, struct ibv_qp *qp,
                      void *local_addr, uint32_t lkey,
                      uint64_t remote_addr, uint32_t rkey,
                      size_t length);
    int postRdmaRead(NicContext &ctx, struct ibv_qp *qp,
                     void *local_addr, uint32_t lkey,
                     uint64_t remote_addr, uint32_t rkey,
                     size_t length);

    // Async RDMA operations - post all chunks at once, return immediately
    int postRdmaWriteAsync(NicContext &ctx, struct ibv_qp *qp,
                           void *local_addr, uint32_t lkey,
                           uint64_t remote_addr, uint32_t rkey,
                           size_t length, AsyncRdmaContext &async_ctx);
    int postRdmaReadAsync(NicContext &ctx, struct ibv_qp *qp,
                          void *local_addr, uint32_t lkey,
                          uint64_t remote_addr, uint32_t rkey,
                          size_t length, AsyncRdmaContext &async_ctx);

    // Async RDMA operations with multi-QP rotation - each slice uses a different QP
    int postRdmaWriteAsyncMultiQP(NicContext &ctx, const std::string &host_id,
                                  size_t nic_index, void *local_addr, uint32_t lkey,
                                  uint64_t remote_addr, uint32_t rkey,
                                  size_t length, AsyncRdmaContext &async_ctx);
    int postRdmaReadAsyncMultiQP(NicContext &ctx, const std::string &host_id,
                                 size_t nic_index, void *local_addr, uint32_t lkey,
                                 uint64_t remote_addr, uint32_t rkey,
                                 size_t length, AsyncRdmaContext &async_ctx);

    // Synchronous RDMA operations with multi-QP rotation - Post-Poll loop in single thread
    // No separate poll thread, better efficiency for scatter/gather
    int rdmaWriteSyncMultiQP(NicContext &ctx, const std::string &host_id,
                             size_t nic_index, void *local_addr, uint32_t lkey,
                             uint64_t remote_addr, uint32_t rkey, size_t length);
    int rdmaReadSyncMultiQP(NicContext &ctx, const std::string &host_id,
                            size_t nic_index, void *local_addr, uint32_t lkey,
                            uint64_t remote_addr, uint32_t rkey, size_t length);

    // Poll for async completion - non-blocking check
    // Returns: MPCOMM_SUCCESS if all done, MPCOMM_ERR_TIMEOUT if still in progress,
    //          or other error code on failure
    int pollAsyncCompletion(NicContext &ctx, AsyncRdmaContext &async_ctx);

    // Wait for async completion - blocking wait with timeout
    int waitAsyncCompletion(NicContext &ctx, AsyncRdmaContext &async_ctx,
                            int timeout_ms = 5000);

    // Background poll thread function for async RDMA operations
    static void asyncPollThreadFunc(AsyncRdmaContext *async_ctx);

    int pollCompletion(NicContext &ctx, int timeout_ms = 5000);

    // Get lkey for a registered memory address on a specific NIC
    uint32_t getLkey(size_t nic_index, void *addr) const;
    
    // Get QP to a remote host's NIC (with optional qp_index for multi-QP)
    // qp_index: index within the QP list (0 to qps_per_connection_-1)
    struct ibv_qp *getOrCreateQP(size_t local_nic_index,
                                 const std::string &remote_host_id,
                                 size_t remote_nic_index,
                                 size_t qp_index = 0);

    // TCP server for accepting connections
    void acceptLoop();

    // Handle buffer query request from remote
    void handleBufferQuery(int client_fd);

    // Transfer direction for unified scatter/gather implementation
    enum class TransferDirection {
        SCATTER,  // local -> remote (RDMA WRITE)
        GATHER    // remote -> local (RDMA READ)
    };

    // Unified implementation for scatter and gather
    int transferImpl(uintptr_t local_addr,
                     const std::vector<std::string> &host_list,
                     const std::vector<uintptr_t> &remote_addrs,
                     const std::vector<size_t> &lengths,
                     int num_threads,
                     TransferDirection direction);

    // Member variables
    std::string local_host_id_;
    int tcp_port_;
    int listen_fd_;
    size_t max_rdma_transfer_size_;  // Configurable via env var
    size_t qps_per_connection_;      // Number of QPs per NIC per connection
    
    std::vector<std::unique_ptr<NicContext>> nic_contexts_;
    
    // Remote host connection info (key: host_id)
    std::unordered_map<std::string, ConnectionInfo> connections_;
    std::mutex connections_mutex_;

    // Published buffer (single buffer for simplicity)
    std::unique_ptr<PublishedBufferInfo> published_buffer_;
    std::mutex published_buffer_mutex_;

    // Accept thread
    std::atomic<bool> accept_running_;
    std::unique_ptr<std::thread> accept_thread_;

    // Thread pool for scatter/gather operations
    std::unique_ptr<ThreadPool> thread_pool_;
    size_t thread_pool_size_;  // Configurable via env var

    bool initialized_;
};

// Utility functions
std::string gidToString(const union ibv_gid &gid);
void stringToGid(const std::string &str, union ibv_gid &gid);

}  // namespace mpcomm

#endif  // MPCOMM_MPCOMM_H_
