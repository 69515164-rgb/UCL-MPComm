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

// ==========================================================================
// TMA (Tensor Memory Accelerator) Kernels for HBM-DRAM Transfer
//
// These kernels use NVIDIA Hopper's TMA engine (cp.async.bulk) to
// efficiently transfer data between CPU DRAM (mapped via Zero-Copy)
// and GPU HBM. The TMA engine operates independently of SM compute
// resources, minimizing SM occupancy while saturating PCIe bandwidth.
//
// TMA kernels use a multi-warp, multi-task-per-warp design where each
// warp drives multiple independent TMA transactions concurrently,
// maximizing in-flight PCIe requests per CTA.
//
// Based on HD_comm/bench_H2D_TMA/kv_gather_tma.cu
// ==========================================================================

#include <cuda.h>
#include <cuda_runtime.h>
#include <vector_types.h>  // int4
#include <cstdint>
#include <cstdio>
#include <algorithm>

namespace mpcomm {

// L2 Cache eviction hints for TMA operations
// EvictFirst: data will be evicted from L2 first (good for streaming/one-shot access)
static constexpr uint64_t kL2EvictFirst = 0x12f0000000000000ULL;

// ==========================================================================
// TMA multi-warp configuration
//
// Each CTA launches warps_per_block warps.  Within each warp, the first
// tasks_per_warp lanes each independently issue TMA load → wait → store
// sequences.  This gives warps_per_block * tasks_per_warp concurrent
// in-flight TMA transactions per CTA, which is critical for saturating
// PCIe bandwidth with small (1 KB) blocks.
// ==========================================================================
static constexpr int kTMAWarpsPerBlock = 32;
static constexpr int kTMATasksPerWarp  = 4;
static constexpr int kTMAThreadsPerBlock = kTMAWarpsPerBlock * 32;
static constexpr int kTMATasksPerBlock = kTMAWarpsPerBlock * kTMATasksPerWarp;

// ==========================================================================
// PTX Wrappers for TMA Operations
// ==========================================================================

// Initialize a shared memory mbarrier
__device__ __forceinline__ void mbarrier_init(uint64_t* barrier_ptr, uint32_t thread_count) {
    uint32_t barrier_addr = static_cast<uint32_t>(__cvta_generic_to_shared(barrier_ptr));
    asm volatile(
        "mbarrier.init.shared.b64 [%0], %1;"
        :: "r"(barrier_addr), "r"(thread_count) : "memory"
    );
}

// Set expected transaction bytes on the mbarrier
__device__ __forceinline__ void mbarrier_expect_tx(uint64_t* barrier_ptr, uint32_t bytes) {
    uint32_t barrier_addr = static_cast<uint32_t>(__cvta_generic_to_shared(barrier_ptr));
    asm volatile(
        "mbarrier.arrive.expect_tx.shared.b64 _, [%0], %1;"
        :: "r"(barrier_addr), "r"(bytes) : "memory"
    );
}

// TMA Load: Global (CPU DRAM mapped) -> Shared Memory
// Uses cp.async.bulk with L2 cache hint for optimal PCIe bandwidth
__device__ __forceinline__ void tma_load(
    void* smem_ptr, const void* global_ptr, uint32_t size, uint64_t* barrier_ptr
) {
    uint32_t smem_addr = static_cast<uint32_t>(__cvta_generic_to_shared(smem_ptr));
    uint32_t barrier_addr = static_cast<uint32_t>(__cvta_generic_to_shared(barrier_ptr));
    asm volatile(
        "cp.async.bulk.shared::cta.global.mbarrier::complete_tx::bytes.L2::cache_hint"
        " [%0], [%1], %2, [%3], %4;"
        :: "r"(smem_addr), "l"(global_ptr), "r"(size),
           "r"(barrier_addr), "l"(kL2EvictFirst) : "memory"
    );
}

// TMA Store: Shared Memory -> Global (GPU HBM or CPU DRAM mapped)
// Uses cp.async.bulk with L2 cache hint
__device__ __forceinline__ void tma_store(
    void* global_ptr, const void* smem_ptr, uint32_t size
) {
    uint32_t smem_addr = static_cast<uint32_t>(__cvta_generic_to_shared(smem_ptr));
    asm volatile(
        "cp.async.bulk.global.shared::cta.bulk_group.L2::cache_hint"
        " [%0], [%1], %2, %3;"
        :: "l"(global_ptr), "r"(smem_addr), "r"(size), "l"(kL2EvictFirst) : "memory"
    );
}

// Wait for mbarrier with parity phase (pure busy-wait, no nanosleep)
__device__ __forceinline__ void mbarrier_wait(uint64_t* barrier_ptr, uint32_t phase) {
    uint32_t barrier_addr = static_cast<uint32_t>(__cvta_generic_to_shared(barrier_ptr));
    asm volatile(
        "{\n\t"
        ".reg .pred p;\n\t"
        "LAB_WAIT:\n\t"
        "mbarrier.try_wait.parity.shared.b64 p, [%0], %1;\n\t"
        "@!p bra LAB_WAIT;\n\t"
        "}"
        :: "r"(barrier_addr), "r"(phase) : "memory"
    );
}

// Commit TMA store group
__device__ __forceinline__ void tma_store_commit() {
    asm volatile("cp.async.bulk.commit_group;" ::: "memory");
}

// Wait for TMA store group to complete
__device__ __forceinline__ void tma_store_wait() {
    asm volatile("cp.async.bulk.wait_group 0;" ::: "memory");
}

// ==========================================================================
// TMA Gather Kernel: DRAM (mapped) -> GPU HBM
//
// Multi-warp, multi-task-per-warp design.  Each CTA has
// kTMAWarpsPerBlock warps; within each warp, the first kTMATasksPerWarp
// lanes each independently drive a TMA load→wait→store pipeline.
// This gives kTMATasksPerBlock (128) concurrent in-flight TMA
// transactions per CTA, matching the HD_comm reference implementation.
//
// Shared memory layout per CTA:
//   Data:     kTMATasksPerBlock * block_size_bytes
//   Barriers: kTMATasksPerBlock * 8  (one mbarrier per task slot)
// ==========================================================================
__global__ void tma_gather_kernel(
    const char* __restrict__ src_base,
    const long* __restrict__ indices,
    char* __restrict__ dst_base,
    int block_size_bytes,
    int total_tasks
) {
    extern __align__(1024) __shared__ char smem_buffer[];

    const int warp_id = threadIdx.x / 32;
    const int lane_id = threadIdx.x % 32;

    // Each active lane gets its own data slot and barrier in shared memory
    const int slot_id = warp_id * kTMATasksPerWarp + lane_id;
    char* my_data = smem_buffer + slot_id * block_size_bytes;
    uint64_t* my_barrier = reinterpret_cast<uint64_t*>(
        smem_buffer + kTMATasksPerBlock * block_size_bytes + slot_id * 8
    );

    // Task assignment: grid-stride over all tasks
    const int first_task = blockIdx.x * kTMATasksPerBlock + slot_id;
    const int stride = gridDim.x * kTMATasksPerBlock;
    uint32_t phase = 1;

    // Only the first kTMATasksPerWarp lanes per warp are active
    if (lane_id < kTMATasksPerWarp) {
        mbarrier_init(my_barrier, 1);
    }

    for (int i = first_task; i < total_tasks; i += stride) {
        if (lane_id < kTMATasksPerWarp) {
            const long target_idx = indices[i];
            const char* src_addr = src_base + target_idx * block_size_bytes;
            char* dst_addr = dst_base + (long)i * block_size_bytes;

            // 1. TMA Load: DRAM (mapped) -> Shared Memory
            mbarrier_expect_tx(my_barrier, block_size_bytes);
            tma_load(my_data, src_addr, block_size_bytes, my_barrier);

            // 2. Wait for Load to complete
            mbarrier_wait(my_barrier, (++phase) % 2);

            // 3. TMA Store: Shared Memory -> GPU HBM
            tma_store(dst_addr, my_data, block_size_bytes);
            tma_store_commit();
            tma_store_wait();
        }
    }
}

// ==========================================================================
// TMA Scatter Kernel: GPU HBM -> DRAM (mapped)
//
// Same multi-warp, multi-task-per-warp design as gather, but reversed:
// reads from contiguous HBM and writes to scattered DRAM locations.
// ==========================================================================
__global__ void tma_scatter_kernel(
    const char* __restrict__ src_base,
    const long* __restrict__ indices,
    char* __restrict__ dst_base,
    int block_size_bytes,
    int total_tasks
) {
    extern __align__(1024) __shared__ char smem_buffer[];

    const int warp_id = threadIdx.x / 32;
    const int lane_id = threadIdx.x % 32;

    const int slot_id = warp_id * kTMATasksPerWarp + lane_id;
    char* my_data = smem_buffer + slot_id * block_size_bytes;
    uint64_t* my_barrier = reinterpret_cast<uint64_t*>(
        smem_buffer + kTMATasksPerBlock * block_size_bytes + slot_id * 8
    );

    const int first_task = blockIdx.x * kTMATasksPerBlock + slot_id;
    const int stride = gridDim.x * kTMATasksPerBlock;
    uint32_t phase = 1;

    if (lane_id < kTMATasksPerWarp) {
        mbarrier_init(my_barrier, 1);
    }

    for (int i = first_task; i < total_tasks; i += stride) {
        if (lane_id < kTMATasksPerWarp) {
            // Source is contiguous in HBM
            const char* src_addr = src_base + (long)i * block_size_bytes;
            // Destination is scattered in DRAM
            const long target_idx = indices[i];
            char* dst_addr = dst_base + target_idx * block_size_bytes;

            // 1. TMA Load: GPU HBM -> Shared Memory
            mbarrier_expect_tx(my_barrier, block_size_bytes);
            tma_load(my_data, src_addr, block_size_bytes, my_barrier);

            // 2. Wait for Load to complete
            mbarrier_wait(my_barrier, (++phase) % 2);

            // 3. TMA Store: Shared Memory -> DRAM (mapped)
            tma_store(dst_addr, my_data, block_size_bytes);
            tma_store_commit();
            tma_store_wait();
        }
    }
}

// ==========================================================================
// int4 Zero-Copy Gather Kernel: DRAM (mapped) -> GPU HBM
//
// Each thread reads a single int4 (16 bytes) directly from DRAM via PCIe
// and writes it to HBM.  No Shared Memory staging — one LDG.E.128 + one
// STG.E.128 per thread.  This is faster than TMA for small-block random
// gather because it avoids the mbarrier + Smem round-trip overhead.
//
// Grid-stride loop so a limited number of blocks can process all tasks.
// ==========================================================================
__global__ void zerocopy_gather_int4_kernel(
    const int4* __restrict__ src_base,   // DRAM device pointer (int4-aligned)
    const long* __restrict__ indices,    // Block indices to gather
    int4* __restrict__ dst_base,         // GPU HBM destination (int4-aligned)
    int block_size_int4,                 // block_size_bytes / 16
    int total_int4_tasks                 // num_blocks * block_size_int4
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int stride = gridDim.x * blockDim.x;

    for (int i = idx; i < total_int4_tasks; i += stride) {
        int block_idx = i / block_size_int4;
        int offset    = i % block_size_int4;
        long target_id = indices[block_idx];
        dst_base[i] = src_base[target_id * block_size_int4 + offset];
    }
}

// ==========================================================================
// int4 Zero-Copy Scatter Kernel: GPU HBM -> DRAM (mapped)
//
// Reverse of gather: reads int4 from contiguous HBM blocks and writes to
// scattered DRAM locations via PCIe.
// ==========================================================================
__global__ void zerocopy_scatter_int4_kernel(
    const int4* __restrict__ src_base,   // GPU HBM source (int4-aligned)
    const long* __restrict__ indices,    // Block indices for scatter
    int4* __restrict__ dst_base,         // DRAM device pointer (int4-aligned)
    int block_size_int4,                 // block_size_bytes / 16
    int total_int4_tasks                 // num_blocks * block_size_int4
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int stride = gridDim.x * blockDim.x;

    for (int i = idx; i < total_int4_tasks; i += stride) {
        int block_idx = i / block_size_int4;
        int offset    = i % block_size_int4;
        long target_id = indices[block_idx];
        dst_base[target_id * block_size_int4 + offset] = src_base[i];
    }
}

// ==========================================================================
// Host-side Launch Wrappers
// ==========================================================================

// Get the number of SMs on the current device (cached)
static int getDeviceSMCount() {
    static int cached_sm_count = 0;
    if (cached_sm_count > 0) return cached_sm_count;

    int device = 0;
    cudaGetDevice(&device);

    int sm_count = 0;
    cudaDeviceGetAttribute(&sm_count, cudaDevAttrMultiProcessorCount, device);
    cached_sm_count = sm_count > 0 ? sm_count : 132;
    return cached_sm_count;
}

void launch_tma_gather_kernel(
    const char* src_base,
    const long* indices,
    char* dst_base,
    int block_size_bytes,
    int total_tasks,
    int max_sm_count,
    int mode   // 0=AUTO, 1=SM (int4 Zero-Copy), 2=TMA (cp.async.bulk)
) {
    if (max_sm_count <= 0) {
        max_sm_count = getDeviceSMCount();
    }

    // Determine whether to use SM (int4 Zero-Copy) path
    // AUTO now defaults to TMA (optimal for Hopper); SM is opt-in via mode=1
    bool use_sm = false;
    if (mode == 1) {
        use_sm = true;
    } else if (mode == 2) {
        use_sm = false;
    } else {
        // AUTO: default to TMA on Hopper
        use_sm = false;
    }

    if (use_sm && (block_size_bytes % 16 == 0)) {
        // SM path: int4 Zero-Copy (no Shared Memory staging)
        const int block_size_int4 = block_size_bytes / 16;
        const int total_int4_tasks = total_tasks * block_size_int4;

        static constexpr int kZCThreads = 256;
        int blocks_needed = (total_int4_tasks + kZCThreads - 1) / kZCThreads;
        int launch_blocks = std::min(blocks_needed, max_sm_count * 4);

        printf("[TMA-Gather] backend=SM(int4), blocks=%d, threads=%d, "
               "tasks=%d, block_size=%d, src=%p (align=%luB)\n",
               launch_blocks, kZCThreads, total_tasks, block_size_bytes,
               src_base, (unsigned long)((uintptr_t)src_base % 1024 == 0 ? 1024 :
                          (uintptr_t)src_base % 64 == 0 ? 64 : (uintptr_t)src_base % 16));

        zerocopy_gather_int4_kernel<<<launch_blocks, kZCThreads>>>(
            reinterpret_cast<const int4*>(src_base),
            indices,
            reinterpret_cast<int4*>(dst_base),
            block_size_int4,
            total_int4_tasks
        );
        return;
    }

    // TMA path: multi-warp, multi-task concurrent pipeline
    // Smem layout: [data: kTMATasksPerBlock * bs | barriers: kTMATasksPerBlock * 8]
    int smem_size = kTMATasksPerBlock * (block_size_bytes + 8);

    int blocks_needed = (total_tasks + kTMATasksPerBlock - 1) / kTMATasksPerBlock;
    int launch_blocks = std::min(blocks_needed, max_sm_count);
    if (launch_blocks <= 0) {
        return;
    }

    printf("[TMA-Gather] backend=TMA(cp.async.bulk), CTAs=%d, threads=%d, "
           "tasks=%d, block_size=%d, smem=%d, src=%p (align=%luB)\n",
           launch_blocks, kTMAThreadsPerBlock, total_tasks, block_size_bytes,
           smem_size, src_base,
           (unsigned long)((uintptr_t)src_base % 1024 == 0 ? 1024 :
                            (uintptr_t)src_base % 64 == 0 ? 64 : (uintptr_t)src_base % 16));

    cudaFuncSetAttribute(tma_gather_kernel,
                         cudaFuncAttributeMaxDynamicSharedMemorySize, smem_size);

    tma_gather_kernel<<<launch_blocks, kTMAThreadsPerBlock, smem_size>>>(
        src_base, indices, dst_base, block_size_bytes, total_tasks
    );
}

void launch_tma_scatter_kernel(
    const char* src_base,
    const long* indices,
    char* dst_base,
    int block_size_bytes,
    int total_tasks,
    int max_sm_count,
    int mode   // 0=AUTO, 1=SM (int4 Zero-Copy), 2=TMA (cp.async.bulk)
) {
    if (max_sm_count <= 0) {
        max_sm_count = getDeviceSMCount();
    }

    // AUTO now defaults to TMA; SM is opt-in via mode=1
    bool use_sm = false;
    if (mode == 1) {
        use_sm = true;
    } else if (mode == 2) {
        use_sm = false;
    } else {
        use_sm = false;
    }

    if (use_sm && (block_size_bytes % 16 == 0)) {
        const int block_size_int4 = block_size_bytes / 16;
        const int total_int4_tasks = total_tasks * block_size_int4;

        static constexpr int kZCThreads = 256;
        int blocks_needed = (total_int4_tasks + kZCThreads - 1) / kZCThreads;
        int launch_blocks = std::min(blocks_needed, max_sm_count * 4);

        printf("[TMA-Scatter] backend=SM(int4), blocks=%d, threads=%d, "
               "tasks=%d, block_size=%d, dst=%p (align=%luB)\n",
               launch_blocks, kZCThreads, total_tasks, block_size_bytes,
               dst_base, (unsigned long)((uintptr_t)dst_base % 1024 == 0 ? 1024 :
                          (uintptr_t)dst_base % 64 == 0 ? 64 : (uintptr_t)dst_base % 16));

        zerocopy_scatter_int4_kernel<<<launch_blocks, kZCThreads>>>(
            reinterpret_cast<const int4*>(src_base),
            indices,
            reinterpret_cast<int4*>(dst_base),
            block_size_int4,
            total_int4_tasks
        );
        return;
    }

    // TMA path: multi-warp, multi-task concurrent pipeline
    int smem_size = kTMATasksPerBlock * (block_size_bytes + 8);

    int blocks_needed = (total_tasks + kTMATasksPerBlock - 1) / kTMATasksPerBlock;
    int launch_blocks = std::min(blocks_needed, max_sm_count);
    if (launch_blocks <= 0) {
        return;
    }

    printf("[TMA-Scatter] backend=TMA(cp.async.bulk), CTAs=%d, threads=%d, "
           "tasks=%d, block_size=%d, smem=%d, dst=%p (align=%luB)\n",
           launch_blocks, kTMAThreadsPerBlock, total_tasks, block_size_bytes,
           smem_size, dst_base,
           (unsigned long)((uintptr_t)dst_base % 1024 == 0 ? 1024 :
                            (uintptr_t)dst_base % 64 == 0 ? 64 : (uintptr_t)dst_base % 16));

    cudaFuncSetAttribute(tma_scatter_kernel,
                         cudaFuncAttributeMaxDynamicSharedMemorySize, smem_size);

    tma_scatter_kernel<<<launch_blocks, kTMAThreadsPerBlock, smem_size>>>(
        src_base, indices, dst_base, block_size_bytes, total_tasks
    );
}

}  // namespace mpcomm
