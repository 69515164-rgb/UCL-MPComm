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
MPComm Target Server

Remote helper that keeps a DDR buffer online for mp_replicate tests.
This script runs on the target host and waits for incoming RDMA connections.

Usage:
    python mpcomm_target.py --host-id target1 --tcp-port 12345 --device mlx5_0

Environment variables:
    MPCOMM_HOST_ID: Local host identifier (default: 127.0.0.1:12345)
    MPCOMM_TCP_PORT: TCP port for metadata exchange (default: 12345)
    MPCOMM_DEVICE: RDMA device name (default: auto-detect)
    MPCOMM_BUFFER_SIZE: Buffer size in bytes (default: 2GB)
"""

import argparse
import ipaddress
import os
import signal
import socket
import sys
import time
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


DEFAULT_BUFFER_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
DEFAULT_TCP_PORT = 12345
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
        print(f"Failed to resolve host {host_only}, using zeros for pattern", file=sys.stderr)
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


class MPCommTargetServer:
    """Target server that maintains a DDR buffer for RDMA operations."""

    def __init__(
        self,
        *,
        host_id: str,
        tcp_port: int,
        device_name: str,
        buffer_size: int,
        verbose: bool,
    ) -> None:
        self.host_id = host_id
        self.tcp_port = tcp_port
        self.device_name = device_name
        self.buffer_size = buffer_size
        self.verbose = verbose
        self._stop_requested = False

        # Initialize MPComm
        self.comm = mpcomm.MPComm()
        ret = self.comm.init(host_id, device_name, tcp_port)
        if ret != 0:
            raise RuntimeError(f"MPComm initialization failed with code {ret}")

        # Get actual TCP port (in case 0 was passed for auto-select)
        self.tcp_port = self.comm.get_tcp_port()

        print(f"[target] Initialized MPComm with {self.comm.get_num_nics()} NICs")
        for i in range(self.comm.get_num_nics()):
            print(f"  NIC {i}: GID={self.comm.get_gid(i)}")

        # Allocate and register buffer
        self._tensor: Optional[torch.Tensor] = None
        self.buffer_addr = self._allocate_buffer()
        self._ipv4_bytes = _resolve_ipv4_bytes(host_id)

        # Initialize buffer with IPv4 pattern
        self._initialize_buffer_pattern()

        # Publish buffer for remote queries
        ret = self.comm.publish_buffer(self.buffer_addr, self.buffer_size)
        if ret != 0:
            raise RuntimeError(f"Failed to publish buffer: {ret}")

    def _allocate_buffer(self) -> int:
        """Allocate a tensor buffer and register it for RDMA."""
        tensor = torch.empty(self.buffer_size, dtype=torch.uint8)
        if not tensor.is_contiguous():
            tensor = tensor.contiguous()
        addr = tensor.data_ptr()

        ret = self.comm.register_memory(addr, self.buffer_size)
        if ret != 0:
            raise RuntimeError(f"Failed to register memory: {ret}")

        self._tensor = tensor
        print(f"[target] Registered buffer at 0x{addr:x} ({_format_bytes(self.buffer_size)})")
        return addr

    def _initialize_buffer_pattern(self) -> None:
        """Initialize buffer with IPv4 pattern for verification."""
        pattern_size = min(self.buffer_size, 1024 * 1024)  # Initialize first 1MB
        payload = _build_ipv4_pattern(self._ipv4_bytes, pattern_size)
        
        ret = self.comm.write_bytes_to_buffer(self.buffer_addr, payload, len(payload))
        if ret != 0:
            print("[target] Warning: failed to seed buffer with IPv4 pattern", file=sys.stderr)
            return

        print(f"[target] Seeded buffer using IPv4 bytes {self._ipv4_bytes} preview={_preview_hex(payload)}")

    def _unpublish_buffer(self) -> None:
        """Unpublish the buffer before cleanup."""
        if self.buffer_addr:
            self.comm.unpublish_buffer(self.buffer_addr)

    def get_buffer_info(self) -> dict:
        """Get buffer information for exchange with initiator."""
        return {
            "host_id": self.host_id,
            "tcp_addr": self.host_id.split(":")[0],
            "tcp_port": self.tcp_port,
            "buffer_addr": self.buffer_addr,
            "buffer_size": self.buffer_size,
            "rkeys": self.comm.get_all_rkeys(self.buffer_addr),
            "num_nics": self.comm.get_num_nics(),
        }

    def stop(self) -> None:
        """Request the server to stop."""
        self._stop_requested = True

    def close(self) -> None:
        """Cleanup resources."""
        if self.buffer_addr and self._tensor is not None:
            self._unpublish_buffer()
            self.comm.unregister_memory(self.buffer_addr)
            self.buffer_addr = 0
            self._tensor = None
        self.comm.stop_accept_thread()
        self.comm.shutdown()

    def run(self) -> None:
        """Run the target server, accepting connections and waiting."""
        # Start accept thread for incoming connections
        ret = self.comm.start_accept_thread()
        if ret != 0:
            raise RuntimeError(f"Failed to start accept thread: {ret}")

        # Print connection info
        print("\n" + "=" * 60)
        print("MPComm Target Server Ready")
        print("=" * 60)
        info = self.get_buffer_info()
        print(f"  Host ID:      {info['host_id']}")
        print(f"  TCP Address:  {info['tcp_addr']}:{info['tcp_port']}")
        print(f"  Buffer Addr:  0x{info['buffer_addr']:x}")
        print(f"  Buffer Size:  {_format_bytes(info['buffer_size'])}")
        print(f"  Num NICs:     {info['num_nics']}")
        print(f"  RKeys:        {info['rkeys']}")
        print("=" * 60)
        print("\nBuffer is published and accessible via TCP metadata exchange.")
        print("Initiator can use query_remote_buffer() to get buffer info automatically.")
        print("\nWaiting for connections... (Press Ctrl+C to stop)\n")

        # Main loop - just wait and periodically print status
        poll_interval = 5.0
        while not self._stop_requested:
            time.sleep(poll_interval)
            if self.verbose:
                # Read and print buffer preview
                preview_data = self.comm.read_bytes_from_buffer(self.buffer_addr, 64)
                print(f"[target] Buffer preview: {_preview_hex(preview_data)}")

        print("[target] Stopping server...")


def _install_signal_handlers(target: MPCommTargetServer) -> None:
    """Install signal handlers for graceful shutdown."""
    def _handler(signum, _frame):
        print(f"\n[target] Received signal {signum}, stopping...")
        target.stop()

    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="MPComm Target Server - maintains DDR buffer for RDMA tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start target server with auto-detected device
    python mpcomm_target.py --host-id target1:12345

    # Start target server with specific device
    python mpcomm_target.py --host-id 10.0.0.2:12345 --device mlx5_0

    # Start target server with larger buffer
    python mpcomm_target.py --host-id target1:12345 --buffer-size 20GB
""",
    )

    parser.add_argument(
        "--host-id",
        default=os.getenv("MPCOMM_HOST_ID", "127.0.0.1:12345"),
        help="Local host identifier (default: %(default)s)",
    )

    parser.add_argument(
        "--tcp-port",
        type=int,
        default=int(os.getenv("MPCOMM_TCP_PORT", DEFAULT_TCP_PORT)),
        help="TCP port for metadata exchange (default: %(default)s)",
    )

    parser.add_argument(
        "--device",
        default=os.getenv("MPCOMM_DEVICE", ""),
        help="RDMA device name (comma-separated for multiple). Empty = auto-detect",
    )

    parser.add_argument(
        "--buffer-size",
        default=os.getenv("MPCOMM_BUFFER_SIZE", str(DEFAULT_BUFFER_SIZE)),
        help="Buffer size with optional suffix (K/M/G/T) (default: 10GB)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print periodic buffer status",
    )

    return parser.parse_args()


def parse_size(size_str: str) -> int:
    """Parse size string with optional suffix (K/M/G/T)."""
    size_str = size_str.strip().upper()
    multipliers = {
        "K": 1024,
        "KB": 1024,
        "KIB": 1024,
        "M": 1024 ** 2,
        "MB": 1024 ** 2,
        "MIB": 1024 ** 2,
        "G": 1024 ** 3,
        "GB": 1024 ** 3,
        "GIB": 1024 ** 3,
        "T": 1024 ** 4,
        "TB": 1024 ** 4,
        "TIB": 1024 ** 4,
    }

    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(suffix):
            return int(float(size_str[:-len(suffix)]) * mult)

    return int(size_str)


def main() -> None:
    """Main entry point."""
    args = parse_args()

    buffer_size = parse_size(args.buffer_size)

    target = MPCommTargetServer(
        host_id=args.host_id,
        tcp_port=args.tcp_port,
        device_name=args.device,
        buffer_size=buffer_size,
        verbose=args.verbose,
    )

    _install_signal_handlers(target)

    try:
        target.run()
    except KeyboardInterrupt:
        target.stop()
    finally:
        target.close()


if __name__ == "__main__":
    main()
