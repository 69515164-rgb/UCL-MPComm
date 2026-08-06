// Copyright (C) 2026 Tencent. All rights reserved.
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

// hello_mpcomm.cpp — minimal MPComm demo (target / initiator roles).
//
//   target    :  ./hello_mpcomm target    <host_id> <tcp_port>
//   initiator :  ./hello_mpcomm initiator <host_id> <target_host_id> <target_ip> <target_port>
//
// Flow: init -> register -> (target: publish + accept) /
//                           (initiator: connect + query + put + get + verify) -> shutdown.

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>

#include "mpcomm.h"

namespace {

constexpr size_t kBufSize = 4 * 1024 * 1024;  // 4 MiB
std::atomic<bool> g_stop{false};

#define CHECK(expr, msg) do { int _rc = (expr); \
    if (_rc != 0) { std::cerr << msg << " rc=" << _rc << "\n"; return 1; } } while (0)

void* AlignedAlloc(size_t n) {
    void* p = nullptr;
    if (posix_memalign(&p, 4096, n) != 0) return nullptr;
    std::memset(p, 0, n);
    return p;
}

int RunTarget(const std::string& host_id, int tcp_port) {
    mpcomm::MPComm c;
    CHECK(c.init(host_id, "", tcp_port), "[target] init");

    void* buf = AlignedAlloc(kBufSize);
    CHECK(c.registerMemory(buf, kBufSize),        "[target] registerMemory");
    CHECK(c.publishBuffer(buf, kBufSize, -1),     "[target] publishBuffer");
    CHECK(c.startAcceptThread(),                  "[target] startAcceptThread");

    std::cout << "[target] ready, host_id=" << c.getLocalHostId()
              << " tcp_port=" << c.getTcpPort()
              << " buf=0x" << std::hex << reinterpret_cast<uintptr_t>(buf) << std::dec
              << ". Ctrl-C to exit.\n";

    std::signal(SIGINT,  [](int){ g_stop = true; });
    std::signal(SIGTERM, [](int){ g_stop = true; });
    while (!g_stop) std::this_thread::sleep_for(std::chrono::milliseconds(200));

    c.stopAcceptThread();
    c.unpublishAllBuffers();
    c.unregisterMemory(buf);
    free(buf);
    c.shutdown();
    return 0;
}

int RunInitiator(const std::string& host_id, const std::string& tid,
                 const std::string& tip, int tport) {
    mpcomm::MPComm c;
    CHECK(c.init(host_id, "", 0), "[init] init");

    auto* send_buf = static_cast<uint8_t*>(AlignedAlloc(kBufSize));
    auto* recv_buf = static_cast<uint8_t*>(AlignedAlloc(kBufSize));
    for (size_t i = 0; i < kBufSize; ++i) send_buf[i] = uint8_t(i);

    CHECK(c.registerMemory(send_buf, kBufSize), "[init] reg send");
    CHECK(c.registerMemory(recv_buf, kBufSize), "[init] reg recv");
    CHECK(c.connect(tid, tip, tport),           "[init] connect");

    mpcomm::RemoteBufferEntry remote;
    CHECK(c.queryRemoteBufferByNuma(tid, tip, tport, -1, remote), "[init] query");
    std::cout << "[init] remote addr=0x" << std::hex << remote.addr
              << std::dec << " len=" << remote.length << "\n";

    auto run = [&](const char* op, mpcomm::TransferHandle h) -> int {
        if (h == mpcomm::INVALID_TRANSFER_HANDLE) {
            std::cerr << "[init] " << op << " submit failed\n"; return 1;
        }
        int rc = c.waitTransfer(h, 10000);
        auto r = c.getTransferResult(h);
        c.releaseTransfer(h);
        if (rc != 0 || r.error_code != 0) {
            std::cerr << "[init] " << op << " rc=" << rc
                      << " err=" << r.error_code << "\n"; return 1;
        }
        std::cout << "[init] " << op << " OK " << r.bytes_transferred
                  << "B " << r.elapsed_ms << "ms\n";
        return 0;
    };
    if (run("put", c.putAsync((uintptr_t)send_buf, tid, remote.addr, kBufSize))) return 1;
    if (run("get", c.getAsync((uintptr_t)recv_buf, tid, remote.addr, kBufSize))) return 1;

    int ret = std::memcmp(send_buf, recv_buf, kBufSize) == 0 ? 0 : 2;
    std::cout << (ret ? "[init] VERIFY FAIL\n" : "[init] VERIFY OK\n");

    c.unregisterMemory(send_buf); c.unregisterMemory(recv_buf);
    free(send_buf); free(recv_buf);
    c.shutdown();
    return ret;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc >= 4 && std::string(argv[1]) == "target")
        return RunTarget(argv[2], std::stoi(argv[3]));
    if (argc >= 6 && std::string(argv[1]) == "initiator")
        return RunInitiator(argv[2], argv[3], argv[4], std::stoi(argv[5]));
    std::cerr <<
        "Usage:\n"
        "  " << argv[0] << " target    <host_id> <tcp_port>\n"
        "  " << argv[0] << " initiator <host_id> <target_host_id> <target_ip> <target_port>\n";
    return 1;
}
