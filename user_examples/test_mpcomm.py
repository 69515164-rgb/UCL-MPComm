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


"""MPComm Test Script

Tests mp_replicate (scatter/gather/broadcast/put/get) functionality using MPComm.
This script runs on the initiator host and performs RDMA operations
to one or more target hosts.

All transfers go through the async C++ path (scatter_async / gather_async /
broadcast_async + wait_transfer or is_transfer_complete).  A single MPComm
instance is used regardless of how many NUMA buffers are allocated; the C++
layer handles multi-NIC dispatching and worker-thread binding internally.

Usage:
    # Basic scatter test (single NUMA, default NUMA 0)
    python test_mpcomm.py --mode scatter --targets target1:<target_ip>:12345

    # Gather test
    python test_mpcomm.py --mode gather --targets target1:<target_ip>:12345

    # Broadcast test (same data to all targets)
    python test_mpcomm.py --mode broadcast --targets target1:<target_ip>:12345

    # All modes (scatter + gather + broadcast + put + get)
    python test_mpcomm.py --mode all --targets target1:<target_ip>:12345

    # Put test (write to a single remote host)
    python test_mpcomm.py --mode put --targets target1:<target_ip>:12345

    # Get test (read from a single remote host)
    python test_mpcomm.py --mode get --targets target1:<target_ip>:12345

    # Polling completion mode
    python test_mpcomm.py --mode scatter --async-mode polling --targets target1:<target_ip>:12345

    # GPU source (GPUDirect RDMA via nvidia-peermem)
    python test_mpcomm.py --mode scatter --gpu 0 --targets target1:<target_ip>:12345

    # GPU performance test
    python test_mpcomm.py --mode scatter --gpu 0 --test-mode performance --iterations 10 --targets target1:<target_ip>:12345

    # Multi-NUMA buffers (single MPComm, multiple buffers on different NUMA nodes)
    python test_mpcomm.py --mode scatter --num-numas 0,1 --targets target1:<target_ip>:12345

    # Single specific NUMA node
    python test_mpcomm.py --mode scatter --num-numas 1 --targets target1:<target_ip>:12345

    # Batch mode: submit multiple async requests per NUMA per iteration
    python test_mpcomm.py --mode scatter --batch-size 4 --test-mode performance \
        --iterations 10 --targets target1:<target_ip>:12345

    # Explicit buffer info (legacy)
    python test_mpcomm.py --mode scatter --targets target1:<target_ip>:12345:0x7f1234:12345678

Environment variables:
    MPCOMM_HOST_ID: Local host identifier
    MPCOMM_DEVICE: RDMA device name
"""
import argparse
import ctypes
import ipaddress
import os
import random
import socket
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import torch

# ---------------------------------------------------------------------------
# Auto-detect mpcomm install path so the script works without PYTHONPATH.
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
    print("  cd trmt-mpcomm && sh build.sh", file=sys.stderr)
    print("  Or: export PYTHONPATH=/path/to/mpcomm-install/lib/python:$PYTHONPATH", file=sys.stderr)
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


@dataclass
class BroadcastPlan:
    """Plan for broadcast operation.

    Unlike ReplicationPlan where each target gets a different slice of the
    local buffer, broadcast sends the same local region to every target.
    """
    length: int                     # Broadcast data length (same for all targets)
    remote_addresses: List[int]     # One remote addr per target
    payload: bytes                  # Expected data (single copy)


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
    """Unified test harness for MPComm scatter/gather operations.

    Uses a **single MPComm instance** regardless of the number of NUMA
    buffers.  The C++ async layer handles multi-NIC dispatching and
    worker-thread binding internally; Python only needs to:
      1. Allocate buffers on the desired NUMA nodes (or GPU).
      2. Register each buffer with the single MPComm instance.
      3. Submit async transfers from the main thread.
      4. Wait / poll for completion from the main thread.

    Memory source modes:
      - CPU + libnuma (default): buffers on one or more NUMA nodes.
      - GPU HBM (gpu_device >= 0): single buffer on GPU,
        GPUDirect RDMA via nvidia-peermem.

    The only C++ transfer path used is:
        scatter_async / gather_async / broadcast_async
        + wait_transfer / is_transfer_complete
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        *,
        host_id: str,
        device_name: str,
        targets: List[TargetInfo],
        min_chunk_size: int,
        max_chunk_size: int,
        num_threads: int,
        numa_nodes: List[int],
        performance_mode: bool = False,
        gpu_device: int = -1,
        batch_size: int = 1,
    ) -> None:
        self.host_id = host_id
        self.device_name = device_name
        self.targets = targets
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.num_threads = num_threads
        self.performance_mode = performance_mode
        self.gpu_device = gpu_device
        self.use_gpu = gpu_device >= 0
        self.batch_size = max(1, batch_size)

        if min_chunk_size <= 0 or max_chunk_size <= 0:
            raise ValueError("Chunk sizes must be positive integers")
        if min_chunk_size > max_chunk_size:
            raise ValueError("min_chunk_size cannot exceed max_chunk_size")
        if not numa_nodes:
            raise ValueError("numa_nodes must not be empty")

        self.numa_nodes = numa_nodes
        self.num_numas = len(numa_nodes)
        self.buffer_capacity = max_chunk_size * len(targets)

        # GPU validation
        if self.use_gpu:
            if not torch.cuda.is_available():
                raise RuntimeError("--gpu requested but CUDA is not available")
            if gpu_device >= torch.cuda.device_count():
                raise RuntimeError(f"GPU device {gpu_device} not found, "
                                   f"available: {torch.cuda.device_count()}")
            torch.cuda.set_device(gpu_device)
            print(f"[test] Using GPU device {gpu_device}: "
                  f"{torch.cuda.get_device_name(gpu_device)}")

        # Load libnuma (needed for CPU NUMA allocation)
        self.libnuma = None if self.use_gpu else self._load_libnuma()

        # Single MPComm instance (C++ handles multi-NIC / multi-worker internally)
        self.comm = mpcomm.MPComm()
        ret = self.comm.init(host_id, device_name, 0)
        if ret != 0:
            raise RuntimeError(f"MPComm init failed: {ret}")
        print(f"[test] MPComm '{host_id}' initialized with "
              f"{self.comm.get_num_nics()} NICs")

        # Per-NUMA buffer resources (indexed by position in numa_nodes)
        self.local_buffer_addrs: List[int] = [0] * self.num_numas
        self._gpu_tensors: List[Optional[torch.Tensor]] = [None] * self.num_numas
        self._numa_alloc_info: List[Optional[Tuple]] = [None] * self.num_numas

        print(f"[test] Allocating buffers on NUMA nodes: {numa_nodes}")

        # Allocate and register per-NUMA buffers
        for idx, numa_node in enumerate(numa_nodes):
            if self.use_gpu:
                self._alloc_gpu_buffer(idx, numa_node)
            elif self.libnuma is not None:
                self._alloc_numa_buffer(idx, numa_node)
            else:
                self._alloc_default_buffer(idx, numa_node)

        # Connect to all targets (single MPComm instance)
        self._connect_targets()

        # Pattern / verification setup
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

    # ------------------------------------------------------------------
    # libnuma helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _load_libnuma():
        """Load libnuma library for NUMA memory allocation."""
        try:
            libnuma = ctypes.CDLL("libnuma.so.1", mode=ctypes.RTLD_GLOBAL)
            libnuma.numa_available.restype = ctypes.c_int
            libnuma.numa_alloc_onnode.argtypes = [ctypes.c_size_t, ctypes.c_int]
            libnuma.numa_alloc_onnode.restype = ctypes.c_void_p
            libnuma.numa_free.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            libnuma.numa_max_node.restype = ctypes.c_int
            if libnuma.numa_available() < 0:
                print("[test] WARNING: libnuma not available")
                return None
            return libnuma
        except OSError as e:
            print(f"[test] WARNING: Failed to load libnuma: {e}")
            return None

    # ------------------------------------------------------------------
    # Buffer allocation
    # ------------------------------------------------------------------
    def _alloc_gpu_buffer(self, idx: int, numa_node: int) -> None:
        """Allocate buffer on GPU HBM and register with MPComm."""
        tensor = torch.empty(self.buffer_capacity, dtype=torch.uint8,
                             device=f"cuda:{self.gpu_device}")
        if not tensor.is_contiguous():
            tensor = tensor.contiguous()
        addr = tensor.data_ptr()
        ret = self.comm.register_memory(addr, self.buffer_capacity)
        if ret != 0:
            raise RuntimeError(f"Failed to register GPU memory: {ret}")
        self._gpu_tensors[idx] = tensor
        self.local_buffer_addrs[idx] = addr
        self._numa_alloc_info[idx] = (0, 0, False)
        print(f"[test] Buffer {idx}: GPU:{self.gpu_device} at "
              f"0x{addr:x} ({_format_bytes(self.buffer_capacity)})")

    def _alloc_numa_buffer(self, idx: int, numa_node: int) -> None:
        """Allocate buffer on a specific NUMA node via libnuma and register."""
        max_node = self.libnuma.numa_max_node()
        if numa_node > max_node:
            raise RuntimeError(f"NUMA node {numa_node} exceeds max {max_node}")
        page_size = 4096
        alloc_size = ((self.buffer_capacity + page_size - 1) // page_size) * page_size
        ptr = self.libnuma.numa_alloc_onnode(alloc_size, numa_node)
        if not ptr:
            raise RuntimeError(f"numa_alloc_onnode failed for NUMA {numa_node}")
        ctypes.memset(ptr, 0, alloc_size)
        ret = self.comm.register_memory(ptr, self.buffer_capacity)
        if ret != 0:
            self.libnuma.numa_free(ptr, alloc_size)
            raise RuntimeError(f"Failed to register NUMA memory: {ret}")
        self.local_buffer_addrs[idx] = ptr
        self._numa_alloc_info[idx] = (ptr, alloc_size, True)
        print(f"[test] Buffer {idx}: NUMA {numa_node} at 0x{ptr:x} "
              f"({_format_bytes(alloc_size)})")

    def _alloc_default_buffer(self, idx: int, numa_node: int) -> None:
        """Fallback: allocate via PyTorch tensor (NUMA placement not guaranteed)."""
        tensor = torch.empty(self.buffer_capacity, dtype=torch.uint8)
        if not tensor.is_contiguous():
            tensor = tensor.contiguous()
        tensor.fill_(0)
        addr = tensor.data_ptr()
        ret = self.comm.register_memory(addr, self.buffer_capacity)
        if ret != 0:
            raise RuntimeError(f"Failed to register memory: {ret}")
        self._gpu_tensors[idx] = tensor  # keep reference
        self.local_buffer_addrs[idx] = addr
        self._numa_alloc_info[idx] = (0, 0, False)
        print(f"[test] Buffer {idx}: at 0x{addr:x} "
              f"({_format_bytes(self.buffer_capacity)}) "
              f"[WARNING: may not be on NUMA {numa_node}]")

    # ------------------------------------------------------------------
    # Target connection (single MPComm instance)
    # ------------------------------------------------------------------
    def _connect_targets(self) -> None:
        """Connect the single MPComm instance to all targets and fetch rkeys."""
        for target in self.targets:
            print(f"[test] Connecting to {target.host_id}...")
            ret = self.comm.connect(target.host_id, target.tcp_addr, target.tcp_port)
            if ret != 0:
                raise RuntimeError(f"Connect to {target.host_id} failed: {ret}")

            if not target.is_complete():
                # Try multi-buffer API first
                try:
                    all_buffers = self.comm.query_remote_buffers(
                        target.host_id, target.tcp_addr, target.tcp_port
                    )
                except AttributeError:
                    all_buffers = None

                if all_buffers and 'buffers' in all_buffers and all_buffers['buffers']:
                    target.remote_buffers = all_buffers['buffers']
                    first_buf = all_buffers['buffers'][0]
                    target.remote_addr = first_buf['addr']
                    target.rkeys = first_buf['rkeys']
                    print(f"[test] Got {len(all_buffers['buffers'])} "
                          f"buffer(s) from {target.host_id}")
                else:
                    buffer_info = self.comm.query_remote_buffer(
                        target.host_id, target.tcp_addr, target.tcp_port
                    )
                    if not buffer_info:
                        raise RuntimeError(f"Query buffer from {target.host_id} failed")
                    target.remote_addr = buffer_info['addr']
                    target.rkeys = buffer_info['rkeys']

            # Update rkeys (use first available buffer's rkeys)
            rkeys_to_use = target.rkeys
            ret = self.comm.update_remote_memory_info(target.host_id, rkeys_to_use)
            if ret != 0:
                raise RuntimeError(f"Update rkeys for {target.host_id} failed: {ret}")
            print(f"[test] Connected to {target.host_id}, rkeys={rkeys_to_use}")

    # ------------------------------------------------------------------
    # Buffer read / write helpers
    # ------------------------------------------------------------------
    def _reset_all_buffers(self) -> None:
        """Reset every NUMA buffer to the base IPv4 pattern."""
        for idx in range(self.num_numas):
            self._reset_buffer(idx)

    def _reset_buffer(self, idx: int) -> None:
        """Reset a single NUMA buffer to the base IPv4 pattern."""
        if self.use_gpu:
            tensor = self._gpu_tensors[idx]
            pattern_tensor = torch.frombuffer(
                bytearray(self._base_buffer_pattern), dtype=torch.uint8
            )
            tensor.copy_(pattern_tensor)
        else:
            ret = self.comm.write_bytes_to_buffer(
                self.local_buffer_addrs[idx],
                self._base_buffer_pattern,
                len(self._base_buffer_pattern),
            )
            if ret != 0:
                raise RuntimeError(f"Failed to reset buffer idx={idx}")

    def _write_chunk(self, idx: int, offset: int, payload: bytes) -> None:
        """Write *payload* into NUMA buffer *idx* at *offset*."""
        if self.use_gpu:
            tensor = self._gpu_tensors[idx]
            pt = torch.frombuffer(bytearray(payload), dtype=torch.uint8)
            tensor[offset:offset + len(payload)].copy_(pt)
        else:
            addr = self.local_buffer_addrs[idx] + offset
            ret = self.comm.write_bytes_to_buffer(addr, payload, len(payload))
            if ret != 0:
                raise RuntimeError(f"Failed to write chunk idx={idx} offset={offset}")

    def _clear_chunk(self, idx: int, offset: int, length: int) -> None:
        """Zero out *length* bytes in NUMA buffer *idx* starting at *offset*."""
        if self.use_gpu:
            self._gpu_tensors[idx][offset:offset + length].zero_()
        else:
            addr = self.local_buffer_addrs[idx] + offset
            ret = self.comm.write_bytes_to_buffer(addr, bytes(length), length)
            if ret != 0:
                raise RuntimeError(f"Failed to clear chunk idx={idx} offset={offset}")

    def _read_bytes(self, idx: int, offset: int, length: int) -> bytes:
        """Read *length* bytes from NUMA buffer *idx* at *offset*."""
        if length <= 0:
            return b""
        if self.use_gpu:
            cpu_slice = self._gpu_tensors[idx][offset:offset + length].cpu()
            return bytes(cpu_slice.numpy().tobytes())
        return self.comm.read_bytes_from_buffer(
            self.local_buffer_addrs[idx] + offset, length
        )

    # ------------------------------------------------------------------
    # Replication plan (scatter / gather)
    # ------------------------------------------------------------------
    def build_replication_plan(self, seed: int, mode: str = "scatter") -> ReplicationPlan:
        """Build a replication plan with random chunk sizes."""
        if mode not in {"scatter", "gather"}:
            raise ValueError(f"Unsupported mode: {mode}")

        rng = random.Random(seed)
        lengths = [rng.randint(self.min_chunk_size, self.max_chunk_size)
                    for _ in self.targets]

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

    # ------------------------------------------------------------------
    # Broadcast plan
    # ------------------------------------------------------------------
    def build_broadcast_plan(self, seed: int) -> BroadcastPlan:
        """Build a broadcast plan with random data length.

        Broadcast sends the SAME data to every target.  The length is
        randomly chosen between min_chunk_size and max_chunk_size.
        """
        rng = random.Random(seed)
        length = rng.randint(self.min_chunk_size, self.max_chunk_size)

        remote_addresses = [t.remote_addr for t in self.targets]

        payload = b""
        if not self.performance_mode:
            payload = self._base_buffer_pattern[:length]

        return BroadcastPlan(
            length=length,
            remote_addresses=remote_addresses,
            payload=payload,
        )

    def get_remote_addresses_for_numa(self, idx: int) -> List[int]:
        """Return per-target remote addresses for NUMA index *idx*."""
        numa_node = self.numa_nodes[idx]
        addrs = []
        for target in self.targets:
            if target.remote_buffers:
                buf = target.get_buffer_for_numa(numa_node)
                addrs.append(buf['addr'])
            else:
                addrs.append(target.remote_addr)
        return addrs

    # ------------------------------------------------------------------
    # Unified scatter / gather  (single C++ path)
    # ------------------------------------------------------------------
    def run_scatter(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        timeout_ms: int = -1,
        poll_interval_us: int = 0,
    ) -> Tuple[float, int, List[float]]:
        """Scatter local buffers to remote targets (RDMA WRITE).

        Submits one async transfer per NUMA buffer from the main thread,
        then waits for all to complete.  Completion mode is determined by
        *poll_interval_us*: ``0`` means blocking ``wait_transfer``,
        ``> 0`` means polling with that sleep interval.

        Returns:
            (wall_duration, total_bytes, per_numa_durations)
        """
        return self._run_transfer(
            "scatter", seed,
            prepare_payload=prepare_payload,
            verify=verify,
            reset=reset,
            plan=plan,
            timeout_ms=timeout_ms,
            poll_interval_us=poll_interval_us,
        )

    def run_gather(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[ReplicationPlan] = None,
        timeout_ms: int = -1,
        poll_interval_us: int = 0,
    ) -> Tuple[float, int, List[float]]:
        """Gather from remote targets into local buffers (RDMA READ).

        Returns:
            (wall_duration, total_bytes, per_numa_durations)
        """
        return self._run_transfer(
            "gather", seed,
            prepare_payload=prepare_payload,
            verify=verify,
            reset=reset,
            plan=plan,
            timeout_ms=timeout_ms,
            poll_interval_us=poll_interval_us,
        )

    # ------------------------------------------------------------------
    # Core transfer implementation
    # ------------------------------------------------------------------
    def _run_transfer(
        self,
        direction: str,
        seed: int,
        *,
        prepare_payload: bool,
        verify: bool,
        reset: bool,
        plan: Optional[ReplicationPlan],
        timeout_ms: int,
        poll_interval_us: int,
    ) -> Tuple[float, int, List[float]]:
        """Submit async transfers for all NUMA buffers, then wait for all.

        All operations happen on the main thread.  The C++ async layer
        dispatches work to its own internal worker threads.

        When batch_size > 1, submits batch_size async requests per NUMA
        buffer per iteration, then waits for all to complete. The total
        data volume is multiplied by batch_size.
        """
        if plan is None:
            plan = self.build_replication_plan(seed, mode=direction)

        host_list = [t.host_id for t in self.targets]
        batch_size = self.batch_size
        total_bytes = sum(plan.lengths) * self.num_numas * batch_size
        use_polling = poll_interval_us > 0

        # Prepare buffers
        for numa_idx in range(self.num_numas):
            if prepare_payload:
                if direction == "scatter":
                    for offset, payload in zip(plan.offsets, plan.payloads):
                        if payload:
                            self._write_chunk(numa_idx, offset, payload)
                else:  # gather: clear
                    for offset, length in zip(plan.offsets, plan.lengths):
                        self._clear_chunk(numa_idx, offset, length)

        # Submit batch_size async requests per NUMA buffer from main thread
        # batch_handles[b] = [(numa_idx, handle), ...] for batch request b
        batch_handles: List[List[Tuple[int, int]]] = []
        wall_start = time.perf_counter()

        for b in range(batch_size):
            handles_for_batch: List[Tuple[int, int]] = []
            for numa_idx in range(self.num_numas):
                local_addr = self.local_buffer_addrs[numa_idx]
                remote_addrs = self.get_remote_addresses_for_numa(numa_idx)

                if direction == "scatter":
                    handle = self.comm.scatter_async(
                        local_addr, host_list, remote_addrs, plan.lengths)
                else:
                    handle = self.comm.gather_async(
                        local_addr, host_list, remote_addrs, plan.lengths)

                if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                    # Release already-submitted handles before raising
                    for prev_handles in batch_handles:
                        for _, h in prev_handles:
                            self.comm.release_transfer(h)
                    for _, h in handles_for_batch:
                        self.comm.release_transfer(h)
                    raise RuntimeError(
                        f"{direction}_async failed for buffer {numa_idx} "
                        f"batch {b} (NUMA {self.numa_nodes[numa_idx]})")

                handles_for_batch.append((numa_idx, handle))
            batch_handles.append(handles_for_batch)

        # Wait for all transfers to complete
        total_polls = 0

        if use_polling:
            # Flatten all handles for polling
            all_handles = [(b, numa_idx, handle)
                           for b, bh in enumerate(batch_handles)
                           for numa_idx, handle in bh]
            pending = set(range(len(all_handles)))
            poll_counts = {i: 0 for i in range(len(all_handles))}
            while pending:
                done = set()
                for i in list(pending):
                    _, _, handle = all_handles[i]
                    poll_counts[i] += 1
                    if self.comm.is_transfer_complete(handle):
                        done.add(i)
                pending -= done
                if pending:
                    time.sleep(poll_interval_us / 1_000_000)
            total_polls = sum(poll_counts.values())
        else:
            # Blocking wait for each handle
            for b_handles in batch_handles:
                for numa_idx, handle in b_handles:
                    ret = self.comm.wait_transfer(handle, timeout_ms)
                    if ret != 0:
                        # Release all handles before raising
                        for bh in batch_handles:
                            for _, h in bh:
                                self.comm.release_transfer(h)
                        raise RuntimeError(
                            f"wait_transfer failed for buffer {numa_idx} "
                            f"(NUMA {self.numa_nodes[numa_idx]}): {ret}")

        wall_duration = time.perf_counter() - wall_start

        # Collect per-NUMA results: take max elapsed_ms across all batch requests
        per_numa_max_ms: Dict[int, float] = {i: 0.0 for i in range(self.num_numas)}
        for b_handles in batch_handles:
            for numa_idx, handle in b_handles:
                result = self.comm.get_transfer_result(handle)
                self.comm.release_transfer(handle)
                if result["error_code"] != 0:
                    raise RuntimeError(
                        f"Transfer error on buffer {numa_idx} "
                        f"(NUMA {self.numa_nodes[numa_idx]}): {result['error_code']}")
                elapsed = result["elapsed_ms"]
                if elapsed > per_numa_max_ms[numa_idx]:
                    per_numa_max_ms[numa_idx] = elapsed

        per_numa_durations = [
            per_numa_max_ms.get(i, 0) / 1000.0
            for i in range(self.num_numas)
        ]

        if use_polling:
            print(f"  [async polling] completed after {total_polls} total polls")

        # Verification (only meaningful for batch_size=1 since batch>1 overwrites same buffer)
        if verify and batch_size == 1:
            for numa_idx in range(self.num_numas):
                if direction == "scatter":
                    self._verify_scatter(numa_idx, plan)
                else:
                    self._verify_gather(numa_idx, plan)

        if reset:
            self._reset_all_buffers()

        return wall_duration, total_bytes, per_numa_durations

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------
    def run_broadcast(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        plan: Optional[BroadcastPlan] = None,
        timeout_ms: int = -1,
        poll_interval_us: int = 0,
    ) -> Tuple[float, int, List[float]]:
        """Broadcast local buffer to all remote targets (RDMA WRITE).

        Each NUMA buffer broadcasts the SAME data to every target.
        Returns:
            (wall_duration, total_bytes, per_numa_durations)
        """
        if plan is None:
            plan = self.build_broadcast_plan(seed)

        host_list = [t.host_id for t in self.targets]
        batch_size = self.batch_size
        # Total bytes = length * num_targets * num_numas * batch_size
        total_bytes = plan.length * len(self.targets) * self.num_numas * batch_size
        use_polling = poll_interval_us > 0

        # Prepare buffers – write the broadcast payload at offset 0
        for numa_idx in range(self.num_numas):
            if prepare_payload and plan.payload:
                self._write_chunk(numa_idx, 0, plan.payload)

        # Submit batch_size broadcast_async requests per NUMA buffer
        batch_handles: List[List[Tuple[int, int]]] = []
        wall_start = time.perf_counter()

        for b in range(batch_size):
            handles_for_batch: List[Tuple[int, int]] = []
            for numa_idx in range(self.num_numas):
                local_addr = self.local_buffer_addrs[numa_idx]
                remote_addrs = self.get_remote_addresses_for_numa(numa_idx)

                handle = self.comm.broadcast_async(
                    local_addr, plan.length, host_list, remote_addrs)

                if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                    for prev_handles in batch_handles:
                        for _, h in prev_handles:
                            self.comm.release_transfer(h)
                    for _, h in handles_for_batch:
                        self.comm.release_transfer(h)
                    raise RuntimeError(
                        f"broadcast_async failed for buffer {numa_idx} "
                        f"batch {b} (NUMA {self.numa_nodes[numa_idx]})")

                handles_for_batch.append((numa_idx, handle))
            batch_handles.append(handles_for_batch)

        # Wait for completion
        total_polls = 0

        if use_polling:
            all_handles = [(b, numa_idx, handle)
                           for b, bh in enumerate(batch_handles)
                           for numa_idx, handle in bh]
            pending = set(range(len(all_handles)))
            poll_counts = {i: 0 for i in range(len(all_handles))}
            while pending:
                done = set()
                for i in list(pending):
                    _, _, handle = all_handles[i]
                    poll_counts[i] += 1
                    if self.comm.is_transfer_complete(handle):
                        done.add(i)
                pending -= done
                if pending:
                    time.sleep(poll_interval_us / 1_000_000)
            total_polls = sum(poll_counts.values())
        else:
            for b_handles in batch_handles:
                for numa_idx, handle in b_handles:
                    ret = self.comm.wait_transfer(handle, timeout_ms)
                    if ret != 0:
                        for bh in batch_handles:
                            for _, h in bh:
                                self.comm.release_transfer(h)
                        raise RuntimeError(
                            f"wait_transfer failed for buffer {numa_idx} "
                            f"(NUMA {self.numa_nodes[numa_idx]}): {ret}")

        wall_duration = time.perf_counter() - wall_start

        # Collect per-NUMA results: take max elapsed_ms across all batch requests
        per_numa_max_ms: Dict[int, float] = {i: 0.0 for i in range(self.num_numas)}
        for b_handles in batch_handles:
            for numa_idx, handle in b_handles:
                result = self.comm.get_transfer_result(handle)
                self.comm.release_transfer(handle)
                if result["error_code"] != 0:
                    raise RuntimeError(
                        f"Transfer error on buffer {numa_idx} "
                        f"(NUMA {self.numa_nodes[numa_idx]}): {result['error_code']}")
                elapsed = result["elapsed_ms"]
                if elapsed > per_numa_max_ms[numa_idx]:
                    per_numa_max_ms[numa_idx] = elapsed

        per_numa_durations = [
            per_numa_max_ms.get(i, 0) / 1000.0
            for i in range(self.num_numas)
        ]

        if use_polling:
            print(f"  [async polling] completed after {total_polls} total polls")

        # Verification (only meaningful for batch_size=1)
        if verify and batch_size == 1:
            for numa_idx in range(self.num_numas):
                self._verify_broadcast(numa_idx, plan)

        if reset:
            self._reset_all_buffers()

        return wall_duration, total_bytes, per_numa_durations

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def _verify_broadcast(self, idx: int, plan: BroadcastPlan) -> None:
        """Verify broadcast by reading back from each remote via gather_async.

        For each target we issue a gather of *plan.length* bytes from the
        remote address, then compare with the expected payload.
        """
        numa_node = self.numa_nodes[idx]
        host_list = [t.host_id for t in self.targets]
        remote_addrs = self.get_remote_addresses_for_numa(idx)

        # Build a gather with the same length for every target, writing
        # results sequentially into our local buffer.
        lengths = [plan.length] * len(self.targets)
        offsets: List[int] = []
        cursor = 0
        for l in lengths:
            offsets.append(cursor)
            cursor += l

        # Clear the local region that will receive the gather data
        for offset, length in zip(offsets, lengths):
            self._clear_chunk(idx, offset, length)

        handle = self.comm.gather_async(
            self.local_buffer_addrs[idx], host_list,
            remote_addrs, lengths,
        )
        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            print(f"[broadcast verify NUMA {numa_node}] gather_async failed",
                  file=sys.stderr)
            return
        ret = self.comm.wait_transfer(handle)
        self.comm.release_transfer(handle)
        if ret != 0:
            print(f"[broadcast verify NUMA {numa_node}] read-back failed",
                  file=sys.stderr)
            return

        for i, (offset, length) in enumerate(zip(offsets, lengths)):
            if length <= 0:
                continue
            expected = plan.payload
            actual = self._read_bytes(idx, offset, length)
            if actual != expected:
                print(f"[broadcast verify NUMA {numa_node}] "
                      f"target={self.targets[i].host_id} "
                      f"expected={_preview_hex(expected)} "
                      f"actual={_preview_hex(actual)}")
                raise AssertionError(
                    f"Broadcast verification failed NUMA {numa_node} "
                    f"target {self.targets[i].host_id}")
            print(f"[broadcast verify NUMA {numa_node}] "
                  f"target={self.targets[i].host_id} len={length}B OK")

    def _verify_scatter(self, idx: int, plan: ReplicationPlan) -> None:
        """Verify scatter by reading back from remotes via gather_async."""
        numa_node = self.numa_nodes[idx]
        host_list = [t.host_id for t in self.targets]
        remote_addrs = self.get_remote_addresses_for_numa(idx)

        for offset, length in zip(plan.offsets, plan.lengths):
            self._clear_chunk(idx, offset, length)

        handle = self.comm.gather_async(
            self.local_buffer_addrs[idx], host_list,
            remote_addrs, plan.lengths,
        )
        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            print(f"[scatter verify NUMA {numa_node}] gather_async failed",
                  file=sys.stderr)
            return
        ret = self.comm.wait_transfer(handle)
        self.comm.release_transfer(handle)
        if ret != 0:
            print(f"[scatter verify NUMA {numa_node}] read-back failed",
                  file=sys.stderr)
            return

        for i, (offset, length) in enumerate(zip(plan.offsets, plan.lengths)):
            if length <= 0:
                continue
            expected = plan.payloads[i]
            actual = self._read_bytes(idx, offset, length)
            if actual != expected:
                print(f"[scatter verify NUMA {numa_node}] "
                      f"target={self.targets[i].host_id} "
                      f"expected={_preview_hex(expected)} "
                      f"actual={_preview_hex(actual)}")
                raise AssertionError(
                    f"Scatter verification failed NUMA {numa_node} "
                    f"target {self.targets[i].host_id}")
            print(f"[scatter verify NUMA {numa_node}] "
                  f"target={self.targets[i].host_id} len={length}B OK")

    def _verify_gather(self, idx: int, plan: ReplicationPlan) -> None:
        """Verify gather by comparing local buffer with expected pattern."""
        numa_node = self.numa_nodes[idx]
        for i, (offset, length) in enumerate(zip(plan.offsets, plan.lengths)):
            if length <= 0:
                continue
            expected = plan.payloads[i]
            actual = self._read_bytes(idx, offset, length)
            if actual != expected:
                print(f"[gather verify NUMA {numa_node}] "
                      f"target={self.targets[i].host_id} "
                      f"expected={_preview_hex(expected)} "
                      f"actual={_preview_hex(actual)}")
                raise AssertionError(
                    f"Gather verification failed NUMA {numa_node} "
                    f"target {self.targets[i].host_id}")
            print(f"[gather verify NUMA {numa_node}] "
                  f"target={self.targets[i].host_id} len={length}B OK")

    # ------------------------------------------------------------------
    # Put / Get (point-to-point)
    # ------------------------------------------------------------------
    def run_put(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        timeout_ms: int = -1,
        poll_interval_us: int = 0,
    ) -> Tuple[float, int, List[float]]:
        """Put local data to a single remote host (RDMA WRITE).

        For each NUMA buffer, writes a random-sized chunk from local buffer
        to a randomly chosen target's remote address using put_async.

        Returns:
            (wall_duration, total_bytes, per_numa_durations)
        """
        rng = random.Random(seed)
        length = rng.randint(self.min_chunk_size, self.max_chunk_size)
        target = self.targets[rng.randint(0, len(self.targets) - 1)]
        batch_size = self.batch_size
        use_polling = poll_interval_us > 0

        # Build expected payload
        payload = b""
        if not self.performance_mode:
            payload = self._base_buffer_pattern[:length]

        total_bytes = length * self.num_numas * batch_size

        # Prepare buffers
        for numa_idx in range(self.num_numas):
            if prepare_payload and payload:
                self._write_chunk(numa_idx, 0, payload)

        # Submit batch_size put_async requests per NUMA buffer
        batch_handles: List[List[Tuple[int, int]]] = []
        wall_start = time.perf_counter()

        for b in range(batch_size):
            handles_for_batch: List[Tuple[int, int]] = []
            for numa_idx in range(self.num_numas):
                local_addr = self.local_buffer_addrs[numa_idx]
                if target.remote_buffers:
                    buf = target.get_buffer_for_numa(self.numa_nodes[numa_idx])
                    remote_addr = buf['addr']
                else:
                    remote_addr = target.remote_addr

                handle = self.comm.put_async(
                    local_addr, target.host_id, remote_addr, length)

                if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                    for prev_handles in batch_handles:
                        for _, h in prev_handles:
                            self.comm.release_transfer(h)
                    for _, h in handles_for_batch:
                        self.comm.release_transfer(h)
                    raise RuntimeError(
                        f"put_async failed for buffer {numa_idx} "
                        f"batch {b} (NUMA {self.numa_nodes[numa_idx]})")
                handles_for_batch.append((numa_idx, handle))
            batch_handles.append(handles_for_batch)

        # Wait for completion
        if use_polling:
            all_handles = [(b, numa_idx, handle)
                           for b, bh in enumerate(batch_handles)
                           for numa_idx, handle in bh]
            pending = set(range(len(all_handles)))
            while pending:
                done = set()
                for i in list(pending):
                    _, _, handle = all_handles[i]
                    if self.comm.is_transfer_complete(handle):
                        done.add(i)
                pending -= done
                if pending:
                    time.sleep(poll_interval_us / 1_000_000)
        else:
            for b_handles in batch_handles:
                for numa_idx, handle in b_handles:
                    ret = self.comm.wait_transfer(handle, timeout_ms)
                    if ret != 0:
                        for bh in batch_handles:
                            for _, h in bh:
                                self.comm.release_transfer(h)
                        raise RuntimeError(
                            f"wait_transfer failed for put buffer {numa_idx}: {ret}")

        wall_duration = time.perf_counter() - wall_start

        per_numa_max_ms: Dict[int, float] = {i: 0.0 for i in range(self.num_numas)}
        for b_handles in batch_handles:
            for numa_idx, handle in b_handles:
                result = self.comm.get_transfer_result(handle)
                self.comm.release_transfer(handle)
                if result["error_code"] != 0:
                    raise RuntimeError(
                        f"Put transfer error on buffer {numa_idx}: {result['error_code']}")
                elapsed = result["elapsed_ms"]
                if elapsed > per_numa_max_ms[numa_idx]:
                    per_numa_max_ms[numa_idx] = elapsed

        per_numa_durations = [
            per_numa_max_ms.get(i, 0) / 1000.0
            for i in range(self.num_numas)
        ]

        # Verify: read back from remote via get_async and compare (only for batch_size=1)
        if verify and batch_size == 1:
            for numa_idx in range(self.num_numas):
                self._verify_put(numa_idx, target, length, payload)

        if reset:
            self._reset_all_buffers()

        return wall_duration, total_bytes, per_numa_durations

    def run_get(
        self,
        seed: int,
        *,
        prepare_payload: bool = True,
        verify: bool = True,
        reset: bool = True,
        timeout_ms: int = -1,
        poll_interval_us: int = 0,
    ) -> Tuple[float, int, List[float]]:
        """Get data from a single remote host to local buffer (RDMA READ).

        For each NUMA buffer, reads a random-sized chunk from a randomly
        chosen target's remote address into local buffer using get_async.

        Returns:
            (wall_duration, total_bytes, per_numa_durations)
        """
        rng = random.Random(seed)
        length = rng.randint(self.min_chunk_size, self.max_chunk_size)
        target = self.targets[rng.randint(0, len(self.targets) - 1)]
        batch_size = self.batch_size
        use_polling = poll_interval_us > 0

        total_bytes = length * self.num_numas * batch_size

        # Clear local buffers before get
        for numa_idx in range(self.num_numas):
            if prepare_payload:
                self._clear_chunk(numa_idx, 0, length)

        # Submit batch_size get_async requests per NUMA buffer
        batch_handles: List[List[Tuple[int, int]]] = []
        wall_start = time.perf_counter()

        for b in range(batch_size):
            handles_for_batch: List[Tuple[int, int]] = []
            for numa_idx in range(self.num_numas):
                local_addr = self.local_buffer_addrs[numa_idx]
                if target.remote_buffers:
                    buf = target.get_buffer_for_numa(self.numa_nodes[numa_idx])
                    remote_addr = buf['addr']
                else:
                    remote_addr = target.remote_addr

                handle = self.comm.get_async(
                    local_addr, target.host_id, remote_addr, length)

                if handle == mpcomm.INVALID_TRANSFER_HANDLE:
                    for prev_handles in batch_handles:
                        for _, h in prev_handles:
                            self.comm.release_transfer(h)
                    for _, h in handles_for_batch:
                        self.comm.release_transfer(h)
                    raise RuntimeError(
                        f"get_async failed for buffer {numa_idx} "
                        f"batch {b} (NUMA {self.numa_nodes[numa_idx]})")
                handles_for_batch.append((numa_idx, handle))
            batch_handles.append(handles_for_batch)

        # Wait for completion
        if use_polling:
            all_handles = [(b, numa_idx, handle)
                           for b, bh in enumerate(batch_handles)
                           for numa_idx, handle in bh]
            pending = set(range(len(all_handles)))
            while pending:
                done = set()
                for i in list(pending):
                    _, _, handle = all_handles[i]
                    if self.comm.is_transfer_complete(handle):
                        done.add(i)
                pending -= done
                if pending:
                    time.sleep(poll_interval_us / 1_000_000)
        else:
            for b_handles in batch_handles:
                for numa_idx, handle in b_handles:
                    ret = self.comm.wait_transfer(handle, timeout_ms)
                    if ret != 0:
                        for bh in batch_handles:
                            for _, h in bh:
                                self.comm.release_transfer(h)
                        raise RuntimeError(
                            f"wait_transfer failed for get buffer {numa_idx}: {ret}")

        wall_duration = time.perf_counter() - wall_start

        per_numa_max_ms: Dict[int, float] = {i: 0.0 for i in range(self.num_numas)}
        for b_handles in batch_handles:
            for numa_idx, handle in b_handles:
                result = self.comm.get_transfer_result(handle)
                self.comm.release_transfer(handle)
                if result["error_code"] != 0:
                    raise RuntimeError(
                        f"Get transfer error on buffer {numa_idx}: {result['error_code']}")
                elapsed = result["elapsed_ms"]
                if elapsed > per_numa_max_ms[numa_idx]:
                    per_numa_max_ms[numa_idx] = elapsed

        per_numa_durations = [
            per_numa_max_ms.get(i, 0) / 1000.0
            for i in range(self.num_numas)
        ]

        # Verify: compare local data with expected remote pattern (only for batch_size=1)
        if verify and batch_size == 1:
            for numa_idx in range(self.num_numas):
                self._verify_get(numa_idx, target, length)

        if reset:
            self._reset_all_buffers()

        return wall_duration, total_bytes, per_numa_durations

    def _verify_put(self, idx: int, target: TargetInfo,
                    length: int, expected: bytes) -> None:
        """Verify put by reading back from remote via get_async and comparing."""
        numa_node = self.numa_nodes[idx]
        if target.remote_buffers:
            buf = target.get_buffer_for_numa(numa_node)
            remote_addr = buf['addr']
        else:
            remote_addr = target.remote_addr

        # Clear local region, then read back
        self._clear_chunk(idx, 0, length)
        handle = self.comm.get_async(
            self.local_buffer_addrs[idx], target.host_id, remote_addr, length)
        if handle == mpcomm.INVALID_TRANSFER_HANDLE:
            print(f"[put verify NUMA {numa_node}] get_async failed", file=sys.stderr)
            return
        ret = self.comm.wait_transfer(handle)
        self.comm.release_transfer(handle)
        if ret != 0:
            print(f"[put verify NUMA {numa_node}] read-back failed", file=sys.stderr)
            return

        actual = self._read_bytes(idx, 0, length)
        if actual != expected:
            print(f"[put verify NUMA {numa_node}] "
                  f"target={target.host_id} "
                  f"expected={_preview_hex(expected)} "
                  f"actual={_preview_hex(actual)}")
            raise AssertionError(
                f"Put verification failed NUMA {numa_node} "
                f"target {target.host_id}")
        print(f"[put verify NUMA {numa_node}] "
              f"target={target.host_id} len={length}B OK")

    def _verify_get(self, idx: int, target: TargetInfo, length: int) -> None:
        """Verify get by comparing local data with expected remote pattern."""
        numa_node = self.numa_nodes[idx]
        # Remote buffer contains IPv4 pattern of the target host
        target_ip_bytes = _resolve_ipv4_bytes(target.host_id)
        expected = _build_ipv4_pattern(target_ip_bytes, length)
        actual = self._read_bytes(idx, 0, length)
        if actual != expected:
            print(f"[get verify NUMA {numa_node}] "
                  f"target={target.host_id} "
                  f"expected={_preview_hex(expected)} "
                  f"actual={_preview_hex(actual)}")
            raise AssertionError(
                f"Get verification failed NUMA {numa_node} "
                f"target {target.host_id}")
        print(f"[get verify NUMA {numa_node}] "
              f"target={target.host_id} len={length}B OK")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Release all resources."""
        for idx in range(self.num_numas):
            addr = self.local_buffer_addrs[idx]
            alloc_info = self._numa_alloc_info[idx]

            if addr and self.comm:
                self.comm.unregister_memory(addr)
            if alloc_info:
                ptr, alloc_size, is_numa = alloc_info
                if is_numa and self.libnuma and ptr:
                    self.libnuma.numa_free(ptr, alloc_size)

        if self.comm:
            self.comm.shutdown()
            self.comm = None

        self.local_buffer_addrs = [0] * self.num_numas
        self._gpu_tensors = [None] * self.num_numas
        self._numa_alloc_info = [None] * self.num_numas


# Default seeds (base36 encoded)
SCATTER_SEED = int("5CATT3R", 36)
GATHER_SEED = int("6A7H3R", 36)
BROADCAST_SEED = int("BR0ADCA", 36)
PUT_SEED = int("PU7S33D", 36)
GET_SEED = int("G37S33D", 36)


def parse_target(target_str: str) -> TargetInfo:
    """
    Parse target string in format:
        host_id:tcp_addr:tcp_port[:remote_addr:rkey1,rkey2,...]

    If remote_addr and rkeys are not provided, they will be queried from remote.

    Examples:
        # Auto-query buffer info (recommended)
        target1:<target_ip>:12345

        # Explicit buffer info (legacy)
        target1:<target_ip>:12345:0x7f1234000000:12345678,87654321
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
    # Basic scatter (single NUMA 0, wait completion)
    python test_mpcomm.py --mode scatter --targets target1:<target_ip>:12345

    # Broadcast (same data to all targets)
    python test_mpcomm.py --mode broadcast --targets target1:<target_ip>:12345

    # All modes (scatter + gather + broadcast)
    python test_mpcomm.py --mode all --targets target1:<target_ip>:12345

    # Polling completion mode
    python test_mpcomm.py --mode scatter --async-mode polling --targets target1:<target_ip>:12345

    # GPU source scatter (GPUDirect RDMA via nvidia-peermem)
    python test_mpcomm.py --mode scatter --gpu 0 --targets target1:<target_ip>:12345

    # GPU performance test
    python test_mpcomm.py --mode scatter --gpu 0 --test-mode performance --iterations 10 \\
        --targets target1:<target_ip>:12345

    # Multi-NUMA (single MPComm, multiple buffers on different NUMA nodes)
    python test_mpcomm.py --mode scatter --num-numas 0,1 --targets target1:<target_ip>:12345

    # Single specific NUMA node
    python test_mpcomm.py --mode scatter --num-numas 1 --targets target1:<target_ip>:12345

    # Batch mode (multiple concurrent async requests per NUMA per iteration)
    python test_mpcomm.py --mode scatter --batch-size 4 --test-mode performance --iterations 10 \\
        --targets target1:<target_ip>:12345

    # Multiple targets
    python test_mpcomm.py --mode both \\
        --targets target1:<target_ip>:12345 \\
        --targets target2:<target2_ip>:12345

    # Broadcast performance test
    python test_mpcomm.py --mode broadcast --test-mode performance --iterations 10 \\
        --targets target1:<target_ip>:12345
""",
    )

    parser.add_argument(
        "--mode",
        choices=["scatter", "gather", "broadcast", "put", "get", "both", "all"],
        default="both",
        help="Operation mode: scatter, gather, broadcast, put, get, both (scatter+gather), "
             "or all (scatter+gather+broadcast+put+get). Default: both",
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
        help="Target in format host_id:tcp_addr:tcp_port[:remote_addr:rkey1,rkey2,...]. "
             "Multiple targets can be comma-separated, e.g. 'target1:ip1:port1,target2:ip2:port2'",
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
        type=str,
        default="",
        help="NUMA nodes to use, e.g. '0', '1', '0,1' (default: empty = single-NUMA mode)",
    )

    parser.add_argument(
        "--gpu",
        type=int,
        default=-1,
        metavar="DEVICE_ID",
        help="Use GPU HBM as source memory via GPUDirect RDMA. "
             "Specify CUDA device ordinal (e.g., --gpu 0). "
             "Default: -1 (CPU memory)",
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
        "--broadcast-seed",
        help="Seed for broadcast plan (supports base-36 strings)",
    )

    parser.add_argument(
        "--put-seed",
        help="Seed for put plan (supports base-36 strings)",
    )

    parser.add_argument(
        "--get-seed",
        help="Seed for get plan (supports base-36 strings)",
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
        "--batch-size",
        type=int,
        default=1,
        help="Number of async requests per NUMA per iteration (default: 1)",
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


def run_tests(
    harness: MPCommTestHarness,
    args: argparse.Namespace,
    scatter_seed: int,
    gather_seed: int,
    broadcast_seed: int,
    put_seed: int = 0,
    get_seed: int = 0,
) -> None:
    """Unified test driver for all modes (CPU/GPU, single/multi-NUMA)."""
    do_scatter = args.mode in {"scatter", "both", "all"}
    do_gather = args.mode in {"gather", "both", "all"}
    do_broadcast = args.mode in {"broadcast", "all"}
    do_put = args.mode in {"put", "all"}
    do_get = args.mode in {"get", "all"}
    iterations = args.iterations

    is_perf = args.test_mode == "performance"
    prepare = not is_perf
    verify = not is_perf
    reset = not is_perf

    timeout_ms = args.async_timeout_ms
    poll_us = args.poll_interval_us if args.async_mode == "polling" else 0

    perf_tracker = PerformanceTracker() if is_perf else None

    batch_size = harness.batch_size
    mode_tag = f"{harness.num_numas}-NUMA"
    if harness.use_gpu:
        mode_tag = f"GPU:{harness.gpu_device}"
    if batch_size > 1:
        mode_tag += f", batch={batch_size}"
    completion = "polling" if poll_us > 0 else "wait"

    # --- Scatter / Gather tests (share ReplicationPlan) ---
    for direction, seed, should_run in [
        ("scatter", scatter_seed, do_scatter),
        ("gather", gather_seed, do_gather),
    ]:
        if not should_run:
            continue

        print(f"\n=== {direction.capitalize()} Test [{mode_tag}, {completion}] "
              f"(seed={seed}, iterations={iterations}) ===")
        plan = harness.build_replication_plan(seed, direction)
        bytes_per_numa = sum(plan.lengths)

        for i in range(iterations):
            current_seed = seed if is_perf else seed + i
            if iterations > 1:
                print(f"\n[{direction}] Iteration {i + 1}/{iterations}")

            run_fn = harness.run_scatter if direction == "scatter" else harness.run_gather
            duration, total_bytes, per_numa = run_fn(
                current_seed,
                prepare_payload=prepare,
                verify=verify,
                reset=reset,
                plan=plan if is_perf else None,
                timeout_ms=timeout_ms,
                poll_interval_us=poll_us,
            )

            if perf_tracker:
                perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)

            bandwidth = total_bytes / duration if duration > 0 else 0
            duration_us = duration * 1_000_000
            print(f"  total: duration={duration_us:.2f}us, "
                  f"bytes={_format_bytes(total_bytes)}, "
                  f"bandwidth={_format_bandwidth(bandwidth)}")
            if harness.num_numas > 1:
                for ni, nd in enumerate(per_numa):
                    nn = harness.numa_nodes[ni]
                    nbw = bytes_per_numa / nd if nd > 0 else 0
                    print(f"    NUMA {nn}: {nd*1_000_000:.2f}us, "
                          f"{_format_bandwidth(nbw)}")

    # --- Broadcast test ---
    if do_broadcast:
        seed = broadcast_seed
        print(f"\n=== Broadcast Test [{mode_tag}, {completion}] "
              f"(seed={seed}, iterations={iterations}) ===")
        bplan = harness.build_broadcast_plan(seed)
        bcast_bytes_per_numa = bplan.length * len(harness.targets)

        for i in range(iterations):
            current_seed = seed if is_perf else seed + i
            if iterations > 1:
                print(f"\n[broadcast] Iteration {i + 1}/{iterations}")

            duration, total_bytes, per_numa = harness.run_broadcast(
                current_seed,
                prepare_payload=prepare,
                verify=verify,
                reset=reset,
                plan=bplan if is_perf else None,
                timeout_ms=timeout_ms,
                poll_interval_us=poll_us,
            )

            if perf_tracker:
                perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)

            bandwidth = total_bytes / duration if duration > 0 else 0
            duration_us = duration * 1_000_000
            print(f"  total: duration={duration_us:.2f}us, "
                  f"bytes={_format_bytes(total_bytes)}, "
                  f"bandwidth={_format_bandwidth(bandwidth)}")
            if harness.num_numas > 1:
                for ni, nd in enumerate(per_numa):
                    nn = harness.numa_nodes[ni]
                    nbw = bcast_bytes_per_numa / nd if nd > 0 else 0
                    print(f"    NUMA {nn}: {nd*1_000_000:.2f}us, "
                          f"{_format_bandwidth(nbw)}")

    # --- Put / Get tests (point-to-point) ---
    for direction, seed, should_run in [
        ("put", put_seed, do_put),
        ("get", get_seed, do_get),
    ]:
        if not should_run:
            continue

        print(f"\n=== {direction.capitalize()} Test [{mode_tag}, {completion}] "
              f"(seed={seed}, iterations={iterations}) ===")

        for i in range(iterations):
            current_seed = seed if is_perf else seed + i
            if iterations > 1:
                print(f"\n[{direction}] Iteration {i + 1}/{iterations}")

            run_fn = harness.run_put if direction == "put" else harness.run_get
            duration, total_bytes, per_numa = run_fn(
                current_seed,
                prepare_payload=prepare,
                verify=verify,
                reset=reset,
                timeout_ms=timeout_ms,
                poll_interval_us=poll_us,
            )

            if perf_tracker:
                perf_tracker.add_sample(bytes_count=total_bytes, duration=duration)

            bandwidth = total_bytes / duration if duration > 0 else 0
            duration_us = duration * 1_000_000
            print(f"  total: duration={duration_us:.2f}us, "
                  f"bytes={_format_bytes(total_bytes)}, "
                  f"bandwidth={_format_bandwidth(bandwidth)}")
            if harness.num_numas > 1:
                bytes_per_numa = total_bytes // harness.num_numas
                for ni, nd in enumerate(per_numa):
                    nn = harness.numa_nodes[ni]
                    nbw = bytes_per_numa / nd if nd > 0 else 0
                    print(f"    NUMA {nn}: {nd*1_000_000:.2f}us, "
                          f"{_format_bandwidth(nbw)}")

    if perf_tracker and perf_tracker.total_bytes > 0 and perf_tracker.total_time > 0:
        avg_bw = perf_tracker.average_bandwidth()
        print(f"\n[performance] Aggregate: "
              f"bytes={_format_bytes(perf_tracker.total_bytes)}, "
              f"time={perf_tracker.total_time*1_000_000:.2f}us, "
              f"bandwidth={_format_bandwidth(avg_bw)}")


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Parse targets (support both comma-separated and multiple --targets)
    targets = []
    for t in args.targets:
        for single_target in t.split(','):
            single_target = single_target.strip()
            if single_target:
                targets.append(parse_target(single_target))
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
    broadcast_seed = _parse_seed_arg(args.broadcast_seed, BROADCAST_SEED)
    put_seed = _parse_seed_arg(args.put_seed, PUT_SEED)
    get_seed = _parse_seed_arg(args.get_seed, GET_SEED)

    # Determine NUMA nodes
    gpu_device = args.gpu
    use_gpu = gpu_device >= 0

    numa_nodes_str = args.num_numas.strip()
    if numa_nodes_str:
        numa_nodes = [int(n.strip()) for n in numa_nodes_str.split(",") if n.strip()]
    else:
        numa_nodes = []

    if use_gpu:
        if numa_nodes:
            print("[warning] --gpu is not compatible with --num-numas, ignoring --num-numas")
        # GPU mode: single NUMA node (default 0)
        numa_nodes = [0]
    elif not numa_nodes:
        # Default: single NUMA node 0
        numa_nodes = [0]

    is_performance_mode = args.test_mode == "performance"

    print(f"[test] NUMA nodes: {numa_nodes}, GPU: {gpu_device}, "
          f"batch-size: {args.batch_size}, async-mode: {args.async_mode}")

    harness = MPCommTestHarness(
        host_id=args.host_id,
        device_name=args.device,
        targets=targets,
        min_chunk_size=args.min_chunk_size,
        max_chunk_size=args.max_chunk_size,
        num_threads=args.num_threads,
        numa_nodes=numa_nodes,
        performance_mode=is_performance_mode,
        gpu_device=gpu_device,
        batch_size=args.batch_size,
    )

    try:
        run_tests(harness, args, scatter_seed, gather_seed, broadcast_seed,
                  put_seed, get_seed)
        print("\n[test] All tests passed!")
    finally:
        harness.close()


if __name__ == "__main__":
    main()
