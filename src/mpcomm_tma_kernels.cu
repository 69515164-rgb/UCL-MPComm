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
// Based on HD_comm/bench_H2D_TMA/kv_gather_tma.cu
// ==========================================================================

#include <cuda.h>
#include <cuda_runtime.h>
#include <cstdint>
#include <cstdio>
#include <algorithm>

namespace mpcomm {

// ==========================================================================
// Configuration Constants
// ==========================================================================

static constexpr int kWarpsPerBlock = 32;
static constexpr int kTasksPerWarp = 4;
static constexpr int kThreadsPerBlock = kWarpsPerBlock * 32;

// L2 Cache eviction hints for TMA operations
// EvictFirst: data will be evicted from L2 first (good for streaming/one-shot access)
static constexpr uint64_t kL2EvictFirst = 0x12f0000000000000ULL;

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

// Wait for mbarrier with parity phase
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
// Each warp processes kTasksPerWarp tasks simultaneously.
// Only the first kTasksPerWarp lanes of each warp are active.
// Flow per task:
//   1. TMA Load: DRAM[indices[i]] -> Shared Memory
//   2. Wait for load completion (mbarrier)
//   3. TMA Store: Shared Memory -> HBM[i]
//   4. Wait for store completion
// ==========================================================================
__global__ void tma_gather_kernel(
    const char* __restrict__ src_base,      // DRAM device pointer (mapped)
    const long* __restrict__ indices,        // Block indices to gather
    char* __restrict__ dst_base,             // GPU HBM destination
    int block_size_bytes,                    // Size of each block
    int total_tasks                          // Total number of blocks to gather
) {
    // Shared memory layout:
    //   [0 .. warps*tasks*block_size) : data blocks
    //   [warps*tasks*block_size .. +warps*tasks*8) : mbarrier array
    extern __align__(1024) __shared__ char smem_buffer[];

    const int warp_id = threadIdx.x / 32;
    const int lane_id = threadIdx.x % 32;

    // Each warp's task slot in shared memory
    char* my_data_block = smem_buffer +
        (warp_id * kTasksPerWarp + lane_id) * block_size_bytes;
    uint64_t* my_barrier_ptr = reinterpret_cast<uint64_t*>(
        smem_buffer + kWarpsPerBlock * kTasksPerWarp * block_size_bytes +
        (warp_id * kTasksPerWarp + lane_id) * 8
    );

    // Task ID: each block processes warps_per_block * tasks_per_warp tasks
    int first_task_id = blockIdx.x * kWarpsPerBlock * kTasksPerWarp +
                        warp_id * kTasksPerWarp + lane_id;
    int stride = gridDim.x * kWarpsPerBlock * kTasksPerWarp;
    uint32_t phase_id = 1;

    // Initialize mbarrier (only active lanes)
    if (lane_id < kTasksPerWarp) {
        mbarrier_init(my_barrier_ptr, 1);
    }

    for (int i = first_task_id; i < total_tasks; i += stride) {
        if (lane_id < kTasksPerWarp) {
            long target_idx = indices[i];
            const char* src_addr = src_base + target_idx * block_size_bytes;
            char* dst_addr = dst_base + i * block_size_bytes;

            // Step 1: TMA Load (DRAM -> Shared Memory)
            mbarrier_expect_tx(my_barrier_ptr, block_size_bytes);
            tma_load(my_data_block, src_addr, block_size_bytes, my_barrier_ptr);

            // Step 2: Wait for load completion
            mbarrier_wait(my_barrier_ptr, (++phase_id) % 2);

            // Step 3: TMA Store (Shared Memory -> GPU HBM)
            tma_store(dst_addr, my_data_block, block_size_bytes);
            tma_store_commit();
            tma_store_wait();
        }
    }
}

// ==========================================================================
// TMA Scatter Kernel: GPU HBM -> DRAM (mapped)
//
// Reverse of gather: reads from contiguous HBM blocks and writes to
// scattered DRAM locations through the mapped device pointer.
// ==========================================================================
__global__ void tma_scatter_kernel(
    const char* __restrict__ src_base,      // GPU HBM source
    const long* __restrict__ indices,        // Block indices for scatter
    char* __restrict__ dst_base,             // DRAM device pointer (mapped)
    int block_size_bytes,                    // Size of each block
    int total_tasks                          // Total number of blocks to scatter
) {
    extern __align__(1024) __shared__ char smem_buffer[];

    const int warp_id = threadIdx.x / 32;
    const int lane_id = threadIdx.x % 32;

    char* my_data_block = smem_buffer +
        (warp_id * kTasksPerWarp + lane_id) * block_size_bytes;
    uint64_t* my_barrier_ptr = reinterpret_cast<uint64_t*>(
        smem_buffer + kWarpsPerBlock * kTasksPerWarp * block_size_bytes +
        (warp_id * kTasksPerWarp + lane_id) * 8
    );

    int first_task_id = blockIdx.x * kWarpsPerBlock * kTasksPerWarp +
                        warp_id * kTasksPerWarp + lane_id;
    int stride = gridDim.x * kWarpsPerBlock * kTasksPerWarp;
    uint32_t phase_id = 1;

    if (lane_id < kTasksPerWarp) {
        mbarrier_init(my_barrier_ptr, 1);
    }

    for (int i = first_task_id; i < total_tasks; i += stride) {
        if (lane_id < kTasksPerWarp) {
            long target_idx = indices[i];
            const char* src_addr = src_base + i * block_size_bytes;
            char* dst_addr = dst_base + target_idx * block_size_bytes;

            // Step 1: TMA Load (GPU HBM -> Shared Memory)
            mbarrier_expect_tx(my_barrier_ptr, block_size_bytes);
            tma_load(my_data_block, src_addr, block_size_bytes, my_barrier_ptr);

            // Step 2: Wait for load completion
            mbarrier_wait(my_barrier_ptr, (++phase_id) % 2);

            // Step 3: TMA Store (Shared Memory -> DRAM mapped)
            tma_store(dst_addr, my_data_block, block_size_bytes);
            tma_store_commit();
            tma_store_wait();
        }
    }
}

// ==========================================================================
// Host-side Launch Wrappers
// ==========================================================================

// Get the number of SMs on the current device
static int getDeviceSMCount() {
    int device = 0;
    cudaGetDevice(&device);

    int sm_count = 0;
    cudaDeviceGetAttribute(&sm_count, cudaDevAttrMultiProcessorCount, device);
    return sm_count > 0 ? sm_count : 132;  // Default to H100's 132 SMs
}

void launch_tma_gather_kernel(
    const char* src_base,
    const long* indices,
    char* dst_base,
    int block_size_bytes,
    int total_tasks,
    int max_sm_count
) {
    // Calculate shared memory size:
    //   Data: warps_per_block * tasks_per_warp * block_size_bytes
    //   Barriers: warps_per_block * tasks_per_warp * 8 bytes
    int smem_size = kWarpsPerBlock * kTasksPerWarp * (block_size_bytes + 8);

    // Calculate grid dimensions
    const int tasks_per_block = kWarpsPerBlock * kTasksPerWarp;
    const int blocks_needed = (total_tasks + tasks_per_block - 1) / tasks_per_block;

    if (max_sm_count <= 0) {
        max_sm_count = getDeviceSMCount();
    }
    const int launch_blocks = std::min(blocks_needed, max_sm_count);

    // Set max dynamic shared memory
    cudaFuncSetAttribute(tma_gather_kernel,
                         cudaFuncAttributeMaxDynamicSharedMemorySize, smem_size);

    tma_gather_kernel<<<launch_blocks, kThreadsPerBlock, smem_size>>>(
        src_base, indices, dst_base, block_size_bytes, total_tasks
    );
}

void launch_tma_scatter_kernel(
    const char* src_base,
    const long* indices,
    char* dst_base,
    int block_size_bytes,
    int total_tasks,
    int max_sm_count
) {
    int smem_size = kWarpsPerBlock * kTasksPerWarp * (block_size_bytes + 8);

    const int tasks_per_block = kWarpsPerBlock * kTasksPerWarp;
    const int blocks_needed = (total_tasks + tasks_per_block - 1) / tasks_per_block;

    if (max_sm_count <= 0) {
        max_sm_count = getDeviceSMCount();
    }
    const int launch_blocks = std::min(blocks_needed, max_sm_count);

    cudaFuncSetAttribute(tma_scatter_kernel,
                         cudaFuncAttributeMaxDynamicSharedMemorySize, smem_size);

    tma_scatter_kernel<<<launch_blocks, kThreadsPerBlock, smem_size>>>(
        src_base, indices, dst_base, block_size_bytes, total_tasks
    );
}

}  // namespace mpcomm
