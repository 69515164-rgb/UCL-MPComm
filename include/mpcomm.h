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
#include <chrono>
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
    MPCOMM_ERR_INVALID_HANDLE = -8,  // Invalid async transfer handle
    MPCOMM_ERR_PENDING = -9,         // Transfer still in progress (not an error)
};

// Async transfer handle type
using TransferHandle = uint64_t;
static constexpr TransferHandle INVALID_TRANSFER_HANDLE = 0;

// wr_id encoding for async transfers
// Format: [63:56] nic_index (8-bit) | [55:48] qp_index (8-bit) | 
//         [47:32] transfer_handle (16-bit) | [31:0] chunk_index (32-bit)
// This allows up to 256 NICs, 256 QPs, 65536 concurrent transfers, 4B chunks
struct WrIdEncoding {
    static constexpr uint64_t NIC_SHIFT = 56;
    static constexpr uint64_t QP_SHIFT = 48;
    static constexpr uint64_t HANDLE_SHIFT = 32;
    static constexpr uint64_t CHUNK_MASK = 0xFFFFFFFFULL;
    static constexpr uint64_t HANDLE_MASK = 0xFFFFULL;
    static constexpr uint64_t QP_MASK = 0xFFULL;
    static constexpr uint64_t NIC_MASK = 0xFFULL;
    
    static inline uint64_t encode(size_t nic_index, size_t qp_index, 
                                  TransferHandle handle, size_t chunk_index) {
        return (static_cast<uint64_t>(nic_index & NIC_MASK) << NIC_SHIFT) |
               (static_cast<uint64_t>(qp_index & QP_MASK) << QP_SHIFT) |
               (static_cast<uint64_t>(handle & HANDLE_MASK) << HANDLE_SHIFT) |
               (chunk_index & CHUNK_MASK);
    }
    
    static inline size_t decodeNic(uint64_t wr_id) {
        return static_cast<size_t>((wr_id >> NIC_SHIFT) & NIC_MASK);
    }
    
    static inline size_t decodeQp(uint64_t wr_id) {
        return static_cast<size_t>((wr_id >> QP_SHIFT) & QP_MASK);
    }
    
    static inline TransferHandle decodeHandle(uint64_t wr_id) {
        return static_cast<TransferHandle>((wr_id >> HANDLE_SHIFT) & HANDLE_MASK);
    }
    
    static inline size_t decodeChunk(uint64_t wr_id) {
        return static_cast<size_t>(wr_id & CHUNK_MASK);
    }
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

// NUMA topology information for a single NUMA node
struct NumaTopology {
    int numa_node;                              // NUMA node ID
    std::vector<std::string> local_nics;        // NICs local to this NUMA node (optimal)
    std::vector<std::string> remote_nics;       // NICs on other NUMA nodes (fallback)
};

// NIC topology information
struct NicTopologyInfo {
    std::string nic_name;                       // NIC device name (e.g., mlx5_0)
    int numa_node;                              // NUMA node this NIC belongs to (-1 if unknown)
};

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
    int numa_node;      // NUMA node this memory belongs to (-1 if unknown)
    bool is_gpu;        // True if this is GPU (HBM) memory
    int gpu_device_id;  // CUDA device ordinal (-1 if CPU memory)
    // PCIe-affine NIC indices for GPU memory.
    // These are the NICs that share the closest PCIe switch with the GPU,
    // providing optimal GPUDirect RDMA performance.
    // Empty for CPU memory (falls back to NUMA-level NIC selection).
    std::vector<size_t> pcie_affine_nic_indices;
};

// Remote buffer entry received from peer (single buffer)
// Defined early so it can be used in ConnectionInfo
struct RemoteBufferEntry {
    uint64_t addr;              // Remote buffer address
    uint64_t length;            // Remote buffer length
    int numa_node;              // NUMA node this buffer belongs to (-1 if unknown)
    std::vector<uint32_t> rkeys;  // Remote keys for each NIC
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
    
    // Remote NUMA topology (for NUMA-aware NIC selection)
    // Maps remote NIC index to its NUMA node
    std::vector<int> remote_nic_numa_nodes;  // remote_nic_numa_nodes[nic_idx] = numa_node
    int remote_numa_count;                   // Number of NUMA nodes on remote side
    
    // Remote NIC names (for name-based matching)
    std::vector<std::string> remote_nic_names;  // remote_nic_names[nic_idx] = device_name
    
    // Local NIC to Remote NIC mapping (for name-based suffix matching)
    // Maps local NIC index to the list of remote NIC indices it connects to
    // Example: local_to_remote_nic_map[2] = {3} means local NIC2 connects to remote NIC3
    std::unordered_map<size_t, std::vector<size_t>> local_to_remote_nic_map;
    
    // Remote buffers information (for multi-NUMA support)
    // Each buffer has its own rkeys, allowing parallel access to different NUMA buffers
    // Key: buffer address, Value: buffer entry with rkeys
    std::unordered_map<uint64_t, RemoteBufferEntry> remote_buffers;
    
    ConnectionInfo() : tcp_port(0), remote_numa_count(0) {}
    
    // Helper: find rkey for a specific remote address and NIC
    // Returns the rkey if found, or falls back to nic_endpoints[nic_idx].rkey
    uint32_t getRkeyForAddr(uint64_t remote_addr, size_t nic_idx) const {
        // First check if this address belongs to a known remote buffer
        for (const auto& [buf_addr, buf_entry] : remote_buffers) {
            if (remote_addr >= buf_addr && remote_addr < buf_addr + buf_entry.length) {
                // Found the buffer containing this address
                if (nic_idx < buf_entry.rkeys.size()) {
                    return buf_entry.rkeys[nic_idx];
                }
                break;
            }
        }
        // Fallback to the legacy single-rkey in nic_endpoints
        if (nic_idx < nic_endpoints.size()) {
            return nic_endpoints[nic_idx].rkey;
        }
        return 0;
    }
    
    // Helper: find remote buffer by NUMA node
    const RemoteBufferEntry* getBufferByNuma(int numa_node) const {
        for (const auto& [addr, entry] : remote_buffers) {
            if (entry.numa_node == numa_node) {
                return &entry;
            }
        }
        return nullptr;
    }
};

// Published buffer information (for metadata exchange)
// Single buffer entry with NUMA info
struct PublishedBufferEntry {
    uint64_t addr;              // Buffer address
    uint64_t length;            // Buffer length
    int numa_node;              // NUMA node this buffer belongs to (-1 if unknown)
    std::vector<uint32_t> rkeys;  // Remote keys for each NIC
};

// All published buffers
struct PublishedBufferInfo {
    std::vector<PublishedBufferEntry> buffers;  // All published buffers
};

// Forward declaration for thread pool
class ThreadPool;

// Remote buffer info received from peer (all buffers)
struct RemoteBufferInfo {
    std::string host_id;        // Remote host identifier
    std::vector<RemoteBufferEntry> buffers;  // All remote buffers with NUMA info
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

// Chunk task for transfer operations
struct ChunkTask {
    size_t host_idx;        // Index into host_list (avoid string copy)
    uintptr_t local_addr;
    uintptr_t remote_addr;
    size_t length;
};

// Result of an async transfer operation
struct TransferResult {
    int error_code;           // MPCOMM_SUCCESS or error code
    size_t bytes_transferred; // Total bytes transferred
    double elapsed_ms;        // Transfer time in milliseconds
};

// Forward declaration
class MPComm;

// Context for tracking async transfer operations
struct TransferContext {
    TransferHandle handle;                          // Unique handle ID
    std::atomic<size_t> total_chunks;               // Total chunks to transfer
    std::atomic<size_t> total_completed;            // Completed chunks
    std::atomic<int> error_code;                    // Error code (0 if no error)
    std::atomic<bool> finished;                     // True when transfer complete or error
    std::atomic<bool> submitted;                    // True when submitted to worker thread
    
    // Transfer parameters (stored for async processing)
    uintptr_t local_addr;
    std::vector<std::string> host_list;
    std::vector<uintptr_t> remote_addrs;
    std::vector<size_t> lengths;
    bool is_scatter;                                // true=scatter, false=gather
    
    // All chunks to be transferred
    std::vector<ChunkTask> all_chunks;
    std::atomic<size_t> next_chunk_idx;             // Next chunk to post
    
    // Per-NIC flow control state
    std::vector<size_t> per_nic_posted;
    std::vector<size_t> per_nic_completed;
    std::vector<size_t> per_nic_bytes;
    std::vector<std::vector<size_t>> per_nic_qp_posted;
    std::vector<std::vector<size_t>> per_nic_qp_completed;
    
    // NUMA-aware NIC selection
    std::vector<size_t> candidate_nic_indices;
    
    // Timing for each stage
    std::chrono::steady_clock::time_point start_time;          // User thread starts
    // Preparation sub-stages (between start_time and queued_time)
    std::chrono::steady_clock::time_point prep_chunks_calc_time;   // After chunk count calculation
    std::chrono::steady_clock::time_point prep_chunks_fill_time;   // After chunks array filled
    std::chrono::steady_clock::time_point prep_numa_query_time;    // After NUMA query
    std::chrono::steady_clock::time_point prep_flowctrl_time;      // After flow control init
    std::chrono::steady_clock::time_point queued_time;         // Task queued to worker
    std::chrono::steady_clock::time_point worker_start_time;   // Worker picks up task
    std::chrono::steady_clock::time_point cache_done_time;     // Connection cache built
    std::chrono::steady_clock::time_point first_post_time;     // First chunk posted
    std::chrono::steady_clock::time_point all_posted_time;     // All chunks posted
    std::chrono::steady_clock::time_point end_time;            // All completions received
    
    // Round-robin index for NIC selection
    size_t rr_nic_index;
    
    TransferContext() 
        : handle(INVALID_TRANSFER_HANDLE)
        , total_chunks(0)
        , total_completed(0)
        , error_code(0)
        , finished(false)
        , submitted(false)
        , local_addr(0)
        , is_scatter(true)
        , next_chunk_idx(0)
        , rr_nic_index(0) {}
    
    // Disable copy
    TransferContext(const TransferContext&) = delete;
    TransferContext& operator=(const TransferContext&) = delete;
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
     * Supports multiple buffers - each call adds a buffer to the published list
     * @param addr       Buffer address (must be registered)
     * @param length     Buffer length
     * @param numa_node  NUMA node this buffer belongs to (-1 = auto-detect or unknown)
     * @return 0 on success, negative error code on failure
     */
    int publishBuffer(void *addr, size_t length, int numa_node = -1);

    /**
     * Unpublish a previously published buffer
     * Removes the buffer from the published list
     * @param addr  Buffer address
     * @return 0 on success, negative error code on failure
     */
    int unpublishBuffer(void *addr);

    /**
     * Unpublish all published buffers
     * Clears the entire published buffer list
     */
    void unpublishAllBuffers();

    /**
     * Query remote host's published buffer information via TCP
     * Returns all published buffers with NUMA info
     * @param remote_host_id  Remote host identifier (must be connected)
     * @param remote_tcp_addr Remote TCP address
     * @param remote_tcp_port Remote TCP port
     * @param out_info        Output: remote buffer information (all buffers)
     * @return 0 on success, negative error code on failure
     */
    int queryRemoteBuffer(const std::string &remote_host_id,
                          const std::string &remote_tcp_addr,
                          int remote_tcp_port,
                          RemoteBufferInfo &out_info);

    /**
     * Query remote host's buffer by NUMA node
     * Convenience method to get a specific NUMA node's buffer
     * @param remote_host_id  Remote host identifier (must be connected)
     * @param remote_tcp_addr Remote TCP address
     * @param remote_tcp_port Remote TCP port
     * @param numa_node       NUMA node to query (-1 = first buffer)
     * @param out_entry       Output: matching buffer entry
     * @return 0 on success, negative error code on failure
     */
    int queryRemoteBufferByNuma(const std::string &remote_host_id,
                                const std::string &remote_tcp_addr,
                                int remote_tcp_port,
                                int numa_node,
                                RemoteBufferEntry &out_entry);

    /**
     * Get local published buffer info (for debugging/display)
     * @return Published buffer info containing all buffers, or nullptr if none published
     */
    const PublishedBufferInfo* getPublishedBufferInfo() const;

    /**
     * Get number of published buffers
     * @return Number of buffers currently published
     */
    size_t getPublishedBufferCount() const;

    /**
     * Get rkey for local memory region (for exchanging with remote)
     * @param nic_index  NIC index
     * @param addr       Memory address
     * @return rkey, or 0 if not found
     */
    uint32_t getRkey(size_t nic_index, void *addr) const;

    /**
     * Get rkey for remote memory region (for exchanging with remote)
     * @param remote_host_id  Remote host identifier
     * @param remote_addr     Remote memory address
     * @return rkey, or 0 if not found
     */
    uint32_t getRkeyForRemoteAddr(const std::string &remote_host_id, uint64_t remote_addr) const;

    // ==================== Async Transfer API ====================
    
    /**
     * Start async scatter operation (returns immediately)
     * 
     * Distribute local data to multiple remote hosts using RDMA WRITE.
     * Uses dynamic load balancing across NICs - chunks are assigned to
     * the NIC with the most available capacity for better performance.
     * 
     * Data layout:
     *   local_buffer[0..lengths[0]] -> host_list[0]:remote_addrs[0]
     *   local_buffer[lengths[0]..lengths[0]+lengths[1]] -> host_list[1]:remote_addrs[1]
     *   ...
     * 
     * Use isTransferComplete() or waitTransfer() to check/wait for completion.
     * 
     * @param local_addr       Local buffer address (must be registered)
     * @param host_list        List of destination host IDs
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @return TransferHandle on success, INVALID_TRANSFER_HANDLE on failure
     */
    TransferHandle scatterAsync(uintptr_t local_addr,
                                const std::vector<std::string> &host_list,
                                const std::vector<uintptr_t> &remote_addrs,
                                const std::vector<size_t> &lengths);

    /**
     * Start async gather operation (returns immediately)
     * 
     * Collect data from multiple remote hosts to local buffer using RDMA READ.
     * Uses dynamic load balancing across NICs - chunks are assigned to
     * the NIC with the most available capacity for better performance.
     * 
     * Data layout:
     *   host_list[0]:remote_addrs[0] -> local_buffer[0..lengths[0]]
     *   host_list[1]:remote_addrs[1] -> local_buffer[lengths[0]..lengths[0]+lengths[1]]
     *   ...
     * 
     * Use isTransferComplete() or waitTransfer() to check/wait for completion.
     * 
     * @param local_addr       Local buffer address (must be registered)
     * @param host_list        List of source host IDs
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @return TransferHandle on success, INVALID_TRANSFER_HANDLE on failure
     */
    TransferHandle gatherAsync(uintptr_t local_addr,
                               const std::vector<std::string> &host_list,
                               const std::vector<uintptr_t> &remote_addrs,
                               const std::vector<size_t> &lengths);

    /**
     * Check if async transfer is complete (non-blocking)
     * 
     * This function polls for completions and updates internal state.
     * 
     * @param handle  Transfer handle from scatterAsync/gatherAsync
     * @return true if transfer is complete (success or error), false if still in progress
     */
    bool isTransferComplete(TransferHandle handle);

    /**
     * Wait for async transfer to complete (blocking with optional timeout)
     * 
     * @param handle      Transfer handle from scatterAsync/gatherAsync
     * @param timeout_ms  Timeout in milliseconds (-1 = wait forever)
     * @return MPCOMM_SUCCESS on success, MPCOMM_ERR_TIMEOUT on timeout,
     *         or other error code on failure
     */
    int waitTransfer(TransferHandle handle, int timeout_ms = -1);

    /**
     * Get result of completed async transfer
     * 
     * Should only be called after isTransferComplete() returns true.
     * 
     * @param handle  Transfer handle from scatterAsync/gatherAsync
     * @return TransferResult with error_code, bytes_transferred, elapsed_ms
     */
    TransferResult getTransferResult(TransferHandle handle);

    /**
     * Release async transfer handle and associated resources
     * 
     * Must be called after transfer is complete to free resources.
     * Calling on an incomplete transfer will cancel and release it.
     * 
     * @param handle  Transfer handle from scatterAsync/gatherAsync
     */
    void releaseTransfer(TransferHandle handle);

    // ==================== End Async Transfer API ====================

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

    /**
     * Get NUMA topology information
     * @return Vector of NumaTopology structures
     */
    const std::vector<NumaTopology>& getNumaTopology() const;

    /**
     * Get NIC topology information
     * @return Vector of NicTopologyInfo structures
     */
    const std::vector<NicTopologyInfo>& getNicTopology() const;

    /**
     * Get the NUMA node for a specific NIC
     * @param nic_name  NIC device name
     * @return NUMA node ID, or -1 if unknown
     */
    int getNicNumaNode(const std::string& nic_name) const;

    /**
     * Get local NICs for a specific NUMA node
     * @param numa_node  NUMA node ID
     * @return Vector of local NIC names (optimal NICs for this NUMA node)
     */
    std::vector<std::string> getLocalNicsForNuma(int numa_node) const;

    /**
     * Get NUMA node for a given memory address (check registered memory regions)
     * For GPU memory, returns the NUMA node of the GPU's PCIe-affine CPU socket
     * @param addr  Memory address
     * @return NUMA node ID, or -1 if not found in registered regions
     */
    int getNumaNodeForAddr(void* addr) const;

    /**
     * Check if a memory address belongs to a GPU device
     * @param addr  Memory address
     * @return GPU device ID if GPU memory, -1 if CPU memory or not registered
     */
    int getGpuDeviceForAddr(void* addr) const;

    /**
     * Get local NIC indices for a specific NUMA node
     * @param numa_node  NUMA node ID
     * @return Vector of local NIC indices (optimal NICs for this NUMA node)
     */
    std::vector<size_t> getLocalNicIndicesForNuma(int numa_node) const;

    /**
     * Get remote NIC indices for a specific remote NUMA node
     * Used for NUMA-aware data transfer - select remote NICs that are local
     * to the destination memory's NUMA node
     * @param remote_host_id  Remote host identifier
     * @param remote_numa_node  Remote NUMA node ID
     * @return Vector of remote NIC indices that belong to the specified NUMA node
     */
    std::vector<size_t> getRemoteNicIndicesForNuma(const std::string& remote_host_id, 
                                                   int remote_numa_node) const;

    /**
     * Get NUMA node for a specific remote NIC
     * @param remote_host_id  Remote host identifier
     * @param nic_index  Remote NIC index
     * @return NUMA node ID, or -1 if unknown
     */
    int getRemoteNicNumaNode(const std::string& remote_host_id, size_t nic_index) const;

    /**
     * Get the NUMA node for a specific GPU device (from topology discovery)
     * @param gpu_device_id  CUDA device ordinal
     * @return NUMA node ID, or -1 if unknown
     */
    int getGpuNumaNode(int gpu_device_id) const;

private:
    // Topology discovery helper functions
    int getNumaNodeCount();
    int readNicNumaNode(const std::string& nic_name);
    std::vector<std::string> getCandidateNics();
    void discoverTopology();
    void printTopologyInfo();
    // Detect if an address is GPU memory and return the GPU device ID
    // Returns -1 if the address is CPU memory or detection fails
    int detectGpuDevice(void* addr) const;

    // Discover PCIe-affine NICs for a GPU device.
    // Compares GPU and NIC sysfs PCIe paths to find NICs sharing the
    // closest PCIe switch (longest common PCIe path prefix).
    // Returns NIC indices sorted by PCIe affinity (closest first).
    std::vector<size_t> getGpuPcieAffinityNics(int gpu_device_id) const;

    // Get PCIe-affine NIC indices for a registered memory address.
    // Returns the pcie_affine_nic_indices from the matching MemoryRegionInfo,
    // or empty vector if not GPU memory or not found.
    std::vector<size_t> getPcieAffinityNicsForAddr(void* addr) const;

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

    // Synchronous RDMA operations with multi-QP rotation - Post-Poll loop in single thread
    // No separate poll thread, better efficiency for scatter/gather
    int rdmaWriteSyncMultiQP(NicContext &ctx, const std::string &host_id,
                             size_t nic_index, void *local_addr, uint32_t lkey,
                             uint64_t remote_addr, uint32_t rkey, size_t length);
    int rdmaReadSyncMultiQP(NicContext &ctx, const std::string &host_id,
                            size_t nic_index, void *local_addr, uint32_t lkey,
                            uint64_t remote_addr, uint32_t rkey, size_t length);

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

    // Async transfer implementation - prepares context and posts initial chunks
    TransferHandle transferAsyncStart(uintptr_t local_addr,
                                      const std::vector<std::string> &host_list,
                                      const std::vector<uintptr_t> &remote_addrs,
                                      const std::vector<size_t> &lengths,
                                      TransferDirection direction);

    // Helper: select best NIC for async transfer (lowest outstanding)
    size_t selectBestNicForAsync(TransferContext& ctx);

    // Helper: poll all NICs for async transfer completions
    int pollAllNicsForAsync(TransferContext& ctx);

    // Member variables
    std::string local_host_id_;
    int tcp_port_;
    int listen_fd_;
    size_t max_rdma_transfer_size_;  // Configurable via env var
    size_t qps_per_connection_;      // Number of QPs per NIC per connection
    
    std::vector<std::unique_ptr<NicContext>> nic_contexts_;
    
    // Remote host connection info (key: host_id)
    std::unordered_map<std::string, ConnectionInfo> connections_;
    mutable std::mutex connections_mutex_;

    // Published buffer (single buffer for simplicity)
    std::unique_ptr<PublishedBufferInfo> published_buffer_;
    std::mutex published_buffer_mutex_;

    // Accept thread
    std::atomic<bool> accept_running_;
    std::unique_ptr<std::thread> accept_thread_;

    // Async transfer management
    std::unordered_map<TransferHandle, std::unique_ptr<TransferContext>> active_transfers_;
    mutable std::mutex transfers_mutex_;
    std::atomic<TransferHandle> next_transfer_handle_{1};

    // Per-NUMA worker threads for fully async transfer (post + poll)
    // Each worker is bound to a NUMA node and handles transfers for that NUMA's memory
    // One worker per NUMA node
    static constexpr size_t kMaxNumaNodes = 8;         // Support up to 8 NUMA nodes
    static constexpr size_t kWorkersPerNuma = 1;       // Workers per NUMA node
    static constexpr size_t kLockFreeQueueSize = 4096; // Lock-free queue capacity
    size_t num_numa_nodes_;                            // Actual number of NUMA nodes
    size_t total_workers_;                             // Total worker threads
    std::vector<std::unique_ptr<std::thread>> worker_threads_;
    std::atomic<bool> worker_running_{false};
    
    // Lock-free MPSC (Multi-Producer Single-Consumer) queue per worker
    // Using fixed-size ring buffer with atomic head/tail pointers
    struct LockFreeQueue {
        std::vector<std::atomic<TransferHandle>> buffer;
        std::atomic<size_t> head{0};  // Producer write position (CAS-based for MPSC)
        std::atomic<size_t> tail{0};  // Consumer read position (single consumer, no CAS needed)
        
        LockFreeQueue() : buffer(kLockFreeQueueSize) {
            for (auto& slot : buffer) {
                slot.store(INVALID_TRANSFER_HANDLE, std::memory_order_relaxed);
            }
        }
        
        // Try to push (returns false if queue is full) - MPSC safe
        bool tryPush(TransferHandle handle) {
            size_t current_head, next_head;
            do {
                current_head = head.load(std::memory_order_relaxed);
                next_head = (current_head + 1) % kLockFreeQueueSize;
                if (next_head == tail.load(std::memory_order_acquire)) {
                    return false;  // Queue is full
                }
            } while (!head.compare_exchange_weak(current_head, next_head,
                                                  std::memory_order_release,
                                                  std::memory_order_relaxed));
            // Successfully reserved slot at current_head
            buffer[current_head].store(handle, std::memory_order_release);
            return true;
        }
        
        // Try to pop (returns INVALID_TRANSFER_HANDLE if queue is empty) - single consumer
        TransferHandle tryPop() {
            size_t current_tail = tail.load(std::memory_order_relaxed);
            if (current_tail == head.load(std::memory_order_acquire)) {
                return INVALID_TRANSFER_HANDLE;  // Queue is empty
            }
            // Wait for the slot to be written (in case producer hasn't finished writing)
            TransferHandle handle;
            do {
                handle = buffer[current_tail].load(std::memory_order_acquire);
            } while (handle == INVALID_TRANSFER_HANDLE);
            buffer[current_tail].store(INVALID_TRANSFER_HANDLE, std::memory_order_relaxed);
            tail.store((current_tail + 1) % kLockFreeQueueSize, std::memory_order_release);
            return handle;
        }
        
        bool empty() const {
            return tail.load(std::memory_order_acquire) == head.load(std::memory_order_acquire);
        }
    };
    
    // Per-worker task queues (total_workers_ = num_numa_nodes_ * kWorkersPerNuma)
    std::vector<std::unique_ptr<LockFreeQueue>> worker_queues_;
    
    // Per-NUMA round-robin counter for load balancing across workers within same NUMA
    // Using unique_ptr because std::atomic is not copyable/movable
    std::vector<std::unique_ptr<std::atomic<size_t>>> numa_worker_rr_;

    // Worker thread entry point
    // worker_id: global worker index (0 to total_workers_-1)
    // numa_id: NUMA node this worker belongs to
    // cpu_id: CPU core to bind to (-1 for no binding)
    void workerThreadLoop(size_t worker_id, int numa_id, int cpu_id);
    
    // Process a single transfer (post all chunks + poll until complete)
    void processTransfer(TransferContext& ctx);
    
    // Determine which NUMA node should handle a transfer based on local memory address
    int getNumaForAddr(uintptr_t addr) const;
    
    // Select a worker within a NUMA node (round-robin)
    size_t selectWorkerForNuma(int numa_id);

    // Thread pool for scatter/gather operations
    std::unique_ptr<ThreadPool> thread_pool_;
    size_t thread_pool_size_;  // Configurable via env var

    bool initialized_;

    // Topology information
    std::vector<NumaTopology> numa_topology_;
    std::vector<NicTopologyInfo> nic_topology_;
};

// Utility functions
std::string gidToString(const union ibv_gid &gid);
void stringToGid(const std::string &str, union ibv_gid &gid);

}  // namespace mpcomm

#endif  // MPCOMM_MPCOMM_H_
