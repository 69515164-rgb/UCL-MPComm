#!/usr/bin/env python3
# Copyright 2024 KVCache.AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""MPComm TMA Interface Test Script

Tests the TMA (Tensor Memory Accelerator) Gather/Scatter functionality
through MPComm's Python bindings. This verifies the full chain:
  mapDRAMtoGPU -> tmaGather/tmaScatter -> unmapDRAMfromGPU

Requirements:
  - NVIDIA Hopper architecture GPU (H100/H800/H20, sm_90+)
  - mpcomm built with USE_CUDA=ON
  - Sufficient CPU DRAM for pinned memory

Usage:
    # Basic correctness test (default parameters)
    python test_tma.py

    # Custom block count and size
    python test_tma.py --num-blocks 2048 --block-size 2048

    # With performance benchmark
    python test_tma.py --benchmark

    # Specify GPU device
    python test_tma.py --gpu 0

    # Large-scale test
    python test_tma.py --num-blocks 4096 --pool-blocks 1048576 --benchmark
"""
import argparse
import os
import sys
import time

import torch

# ---------------------------------------------------------------------------
# Auto-detect mpcomm install path so the script works without PYTHONPATH.
# The typical install layout is:
#   trmt-mpcomm/mpcomm-install/lib/python/mpcomm/__init__.py
#   trmt-mpcomm/mpcomm-install/lib/python/mpcomm/mpcomm.cpython-*.so
# We also check the build/ directory for in-tree builds.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, os.pardir))

_CANDIDATE_PATHS = [
    os.path.join(_PROJECT_ROOT, "mpcomm-install", "lib", "python"),
    os.path.join(_PROJECT_ROOT, "build"),
]

for _p in _CANDIDATE_PATHS:
    if os.path.isdir(os.path.join(_p, "mpcomm")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
        break

try:
    import mpcomm
except ImportError:
    print("Error: mpcomm module not found.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please build it first:", file=sys.stderr)
    print("  cd trmt-mpcomm && sh build.sh", file=sys.stderr)
    print("", file=sys.stderr)
    print("Or set PYTHONPATH manually:", file=sys.stderr)
    print("  export PYTHONPATH=/path/to/mpcomm-install/lib/python:$PYTHONPATH", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Searched paths: {_CANDIDATE_PATHS}", file=sys.stderr)
    sys.exit(1)


def test_map_dram_to_gpu(comm):
    """测试 DRAM-GPU 映射的基本功能"""
    print(f"\n{'='*60}")
    print("DRAM-GPU 映射基本测试")
    print(f"{'='*60}")

    buf_size = 4096 * 16  # 64 KB
    cpu_buf = torch.empty(buf_size, dtype=torch.uint8)
    cpu_buf.fill_(42)
    addr = cpu_buf.data_ptr()

    # 测试映射
    dev_ptr = comm.map_dram_to_gpu(addr, buf_size)
    if dev_ptr == 0:
        print("  ❌ map_dram_to_gpu 返回 0 (失败)")
        return False
    print(f"  映射: CPU 0x{addr:x} -> GPU 0x{dev_ptr:x} ({buf_size} bytes)")

    # 测试解除映射
    ret = comm.unmap_dram_from_gpu(addr)
    if ret != 0:
        print(f"  ❌ unmap_dram_from_gpu 返回 {ret}")
        return False
    print(f"  解除映射: ret={ret}")

    # 测试重复映射
    dev_ptr2 = comm.map_dram_to_gpu(addr, buf_size)
    if dev_ptr2 == 0:
        print("  ❌ 重复映射失败")
        return False
    comm.unmap_dram_from_gpu(addr)

    # 测试无效参数
    zero_ptr = comm.map_dram_to_gpu(0, buf_size)
    if zero_ptr != 0:
        print("  ❌ 传入 addr=0 时应返回 0")
        return False

    zero_len = comm.map_dram_to_gpu(addr, 0)
    if zero_len != 0:
        print("  ❌ 传入 length=0 时应返回 0")
        return False

    print(f"  ✅ DRAM-GPU 映射测试通过")
    return True


def test_tma_gather(comm, num_blocks, block_size, pool_blocks, benchmark=False):
    """测试 TMA Gather: DRAM -> GPU HBM"""
    print(f"\n{'='*60}")
    print(f"TMA Gather 测试: {num_blocks} blocks x {block_size} bytes")
    print(f"{'='*60}")

    device = torch.device("cuda:0")

    # 1. 在 CPU 上分配 DRAM 内存池
    cpu_pool = torch.empty(pool_blocks * block_size, dtype=torch.uint8)
    # 填充已知模式: 每个 block 用 block_index % 256 填充
    for i in range(pool_blocks):
        start = i * block_size
        cpu_pool[start:start + block_size] = i % 256

    pool_addr = cpu_pool.data_ptr()
    print(f"  CPU 内存池: {pool_blocks} blocks ({pool_blocks * block_size / 1024 / 1024:.1f} MB), "
          f"addr=0x{pool_addr:x}")

    # 2. 将 DRAM 映射到 GPU 地址空间
    dram_dev_ptr = comm.map_dram_to_gpu(pool_addr, pool_blocks * block_size)
    if dram_dev_ptr == 0:
        print("  ❌ map_dram_to_gpu 失败!")
        return False
    print(f"  DRAM 映射成功: GPU device ptr = 0x{dram_dev_ptr:x}")

    # 3. 准备 indices (在 GPU 上)
    indices_cpu = torch.randint(0, pool_blocks, (num_blocks,), dtype=torch.long)
    indices_gpu = indices_cpu.to(device)

    # 4. 分配 GPU 输出 buffer
    gpu_output = torch.zeros(num_blocks * block_size, dtype=torch.uint8, device=device)

    # 5. 调用 tmaGather
    ret = comm.tma_gather(
        dram_dev_ptr,
        indices_gpu.data_ptr(),
        gpu_output.data_ptr(),
        num_blocks,
        block_size,
        0  # max_sm_count=0 -> auto
    )
    torch.cuda.synchronize()

    if ret != 0:
        print(f"  ❌ tma_gather 返回错误: {ret}")
        comm.unmap_dram_from_gpu(pool_addr)
        return False
    print(f"  tma_gather 调用成功 (ret={ret})")

    # 6. 正确性验证
    expected = torch.empty(num_blocks * block_size, dtype=torch.uint8)
    for i in range(num_blocks):
        idx = indices_cpu[i].item()
        src_start = idx * block_size
        dst_start = i * block_size
        expected[dst_start:dst_start + block_size] = cpu_pool[src_start:src_start + block_size]

    actual = gpu_output.cpu()
    diff = (actual.float() - expected.float()).abs().sum().item()

    if diff == 0:
        print(f"  ✅ 数据验证通过: {num_blocks} blocks 全部正确")
    else:
        mismatches = 0
        for i in range(num_blocks):
            s = i * block_size
            e = s + block_size
            if not torch.equal(actual[s:e], expected[s:e]):
                mismatches += 1
                if mismatches <= 3:
                    idx = indices_cpu[i].item()
                    print(f"  ❌ Block {i} (index={idx}) 不匹配:")
                    print(f"     expected[:8] = {expected[s:s+8].tolist()}")
                    print(f"     actual[:8]   = {actual[s:s+8].tolist()}")
        print(f"  ❌ 共 {mismatches}/{num_blocks} blocks 不匹配")
        comm.unmap_dram_from_gpu(pool_addr)
        return False

    # 7. 性能基准测试
    if benchmark:
        warmup = 10
        iters = 100
        for _ in range(warmup):
            comm.tma_gather(dram_dev_ptr, indices_gpu.data_ptr(),
                            gpu_output.data_ptr(), num_blocks, block_size, 0)
        torch.cuda.synchronize()

        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)
        start_event.record()
        for _ in range(iters):
            comm.tma_gather(dram_dev_ptr, indices_gpu.data_ptr(),
                            gpu_output.data_ptr(), num_blocks, block_size, 0)
        end_event.record()
        torch.cuda.synchronize()

        avg_ms = start_event.elapsed_time(end_event) / iters
        data_mb = (num_blocks * block_size) / (1024 * 1024)
        bw_gbs = (num_blocks * block_size) / (avg_ms / 1000) / 1e9
        print(f"  📊 TMA Gather 性能: {avg_ms:.4f} ms/iter, "
              f"{data_mb:.2f} MB, {bw_gbs:.2f} GB/s")

        # 与 PyTorch baseline 对比
        start_event.record()
        for _ in range(iters):
            _ = cpu_pool.view(pool_blocks, block_size)[indices_cpu].to(device)
        end_event.record()
        torch.cuda.synchronize()

        baseline_ms = start_event.elapsed_time(end_event) / iters
        baseline_bw = (num_blocks * block_size) / (baseline_ms / 1000) / 1e9
        speedup = baseline_ms / avg_ms if avg_ms > 0 else float('inf')
        print(f"  📊 PyTorch Baseline: {baseline_ms:.4f} ms/iter, {baseline_bw:.2f} GB/s")
        print(f"  📊 TMA 加速比: {speedup:.2f}x")

    comm.unmap_dram_from_gpu(pool_addr)
    return True


def test_tma_scatter(comm, num_blocks, block_size, pool_blocks, benchmark=False):
    """测试 TMA Scatter: GPU HBM -> DRAM"""
    print(f"\n{'='*60}")
    print(f"TMA Scatter 测试: {num_blocks} blocks x {block_size} bytes")
    print(f"{'='*60}")

    device = torch.device("cuda:0")

    # 1. 在 CPU 上分配 DRAM 目标内存池 (清零)
    cpu_pool = torch.zeros(pool_blocks * block_size, dtype=torch.uint8)
    pool_addr = cpu_pool.data_ptr()
    print(f"  CPU 目标池: {pool_blocks} blocks ({pool_blocks * block_size / 1024 / 1024:.1f} MB), "
          f"addr=0x{pool_addr:x}")

    # 2. 映射 DRAM 到 GPU
    dram_dev_ptr = comm.map_dram_to_gpu(pool_addr, pool_blocks * block_size)
    if dram_dev_ptr == 0:
        print("  ❌ map_dram_to_gpu 失败!")
        return False
    print(f"  DRAM 映射成功: GPU device ptr = 0x{dram_dev_ptr:x}")

    # 3. 在 GPU 上准备源数据
    gpu_src = torch.empty(num_blocks * block_size, dtype=torch.uint8, device=device)
    for i in range(num_blocks):
        s = i * block_size
        gpu_src[s:s + block_size] = (i + 42) % 256

    # 4. 准备 indices (在 GPU 上) - 使用不重复的散列写入位置
    indices_cpu = torch.randperm(pool_blocks)[:num_blocks].to(torch.long)
    indices_gpu = indices_cpu.to(device)

    # 5. 调用 tmaScatter
    ret = comm.tma_scatter(
        gpu_src.data_ptr(),
        indices_gpu.data_ptr(),
        dram_dev_ptr,
        num_blocks,
        block_size,
        0
    )
    torch.cuda.synchronize()

    if ret != 0:
        print(f"  ❌ tma_scatter 返回错误: {ret}")
        comm.unmap_dram_from_gpu(pool_addr)
        return False
    print(f"  tma_scatter 调用成功 (ret={ret})")

    # 6. 正确性验证
    gpu_src_cpu = gpu_src.cpu()
    errors = 0
    for i in range(num_blocks):
        idx = indices_cpu[i].item()
        src_start = i * block_size
        dst_start = idx * block_size
        expected_block = gpu_src_cpu[src_start:src_start + block_size]
        actual_block = cpu_pool[dst_start:dst_start + block_size]
        if not torch.equal(expected_block, actual_block):
            errors += 1
            if errors <= 3:
                print(f"  ❌ Block {i} -> pool[{idx}] 不匹配:")
                print(f"     expected[:8] = {expected_block[:8].tolist()}")
                print(f"     actual[:8]   = {actual_block[:8].tolist()}")

    if errors == 0:
        print(f"  ✅ 数据验证通过: {num_blocks} blocks 全部正确")
    else:
        print(f"  ❌ 共 {errors}/{num_blocks} blocks 不匹配")
        comm.unmap_dram_from_gpu(pool_addr)
        return False

    # 7. 性能基准测试
    if benchmark:
        # 重新清零内存池
        cpu_pool.zero_()

        warmup = 10
        iters = 100
        for _ in range(warmup):
            comm.tma_scatter(gpu_src.data_ptr(), indices_gpu.data_ptr(),
                             dram_dev_ptr, num_blocks, block_size, 0)
        torch.cuda.synchronize()

        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)
        start_event.record()
        for _ in range(iters):
            comm.tma_scatter(gpu_src.data_ptr(), indices_gpu.data_ptr(),
                             dram_dev_ptr, num_blocks, block_size, 0)
        end_event.record()
        torch.cuda.synchronize()

        avg_ms = start_event.elapsed_time(end_event) / iters
        data_mb = (num_blocks * block_size) / (1024 * 1024)
        bw_gbs = (num_blocks * block_size) / (avg_ms / 1000) / 1e9
        print(f"  📊 TMA Scatter 性能: {avg_ms:.4f} ms/iter, "
              f"{data_mb:.2f} MB, {bw_gbs:.2f} GB/s")

    comm.unmap_dram_from_gpu(pool_addr)
    return True


def test_tma_roundtrip(comm, num_blocks, block_size, pool_blocks):
    """测试 TMA 往返: Scatter 写入 DRAM, 再 Gather 读回, 验证一致性"""
    print(f"\n{'='*60}")
    print(f"TMA 往返测试 (Scatter -> Gather): {num_blocks} blocks x {block_size} bytes")
    print(f"{'='*60}")

    device = torch.device("cuda:0")

    # 1. 分配 CPU 内存池 (清零)
    cpu_pool = torch.zeros(pool_blocks * block_size, dtype=torch.uint8)
    pool_addr = cpu_pool.data_ptr()
    dram_dev_ptr = comm.map_dram_to_gpu(pool_addr, pool_blocks * block_size)
    if dram_dev_ptr == 0:
        print("  ❌ map_dram_to_gpu 失败!")
        return False

    # 2. GPU 上准备随机数据
    gpu_original = torch.randint(0, 256, (num_blocks * block_size,),
                                  dtype=torch.uint8, device=device)

    # 3. Scatter: GPU -> DRAM
    indices_cpu = torch.randperm(pool_blocks)[:num_blocks].to(torch.long)
    indices_gpu = indices_cpu.to(device)

    ret = comm.tma_scatter(gpu_original.data_ptr(), indices_gpu.data_ptr(),
                            dram_dev_ptr, num_blocks, block_size, 0)
    torch.cuda.synchronize()
    if ret != 0:
        print(f"  ❌ tma_scatter 失败: {ret}")
        comm.unmap_dram_from_gpu(pool_addr)
        return False
    print(f"  Scatter 完成 (GPU -> DRAM)")

    # 4. Gather: DRAM -> GPU (用相同 indices)
    gpu_readback = torch.zeros(num_blocks * block_size, dtype=torch.uint8, device=device)
    ret = comm.tma_gather(dram_dev_ptr, indices_gpu.data_ptr(),
                           gpu_readback.data_ptr(), num_blocks, block_size, 0)
    torch.cuda.synchronize()
    if ret != 0:
        print(f"  ❌ tma_gather 失败: {ret}")
        comm.unmap_dram_from_gpu(pool_addr)
        return False
    print(f"  Gather 完成 (DRAM -> GPU)")

    # 5. 验证: original == readback
    diff = (gpu_original.float() - gpu_readback.float()).abs().sum().item()
    if diff == 0:
        print(f"  ✅ 往返验证通过: Scatter -> Gather 数据完全一致")
    else:
        original_cpu = gpu_original.cpu()
        readback_cpu = gpu_readback.cpu()
        mismatches = 0
        for i in range(num_blocks):
            s = i * block_size
            e = s + block_size
            if not torch.equal(original_cpu[s:e], readback_cpu[s:e]):
                mismatches += 1
                if mismatches <= 3:
                    idx = indices_cpu[i].item()
                    print(f"  ❌ Block {i} (index={idx}) 不匹配:")
                    print(f"     original[:8] = {original_cpu[s:s+8].tolist()}")
                    print(f"     readback[:8] = {readback_cpu[s:s+8].tolist()}")
        print(f"  ❌ 往返验证失败: {mismatches}/{num_blocks} blocks 不匹配")
        comm.unmap_dram_from_gpu(pool_addr)
        return False

    comm.unmap_dram_from_gpu(pool_addr)
    return True


def test_tma_alignment(comm):
    """测试 TMA 对齐要求"""
    print(f"\n{'='*60}")
    print("TMA 对齐测试")
    print(f"{'='*60}")

    device = torch.device("cuda:0")

    # 测试多种 block_size (都必须是 16 的倍数)
    test_sizes = [16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
    num_blocks = 64
    pool_blocks = 256

    all_pass = True
    for block_size in test_sizes:
        cpu_pool = torch.empty(pool_blocks * block_size, dtype=torch.uint8)
        for i in range(pool_blocks):
            cpu_pool[i * block_size:(i + 1) * block_size] = i % 256

        pool_addr = cpu_pool.data_ptr()
        dram_dev_ptr = comm.map_dram_to_gpu(pool_addr, pool_blocks * block_size)
        if dram_dev_ptr == 0:
            print(f"  ❌ block_size={block_size}: map_dram_to_gpu 失败")
            all_pass = False
            continue

        indices_cpu = torch.randint(0, pool_blocks, (num_blocks,), dtype=torch.long)
        indices_gpu = indices_cpu.to(device)
        gpu_output = torch.zeros(num_blocks * block_size, dtype=torch.uint8, device=device)

        ret = comm.tma_gather(dram_dev_ptr, indices_gpu.data_ptr(),
                               gpu_output.data_ptr(), num_blocks, block_size, 0)
        torch.cuda.synchronize()

        if ret != 0:
            print(f"  ❌ block_size={block_size}: tma_gather 返回 {ret}")
            comm.unmap_dram_from_gpu(pool_addr)
            all_pass = False
            continue

        # 验证
        expected = torch.empty(num_blocks * block_size, dtype=torch.uint8)
        for i in range(num_blocks):
            idx = indices_cpu[i].item()
            expected[i * block_size:(i + 1) * block_size] = \
                cpu_pool[idx * block_size:(idx + 1) * block_size]

        actual = gpu_output.cpu()
        if torch.equal(actual, expected):
            print(f"  ✅ block_size={block_size:5d}: 通过")
        else:
            print(f"  ❌ block_size={block_size:5d}: 数据不匹配")
            all_pass = False

        comm.unmap_dram_from_gpu(pool_addr)

    if all_pass:
        print(f"  ✅ 所有对齐测试通过")
    return all_pass


def main():
    parser = argparse.ArgumentParser(
        description="MPComm TMA 接口测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python test_tma.py                                    # 基本正确性测试
    python test_tma.py --benchmark                        # 带性能基准测试
    python test_tma.py --num-blocks 2048 --block-size 2048  # 自定义参数
    python test_tma.py --pool-blocks 1048576 --benchmark  # 大规模测试
"""
    )
    parser.add_argument("--num-blocks", type=int, default=1024,
                        help="每次 gather/scatter 的 block 数 (default: 1024)")
    parser.add_argument("--block-size", type=int, default=1024,
                        help="每个 block 大小(字节), 必须 16 字节对齐 (default: 1024)")
    parser.add_argument("--pool-blocks", type=int, default=8192,
                        help="DRAM 内存池总 block 数 (default: 8192)")
    parser.add_argument("--benchmark", action="store_true",
                        help="运行性能基准测试")
    parser.add_argument("--gpu", type=int, default=0,
                        help="CUDA 设备编号 (default: 0)")
    args = parser.parse_args()

    # 参数检查
    if args.block_size % 16 != 0:
        print(f"Error: block_size ({args.block_size}) 必须是 16 的倍数")
        sys.exit(1)
    if args.num_blocks > args.pool_blocks:
        print(f"Error: num_blocks ({args.num_blocks}) 不能超过 pool_blocks ({args.pool_blocks})")
        sys.exit(1)

    if not torch.cuda.is_available():
        print("Error: CUDA 不可用")
        sys.exit(1)

    torch.cuda.set_device(args.gpu)
    props = torch.cuda.get_device_properties(args.gpu)
    print(f"{'='*60}")
    print(f"MPComm TMA 接口测试")
    print(f"{'='*60}")
    print(f"GPU: {props.name} (SMs: {props.multi_processor_count}, "
          f"Compute: {props.major}.{props.minor})")
    print(f"参数: num_blocks={args.num_blocks}, block_size={args.block_size}, "
          f"pool_blocks={args.pool_blocks}")

    if props.major < 9:
        print(f"\n⚠️  警告: TMA 需要 Hopper 架构 (sm_90+), 当前为 sm_{props.major}{props.minor}")
        print(f"   TMA 内核可能无法执行!")

    # 初始化 MPComm (本地模式，无需 RDMA 连接)
    comm = mpcomm.MPComm()
    ret = comm.init(f"tma-test:{args.gpu}", "", 0)
    if ret != 0:
        print(f"Error: MPComm init 失败: {ret}")
        sys.exit(1)
    print(f"MPComm 初始化成功")

    results = []

    # 测试 0: DRAM-GPU 映射基本功能
    ok = test_map_dram_to_gpu(comm)
    results.append(("DRAM-GPU Mapping", ok))

    # 测试 1: TMA Gather
    ok = test_tma_gather(comm, args.num_blocks, args.block_size,
                         args.pool_blocks, args.benchmark)
    results.append(("TMA Gather", ok))

    # 测试 2: TMA Scatter
    ok = test_tma_scatter(comm, args.num_blocks, args.block_size,
                          args.pool_blocks, args.benchmark)
    results.append(("TMA Scatter", ok))

    # 测试 3: 往返测试 (Scatter -> Gather 一致性)
    ok = test_tma_roundtrip(comm, args.num_blocks, args.block_size,
                             args.pool_blocks)
    results.append(("TMA Roundtrip", ok))

    # 测试 4: 对齐测试 (多种 block_size)
    ok = test_tma_alignment(comm)
    results.append(("TMA Alignment", ok))

    # 汇总
    print(f"\n{'='*60}")
    print("测试结果汇总:")
    print(f"{'='*60}")
    all_pass = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    comm.shutdown()

    if all_pass:
        print(f"\n🎉 全部测试通过!")
    else:
        print(f"\n💥 存在失败的测试")
        sys.exit(1)


if __name__ == "__main__":
    main()
