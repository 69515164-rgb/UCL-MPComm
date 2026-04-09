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

#include "mpcomm_pxn.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <immintrin.h>  // _mm_pause
#include <pthread.h>    // pthread_self

namespace mpcomm {

#ifdef USE_CUDA

// =====================================================================
// PxnManager Implementation
// =====================================================================

PxnManager::PxnManager()
    : enabled_(false), buffer_size_(kPxnDefaultBufferSize), nic_count_(0) {}

PxnManager::~PxnManager() {
    shutdown();
}

bool PxnManager::init(
    size_t nic_count,
    std::function<std::vector<size_t>(int gpu_device_id)> get_gpu_pcie_nics) {

    // Check environment variable
    const char* env_enable = std::getenv(kPxnEnableEnvVar);
    if (!env_enable || std::string(env_enable) != "1") {
        MPCOMM_LOG_INFO("MPComm PXN: Disabled (set %s=1 to enable)\n",
                        kPxnEnableEnvVar);
        enabled_ = false;
        return false;
    }

    // Read buffer size from environment
    const char* env_buf_size = std::getenv(kPxnBufferSizeEnvVar);
    if (env_buf_size && env_buf_size[0] != '\0') {
        char* endptr = nullptr;
        unsigned long long val = strtoull(env_buf_size, &endptr, 10);
        if (endptr != env_buf_size && *endptr == '\0' && val > 0) {
            buffer_size_ = static_cast<size_t>(val);
            MPCOMM_LOG_INFO("MPComm PXN: Using buffer size from %s: %zu bytes\n",
                            kPxnBufferSizeEnvVar, buffer_size_);
        } else {
            MPCOMM_LOG_WARN("MPComm PXN: Invalid %s value '%s', using default %zu\n",
                            kPxnBufferSizeEnvVar, env_buf_size, buffer_size_);
        }
    }

    nic_count_ = nic_count;

    // Step 1: Discover NVLink topology
    if (!discoverNvlinkTopology()) {
        MPCOMM_LOG_WARN("MPComm PXN: NVLink topology discovery failed, PXN disabled\n");
        enabled_ = false;
        return false;
    }

    // Step 2: Build NIC -> GPU mapping using the provided callback
    for (auto& gpu_info : gpu_topology_) {
        gpu_info.direct_nic_indices = get_gpu_pcie_nics(gpu_info.device_id);
        for (size_t nic_idx : gpu_info.direct_nic_indices) {
            nic_to_gpu_[nic_idx] = gpu_info.device_id;
        }
    }

    // Log NIC-GPU mapping
    MPCOMM_LOG_INFO("MPComm PXN: NIC-to-GPU mapping:\n");
    for (const auto& [nic_idx, gpu_id] : nic_to_gpu_) {
        MPCOMM_LOG_INFO("  NIC %zu -> GPU %d\n", nic_idx, gpu_id);
    }

    // Step 3: Allocate proxy buffers on each GPU
    if (!allocateProxyBuffers()) {
        MPCOMM_LOG_ERROR("MPComm PXN: Failed to allocate proxy buffers\n");
        enabled_ = false;
        return false;
    }

    // Step 4: Start per-GPU copy threads (dedicated context, no switching)
    if (!startCopyThreads()) {
        MPCOMM_LOG_ERROR("MPComm PXN: Failed to start copy threads\n");
        freeProxyBuffers();
        enabled_ = false;
        return false;
    }

    enabled_ = true;
    MPCOMM_LOG_INFO("MPComm PXN: Enabled with %zu GPUs, %zu NICs, "
                    "buffer_size=%zu MB per GPU, 1 unified copy thread\n",
                    gpu_topology_.size(), nic_count_,
                    buffer_size_ >> 20);
    return true;
}

void PxnManager::shutdown() {
    if (!enabled_) return;

    // Stop copy threads first (they use contexts)
    stopCopyThreads();

    // Free proxy buffers (releases primary contexts)
    freeProxyBuffers();

    gpu_topology_.clear();
    device_id_to_idx_.clear();
    nic_to_gpu_.clear();
    proxy_lkeys_.clear();

    enabled_ = false;
    MPCOMM_LOG_INFO("MPComm PXN: Shutdown complete\n");
}

// =====================================================================
// NVLink Topology Discovery
// =====================================================================

bool PxnManager::discoverNvlinkTopology() {
    // Ensure CUDA driver API is initialized before querying devices.
    // cuInit is safe to call multiple times — subsequent calls are no-ops.
    CUresult init_res = cuInit(0);
    if (init_res != CUDA_SUCCESS) {
        MPCOMM_LOG_WARN("MPComm PXN: cuInit failed: %d\n", init_res);
        return false;
    }

    int device_count = 0;
    CUresult res = cuDeviceGetCount(&device_count);
    if (res != CUDA_SUCCESS || device_count <= 1) {
        MPCOMM_LOG_INFO("MPComm PXN: Only %d GPU(s) found, PXN requires >= 2\n",
                        device_count);
        return false;
    }

    MPCOMM_LOG_INFO("MPComm PXN: Discovering NVLink topology for %d GPUs...\n",
                    device_count);

    gpu_topology_.resize(device_count);
    for (int i = 0; i < device_count; ++i) {
        gpu_topology_[i].device_id = i;
        device_id_to_idx_[i] = static_cast<size_t>(i);
    }

    // Probe P2P accessibility and NVLink connectivity between all GPU pairs
    for (int i = 0; i < device_count; ++i) {
        for (int j = 0; j < device_count; ++j) {
            if (i == j) continue;

            int can_access = 0;
            res = cuDeviceCanAccessPeer(&can_access, i, j);
            if (res != CUDA_SUCCESS || !can_access) continue;

            // Check if the link is NVLink (not just PCIe P2P)
            int perf_rank = 0;
            res = cuDeviceGetP2PAttribute(
                &perf_rank,
                CU_DEVICE_P2P_ATTRIBUTE_PERFORMANCE_RANK,
                i, j);

            // perf_rank > 0 indicates a high-performance link (NVLink)
            // perf_rank == 0 might be PCIe P2P which is too slow for PXN
            if (res == CUDA_SUCCESS && perf_rank > 0) {
                gpu_topology_[i].nvlink_peers.push_back(j);
                MPCOMM_LOG_INFO("  GPU %d <-> GPU %d: NVLink (perf_rank=%d)\n",
                                i, j, perf_rank);
            } else if (can_access) {
                // PCIe P2P — still usable but slower, include with a note
                gpu_topology_[i].nvlink_peers.push_back(j);
                MPCOMM_LOG_INFO("  GPU %d <-> GPU %d: P2P (perf_rank=%d, may be PCIe)\n",
                                i, j, perf_rank);
            }
        }
    }

    // Verify at least some NVLink connections exist
    bool has_nvlink = false;
    for (const auto& gpu : gpu_topology_) {
        if (!gpu.nvlink_peers.empty()) {
            has_nvlink = true;
            break;
        }
    }

    if (!has_nvlink) {
        MPCOMM_LOG_INFO("MPComm PXN: No NVLink/P2P connections found between GPUs\n");
        return false;
    }

    return true;
}

// =====================================================================
// Proxy Buffer Management
// =====================================================================

bool PxnManager::allocateProxyBuffers() {
    proxy_buffers_.resize(gpu_topology_.size());

    for (size_t i = 0; i < gpu_topology_.size(); ++i) {
        int dev_id = gpu_topology_[i].device_id;
        auto& pb = proxy_buffers_[i];
        pb.gpu_device_id = dev_id;
        pb.size = buffer_size_;

        // Get or retain the primary context for this GPU
        CUdevice cu_dev;
        CUresult res = cuDeviceGet(&cu_dev, dev_id);
        if (res != CUDA_SUCCESS) {
            MPCOMM_LOG_ERROR("MPComm PXN: cuDeviceGet(%d) failed: %d\n",
                             dev_id, res);
            freeProxyBuffers();
            return false;
        }

        res = cuDevicePrimaryCtxRetain(&pb.cuda_ctx, cu_dev);
        if (res != CUDA_SUCCESS) {
            MPCOMM_LOG_ERROR("MPComm PXN: cuDevicePrimaryCtxRetain(%d) failed: %d\n",
                             dev_id, res);
            freeProxyBuffers();
            return false;
        }

        // Push context, allocate buffer, pop context
        CUcontext old_ctx;
        cuCtxPushCurrent(pb.cuda_ctx);

        res = cuMemAlloc(&pb.buffer, buffer_size_);
        if (res != CUDA_SUCCESS) {
            MPCOMM_LOG_ERROR("MPComm PXN: cuMemAlloc(%zu) on GPU %d failed: %d\n",
                             buffer_size_, dev_id, res);
            cuCtxPopCurrent(&old_ctx);
            cuDevicePrimaryCtxRelease(cu_dev);
            pb.cuda_ctx = nullptr;
            freeProxyBuffers();
            return false;
        }

        cuCtxPopCurrent(&old_ctx);

        pb.alloc_offset.store(0);
        pb.free_offset.store(0);

        MPCOMM_LOG_INFO("MPComm PXN: Allocated %zu MB proxy buffer on GPU %d "
                        "(addr=0x%llx)\n",
                        buffer_size_ >> 20, dev_id,
                        (unsigned long long)pb.buffer);
    }

    // Enable P2P access between all GPU pairs that have NVLink
    for (size_t i = 0; i < gpu_topology_.size(); ++i) {
        int src_dev = gpu_topology_[i].device_id;
        CUdevice src_cu_dev;
        cuDeviceGet(&src_cu_dev, src_dev);

        CUcontext old_ctx;
        cuCtxPushCurrent(proxy_buffers_[i].cuda_ctx);

        for (int peer_dev : gpu_topology_[i].nvlink_peers) {
            auto it = device_id_to_idx_.find(peer_dev);
            if (it == device_id_to_idx_.end()) continue;

            CUresult res = cuCtxEnablePeerAccess(
                proxy_buffers_[it->second].cuda_ctx, 0);
            if (res != CUDA_SUCCESS && res != CUDA_ERROR_PEER_ACCESS_ALREADY_ENABLED) {
                MPCOMM_LOG_WARN("MPComm PXN: cuCtxEnablePeerAccess GPU %d -> GPU %d "
                                "failed: %d\n", src_dev, peer_dev, res);
            }
        }

        cuCtxPopCurrent(&old_ctx);
    }

    return true;
}

void PxnManager::freeProxyBuffers() {
    for (auto& pb : proxy_buffers_) {
        if (pb.buffer != 0 && pb.cuda_ctx != nullptr) {
            CUcontext old_ctx;
            cuCtxPushCurrent(pb.cuda_ctx);
            cuMemFree(pb.buffer);
            cuCtxPopCurrent(&old_ctx);
            pb.buffer = 0;
        }
        if (pb.cuda_ctx != nullptr) {
            CUdevice cu_dev;
            if (cuDeviceGet(&cu_dev, pb.gpu_device_id) == CUDA_SUCCESS) {
                cuDevicePrimaryCtxRelease(cu_dev);
            }
            pb.cuda_ctx = nullptr;
        }
    }
    proxy_buffers_.clear();
}

// =====================================================================
// NVLink Copy Event Utilities
// =====================================================================
const PxnGpuInfo* PxnManager::getGpuInfo(int device_id) const {
    auto it = device_id_to_idx_.find(device_id);
    if (it == device_id_to_idx_.end()) return nullptr;
    return &gpu_topology_[it->second];
}

std::vector<size_t> PxnManager::getAllReachableNics(int gpu_device_id) const {
    std::vector<size_t> result;
    auto it = device_id_to_idx_.find(gpu_device_id);
    if (it == device_id_to_idx_.end()) return result;

    const auto& gpu = gpu_topology_[it->second];

    // Add direct NICs first
    for (size_t nic : gpu.direct_nic_indices) {
        result.push_back(nic);
    }

    // Add NICs reachable via NVLink peers
    for (int peer_dev : gpu.nvlink_peers) {
        auto peer_it = device_id_to_idx_.find(peer_dev);
        if (peer_it == device_id_to_idx_.end()) continue;
        const auto& peer_gpu = gpu_topology_[peer_it->second];
        for (size_t nic : peer_gpu.direct_nic_indices) {
            // Avoid duplicates
            if (std::find(result.begin(), result.end(), nic) == result.end()) {
                result.push_back(nic);
            }
        }
    }

    return result;
}

int PxnManager::getProxyGpuForNic(int src_gpu_device_id,
                                   size_t nic_index) const {
    auto it = device_id_to_idx_.find(src_gpu_device_id);
    if (it == device_id_to_idx_.end()) return -1;

    const auto& src_gpu = gpu_topology_[it->second];

    // Check if this NIC is directly connected to src GPU
    for (size_t nic : src_gpu.direct_nic_indices) {
        if (nic == nic_index) return -1;  // Direct, no proxy needed
    }

    // Find which GPU owns this NIC
    auto nic_it = nic_to_gpu_.find(nic_index);
    if (nic_it == nic_to_gpu_.end()) return -1;

    return nic_it->second;  // Return the proxy GPU's device_id
}

PxnProxyBuffer* PxnManager::getProxyBuffer(int gpu_device_id) {
    auto it = device_id_to_idx_.find(gpu_device_id);
    if (it == device_id_to_idx_.end()) return nullptr;
    if (it->second >= proxy_buffers_.size()) return nullptr;
    return &proxy_buffers_[it->second];
}

// =====================================================================
// Proxy Buffer Registration
// =====================================================================

int PxnManager::registerProxyBuffers(
    std::function<int(void* addr, size_t length)> register_fn) {
    for (auto& pb : proxy_buffers_) {
        if (pb.buffer == 0) continue;
        int ret = register_fn(reinterpret_cast<void*>(pb.buffer), pb.size);
        if (ret != 0) {
            MPCOMM_LOG_ERROR("MPComm PXN: Failed to register proxy buffer on "
                             "GPU %d: %d\n", pb.gpu_device_id, ret);
            return ret;
        }
        MPCOMM_LOG_INFO("MPComm PXN: Registered proxy buffer GPU %d "
                        "(addr=0x%llx, size=%zu)\n",
                        pb.gpu_device_id,
                        (unsigned long long)pb.buffer, pb.size);
    }
    return 0;
}

int PxnManager::unregisterProxyBuffers(
    std::function<int(void* addr)> unregister_fn) {
    for (auto& pb : proxy_buffers_) {
        if (pb.buffer == 0) continue;
        unregister_fn(reinterpret_cast<void*>(pb.buffer));
    }
    return 0;
}

// =====================================================================
// NVLink Copy Event Utilities
// =====================================================================

bool PxnManager::isEventDone(CUevent event) {
    if (!event) return true;
    CUresult res = cuEventQuery(event);
    return (res == CUDA_SUCCESS);
}

void PxnManager::recycleEventToThread(int gpu_device_id, CUevent event) {
    if (!event) return;
    if (copy_thread_) {
        PxnCopyThreadState::RecycledEvent re;
        re.gpu_device_id = gpu_device_id;
        re.event = event;
        if (copy_thread_->recycle_queue.tryPush(re)) {
            return;
        }
    }
    // Recycle queue full or thread not found — destroy the event
    cuEventDestroy(event);
}

// =====================================================================
// Unified Copy Thread
// =====================================================================

bool PxnManager::startCopyThreads() {
    auto state = std::make_unique<PxnCopyThreadState>();

    // Collect all GPUs that have NVLink peers (potential proxy destinations)
    for (size_t i = 0; i < gpu_topology_.size(); ++i) {
        if (gpu_topology_[i].nvlink_peers.empty()) continue;

        int dev_id = gpu_topology_[i].device_id;
        PxnCopyThreadState::PerGpuResources res;
        res.gpu_device_id = dev_id;
        res.cuda_ctx = proxy_buffers_[i].cuda_ctx;
        res.next_stream_idx = 0;

        size_t idx = state->gpu_resources.size();
        state->gpu_dev_to_res_idx[dev_id] = idx;
        state->gpu_resources.push_back(std::move(res));
    }

    if (state->gpu_resources.empty()) {
        MPCOMM_LOG_INFO("MPComm PXN: No proxy GPUs found, skipping copy thread\n");
        return true;
    }

    state->running.store(true, std::memory_order_relaxed);

    PxnCopyThreadState* raw_ptr = state.get();
    state->thread = std::make_unique<std::thread>(
        &PxnManager::copyThreadLoop, this, raw_ptr);

    copy_thread_ = std::move(state);
    MPCOMM_LOG_INFO("MPComm PXN: Started unified copy thread for %zu proxy GPUs\n",
                    copy_thread_->gpu_resources.size());
    return true;
}

void PxnManager::stopCopyThreads() {
    if (!copy_thread_) return;

    // Signal the thread to stop
    copy_thread_->running.store(false, std::memory_order_release);

    // Join the thread
    if (copy_thread_->thread && copy_thread_->thread->joinable()) {
        copy_thread_->thread->join();
    }

    // Destroy per-GPU event pools
    for (auto& gpu_res : copy_thread_->gpu_resources) {
        if (gpu_res.cuda_ctx) {
            CUcontext old_ctx;
            cuCtxPushCurrent(gpu_res.cuda_ctx);
            for (CUevent ev : gpu_res.event_pool) {
                cuEventDestroy(ev);
            }
            cuCtxPopCurrent(&old_ctx);
        }
        gpu_res.event_pool.clear();
    }

    // Drain recycle queue
    PxnCopyThreadState::RecycledEvent recycled;
    while (copy_thread_->recycle_queue.tryPop(recycled)) {
        cuEventDestroy(recycled.event);
    }

    copy_thread_.reset();
}

void PxnManager::copyThreadLoop(PxnCopyThreadState* state) {
    // Initialize per-GPU streams by temporarily pushing each GPU's context
    for (auto& gpu_res : state->gpu_resources) {
        CUcontext old_ctx;
        cuCtxPushCurrent(gpu_res.cuda_ctx);

        bool ok = true;
        for (size_t s = 0; s < kPxnStreamsPerThread; ++s) {
            CUresult stream_res = cuStreamCreate(&gpu_res.streams[s], CU_STREAM_NON_BLOCKING);
            if (stream_res != CUDA_SUCCESS) {
                MPCOMM_LOG_ERROR("MPComm PXN: Unified copy thread GPU %d: "
                                "cuStreamCreate[%zu] failed: %d\n",
                                gpu_res.gpu_device_id, s, stream_res);
                for (size_t j = 0; j < s; ++j) {
                    cuStreamDestroy(gpu_res.streams[j]);
                    gpu_res.streams[j] = nullptr;
                }
                ok = false;
                break;
            }
        }
        gpu_res.next_stream_idx = 0;

        cuCtxPopCurrent(&old_ctx);

        if (!ok) {
            MPCOMM_LOG_ERROR("MPComm PXN: Unified copy thread failed to init GPU %d\n",
                            gpu_res.gpu_device_id);
            return;
        }
    }

    MPCOMM_LOG_INFO("MPComm PXN: Unified copy thread started with %zu GPUs, "
                    "%zu streams/GPU (tid=%lu)\n",
                    state->gpu_resources.size(), kPxnStreamsPerThread,
                    static_cast<unsigned long>(pthread_self()));

    while (state->running.load(std::memory_order_acquire)) {
        // Drain recycled events back to per-GPU event pools
        PxnCopyThreadState::RecycledEvent recycled;
        while (state->recycle_queue.tryPop(recycled)) {
            auto rit = state->gpu_dev_to_res_idx.find(recycled.gpu_device_id);
            if (rit != state->gpu_dev_to_res_idx.end()) {
                state->gpu_resources[rit->second].event_pool.push_back(recycled.event);
            } else {
                cuEventDestroy(recycled.event);
            }
        }

        PxnCopyRequest req;
        if (!state->request_queue.tryPop(req)) {
            _mm_pause();
            continue;
        }

        PxnCopyResult result;
        result.request_id = req.request_id;
        result.t_dequeued = std::chrono::steady_clock::now();

        // Find the per-GPU resources for the destination GPU (by dst_ctx)
        PxnCopyThreadState::PerGpuResources* gpu_res = nullptr;
        for (auto& gr : state->gpu_resources) {
            if (gr.cuda_ctx == req.dst_ctx) {
                gpu_res = &gr;
                break;
            }
        }

        if (!gpu_res) {
            MPCOMM_LOG_ERROR("MPComm PXN: Unified copy thread: no GPU resources "
                            "for dst_ctx=%p\n", (void*)req.dst_ctx);
            result.completion_event = nullptr;
            result.success = false;
            while (!state->result_queue.tryPush(result)) {
                _mm_pause();
            }
            continue;
        }

        // Pick stream via round-robin from the destination GPU's streams
        CUstream cur_stream = gpu_res->streams[gpu_res->next_stream_idx % kPxnStreamsPerThread];
        gpu_res->next_stream_idx++;

        // cuMemcpyPeerAsync does NOT require the calling thread to have
        // a matching current context — src/dst contexts are passed explicitly.
        CUresult res = cuMemcpyPeerAsync(
            req.dst_addr, req.dst_ctx,
            req.src_addr, req.src_ctx,
            req.length, cur_stream);

        result.t_copy_launched = std::chrono::steady_clock::now();

        if (res != CUDA_SUCCESS) {
            MPCOMM_LOG_ERROR("MPComm PXN: Unified copy thread GPU %d: "
                            "cuMemcpyPeerAsync failed: %d\n",
                            gpu_res->gpu_device_id, res);
            result.completion_event = nullptr;
            result.success = false;
            while (!state->result_queue.tryPush(result)) {
                _mm_pause();
            }
            continue;
        }

        // Acquire event from per-GPU pool (no mutex — single thread)
        CUevent event = nullptr;
        if (!gpu_res->event_pool.empty()) {
            event = gpu_res->event_pool.back();
            gpu_res->event_pool.pop_back();
        } else {
            // Create event under the destination GPU's context
            CUcontext old_ctx;
            cuCtxPushCurrent(gpu_res->cuda_ctx);
            CUresult ev_res = cuEventCreate(&event, CU_EVENT_DISABLE_TIMING);
            cuCtxPopCurrent(&old_ctx);
            if (ev_res != CUDA_SUCCESS) {
                MPCOMM_LOG_ERROR("MPComm PXN: Unified copy thread GPU %d: "
                                "cuEventCreate failed: %d\n",
                                gpu_res->gpu_device_id, ev_res);
                result.completion_event = nullptr;
                result.success = false;
                while (!state->result_queue.tryPush(result)) {
                    _mm_pause();
                }
                continue;
            }
        }

        // cuEventRecord: event and stream must belong to the same context.
        // Both were created under gpu_res->cuda_ctx, so this is safe.
        res = cuEventRecord(event, cur_stream);
        if (res != CUDA_SUCCESS) {
            MPCOMM_LOG_ERROR("MPComm PXN: Unified copy thread GPU %d: "
                            "cuEventRecord failed: %d\n",
                            gpu_res->gpu_device_id, res);
            gpu_res->event_pool.push_back(event);
            result.completion_event = nullptr;
            result.success = false;
            while (!state->result_queue.tryPush(result)) {
                _mm_pause();
            }
            continue;
        }

        // Success — push result
        result.completion_event = event;
        result.success = true;
        result.t_result_pushed = std::chrono::steady_clock::now();
        while (!state->result_queue.tryPush(result)) {
            _mm_pause();
        }
    }

    // Clean up all per-GPU streams
    for (auto& gpu_res : state->gpu_resources) {
        CUcontext old_ctx;
        cuCtxPushCurrent(gpu_res.cuda_ctx);
        for (size_t s = 0; s < kPxnStreamsPerThread; ++s) {
            if (gpu_res.streams[s]) {
                cuStreamSynchronize(gpu_res.streams[s]);
                cuStreamDestroy(gpu_res.streams[s]);
                gpu_res.streams[s] = nullptr;
            }
        }
        cuCtxPopCurrent(&old_ctx);
    }

    MPCOMM_LOG_INFO("MPComm PXN: Unified copy thread stopped\n");
}

bool PxnManager::submitCopyRequest(int dst_gpu_device_id,
                                    const PxnCopyRequest& request) {
    (void)dst_gpu_device_id;  // Unified copy thread routes by dst_ctx in request
    if (!copy_thread_) return false;
    return copy_thread_->request_queue.tryPush(request);
}

size_t PxnManager::pollCopyResults(int dst_gpu_device_id,
                                    std::vector<PxnCopyResult>& results) {
    (void)dst_gpu_device_id;  // Unified copy thread uses single result queue
    return pollAllCopyResults(results);
}

size_t PxnManager::pollAllCopyResults(std::vector<PxnCopyResult>& results) {
    if (!copy_thread_) return 0;
    size_t total = 0;
    PxnCopyResult result;
    while (copy_thread_->result_queue.tryPop(result)) {
        results.push_back(result);
        ++total;
    }
    return total;
}

// =====================================================================
// Proxy Lkey Management
// =====================================================================

uint32_t PxnManager::getProxyLkey(int proxy_gpu_device_id,
                                   size_t nic_index) const {
    std::lock_guard<std::mutex> lock(proxy_lkeys_mutex_);
    auto gpu_it = proxy_lkeys_.find(proxy_gpu_device_id);
    if (gpu_it == proxy_lkeys_.end()) return 0;
    auto nic_it = gpu_it->second.find(nic_index);
    if (nic_it == gpu_it->second.end()) return 0;
    return nic_it->second;
}

void PxnManager::setProxyLkey(int proxy_gpu_device_id,
                               size_t nic_index, uint32_t lkey) {
    std::lock_guard<std::mutex> lock(proxy_lkeys_mutex_);
    proxy_lkeys_[proxy_gpu_device_id][nic_index] = lkey;
}

#endif  // USE_CUDA

}  // namespace mpcomm
