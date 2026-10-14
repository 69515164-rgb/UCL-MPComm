# AI 推理问题量化调研（价值判定素材）

> **用途**：昇腾 950 统一通信控制面「价值判定」——业界公开问题分类 + 可引用量化 + benchmark 描述  
> **时间窗**：约 2025-04 ～ 2026-10（部分奠基工作略早，文中标清）  
> **口径**：先白话，术语放括号；正文不用「卸数 / 池化 / ±HCCL」  
> **知识树**：A 容量 · B 带宽 · C 传输 · D 复用 · E 调度 · F 新模型范式  
> **声明**：只引用公开源；找不到写「未找到公开数」。数字为原文量级，用于支撑「忙时尾延迟膨胀 / 破 SLO / 多买卡」叙述；**不等于昇腾 950 测实收益**。

---

## 1. 一页总览表

| 问题类别 | 严重性一句话 | 关键量化（带单位） | 对应 benchmark / 指标 | 来源（会议/公司 + 日期 + 链接） | 分支 |
|---|---|---|---|---|---|
| Prefill→Decode 跨机传 KV 撞路径 | 多路大 KV 流哈希撞同一脊链路，传完时间拉长，首字变慢 | 均值流完成时间最多 **−27.3%**，P95 **−34.0%**；均值 TTFT **−12.9%**（相对 ECMP）；单流 100K token / LLaMA-405B 约 **48 GB**，可占满 400 Gbps **~960 ms** | SimAI+NS-3；LLaMA-3-8B；16 GPU（8P/8D）；Zipf 提示；QPS 扫到 30；指标 FCT / TTFT | ARK，SIGCOMM’26 Workshop NIAC，2026-08 · [PDF](https://saeed.github.io/files/arc_niac26.pdf) · [ACM](https://dl.acm.org/doi/10.1145/3789240.3828750) | C |
| 机内 PCIe：KV 传卡 ↔ 本机内存搬 KV 互抢 | 关键路径 RDMA 写卡与本机 H2D 抢同一 PCIe 段，本机拷贝带宽可掉近八成 | H2D：**25.82 → 5.23 GiB/s（−79.8%）**；D2H 在 GDR read 下 **−53.9%**；保护后 PD KV 传时 **−19.4%～−34.4%**，均值 TTFT **−2.4%～−6.1%** | DGX-H100 受控微基准 + vLLM+Mooncake；Qwen3-8B；Codex/SWE-bench Pro 请求形态；KV 聚合 1.2～9.4 GB | GPUWeaver，APSys’26 · [PDF](https://yunmingxiao.github.io/publication/26apsys-gpuweaver/apsys26-gpuweaver.pdf) | B/C |
| 多机共享内存路径「传满」仍是数据面 | 共享内存那一路能跑多快，决定控制面下面「某一路引擎」的上限 | 4 NIC 零拷贝 PUT：**195.7 GB/s** vs Mooncake TENT **142.2 GB/s（约 +38%）** | 1 GB 块、batch=4、4 NIC；AMD Turin / RTX PRO 5000 等 | 腾讯 UCL-MPComm README（公开仓库）· [GitHub](https://github.com/Tencent/UCL-MPComm) | C |
| PD 分离后全局 KV 缓存不够 / 命中低 | 只靠本机内存缓存打不满理论命中，要跨机共享才值钱 | 生产：**A800 +115% / H800 +107%** 请求量；SLO 内有效容量 **+59%～+498%**；全局相对本机命中最高 **2.36×**，prefill GPU 时间最多 **-48%** | 16×8×A800；真实对话/工具链 + 合成长上下文；TTFT≤30s，TBT 100/200/300 ms | Mooncake，FAST’25，2025-02 · [PDF](https://www.usenix.org/system/files/fast25-qin.pdf) | A/D/C |
| 显存里 KV 装不下 → 往本机内存搬 | 搬完再算时，PCIe 吃掉绝大部分首字时间，卡算力空转 | 文档问答场景可 **99%** 时间在传；PCIe 开销相对算力最高约 **86×**；GPU 平均只到额定功耗 **~28%**；对话 κ 中位 **~100**，文档 **~5000** | vLLM+LMCache；H100×8；LLaMA-3.1-70B / Qwen3-235B；ShareGPT / NarrativeQA | arXiv:2601.19910，2025-12 · [HTML](https://arxiv.org/html/2601.19910) | A/B |
| 生产前缀复用：寿命短、命中偏斜 | 缓存策略不对会直接抬排队首字 | to-B 理想命中 **~54%**；P99 KV 寿命 **97 s**；工作负载感知淘汰相对 LRU 等：命中 +1.5～3.9%，**QTTFT −28.3%～−41.9%** | 阿里云通义生产 trace（2024-12 / 2025-02）；vLLM + CPU-GPU 缓存；Qwen2-7B / Llama2-13B / Llama3-70B | ATC’25 · [PDF](https://www.usenix.org/system/files/atc25-wang-jiahao.pdf) | D/A |
| 多请求抢 KV 块 → 尾延迟炸 | 并发刚过「装得下」的拐点，P99 首字可跳一个数量级 | 例：并发 12→14，P99 TTFT **2.6 s → 38.9 s（~15×）**，吞吐同时掉 **~23%** | Qwen3-4B on L4；22.8K-token agentic；fp8 KV | KVBench concurrency blog（公开）· [链接](https://ksmotiv8.github.io/kvbenchdocs/kvcache/concurrency/) | A/E |
| 争用调度 / 控制面级「让路」 | 业界已把「传输当可编排资源」写成系统论文 | 同上 GPUWeaver 案例；NVIDIA Dynamo 宣称 DeepSeek-R1 on GB200 NVL72 请求数最高约 **30×**（相对同引擎非 Dynamo 配置） | GTC 博客：FP4，ISL/OSL 32K/8K；对比 Inflight Batching vs Disagg | NVIDIA Dynamo 介绍，2025-03-18 · [Blog](https://developer.nvidia.com/blog/introducing-nvidia-dynamo-a-low-latency-distributed-inference-framework-for-scaling-reasoning-ai-models/) | E/C |
| 存储侧接住 KV 搬移带宽 | 控制面下面「多机共享 / 远端存」路径要够快才不拖后腿 | Vast→单 H100 **35 GB/s**；WEKA 八卡合计读吞吐最高 **270 GB/s** | DGX H100；Dynamo NIXL / GDS 插件 | NVIDIA Dynamo KV 博客，2025-09-18 · [Blog](https://developer.nvidia.com/blog/how-to-reduce-kv-cache-bottlenecks-with-nvidia-dynamo/) | A/C |
| 主机 CPU 干扰拖垮推理栈 | 稳态推理若绑在主机调度上，干扰下尾延迟可差两个数量级 | 干扰下基线 P99 TTFT 可膨胀至约 **139×**；Blink 相对基线 P99 TTFT 最多约 **8.47×** 改善 | 对比 TensorRT-LLM / vLLM / SGLang；有/无 CPU 干扰 | Blink，arXiv:2604.07609，2026-04 · [abs](https://arxiv.org/abs/2604.07609) | E |
| 零拷贝本机内存扩展 KV | 传统「先拷进卡再算」浪费带宽与显存 | 相对既有方案：CPU↔GPU 传输量最多 **−50%**，GPU 显存占用 **−43%**，端到端最多 **1.2×** | GH200；NVLink-C2C 直接读本机侧 KV | DirectKV，OSDI’26 · [USENIX](https://www.usenix.org/conference/osdi26/presentation/luo) | A/B |
| 本机算力卸载扩 batch | 卡显存不够大 batch 时，把部分注意力/KV 放到本机 CPU | 相对纯 GPU：T4 吞吐最高 **7.5×**，A10G **+26%**（更强 CPU 可到 **+79.3%**），H100 **+14%**，同延迟约束 | 代码生成/摘要；7B/8B/70B；T4/A10G/H100 | Neo，MLSys’25 · [PDF](https://proceedings.mlsys.org/paper_files/paper/2025/file/66a026c0d17040889b50f0dfa650e5e0-Paper-Conference.pdf) | A |
| MLA 等压缩降每 token KV | 从结构上少传、少存 | DeepSeek-V2 相对原 67B MHA：KV 约 **−93.3%**；同节点最大生成吞吐约 **5.76×** | 官方技术报告公开数 | DeepSeek-V2 tech report · [arXiv HTML](https://arxiv.org/html/2405.04434v3) | F/A |

---

## 2. 按类别详细展开

### 2.1 显存 / KV 容量不够（分支 A）

#### 证据 A1 — 生产侧：KV 寿命短、小缓存即可逼近理想命中（ATC’25）

- **白话问题**：线上请求的 KV 活不久；缓存策略若按「谁用得多留谁」会留一堆已死块，反而挤掉马上要用的前缀。
- **量化（原文）**：to-B 工作负载理想命中约 **54%**（to-C 约 **62%**）；to-B 的 P99 KV 寿命约 **97 秒**；容量约为每 GPU 可用 HBM 的 **2×** 时，在常见 GQA 模型 + LRU 下可逼近无限容量理想命中；工作负载感知淘汰相对最佳基线命中高 **1.5～3.9%**，排队首字（QTTFT）降 **28.3～41.9%**。
- **Benchmark**：阿里云通义一周量级生产 trace（文中展示代表日）；匿名化 token hash；模型 Qwen2-7B / Llama2-13B / Llama3-70B（70B 用 4 卡）；指标：缓存命中率、QTTFT（TTFT+排队）。
- **和我们控制面的关联**：容量问题本身靠缓存策略/压缩解决；控制面价值在「容量不够时往本机内存/多机共享内存搬」的**路径争用**，不直接替代缓存策略。

#### 证据 A2 — 并发刚过拐点，P99 首字跳崖（KVBench 公开实验）

- **白话问题**：卡上同时装不下所有会话的 KV 时，系统开始换出、重算，尾延迟不是慢慢变差，而是断崖。
- **量化**：并发 **12→14**，P99 TTFT **&lt;2.6 s → 38.9 s（约 15×）**，吞吐峰值 1.36 req/s 处掉约 **23%**；2 s P99 SLA 下安全点约 **6** 并发（fp8）。
- **Benchmark**：Qwen3-4B，NVIDIA L4；约 22.8K token agentic 会话（含 10K 共享前缀）；扫并发与 KV 精度（fp16/fp8）。
- **关联**：支撑「忙时破 SLO → 只能少接请求 / 多买卡」；控制面不解决容量拐点本身，但忙时多路传输争用会**提前**把系统推向拐点。

#### 证据 A3 — Neo：把部分 KV/注意力放到本机 CPU 换吞吐（MLSys’25）

- **白话问题**：显存不够大 batch，算力空着；把一部分状态放到本机内存并和 GPU 流水线重叠，能多跑请求。
- **量化**：相对纯 GPU，吞吐最高 **T4 7.5× / A10G +26%（更强 CPU +79.3%）/ H100 +14%**，延迟目标不变。
- **Benchmark**：代码生成、文本摘要；7B/8B/70B；T4、A10G、H100。
- **关联**：说明「KV 挪到本机内存」已是业界标配手段；一旦开启，就引入 **PCIe 上的第二类流量**，与 PD 传 KV 叠在一起——正是控制面要编排的对象。

---

### 2.2 HBM / 内存带宽打满（分支 B）

#### 证据 B1 — NVLink 传数据 vs 本机算力读 HBM 互抢（GPUWeaver）

- **白话问题**：卡与卡之间走 NVLink 搬状态时，和本卡算力读 HBM 抢同一套片上互联与内存控制器。
- **量化**：受控微基准下，重叠充分时 HBM 有效带宽大约掉 **~20%**（短传输约 3～10%）；NVLink 侧在「短传被长内存访问完全盖住」时可掉约 **20%**，对角线上多约 **5～7%**。
- **Benchmark**：DGX-H100；内存访问核 + `cudaMemcpyPeerAsync` 双向；缓冲 128 MB～4 GB 二维扫描；指标：相对隔离基线的带宽退化百分比。
- **关联**：Decode 多卡集合通信 / 卡间搬 KV 会与算力抢 HBM——控制面「按路径让路」叙事的硬件层依据。

#### 证据 B2 — 本机内存侧 KV 很大时，prefill 从算力瓶颈变成带宽瓶颈（arXiv:2601.19910）

- **白话问题**：缓存命中很多、新 token 很少时，大部分时间在等 PCIe，不在算。
- **量化**：κ_crit 多为 **&lt;15**（按有效 PCIe）；工作负载 κ 中位：对话 **~100**、文档 **~5000**；例：Qwen、K=65k、T=64 时 PCIe 开销约 **86×** 算力时间（约 **99%** 时间在传）；GPU 平均功耗约额定 **28%**。
- **Benchmark**：8×H100 SXM5；vLLM 0.10.1 + LMCache；LLaMA-3.1-70B / Qwen3-235B-A22B；ShareGPT、NarrativeQA；指标 TTFT、PCIe 开销、功耗。
- **关联**：硬支撑「KV 挪到本机内存」不是免费的——忙时若再叠 PD RDMA，尾延迟更容易炸。

---

### 2.3 PD 分离与跨机 KV 传输（分支 C）

#### 证据 C1 — ECMP 哈希碰撞拉长 KV 流（ARK，SIGCOMM’26 NIAC）

- **白话问题**：Prefill 卡算完要把整份 KV 送给 Decode 卡；这种流动辄数百毫秒到数秒，传统「大象流」才几十 MB，而 100K token 的 LLaMA-405B KV 约 **48 GB**，可单独占满 400 Gbps 约 **960 ms**。多条大流若哈希到同一脊链路，完成时间被拉长，首字直接变差。
- **量化（相对 vanilla ECMP）**：QPS=25 时均值 FCT **−27.3%**，P95 FCT **−34.0%**；端到端均值 TTFT 最多约 **−12.9%**。热力图：ECMP 单脊可达 **18** 路并发，ARK 峰值压到约 **&lt;8**。
- **Benchmark**：SimAI（Vidur 算力）+ AstraSim/NS-3 RDMA；拓扑对齐阿里 HPN 风格两层 leaf-spine，16 GPU（8P/8D），链路 100 Gbps，叶脊过订阅 2:1；LLaMA-3-8B Zipf(α=0.7) 提示，均值约 13.3K token → KV 均值约 **1.6 GB**（125 MB～6.7 GB）；Poisson QPS 1～30；每实验 1000 请求；TTFT = prefill + KV_FCT + 首步 decode。
- **关联**：**最直接**支撑控制面「路径级编排 / 违约能拦」——业界已证明只靠 ECMP 不够，需要准入时选路。

#### 证据 C2 — Mooncake：生产 PD + 全局 KV 缓存（FAST’25）

- **白话问题**：把 Prefill / Decode 拆开，再用集群里闲置的本机内存、SSD、网卡做成跨会话共享的 KV 仓库；用存储换计算。
- **量化**：线上相对旧系统，A800 集群请求量 **+115%**，H800 **+107%**；回放实验 SLO 内有效请求容量 **+59%～+498%**；全局缓存相对本机命中最高 **2.36×**，prefill 计算时间最多 **-48%**；传输引擎搬 40 GB 缓存时相对 TCP 约 **2.4× / 4.6×**（4×200G / 8×400G NIC）。
- **Benchmark**：16 节点 × 8×A800 + 4×200 Gbps RDMA；伪 LLaMA3-70B；真实对话/工具链 + ShareGPT/L-Eval/LooGLE 合成；TTFT SLO 30 s，TBT 100/200/300 ms；有效请求 = 同时满足 TTFT 与 TBT。
- **关联**：定义了「多机共享内存」数据面标杆；控制面应**编排**含这一路在内的多路，而不是替代 Mooncake/MPComm 这类引擎。

#### 证据 C3 — 腾讯 UCL-MPComm：共享内存数据面带宽（公开 README）

- **白话问题**：多机共享内存上的 put/get 要尽量吃满多网卡。
- **量化**：4 NIC、1 GB 块、batch=4，零拷贝 PUT/GET 约 **195.7 / 195.7 GB/s**，对比 Mooncake TENT **142.2 / 142.3 GB/s**（约 **1.38×**）；非零拷贝相对 UCX 最高约 **5×**。
- **Benchmark**：AMD Turin + RTX PRO 5000 / AMD Genoa + H20；公开表格。
- **关联**：对比图里「共享内存那一路可接 MPCOMM」的定量注脚；层次是数据面，不是控制面。

#### 证据 C4 — NVIDIA Dynamo：PD 分离框架级吞吐（GTC’25 博客）

- **白话问题**：工业界把 Prefill/Decode 拆开、动态分卡、KV 感知路由、异步传 KV，做成开源框架。
- **量化**：DeepSeek-R1 on GB200 NVL72，请求数最高约 **30×**（相对同引擎非 Dynamo 配置）；Llama 70B on Hopper 吞吐超过 **2×**。脚注条件：左图 TensorRT-LLM FP4，ISL/OSL 32K/8K；右图 vLLM FP8，ISL/OSL 3K/50。
- **关联**：说明「统一推理侧传输栈」已是大厂主航道；我们差异化要对齐「可编排资源 + 护城河」，不能停在「多抓手」。

---

### 2.4 多租户 / 多请求争用与尾延迟（分支 E / C）

#### 证据 E1 — PCIe 上「关键 KV 传」被「本机搬 KV」挤掉（GPUWeaver 案例）

- **白话问题**：Prefill→Decode 的 GPUDirect RDMA 写，和本机把前缀 KV 搬到 CPU，走同一段 GPU 侧 PCIe；后台搬移会拖住关键路径。
- **量化**：H2D 在并发 GDR write 下 **−79.8%**；集成 vLLM+Mooncake、Qwen3-8B、真实 agent 请求形态后，PD KV 传时 **−19.4%～−34.4%**，均值 TTFT **−2.4%～−6.1%**（TTFT 增益小于传时增益，因传 KV 只占 TTFT 一部分）。
- **关联**：**几乎是我们控制面故事的镜像**——忙时多路（PD KV + 本机内存搬 + 可选共享内存）需要按优先级注入/让路。

#### 证据 E2 — 主机 CPU 干扰导致尾延迟数量级恶化（Blink）

- **白话问题**：传统推理栈稳态仍依赖主机 CPU 做调度/批处理；机器上别的活一抢 CPU，尾延迟可炸。
- **量化**：论文称干扰下现有系统 P99 可恶化达约两个数量级（公开综述引至约 **139×** TTFT）；Blink 宣称隔离态 P99 TTFT 最多约 **8.47×**、P99 TPOT 约 **3.40×** 优于基线，干扰下仍接近隔离吞吐。
- **关联**：提醒价值判定：尾延迟不全是「网」的问题，还有主机控制面；我们方案边界写清「默认可执行层=用户态包装」与铁面一致。

---

### 2.5 KV 挪到本机内存的开销（分支 A/B）

见 **B2、A3、DirectKV（OSDI’26：传输量 −50%，显存 −43%，e2e 最多 1.2×）**。  
要点一句话：业界一边证明「必须挪」，一边证明「挪完 PCIe 会变成新瓶颈」——控制面要管的正是这条新瓶颈与 PD 路径的叠加。

---

### 2.6 多机共享内存路径（分支 C/D）

见 **C2 Mooncake、C3 MPComm、NVIDIA Dynamo 存储验证（单卡 35 GB/s、八卡 270 GB/s）**。  
要点：共享内存路径已有「传满」竞赛；我们的差异是**多路编排**，可把 MPComm 类引擎挂在其中一路之下。

---

### 2.7 Decode 多卡集合通信叠推理（分支 B/C）

- **公开量化**：近半年顶会里，**单独把「Decode 侧集合通信与 PD-KV / 本机搬 KV 三叠一」测出的 P99 膨胀百分比**，未找到可直接引用的昇腾或通用公开表。
- **可引用间接证据**：GPUWeaver 证明 NVLink 流量与 HBM 算力访问互抢（约两成带宽退化）；ARK/Mooncake/Dynamo 证明 PD-KV 已是独立大象流。三者叠加的「主场景 / 加码场景」需按铁面规格在典型单元上**分档测实**。
- **关联**：价值页不要写「±集合通信」黑话；写成两档：主场景不开 Decode 多卡集合通信；加码场景再叠上。

---

### 2.8 调度与批大小（分支 E）

- **CacheOPT（arXiv:2503.13773，2025-03）**：缓解 KV 块竞争，称尾 TBT / 尾 TTFT 最多约 **3.29× / 2.83×** 改善，SLO 达成率升约 **47% / 53%**，可支撑到达率约 **1.58×**。[HTML](https://arxiv.org/html/2503.13773)
- **关联**：调度层能吃掉一部分竞争；与传输控制面正交，价值故事可并列「调度选谁算」与「传输谁先走」。

---

### 2.9 成本 / 卡数 / TCO（分支 A/E）

| 来源 | 量化 | 能否当「已签收益」 |
|---|---|---|
| Mooncake 生产 | A800/H800 同集群请求量 +115% / +107% | 可作**业界旁证**（Moonshot 栈），非昇腾测实 |
| Splitwise（ISCA’24，略早于窗口） | 同吞吐最高约 **1.4×** 且成本约 **−20%**；或同成本功耗下吞吐约 **2.35×** | 旁证「PD 分离省卡」，需注明年份 |
| Dynamo 博客 | 某 planner 材料提到「约 80% TTFT 降、少约 5% GPU」等（会议幻灯片口径） | **谨慎**：作情景参考，核对原始幻灯条件后再用 |
| 本组业务假设（已有） | 100/125/102 ms，SLO 110，f=35% → 高峰少用约六成单元 / 日均约两成 | **仅价值评估情景**，铁面不签 |

---

## 3. 「可直接用于价值判定」的推演素材

### 3.1 可硬撑叙述的公开数（建议上内部价值页脚注）

| 叙述句 | 可用公开锚点 | 用法 |
|---|---|---|
| 「忙时多路 KV 传会互相拖慢」 | ARK：碰撞下 FCT/TTFT 可改善十几到三十多个点；单流可达数十 GB、近秒级占链路 | 支撑「规模越大越忙越需要路径编排」 |
| 「本机搬 KV 会挤关键 PD 传」 | GPUWeaver：H2D −79.8%；保护后 PD 传时 −19～34%，TTFT −2～6% | 支撑「四路里至少两路已经在抢 PCIe」 |
| 「只靠本机缓存不够，要跨机共享」 | Mooncake：全局命中最高 2.36×；生产请求量约翻倍 | 支撑「多机共享内存」一路的存在必要 |
| 「挪到本机内存后首字会被 PCIe 吃掉」 | arXiv:2601.19910：最高约 99% 时间在传；GPU ~28% TDP | 支撑「不能无脑叠搬移」 |
| 「破容量拐点 → P99 跳崖 → 只能少接或加卡」 | KVBench：P99 约 15× 跳变 | 支撑「破 SLO / 多买卡」逻辑链 |
| 「工业界已把传输栈产品化」 | Dynamo 30× / 2× 量级；MPComm 带宽表 | 支撑差异化要对齐「可编排」而非「多几个旋钮」 |

### 3.2 只能当情景外推、不能当测实收益

- 任何把 ARK 的 **−27% FCT** 或 GPUWeaver 的 **−30% 传时** 直接写成「客户 TTFT −X% / 少买 Y% 卡」——**禁止**（拓扑、模型、P:D、过订阅、有无本机搬 KV 均不同）。
- Mooncake 生产 **+115%** 是 **Moonshot 全栈**（缓存+调度+PD+传输）收益，不能单记在「控制面」账上。
- Dynamo **30×** 含 PD 分离 + 路由 + 框架，对比基线是同引擎非 Dynamo，**不是**「加一个控制面相对无控制面」。
- 本组 **100/125/102、少用六成/两成** 仍是业务假设；铁面口径：测实三个数到位前只写「准入门槛 / 情景」。

### 3.3 推荐的价值判定推演骨架（给人看的）

1. **问题**：典型单元忙时，多路 Prefill→Decode KV + 本机内存搬 KV + 多机共享内存（± Decode 多卡集合通信）抢网/抢 PCIe。  
2. **公开严重性**：路径碰撞可让传完时间多出两到三成量级（ARK）；本机搬移可让 H2D 掉近八成（GPUWeaver）；容量一过拐点 P99 可跳一个数量级（KVBench）。  
3. **后果**：TTFT/TBT 破 SLO → 只能降并发或加卡（Mooncake/DistServe 类 goodput 叙事）。  
4. **我们的抓手**：统一控制面把四路变成可编排资源（铁面已签 C 叙事）；执行层默认用户态包装，硬件 QoS TBD。  
5. **过线**：测实 \(B_0/B_c/\mathrm{After}\) 后用同公式替换，再送收益复核。

---

## 4. 缺口清单（近半年公开信息仍缺什么）

1. **昇腾 950 / 950PR+950DT / UBoE 现场测实**：安静 \(B_0\)、忙时无控制面 \(B_c\)、有控制面 After（≥20 次 P99）——**公开侧未找到**，必须自测。  
2. **「三叠一」或「四叠一」争用曲线**：PD-KV + 本机内存搬 + 多机共享内存 + Decode 集合通信同开时的 P99 膨胀百分比——通用公开完整表**未找到**；GPUWeaver 只覆盖其中 PCIe 两路。  
3. **昇腾集合通信（HCCL 等价物）与 PD-KV 同链路争用的公开数**——未找到。  
4. **客户侧真实忙时请求占比 \(f\)**（本组 35% 为假设）——未找到可对标的昇腾客户公开统计；阿里 ATC’25 有复用时间分布但非「带宽忙时窗占比」。  
5. **控制面自身开销**（铁面门槛 ΔP99≤+20μs）的业界对标公开数——ARK 控制器微基准为微秒级，但是模拟器主机侧，**不能**直接当昇腾控制面开销。  
6. **相对「仅软限速」的量化优势**：GPUWeaver 是注入调节/延迟注入原型，**不是**完整「违约能拦 + 路径级规矩」产品对比；缺 head-to-head。  
7. **TCO 人民币/卡年**级别公开对比——大厂博客多为相对百分比，缺可审计成本模型。

---

## 5. 检索说明（便于复核）

| 来源类型 | 已覆盖 | 备注 |
|---|---|---|
| 顶会 | FAST’25 Mooncake；ATC’25 Alibaba KV；MLSys’25 Neo；OSDI’26 DirectKV；SIGCOMM’26 NIAC ARK；APSys’26 GPUWeaver | DistServe OSDI’24 / Splitwise ISCA’24 略早，仅作奠基旁证 |
| 大厂 | NVIDIA GTC/Dynamo 博客（2025-03、2025-09）；LMSYS DeepSeek PD 博客（2025-05，吞吐导向）；腾讯 UCL-MPComm | Meta/Google 近半年「推理传输争用」带硬百分比的公开文相对少 |
| arXiv | 2601.19910 KV offload；2503.13773 CacheOPT；2604.07609 Blink | 以 PDF/HTML 原文数字为准 |
| 开源 | vLLM/SGLang Mooncake connector；MPComm | 多为机制与带宽表，少端到端 SLO |

---

*整理日期：2026-10-13（Asia/Shanghai）。数字如与原文冲突，以原文 PDF/官方博客为准。*
