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
    remote_addr: int = 0  # Can be queried from remote
    rkeys: List[int] = None  # Can be queried from remote

    def __post_init__(self):
        if self.rkeys is None:
            self.rkeys = []

    def is_complete(self) -> bool:
        """Check if target has complete info (addr and rkeys)."""
        return self.remote_addr != 0 and len(self.rkeys) > 0


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
        """Run scatter operation (RDMA WRITE to targets)."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="scatter")

        # Prepare payloads in local buffer
        if prepare_payload:
            for offset, payload in zip(plan.offsets, plan.payloads):
                if payload:
                    self._write_local_chunk(offset, payload)

        # Build host list
        host_list = [t.host_id for t in self.targets]

        # Run scatter
        start_time = time.perf_counter()
        ret = self.comm.mp_replicate(
            "scatter",
            host_list,
            self.local_buffer_addr,
            plan.remote_addresses,
            plan.lengths,
            self.num_threads
        )
        duration = time.perf_counter() - start_time

        if ret != 0:
            raise RuntimeError(f"mp_replicate scatter failed: {ret}")

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
        """Run gather operation (RDMA READ from targets)."""
        if plan is None:
            plan = self.build_replication_plan(seed, mode="gather")

        # Clear local buffer regions where data will be gathered
        if prepare_payload:
            for offset, length in zip(plan.offsets, plan.lengths):
                self._clear_local_chunk(offset, length)

        # Build host list
        host_list = [t.host_id for t in self.targets]

        # Run gather
        start_time = time.perf_counter()
        ret = self.comm.mp_replicate(
            "gather",
            host_list,
            self.local_buffer_addr,
            plan.remote_addresses,
            plan.lengths,
            self.num_threads
        )
        duration = time.perf_counter() - start_time

        if ret != 0:
            raise RuntimeError(f"mp_replicate gather failed: {ret}")

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

    # Test mode settings
    is_performance_mode = args.test_mode == "performance"
    prepare_payload = not is_performance_mode
    verify_payload = not is_performance_mode
    reset_buffer = not is_performance_mode

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
            print(f"\n=== Scatter Test (seed={scatter_seed}, iterations={iterations}) ===")
            plan = harness.build_replication_plan(scatter_seed, "scatter")
            total_bytes = sum(plan.lengths)

            for i in range(iterations):
                current_seed = scatter_seed if is_performance_mode else scatter_seed + i
                if iterations > 1:
                    print(f"\n[scatter] Iteration {i + 1}/{iterations}")

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
            print(f"\n=== Gather Test (seed={gather_seed}, iterations={iterations}) ===")
            plan = harness.build_replication_plan(gather_seed, "gather")
            total_bytes = sum(plan.lengths)

            for i in range(iterations):
                current_seed = gather_seed if is_performance_mode else gather_seed + i
                if iterations > 1:
                    print(f"\n[gather] Iteration {i + 1}/{iterations}")

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
