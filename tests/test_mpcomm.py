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

"""
MPComm Test Script

Tests mp_replicate (scatter/gather) functionality using MPComm.
This script runs on the initiator host and performs RDMA operations
to one or more target hosts.

Usage:
    # Run scatter test (auto-query buffer info from target)
    python test_mpcomm.py --mode scatter --targets target1:192.168.1.100:12345

    # Run gather test
    python test_mpcomm.py --mode gather --targets target1:192.168.1.100:12345
    
    # Run async scatter test
    python test_mpcomm.py --mode scatter --async --targets target1:192.168.1.100:12345
    
    # Multi-NUMA test (2 NUMA nodes, each with separate buffer)
    python test_mpcomm.py --mode scatter --async --num-numas 2 --targets target1:192.168.1.100:12345
    
    # Explicit buffer info (legacy mode)
    python test_mpcomm.py --mode scatter --targets target1:192.168.1.100:12345:0x7f1234:12345678

Environment variables:
    MPCOMM_HOST_ID: Local host identifier
    MPCOMM_DEVICE: RDMA device name
    MPCOMM_TARGETS: Comma-separated list of targets (host_id:tcp_port:remote_addr:rkey)
"""

import argparse
import ipaddress
import os
import random
import socket
import sys
import time
from dataclasses import dataclass
from typing import List, Optional
import concurrent.futures

import torch

# Import mpcomm module (built from C++)
try:
    import mpcomm
except ImportError:
    print("Error: mpcomm module not found. Please build it first:", file=sys.stderr)
    print("  cd mpcomm && mkdir build && cd build", file=sys.stderr)
    print("  cmake .. -DBUILD_MPCOMM_PYTHON=ON && make", file=sys.stderr)
    sys.exit(1)


DEFAULT_MIN_CHUNK_SIZE = 32 * 1024   # 32 KB
DEFAULT_MAX_CHUNK_SIZE = 128 * 1024  # 128 KB
PATTERN_PREVIEW_BYTES = 16


def _build_ipv4_pattern(ip_bytes: List[int], total_length: int) -> bytes:
    """Build a repeating pattern based on IPv4 address bytes."""
    if total_length <= 0:
        return b""
    pattern = bytearray(total_length)
    chunk = ip_bytes or [0, 0, 0, 0]
    for idx in range(total_length):
        pattern[idx] = chunk[idx % 4]
    return bytes(pattern)


def _resolve_ipv4_bytes(host: str) -> List[int]:
    """Resolve hostname to IPv4 bytes."""
    host_only = host.split(":", 1)[0]
    try:
        ip_obj = ipaddress.ip_address(socket.gethostbyname(host_only))
        return list(ip_obj.packed)
    except OSError:
        print(f"Failed to resolve host {host_only}, using zeros", file=sys.stderr)
        return [0, 0, 0, 0]


def _preview_hex(payload: bytes, limit: int = PATTERN_PREVIEW_BYTES) -> str:
    """Preview bytes as space-separated decimal values."""
    if not payload:
        return "<empty>"
    preview = payload[:limit]
    return " ".join(str(byte) for byte in preview)


def _format_bytes(num_bytes: int) -> str:
    """Format bytes with human-readable units (network convention, base 1000)."""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    idx = 0
    while value >= 1000 and idx < len(units) - 1:
        value /= 1000
        idx += 1
    return f"{value:.2f} {units[idx]}"


def _format_bandwidth(bytes_per_second: float) -> str:
    """Format bandwidth in GB/s (network convention, base 1000)."""
    if bytes_per_second <= 0:
        return "0.00 GB/s"
    gb_per_sec = bytes_per_second / (1000 ** 3)
    return f"{gb_per_sec:.2f} GB/s"


@dataclass
class TargetInfo:
    """Information about a remote target."""
    host_id: str
    tcp_addr: str
    tcp_port: int
    remote_addr: int = 0  # Can be queried from remote (for single-buffer mode)
    rkeys: List[int] = None  # Can be queried from remote
    # Multi-NUMA buffer support: list of (addr, numa_node) tuples
    remote_buffers: List[dict] = None  # [{'addr': int, 'length': int, 'numa_node': int, 'rkeys': [int...]}, ...]

    def __post_init__(self):
        if self.rkeys is None:
            self.rkeys = []
        if self.remote_buffers is None:
            self.remote_buffers = []

    def is_complete(self) -> bool:
        """Check if target has complete info (addr and rkeys)."""
        return self.remote_addr != 0 and len(self.rkeys) > 0

    def get_buffer_for_numa(self, numa_node: int) -> dict:
        """Get buffer info for specific NUMA node.
        
        Returns buffer dict with 'addr', 'length', 'numa_node', 'rkeys'.
        Falls back to remote_addr/rkeys if no NUMA-specific buffer found.
        """
        if self.remote_buffers:
            for buf in self.remote_buffers:
                if buf.get('numa_node') == numa_node:
                    return buf
            # Fallback to first buffer
            if self.remote_buffers:
                return self.remote_buffers[0]
        # Legacy fallback
        return {'addr': self.remote_addr, 'length': 0, 'numa_node': -1, 'rkeys': self.rkeys}


@dataclass
class ReplicationPlan:
    """Plan for scatter/gather operation."""
    lengths: List[int]
    offsets: List[int]
    remote_addresses: List[int]
    payloads: List[bytes]


class PerformanceTracker:
    """Track performance metrics."""

    def __init__(self) -> None:
        self.total_bytes = 0
        self.total_time = 0.0

    def add_sample(self, *, bytes_count: int, duration: float) -> None:
        self.total_bytes += bytes_count
        self.total_time += max(duration, 0.0)

    def average_bandwidth(self) -> float:
        if self.total_time <= 0:
            return 0.0
        return self.total_bytes / self.total_time


class MPCommTestHarness:
    """Test harness for MPComm mp_replicate operations."""

    def __init__(
        self,
        *,
        host_id: str,
        device_name: str,
        targets: List[TargetInfo],
        min_chunk_size: int,
        max_chunk_size: int,
        num_threads: int,
        performance_mode: bool = False,
    ) -> None:
        self.host_id = host_id
        self.device_name = device_name
        self.targets = targets
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.num_threads = num_threads
        self.performance_mode = performance_mode

        if min_chunk_size <= 0 or max_chunk_size <= 0:
            raise ValueError("Chunk sizes must be positive integers")
        if min_chunk_size > max_chunk_size:
            raise ValueError("min_chunk_size cannot exceed max_chunk_size")

        # Calculate buffer capacity
        self.buffer_capacity = max_chunk_size * len(targets)

        # Initialize MPComm
        self.comm = mpcomm.MPComm()
        ret = self.comm.init(host_id, device_name, 0)  # 0 = no listening port
        if ret != 0:
            raise RuntimeError(f"MPComm initialization failed with code {ret}")

        print(f"[test] Initialized MPComm with {self.comm.get_num_nics()} NICs")

        # Allocate and register local buffer
        self._tensor: Optional[torch.Tensor] = None
        self.local_buffer_addr = self._allocate_buffer()
        
        # Skip pattern initialization in performance mode
        if not performance_mode:
            self.local_ipv4_bytes = _resolve_ipv4_bytes(host_id)
            # Initialize buffer with local IPv4 pattern
            self._base_buffer_pattern = _build_ipv4_pattern(
                self.local_ipv4_bytes, self.buffer_capacity
            )
            self._reset_local_buffer()

            # Resolve target IPv4 bytes (for gather verification)
            self.target_ipv4_bytes = [
                _resolve_ipv4_bytes(t.host_id) for t in targets
            ]
        else:
            self.local_ipv4_bytes = [0, 0, 0, 0]
            self._base_buffer_pattern = b""
            self.target_ipv4_bytes = [[0, 0, 0, 0] for _ in targets]

        # Connect to targets
        self._connect_targets()

    def _allocate_buffer(self) -> int:
        """Allocate a tensor buffer and register it for RDMA."""
        tensor = torch.empty(self.buffer_capacity, dtype=torch.uint8)
        if not tensor.is_contiguous():
            tensor = tensor.contiguous()
        addr = tensor.data_ptr()

        ret = self.comm.register_memory(addr, self.buffer_capacity)
        if ret != 0:
            raise RuntimeError(f"Failed to register memory: {ret}")

        self._tensor = tensor
        print(f"[test] Registered buffer at 0x{addr:x} ({_format_bytes(self.buffer_capacity)})")
        return addr

    def _connect_targets(self) -> None:
        """Connect to all target hosts and query buffer info if needed."""
        for target in self.targets:
            print(f"[test] Connecting to {target.host_id} at {target.tcp_addr}:{target.tcp_port}...")
            ret = self.comm.connect(target.host_id, target.tcp_addr, target.tcp_port)
            if ret != 0:
                raise RuntimeError(f"Failed to connect to {target.host_id}: {ret}")

            # Query remote buffer info if not provided
            if not target.is_complete():
                print(f"[test] Querying buffer info from {target.host_id}...")
                buffer_info = self.comm.query_remote_buffer(
                    target.host_id, target.tcp_addr, target.tcp_port
                )
                if not buffer_info:
                    raise RuntimeError(f"Failed to query buffer info from {target.host_id}")
                
                target.remote_addr = buffer_info["addr"]
                target.rkeys = buffer_info["rkeys"]
                print(f"[test] Got buffer info from {target.host_id}: "
                      f"addr=0x{target.remote_addr:x}, rkeys={target.rkeys}")
            else:
                # Update remote memory info (rkeys) if provided manually
                ret = self.comm.update_remote_memory_info(target.host_id, target.rkeys)
                if ret != 0:
                    raise RuntimeError(f"Failed to update rkeys for {target.host_id}: {ret}")

            print(f"[test] Connected to {target.host_id}, rkeys={target.rkeys}")

    def _reset_local_buffer(self) -> None:
        """Reset local buffer to base IPv4 pattern."""
        ret = self.comm.write_bytes_to_buffer(
            self.local_buffer_addr,
            self._base_buffer_pattern,
            len(self._base_buffer_pattern)
        )
        if ret != 0:
            raise RuntimeError("Failed to reset local buffer")

    def _write_local_chunk(self, offset: int, payload: bytes) -> None:
        """Write data to local buffer at offset."""
        addr = self.local_buffer_addr + offset
        ret = self.comm.write_bytes_to_buffer(addr, payload, len(payload))
        if ret != 0:
            raise RuntimeError(f"Failed to write local chunk at offset {offset}")

    def _clear_local_chunk(self, offset: int, length: int) -> None:
        """Clear local buffer region with zeros."""
        addr = self.local_buffer_addr + offset
        ret = self.comm.write_bytes_to_buffer(addr, bytes(length), length)
        if ret != 0:
            raise RuntimeError(f"Failed to clear local chunk at offset {offset}")

    def _read_local_bytes(self, offset: int, length: int) -> bytes:
        """Read bytes from local buffer."""
        if length <= 0:
            return b""
        return self.comm.read_bytes_from_buffer(self.local_buffer_addr + offset, length)

    def build_replication_plan(self, seed: int, mode: str = "scatter") -> ReplicationPlan:
        """Build a replication plan with random chunk sizes."""
        if mode not in {"scatter", "gather"}:
            raise ValueError(f"Unsupported mode: {mode}")

        rng = random.Random(seed)
        lengths: List[int] = []

        for _ in self.targets:
            length = rng.randint(self.min_chunk_size, self.max_chunk_size)
            lengths.append(length)

        # Calculate offsets
        offsets: List[int] = []
        cursor = 0
        for length in lengths:
            offsets.append(cursor)
            cursor += length

        if cursor > self.buffer_capacity:
            raise RuntimeError("Replication plan exceeds buffer capacity")

        # Build remote addresses (from targets)
        remote_addresses = [t.remote_addr for t in self.targets]

        # Build expected payloads (skip in performance mode)
        payloads: List[bytes] = []
        if not self.performance_mode:
            for idx, length in enumerate(lengths):
                if mode == "gather":
                    # For gather, expect remote's IPv4 pattern
                    ip_bytes = self.target_ipv4_bytes[idx]
                    payloads.append(_build_ipv4_pattern(ip_bytes, length))
                else:
                    # For scatter, use local IPv4 pattern from buffer
                    start = offsets[idx]
                    payloads.append(self._base_buffer_pattern[start:start + length])

        return ReplicationPlan(lengths, offsets, remote_addresses, payloads)

    def run_scatter(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
    ) -> float:
        """Run scatter operation (RDMA WRITE to targets).
        
        Note: This now uses async API internally since sync API has been removed.
        """
        return self.run_scatter_async(
            seed,
            prepare_payload=prepare_payload,
            verify=verify,
            reset=reset,
            plan=plan,
            timeout_ms=-1,
        )

    def run_scatter_async(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        timeout_ms: int = -1,
    ) -> float:
        """Run async scatter operation (RDMA WRITE to targets)."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="scatter")

        # Prepare payloads in local buffer
        if prepare_payload:
            for offset, payload in zip(plan.offsets, plan.payloads):
                if payload:
                    self._write_local_chunk(offset, payload)

        # Build host list
        host_list = [t.host_id for t in self.targets]

        # Run async scatter
        start_time = time.perf_counter()
        handle = self.comm.scatter_async(
            self.local_buffer_addr,
            host_list,
            plan.remote_addresses,
            plan.lengths
        )

        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            raise RuntimeError("scatter_async failed to start")

        # Wait for completion
        ret = self.comm.wait_transfer(handle, timeout_ms)
        duration = time.perf_counter() - start_time

        # Get result and release handle
        result = self.comm.get_transfer_result(handle)
        self.comm.release_transfer(handle)

        if ret != 0:
            raise RuntimeError(f"scatter_async failed with code {ret}")

        if result["error_code"] != 0:
            raise RuntimeError(f"scatter_async transfer error: {result['error_code']}")

        # Verification: read back from remote and compare
        if verify:
            self._verify_scatter(plan)

        if reset:
            self._reset_local_buffer()

        return duration

    def run_gather(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
    ) -> float:
        """Run gather operation (RDMA READ from targets).
        
        Note: This now uses async API internally since sync API has been removed.
        """
        return self.run_gather_async(
            seed,
            prepare_payload=prepare_payload,
            verify=verify,
            reset=reset,
            plan=plan,
            timeout_ms=-1,
        )

    def run_gather_async(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        timeout_ms: int = -1,
    ) -> float:
        """Run async gather operation (RDMA READ from targets)."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="gather")

        # Clear local buffer regions where data will be gathered
        if prepare_payload:
            for offset, length in zip(plan.offsets, plan.lengths):
                self._clear_local_chunk(offset, length)

        # Build host list
        host_list = [t.host_id for t in self.targets]

        # Run async gather
        start_time = time.perf_counter()
        handle = self.comm.gather_async(
            self.local_buffer_addr,
            host_list,
            plan.remote_addresses,
            plan.lengths
        )

        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            raise RuntimeError("gather_async failed to start")

        # Wait for completion
        ret = self.comm.wait_transfer(handle, timeout_ms)
        duration = time.perf_counter() - start_time

        # Get result and release handle
        result = self.comm.get_transfer_result(handle)
        self.comm.release_transfer(handle)

        if ret != 0:
            raise RuntimeError(f"gather_async failed with code {ret}")

        if result["error_code"] != 0:
            raise RuntimeError(f"gather_async transfer error: {result['error_code']}")

        # Verification
        if verify:
            self._verify_gather(plan)

        if reset:
            self._reset_local_buffer()

        return duration

    def run_scatter_async_polling(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        poll_interval_us: int = 100,
    ) -> float:
        """Run async scatter with polling (non-blocking check) mode."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="scatter")

        # Prepare payloads in local buffer
        if prepare_payload:
            for offset, payload in zip(plan.offsets, plan.payloads):
                if payload:
                    self._write_local_chunk(offset, payload)

        # Build host list
        host_list = [t.host_id for t in self.targets]

        # Run async scatter
        start_time = time.perf_counter()
        handle = self.comm.scatter_async(
            self.local_buffer_addr,
            host_list,
            plan.remote_addresses,
            plan.lengths
        )

        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            raise RuntimeError("scatter_async failed to start")

        # Polling loop
        poll_count = 0
        while not self.comm.is_transfer_complete(handle):
            poll_count += 1
            time.sleep(poll_interval_us / 1_000_000)  # Convert us to seconds

        duration = time.perf_counter() - start_time

        # Get result and release handle
        result = self.comm.get_transfer_result(handle)
        self.comm.release_transfer(handle)

        if result["error_code"] != 0:
            raise RuntimeError(f"scatter_async transfer error: {result['error_code']}")

        print(f"  [async polling] completed after {poll_count} polls")

        # Verification
        if verify:
            self._verify_scatter(plan)

        if reset:
            self._reset_local_buffer()

        return duration

    def run_gather_async_polling(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        poll_interval_us: int = 100,
    ) -> float:
        """Run async gather with polling (non-blocking check) mode."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="gather")

        # Clear local buffer regions where data will be gathered
        if prepare_payload:
            for offset, length in zip(plan.offsets, plan.lengths):
                self._clear_local_chunk(offset, length)

        # Build host list
        host_list = [t.host_id for t in self.targets]

        # Run async gather
        start_time = time.perf_counter()
        handle = self.comm.gather_async(
            self.local_buffer_addr,
            host_list,
            plan.remote_addresses,
            plan.lengths
        )

        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            raise RuntimeError("gather_async failed to start")

        # Polling loop
        poll_count = 0
        while not self.comm.is_transfer_complete(handle):
            poll_count += 1
            time.sleep(poll_interval_us / 1_000_000)  # Convert us to seconds

        duration = time.perf_counter() - start_time

        # Get result and release handle
        result = self.comm.get_transfer_result(handle)
        self.comm.release_transfer(handle)

        if result["error_code"] != 0:
            raise RuntimeError(f"gather_async transfer error: {result['error_code']}")

        print(f"  [async polling] completed after {poll_count} polls")

        # Verification
        if verify:
            self._verify_gather(plan)

        if reset:
            self._reset_local_buffer()

        return duration

    def _verify_scatter(self, plan: ReplicationPlan) -> None:
        """Verify scatter operation by reading back from remotes."""
        # For scatter, we need to read back the data from remote to verify
        # This requires another gather operation
        host_list = [t.host_id for t in self.targets]

        # First, save and clear local buffer
        for offset, length in zip(plan.offsets, plan.lengths):
            self._clear_local_chunk(offset, length)

        # Read back from remotes
        ret = self.comm.gather(
            self.local_buffer_addr,
            host_list,
            plan.remote_addresses,
            plan.lengths,
            self.num_threads
        )

        if ret != 0:
            print("[scatter verify] Failed to read back data for verification", file=sys.stderr)
            return

        # Compare
        for idx, (offset, length) in enumerate(zip(plan.offsets, plan.lengths)):
            if length <= 0:
                continue

            expected = plan.payloads[idx]
            actual = self._read_local_bytes(offset, length)

            target = self.targets[idx]
            expected_preview = _preview_hex(expected)
            actual_preview = _preview_hex(actual)

            print(
                f"[scatter verify] target={target.host_id} len={length}B "
                f"remote=0x{plan.remote_addresses[idx]:x} "
                f"expected={expected_preview} actual={actual_preview}"
            )

            if actual != expected:
                raise AssertionError(
                    f"Scatter verification failed for target {target.host_id}"
                )

    def _verify_gather(self, plan: ReplicationPlan) -> None:
        """Verify gather operation by checking local buffer."""
        for idx, (offset, length) in enumerate(zip(plan.offsets, plan.lengths)):
            if length <= 0:
                continue

            expected = plan.payloads[idx]
            actual = self._read_local_bytes(offset, length)

            target = self.targets[idx]
            expected_preview = _preview_hex(expected)
            actual_preview = _preview_hex(actual)

            print(
                f"[gather verify] target={target.host_id} len={length}B "
                f"remote=0x{plan.remote_addresses[idx]:x} "
                f"expected={expected_preview} actual={actual_preview}"
            )

            if actual != expected:
                raise AssertionError(
                    f"Gather verification failed for target {target.host_id}"
                )

    def close(self) -> None:
        """Cleanup resources."""
        if self.local_buffer_addr and self._tensor is not None:
            self.comm.unregister_memory(self.local_buffer_addr)
            self.local_buffer_addr = 0
            self._tensor = None
        self.comm.shutdown()


class MultiNumaTestHarness:
    """Test harness for MPComm operations with multiple NUMA nodes.
    
    This class allocates separate buffers on different NUMA nodes and
    runs async transfers in parallel to maximize bandwidth utilization.
    """

    def __init__(
        self,
        *,
        host_id: str,
        device_name: str,
        targets: List[TargetInfo],
        min_chunk_size: int,
        max_chunk_size: int,
        num_threads: int,
        num_numas: int = 2,
        performance_mode: bool = False,
    ) -> None:
        self.host_id = host_id
        self.device_name = device_name
        self.targets = targets
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.num_threads = num_threads
        self.num_numas = num_numas
        self.performance_mode = performance_mode

        if min_chunk_size <= 0 or max_chunk_size <= 0:
            raise ValueError("Chunk sizes must be positive integers")
        if min_chunk_size > max_chunk_size:
            raise ValueError("min_chunk_size cannot exceed max_chunk_size")
        if num_numas < 1:
            raise ValueError("num_numas must be at least 1")

        # Calculate buffer capacity per NUMA
        self.buffer_capacity = max_chunk_size * len(targets)

        # Initialize MPComm
        self.comm = mpcomm.MPComm()
        ret = self.comm.init(host_id, device_name, 0)  # 0 = no listening port
        if ret != 0:
            raise RuntimeError(f"MPComm initialization failed with code {ret}")

        print(f"[multi-numa] Initialized MPComm with {self.comm.get_num_nics()} NICs")
        print(f"[multi-numa] Using {num_numas} NUMA node(s)")

        # Allocate and register buffers for each NUMA node
        self._tensors: List[Optional[torch.Tensor]] = []
        self.local_buffer_addrs: List[int] = []
        self._allocate_numa_buffers()

        # Skip pattern initialization in performance mode
        if not performance_mode:
            self.local_ipv4_bytes = _resolve_ipv4_bytes(host_id)
            self._base_buffer_pattern = _build_ipv4_pattern(
                self.local_ipv4_bytes, self.buffer_capacity
            )
            self._reset_all_buffers()
            self.target_ipv4_bytes = [
                _resolve_ipv4_bytes(t.host_id) for t in targets
            ]
        else:
            self.local_ipv4_bytes = [0, 0, 0, 0]
            self._base_buffer_pattern = b""
            self.target_ipv4_bytes = [[0, 0, 0, 0] for _ in targets]

        # Connect to targets
        self._connect_targets()

    def _allocate_numa_buffers(self) -> None:
        """Allocate tensor buffers on different NUMA nodes."""
        for numa_id in range(self.num_numas):
            # Try to allocate on specific NUMA node
            # Note: PyTorch doesn't have direct NUMA API, we use numactl or rely on OS
            # For now, we allocate separate tensors which may be placed on different NUMA nodes
            # by the OS based on memory policy
            try:
                # Try to use numa library if available
                try:
                    import numa
                    if numa.available():
                        numa.set_preferred(numa_id % numa.get_max_node())
                except ImportError:
                    pass  # numa library not available, continue without NUMA binding
                
                tensor = torch.empty(self.buffer_capacity, dtype=torch.uint8)
                if not tensor.is_contiguous():
                    tensor = tensor.contiguous()
                
                # Touch the memory to ensure allocation on current NUMA node
                tensor.fill_(0)
                
                addr = tensor.data_ptr()
                ret = self.comm.register_memory(addr, self.buffer_capacity)
                if ret != 0:
                    raise RuntimeError(f"Failed to register memory for NUMA {numa_id}: {ret}")

                self._tensors.append(tensor)
                self.local_buffer_addrs.append(addr)
                print(f"[multi-numa] NUMA {numa_id}: Registered buffer at 0x{addr:x} "
                      f"({_format_bytes(self.buffer_capacity)})")
            except Exception as e:
                raise RuntimeError(f"Failed to allocate buffer for NUMA {numa_id}: {e}")

    def _connect_targets(self) -> None:
        """Connect to all target hosts and query buffer info (with NUMA support)."""
        for target in self.targets:
            print(f"[multi-numa] Connecting to {target.host_id} at {target.tcp_addr}:{target.tcp_port}...")
            ret = self.comm.connect(target.host_id, target.tcp_addr, target.tcp_port)
            if ret != 0:
                raise RuntimeError(f"Failed to connect to {target.host_id}: {ret}")

            if not target.is_complete():
                print(f"[multi-numa] Querying all buffers from {target.host_id}...")
                # Try new multi-buffer API first
                try:
                    all_buffers = self.comm.query_remote_buffers(
                        target.host_id, target.tcp_addr, target.tcp_port
                    )
                except AttributeError:
                    # Fallback to old API if new one not available
                    all_buffers = None

                if all_buffers and 'buffers' in all_buffers and all_buffers['buffers']:
                    # New multi-buffer API succeeded
                    target.remote_buffers = all_buffers['buffers']
                    # Use first buffer for backward compatibility
                    first_buf = all_buffers['buffers'][0]
                    target.remote_addr = first_buf['addr']
                    target.rkeys = first_buf['rkeys']
                    print(f"[multi-numa] Got {len(all_buffers['buffers'])} buffer(s) from {target.host_id}:")
                    for buf in all_buffers['buffers']:
                        print(f"    NUMA {buf.get('numa_node', -1)}: addr=0x{buf['addr']:x}, "
                              f"length={_format_bytes(buf['length'])}, rkeys={buf['rkeys']}")
                else:
                    # Fallback to old single-buffer API
                    buffer_info = self.comm.query_remote_buffer(
                        target.host_id, target.tcp_addr, target.tcp_port
                    )
                    if not buffer_info:
                        raise RuntimeError(f"Failed to query buffer info from {target.host_id}")
                    target.remote_addr = buffer_info['addr']
                    target.rkeys = buffer_info['rkeys']
                    print(f"[multi-numa] Got buffer info from {target.host_id}: "
                          f"addr=0x{target.remote_addr:x}, rkeys={target.rkeys}")
            else:
                ret = self.comm.update_remote_memory_info(target.host_id, target.rkeys)
                if ret != 0:
                    raise RuntimeError(f"Failed to update rkeys for {target.host_id}: {ret}")

            print(f"[multi-numa] Connected to {target.host_id}")

    def _reset_all_buffers(self) -> None:
        """Reset all NUMA buffers to base IPv4 pattern."""
        for numa_id, addr in enumerate(self.local_buffer_addrs):
            ret = self.comm.write_bytes_to_buffer(
                addr, self._base_buffer_pattern, len(self._base_buffer_pattern)
            )
            if ret != 0:
                raise RuntimeError(f"Failed to reset buffer for NUMA {numa_id}")

    def _write_chunk(self, numa_id: int, offset: int, payload: bytes) -> None:
        """Write data to specific NUMA buffer at offset."""
        addr = self.local_buffer_addrs[numa_id] + offset
        ret = self.comm.write_bytes_to_buffer(addr, payload, len(payload))
        if ret != 0:
            raise RuntimeError(f"Failed to write chunk at NUMA {numa_id} offset {offset}")

    def _clear_chunk(self, numa_id: int, offset: int, length: int) -> None:
        """Clear NUMA buffer region with zeros."""
        addr = self.local_buffer_addrs[numa_id] + offset
        ret = self.comm.write_bytes_to_buffer(addr, bytes(length), length)
        if ret != 0:
            raise RuntimeError(f"Failed to clear chunk at NUMA {numa_id} offset {offset}")

    def _read_bytes(self, numa_id: int, offset: int, length: int) -> bytes:
        """Read bytes from specific NUMA buffer."""
        if length <= 0:
            return b""
        return self.comm.read_bytes_from_buffer(
            self.local_buffer_addrs[numa_id] + offset, length
        )

    def build_replication_plan(self, seed: int, mode: str = "scatter") -> ReplicationPlan:
        """Build a replication plan with random chunk sizes."""
        if mode not in {"scatter", "gather"}:
            raise ValueError(f"Unsupported mode: {mode}")

        rng = random.Random(seed)
        lengths: List[int] = []

        for _ in self.targets:
            length = rng.randint(self.min_chunk_size, self.max_chunk_size)
            lengths.append(length)

        # Calculate offsets
        offsets: List[int] = []
        cursor = 0
        for length in lengths:
            offsets.append(cursor)
            cursor += length

        if cursor > self.buffer_capacity:
            raise RuntimeError("Replication plan exceeds buffer capacity")

        remote_addresses = [t.remote_addr for t in self.targets]

        payloads: List[bytes] = []
        if not self.performance_mode:
            for idx, length in enumerate(lengths):
                if mode == "gather":
                    ip_bytes = self.target_ipv4_bytes[idx]
                    payloads.append(_build_ipv4_pattern(ip_bytes, length))
                else:
                    start = offsets[idx]
                    payloads.append(self._base_buffer_pattern[start:start + length])

        return ReplicationPlan(lengths, offsets, remote_addresses, payloads)

    def get_remote_addresses_for_numa(self, numa_id: int) -> List[int]:
        """Get remote addresses for a specific NUMA node.
        
        This method enables NUMA-to-NUMA mapping:
        - initiator NUMA 0 accesses target buffers with numa_node=0
        - initiator NUMA 1 accesses target buffers with numa_node=1
        - etc.
        """
        remote_addrs = []
        for target in self.targets:
            if target.remote_buffers:
                # Use multi-NUMA buffer matching
                buf = target.get_buffer_for_numa(numa_id)
                remote_addrs.append(buf['addr'])
            else:
                # Fallback to single buffer
                remote_addrs.append(target.remote_addr)
        return remote_addrs

    def _get_target_rkeys_for_numa(self, target: TargetInfo, numa_id: int) -> List[int]:
        """Get rkeys for a specific target's NUMA buffer.
        
        Returns the rkeys associated with the buffer that matches the given numa_id.
        Falls back to target.rkeys if no NUMA-specific buffer is found.
        """
        if target.remote_buffers:
            buf = target.get_buffer_for_numa(numa_id)
            return buf.get('rkeys', target.rkeys)
        return target.rkeys

    def _get_rkeys_for_numa(self, numa_id: int) -> List[List[int]]:
        """Get rkeys for all targets for a specific NUMA node.
        
        Returns a list of rkey lists, one per target.
        """
        return [self._get_target_rkeys_for_numa(t, numa_id) for t in self.targets]

    def run_multi_numa_scatter_async(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        timeout_ms: int = -1,
    ) -> tuple:
        """Run parallel async scatter operations on all NUMA nodes.
        
        Each local NUMA buffer scatters to corresponding remote NUMA buffer:
        - local NUMA 0 -> remote NUMA 0 buffer
        - local NUMA 1 -> remote NUMA 1 buffer
        
        Returns:
            tuple: (total_duration, total_bytes, per_numa_durations)
        """
        if plan is None:
            plan = self.build_replication_plan(seed, mode="scatter")

        # Prepare payloads in all NUMA buffers
        if prepare_payload:
            for numa_id in range(self.num_numas):
                for offset, payload in zip(plan.offsets, plan.payloads):
                    if payload:
                        self._write_chunk(numa_id, offset, payload)

        host_list = [t.host_id for t in self.targets]
        total_bytes = sum(plan.lengths) * self.num_numas

        # Debug: print remote buffer info
        print(f"[multi-numa scatter] Starting scatter on {self.num_numas} NUMA node(s)")
        for numa_id in range(self.num_numas):
            remote_addrs = self.get_remote_addresses_for_numa(numa_id)
            rkeys_for_numa = self._get_rkeys_for_numa(numa_id)
            print(f"  NUMA {numa_id}: local_addr=0x{self.local_buffer_addrs[numa_id]:x}, "
                  f"remote_addrs=[{', '.join(f'0x{a:x}' for a in remote_addrs)}], "
                  f"rkeys={rkeys_for_numa}")

        # Start async transfers on all NUMA nodes in parallel
        # C++ side now uses getRkeyForAddr() to find correct rkey for each remote_addr
        start_time = time.perf_counter()
        handles = []
        
        for numa_id in range(self.num_numas):
            # Get remote addresses for this NUMA node
            remote_addrs = self.get_remote_addresses_for_numa(numa_id)
            
            print(f"[multi-numa scatter] Starting scatter_async for NUMA {numa_id}...")
            handle = self.comm.scatter_async(
                self.local_buffer_addrs[numa_id],
                host_list,
                remote_addrs,
                plan.lengths
            )
            print(f"[multi-numa scatter] scatter_async returned handle={handle} for NUMA {numa_id}")
            if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                # Release already started handles
                for h in handles:
                    self.comm.release_transfer(h)
                raise RuntimeError(f"scatter_async failed to start on NUMA {numa_id}")
            handles.append(handle)

        # Wait for all transfers to complete in parallel
        print(f"[multi-numa scatter] All {len(handles)} handles started, waiting for completion...")
        per_numa_durations = []
        for numa_id, handle in enumerate(handles):
            print(f"[multi-numa scatter] Waiting for NUMA {numa_id} handle={handle}...")
            ret = self.comm.wait_transfer(handle, timeout_ms)
            
            if ret != 0:
                raise RuntimeError(f"scatter_async failed on NUMA {numa_id} with code {ret}")
            result = self.comm.get_transfer_result(handle)
            self.comm.release_transfer(handle)
            if result["error_code"] != 0:
                raise RuntimeError(f"scatter_async transfer error on NUMA {numa_id}: {result['error_code']}")
            # Use actual elapsed time from C++ layer (in ms, convert to seconds)
            numa_duration = result["elapsed_ms"] / 1000.0
            per_numa_durations.append(numa_duration)
            print(f"[multi-numa scatter] NUMA {numa_id} completed in {numa_duration*1000:.2f}ms")

        total_duration = time.perf_counter() - start_time
        print(f"[multi-numa scatter] All transfers completed in {total_duration*1000:.2f}ms")

        # Verification
        if verify:
            for numa_id in range(self.num_numas):
                self._verify_scatter(numa_id, plan)

        if reset:
            self._reset_all_buffers()

        return total_duration, total_bytes, per_numa_durations

    def run_multi_numa_gather_async(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        timeout_ms: int = -1,
    ) -> tuple:
        """Run parallel async gather operations on all NUMA nodes.
        
        Each local NUMA buffer gathers from corresponding remote NUMA buffer:
        - local NUMA 0 <- remote NUMA 0 buffer
        - local NUMA 1 <- remote NUMA 1 buffer
        
        Returns:
            tuple: (total_duration, total_bytes, per_numa_durations)
        """
        if plan is None:
            plan = self.build_replication_plan(seed, mode="gather")

        # Clear all NUMA buffer regions
        if prepare_payload:
            for numa_id in range(self.num_numas):
                for offset, length in zip(plan.offsets, plan.lengths):
                    self._clear_chunk(numa_id, offset, length)

        host_list = [t.host_id for t in self.targets]
        total_bytes = sum(plan.lengths) * self.num_numas

        # Debug: print remote buffer info
        print(f"[multi-numa gather] Starting gather on {self.num_numas} NUMA node(s)")
        for numa_id in range(self.num_numas):
            remote_addrs = self.get_remote_addresses_for_numa(numa_id)
            rkeys_for_numa = self._get_rkeys_for_numa(numa_id)
            print(f"  NUMA {numa_id}: local_addr=0x{self.local_buffer_addrs[numa_id]:x}, "
                  f"remote_addrs=[{', '.join(f'0x{a:x}' for a in remote_addrs)}], "
                  f"rkeys={rkeys_for_numa}")

        # Start async transfers on all NUMA nodes in parallel
        # C++ side now uses getRkeyForAddr() to find correct rkey for each remote_addr
        start_time = time.perf_counter()
        handles = []
        
        for numa_id in range(self.num_numas):
            # Get remote addresses for this NUMA node
            remote_addrs = self.get_remote_addresses_for_numa(numa_id)
            
            print(f"[multi-numa gather] Starting gather_async for NUMA {numa_id}...")
            handle = self.comm.gather_async(
                self.local_buffer_addrs[numa_id],
                host_list,
                remote_addrs,
                plan.lengths
            )
            print(f"[multi-numa gather] gather_async returned handle={handle} for NUMA {numa_id}")
            if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                for h in handles:
                    self.comm.release_transfer(h)
                raise RuntimeError(f"gather_async failed to start on NUMA {numa_id}")
            handles.append(handle)

        # Wait for all transfers to complete in parallel
        print(f"[multi-numa gather] All {len(handles)} handles started, waiting for completion...")
        per_numa_durations = []
        for numa_id, handle in enumerate(handles):
            print(f"[multi-numa gather] Waiting for NUMA {numa_id} handle={handle}...")
            ret = self.comm.wait_transfer(handle, timeout_ms)
            
            if ret != 0:
                raise RuntimeError(f"gather_async failed on NUMA {numa_id} with code {ret}")
            result = self.comm.get_transfer_result(handle)
            self.comm.release_transfer(handle)
            if result["error_code"] != 0:
                raise RuntimeError(f"gather_async transfer error on NUMA {numa_id}: {result['error_code']}")
            # Use actual elapsed time from C++ layer (in ms, convert to seconds)
            numa_duration = result["elapsed_ms"] / 1000.0
            per_numa_durations.append(numa_duration)
            print(f"[multi-numa gather] NUMA {numa_id} completed in {numa_duration*1000:.2f}ms")

        total_duration = time.perf_counter() - start_time
        print(f"[multi-numa gather] All transfers completed in {total_duration*1000:.2f}ms")

        # Verification
        if verify:
            for numa_id in range(self.num_numas):
                self._verify_gather(numa_id, plan)

        if reset:
            self._reset_all_buffers()

        return total_duration, total_bytes, per_numa_durations

    def run_multi_numa_scatter_async_polling(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        poll_interval_us: int = 100,
    ) -> tuple:
        """Run parallel async scatter with polling mode on all NUMA nodes."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="scatter")

        if prepare_payload:
            for numa_id in range(self.num_numas):
                for offset, payload in zip(plan.offsets, plan.payloads):
                    if payload:
                        self._write_chunk(numa_id, offset, payload)

        host_list = [t.host_id for t in self.targets]
        total_bytes = sum(plan.lengths) * self.num_numas

        # Start async transfers on all NUMA nodes in parallel
        start_time = time.perf_counter()
        handles = []
        
        for numa_id in range(self.num_numas):
            # Get remote addresses for this NUMA node
            remote_addrs = self.get_remote_addresses_for_numa(numa_id)
            
            handle = self.comm.scatter_async(
                self.local_buffer_addrs[numa_id],
                host_list,
                remote_addrs,
                plan.lengths
            )
            if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                for h in handles:
                    self.comm.release_transfer(h)
                raise RuntimeError(f"scatter_async failed to start on NUMA {numa_id}")
            handles.append(handle)

        # Polling loop - wait for all to complete
        poll_count = 0
        completed = [False] * self.num_numas
        
        while not all(completed):
            poll_count += 1
            for numa_id, handle in enumerate(handles):
                if not completed[numa_id] and self.comm.is_transfer_complete(handle):
                    completed[numa_id] = True
            time.sleep(poll_interval_us / 1_000_000)

        total_duration = time.perf_counter() - start_time

        # Get results and release handles, use elapsed_ms for per-NUMA durations
        per_numa_durations = [0.0] * self.num_numas
        for numa_id, handle in enumerate(handles):
            result = self.comm.get_transfer_result(handle)
            self.comm.release_transfer(handle)
            if result["error_code"] != 0:
                raise RuntimeError(f"scatter_async transfer error on NUMA {numa_id}: {result['error_code']}")
            # Use actual elapsed time from C++ layer (in ms, convert to seconds)
            per_numa_durations[numa_id] = result["elapsed_ms"] / 1000.0

        print(f"  [multi-numa async polling] completed after {poll_count} polls")

        if verify:
            for numa_id in range(self.num_numas):
                self._verify_scatter(numa_id, plan)

        if reset:
            self._reset_all_buffers()

        return total_duration, total_bytes, per_numa_durations

    def run_multi_numa_gather_async_polling(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        poll_interval_us: int = 100,
    ) -> tuple:
        """Run parallel async gather with polling mode on all NUMA nodes."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="gather")

        if prepare_payload:
            for numa_id in range(self.num_numas):
                for offset, length in zip(plan.offsets, plan.lengths):
                    self._clear_chunk(numa_id, offset, length)

        host_list = [t.host_id for t in self.targets]
        total_bytes = sum(plan.lengths) * self.num_numas

        # Start async transfers on all NUMA nodes in parallel
        start_time = time.perf_counter()
        handles = []
        
        for numa_id in range(self.num_numas):
            # Get remote addresses for this NUMA node
            remote_addrs = self.get_remote_addresses_for_numa(numa_id)
            
            handle = self.comm.gather_async(
                self.local_buffer_addrs[numa_id],
                host_list,
                remote_addrs,
                plan.lengths
            )
            if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                for h in handles:
                    self.comm.release_transfer(h)
                raise RuntimeError(f"gather_async failed to start on NUMA {numa_id}")
            handles.append(handle)

        # Polling loop - wait for all to complete
        poll_count = 0
        completed = [False] * self.num_numas
        
        while not all(completed):
            poll_count += 1
            for numa_id, handle in enumerate(handles):
                if not completed[numa_id] and self.comm.is_transfer_complete(handle):
                    completed[numa_id] = True
            time.sleep(poll_interval_us / 1_000_000)

        total_duration = time.perf_counter() - start_time

        # Get results and release handles, use elapsed_ms for per-NUMA durations
        per_numa_durations = [0.0] * self.num_numas
        for numa_id, handle in enumerate(handles):
            result = self.comm.get_transfer_result(handle)
            self.comm.release_transfer(handle)
            if result["error_code"] != 0:
                raise RuntimeError(f"gather_async transfer error on NUMA {numa_id}: {result['error_code']}")
            # Use actual elapsed time from C++ layer (in ms, convert to seconds)
            per_numa_durations[numa_id] = result["elapsed_ms"] / 1000.0

        print(f"  [multi-numa async polling] completed after {poll_count} polls")

        if verify:
            for numa_id in range(self.num_numas):
                self._verify_gather(numa_id, plan)

        if reset:
            self._reset_all_buffers()

        return total_duration, total_bytes, per_numa_durations

    def _verify_scatter(self, numa_id: int, plan: ReplicationPlan) -> None:
        """Verify scatter operation for a specific NUMA node."""
        host_list = [t.host_id for t in self.targets]

        # Clear and read back
        for offset, length in zip(plan.offsets, plan.lengths):
            self._clear_chunk(numa_id, offset, length)

        # Use NUMA-to-NUMA mapping for verification
        remote_addrs = self.get_remote_addresses_for_numa(numa_id)

        ret = self.comm.gather(
            self.local_buffer_addrs[numa_id],
            host_list,
            remote_addrs,
            plan.lengths,
            self.num_threads
        )

        if ret != 0:
            print(f"[scatter verify NUMA {numa_id}] Failed to read back data", file=sys.stderr)
            return

        for idx, (offset, length) in enumerate(zip(plan.offsets, plan.lengths)):
            if length <= 0:
                continue
            expected = plan.payloads[idx]
            actual = self._read_bytes(numa_id, offset, length)
            target = self.targets[idx]

            if actual != expected:
                expected_preview = _preview_hex(expected)
                actual_preview = _preview_hex(actual)
                print(f"[scatter verify NUMA {numa_id}] target={target.host_id} "
                      f"expected={expected_preview} actual={actual_preview}")
                raise AssertionError(
                    f"Scatter verification failed for NUMA {numa_id} target {target.host_id}"
                )

    def _verify_gather(self, numa_id: int, plan: ReplicationPlan) -> None:
        """Verify gather operation for a specific NUMA node."""
        for idx, (offset, length) in enumerate(zip(plan.offsets, plan.lengths)):
            if length <= 0:
                continue
            expected = plan.payloads[idx]
            actual = self._read_bytes(numa_id, offset, length)
            target = self.targets[idx]

            if actual != expected:
                expected_preview = _preview_hex(expected)
                actual_preview = _preview_hex(actual)
                print(f"[gather verify NUMA {numa_id}] target={target.host_id} "
                      f"expected={expected_preview} actual={actual_preview}")
                raise AssertionError(
                    f"Gather verification failed for NUMA {numa_id} target {target.host_id}"
                )

    def close(self) -> None:
        """Cleanup resources."""
        for numa_id, (addr, tensor) in enumerate(zip(self.local_buffer_addrs, self._tensors)):
            if addr and tensor is not None:
                self.comm.unregister_memory(addr)
        self.local_buffer_addrs = []
        self._tensors = []
        self.comm.shutdown()


# Default seeds (base36 encoded)
SCATTER_SEED = int("5CATT3R", 36)
GATHER_SEED = int("6A7H3R", 36)


def parse_target(target_str: str) -> TargetInfo:
    """
    Parse target string in format:
        host_id:tcp_addr:tcp_port[:remote_addr:rkey1,rkey2,...]
    
    If remote_addr and rkeys are not provided, they will be queried from remote.
    
    Examples:
        # Auto-query buffer info (recommended)
        target1:192.168.1.100:12345
        
        # Explicit buffer info (legacy)
        target1:192.168.1.100:12345:0x7f1234000000:12345678,87654321
    """
    parts = target_str.strip().split(":")
    if len(parts) < 3:
        raise ValueError(
            f"Invalid target format: {target_str}\n"
            "Expected: host_id:tcp_addr:tcp_port[:remote_addr:rkey1,rkey2,...]"
        )

    host_id = parts[0]
    tcp_addr = parts[1]
    tcp_port = int(parts[2])
    
    # Optional: remote_addr and rkeys (can be queried from remote)
    remote_addr = 0
    rkeys = []
    
    if len(parts) >= 5:
        remote_addr = int(parts[3], 0)  # Support hex
        rkeys = [int(r, 0) for r in parts[4].split(",")]

    return TargetInfo(
        host_id=host_id,
        tcp_addr=tcp_addr,
        tcp_port=tcp_port,
        remote_addr=remote_addr,
        rkeys=rkeys,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="MPComm mp_replicate Test Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Target format:
    host_id:tcp_addr:tcp_port[:remote_addr:rkey1,rkey2,...]

    If remote_addr and rkeys are not provided, they will be queried automatically
    from the target via TCP metadata exchange.

Examples:
    # Auto-query buffer info (recommended - no need to copy/paste addr and rkeys)
    python test_mpcomm.py --mode scatter --targets target1:192.168.1.100:12345

    # Async mode with wait_transfer
    python test_mpcomm.py --mode scatter --async --targets target1:192.168.1.100:12345

    # Async mode with polling (non-blocking)
    python test_mpcomm.py --mode scatter --async --async-mode polling --targets target1:192.168.1.100:12345

    # Multi-NUMA test (2 NUMA nodes with parallel async transfers)
    python test_mpcomm.py --mode scatter --async --num-numas 2 --targets target1:192.168.1.100:12345

    # Multiple targets with auto-query
    python test_mpcomm.py --mode both \\
        --targets target1:192.168.1.100:12345 \\
        --targets target2:114.193.206.253:12345

    # Explicit buffer info (legacy mode)
    python test_mpcomm.py --mode scatter \\
        --targets target1:192.168.1.100:12345:0x7f1234000000:12345678

    # Performance mode with 10 iterations
    python test_mpcomm.py --mode scatter --test-mode performance --iterations 10 \\
        --targets target1:192.168.1.100:12345
""",
    )

    parser.add_argument(
        "--mode",
        choices=["scatter", "gather", "both"],
        default="both",
        help="Operation mode (default: both)",
    )

    parser.add_argument(
        "--host-id",
        default=os.getenv("MPCOMM_HOST_ID", "initiator:0"),
        help="Local host identifier (default: initiator:0)",
    )

    parser.add_argument(
        "--device",
        default=os.getenv("MPCOMM_DEVICE", ""),
        help="RDMA device name (comma-separated for multiple). Empty = auto-detect",
    )

    parser.add_argument(
        "--targets",
        action="append",
        required=True,
        help="Target in format host_id:tcp_addr:tcp_port[:remote_addr:rkey1,rkey2,...]",
    )

    parser.add_argument(
        "--min-chunk-size",
        type=int,
        default=DEFAULT_MIN_CHUNK_SIZE,
        help=f"Minimum chunk size in bytes (default: {DEFAULT_MIN_CHUNK_SIZE})",
    )

    parser.add_argument(
        "--max-chunk-size",
        type=int,
        default=DEFAULT_MAX_CHUNK_SIZE,
        help=f"Maximum chunk size in bytes (default: {DEFAULT_MAX_CHUNK_SIZE})",
    )

    parser.add_argument(
        "--num-threads",
        type=int,
        default=1,
        help="Number of threads per transfer (default: 1)",
    )

    parser.add_argument(
        "--num-numas",
        type=int,
        default=1,
        help="Number of NUMA nodes to use for parallel async transfers (default: 1)",
    )

    parser.add_argument(
        "--scatter-seed",
        help="Seed for scatter plan (supports base-36 strings)",
    )

    parser.add_argument(
        "--gather-seed",
        help="Seed for gather plan (supports base-36 strings)",
    )

    parser.add_argument(
        "--test-mode",
        choices=["correctness", "performance"],
        default="correctness",
        help="Test mode: correctness verifies data, performance skips verification",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations (default: 1)",
    )

    parser.add_argument(
        "--async",
        dest="use_async",
        action="store_true",
        help="Use async transfer API instead of sync API",
    )

    parser.add_argument(
        "--async-mode",
        choices=["wait", "polling"],
        default="wait",
        help="Async mode: wait (blocking wait_transfer) or polling (non-blocking is_transfer_complete)",
    )

    parser.add_argument(
        "--async-timeout-ms",
        type=int,
        default=-1,
        help="Timeout for async wait in milliseconds (-1 = wait forever)",
    )

    parser.add_argument(
        "--poll-interval-us",
        type=int,
        default=100,
        help="Poll interval in microseconds for async polling mode (default: 100)",
    )

    return parser.parse_args()


def _parse_seed_arg(seed_value: Optional[str], fallback: int) -> int:
    """Parse seed argument supporting multiple formats."""
    if seed_value is None:
        return fallback

    parsers = (
        lambda: int(seed_value, 0),
        lambda: int(seed_value, 36),
        lambda: int(seed_value, 10),
    )

    for parser in parsers:
        try:
            return parser()
        except ValueError:
            continue

    print(f"Unable to parse seed '{seed_value}', using default {fallback}", file=sys.stderr)
    return fallback


def run_multi_numa_tests(
    harness: MultiNumaTestHarness,
    args: argparse.Namespace,
    scatter_seed: int,
    gather_seed: int,
) -> None:
    """Run tests using multi-NUMA harness."""
    run_scatter = args.mode in {"scatter", "both"}
    run_gather = args.mode in {"gather", "both"}
    iterations = args.iterations
    
    is_performance_mode = args.test_mode == "performance"
    prepare_payload = not is_performance_mode
    verify_payload = not is_performance_mode
    reset_buffer = not is_performance_mode
    
    async_mode = args.async_mode
    async_timeout_ms = args.async_timeout_ms
    poll_interval_us = args.poll_interval_us
    
    perf_tracker = PerformanceTracker() if is_performance_mode else None

    # Run scatter tests
    if run_scatter:
        mode_str = f"Multi-NUMA Async ({harness.num_numas} nodes)"
        print(f"\n=== Scatter Test [{mode_str}] (seed={scatter_seed}, iterations={iterations}) ===")
        plan = harness.build_replication_plan(scatter_seed, "scatter")
        bytes_per_numa = sum(plan.lengths)

        for i in range(iterations):
            current_seed = scatter_seed if is_performance_mode else scatter_seed + i
            if iterations > 1:
                print(f"\n[scatter] Iteration {i + 1}/{iterations}")

            if async_mode == "polling":
                duration, total_bytes, per_numa = harness.run_multi_numa_scatter_async_polling(
                    current_seed,
                    prepare_payload=prepare_payload,
                    verify=verify_payload,
                    reset=reset_buffer,
                    plan=plan if is_performance_mode else None,
                    poll_interval_us=poll_interval_us,
                )
            else:
                duration, total_bytes, per_numa = harness.run_multi_numa_scatter_async(
                    current_seed,
                    prepare_payload=prepare_payload,
                    verify=verify_payload,
                    reset=reset_buffer,
                    plan=plan if is_performance_mode else None,
                    timeout_ms=async_timeout_ms,
                )

            if perf_tracker:
                perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)
            
            bandwidth = total_bytes / duration if duration > 0 else 0
            duration_us = duration * 1_000_000
            print(f"  total: duration={duration_us:.2f}us, bytes={_format_bytes(total_bytes)}, "
                  f"bandwidth={_format_bandwidth(bandwidth)}")
            
            for numa_id, numa_dur in enumerate(per_numa):
                numa_bw = bytes_per_numa / numa_dur if numa_dur > 0 else 0
                print(f"    NUMA {numa_id}: {numa_dur*1_000_000:.2f}us, {_format_bandwidth(numa_bw)}")

    # Run gather tests
    if run_gather:
        mode_str = f"Multi-NUMA Async ({harness.num_numas} nodes)"
        print(f"\n=== Gather Test [{mode_str}] (seed={gather_seed}, iterations={iterations}) ===")
        plan = harness.build_replication_plan(gather_seed, "gather")
        bytes_per_numa = sum(plan.lengths)

        for i in range(iterations):
            current_seed = gather_seed if is_performance_mode else gather_seed + i
            if iterations > 1:
                print(f"\n[gather] Iteration {i + 1}/{iterations}")

            if async_mode == "polling":
                duration, total_bytes, per_numa = harness.run_multi_numa_gather_async_polling(
                    current_seed,
                    prepare_payload=prepare_payload,
                    verify=verify_payload,
                    reset=reset_buffer,
                    plan=plan if is_performance_mode else None,
                    poll_interval_us=poll_interval_us,
                )
            else:
                duration, total_bytes, per_numa = harness.run_multi_numa_gather_async(
                    current_seed,
                    prepare_payload=prepare_payload,
                    verify=verify_payload,
                    reset=reset_buffer,
                    plan=plan if is_performance_mode else None,
                    timeout_ms=async_timeout_ms,
                )

            if perf_tracker:
                perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)
            
            bandwidth = total_bytes / duration if duration > 0 else 0
            duration_us = duration * 1_000_000
            print(f"  total: duration={duration_us:.2f}us, bytes={_format_bytes(total_bytes)}, "
                  f"bandwidth={_format_bandwidth(bandwidth)}")
            
            for numa_id, numa_dur in enumerate(per_numa):
                numa_bw = bytes_per_numa / numa_dur if numa_dur > 0 else 0
                print(f"    NUMA {numa_id}: {numa_dur*1_000_000:.2f}us, {_format_bandwidth(numa_bw)}")

    # Print aggregate statistics
    if perf_tracker and perf_tracker.total_bytes > 0 and perf_tracker.total_time > 0:
        avg_bandwidth = perf_tracker.average_bandwidth()
        total_time_us = perf_tracker.total_time * 1_000_000
        print(f"\n[performance] Aggregate: bytes={_format_bytes(perf_tracker.total_bytes)}, "
              f"time={total_time_us:.2f}us, bandwidth={_format_bandwidth(avg_bandwidth)}")


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Parse targets
    targets = [parse_target(t) for t in args.targets]
    print(f"[test] Configured {len(targets)} target(s):")
    for t in targets:
        if t.is_complete():
            print(f"  - {t.host_id} @ {t.tcp_addr}:{t.tcp_port}, "
                  f"addr=0x{t.remote_addr:x}, rkeys={t.rkeys}")
        else:
            print(f"  - {t.host_id} @ {t.tcp_addr}:{t.tcp_port} (will query buffer info)")

    # Parse seeds
    scatter_seed = _parse_seed_arg(args.scatter_seed, SCATTER_SEED)
    gather_seed = _parse_seed_arg(args.gather_seed, GATHER_SEED)

    # Check if using multi-NUMA mode
    num_numas = args.num_numas
    use_multi_numa = num_numas > 1

    if use_multi_numa:
        if not args.use_async:
            print("[warning] Multi-NUMA mode requires async API, enabling --async automatically")
            args.use_async = True
        
        print(f"[test] Using Multi-NUMA mode with {num_numas} NUMA nodes")
        
        is_performance_mode = args.test_mode == "performance"
        harness = MultiNumaTestHarness(
            host_id=args.host_id,
            device_name=args.device,
            targets=targets,
            min_chunk_size=args.min_chunk_size,
            max_chunk_size=args.max_chunk_size,
            num_threads=args.num_threads,
            num_numas=num_numas,
            performance_mode=is_performance_mode,
        )

        try:
            run_multi_numa_tests(harness, args, scatter_seed, gather_seed)
            print("\n[test] All tests passed!")
        finally:
            harness.close()
    else:
        # Original single-NUMA test path
        # Test mode settings
        is_performance_mode = args.test_mode == "performance"
        prepare_payload = not is_performance_mode
        verify_payload = not is_performance_mode
        reset_buffer = not is_performance_mode

        # Async mode settings
        use_async = args.use_async
        async_mode = args.async_mode
        async_timeout_ms = args.async_timeout_ms
        poll_interval_us = args.poll_interval_us

        if use_async:
            print(f"[test] Using ASYNC API (mode={async_mode}, timeout={async_timeout_ms}ms)")
        else:
            print("[test] Using SYNC API")

        # Create test harness
        harness = MPCommTestHarness(
            host_id=args.host_id,
            device_name=args.device,
            targets=targets,
            min_chunk_size=args.min_chunk_size,
            max_chunk_size=args.max_chunk_size,
            num_threads=args.num_threads,
            performance_mode=is_performance_mode,
        )

        try:
            run_scatter = args.mode in {"scatter", "both"}
            run_gather = args.mode in {"gather", "both"}
            iterations = args.iterations
            perf_tracker = PerformanceTracker() if is_performance_mode else None

            # Run scatter tests
            if run_scatter:
                mode_str = "Async" if use_async else "Sync"
                print(f"\n=== Scatter Test [{mode_str}] (seed={scatter_seed}, iterations={iterations}) ===")
                plan = harness.build_replication_plan(scatter_seed, "scatter")
                total_bytes = sum(plan.lengths)

                for i in range(iterations):
                    current_seed = scatter_seed if is_performance_mode else scatter_seed + i
                    if iterations > 1:
                        print(f"\n[scatter] Iteration {i + 1}/{iterations}")

                    if use_async:
                        if async_mode == "polling":
                            duration = harness.run_scatter_async_polling(
                                current_seed,
                                prepare_payload=prepare_payload,
                                verify=verify_payload,
                                reset=reset_buffer,
                                plan=plan if is_performance_mode else None,
                                poll_interval_us=poll_interval_us,
                            )
                        else:
                            duration = harness.run_scatter_async(
                                current_seed,
                                prepare_payload=prepare_payload,
                                verify=verify_payload,
                                reset=reset_buffer,
                                plan=plan if is_performance_mode else None,
                                timeout_ms=async_timeout_ms,
                            )
                    else:
                        duration = harness.run_scatter(
                            current_seed,
                            prepare_payload=prepare_payload,
                            verify=verify_payload,
                            reset=reset_buffer,
                            plan=plan if is_performance_mode else None,
                        )

                    if perf_tracker:
                        perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)
                        bandwidth = total_bytes / duration if duration > 0 else 0
                        duration_us = duration * 1_000_000
                        print(f"  duration={duration_us:.2f}us, bytes={_format_bytes(total_bytes)}, "
                              f"bandwidth={_format_bandwidth(bandwidth)}")

            # Run gather tests
            if run_gather:
                mode_str = "Async" if use_async else "Sync"
                print(f"\n=== Gather Test [{mode_str}] (seed={gather_seed}, iterations={iterations}) ===")
                plan = harness.build_replication_plan(gather_seed, "gather")
                total_bytes = sum(plan.lengths)

                for i in range(iterations):
                    current_seed = gather_seed if is_performance_mode else gather_seed + i
                    if iterations > 1:
                        print(f"\n[gather] Iteration {i + 1}/{iterations}")

                    if use_async:
                        if async_mode == "polling":
                            duration = harness.run_gather_async_polling(
                                current_seed,
                                prepare_payload=prepare_payload,
                                verify=verify_payload,
                                reset=reset_buffer,
                                plan=plan if is_performance_mode else None,
                                poll_interval_us=poll_interval_us,
                            )
                        else:
                            duration = harness.run_gather_async(
                                current_seed,
                                prepare_payload=prepare_payload,
                                verify=verify_payload,
                                reset=reset_buffer,
                                plan=plan if is_performance_mode else None,
                                timeout_ms=async_timeout_ms,
                            )
                    else:
                        duration = harness.run_gather(
                            current_seed,
                            prepare_payload=prepare_payload,
                            verify=verify_payload,
                            reset=reset_buffer,
                            plan=plan if is_performance_mode else None,
                        )

                    if perf_tracker:
                        perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)
                        bandwidth = total_bytes / duration if duration > 0 else 0
                        duration_us = duration * 1_000_000
                        print(f"  duration={duration_us:.2f}us, bytes={_format_bytes(total_bytes)}, "
                              f"bandwidth={_format_bandwidth(bandwidth)}")

            # Print aggregate statistics
            if perf_tracker and perf_tracker.total_bytes > 0 and perf_tracker.total_time > 0:
                avg_bandwidth = perf_tracker.average_bandwidth()
                total_time_us = perf_tracker.total_time * 1_000_000
                print(f"\n[performance] Aggregate: bytes={_format_bytes(perf_tracker.total_bytes)}, "
                      f"time={total_time_us:.2f}us, bandwidth={_format_bandwidth(avg_bandwidth)}")

            print("\n[test] All tests passed!")

        finally:
            harness.close()


if __name__ == "__main__":
    main()
