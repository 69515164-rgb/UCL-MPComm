# MPComm 最小示例 —— Hello, MPComm!

本目录提供了 **尽可能精简** 的 MPComm 使用示例，覆盖 **C++** 和 **Python** 两种语言。
它被设计为一份可以从头读到尾的入门教程：在约 100 行代码中完整展示一个 MPComm 程序的
生命周期 —— init → register → publish/query → put → get → verify → shutdown，
没有性能基准、没有多 NUMA、没有多轮循环等干扰内容。

文件列表：

| 文件 | 用途 |
|---|---|
| `hello_mpcomm.cpp` | C++ 单文件示例（`target` / `initiator` 两种角色） |
| `hello_mpcomm.py`  | 同一示例的 Python 版本（使用 `mpcomm` pybind11 模块） |
| `CMakeLists.txt`   | 基于已安装的 `mpcomm::mpcomm` 目标构建 C++ 示例 |
| `build.sh`         | CMake 构建的便捷封装脚本 |
| `run-target.sh`    | 启动 `target` 端（在文件头部修改 IP/端口） |
| `run-initiator.sh` | 启动 `initiator` 端（在文件头部修改 IP/端口） |

## 示例做了什么

1. **target 节点**
   - `init(host_id, devices, tcp_port)` —— 建立 RDMA QP，并启动 TCP 元数据监听
   - 分配一块 DRAM 缓冲区，调用 `register_memory(addr, len)` 注册
   - `publish_buffer(addr, len)` 发布缓冲区，让 initiator 能查询到它的地址和 rkeys
   - `start_accept_thread()` 启动接受线程，空转直到 Ctrl-C

2. **initiator 节点**
   - `init(...)`
   - 分配两块本地缓冲区：`send_buf`（填充 `byte[i] = i % 256`）和 `recv_buf`
   - 对两块缓冲区都调用 `register_memory()`
   - `connect(target_host_id, target_ip, target_port)`（TCP 握手）
   - `query_remote_buffer_by_numa(...)` —— 拿到 target 的 `{addr, length, rkeys}`
   - `put_async(send_buf → target.addr)` + `wait_transfer()` —— RDMA WRITE
   - `get_async(recv_buf ← target.addr)` + `wait_transfer()` —— RDMA READ
   - `memcmp(send_buf, recv_buf)` —— 校验数据往返正确性

## 构建 C++ 示例

该示例依赖已安装的 `mpcomm` 包（可通过 `pip install .` 安装 mpcomm wheel，
或使用传统的 `cmake --install`）。构建方法：

```bash
./build.sh
# -> build/hello_mpcomm
```

`build.sh` 会向 CMake 传入
`-Dmpcomm_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_cmake_dir())")`，
因此只要你能 `import mpcomm`，就能直接构建成功。

## 运行示例（两个终端，可同机也可跨机）

### 终端 A —— target

```bash
# 指定 target 身份标识和 TCP 握手端口
TARGET_IP=29.160.51.247 TCP_PORT=12345 ./run-target.sh
```

控制台输出示例：

```
[target] ready, host_id=29.160.51.247:12345 tcp_port=12345 buf=0x7f.... Ctrl-C to exit.
```

### 终端 B —— initiator

```bash
LOCAL_IP=29.160.51.248 \
TARGET_HOST_ID=29.160.51.247:12345 \
TARGET_IP=29.160.51.247 TARGET_PORT=12345 \
./run-initiator.sh
```

控制台输出示例：

```
[init] remote addr=0x... len=4194304
[init] put OK 4194304B 0.31ms
[init] get OK 4194304B 0.29ms
[init] VERIFY OK
```

## Python 版本

无需构建步骤，直接使用 Python 绑定即可：

```bash
# 终端 A
ROLE_IMPL=py TARGET_IP=29.160.51.247 TCP_PORT=12345 ./run-target.sh

# 终端 B
ROLE_IMPL=py \
LOCAL_IP=29.160.51.248 \
TARGET_HOST_ID=29.160.51.247:12345 \
TARGET_IP=29.160.51.247 TARGET_PORT=12345 \
./run-initiator.sh
```

或直接调用脚本：

```bash
python3 hello_mpcomm.py target    29.160.51.247:12345 12345

python3 hello_mpcomm.py initiator 29.160.51.248:0 \
    29.160.51.247:12345 29.160.51.247 12345
```

## 常用环境变量

示例遵循所有标准的 MPComm 环境变量，最常用的几个如下：

| 环境变量 | 作用 |
|---|---|
| `MPCOMM_NIC_FILTER` | 允许使用的 RDMA 网卡列表，逗号分隔（例如 `mlx5_bond_1,mlx5_bond_2`） |
| `MPCOMM_QPS_PER_CONNECTION` | 每个连接每块网卡上的 QP 数量（默认 1） |
| `MPCOMM_LOG_LEVEL` | 日志级别：`error` / `warn` / `info` / `debug` |

示例：

```bash
export MPCOMM_NIC_FILTER="mlx5_bond_1,mlx5_bond_2,mlx5_bond_3,mlx5_bond_4"
export MPCOMM_QPS_PER_CONNECTION=4
export MPCOMM_LOG_LEVEL=info
```

## 进阶用法

在 hello-world 跑通后，推荐的下一步尝试：

- 把 `put_async` + `get_async` 换成 **`scatter_async`** / **`gather_async`**，
  将一块大缓冲区分片到 *多个* target 上（传入 `host_list`、`remote_addrs`、
  `lengths` 列表即可）。
- 在 target 上多次调用 `publish_buffer`（每个 NUMA 节点一次），在 initiator
  上通过 `query_remote_buffer_by_numa(..., numa_node=N)` 选择 NUMA 亲和的
  缓冲区。
- 参考 `../scatter_test.cpp` / `../test_mpcomm.py`，它们是基于同样的接口
  原语构建的完整基准测试脚手架。
