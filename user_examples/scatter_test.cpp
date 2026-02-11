// MPComm C++ Scatter Performance Test
//
// Demonstrates scatter_async API usage with DRAM and HBM (GPU) memory.
// Supports both initiator and target modes in a single binary.
// No data correctness verification — purely performance-oriented.
//
// Target mode (run on remote host first):
//   ./scatter_test --mode target --host-id 29.160.42.103:12345 --tcp-port 12345 --buffer-size 2G
//
//   # Multi-NUMA target:
//   ./scatter_test --mode target --host-id 29.160.42.103:12345 --tcp-port 12345 --buffer-size 2G --num-numas 0,1
//
// Initiator mode (default, run on local host):
//   # Single target, DRAM scatter (default 1GB per target, 10 iterations):
//   ./scatter_test --target target1:192.168.1.100:12345
//
//   # Multiple targets:
//   ./scatter_test --target target1:192.168.1.100:12345 --target target2:114.193.206.253:12345
//
//   # Multiple targets with custom per-target size and iterations:
//   ./scatter_test --target t1:10.0.0.1:12345 --target t2:10.0.0.2:12345 --size 500000000 --iterations 20
//
//   # HBM (GPU) scatter to multiple targets:
//   ./scatter_test --target t1:10.0.0.1:12345 --target t2:10.0.0.2:12345 --gpu 0
//
//   # Both DRAM and HBM:
//   ./scatter_test --target t1:10.0.0.1:12345 --target t2:10.0.0.2:12345 --gpu 0 --both
//
//   # Multi-NUMA initiator (dual NUMA buffers, each NUMA sends via its local NICs):
//   ./scatter_test --target t1:10.0.0.1:12345 --target t2:10.0.0.2:12345 --num-numas 0,1

#include <mpcomm.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <csignal>
#include <sstream>
#include <numa.h>
#include <numaif.h>

#ifdef USE_CUDA
#include <cuda.h>
#endif

using namespace mpcomm;

// =====================================================================
// Signal handling for target mode graceful shutdown
// =====================================================================

static std::atomic<bool> g_stop_requested{false};

static void signalHandler(int signum) {
    printf("\n[target] Received signal %d, stopping...\n", signum);
    g_stop_requested.store(true);
}

// =====================================================================
// Helpers
// =====================================================================

struct TargetInfo {
    std::string host_id;
    std::string tcp_addr;
    int tcp_port = 0;
};

enum RunMode {
    MODE_INITIATOR = 0,
    MODE_TARGET = 1,
};

struct TestConfig {
    RunMode mode = MODE_INITIATOR;

    // --- Common ---
    std::string host_id = "test:0";
    std::string device = "";           // empty = auto-detect
    int tcp_port = 0;                  // TCP port for metadata exchange

    // --- Initiator mode ---
    std::vector<TargetInfo> targets;   // one or more remote targets
    size_t buffer_size = 1000000000;   // 1 GB per target
    int iterations = 10;
    int warmup = 2;
    int gpu_device = -1;               // -1 = CPU only
    bool run_both = false;             // run both DRAM and HBM
    std::vector<int> initiator_numas;  // NUMA nodes for initiator buffers

    // --- Target mode ---
    size_t target_buffer_size = 2ULL * 1024 * 1024 * 1024;  // 2 GB default
    std::vector<int> numa_nodes;       // NUMA nodes to allocate buffers on
    bool verbose = false;
};

// Parse size string with optional suffix (K/M/G/T)
static size_t parseSize(const std::string &str) {
    if (str.empty()) return 0;

    size_t len = str.size();
    double value = 0;
    size_t suffix_start = 0;

    // Find where the numeric part ends
    for (size_t i = 0; i < len; ++i) {
        char c = str[i];
        if ((c >= '0' && c <= '9') || c == '.') {
            suffix_start = i + 1;
        } else {
            break;
        }
    }

    value = std::stod(str.substr(0, suffix_start));
    std::string suffix = str.substr(suffix_start);

    // Convert suffix to uppercase
    for (auto &c : suffix) c = (char)toupper((unsigned char)c);

    size_t multiplier = 1;
    if (suffix.empty() || suffix == "B") {
        multiplier = 1;
    } else if (suffix == "K" || suffix == "KB" || suffix == "KIB") {
        multiplier = 1024ULL;
    } else if (suffix == "M" || suffix == "MB" || suffix == "MIB") {
        multiplier = 1024ULL * 1024;
    } else if (suffix == "G" || suffix == "GB" || suffix == "GIB") {
        multiplier = 1024ULL * 1024 * 1024;
    } else if (suffix == "T" || suffix == "TB" || suffix == "TIB") {
        multiplier = 1024ULL * 1024 * 1024 * 1024;
    }

    return static_cast<size_t>(value * multiplier);
}

// Parse comma-separated NUMA node list, e.g. "0,1"
static std::vector<int> parseNumaNodes(const std::string &str) {
    std::vector<int> nodes;
    std::istringstream iss(str);
    std::string token;
    while (std::getline(iss, token, ',')) {
        if (!token.empty()) {
            nodes.push_back(std::stoi(token));
        }
    }
    return nodes;
}

static void printUsage(const char *prog) {
    printf("MPComm C++ Scatter Test (initiator + target in one binary)\n\n");
    printf("Usage:\n");
    printf("  Target mode:\n");
    printf("    %s --mode target --host-id HOST:PORT --tcp-port PORT [options]\n\n", prog);
    printf("  Initiator mode (default):\n");
    printf("    %s --target host_id:addr:port [--target ...] [options]\n\n", prog);
    printf("Common Options:\n");
    printf("  --mode MODE                  'initiator' (default) or 'target'\n");
    printf("  --host-id ID                 Local host ID (default: test:0)\n");
    printf("  --device DEVS                RDMA devices, comma-separated (default: auto)\n");
    printf("  --tcp-port PORT              TCP port for metadata exchange (default: 0=auto)\n");
    printf("  --num-numas NODES            Comma-separated NUMA nodes (default: 0)\n");
    printf("\nTarget Mode Options:\n");
    printf("  --buffer-size SIZE           Buffer size with suffix K/M/G/T (default: 2G)\n");
    printf("  --verbose                    Print periodic buffer status\n");
    printf("\nInitiator Mode Options:\n");
    printf("  --target HOST_ID:ADDR:PORT   Remote target (required, repeatable)\n");
    printf("  --size BYTES                 Buffer size per target in bytes (default: 1000000000)\n");
    printf("  --iterations N               Number of timed iterations (default: 10)\n");
    printf("  --warmup N                   Number of warmup iterations (default: 2)\n");
    printf("  --gpu DEVICE_ID              GPU device for HBM test (default: -1, CPU only)\n");
    printf("  --both                       Run both DRAM and HBM tests\n");
    printf("\nExamples:\n");
    printf("  # Target (remote host):\n");
    printf("  %s --mode target --host-id 29.160.42.103:12345 --tcp-port 12345 --buffer-size 2G\n", prog);
    printf("  %s --mode target --host-id 29.160.42.103:12345 --tcp-port 12345 --buffer-size 2G --num-numas 0,1\n", prog);
    printf("\n  # Initiator (local host):\n");
    printf("  %s --target t1:10.0.0.1:12345 --target t2:10.0.0.2:12345\n", prog);
    printf("  %s --target t1:10.0.0.1:12345 --gpu 0 --both\n", prog);
    printf("  # Multi-NUMA initiator:\n");
    printf("  %s --target t1:10.0.0.1:12345 --num-numas 0,1\n", prog);
}

static bool parseTarget(const std::string &val, TargetInfo &info) {
    size_t p1 = val.find(':');
    size_t p2 = val.find(':', p1 + 1);
    if (p1 == std::string::npos || p2 == std::string::npos) {
        fprintf(stderr, "Error: --target format must be host_id:tcp_addr:tcp_port\n");
        return false;
    }
    info.host_id = val.substr(0, p1);
    info.tcp_addr = val.substr(p1 + 1, p2 - p1 - 1);
    info.tcp_port = std::stoi(val.substr(p2 + 1));
    return true;
}

static bool parseArgs(int argc, char *argv[], TestConfig &cfg) {
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--mode" && i + 1 < argc) {
            std::string mode_str = argv[++i];
            if (mode_str == "target") {
                cfg.mode = MODE_TARGET;
            } else if (mode_str == "initiator") {
                cfg.mode = MODE_INITIATOR;
            } else {
                fprintf(stderr, "Error: --mode must be 'initiator' or 'target'\n");
                return false;
            }
        } else if (arg == "--target" && i + 1 < argc) {
            TargetInfo info;
            if (!parseTarget(argv[++i], info)) {
                return false;
            }
            cfg.targets.push_back(std::move(info));
        } else if (arg == "--host-id" && i + 1 < argc) {
            cfg.host_id = argv[++i];
        } else if (arg == "--device" && i + 1 < argc) {
            cfg.device = argv[++i];
        } else if (arg == "--tcp-port" && i + 1 < argc) {
            cfg.tcp_port = std::stoi(argv[++i]);
        } else if (arg == "--size" && i + 1 < argc) {
            cfg.buffer_size = std::stoull(argv[++i]);
        } else if (arg == "--buffer-size" && i + 1 < argc) {
            cfg.target_buffer_size = parseSize(argv[++i]);
        } else if (arg == "--num-numas" && i + 1 < argc) {
            auto nodes = parseNumaNodes(argv[++i]);
            cfg.numa_nodes = nodes;
            cfg.initiator_numas = nodes;
        } else if (arg == "--iterations" && i + 1 < argc) {
            cfg.iterations = std::stoi(argv[++i]);
        } else if (arg == "--warmup" && i + 1 < argc) {
            cfg.warmup = std::stoi(argv[++i]);
        } else if (arg == "--gpu" && i + 1 < argc) {
            cfg.gpu_device = std::stoi(argv[++i]);
        } else if (arg == "--both") {
            cfg.run_both = true;
        } else if (arg == "--verbose" || arg == "-v") {
            cfg.verbose = true;
        } else if (arg == "--help" || arg == "-h") {
            printUsage(argv[0]);
            exit(0);
        } else {
            fprintf(stderr, "Unknown argument: %s\n", arg.c_str());
            printUsage(argv[0]);
            return false;
        }
    }

    if (cfg.mode == MODE_INITIATOR) {
        if (cfg.targets.empty()) {
            fprintf(stderr, "Error: at least one --target is required in initiator mode\n");
            printUsage(argv[0]);
            return false;
        }
        if (cfg.initiator_numas.empty()) {
            cfg.initiator_numas.push_back(0);
        }
    } else {
        // Target mode defaults
        if (cfg.numa_nodes.empty()) {
            cfg.numa_nodes.push_back(0);
        }
    }
    return true;
}

// =====================================================================
// DRAM allocation via libnuma
// =====================================================================

static void *allocDRAM(size_t size, int numa_node) {
    // Align to page boundary
    size_t page_size = 4096;
    size_t alloc_size = ((size + page_size - 1) / page_size) * page_size;

    void *ptr = nullptr;
    if (numa_available() >= 0 && numa_node >= 0) {
        ptr = numa_alloc_onnode(alloc_size, numa_node);
    }
    if (!ptr) {
        ptr = aligned_alloc(page_size, alloc_size);
    }
    if (ptr) {
        memset(ptr, 0xAB, alloc_size);  // touch pages to fault them in
    }
    return ptr;
}

static void freeDRAM(void *ptr, size_t size) {
    if (!ptr) return;
    size_t page_size = 4096;
    size_t alloc_size = ((size + page_size - 1) / page_size) * page_size;
    if (numa_available() >= 0) {
        numa_free(ptr, alloc_size);
    } else {
        free(ptr);
    }
}

// =====================================================================
// HBM (GPU) allocation via CUDA driver API
// =====================================================================

#ifdef USE_CUDA
static void *allocHBM(size_t size, int gpu_device) {
    CUresult res;
    res = cuInit(0);
    if (res != CUDA_SUCCESS) {
        fprintf(stderr, "cuInit failed: %d\n", res);
        return nullptr;
    }

    CUdevice dev;
    res = cuDeviceGet(&dev, gpu_device);
    if (res != CUDA_SUCCESS) {
        fprintf(stderr, "cuDeviceGet(%d) failed: %d\n", gpu_device, res);
        return nullptr;
    }

    CUcontext ctx;
    res = cuCtxCreate(&ctx, 0, dev);
    if (res != CUDA_SUCCESS) {
        fprintf(stderr, "cuCtxCreate failed: %d\n", res);
        return nullptr;
    }

    CUdeviceptr dptr = 0;
    res = cuMemAlloc(&dptr, size);
    if (res != CUDA_SUCCESS) {
        fprintf(stderr, "cuMemAlloc(%zu) failed: %d\n", size, res);
        cuCtxDestroy(ctx);
        return nullptr;
    }

    // Touch memory to ensure allocation is committed
    cuMemsetD8(dptr, 0xCD, size);

    printf("  GPU %d: allocated %zu bytes at 0x%llx\n",
           gpu_device, size, (unsigned long long)dptr);
    return reinterpret_cast<void *>(dptr);
}

static void freeHBM(void *ptr) {
    if (!ptr) return;
    cuMemFree(reinterpret_cast<CUdeviceptr>(ptr));
    // Note: CUcontext is leaked here for simplicity in a test program.
    // In production code, you should properly manage the CUDA context.
}
#endif

// =====================================================================
// Target mode: allocate buffers, publish, accept connections, wait
// =====================================================================

static std::string formatBytes(size_t bytes) {
    const char *units[] = {"B", "KB", "MB", "GB", "TB"};
    double value = static_cast<double>(bytes);
    int idx = 0;
    while (value >= 1000.0 && idx < 4) {
        value /= 1024.0;
        idx++;
    }
    char buf[64];
    snprintf(buf, sizeof(buf), "%.2f %s", value, units[idx]);
    return std::string(buf);
}

struct NumaBuffer {
    void *ptr = nullptr;
    size_t alloc_size = 0;
    int numa_node = -1;
};

static int runTargetMode(const TestConfig &cfg) {
    // Install signal handlers for graceful shutdown
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);

    printf("=== MPComm Target Mode ===\n");
    printf("  Host ID:      %s\n", cfg.host_id.c_str());
    printf("  TCP Port:     %d\n", cfg.tcp_port);
    printf("  Buffer Size:  %s per NUMA\n", formatBytes(cfg.target_buffer_size).c_str());
    printf("  NUMA Nodes:   ");
    for (size_t i = 0; i < cfg.numa_nodes.size(); ++i) {
        if (i > 0) printf(",");
        printf("%d", cfg.numa_nodes[i]);
    }
    printf("\n\n");

    // Initialize MPComm
    MPComm comm;
    int ret = comm.init(cfg.host_id, cfg.device, cfg.tcp_port);
    if (ret != 0) {
        fprintf(stderr, "MPComm init failed: %d\n", ret);
        return 1;
    }
    printf("[target] Initialized MPComm with %zu NICs\n", comm.getNumNics());
    printf("[target] TCP port: %d\n", comm.getTcpPort());
    for (size_t i = 0; i < comm.getNumNics(); ++i) {
        printf("  NIC %zu: %s GID=%s\n",
               i, comm.getDeviceName(i).c_str(), comm.getGid(i).c_str());
    }

    // Allocate and register buffers for each NUMA node
    std::vector<NumaBuffer> buffers;
    const size_t page_size = 4096;

    for (int numa_node : cfg.numa_nodes) {
        size_t alloc_size = ((cfg.target_buffer_size + page_size - 1) / page_size) * page_size;
        NumaBuffer nbuf;
        nbuf.numa_node = numa_node;
        nbuf.alloc_size = alloc_size;

        if (numa_available() >= 0 && numa_node >= 0) {
            nbuf.ptr = numa_alloc_onnode(alloc_size, numa_node);
        }
        if (!nbuf.ptr) {
            nbuf.ptr = aligned_alloc(page_size, alloc_size);
        }
        if (!nbuf.ptr) {
            fprintf(stderr, "Failed to allocate buffer for NUMA %d\n", numa_node);
            goto target_cleanup;
        }

        // Touch all pages to fault them in
        memset(nbuf.ptr, 0xAB, alloc_size);

        ret = comm.registerMemory(nbuf.ptr, cfg.target_buffer_size);
        if (ret != 0) {
            fprintf(stderr, "Failed to register memory for NUMA %d: %d\n", numa_node, ret);
            if (numa_available() >= 0) {
                numa_free(nbuf.ptr, alloc_size);
            } else {
                free(nbuf.ptr);
            }
            goto target_cleanup;
        }

        ret = comm.publishBuffer(nbuf.ptr, cfg.target_buffer_size, numa_node);
        if (ret != 0) {
            fprintf(stderr, "Failed to publish buffer for NUMA %d: %d\n", numa_node, ret);
            comm.unregisterMemory(nbuf.ptr);
            if (numa_available() >= 0) {
                numa_free(nbuf.ptr, alloc_size);
            } else {
                free(nbuf.ptr);
            }
            goto target_cleanup;
        }

        printf("[target] NUMA %d: allocated %s at %p, registered and published\n",
               numa_node, formatBytes(alloc_size).c_str(), nbuf.ptr);

        buffers.push_back(nbuf);
    }

    // Start accept thread
    ret = comm.startAcceptThread();
    if (ret != 0) {
        fprintf(stderr, "Failed to start accept thread: %d\n", ret);
        goto target_cleanup;
    }

    // Print ready info
    {
        printf("\n");
        printf("============================================================\n");
        printf(" MPComm Target Server Ready\n");
        printf("============================================================\n");
        printf("  Host ID:      %s\n", cfg.host_id.c_str());
        printf("  TCP Port:     %d\n", comm.getTcpPort());
        printf("  Num NICs:     %zu\n", comm.getNumNics());
        printf("  Num NUMAs:    %zu\n", buffers.size());
        printf("\n  Published Buffers:\n");
        for (const auto &nbuf : buffers) {
            printf("    NUMA %d: addr=%p, length=%s, rkeys=[",
                   nbuf.numa_node, nbuf.ptr,
                   formatBytes(cfg.target_buffer_size).c_str());
            for (size_t i = 0; i < comm.getNumNics(); ++i) {
                uint32_t rkey = comm.getRkey(i, nbuf.ptr);
                if (i > 0) printf(", ");
                printf("%u", rkey);
            }
            printf("]\n");
        }
        printf("============================================================\n");
        printf("\nWaiting for connections... (Press Ctrl+C to stop)\n\n");
    }

    // Main loop - wait for Ctrl+C
    while (!g_stop_requested.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    printf("[target] Shutting down...\n");

target_cleanup:
    // Cleanup: unpublish, unregister, free
    for (auto &nbuf : buffers) {
        if (nbuf.ptr) {
            comm.unpublishBuffer(nbuf.ptr);
            comm.unregisterMemory(nbuf.ptr);
            if (numa_available() >= 0) {
                numa_free(nbuf.ptr, nbuf.alloc_size);
            } else {
                free(nbuf.ptr);
            }
        }
    }
    comm.stopAcceptThread();
    comm.shutdown();

    printf("[target] Stopped.\n");
    return 0;
}

// =====================================================================
// Scatter performance benchmark (multi-NUMA aware)
// =====================================================================

// Per-NUMA buffer info for initiator
struct InitiatorNumaBuffer {
    void *ptr = nullptr;
    size_t alloc_size = 0;
    int numa_node = -1;
};

static int runScatterBenchmark(
    MPComm &comm,
    const TestConfig &cfg,
    const std::vector<InitiatorNumaBuffer> &numa_buffers,
    const std::vector<std::string> &host_list,
    // per-NUMA remote addresses: remote_addrs_per_numa[numa_idx][target_idx]
    const std::vector<std::vector<uintptr_t>> &remote_addrs_per_numa,
    const std::vector<size_t> &lengths,
    const char *mem_type_label)
{
    size_t per_numa_size = 0;
    for (size_t l : lengths) per_numa_size += l;
    size_t total_size = per_numa_size * numa_buffers.size();
    size_t num_numas = numa_buffers.size();

    printf("\n========================================\n");
    printf(" Scatter Performance: %s\n", mem_type_label);
    printf(" Targets: %zu\n", host_list.size());
    printf(" Per-target size: %zu bytes (%.2f MB)\n",
           cfg.buffer_size, cfg.buffer_size / 1e6);
    printf(" NUMA nodes: %zu (", num_numas);
    for (size_t i = 0; i < num_numas; ++i) {
        if (i > 0) printf(",");
        printf("%d", numa_buffers[i].numa_node);
    }
    printf(")\n");
    printf(" Per-NUMA total: %zu bytes (%.2f MB)\n",
           per_numa_size, per_numa_size / 1e6);
    printf(" Aggregate total: %zu bytes (%.2f MB)\n",
           total_size, total_size / 1e6);
    printf(" Warmup: %d, Iterations: %d\n", cfg.warmup, cfg.iterations);
    printf("========================================\n\n");

    // ---- Warmup ----
    printf("Warming up (%d iterations)...\n", cfg.warmup);
    for (int i = 0; i < cfg.warmup; ++i) {
        // Submit one scatterAsync per NUMA
        std::vector<TransferHandle> handles;
        handles.reserve(num_numas);
        for (size_t n = 0; n < num_numas; ++n) {
            uintptr_t local_addr = reinterpret_cast<uintptr_t>(numa_buffers[n].ptr);
            TransferHandle handle = comm.scatterAsync(
                local_addr, host_list, remote_addrs_per_numa[n], lengths);
            if (handle == INVALID_TRANSFER_HANDLE) {
                fprintf(stderr, "scatterAsync failed during warmup (NUMA %d)\n",
                        numa_buffers[n].numa_node);
                for (auto h : handles) comm.releaseTransfer(h);
                return 1;
            }
            handles.push_back(handle);
        }
        // Wait all
        for (size_t n = 0; n < num_numas; ++n) {
            int ret = comm.waitTransfer(handles[n], -1);
            if (ret != 0) {
                fprintf(stderr, "waitTransfer failed during warmup (NUMA %d): %d\n",
                        numa_buffers[n].numa_node, ret);
                for (auto h : handles) comm.releaseTransfer(h);
                return 1;
            }
        }
        for (auto h : handles) comm.releaseTransfer(h);
    }
    printf("Warmup done.\n\n");

    // ---- Timed iterations ----
    std::vector<double> durations_ms;         // wall time per iteration
    std::vector<std::vector<double>> per_numa_ms(num_numas);  // per-NUMA internal time
    durations_ms.reserve(cfg.iterations);
    for (size_t n = 0; n < num_numas; ++n) {
        per_numa_ms[n].reserve(cfg.iterations);
    }

    for (int i = 0; i < cfg.iterations; ++i) {
        auto wall_start = std::chrono::steady_clock::now();

        // Submit all NUMAs
        std::vector<TransferHandle> handles;
        handles.reserve(num_numas);
        for (size_t n = 0; n < num_numas; ++n) {
            uintptr_t local_addr = reinterpret_cast<uintptr_t>(numa_buffers[n].ptr);
            TransferHandle handle = comm.scatterAsync(
                local_addr, host_list, remote_addrs_per_numa[n], lengths);
            if (handle == INVALID_TRANSFER_HANDLE) {
                fprintf(stderr, "scatterAsync failed at iteration %d (NUMA %d)\n",
                        i, numa_buffers[n].numa_node);
                for (auto h : handles) comm.releaseTransfer(h);
                return 1;
            }
            handles.push_back(handle);
        }

        // Wait all
        for (size_t n = 0; n < num_numas; ++n) {
            int ret = comm.waitTransfer(handles[n], -1);
            if (ret != 0) {
                fprintf(stderr, "waitTransfer failed at iteration %d (NUMA %d): %d\n",
                        i, numa_buffers[n].numa_node, ret);
                for (auto h : handles) comm.releaseTransfer(h);
                return 1;
            }
        }

        auto wall_end = std::chrono::steady_clock::now();
        double wall_ms = std::chrono::duration<double, std::milli>(
            wall_end - wall_start).count();

        // Collect per-NUMA internal timing
        double max_internal_ms = 0;
        printf("  [%2d] wall=%.3f ms", i, wall_ms);
        for (size_t n = 0; n < num_numas; ++n) {
            TransferResult result = comm.getTransferResult(handles[n]);
            comm.releaseTransfer(handles[n]);
            per_numa_ms[n].push_back(result.elapsed_ms);
            if (result.elapsed_ms > max_internal_ms) {
                max_internal_ms = result.elapsed_ms;
            }
            if (num_numas > 1) {
                double numa_bw_gbps = (per_numa_size * 8.0) / (result.elapsed_ms * 1e6);
                double numa_bw_gbs = (per_numa_size / 1e9) / (result.elapsed_ms / 1e3);
                printf("  NUMA%d=%.3f ms (%.2f Gbps, %.2f GB/s)",
                       numa_buffers[n].numa_node, result.elapsed_ms,
                       numa_bw_gbps, numa_bw_gbs);
            }
        }

        // Use max internal time across NUMAs as the effective duration
        durations_ms.push_back(max_internal_ms);

        double agg_bw_gbps = (total_size * 8.0) / (max_internal_ms * 1e6);
        double agg_bw_gbs = (total_size / 1e9) / (max_internal_ms / 1e3);
        if (num_numas == 1) {
            printf("  internal=%.3f ms  BW=%.2f Gbps (%.2f GB/s)\n",
                   max_internal_ms, agg_bw_gbps, agg_bw_gbs);
        } else {
            printf("  => Agg: %.3f ms, %.2f Gbps (%.2f GB/s)\n",
                   max_internal_ms, agg_bw_gbps, agg_bw_gbs);
        }
    }

    // ---- Summary ----
    double sum_ms = 0, min_ms = 1e9, max_ms = 0;
    for (double d : durations_ms) {
        sum_ms += d;
        if (d < min_ms) min_ms = d;
        if (d > max_ms) max_ms = d;
    }
    double avg_ms = sum_ms / cfg.iterations;
    double avg_bw_gbps = (total_size * 8.0) / (avg_ms * 1e6);
    double avg_bw_gbs = (total_size / 1e9) / (avg_ms / 1e3);
    double min_bw_gbps = (total_size * 8.0) / (min_ms * 1e6);
    double min_bw_gbs = (total_size / 1e9) / (min_ms / 1e3);
    double max_bw_gbps = (total_size * 8.0) / (max_ms * 1e6);
    double max_bw_gbs = (total_size / 1e9) / (max_ms / 1e3);

    printf("\n--- %s Summary (%zu targets, %zu NUMAs) ---\n",
           mem_type_label, host_list.size(), num_numas);
    printf("  Aggregate Avg: %.3f ms (%.2f Gbps, %.2f GB/s)\n",
           avg_ms, avg_bw_gbps, avg_bw_gbs);
    printf("  Aggregate Min: %.3f ms (%.2f Gbps, %.2f GB/s)\n",
           min_ms, min_bw_gbps, min_bw_gbs);
    printf("  Aggregate Max: %.3f ms (%.2f Gbps, %.2f GB/s)\n",
           max_ms, max_bw_gbps, max_bw_gbs);

    // Per-NUMA summary
    if (num_numas > 1) {
        for (size_t n = 0; n < num_numas; ++n) {
            double ns = 0, nmin = 1e9, nmax = 0;
            for (double d : per_numa_ms[n]) {
                ns += d;
                if (d < nmin) nmin = d;
                if (d > nmax) nmax = d;
            }
            double navg = ns / cfg.iterations;
            double navg_gbps = (per_numa_size * 8.0) / (navg * 1e6);
            double navg_gbs = (per_numa_size / 1e9) / (navg / 1e3);
            double nmin_gbps = (per_numa_size * 8.0) / (nmin * 1e6);
            double nmin_gbs = (per_numa_size / 1e9) / (nmin / 1e3);
            double nmax_gbps = (per_numa_size * 8.0) / (nmax * 1e6);
            double nmax_gbs = (per_numa_size / 1e9) / (nmax / 1e3);
            printf("  NUMA %d: Avg %.3f ms (%.2f Gbps, %.2f GB/s), "
                   "Min %.3f ms (%.2f Gbps, %.2f GB/s), "
                   "Max %.3f ms (%.2f Gbps, %.2f GB/s)\n",
                   numa_buffers[n].numa_node,
                   navg, navg_gbps, navg_gbs,
                   nmin, nmin_gbps, nmin_gbs,
                   nmax, nmax_gbps, nmax_gbs);
        }
    }
    printf("\n");

    return 0;
}

// =====================================================================
// Main
// =====================================================================

int main(int argc, char *argv[]) {
    TestConfig cfg;
    if (!parseArgs(argc, argv, cfg)) {
        return 1;
    }

    // Dispatch based on mode
    if (cfg.mode == MODE_TARGET) {
        return runTargetMode(cfg);
    }

    // --- Initiator mode (original logic) ---
    const size_t num_targets = cfg.targets.size();
    const size_t total_buffer_size = cfg.buffer_size * num_targets;
    const size_t num_initiator_numas = cfg.initiator_numas.size();

    // Determine what to run
    bool run_dram = true;
    bool run_hbm = false;
#ifdef USE_CUDA
    if (cfg.gpu_device >= 0) {
        run_hbm = true;
        if (!cfg.run_both) {
            run_dram = false;  // --gpu without --both: HBM only
        }
    }
#else
    if (cfg.gpu_device >= 0) {
        fprintf(stderr, "Warning: --gpu specified but USE_CUDA not enabled. "
                        "Running DRAM test only.\n");
    }
#endif

    // ---- Initialize MPComm ----
    printf("Initializing MPComm (host=%s, device=%s)...\n",
           cfg.host_id.c_str(),
           cfg.device.empty() ? "auto" : cfg.device.c_str());

    MPComm comm;
    int ret = comm.init(cfg.host_id, cfg.device, 0);
    if (ret != 0) {
        fprintf(stderr, "MPComm init failed: %d\n", ret);
        return 1;
    }
    printf("MPComm initialized with %zu NICs\n", comm.getNumNics());

    // ---- Allocate and register per-NUMA DRAM buffers ----
    std::vector<InitiatorNumaBuffer> dram_numa_buffers;
    if (run_dram) {
        printf("Allocating DRAM buffers (%zu bytes per NUMA = %zu per target x %zu targets) "
               "on %zu NUMA node(s)...\n",
               total_buffer_size, cfg.buffer_size, num_targets, num_initiator_numas);
        for (size_t n = 0; n < num_initiator_numas; ++n) {
            int numa_node = cfg.initiator_numas[n];
            InitiatorNumaBuffer nbuf;
            nbuf.numa_node = numa_node;
            nbuf.alloc_size = total_buffer_size;
            nbuf.ptr = allocDRAM(total_buffer_size, numa_node);
            if (!nbuf.ptr) {
                fprintf(stderr, "Failed to allocate DRAM buffer on NUMA %d\n", numa_node);
                for (auto &b : dram_numa_buffers) {
                    comm.unregisterMemory(b.ptr);
                    freeDRAM(b.ptr, b.alloc_size);
                }
                comm.shutdown();
                return 1;
            }
            ret = comm.registerMemory(nbuf.ptr, total_buffer_size);
            if (ret != 0) {
                fprintf(stderr, "Failed to register DRAM memory on NUMA %d: %d\n",
                        numa_node, ret);
                freeDRAM(nbuf.ptr, total_buffer_size);
                for (auto &b : dram_numa_buffers) {
                    comm.unregisterMemory(b.ptr);
                    freeDRAM(b.ptr, b.alloc_size);
                }
                comm.shutdown();
                return 1;
            }
            printf("  NUMA %d: DRAM buffer registered at %p (%zu bytes)\n",
                   numa_node, nbuf.ptr, total_buffer_size);
            dram_numa_buffers.push_back(nbuf);
        }
    }

    // ---- Allocate and register HBM buffer (single, not per-NUMA) ----
    void *hbm_buffer = nullptr;
    std::vector<InitiatorNumaBuffer> hbm_numa_buffers;
#ifdef USE_CUDA
    if (run_hbm) {
        printf("Allocating HBM buffer (%zu bytes = %zu per target x %zu targets) on GPU %d...\n",
               total_buffer_size, cfg.buffer_size, num_targets, cfg.gpu_device);
        hbm_buffer = allocHBM(total_buffer_size, cfg.gpu_device);
        if (!hbm_buffer) {
            fprintf(stderr, "Failed to allocate HBM buffer\n");
            for (auto &b : dram_numa_buffers) {
                comm.unregisterMemory(b.ptr);
                freeDRAM(b.ptr, b.alloc_size);
            }
            comm.shutdown();
            return 1;
        }
        ret = comm.registerMemory(hbm_buffer, total_buffer_size);
        if (ret != 0) {
            fprintf(stderr, "Failed to register HBM memory: %d\n", ret);
            freeHBM(hbm_buffer);
            for (auto &b : dram_numa_buffers) {
                comm.unregisterMemory(b.ptr);
                freeDRAM(b.ptr, b.alloc_size);
            }
            comm.shutdown();
            return 1;
        }
        printf("HBM buffer registered at %p\n", hbm_buffer);
        // Wrap HBM into a single InitiatorNumaBuffer for the benchmark
        InitiatorNumaBuffer hbuf;
        hbuf.ptr = hbm_buffer;
        hbuf.alloc_size = total_buffer_size;
        hbuf.numa_node = 0;  // GPU has no NUMA concept, use 0
        hbm_numa_buffers.push_back(hbuf);
    }
#endif

    // ---- Connect to all targets and query remote buffers ----
    // We need per-NUMA remote addresses:
    //   remote_addrs_per_numa[numa_idx][target_idx] = remote buffer addr matching that NUMA
    {
        std::vector<std::string> host_list;
        std::vector<size_t> lengths;
        // remote_addrs_per_numa[n][t] for DRAM
        std::vector<std::vector<uintptr_t>> dram_remote_addrs(num_initiator_numas);
        // For HBM: always use first remote buffer (single NUMA)
        std::vector<std::vector<uintptr_t>> hbm_remote_addrs(1);

        for (size_t t = 0; t < num_targets; ++t) {
            const auto &target = cfg.targets[t];

            printf("Connecting to target[%zu] %s (%s:%d)...\n",
                   t, target.host_id.c_str(),
                   target.tcp_addr.c_str(), target.tcp_port);

            ret = comm.connect(target.host_id, target.tcp_addr, target.tcp_port);
            if (ret != 0) {
                fprintf(stderr, "Failed to connect to target[%zu] %s: %d\n",
                        t, target.host_id.c_str(), ret);
                goto cleanup;
            }
            printf("Connected to %s.\n", target.host_id.c_str());

            // Query all remote buffers from this target
            RemoteBufferInfo remote_info;
            ret = comm.queryRemoteBuffer(
                target.host_id, target.tcp_addr, target.tcp_port, remote_info);
            if (ret != 0 || remote_info.buffers.empty()) {
                fprintf(stderr, "Failed to query remote buffer from target[%zu] %s: %d\n",
                        t, target.host_id.c_str(), ret);
                goto cleanup;
            }

            printf("  Remote buffers from %s: %zu buffer(s)\n",
                   target.host_id.c_str(), remote_info.buffers.size());
            for (size_t b = 0; b < remote_info.buffers.size(); ++b) {
                auto &buf = remote_info.buffers[b];
                printf("    [%zu] addr=0x%lx, length=%lu, numa=%d\n",
                       b, (unsigned long)buf.addr, (unsigned long)buf.length,
                       buf.numa_node);
            }

            // Update rkeys using first buffer (all buffers share same NIC rkeys)
            ret = comm.updateRemoteMemoryInfo(target.host_id,
                                               remote_info.buffers[0].rkeys);
            if (ret != 0) {
                fprintf(stderr, "Failed to update remote memory info for target[%zu] %s: %d\n",
                        t, target.host_id.c_str(), ret);
                goto cleanup;
            }

            // Match initiator NUMA nodes to remote NUMA buffers
            for (size_t n = 0; n < num_initiator_numas; ++n) {
                int want_numa = cfg.initiator_numas[n];
                // Try to find a remote buffer with matching NUMA node
                const RemoteBufferEntry *matched = nullptr;
                for (const auto &buf : remote_info.buffers) {
                    if (buf.numa_node == want_numa) {
                        matched = &buf;
                        break;
                    }
                }
                if (!matched) {
                    // Fallback: use the Nth buffer if available, otherwise first
                    if (n < remote_info.buffers.size()) {
                        matched = &remote_info.buffers[n];
                    } else {
                        matched = &remote_info.buffers[0];
                    }
                    if (num_initiator_numas > 1) {
                        printf("  Warning: No remote NUMA %d buffer for target %s, "
                               "using NUMA %d buffer at 0x%lx\n",
                               want_numa, target.host_id.c_str(),
                               matched->numa_node, (unsigned long)matched->addr);
                    }
                }
                dram_remote_addrs[n].push_back(matched->addr);
            }

            // HBM always uses first remote buffer
            if (run_hbm) {
                hbm_remote_addrs[0].push_back(remote_info.buffers[0].addr);
            }

            host_list.push_back(target.host_id);
            lengths.push_back(cfg.buffer_size);
        }

        printf("\nAll %zu targets connected and ready.\n", num_targets);

        // ---- Run DRAM scatter benchmark ----
        if (run_dram) {
            ret = runScatterBenchmark(comm, cfg, dram_numa_buffers,
                                      host_list, dram_remote_addrs, lengths, "DRAM");
            if (ret != 0) goto cleanup;
        }

        // ---- Run HBM scatter benchmark ----
        if (run_hbm) {
            ret = runScatterBenchmark(comm, cfg, hbm_numa_buffers,
                                      host_list, hbm_remote_addrs, lengths, "HBM (GPU)");
            if (ret != 0) goto cleanup;
        }
    }

    ret = 0;

cleanup:
    // ---- Cleanup ----
#ifdef USE_CUDA
    if (hbm_buffer) {
        comm.unregisterMemory(hbm_buffer);
        freeHBM(hbm_buffer);
    }
#endif
    for (auto &b : dram_numa_buffers) {
        if (b.ptr) {
            comm.unregisterMemory(b.ptr);
            freeDRAM(b.ptr, b.alloc_size);
        }
    }
    comm.shutdown();

    return ret;
}
