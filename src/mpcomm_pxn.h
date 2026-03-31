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

#ifndef MPCOMM_PXN_H_
#define MPCOMM_PXN_H_

#include "mpcomm_log.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#ifdef USE_CUDA
#include <cuda.h>
#endif

namespace mpcomm {

// =====================================================================
// Lock-free SPSC (Single Producer, Single Consumer) Ring Buffer Queue
// =====================================================================

template <typename T, size_t Capacity>
class SpscQueue {
public:
    SpscQueue() : head_(0), tail_(0) {}

    // Non-copyable, non-movable
    SpscQueue(const SpscQueue&) = delete;
    SpscQueue& operator=(const SpscQueue&) = delete;

    // Producer: try to push an item. Returns false if full.
    bool tryPush(const T& item) {
        size_t cur_tail = tail_.load(std::memory_order_relaxed);
        size_t next_tail = (cur_tail + 1) % (Capacity + 1);
        if (next_tail == head_.load(std::memory_order_acquire)) {
            return false;  // Full
        }
        buffer_[cur_tail] = item;
        tail_.store(next_tail, std::memory_order_release);
        return true;
    }

    // Consumer: try to pop an item. Returns false if empty.
    bool tryPop(T& item) {
        size_t cur_head = head_.load(std::memory_order_relaxed);
        if (cur_head == tail_.load(std::memory_order_acquire)) {
            return false;  // Empty
        }
        item = buffer_[cur_head];
        head_.store((cur_head + 1) % (Capacity + 1), std::memory_order_release);
        return true;
    }

    bool empty() const {
        return head_.load(std::memory_order_acquire) ==
               tail_.load(std::memory_order_acquire);
    }

private:
    T buffer_[Capacity + 1];  // One extra slot for full/empty disambiguation
    alignas(64) std::atomic<size_t> head_;
    alignas(64) std::atomic<size_t> tail_;
};

// =====================================================================
// PXN (NVLink Proxy) Configuration
// =====================================================================

// Environment variable names
inline constexpr const char* kPxnEnableEnvVar = "MPCOMM_PXN_ENABLE";
inline constexpr const char* kPxnBufferSizeEnvVar = "MPCOMM_PXN_BUFFER_SIZE";
inline constexpr const char* kPxnDirectRatioEnvVar = "MPCOMM_PXN_DIRECT_RATIO";
inline constexpr const char* kPxnBenchSequentialEnvVar = "MPCOMM_PXN_BENCH_SEQUENTIAL";

// Default proxy buffer size per GPU: 256 MB
static constexpr size_t kPxnDefaultBufferSize = 256ULL << 20;

// Maximum number of GPUs supported for PXN
static constexpr size_t kPxnMaxGpus = 16;

// Maximum pending copy requests per GPU copy thread
static constexpr size_t kPxnCopyQueueCapacity = 4096;

// Number of CUDA streams per copy thread for NVLink copy pipelining
static constexpr size_t kPxnStreamsPerThread = 8;

// =====================================================================
// PXN Data Structures
// =====================================================================

// Information about a single GPU's topology
struct PxnGpuInfo {
    int device_id;                          // CUDA device ordinal
    std::vector<size_t> direct_nic_indices; // PCIe-affine NIC indices
    std::vector<int> nvlink_peers;          // NVLink-connected peer GPU device IDs
};

#ifdef USE_CUDA

// Proxy buffer allocated on a single GPU for PXN forwarding.
// Uses a simple ring buffer allocator for sub-allocations.
struct PxnProxyBuffer {
    int gpu_device_id;
    CUdeviceptr buffer;          // GPU HBM base address
    size_t size;                 // Total buffer size in bytes
    CUcontext cuda_ctx;          // CUDA context for this GPU

    // Ring buffer allocator state (used by worker thread, no lock needed
    // since each worker processes chunks sequentially per transfer)
    std::atomic<size_t> alloc_offset;  // Current allocation offset
    std::atomic<size_t> free_offset;   // Current free offset

    PxnProxyBuffer()
        : gpu_device_id(-1), buffer(0), size(0), cuda_ctx(nullptr),
          alloc_offset(0), free_offset(0) {}

    // Move constructor (std::atomic is not movable, so copy values manually)
    PxnProxyBuffer(PxnProxyBuffer&& other) noexcept
        : gpu_device_id(other.gpu_device_id),
          buffer(other.buffer),
          size(other.size),
          cuda_ctx(other.cuda_ctx),
          alloc_offset(other.alloc_offset.load(std::memory_order_relaxed)),
          free_offset(other.free_offset.load(std::memory_order_relaxed)) {
        other.buffer = 0;
        other.cuda_ctx = nullptr;
    }

    // Move assignment
    PxnProxyBuffer& operator=(PxnProxyBuffer&& other) noexcept {
        if (this != &other) {
            gpu_device_id = other.gpu_device_id;
            buffer = other.buffer;
            size = other.size;
            cuda_ctx = other.cuda_ctx;
            alloc_offset.store(other.alloc_offset.load(std::memory_order_relaxed),
                               std::memory_order_relaxed);
            free_offset.store(other.free_offset.load(std::memory_order_relaxed),
                              std::memory_order_relaxed);
            other.buffer = 0;
            other.cuda_ctx = nullptr;
        }
        return *this;
    }

    // Non-copyable
    PxnProxyBuffer(const PxnProxyBuffer&) = delete;
    PxnProxyBuffer& operator=(const PxnProxyBuffer&) = delete;

    // Try to allocate `len` bytes from the ring buffer.
    // Returns 0 if not enough space. Thread-safe for single producer.
    CUdeviceptr tryAlloc(size_t len) {
        size_t aligned_len = (len + 255) & ~255ULL;  // 256-byte alignment
        size_t cur = alloc_offset.load(std::memory_order_relaxed);
        size_t free = free_offset.load(std::memory_order_acquire);

        // Simple linear allocation (no wrap-around for simplicity)
        // Reset when both pointers reach the end
        if (cur + aligned_len > size) {
            if (free == cur) {
                // Buffer is empty, reset both pointers
                alloc_offset.store(0, std::memory_order_relaxed);
                free_offset.store(0, std::memory_order_release);
                cur = 0;
            } else {
                return 0;  // No space, need to wait for completions
            }
        }

        alloc_offset.store(cur + aligned_len, std::memory_order_relaxed);
        return buffer + cur;
    }

    // Free `len` bytes (advance free pointer)
    void free(size_t len) {
        size_t aligned_len = (len + 255) & ~255ULL;
        free_offset.fetch_add(aligned_len, std::memory_order_release);
    }

    // Reset allocator state (for reuse between rounds in static partition mode)
    void resetAllocator() {
        alloc_offset.store(0, std::memory_order_relaxed);
        free_offset.store(0, std::memory_order_release);
    }
};

// Pending NVLink copy that hasn't completed yet.
// Worker thread checks the atomic flag to know when RDMA post can proceed.
struct PxnPendingChunk {
    size_t chunk_idx;           // Original chunk index in TransferContext
    size_t host_idx;            // Host index for connection lookup
    size_t nic_index;           // Target NIC for RDMA post
    size_t qp_index;            // QP index within the NIC
    CUdeviceptr proxy_addr;     // Address in proxy buffer (for sge.addr)
    size_t proxy_gpu_idx;       // Index into pxn_proxy_buffers_ (for free)
    uintptr_t remote_addr;      // Remote RDMA address
    size_t length;              // Chunk length
    std::atomic<bool>* copy_done_flag;  // Set by CUDA stream callback when copy completes
};

// =====================================================================
// PXN Copy Thread Request / Result (for dedicated copy threads)
// =====================================================================

// Request submitted by worker thread to a GPU's copy thread
struct PxnCopyRequest {
    CUdeviceptr src_addr;
    CUcontext src_ctx;          // Pre-resolved source CUDA context
    CUdeviceptr dst_addr;
    CUcontext dst_ctx;          // Pre-resolved destination CUDA context
    size_t length;
    uint64_t request_id;        // Opaque ID for correlating results
};

// Result returned by copy thread after NVLink copy is initiated
struct PxnCopyResult {
    uint64_t request_id;        // Matches PxnCopyRequest::request_id
    std::atomic<bool>* copy_done_flag;  // Atomic flag set by cuLaunchHostFunc callback (nullptr on error)
    bool success;
    // Fine-grained timing from copy thread (for diagnosing submit->result_recv)
    std::chrono::steady_clock::time_point t_dequeued;       // When request was popped from SPSC queue
    std::chrono::steady_clock::time_point t_copy_launched;  // After cuMemcpyPeerAsync returned
    std::chrono::steady_clock::time_point t_result_pushed;  // After cuLaunchHostFunc, just before result push
};

// Per-GPU copy thread state
struct PxnCopyThreadState {
    std::unique_ptr<std::thread> thread;
    std::atomic<bool> running{false};

    // SPSC queues: worker (producer) -> copy thread (consumer) for requests,
    //              copy thread (producer) -> worker (consumer) for results.
    SpscQueue<PxnCopyRequest, kPxnCopyQueueCapacity> request_queue;
    SpscQueue<PxnCopyResult, kPxnCopyQueueCapacity> result_queue;

    // Recycle queue: worker (producer) -> copy thread (consumer) for returning flags.
    // Worker returns used atomic<bool>* flags so the copy thread can reuse them.
    SpscQueue<std::atomic<bool>*, kPxnCopyQueueCapacity> recycle_queue;

    // Per-GPU resources managed by the single copy thread.
    // Indexed by gpu_topology_ index (not device_id).
    struct PerGpuResources {
        int gpu_device_id = -1;
        CUcontext cuda_ctx = nullptr;
        CUstream streams[kPxnStreamsPerThread] = {};
        size_t next_stream_idx = 0;
    };

    // Pool of reusable atomic<bool> flags for copy completion notification.
    // Managed by the copy thread (single-threaded access for alloc/recycle).
    std::vector<std::atomic<bool>*> flag_pool;
    std::vector<PerGpuResources> gpu_resources;

    // Map from gpu_device_id to index in gpu_resources
    std::unordered_map<int, size_t> gpu_dev_to_res_idx;

    PxnCopyThreadState() = default;

    // Non-copyable, non-movable
    PxnCopyThreadState(const PxnCopyThreadState&) = delete;
    PxnCopyThreadState& operator=(const PxnCopyThreadState&) = delete;
};

// =====================================================================
// PxnManager: Manages NVLink topology, proxy buffers, and data copies
// =====================================================================

class PxnManager {
public:
    PxnManager();
    ~PxnManager();

    // Non-copyable
    PxnManager(const PxnManager&) = delete;
    PxnManager& operator=(const PxnManager&) = delete;

    // Initialize PXN subsystem. Call after CUDA is available.
    // `nic_count` is the total number of NICs.
    // `get_gpu_pcie_nics` is a callback to get PCIe-affine NIC indices for a GPU.
    // Returns true if PXN is enabled and initialized successfully.
    bool init(size_t nic_count,
              std::function<std::vector<size_t>(int gpu_device_id)> get_gpu_pcie_nics);

    // Shutdown and free all resources
    void shutdown();

    // Check if PXN is enabled and initialized
    bool isEnabled() const { return enabled_; }

    // Get the configured proxy buffer size
    size_t getBufferSize() const { return buffer_size_; }

    // Get number of discovered GPUs
    size_t getGpuCount() const { return gpu_topology_.size(); }

    // Get topology info for a GPU
    const PxnGpuInfo* getGpuInfo(int device_id) const;

    // Get all NIC indices reachable from a GPU via NVLink (including direct NICs)
    std::vector<size_t> getAllReachableNics(int gpu_device_id) const;

    // Get the proxy GPU device ID for a given NIC index.
    // Returns -1 if the NIC is directly connected to src_gpu (no proxy needed),
    // or the device_id of the proxy GPU that owns this NIC.
    int getProxyGpuForNic(int src_gpu_device_id, size_t nic_index) const;

    // Get proxy buffer for a specific GPU device
    PxnProxyBuffer* getProxyBuffer(int gpu_device_id);

    // Register proxy buffers with a NIC (call registerMemory for each proxy buffer).
    // The caller provides a callback that performs the actual ibv_reg_mr.
    // Returns 0 on success.
    int registerProxyBuffers(
        std::function<int(void* addr, size_t length)> register_fn);

    // Unregister proxy buffers
    int unregisterProxyBuffers(
        std::function<int(void* addr)> unregister_fn);

    // Submit an async NVLink copy request to the dedicated copy thread.
    // Returns true if the request was enqueued successfully.
    // The copy thread will process it without any CUDA context switching.
    bool submitCopyRequest(int dst_gpu_device_id, const PxnCopyRequest& request);

    // Poll for completed copy results from the single copy thread.
    // Returns the number of results retrieved.
    // Results are appended to `results`.
    size_t pollCopyResults(int dst_gpu_device_id,
                           std::vector<PxnCopyResult>& results);

    // Poll copy results from the single copy thread.
    // Returns total number of results retrieved.
    size_t pollAllCopyResults(std::vector<PxnCopyResult>& results);

    // Recycle a copy-done flag back to the copy thread's pool for reuse.
    void recycleFlagToThread(std::atomic<bool>* flag);

    // Get lkey for a proxy buffer address on a specific NIC.
    // This is needed because the RDMA post must use the proxy buffer's lkey,
    // not the original source buffer's lkey.
    uint32_t getProxyLkey(int proxy_gpu_device_id, size_t nic_index) const;

    // Store lkey mapping (called during proxy buffer registration)
    void setProxyLkey(int proxy_gpu_device_id, size_t nic_index, uint32_t lkey);

private:
    // Discover NVLink topology between GPUs
    bool discoverNvlinkTopology();

    // Allocate proxy buffers on each GPU
    bool allocateProxyBuffers();

    // Free proxy buffers
    void freeProxyBuffers();

    // Run GPU-to-GPU copy bandwidth benchmark during init
    void benchmarkGpuCopyBandwidth();

    // Start the single unified copy thread (called from init when PXN is enabled)
    bool startCopyThreads();

    // Stop the copy thread (called from shutdown)
    void stopCopyThreads();

    // Copy thread main loop (runs on a single dedicated thread)
    void copyThreadLoop(PxnCopyThreadState* state);

    bool enabled_;
    size_t buffer_size_;
    size_t nic_count_;

    // GPU topology: device_id -> PxnGpuInfo
    std::vector<PxnGpuInfo> gpu_topology_;
    std::unordered_map<int, size_t> device_id_to_idx_;  // device_id -> index in gpu_topology_

    // NIC -> GPU mapping: nic_index -> GPU device_id that owns it (PCIe-affine)
    std::unordered_map<size_t, int> nic_to_gpu_;

    // Proxy buffers: one per GPU
    std::vector<PxnProxyBuffer> proxy_buffers_;

    // Proxy buffer lkeys: [gpu_device_id][nic_index] -> lkey
    std::unordered_map<int, std::unordered_map<size_t, uint32_t>> proxy_lkeys_;
    mutable std::mutex proxy_lkeys_mutex_;

    // Single unified copy thread (handles all proxy GPUs)
    std::unique_ptr<PxnCopyThreadState> copy_thread_;
};

#else  // !USE_CUDA

// Stub PxnManager when CUDA is not available
class PxnManager {
public:
    PxnManager() {}
    ~PxnManager() {}
    bool init(size_t, std::function<std::vector<size_t>(int)>) { return false; }
    void shutdown() {}
    bool isEnabled() const { return false; }
    size_t getBufferSize() const { return 0; }
    size_t getGpuCount() const { return 0; }
    std::vector<size_t> getAllReachableNics(int) const { return {}; }
    int getProxyGpuForNic(int, size_t) const { return -1; }
};

#endif  // USE_CUDA

}  // namespace mpcomm

#endif  // MPCOMM_PXN_H_
