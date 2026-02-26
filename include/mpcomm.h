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

#include <stdint.h>

#include <memory>
#include <string>
#include <vector>

namespace mpcomm {

// =====================================================================
// Public Error Codes
// =====================================================================

enum MPCommError {
    MPCOMM_SUCCESS = 0,
    MPCOMM_ERR_DEVICE = -1,
    MPCOMM_ERR_CONTEXT = -2,
    MPCOMM_ERR_MEMORY = -3,
    MPCOMM_ERR_CONNECTION = -4,
    MPCOMM_ERR_TRANSFER = -5,
    MPCOMM_ERR_TIMEOUT = -6,
    MPCOMM_ERR_INVALID_ARG = -7,
    MPCOMM_ERR_INVALID_HANDLE = -8,
    MPCOMM_ERR_PENDING = -9,
};

// =====================================================================
// Public Types
// =====================================================================

// Async transfer handle type
using TransferHandle = uint64_t;
static constexpr TransferHandle INVALID_TRANSFER_HANDLE = 0;

// Maximum size for a single RDMA transfer (default: 1 GB)
// Can be configured via environment variable MPCOMM_MAX_RDMA_TRANSFER_SIZE
static constexpr size_t MPCOMM_DEFAULT_MAX_RDMA_TRANSFER_SIZE = 1ULL << 30;

// Number of QPs per NIC per connection (default: 1)
// Can be configured via environment variable MPCOMM_QPS_PER_CONNECTION
static constexpr size_t MPCOMM_DEFAULT_QPS_PER_CONNECTION = 1;

// NUMA topology information for a single NUMA node
struct NumaTopology {
    int numa_node;
    std::vector<std::string> local_nics;
    std::vector<std::string> remote_nics;
};

// NIC topology information
struct NicTopologyInfo {
    std::string nic_name;
    int numa_node;
};

// Remote buffer entry received from peer (single buffer)
struct RemoteBufferEntry {
    uint64_t addr;
    uint64_t length;
    int numa_node;
    std::vector<uint32_t> rkeys;
};

// Single published buffer entry with NUMA info
struct PublishedBufferEntry {
    uint64_t addr;
    uint64_t length;
    int numa_node;
    std::vector<uint32_t> rkeys;
};

// All published buffers
struct PublishedBufferInfo {
    std::vector<PublishedBufferEntry> buffers;
};

// Remote buffer info received from peer (all buffers)
struct RemoteBufferInfo {
    std::string host_id;
    std::vector<RemoteBufferEntry> buffers;
};

// Result of an async transfer operation
struct TransferResult {
    int error_code;
    size_t bytes_transferred;
    double elapsed_ms;
};

// =====================================================================
// MPComm Class (Pimpl)
// =====================================================================

/**
 * MPComm - Memory Pooling Communication using native ibverbs
 *
 * This class implements scatter/gather operations across multiple hosts
 * using multiple NICs, without depending on mooncake's TransferEngine.
 *
 * Environment Variables:
 *   MPCOMM_NIC_FILTER              - Comma-separated list of allowed NIC device names.
 *   MPCOMM_MAX_RDMA_TRANSFER_SIZE  - Max bytes per RDMA operation (default: 1 GB).
 *   MPCOMM_QPS_PER_CONNECTION      - Number of QPs per NIC per connection (default: 1).
 *   MPCOMM_POLL_BATCH_SIZE         - Max WCs per ibv_poll_cq call (default: 64).
 *   MPCOMM_MAX_IDLE_SPINS          - Worker idle spins before yield (default: 10000).
 *   MPCOMM_MAX_SEND_WR             - QP send queue depth (default: 512).
 *   MPCOMM_MAX_OUTSTANDING_PER_QP  - Max outstanding WRs per QP (default: 256).
 *   MPCOMM_LOG_LEVEL               - Log verbosity: "0"/"error", "1"/"warn", "2"/"info" (default),
 *                                    "3"/"debug" (includes transfer timing & NIC statistics).
 *   MPCOMM_TRANSFER_STATS_INTERVAL - Print stats every N transfers (default: 0 = every transfer,
 *                                    requires LOG_LEVEL=3/debug).
 */
class MPComm {
public:
    MPComm();
    ~MPComm();

    // Non-copyable, non-movable
    MPComm(const MPComm &) = delete;
    MPComm &operator=(const MPComm &) = delete;
    MPComm(MPComm &&) noexcept;
    MPComm &operator=(MPComm &&) noexcept;

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
     * @param remote_host_id  Remote host identifier
     * @param remote_tcp_addr Remote TCP address for handshake
     * @param remote_tcp_port Remote TCP port
     * @return 0 on success, negative error code on failure
     */
    int connect(const std::string &remote_host_id,
                const std::string &remote_tcp_addr,
                int remote_tcp_port);

    /**
     * Accept incoming connections (run in background)
     * @return 0 on success, negative error code on failure
     */
    int startAcceptThread();

    /**
     * Stop the accept thread
     */
    void stopAcceptThread();

    /**
     * Update remote memory info (rkey and address) for a connected host
     * @param remote_host_id  Remote host identifier
     * @param rkeys           Remote keys for each NIC (must match getNumNics())
     * @return 0 on success, negative error code on failure
     */
    int updateRemoteMemoryInfo(const std::string &remote_host_id,
                               const std::vector<uint32_t> &rkeys);

    /**
     * Publish a local buffer for remote access
     * @param addr       Buffer address (must be registered)
     * @param length     Buffer length
     * @param numa_node  NUMA node this buffer belongs to (-1 = auto-detect)
     * @return 0 on success, negative error code on failure
     */
    int publishBuffer(void *addr, size_t length, int numa_node = -1);

    /**
     * Unpublish a previously published buffer
     * @param addr  Buffer address
     * @return 0 on success, negative error code on failure
     */
    int unpublishBuffer(void *addr);

    /**
     * Unpublish all published buffers
     */
    void unpublishAllBuffers();

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
     * Query remote host's buffer by NUMA node
     * @param remote_host_id  Remote host identifier
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
     * Get local published buffer info
     * @return Published buffer info, or nullptr if none published
     */
    const PublishedBufferInfo* getPublishedBufferInfo() const;

    /**
     * Get number of published buffers
     */
    size_t getPublishedBufferCount() const;

    /**
     * Get rkey for local memory region
     * @param nic_index  NIC index
     * @param addr       Memory address
     * @return rkey, or 0 if not found
     */
    uint32_t getRkey(size_t nic_index, void *addr) const;

    // ==================== Async Transfer API ====================

    /**
     * Start async scatter operation (returns immediately)
     *
     * Data layout:
     *   local_buffer[0..lengths[0]] -> host_list[0]:remote_addrs[0]
     *   local_buffer[lengths[0]..lengths[0]+lengths[1]] -> host_list[1]:remote_addrs[1]
     *   ...
     */
    TransferHandle scatterAsync(uintptr_t local_addr,
                                const std::vector<std::string> &host_list,
                                const std::vector<uintptr_t> &remote_addrs,
                                const std::vector<size_t> &lengths);

    /**
     * Start async gather operation (returns immediately)
     *
     * Data layout:
     *   host_list[0]:remote_addrs[0] -> local_buffer[0..lengths[0]]
     *   host_list[1]:remote_addrs[1] -> local_buffer[lengths[0]..lengths[0]+lengths[1]]
     *   ...
     */
    TransferHandle gatherAsync(uintptr_t local_addr,
                               const std::vector<std::string> &host_list,
                               const std::vector<uintptr_t> &remote_addrs,
                               const std::vector<size_t> &lengths);

    /**
     * Start async broadcast operation (returns immediately)
     *
     * Broadcasts the same local data to all destinations.
     */
    TransferHandle broadcastAsync(uintptr_t local_addr,
                                  size_t length,
                                  const std::vector<std::string> &host_list,
                                  const std::vector<uintptr_t> &remote_addrs);

    /**
     * Start async put operation (RDMA WRITE to single host)
     */
    TransferHandle putAsync(uintptr_t local_addr,
                            const std::string &remote_host_id,
                            uintptr_t remote_addr,
                            size_t length);

    /**
     * Start async get operation (RDMA READ from single host)
     */
    TransferHandle getAsync(uintptr_t local_addr,
                            const std::string &remote_host_id,
                            uintptr_t remote_addr,
                            size_t length);

    /**
     * Check if async transfer is complete (non-blocking)
     */
    bool isTransferComplete(TransferHandle handle);

    /**
     * Wait for async transfer to complete (blocking with optional timeout)
     * @param timeout_ms  -1 = wait forever
     */
    int waitTransfer(TransferHandle handle, int timeout_ms = -1);

    /**
     * Get result of completed async transfer
     */
    TransferResult getTransferResult(TransferHandle handle);

    /**
     * Release async transfer handle and associated resources
     */
    void releaseTransfer(TransferHandle handle);

    // ==================== End Async Transfer API ====================

    /** Get number of available NICs */
    size_t getNumNics() const;

    /** Get local host ID */
    const std::string &getLocalHostId() const;

    /** Get TCP port for metadata exchange */
    int getTcpPort() const;

    /** Get GID string for a specific NIC */
    std::string getGid(size_t nic_index) const;

    /** Get device name for a specific NIC */
    std::string getDeviceName(size_t nic_index) const;

    /** Get all active device names */
    std::vector<std::string> getActiveDevices() const;

    /** Get the NIC filter environment variable name */
    static const char* getNicFilterEnvVarName();

    /** Get the current max RDMA transfer size */
    size_t getMaxRdmaTransferSize() const;

    /** Get the number of QPs per connection */
    size_t getQpsPerConnection() const;

    /** Get the QPs per connection environment variable name */
    static const char* getQpsPerConnectionEnvVarName();

    /** Get NUMA topology information */
    const std::vector<NumaTopology>& getNumaTopology() const;

    /** Get NIC topology information */
    const std::vector<NicTopologyInfo>& getNicTopology() const;

    /** Get the NUMA node for a specific NIC */
    int getNicNumaNode(const std::string& nic_name) const;

    /** Get NUMA node for a given memory address */
    int getNumaNodeForAddr(void* addr) const;

    /** Get local NIC indices for a specific NUMA node */
    std::vector<size_t> getLocalNicIndicesForNuma(int numa_node) const;

    /** Get the NUMA node for a specific GPU device */
    int getGpuNumaNode(int gpu_device_id) const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace mpcomm

#endif  // MPCOMM_MPCOMM_H_
