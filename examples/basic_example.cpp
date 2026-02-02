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

/**
 * MPComm Basic Example
 * 
 * This example demonstrates basic usage of MPComm for scatter/gather operations.
 * 
 * Usage:
 *   # On server (host A):
 *   ./mpcomm_example server 12345 mlx5_0
 *   # Server will print buffer address and rkey, note them down
 * 
 *   # On client (host B):
 *   ./mpcomm_example client <server_ip> 12345 <remote_addr> <remote_rkey> [device_name]
 * 
 * Note: In real applications, rkey and address should be exchanged via a
 * metadata protocol (e.g., additional TCP messages after connection setup).
 */

#include <mpcomm.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <signal.h>

using namespace mpcomm;

// Buffer size for testing
static const size_t kBufferSize = 1024 * 1024;  // 1MB

// Initialize buffer with pattern based on offset (for verification)
void initBufferWithPattern(char *buffer, size_t length, uint8_t base_value) {
    for (size_t i = 0; i < length; ++i) {
        buffer[i] = static_cast<char>((base_value + (i & 0xFF)) & 0xFF);
    }
}

// Verify buffer content
bool verifyBuffer(const char *buffer, size_t length, uint8_t base_value) {
    for (size_t i = 0; i < length; ++i) {
        uint8_t expected = (base_value + (i & 0xFF)) & 0xFF;
        if (static_cast<uint8_t>(buffer[i]) != expected) {
            printf("Verification failed at offset %zu: expected %u, got %u\n",
                   i, expected, static_cast<uint8_t>(buffer[i]));
            return false;
        }
    }
    return true;
}

int runServer(int port, const char *device_name) {
    printf("=== MPComm Server ===\n");

    MPComm comm;
    
    // Initialize with specified device and port
    int ret = comm.init("server:host", device_name ? device_name : "", port);
    if (ret != 0) {
        fprintf(stderr, "Failed to initialize MPComm: %d\n", ret);
        return 1;
    }

    printf("Server initialized on port %d with %zu NICs\n",
           comm.getTcpPort(), comm.getNumNics());

    // Allocate and register memory
    char *buffer = static_cast<char *>(aligned_alloc(4096, kBufferSize));
    if (!buffer) {
        fprintf(stderr, "Failed to allocate buffer\n");
        return 1;
    }
    memset(buffer, 0, kBufferSize);

    ret = comm.registerMemory(buffer, kBufferSize);
    if (ret != 0) {
        fprintf(stderr, "Failed to register memory: %d\n", ret);
        free(buffer);
        return 1;
    }

    // Print buffer info and rkey for each NIC
    printf("\n========================================\n");
    printf("Buffer address: %p (0x%lx)\n", buffer, reinterpret_cast<uintptr_t>(buffer));
    printf("Buffer size: %zu bytes\n", kBufferSize);
    for (size_t i = 0; i < comm.getNumNics(); ++i) {
        uint32_t rkey = comm.getRkey(i, buffer);
        printf("NIC %zu rkey: %u (0x%x)\n", i, rkey, rkey);
    }
    printf("========================================\n\n");

    // Start accept thread to handle incoming connections
    ret = comm.startAcceptThread();
    if (ret != 0) {
        fprintf(stderr, "Failed to start accept thread: %d\n", ret);
        free(buffer);
        return 1;
    }

    printf("Waiting for connections... (Press Ctrl+C to exit)\n");

    // Keep running until interrupted
    while (true) {
        sleep(5);
        
        // Print buffer content periodically (first 64 bytes as decimal)
        printf("Buffer content (first 64 bytes): ");
        for (int i = 0; i < 64; ++i) {
            printf("%d ", static_cast<int>(static_cast<uint8_t>(buffer[i])));
        }
        printf("\n");
    }

    // Cleanup (unreachable in this example)
    comm.stopAcceptThread();
    comm.unregisterMemory(buffer);
    free(buffer);
    comm.shutdown();

    return 0;
}

int runClient(const char *server_addr, int server_port, const char *device_name,
              uintptr_t remote_buffer_addr, uint32_t remote_rkey) {
    printf("=== MPComm Client ===\n");

    MPComm comm;
    
    // Initialize (no listening port needed for client)
    int ret = comm.init("client:host", device_name ? device_name : "", 0);
    if (ret != 0) {
        fprintf(stderr, "Failed to initialize MPComm: %d\n", ret);
        return 1;
    }

    printf("Client initialized with %zu NICs\n", comm.getNumNics());

    // Allocate and register local memory
    char *local_buffer = static_cast<char *>(aligned_alloc(4096, kBufferSize));
    if (!local_buffer) {
        fprintf(stderr, "Failed to allocate buffer\n");
        return 1;
    }

    // Initialize with test pattern (base_value based on IP-like pattern)
    uint8_t pattern_base = 0x42;  // 66 in decimal
    initBufferWithPattern(local_buffer, kBufferSize, pattern_base);

    ret = comm.registerMemory(local_buffer, kBufferSize);
    if (ret != 0) {
        fprintf(stderr, "Failed to register memory: %d\n", ret);
        free(local_buffer);
        return 1;
    }

    printf("Local buffer registered at %p\n", local_buffer);

    // Connect to server
    printf("Connecting to %s:%d...\n", server_addr, server_port);
    ret = comm.connect("server:host", server_addr, server_port);
    if (ret != 0) {
        fprintf(stderr, "Failed to connect: %d\n", ret);
        free(local_buffer);
        return 1;
    }

    printf("Connected to server\n");

    // Update remote memory info (rkey) - in real app this would be exchanged via protocol
    std::vector<uint32_t> rkeys(comm.getNumNics(), remote_rkey);
    ret = comm.updateRemoteMemoryInfo("server:host", rkeys);
    if (ret != 0) {
        fprintf(stderr, "Failed to update remote memory info: %d\n", ret);
        free(local_buffer);
        return 1;
    }

    // Test scatter: write local data to remote
    printf("\n--- Scatter Test (WRITE) ---\n");
    printf("Writing %zu bytes to remote address 0x%lx with rkey 0x%x\n",
           kBufferSize, remote_buffer_addr, remote_rkey);

    std::vector<std::string> hosts = {"server:host"};
    std::vector<uintptr_t> remote_addrs = {remote_buffer_addr};
    std::vector<size_t> lengths = {kBufferSize};

    ret = comm.scatter(reinterpret_cast<uintptr_t>(local_buffer),
                       hosts, remote_addrs, lengths, 1);
    if (ret != 0) {
        fprintf(stderr, "Scatter failed: %d\n", ret);
    } else {
        printf("Scatter completed successfully!\n");
    }

    // Test gather: read remote data to local
    printf("\n--- Gather Test (READ) ---\n");
    
    // Clear local buffer first
    memset(local_buffer, 0, kBufferSize);

    printf("Reading %zu bytes from remote address 0x%lx\n",
           kBufferSize, remote_buffer_addr);

    ret = comm.gather(reinterpret_cast<uintptr_t>(local_buffer),
                      hosts, remote_addrs, lengths, 1);
    if (ret != 0) {
        fprintf(stderr, "Gather failed: %d\n", ret);
    } else {
        printf("Gather completed successfully!\n");
        
        // Verify data
        uint8_t pattern_base = 0x42;
        if (verifyBuffer(local_buffer, kBufferSize, pattern_base)) {
            printf("Data verification PASSED!\n");
        } else {
            printf("Data verification FAILED!\n");
        }
    }

    // Cleanup
    comm.unregisterMemory(local_buffer);
    free(local_buffer);
    comm.shutdown();

    return 0;
}

void printUsage(const char *prog) {
    printf("Usage:\n");
    printf("  Server: %s server <port> [device_name]\n", prog);
    printf("  Client: %s client <server_ip> <port> <remote_addr> <remote_rkey> [device_name]\n", prog);
    printf("\n");
    printf("Examples:\n");
    printf("  # Start server:\n");
    printf("  %s server 12345 mlx5_0\n", prog);
    printf("\n");
    printf("  # Start client (use addr and rkey printed by server):\n");
    printf("  %s client 192.168.1.100 12345 0x7f1234000000 0x12345678 mlx5_0\n", prog);
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        printUsage(argv[0]);
        return 1;
    }

    const char *mode = argv[1];

    if (strcmp(mode, "server") == 0) {
        if (argc < 3) {
            printUsage(argv[0]);
            return 1;
        }
        int port = atoi(argv[2]);
        const char *device = (argc > 3) ? argv[3] : nullptr;
        return runServer(port, device);
    } else if (strcmp(mode, "client") == 0) {
        if (argc < 6) {
            printUsage(argv[0]);
            return 1;
        }
        const char *server_addr = argv[2];
        int server_port = atoi(argv[3]);
        uintptr_t remote_addr = strtoull(argv[4], nullptr, 0);
        uint32_t remote_rkey = static_cast<uint32_t>(strtoul(argv[5], nullptr, 0));
        const char *device = (argc > 6) ? argv[6] : nullptr;
        return runClient(server_addr, server_port, device, remote_addr, remote_rkey);
    } else {
        printUsage(argv[0]);
        return 1;
    }

    return 0;
}
