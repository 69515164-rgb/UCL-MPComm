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

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstring>
#include <vector>

#include "mpcomm.h"

namespace py = pybind11;

namespace mpcomm {

/**
 * Python wrapper for MPComm class
 * Provides Python-friendly interface with uintptr_t for memory addresses
 */
class MPCommPy {
public:
    MPCommPy() = default;
    ~MPCommPy() = default;

    /**
     * Initialize RDMA resources
     * @param local_host_id  Unique identifier for this host (e.g., "host1:12345")
     * @param device_names   Comma-separated list of device names (e.g., "mlx5_0,mlx5_1")
     * @param tcp_port       TCP port for metadata exchange (0 = auto select)
     * @return 0 on success, negative error code on failure
     */
    int init(const std::string &local_host_id,
             const std::string &device_names = "",
             int tcp_port = 0) {
        return comm_.init(local_host_id, device_names, tcp_port);
    }

    /**
     * Shutdown and cleanup resources
     */
    void shutdown() {
        comm_.shutdown();
    }

    /**
     * Register local memory for RDMA operations
     * @param addr    Memory address as uintptr_t
     * @param length  Memory length in bytes
     * @return 0 on success, negative error code on failure
     */
    int registerMemory(uintptr_t addr, size_t length) {
        return comm_.registerMemory(reinterpret_cast<void *>(addr), length);
    }

    /**
     * Unregister previously registered memory
     * @param addr  Memory address as uintptr_t
     * @return 0 on success, negative error code on failure
     */
    int unregisterMemory(uintptr_t addr) {
        return comm_.unregisterMemory(reinterpret_cast<void *>(addr));
    }

    /**
     * Connect to a remote host
     * @param remote_host_id  Remote host identifier
     * @param remote_tcp_addr Remote TCP address for handshake
     * @param remote_tcp_port Remote TCP port
     * @return 0 on success, negative error code on failure
     */
    int connect(const std::string &remote_host_id,
                const std::string &remote_tcp_addr,
                int remote_tcp_port) {
        return comm_.connect(remote_host_id, remote_tcp_addr, remote_tcp_port);
    }

    /**
     * Start accepting incoming connections in background
     * @return 0 on success, negative error code on failure
     */
    int startAcceptThread() {
        return comm_.startAcceptThread();
    }

    /**
     * Stop the accept thread
     */
    void stopAcceptThread() {
        comm_.stopAcceptThread();
    }

    /**
     * Update remote memory info (rkey) for a connected host
     * @param remote_host_id  Remote host identifier
     * @param rkeys           Remote keys for each NIC
     * @return 0 on success, negative error code on failure
     */
    int updateRemoteMemoryInfo(const std::string &remote_host_id,
                               const std::vector<uint32_t> &rkeys) {
        return comm_.updateRemoteMemoryInfo(remote_host_id, rkeys);
    }

    /**
     * Get rkey for local memory region
     * @param nic_index  NIC index
     * @param addr       Memory address as uintptr_t
     * @return rkey, or 0 if not found
     */
    uint32_t getRkey(size_t nic_index, uintptr_t addr) {
        return comm_.getRkey(nic_index, reinterpret_cast<void *>(addr));
    }

    /**
     * Get all rkeys for local memory region (one per NIC)
     * @param addr  Memory address as uintptr_t
     * @return vector of rkeys, one per NIC
     */
    std::vector<uint32_t> getAllRkeys(uintptr_t addr) {
        std::vector<uint32_t> rkeys;
        size_t num_nics = comm_.getNumNics();
        rkeys.reserve(num_nics);
        for (size_t i = 0; i < num_nics; ++i) {
            rkeys.push_back(comm_.getRkey(i, reinterpret_cast<void *>(addr)));
        }
        return rkeys;
    }

    /**
     * Scatter: distribute local data to multiple remote hosts (RDMA WRITE)
     * @param local_addr       Local buffer address
     * @param host_list        List of destination host IDs
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @param num_threads      Number of threads (each uses different NIC)
     * @return 0 on success, negative error code on failure
     */
    int scatter(uintptr_t local_addr,
                const std::vector<std::string> &host_list,
                const std::vector<uintptr_t> &remote_addrs,
                const std::vector<size_t> &lengths,
                int num_threads = 1) {
        return comm_.scatter(local_addr, host_list, remote_addrs, lengths, num_threads);
    }

    /**
     * Gather: collect data from multiple remote hosts to local buffer (RDMA READ)
     * @param local_addr       Local buffer address
     * @param host_list        List of source host IDs
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @param num_threads      Number of threads (each uses different NIC)
     * @return 0 on success, negative error code on failure
     */
    int gather(uintptr_t local_addr,
               const std::vector<std::string> &host_list,
               const std::vector<uintptr_t> &remote_addrs,
               const std::vector<size_t> &lengths,
               int num_threads = 1) {
        return comm_.gather(local_addr, host_list, remote_addrs, lengths, num_threads);
    }

    /**
     * mp_replicate: unified interface for scatter/gather operations
     * @param comm_type        "scatter" or "gather"
     * @param host_list        List of remote host IDs
     * @param local_addr       Local buffer address
     * @param remote_addrs     Remote buffer addresses on each host
     * @param lengths          Data lengths for each host
     * @param num_threads      Number of threads (each uses different NIC)
     * @return 0 on success, negative error code on failure
     */
    int mpReplicate(const std::string &comm_type,
                    const std::vector<std::string> &host_list,
                    uintptr_t local_addr,
                    const std::vector<uintptr_t> &remote_addrs,
                    const std::vector<size_t> &lengths,
                    int num_threads = 1) {
        if (comm_type == "scatter") {
            return scatter(local_addr, host_list, remote_addrs, lengths, num_threads);
        } else if (comm_type == "gather") {
            return gather(local_addr, host_list, remote_addrs, lengths, num_threads);
        }
        return MPCOMM_ERR_INVALID_ARG;
    }

    /**
     * Get number of available NICs
     */
    size_t getNumNics() const { return comm_.getNumNics(); }

    /**
     * Get local host ID
     */
    std::string getLocalHostId() const { return comm_.getLocalHostId(); }

    /**
     * Get TCP port for metadata exchange
     */
    int getTcpPort() const { return comm_.getTcpPort(); }

    /**
     * Get GID string for a specific NIC
     */
    std::string getGid(size_t nic_index) const { return comm_.getGid(nic_index); }

    /**
     * Get device name for a specific NIC
     */
    std::string getDeviceName(size_t nic_index) const { return comm_.getDeviceName(nic_index); }

    /**
     * Get all active device names
     */
    std::vector<std::string> getActiveDevices() const { return comm_.getActiveDevices(); }

    /**
     * Get the NIC filter environment variable name
     */
    static std::string getNicFilterEnvVarName() { return std::string(MPComm::getNicFilterEnvVarName()); }

    /**
     * Get the QPs per connection environment variable name
     */
    static std::string getQpsPerConnectionEnvVarName() { return std::string(MPComm::getQpsPerConnectionEnvVarName()); }

    /**
     * Get the number of QPs per connection
     */
    size_t getQpsPerConnection() const { return comm_.getQpsPerConnection(); }

    /**
     * Write bytes to a registered buffer (for testing)
     * @param addr    Memory address as uintptr_t
     * @param data    Data to write
     * @param length  Number of bytes to write
     * @return 0 on success, negative error code on failure
     */
    int writeBytesToBuffer(uintptr_t addr, const py::bytes &data, size_t length) {
        std::string str_data = data;
        if (str_data.size() < length) {
            return MPCOMM_ERR_INVALID_ARG;
        }
        std::memcpy(reinterpret_cast<void *>(addr), str_data.data(), length);
        return MPCOMM_SUCCESS;
    }

    /**
     * Read bytes from a registered buffer (for testing)
     * @param addr    Memory address as uintptr_t
     * @param length  Number of bytes to read
     * @return bytes object containing the data
     */
    py::bytes readBytesFromBuffer(uintptr_t addr, size_t length) {
        return py::bytes(reinterpret_cast<const char *>(addr), length);
    }

    /**
     * Publish a local buffer for remote access
     * @param addr    Buffer address (must be registered)
     * @param length  Buffer length
     * @return 0 on success, negative error code on failure
     */
    int publishBuffer(uintptr_t addr, size_t length) {
        return comm_.publishBuffer(reinterpret_cast<void *>(addr), length);
    }

    /**
     * Unpublish a previously published buffer
     * @param addr  Buffer address
     * @return 0 on success, negative error code on failure
     */
    int unpublishBuffer(uintptr_t addr) {
        return comm_.unpublishBuffer(reinterpret_cast<void *>(addr));
    }

    /**
     * Query remote host's published buffer information via TCP
     * @param remote_host_id  Remote host identifier (must be connected)
     * @param remote_tcp_addr Remote TCP address
     * @param remote_tcp_port Remote TCP port
     * @return dict with buffer info: {'addr': int, 'length': int, 'rkeys': [int...]}
     *         or empty dict on failure
     */
    py::dict queryRemoteBuffer(const std::string &remote_host_id,
                               const std::string &remote_tcp_addr,
                               int remote_tcp_port) {
        RemoteBufferInfo info;
        int ret = comm_.queryRemoteBuffer(remote_host_id, remote_tcp_addr,
                                          remote_tcp_port, info);
        py::dict result;
        if (ret == 0) {
            result["host_id"] = info.host_id;
            result["addr"] = info.addr;
            result["length"] = info.length;
            result["rkeys"] = info.rkeys;
        }
        return result;
    }

    /**
     * Get local published buffer info (for debugging/display)
     * @return dict with buffer info: {'addr': int, 'length': int, 'rkeys': [int...]}
     *         or empty dict if not published
     */
    py::dict getPublishedBufferInfo() {
        py::dict result;
        const PublishedBufferInfo* info = comm_.getPublishedBufferInfo();
        if (info) {
            result["addr"] = info->addr;
            result["length"] = info->length;
            result["rkeys"] = info->rkeys;
        }
        return result;
    }

private:
    MPComm comm_;
};

PYBIND11_MODULE(mpcomm, m) {
    m.doc() = "MPComm - Multi-Path Communication using native ibverbs";

    // Error codes
    py::enum_<MPCommError>(m, "MPCommError")
        .value("SUCCESS", MPCOMM_SUCCESS)
        .value("ERR_DEVICE", MPCOMM_ERR_DEVICE)
        .value("ERR_CONTEXT", MPCOMM_ERR_CONTEXT)
        .value("ERR_MEMORY", MPCOMM_ERR_MEMORY)
        .value("ERR_CONNECTION", MPCOMM_ERR_CONNECTION)
        .value("ERR_TRANSFER", MPCOMM_ERR_TRANSFER)
        .value("ERR_TIMEOUT", MPCOMM_ERR_TIMEOUT)
        .value("ERR_INVALID_ARG", MPCOMM_ERR_INVALID_ARG)
        .export_values();

    // MPComm class
    py::class_<MPCommPy>(m, "MPComm")
        .def(py::init<>())
        .def("init", &MPCommPy::init,
             py::arg("local_host_id"),
             py::arg("device_names") = "",
             py::arg("tcp_port") = 0,
             "Initialize RDMA resources")
        .def("shutdown", &MPCommPy::shutdown,
             "Shutdown and cleanup resources")
        .def("register_memory", &MPCommPy::registerMemory,
             py::arg("addr"),
             py::arg("length"),
             "Register local memory for RDMA operations")
        .def("unregister_memory", &MPCommPy::unregisterMemory,
             py::arg("addr"),
             "Unregister previously registered memory")
        .def("connect", &MPCommPy::connect,
             py::arg("remote_host_id"),
             py::arg("remote_tcp_addr"),
             py::arg("remote_tcp_port"),
             "Connect to a remote host via TCP metadata exchange")
        .def("start_accept_thread", &MPCommPy::startAcceptThread,
             "Start accepting incoming connections in background")
        .def("stop_accept_thread", &MPCommPy::stopAcceptThread,
             "Stop the accept thread")
        .def("update_remote_memory_info", &MPCommPy::updateRemoteMemoryInfo,
             py::arg("remote_host_id"),
             py::arg("rkeys"),
             "Update remote memory info (rkeys) for a connected host")
        .def("get_rkey", &MPCommPy::getRkey,
             py::arg("nic_index"),
             py::arg("addr"),
             "Get rkey for local memory region on a specific NIC")
        .def("get_all_rkeys", &MPCommPy::getAllRkeys,
             py::arg("addr"),
             "Get all rkeys for local memory region (one per NIC)")
        .def("scatter", &MPCommPy::scatter,
             py::arg("local_addr"),
             py::arg("host_list"),
             py::arg("remote_addrs"),
             py::arg("lengths"),
             py::arg("num_threads") = 1,
             "Scatter: distribute local data to multiple remote hosts (RDMA WRITE)")
        .def("gather", &MPCommPy::gather,
             py::arg("local_addr"),
             py::arg("host_list"),
             py::arg("remote_addrs"),
             py::arg("lengths"),
             py::arg("num_threads") = 1,
             "Gather: collect data from multiple remote hosts to local buffer (RDMA READ)")
        .def("mp_replicate", &MPCommPy::mpReplicate,
             py::arg("comm_type"),
             py::arg("host_list"),
             py::arg("local_addr"),
             py::arg("remote_addrs"),
             py::arg("lengths"),
             py::arg("num_threads") = 1,
             "Unified interface for scatter/gather operations")
        .def("get_num_nics", &MPCommPy::getNumNics,
             "Get number of available NICs")
        .def("get_local_host_id", &MPCommPy::getLocalHostId,
             "Get local host ID")
        .def("get_tcp_port", &MPCommPy::getTcpPort,
             "Get TCP port for metadata exchange")
        .def("get_gid", &MPCommPy::getGid,
             py::arg("nic_index"),
             "Get GID string for a specific NIC")
        .def("get_device_name", &MPCommPy::getDeviceName,
             py::arg("nic_index"),
             "Get device name for a specific NIC")
        .def("get_active_devices", &MPCommPy::getActiveDevices,
             "Get all active device names")
        .def_static("get_nic_filter_env_var_name", &MPCommPy::getNicFilterEnvVarName,
             "Get the NIC filter environment variable name (MPCOMM_NIC_FILTER)")
        .def_static("get_qps_per_connection_env_var_name", &MPCommPy::getQpsPerConnectionEnvVarName,
             "Get the QPs per connection environment variable name (MPCOMM_QPS_PER_CONNECTION)")
        .def("get_qps_per_connection", &MPCommPy::getQpsPerConnection,
             "Get the number of QPs per NIC connection")
        .def("write_bytes_to_buffer", &MPCommPy::writeBytesToBuffer,
             py::arg("addr"),
             py::arg("data"),
             py::arg("length"),
             "Write bytes to a registered buffer")
        .def("read_bytes_from_buffer", &MPCommPy::readBytesFromBuffer,
             py::arg("addr"),
             py::arg("length"),
             "Read bytes from a registered buffer")
        .def("publish_buffer", &MPCommPy::publishBuffer,
             py::arg("addr"),
             py::arg("length"),
             "Publish a local buffer for remote access via TCP metadata exchange")
        .def("unpublish_buffer", &MPCommPy::unpublishBuffer,
             py::arg("addr"),
             "Unpublish a previously published buffer")
        .def("query_remote_buffer", &MPCommPy::queryRemoteBuffer,
             py::arg("remote_host_id"),
             py::arg("remote_tcp_addr"),
             py::arg("remote_tcp_port"),
             "Query remote host's published buffer information via TCP")
        .def("get_published_buffer_info", &MPCommPy::getPublishedBufferInfo,
             "Get local published buffer info");
}

}  // namespace mpcomm
