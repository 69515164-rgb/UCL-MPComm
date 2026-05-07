#!/usr/bin/env python3
# hello_mpcomm.py — minimal MPComm demo (target / initiator roles).
#
#   target    :  hello_mpcomm.py target    <host_id> <tcp_port>
#   initiator :  hello_mpcomm.py initiator <host_id> <target_host_id> <target_ip> <target_port>

import ctypes, signal, sys, time
import mpcomm

BUF = 4 * 1024 * 1024  # 4 MiB

def alloc(n):
    """Return (addr, keepalive) for an n-byte zeroed buffer."""
    raw = (ctypes.c_ubyte * n)()
    return ctypes.addressof(raw), raw

def check(rc, msg):
    if rc != 0:
        sys.exit(f"{msg} rc={rc}")

def run_target(host_id, tcp_port):
    c = mpcomm.MPComm()
    check(c.init(host_id, "", tcp_port), "[target] init")

    addr, keep = alloc(BUF)
    check(c.register_memory(addr, BUF),     "[target] register_memory")
    check(c.publish_buffer(addr, BUF, -1),  "[target] publish_buffer")
    check(c.start_accept_thread(),          "[target] start_accept_thread")
    print(f"[target] ready host_id={c.get_local_host_id()} "
          f"tcp_port={c.get_tcp_port()} addr=0x{addr:x}. Ctrl-C to exit.")

    stop = [False]
    signal.signal(signal.SIGINT,  lambda *_: stop.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__(0, True))
    while not stop[0]: time.sleep(0.2)

    c.stop_accept_thread(); c.unpublish_all_buffers()
    c.unregister_memory(addr); c.shutdown()
    del keep

def run_initiator(host_id, tid, tip, tport):
    c = mpcomm.MPComm()
    check(c.init(host_id, "", 0), "[init] init")

    send, sk = alloc(BUF)
    recv, rk = alloc(BUF)
    ctypes.memmove(send, bytes(i & 0xFF for i in range(BUF)), BUF)

    check(c.register_memory(send, BUF), "[init] reg send")
    check(c.register_memory(recv, BUF), "[init] reg recv")
    check(c.connect(tid, tip, tport),   "[init] connect")

    remote = c.query_remote_buffer_by_numa(tid, tip, tport, -1)
    if not remote: sys.exit("[init] query failed")
    print(f"[init] remote addr=0x{remote['addr']:x} len={remote['length']}")

    def do(op, h):
        if h == mpcomm.INVALID_TRANSFER_HANDLE: sys.exit(f"[init] {op} submit failed")
        rc = c.wait_transfer(h, 10000)
        r = c.get_transfer_result(h); c.release_transfer(h)
        if rc or r["error_code"]: sys.exit(f"[init] {op} rc={rc} err={r['error_code']}")
        print(f"[init] {op} OK {r['bytes_transferred']}B {r['elapsed_ms']:.3f}ms")

    do("put", c.put_async(send, tid, remote["addr"], BUF))
    do("get", c.get_async(recv, tid, remote["addr"], BUF))

    ok = bytes((ctypes.c_ubyte * BUF).from_address(send)) == \
         bytes((ctypes.c_ubyte * BUF).from_address(recv))
    print("[init] VERIFY OK" if ok else "[init] VERIFY FAIL")

    c.unregister_memory(send); c.unregister_memory(recv); c.shutdown()
    del sk, rk
    sys.exit(0 if ok else 2)

def main():
    a = sys.argv
    if len(a) == 4 and a[1] == "target":
        run_target(a[2], int(a[3]))
    elif len(a) == 6 and a[1] == "initiator":
        run_initiator(a[2], a[3], a[4], int(a[5]))
    else:
        sys.exit(f"Usage:\n"
                 f"  {a[0]} target    <host_id> <tcp_port>\n"
                 f"  {a[0]} initiator <host_id> <target_host_id> <target_ip> <target_port>")

if __name__ == "__main__":
    main()
