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

// MPComm C++ Scatter / Gather / Broadcast Performance Test
//
// Demonstrates scatter_async, gather_async, and broadcast_async API usage
// with DRAM and HBM (GPU) memory.
// Supports initiator, target, and "both" modes in a single binary.
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
//   ./scatter_test --target t1:<ip1>:12345 --target t2:<ip2>:12345 --size 500000000 --iterations 20
//
//   # HBM (GPU) scatter to multiple targets:
//   ./scatter_test --target t1:<ip1>:12345 --target t2:<ip2>:12345 --gpu 0
//
//   # Both DRAM and HBM:
//   ./scatter_test --target t1:<ip1>:12345 --target t2:<ip2>:12345 --gpu 0 --both
//
//   # Multi-NUMA initiator (dual NUMA buffers, each NUMA sends via its local NICs):
//   ./scatter_test --target t1:<ip1>:12345 --target t2:<ip2>:12345 --num-numas 0,1
//
//   # Run specific test types (default: scatter,gather,broadcast):
//   ./scatter_test --target t1:<ip1>:12345 --test-type scatter
//   ./scatter_test --target t1:<ip1>:12345 --test-type gather
//   ./scatter_test --target t1:<ip1>:12345 --test-type broadcast
//   ./scatter_test --target t1:<ip1>:12345 --test-type scatter,gather,broadcast
//
//   # Single-target put / get (RDMA WRITE / READ to/from one peer):
//   ./scatter_test --target t1:<ip1>:12345 --test-type put
//   ./scatter_test --target t1:<ip1>:12345 --test-type get
//   ./scatter_test --target t1:<ip1>:12345 --test-type put,get
//   # NOTE: put and get require exactly one --target.
//
// Both mode (a single process simultaneously acts as target for some peers
// and as initiator toward other peers, sharing one MPComm instance):
//   ./scatter_test --mode both --host-id 29.1.1.1:12345 --tcp-port 12345 \
//       --serve 1001:2G:0 \
//       --serve 1002:2G:0 \
//       --target B:29.1.1.2:12345:2001:0 \
//       --target C:29.1.1.3:12345:2002:0
//
//   --serve  CHANNEL_ID:SIZE:NUMA
//       Allocate a target buffer on NUMA and publish it under a composite tag
//       ((CHANNEL_ID<<16)|NUMA). Repeatable. Each channel_id MUST be unique
//       within this process; the remote initiator must know the same
//       channel_id to query this buffer.
//
//   --target HOST_ID:ADDR:PORT[:CHANNEL_ID:PEER_NUMA]
//       When the optional trailing ":CHANNEL_ID:PEER_NUMA" suffix is present
//       the initiator benchmark will query the remote buffer using the
//       composite tag ((CHANNEL_ID<<16)|PEER_NUMA) instead of the local
//       initiator NUMA. Each --target can specify its own pair.
//
//   --job LABEL
//       In both mode, groups subsequent --target entries under one logical
//       "job". Each job is benchmarked independently (its own connect,
//       allocate, scatter/gather/broadcast round), and its log lines are
//       prefixed with "[job=LABEL] " so an orchestrator can attribute each
//       summary block. Passing an empty label clears the grouping.
//
// After every initiator benchmark completes, a "both"-mode process keeps
// running (serving published buffers) until it receives SIGINT/SIGTERM, so
// that peers still performing RDMA reads/writes against us do not error out.

#include <mpcomm.h>

#include <numa.h>
#include <numaif.h>
#include <sys/stat.h>

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

#ifdef USE_CUDA
#include <cuda.h>
#endif

using namespace mpcomm;

// =====================================================================
// Transfer operation type
// =====================================================================

enum class TestOpType {
    SCATTER = 0,
    GATHER,
    BROADCAST,
    PUT,
    GET,
};

static const char *opTypeName(TestOpType op) {
    switch (op) {
        case TestOpType::SCATTER:   return "scatter";
        case TestOpType::GATHER:    return "gather";
        case TestOpType::BROADCAST: return "broadcast";
        case TestOpType::PUT:       return "put";
        case TestOpType::GET:       return "get";
    }
    return "unknown";
}

// put/get only support a single (initiator, target) pair.
static inline bool isSingleTargetOp(TestOpType op) {
    return op == TestOpType::PUT || op == TestOpType::GET;
}

// =====================================================================
// Signal handling for target / both mode graceful shutdown
// =====================================================================

static std::atomic<bool> g_stop_requested{false};

static void signalHandler(int signum) {
    printf("\n[scatter_test] Received signal %d, stopping...\n", signum);
    g_stop_requested.store(true);
}

// =====================================================================
// Helpers
// =====================================================================

// A single remote target description for the initiator benchmark.
// channel_id/peer_numa are optional; when channel_id == 0 the original
// "match by initiator NUMA" fallback is used (backward compatible).
struct TargetInfo {
    std::string host_id;
    std::string tcp_addr;
    int tcp_port = 0;
    int channel_id = 0;   // 0 = not specified (use legacy NUMA matching)
    int peer_numa = 0;    // used only if channel_id > 0
    std::string job_label;  // empty = default job; otherwise which logical job
                           //   this target belongs to (both mode only)
};

// A single local "served" buffer, exposed to remote peers via publishBuffer.
// Each entry produces one registered + published buffer in "both" mode.
struct ServeSpec {
    int channel_id = 0;   // must be > 0, unique within the process
    size_t size = 0;
    int numa = 0;
};

enum RunMode {
    MODE_INITIATOR = 0,
    MODE_TARGET = 1,
    MODE_BOTH = 2,
};

// Encode (channel_id, numa) -> 32-bit composite tag used as the
// numa_node argument of publishBuffer / queryRemoteBufferByNuma.
// Layout: (channel_id << 16) | (numa & 0xFFFF).
// channel_id == 0 means "no tag" (legacy behaviour).
static inline int encodeBufferTag(int channel_id, int numa) {
    if (channel_id <= 0) {
        return numa;  // legacy: tag equals the real NUMA node
    }
    return (channel_id << 16) | (numa & 0xFFFF);
}

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
    int batch_size = 1;                // number of async requests per batch
    int gpu_device = -1;               // -1 = CPU only
    bool run_both = false;             // run both DRAM and HBM
    std::vector<int> initiator_numas;  // NUMA nodes for initiator buffers
    std::vector<TestOpType> test_types;  // which operations to benchmark

    // --- Target mode ---
    size_t target_buffer_size = 2ULL * 1024 * 1024 * 1024;  // 2 GB default
    std::vector<int> numa_nodes;       // NUMA nodes to allocate buffers on
    bool verbose = false;

    // --- Both mode ---
    std::vector<ServeSpec> serves;     // buffers to publish for remote peers
    // Tracks the most recent --job label seen during argument parsing so that
    // subsequent --target entries get attached to that logical job. Reset to
    // empty when a new --job is seen.
    std::string _current_job_label;

    // Optional: after publishing buffers and reaching the "Ready" marker,
    // block until this file appears on the local filesystem. Drivers use
    // this as a global barrier so that initiator workloads do not start
    // connecting before every peer has finished publishing.
    std::string wait_go_file;
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
    for (auto &c : suffix) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));

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

// Split a colon-separated string into tokens. Empty tokens are preserved
// (so "a::b" splits to {"a", "", "b"}).
static std::vector<std::string> splitColons(const std::string &str) {
    std::vector<std::string> out;
    size_t start = 0;
    while (true) {
        size_t pos = str.find(':', start);
        if (pos == std::string::npos) {
            out.push_back(str.substr(start));
            break;
        }
        out.push_back(str.substr(start, pos - start));
        start = pos + 1;
    }
    return out;
}

static void printUsage(const char *prog) {
    printf("MPComm C++ Scatter Test (initiator + target in one binary)\n\n");
    printf("Usage:\n");
    printf("  Target mode:\n");
    printf("    %s --mode target --host-id HOST:PORT --tcp-port PORT [options]\n\n", prog);
    printf("  Initiator mode (default):\n");
    printf("    %s --target host_id:addr:port [--target ...] [options]\n\n", prog);
    printf("  Both mode (initiator + target in one MPComm instance):\n");
    printf("    %s --mode both --host-id HOST:PORT --tcp-port PORT \\\n", prog);
    printf("        --serve CHANNEL_ID:SIZE:NUMA [--serve ...] \\\n");
    printf("        --target host_id:addr:port:CHANNEL_ID:PEER_NUMA [--target ...]\n\n");
    printf("Common Options:\n");
    printf("  --mode MODE                  'initiator' (default), 'target', or 'both'\n");
    printf("  --host-id ID                 Local host ID (default: test:0)\n");
    printf("  --device DEVS                RDMA devices, comma-separated (default: auto)\n");
    printf("  --tcp-port PORT              TCP port for metadata exchange (default: 0=auto)\n");
    printf("  --num-numas NODES            Comma-separated NUMA nodes (default: 0)\n");
    printf("\nTarget Mode Options:\n");
    printf("  --buffer-size SIZE           Buffer size with suffix K/M/G/T (default: 2G)\n");
    printf("  --verbose                    Print periodic buffer status\n");
    printf("\nInitiator Mode Options:\n");
    printf("  --target HOST_ID:ADDR:PORT[:CHANNEL_ID:PEER_NUMA]\n");
    printf("                               Remote target (required, repeatable). The optional\n");
    printf("                               trailing ':CHANNEL_ID:PEER_NUMA' selects a specific\n");
    printf("                               remote publish buffer (for 'both' mode).\n");
    printf("  --size BYTES                 Buffer size per target in bytes (default: 1000000000)\n");
    printf("  --iterations N               Number of timed iterations (default: 10)\n");
    printf("  --warmup N                   Number of warmup iterations (default: 2)\n");
    printf("  --batch-size N               Async requests per batch (default: 1)\n");
    printf("  --gpu DEVICE_ID              GPU device for HBM test (default: -1, CPU only)\n");
    printf("  --both                       Run both DRAM and HBM tests\n");
    printf("  --test-type TYPES            Comma-separated test types:\n");
    printf("                               scatter,gather,broadcast,put,get\n");
    printf("                               (default: scatter,gather,broadcast)\n");
    printf("                               NOTE: put/get require exactly one --target.\n");
    printf("\nBoth Mode Options:\n");
    printf("  --serve CHANNEL_ID:SIZE:NUMA Publish a target buffer tagged by CHANNEL_ID on NUMA.\n");
    printf("                               Repeatable. Each CHANNEL_ID must be unique in this\n");
    printf("                               process; remote initiators look it up via --target.\n");
    printf("  --job LABEL                  Group subsequent --target entries under a logical\n");
    printf("                               job. Each job is benchmarked independently and its\n");
    printf("                               log lines are prefixed with '[job=LABEL] '. An empty\n");
    printf("                               LABEL clears the grouping.\n");
    printf("  --wait-go-file PATH          After publishing buffers and printing the 'Ready'\n");
    printf("                               marker, block until PATH appears on the local\n");
    printf("                               filesystem before starting the initiator workload.\n");
    printf("                               Used by orchestrators as a global barrier.\n");
    printf("\nExamples:\n");
    printf("  # Target (remote host):\n");
    printf("  %s --mode target --host-id 29.160.42.103:12345 --tcp-port 12345 --buffer-size 2G\n", prog);
    printf("  %s --mode target --host-id 29.160.42.103:12345 --tcp-port 12345 "
           "--buffer-size 2G --num-numas 0,1\n", prog);
    printf("\n  # Initiator (local host):\n");
    printf("  %s --target t1:<ip1>:12345 --target t2:<ip2>:12345\n", prog);
    printf("  %s --target t1:<ip1>:12345 --gpu 0 --both\n", prog);
    printf("  # Multi-NUMA initiator:\n");
    printf("  %s --target t1:<ip1>:12345 --num-numas 0,1\n", prog);
    printf("\n  # Both (single process, multiple publish buffers + multiple benchmarks):\n");
    printf("  %s --mode both --host-id A:12345 --tcp-port 12345 \\\n", prog);
    printf("      --serve 1001:2G:0 --serve 1002:2G:0 \\\n");
    printf("      --target B:<ip2>:12345:2001:0 --target C:<ip3>:12345:2002:0\n");
}

// Parse a --target argument. Accepts:
//   host_id:addr:port                          (channel_id=0, peer_numa=0)
//   host_id:addr:port:channel_id:peer_numa     (explicit tag)
//
// host_id itself may contain ':' (e.g. "ip:port" form used by --mode both).
// We therefore disambiguate by counting segments from the *right*:
//   >=5 segments: last 2 are channel_id:peer_numa, preceding 2 are addr:port,
//                 everything before that is the host_id (rejoined with ':').
//   ==3 segments: host_id:addr:port (host_id has no ':'), channel_id=0.
static bool parseTarget(const std::string &val, TargetInfo &info) {
    std::vector<std::string> parts = splitColons(val);
    const size_t n = parts.size();
    if (n != 3 && n < 5) {
        fprintf(stderr, "Error: --target format must be host_id:tcp_addr:tcp_port "
                        "or host_id:tcp_addr:tcp_port:channel_id:peer_numa "
                        "(got '%s')\n", val.c_str());
        return false;
    }

    size_t addr_idx, port_idx;
    bool has_tag = (n >= 5);
    if (has_tag) {
        // Last 2 segments are channel_id:peer_numa.
        // The two immediately before them are addr:port.
        // Everything before that (>=1 segment) forms host_id.
        addr_idx = n - 4;
        port_idx = n - 3;
    } else {
        // n == 3: host_id:addr:port
        addr_idx = 1;
        port_idx = 2;
    }

    // Rejoin host_id segments.
    info.host_id = parts[0];
    for (size_t k = 1; k < addr_idx; ++k) {
        info.host_id += ":";
        info.host_id += parts[k];
    }
    info.tcp_addr = parts[addr_idx];
    try {
        info.tcp_port = std::stoi(parts[port_idx]);
    } catch (const std::exception &e) {
        fprintf(stderr, "Error: invalid --target port '%s'\n",
                parts[port_idx].c_str());
        return false;
    }
    if (has_tag) {
        try {
            info.channel_id = std::stoi(parts[n - 2]);
            info.peer_numa = std::stoi(parts[n - 1]);
        } catch (const std::exception &e) {
            fprintf(stderr, "Error: invalid --target channel_id/peer_numa in '%s'\n",
                    val.c_str());
            return false;
        }
        if (info.channel_id <= 0) {
            fprintf(stderr, "Error: --target channel_id must be > 0 (got %d)\n",
                    info.channel_id);
            return false;
        }
    }
    return true;
}

// Parse a --serve argument: CHANNEL_ID:SIZE:NUMA
static bool parseServe(const std::string &val, ServeSpec &spec) {
    std::vector<std::string> parts = splitColons(val);
    if (parts.size() != 3) {
        fprintf(stderr, "Error: --serve format must be channel_id:size:numa "
                        "(got '%s')\n", val.c_str());
        return false;
    }
    try {
        spec.channel_id = std::stoi(parts[0]);
        spec.size = parseSize(parts[1]);
        spec.numa = std::stoi(parts[2]);
    } catch (const std::exception &e) {
        fprintf(stderr, "Error: invalid --serve value '%s'\n", val.c_str());
        return false;
    }
    if (spec.channel_id <= 0) {
        fprintf(stderr, "Error: --serve channel_id must be > 0 (got %d)\n",
                spec.channel_id);
        return false;
    }
    if (spec.size == 0) {
        fprintf(stderr, "Error: --serve size must be > 0 (got '%s')\n",
                parts[1].c_str());
        return false;
    }
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
            } else if (mode_str == "both") {
                cfg.mode = MODE_BOTH;
            } else {
                fprintf(stderr, "Error: --mode must be 'initiator', 'target', or 'both'\n");
                return false;
            }
        } else if (arg == "--target" && i + 1 < argc) {
            TargetInfo info;
            if (!parseTarget(argv[++i], info)) {
                return false;
            }
            info.job_label = cfg._current_job_label;
            cfg.targets.push_back(std::move(info));
        } else if (arg == "--job" && i + 1 < argc) {
            // Group subsequent --target entries under this logical job name.
            // An empty value ("--job \"\"") clears the grouping.
            cfg._current_job_label = argv[++i];
        } else if (arg == "--serve" && i + 1 < argc) {
            ServeSpec spec;
            if (!parseServe(argv[++i], spec)) {
                return false;
            }
            cfg.serves.push_back(std::move(spec));
        } else if (arg == "--host-id" && i + 1 < argc) {
            cfg.host_id = argv[++i];
        } else if (arg == "--device" && i + 1 < argc) {
            cfg.device = argv[++i];
        } else if (arg == "--tcp-port" && i + 1 < argc) {
            cfg.tcp_port = std::stoi(argv[++i]);
        } else if (arg == "--size" && i + 1 < argc) {
            cfg.buffer_size = parseSize(argv[++i]);
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
        } else if (arg == "--batch-size" && i + 1 < argc) {
            cfg.batch_size = std::stoi(argv[++i]);
            if (cfg.batch_size < 1) cfg.batch_size = 1;
        } else if (arg == "--gpu" && i + 1 < argc) {
            cfg.gpu_device = std::stoi(argv[++i]);
        } else if (arg == "--both") {
            cfg.run_both = true;
        } else if (arg == "--test-type" && i + 1 < argc) {
            std::string types_str = argv[++i];
            std::istringstream tss(types_str);
            std::string token;
            while (std::getline(tss, token, ',')) {
                if (token == "scatter") {
                    cfg.test_types.push_back(TestOpType::SCATTER);
                } else if (token == "gather") {
                    cfg.test_types.push_back(TestOpType::GATHER);
                } else if (token == "broadcast") {
                    cfg.test_types.push_back(TestOpType::BROADCAST);
                } else if (token == "put") {
                    cfg.test_types.push_back(TestOpType::PUT);
                } else if (token == "get") {
                    cfg.test_types.push_back(TestOpType::GET);
                } else {
                    fprintf(stderr, "Error: unknown test type '%s' "
                            "(must be scatter, gather, broadcast, put, or get)\n",
                            token.c_str());
                    return false;
                }
            }
        } else if (arg == "--wait-go-file" && i + 1 < argc) {
            cfg.wait_go_file = argv[++i];
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
        if (cfg.test_types.empty()) {
            cfg.test_types.push_back(TestOpType::SCATTER);
            cfg.test_types.push_back(TestOpType::GATHER);
            cfg.test_types.push_back(TestOpType::BROADCAST);
        }
    } else if (cfg.mode == MODE_TARGET) {
        // Target mode defaults
        if (cfg.numa_nodes.empty()) {
            cfg.numa_nodes.push_back(0);
        }
    } else {
        // both mode: at least one --serve or one --target is required
        if (cfg.serves.empty() && cfg.targets.empty()) {
            fprintf(stderr, "Error: --mode both requires at least one --serve or --target\n");
            printUsage(argv[0]);
            return false;
        }
        // Reject duplicate serve channel_ids up front.
        for (size_t i = 0; i < cfg.serves.size(); ++i) {
            for (size_t j = i + 1; j < cfg.serves.size(); ++j) {
                if (cfg.serves[i].channel_id == cfg.serves[j].channel_id) {
                    fprintf(stderr, "Error: duplicate --serve channel_id %d\n",
                            cfg.serves[i].channel_id);
                    return false;
                }
            }
        }
        if (cfg.initiator_numas.empty()) {
            cfg.initiator_numas.push_back(0);
        }
        if (cfg.test_types.empty()) {
            cfg.test_types.push_back(TestOpType::SCATTER);
            cfg.test_types.push_back(TestOpType::GATHER);
            cfg.test_types.push_back(TestOpType::BROADCAST);
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
// Transfer performance benchmark (multi-NUMA aware)
// Supports scatter, gather, and broadcast operations.
// =====================================================================

// Per-NUMA buffer info for initiator
struct InitiatorNumaBuffer {
    void *ptr = nullptr;
    size_t alloc_size = 0;
    int numa_node = -1;
};

// Helper: issue a single async transfer based on the operation type
static TransferHandle issueTransferAsync(
    MPComm &comm,
    TestOpType op,
    uintptr_t local_addr,
    const std::vector<std::string> &host_list,
    const std::vector<uintptr_t> &remote_addrs,
    const std::vector<size_t> &lengths) {
    switch (op) {
        case TestOpType::SCATTER:
            return comm.scatterAsync(local_addr, host_list, remote_addrs, lengths);
        case TestOpType::GATHER:
            return comm.gatherAsync(local_addr, host_list, remote_addrs, lengths);
        case TestOpType::BROADCAST:
            // broadcastAsync uses a single length (same data to all targets)
            // Use the first element of lengths as the broadcast length.
            if (lengths.empty()) return INVALID_TRANSFER_HANDLE;
            return comm.broadcastAsync(local_addr, lengths[0], host_list, remote_addrs);
        case TestOpType::PUT:
            // put: single (initiator, target) pair, RDMA WRITE local -> remote.
            if (host_list.empty() || remote_addrs.empty() || lengths.empty()) {
                return INVALID_TRANSFER_HANDLE;
            }
            return comm.putAsync(local_addr, host_list[0],
                                 remote_addrs[0], lengths[0]);
        case TestOpType::GET:
            // get: single (initiator, target) pair, RDMA READ remote -> local.
            if (host_list.empty() || remote_addrs.empty() || lengths.empty()) {
                return INVALID_TRANSFER_HANDLE;
            }
            return comm.getAsync(local_addr, host_list[0],
                                 remote_addrs[0], lengths[0]);
    }
    return INVALID_TRANSFER_HANDLE;
}

static int runTransferBenchmark(
    MPComm &comm,
    const TestConfig &cfg,
    TestOpType op_type,
    const std::vector<InitiatorNumaBuffer> &numa_buffers,
    const std::vector<std::string> &host_list,
    // per-NUMA remote addresses: remote_addrs_per_numa[numa_idx][target_idx]
    const std::vector<std::vector<uintptr_t>> &remote_addrs_per_numa,
    const std::vector<size_t> &lengths,
    const char *mem_type_label) {
    const char *op_name_upper = "";
    const char *op_direction = "";
    switch (op_type) {
        case TestOpType::SCATTER:
            op_name_upper = "Scatter";
            op_direction = "local -> remote";
            break;
        case TestOpType::GATHER:
            op_name_upper = "Gather";
            op_direction = "remote -> local";
            break;
        case TestOpType::BROADCAST:
            op_name_upper = "Broadcast";
            op_direction = "local -> all remotes (same data)";
            break;
        case TestOpType::PUT:
            op_name_upper = "Put";
            op_direction = "local -> remote (single target, RDMA WRITE)";
            break;
        case TestOpType::GET:
            op_name_upper = "Get";
            op_direction = "remote -> local (single target, RDMA READ)";
            break;
    }

    // For broadcast, the effective per-NUMA size is length * num_targets
    // (same data sent to each target). For put/get there is exactly one
    // target so the per-NUMA size is simply lengths[0]. For scatter/gather
    // it is the sum of per-target lengths.
    size_t per_numa_size = 0;
    if (op_type == TestOpType::BROADCAST) {
        // Broadcast sends the same block to all targets
        per_numa_size = (lengths.empty() ? 0 : lengths[0]) * host_list.size();
    } else if (op_type == TestOpType::PUT || op_type == TestOpType::GET) {
        per_numa_size = (lengths.empty() ? 0 : lengths[0]);
    } else {
        for (size_t l : lengths) per_numa_size += l;
    }
    size_t total_size = per_numa_size * numa_buffers.size();
    size_t num_numas = numa_buffers.size();

    printf("\n========================================\n");
    printf(" %s Performance: %s\n", op_name_upper, mem_type_label);
    printf(" Direction: %s\n", op_direction);
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
    printf(" Warmup: %d, Iterations: %d, Batch size: %d\n",
           cfg.warmup, cfg.iterations, cfg.batch_size);
    printf("========================================\n\n");

    const int batch_size = cfg.batch_size;

    // ---- Warmup ----
    printf("Warming up (%d iterations)...\n", cfg.warmup);
    for (int i = 0; i < cfg.warmup; ++i) {
        // Submit one async transfer per NUMA
        std::vector<TransferHandle> handles;
        handles.reserve(num_numas);
        for (size_t n = 0; n < num_numas; ++n) {
            uintptr_t local_addr = reinterpret_cast<uintptr_t>(numa_buffers[n].ptr);
            TransferHandle handle = issueTransferAsync(
                comm, op_type, local_addr, host_list,
                remote_addrs_per_numa[n], lengths);
            if (handle == INVALID_TRANSFER_HANDLE) {
                fprintf(stderr, "%sAsync failed during warmup (NUMA %d)\n",
                        op_name_upper, numa_buffers[n].numa_node);
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
    // Each iteration submits batch_size async requests per NUMA, then waits
    // for all to complete.  Data volume per iteration:
    //   per_iter_total = total_size * batch_size  (across all NUMAs)
    //   per_iter_per_numa = per_numa_size * batch_size
    const int total_iters = cfg.iterations;
    const size_t iter_total_size = total_size * (size_t)batch_size;
    const size_t iter_per_numa_size = per_numa_size * (size_t)batch_size;

    std::vector<double> durations_ms;         // wall time per iteration
    std::vector<std::vector<double>> per_numa_ms(num_numas);  // per-NUMA max internal time per iter
    durations_ms.reserve(total_iters);
    for (size_t n = 0; n < num_numas; ++n) {
        per_numa_ms[n].reserve(total_iters);
    }

    for (int iter = 0; iter < total_iters; ++iter) {
        auto wall_start = std::chrono::steady_clock::now();

        // Submit batch_size async requests per NUMA
        // handles[b][n] = handle for batch-request b, NUMA n
        std::vector<std::vector<TransferHandle>> batch_handles(batch_size);
        auto last_submit_time = std::chrono::steady_clock::time_point{};
        for (int b = 0; b < batch_size; ++b) {
            batch_handles[b].reserve(num_numas);
            for (size_t n = 0; n < num_numas; ++n) {
                uintptr_t local_addr = reinterpret_cast<uintptr_t>(numa_buffers[n].ptr);
                TransferHandle handle = issueTransferAsync(
                    comm, op_type, local_addr, host_list,
                    remote_addrs_per_numa[n], lengths);
                if (handle == INVALID_TRANSFER_HANDLE) {
                    fprintf(stderr, "%sAsync failed at iter %d, batch %d (NUMA %d)\n",
                            op_name_upper, iter, b, numa_buffers[n].numa_node);
                    // Cleanup already-submitted handles
                    for (int bb = 0; bb <= b; ++bb) {
                        for (auto h : batch_handles[bb]) {
                            comm.waitTransfer(h, -1);
                            comm.releaseTransfer(h);
                        }
                    }
                    return 1;
                }
                batch_handles[b].push_back(handle);
            }
        }
        last_submit_time = std::chrono::steady_clock::now();

        // Wait all handles in this iteration
        for (int b = 0; b < batch_size; ++b) {
            for (size_t n = 0; n < num_numas; ++n) {
                int ret = comm.waitTransfer(batch_handles[b][n], -1);
                if (ret != 0) {
                    fprintf(stderr, "waitTransfer failed at iter %d, batch %d (NUMA %d): %d\n",
                            iter, b, numa_buffers[n].numa_node, ret);
                    // Cleanup remaining handles
                    for (int bb = b; bb < batch_size; ++bb) {
                        for (size_t nn = (bb == b ? n : 0); nn < num_numas; ++nn) {
                            comm.waitTransfer(batch_handles[bb][nn], -1);
                        }
                    }
                    for (int bb = 0; bb < batch_size; ++bb) {
                        for (auto h : batch_handles[bb]) comm.releaseTransfer(h);
                    }
                    return 1;
                }
            }
        }

        auto wall_end = std::chrono::steady_clock::now();
        double wall_ms = std::chrono::duration<double, std::milli>(
            wall_end - wall_start).count();
        double submit_ms = std::chrono::duration<double, std::milli>(
            last_submit_time - wall_start).count();
        double wait_ms = std::chrono::duration<double, std::milli>(
            wall_end - last_submit_time).count();

        // Collect per-NUMA internal timing: max across all batch requests
        std::vector<double> numa_max_ms(num_numas, 0.0);
        for (int b = 0; b < batch_size; ++b) {
            for (size_t n = 0; n < num_numas; ++n) {
                TransferResult result = comm.getTransferResult(batch_handles[b][n]);
                if (result.elapsed_ms > numa_max_ms[n]) {
                    numa_max_ms[n] = result.elapsed_ms;
                }
            }
        }

        // Release all handles
        for (int b = 0; b < batch_size; ++b) {
            for (auto h : batch_handles[b]) comm.releaseTransfer(h);
        }

        // Compute iteration bandwidth using wall time
        double max_internal_ms = 0;
        for (size_t n = 0; n < num_numas; ++n) {
            if (numa_max_ms[n] > max_internal_ms) {
                max_internal_ms = numa_max_ms[n];
            }
        }

        durations_ms.push_back(wall_ms);
        for (size_t n = 0; n < num_numas; ++n) {
            per_numa_ms[n].push_back(numa_max_ms[n]);
        }

        // Print iteration result
        double agg_bw_gbps = (iter_total_size * 8.0) / (wall_ms * 1e6);
        double agg_bw_gbs = (iter_total_size / 1e9) / (wall_ms / 1e3);
        printf("  [%4d] %d reqs/NUMA, wall=%.3f ms (submit=%.3f, wait=%.3f)",
               iter, batch_size, wall_ms, submit_ms, wait_ms);
        for (size_t n = 0; n < num_numas; ++n) {
            if (num_numas > 1) {
                double numa_bw_gbps = (iter_per_numa_size * 8.0) / (numa_max_ms[n] * 1e6);
                double numa_bw_gbs = (iter_per_numa_size / 1e9) / (numa_max_ms[n] / 1e3);
                printf("  NUMA%d=%.3f ms (%.2f Gbps, %.2f GB/s)",
                       numa_buffers[n].numa_node, numa_max_ms[n],
                       numa_bw_gbps, numa_bw_gbs);
            }
        }
        if (num_numas == 1) {
            printf("  internal=%.3f ms  BW=%.2f Gbps (%.2f GB/s)\n",
                   max_internal_ms, agg_bw_gbps, agg_bw_gbs);
        } else {
            printf("  => Agg: %.3f ms, %.2f Gbps (%.2f GB/s)\n",
                   wall_ms, agg_bw_gbps, agg_bw_gbs);
        }
    }

    // ---- Summary ----
    double sum_ms = 0, min_ms = 1e9, max_ms = 0;
    double sum_bw_gbs = 0, min_bw_gbs = 1e9, max_bw_gbs = 0;
    for (int i = 0; i < total_iters; ++i) {
        double d = durations_ms[i];
        double bw = (iter_total_size / 1e9) / (d / 1e3);
        sum_ms += d;
        sum_bw_gbs += bw;
        if (d < min_ms) min_ms = d;
        if (d > max_ms) max_ms = d;
        if (bw < min_bw_gbs) min_bw_gbs = bw;
        if (bw > max_bw_gbs) max_bw_gbs = bw;
    }
    double avg_ms = sum_ms / total_iters;
    double avg_bw_gbs = sum_bw_gbs / total_iters;

    printf("\n--- %s %s Summary (%zu targets, %zu NUMAs, batch_size=%d) ---\n",
           op_name_upper, mem_type_label, host_list.size(), num_numas, batch_size);
    printf("  Iterations: %d (%d async reqs per NUMA per iter, %d total reqs per iter)\n",
           total_iters, batch_size, batch_size * static_cast<int>(num_numas));
    printf("  Data per iter: %s (%.2f MB per NUMA)\n",
           formatBytes(iter_total_size).c_str(), iter_per_numa_size / 1e6);
    printf("  Aggregate Avg: %.3f ms (%.2f Gbps, %.2f GB/s)\n",
           avg_ms, avg_bw_gbs * 8.0, avg_bw_gbs);
    printf("  Best BW:  %.2f Gbps (%.2f GB/s)  |  Worst BW: %.2f Gbps (%.2f GB/s)\n",
           max_bw_gbs * 8.0, max_bw_gbs, min_bw_gbs * 8.0, min_bw_gbs);
    printf("  Min wall: %.3f ms  |  Max wall: %.3f ms\n", min_ms, max_ms);

    // Per-NUMA summary
    if (num_numas > 1) {
        for (size_t n = 0; n < num_numas; ++n) {
            double ns = 0, nmin = 1e9, nmax = 0;
            for (double d : per_numa_ms[n]) {
                ns += d;
                if (d < nmin) nmin = d;
                if (d > nmax) nmax = d;
            }
            double navg = ns / total_iters;
            // Per-NUMA bandwidth: iter_per_numa_size bytes over the NUMA's time
            double navg_gbs = (iter_per_numa_size / 1e9) / (navg / 1e3);
            double nmin_gbs = (iter_per_numa_size / 1e9) / (nmin / 1e3);
            double nmax_gbs = (iter_per_numa_size / 1e9) / (nmax / 1e3);
            printf("  NUMA %d: Avg %.3f ms (%.2f GB/s), "
                   "Min %.3f ms (%.2f GB/s), "
                   "Max %.3f ms (%.2f GB/s)\n",
                   numa_buffers[n].numa_node,
                   navg, navg_gbs,
                   nmin, nmax_gbs,
                   nmax, nmin_gbs);
        }
    }
    printf("\n");

    return 0;
}

// =====================================================================
// Initiator workflow (shared between MODE_INITIATOR and MODE_BOTH)
//
// Allocates per-NUMA DRAM buffers (and optionally an HBM buffer), connects
// to every target, resolves remote buffer addresses, and then runs the
// requested benchmarks.  Resources are cleaned up before return.
// The MPComm instance is passed in; the caller owns its lifetime.
// =====================================================================

// Run the full initiator benchmark for one logical "job": allocate per-NUMA
// buffers sized for that job's target list, connect, query remote buffers,
// then run scatter/gather/broadcast as requested. This function is invoked
// once per --job group in both mode, and exactly once in initiator mode.
// `job_label` is emitted inside every log line prefix so the driver script
// can extract per-job summaries from a shared log file.
static int runInitiatorWorkloadForTargets(MPComm &comm,
                                          const TestConfig &cfg,
                                          const std::vector<TargetInfo> &targets,
                                          const std::string &job_label) {
    const size_t num_targets = targets.size();
    const size_t total_buffer_size = cfg.buffer_size * num_targets;
    const size_t num_initiator_numas = cfg.initiator_numas.size();
    const std::string jp = job_label.empty() ? "" : ("[job=" + job_label + "] ");

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

    int ret = 0;

    // ---- Allocate and register per-NUMA DRAM buffers ----
    std::vector<InitiatorNumaBuffer> dram_numa_buffers;
    if (run_dram) {
        printf("%sAllocating DRAM buffers (%zu bytes per NUMA = %zu per target x %zu targets) "
               "on %zu NUMA node(s)...\n",
               jp.c_str(),
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
                return 1;
            }
            printf("%s  NUMA %d: DRAM buffer registered at %p (%zu bytes)\n",
                   jp.c_str(), numa_node, nbuf.ptr, total_buffer_size);
            dram_numa_buffers.push_back(nbuf);
        }
    }

    // ---- Allocate and register HBM buffer (single, not per-NUMA) ----
    void *hbm_buffer = nullptr;
    std::vector<InitiatorNumaBuffer> hbm_numa_buffers;
#ifdef USE_CUDA
    if (run_hbm) {
        printf("%sAllocating HBM buffer (%zu bytes = %zu per target x %zu targets) on GPU %d...\n",
               jp.c_str(),
               total_buffer_size, cfg.buffer_size, num_targets, cfg.gpu_device);
        hbm_buffer = allocHBM(total_buffer_size, cfg.gpu_device);
        if (!hbm_buffer) {
            fprintf(stderr, "Failed to allocate HBM buffer\n");
            for (auto &b : dram_numa_buffers) {
                comm.unregisterMemory(b.ptr);
                freeDRAM(b.ptr, b.alloc_size);
            }
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
    {
        std::vector<std::string> host_list;
        std::vector<size_t> lengths;
        // remote_addrs_per_numa[n][t] for DRAM
        std::vector<std::vector<uintptr_t>> dram_remote_addrs(num_initiator_numas);
        // For HBM: always use first remote buffer (single NUMA)
        std::vector<std::vector<uintptr_t>> hbm_remote_addrs(1);

        for (size_t t = 0; t < num_targets; ++t) {
            const auto &target = targets[t];

            printf("%sConnecting to target[%zu] %s (%s:%d)%s...\n",
                   jp.c_str(),
                   t, target.host_id.c_str(),
                   target.tcp_addr.c_str(), target.tcp_port,
                   target.channel_id > 0 ? " [channel-tagged]" : "");

            // Retry connect to tolerate the target side not yet being
            // ready to accept (e.g. peer process still publishing buffers).
            // Defaults: 10 attempts, 1000 ms interval. Override with env vars
            //   MPCOMM_CONNECT_RETRIES, MPCOMM_CONNECT_RETRY_INTERVAL_MS.
            int max_retries = 10;
            int retry_interval_ms = 1000;
            if (const char* s = std::getenv("MPCOMM_CONNECT_RETRIES")) {
                int v = std::atoi(s);
                if (v > 0) max_retries = v;
            }
            if (const char* s = std::getenv("MPCOMM_CONNECT_RETRY_INTERVAL_MS")) {
                int v = std::atoi(s);
                if (v > 0) retry_interval_ms = v;
            }

            ret = -1;
            for (int attempt = 1; attempt <= max_retries; ++attempt) {
                ret = comm.connect(target.host_id, target.tcp_addr, target.tcp_port);
                if (ret == 0) break;
                if (attempt < max_retries) {
                    fprintf(stderr,
                            "%sConnect to target[%zu] %s failed (rc=%d), "
                            "attempt %d/%d, retrying in %d ms...\n",
                            jp.c_str(), t, target.host_id.c_str(), ret,
                            attempt, max_retries, retry_interval_ms);
                    std::this_thread::sleep_for(
                        std::chrono::milliseconds(retry_interval_ms));
                }
            }
            if (ret != 0) {
                fprintf(stderr,
                        "%sFailed to connect to target[%zu] %s after %d attempts: %d\n",
                        jp.c_str(), t, target.host_id.c_str(), max_retries, ret);
                goto cleanup;
            }
            printf("%sConnected to %s.\n", jp.c_str(), target.host_id.c_str());

            // Query all remote buffers from this target
            RemoteBufferInfo remote_info;
            ret = comm.queryRemoteBuffer(
                target.host_id, target.tcp_addr, target.tcp_port, remote_info);
            if (ret != 0 || remote_info.buffers.empty()) {
                fprintf(stderr, "Failed to query remote buffer from target[%zu] %s: %d\n",
                        t, target.host_id.c_str(), ret);
                goto cleanup;
            }

            printf("%s  Remote buffers from %s: %zu buffer(s)\n",
                   jp.c_str(), target.host_id.c_str(), remote_info.buffers.size());
            for (size_t b = 0; b < remote_info.buffers.size(); ++b) {
                auto &buf = remote_info.buffers[b];
                printf("%s    [%zu] addr=0x%lx, length=%lu, tag=%d\n",
                       jp.c_str(), b, (unsigned long)buf.addr, (unsigned long)buf.length,
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

            // Resolve which remote buffer each initiator NUMA should target.
            // Selection rules:
            //   (1) If this --target carries an explicit channel_id, use the
            //       composite tag (channel_id<<16)|peer_numa for ALL initiator
            //       NUMAs — the initiator is deliberately pointed at a single
            //       remote buffer chosen by the scheduler.
            //   (2) Otherwise, fall back to legacy behaviour: match each
            //       initiator NUMA to a remote buffer with the same numa_node,
            //       falling back to index-based / first-buffer selection.
            for (size_t n = 0; n < num_initiator_numas; ++n) {
                int want_numa = cfg.initiator_numas[n];
                int want_tag = (target.channel_id > 0)
                    ? encodeBufferTag(target.channel_id, target.peer_numa)
                    : want_numa;

                const RemoteBufferEntry *matched = nullptr;
                for (const auto &buf : remote_info.buffers) {
                    if (buf.numa_node == want_tag) {
                        matched = &buf;
                        break;
                    }
                }
                if (!matched) {
                    if (target.channel_id > 0) {
                        fprintf(stderr, "Error: target %s has no published buffer with tag %d "
                                        "(channel_id=%d, peer_numa=%d). Check --serve on peer.\n",
                                target.host_id.c_str(), want_tag,
                                target.channel_id, target.peer_numa);
                        ret = 1;
                        goto cleanup;
                    }
                    // Legacy fallback: use the Nth buffer if available, otherwise first
                    if (n < remote_info.buffers.size()) {
                        matched = &remote_info.buffers[n];
                    } else {
                        matched = &remote_info.buffers[0];
                    }
                    if (num_initiator_numas > 1) {
                        printf("  Warning: No remote NUMA %d buffer for target %s, "
                               "using buffer with tag %d at 0x%lx\n",
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

        printf("\n%sAll %zu targets connected and ready.\n", jp.c_str(), num_targets);

        // ---- Run benchmarks for each requested test type ----
        for (TestOpType op : cfg.test_types) {
            // put/get only support exactly one target. Skip with a clear
            // warning instead of failing the entire run, so a mixed
            // --test-type list (e.g. "scatter,put") still completes the
            // multi-target operations.
            if (isSingleTargetOp(op) && num_targets != 1) {
                fprintf(stderr,
                        "%sWarning: skipping %s test - it requires exactly one "
                        "--target (got %zu).\n",
                        jp.c_str(), opTypeName(op), num_targets);
                continue;
            }

            printf("\n%s>>> Running %s test <<<\n", jp.c_str(), opTypeName(op));

            // For broadcast, we use buffer_size as the single length
            // (same block sent to all targets), so prepare a matching lengths vector.
            // For put/get, we use a single-element vector.
            std::vector<size_t> bench_lengths;
            if (op == TestOpType::BROADCAST) {
                bench_lengths.assign(num_targets, cfg.buffer_size);
            } else if (op == TestOpType::PUT || op == TestOpType::GET) {
                bench_lengths.assign(1, cfg.buffer_size);
            } else {
                bench_lengths = lengths;
            }

            // The benchmark labels internally use "DRAM" / "HBM (GPU)"; when we
            // are running inside a multi-job both process we prefix the label
            // with the job name so the driver script's summary extractor can
            // attribute every "--- X Y Summary" line to its originating job.
            std::string dram_label = job_label.empty()
                ? std::string("DRAM")
                : ("DRAM@" + job_label);
            std::string hbm_label = job_label.empty()
                ? std::string("HBM (GPU)")
                : ("HBM@" + job_label);

            if (run_dram) {
                ret = runTransferBenchmark(comm, cfg, op, dram_numa_buffers,
                                          host_list, dram_remote_addrs,
                                          bench_lengths, dram_label.c_str());
                if (ret != 0) goto cleanup;
            }

            if (run_hbm) {
                ret = runTransferBenchmark(comm, cfg, op, hbm_numa_buffers,
                                          host_list, hbm_remote_addrs,
                                          bench_lengths, hbm_label.c_str());
                if (ret != 0) goto cleanup;
            }
        }
    }

    ret = 0;

cleanup:
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
    return ret;
}

// =====================================================================
// Both mode: one MPComm instance serves its --serve buffers AND acts as
// initiator for every --target. After all benchmarks finish, the process
// keeps serving its published buffers until SIGINT/SIGTERM is received so
// that remote peers still transferring against us do not error out.
// =====================================================================

static int runBothMode(const TestConfig &cfg) {
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);

    printf("=== MPComm Both Mode ===\n");
    printf("  Host ID:     %s\n", cfg.host_id.c_str());
    printf("  TCP Port:    %d\n", cfg.tcp_port);
    printf("  Serves:      %zu\n", cfg.serves.size());
    for (const auto &s : cfg.serves) {
        printf("    channel_id=%d, size=%s, numa=%d\n",
               s.channel_id, formatBytes(s.size).c_str(), s.numa);
    }
    printf("  Targets:     %zu\n", cfg.targets.size());
    for (const auto &t : cfg.targets) {
        printf("    %s @ %s:%d", t.host_id.c_str(), t.tcp_addr.c_str(), t.tcp_port);
        if (t.channel_id > 0) {
            printf("  (channel_id=%d, peer_numa=%d -> tag %d)",
                   t.channel_id, t.peer_numa,
                   encodeBufferTag(t.channel_id, t.peer_numa));
        }
        printf("\n");
    }
    printf("\n");

    MPComm comm;
    int ret = comm.init(cfg.host_id, cfg.device, cfg.tcp_port);
    if (ret != 0) {
        fprintf(stderr, "MPComm init failed: %d\n", ret);
        return 1;
    }
    printf("[both] Initialized MPComm with %zu NICs, TCP port %d\n",
           comm.getNumNics(), comm.getTcpPort());

    // ---- Allocate + register + publish all --serve buffers ----
    std::vector<NumaBuffer> serve_buffers;
    std::vector<int> serve_tags;  // parallel with serve_buffers
    const size_t page_size = 4096;

    auto freeServeBuffers = [&]() {
        for (auto &nb : serve_buffers) {
            if (nb.ptr) {
                comm.unpublishBuffer(nb.ptr);
                comm.unregisterMemory(nb.ptr);
                if (numa_available() >= 0) {
                    numa_free(nb.ptr, nb.alloc_size);
                } else {
                    free(nb.ptr);
                }
                nb.ptr = nullptr;
            }
        }
    };

    for (const auto &s : cfg.serves) {
        size_t alloc_size = ((s.size + page_size - 1) / page_size) * page_size;
        NumaBuffer nb;
        nb.numa_node = s.numa;
        nb.alloc_size = alloc_size;

        if (numa_available() >= 0 && s.numa >= 0) {
            nb.ptr = numa_alloc_onnode(alloc_size, s.numa);
        }
        if (!nb.ptr) {
            nb.ptr = aligned_alloc(page_size, alloc_size);
        }
        if (!nb.ptr) {
            fprintf(stderr, "Failed to allocate serve buffer (channel_id=%d, numa=%d)\n",
                    s.channel_id, s.numa);
            freeServeBuffers();
            comm.shutdown();
            return 1;
        }
        memset(nb.ptr, 0xAB, alloc_size);

        ret = comm.registerMemory(nb.ptr, s.size);
        if (ret != 0) {
            fprintf(stderr, "registerMemory failed for serve channel_id=%d: %d\n",
                    s.channel_id, ret);
            if (numa_available() >= 0) numa_free(nb.ptr, alloc_size);
            else
                free(nb.ptr);
            freeServeBuffers();
            comm.shutdown();
            return 1;
        }

        int tag = encodeBufferTag(s.channel_id, s.numa);
        ret = comm.publishBuffer(nb.ptr, s.size, tag);
        if (ret != 0) {
            fprintf(stderr, "publishBuffer failed for serve channel_id=%d (tag=%d): %d\n",
                    s.channel_id, tag, ret);
            comm.unregisterMemory(nb.ptr);
            if (numa_available() >= 0) numa_free(nb.ptr, alloc_size);
            else
                free(nb.ptr);
            freeServeBuffers();
            comm.shutdown();
            return 1;
        }
        printf("[both] Published serve buffer: channel_id=%d, numa=%d, tag=%d, "
               "size=%s, addr=%p\n",
               s.channel_id, s.numa, tag, formatBytes(s.size).c_str(), nb.ptr);
        serve_buffers.push_back(nb);
        serve_tags.push_back(tag);
    }

    // ---- Start accept thread so remote initiators can connect + query ----
    ret = comm.startAcceptThread();
    if (ret != 0) {
        fprintf(stderr, "Failed to start accept thread: %d\n", ret);
        freeServeBuffers();
        comm.shutdown();
        return 1;
    }

    // Drivers grep this line to decide when it is safe to let peers connect.
    // The word "connections" matches the existing target-mode ready marker so
    // that orchestrators don't need two separate regexes.
    printf("[both] Ready - waiting for connections... "
           "(published %zu buffer(s); will now start initiator workload)\n",
           serve_buffers.size());
    fflush(stdout);

    // ---- Optional global barrier: wait for driver to release us. ----
    // The driver writes the go-file only after it has confirmed that every
    // host has reached the "Ready" marker above. This guarantees that no
    // initiator starts connecting before all remote targets have finished
    // publishing their buffers and started their accept thread.
    if (!cfg.wait_go_file.empty()) {
        printf("[both] Waiting for go-file: %s\n", cfg.wait_go_file.c_str());
        fflush(stdout);
        const auto wait_start = std::chrono::steady_clock::now();
        while (true) {
            struct stat st;
            if (::stat(cfg.wait_go_file.c_str(), &st) == 0) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now() - wait_start).count();
            // Print a heartbeat every 30s so the driver-side log shows progress.
            if (elapsed > 0 && (elapsed % 30) == 0) {
                static long last_print = -1;
                if (elapsed != last_print) {
                    printf("[both] Still waiting for go-file (%lds)...\n",
                           (long)elapsed);
                    fflush(stdout);
                    last_print = elapsed;
                }
            }
        }
        printf("[both] Go-file detected, releasing initiator workload.\n");
        fflush(stdout);
    }

    // ---- If we have --target entries, run the initiator workload(s). ----
    // In both mode we partition cfg.targets by their job_label so that each
    // logical job on this host is benchmarked independently (with its own
    // connect/query/allocate round). Targets without a label are grouped into
    // a single anonymous job, preserving legacy initiator semantics.
    int workload_rc = 0;
    if (!cfg.targets.empty()) {
        // Preserve the first-seen order of job labels so output remains
        // deterministic for the driver script.
        std::vector<std::string> job_order;
        for (const auto &t : cfg.targets) {
            bool seen = false;
            for (const auto &j : job_order) {
                if (j == t.job_label) { seen = true; break; }
            }
            if (!seen) job_order.push_back(t.job_label);
        }

        for (const auto &label : job_order) {
            std::vector<TargetInfo> group;
            for (const auto &t : cfg.targets) {
                if (t.job_label == label) group.push_back(t);
            }
            printf("\n[both] === Running job '%s' with %zu target(s) ===\n",
                   label.empty() ? "(default)" : label.c_str(),
                   group.size());
            int rc = runInitiatorWorkloadForTargets(comm, cfg, group, label);
            if (rc != 0) {
                fprintf(stderr, "[both] Job '%s' failed with rc=%d\n",
                        label.empty() ? "(default)" : label.c_str(), rc);
                workload_rc = rc;
                // Continue running other jobs so we still serve published
                // buffers; peers may still be reading from us for their own
                // benchmarks even if our initiator half failed.
            } else {
                printf("[both] Job '%s' complete.\n",
                       label.empty() ? "(default)" : label.c_str());
            }
        }
    } else {
        printf("[both] No --target specified; skipping initiator workload.\n");
    }

    // ---- Keep serving published buffers until Ctrl+C ----
    // Peers that are still performing RDMA transfers against us need our
    // serve buffers to remain registered and published.
    printf("\n[both] Benchmarks done. Still serving %zu buffer(s); "
           "press Ctrl+C to stop.\n", serve_buffers.size());
    while (!g_stop_requested.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    printf("[both] Shutting down...\n");
    freeServeBuffers();
    comm.stopAcceptThread();
    comm.shutdown();
    printf("[both] Stopped.\n");
    return workload_rc;
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
    if (cfg.mode == MODE_BOTH) {
        return runBothMode(cfg);
    }

    // --- Initiator mode (legacy path; no --serve) ---
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

    ret = runInitiatorWorkloadForTargets(comm, cfg, cfg.targets, "");
    comm.shutdown();
    return ret;
}
