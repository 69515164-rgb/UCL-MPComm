# NVIDIA 参数面：架构、标准策略、大客户定制

研究截止 **2026-09-28**。配套幻灯片 `docs/nvidia-param-plane.pptx`（19 页）。参数面指承载集合通信的东西向 RDMA 织物，包含 Spectrum-X 以太和 Quantum InfiniBand。NVLink、BlueField 南北向、上下文存储不在参数面里。

证据等级写在每条后面：论文、官方、厂商口径、媒体。厂商口径只表示「NVIDIA 确实这么说」。

## 1. 参数面在五支柱中的位置

NVIDIA 在 2026 年 Hot Chips 把 AI 工厂网络说成五支柱（SDxCentral、Converge Digest 对 Gilad Shainer 的转述）：

| 支柱 | 实现 | 是否参数面 |
| --- | --- | --- |
| Scale-Up | NVLink 6，72 GPU 一个域，每 GPU 3.6 TB/s，整域 260 TB/s | 否 |
| Scale-Out | Spectrum-X 以太，或 Quantum InfiniBand | 是 |
| Scale-Across | Spectrum-XGS | 参数面向外的一跳 |
| Context Memory | BlueField-4 STX / CMX，共享 KV | 否 |
| Scale-In | BlueField-4 + DOCA，安全、存储、控制面 | 否，故意分开 |

端点带宽三代（Spectrum-X 产品页 FAQ；Vera Rubin 技术博客）：

| 代 | 每 GPU 东西向 | 端点 |
| --- | --- | --- |
| Hopper | 400 GbE | 论文测试床 ConnectX-7；xAI 部署 BlueField-3 |
| Blackwell | 800 Gb/s（2×400G） | ConnectX-8 |
| Vera Rubin | 1.6 Tb/s | ConnectX-9。官网 FAQ 写 4×200G，技术博客表格写 2×800G，算术不一致。两边一致的只有总数 1.6 Tb/s |

## 2. 两条参数面

**Quantum-X800**（官方产品页）：144×800 Gb/s，SHARP v4，自适应路由，基于遥测的拥塞控制，UFM。Huang 在 Q2 FY2026 财报电话说，对超算和头部模型厂商，Quantum InfiniBand 是明确选择。Azure NDv6 GB300 集群内、CoreWeave GB300 用的是这一代。

**Spectrum-X 以太**（论文 arXiv:2605.21187；DSX 新闻稿 2026-03-16）：Vera Rubin DSX 参考设计点名的织物是 Spectrum-X Ethernet。Huang 原话：Spectrum Ethernet is not off the shelf。Shainer：抖动不能只靠交换机或只靠网卡解决。

物料只写两边口径一致的数：

| | Hopper | Blackwell | Vera Rubin |
| --- | --- | --- | --- |
| 以太交换 | Spectrum-4，51.2 Tb/s；SN5600 为 64×800GbE | SN5000 系列，同一代芯片 | Spectrum-6，102.4 Tb/s/芯片，200G SerDes；SN6600 128×800G；SN6800 512×800G，5U |
| InfiniBand | Quantum-2 | Quantum-X800，144×800G，SHARP v4 | 官方仍与 Spectrum-X 并列为 Rubin 的 scale-out |
| 论文测试床 | 1024 GPU，1 平面，三层胖树，CX-7 | 144 GPU 单平面 CX-7；1152 GPU、4 平面、CX-8、两层 rail-optimized | 架构章停在 Blackwell Ultra |

SN6800 的 409.6 Tb/s 是 4×102.4 的推算，片子和本文都不写。

## 3. 架构：多平面和三条控制环

来源：Khashab 等，*High-speed Networking for Giga-Scale AI Factories*，arXiv:2605.21187，2026-05-20。幻灯片嵌了 Figure 2、4、5、8、12、13。

**拓扑。** 平面在交换机侧断开。每张网卡经无源光 shuffle box 接入全部平面，网卡之间仍全可达。论文给出的容量上界：两层多平面 12.8 万端点，三层 1600 万。这是拓扑上界，不是已交付规模。无论几个平面，网卡只暴露一个 RoCE 设备，NCCL 和传输层不用改。乱序由网卡直接落内存，完成队列在网卡里重排。

**三条环，信号和时间尺度分开。**

| 环 | 位置 | 状态 | 时间尺度 | 做法 |
| --- | --- | --- | --- | --- |
| 自适应路由 | 交换机 fabric 口 | 无状态，逐包 | 数百纳秒 | 量化 JSQ。出口队列亚微秒采样，转发到最空的口之一 |
| 平面负载均衡 | 网卡平面口 | 每平面每目的地 | 逐包，数个 RTT | 先按速率额度掩掉限速面和故障面，再选本地最浅队列 |
| 拥塞控制 | 发送端 | 每目的地 | RTT | RTT 探针。ECN 只在负载均衡容量用尽时标记 |

拆开的原因：fabric 口上的微突发会抬高 RTT。若拥塞控制把这读成端点 incast，会在所有平面上一起限速。平面内一条上联故障对其余链路的负载增加不到 1%；四平面断一平面，剩下的会被不成比例地打满。所以平面内无状态，平面间有状态。

逐包喷洒使乱序和丢包分不清，链路层因此无损。NVIDIA 称两年生产运行里没有观察到 PFC 风暴。超过 97% 的流量容忍乱序；要保序的控制流量走普通以太 / TCP / BGP。

**故障。** 本地链路，自适应路由约 100 纳秒排除。远端永久不对称的权重由 BGP 计算，之后硬件仍按包平衡（Figure 5）。四平面断一平面，硬件平面负载均衡在 3 毫秒内回到 75% 线速；NCCL 之上的软件负载均衡要 1.08 秒，论文称大约慢 400 倍（Figure 12）。永久少 10% 链路时，p01 带宽从 377.80 降到 335.31 Gb/s（−11%），p99 时延从 14.97 升到 15.96 微秒。NSX 仿真 25.6 万 GPU：收敛停在 10 毫秒内，P99 集合完成时间约 +20%；100 毫秒约 +53%，300 毫秒约 +260%。

## 4. 论文实测（对照是 DCQCN + ECMP）

对照不是 UEC，也不是云厂商自研喷洒。

| 实验 | 结果 |
| --- | --- |
| 64 节点，流量全部过脊 | p01 带宽 377 Gb/s，线速的 98% |
| 300 Gb/s 下的 p99 | Spectrum-X 8–9 微秒；以太中位约 13 微秒，散到 22 微秒 |
| 安静 All2All | 49.3 / 49.5 GB/s；以太顶在 43 GB/s |
| 16 节点受害、48 节点背景 | 以太受害带宽掉到 10.9 GB/s 以下，约掉八成；Spectrum-X 近乎不掉 |
| DeepSeek-V3 代理，16 节点 NVL8 | 单独 667 ms，有背景流量仍 668 ms；以太从 735 ms 涨到 1.18 秒 |
| 两台叶上联削到四分之一 | 全局一份拥塞上下文，一对多从 94.5 掉到 47.3 GB/s；按平面分开的上下文维持 93.7。4 MB 以下可低到 0.75–0.85 |

部署陈述（论文，未经第三方审计）：数十个客户集群，合计超过 100 万 GPU。

运维：自适应路由把流量打成对称，偏离就是故障或配错。高频遥测采样在 100 微秒到 10 毫秒。

## 5. 和参数面一起卖、但不在同一层

| 事项 | 位置 | 口径 |
| --- | --- | --- |
| SHARP | Quantum-X800 的 v4；NVLink 6 交换托盘 14.4 TFLOPS FP8 | 以太交换机的公开特性清单没有对等项。云伙伴规范 NET-2 写 SHARP where supported |
| Spectrum-XGS | 2025-08 发布。500 米以上到数百公里 | 厂商：10 公里大消息 AllReduce 相对现成以太 1.9 倍，内部实验。具名首个采用者 CoreWeave。微软跨站的公开名称是 MRC |
| 共封装光 | Spectrum-6 上的 Spectrum-X Ethernet Photonics | 厂商：相对可插拔，能效 5 倍、故障间隔 10 倍、正常运行 5 倍。GTC 2026 称已投产 |

NVLink 6 上 SHARP 的 50% 通信量、20% 张量并行，是厂商口径，而且发生在 scale-up，不是以太参数面。

## 6. 标准组织

归纳判断（分析，不是 NVIDIA 的自我描述）：**买入的层做成标准，卖出的层发放许可。** 不能说 NVIDIA 不做标准。它做物理层标准，避开传输层标准。

| 层 | 组织 | 公开位置 |
| --- | --- | --- |
| 物理层 | IEEE 802.3dj、OIF | 2026-03 的 802.3dj 出席名单至少 6 名 NVIDIA 工程师，并署名评论决议。Karl Bois 任 OIF 技术委员会副主席（2026-01-14 公告） |
| 机柜 | OCP | 2024-10-15 捐赠 GB200 NVL72 机柜、托盘、线缆仓体积。Spectrum-X 支持 SAI 与 SONiC。协议文本不捐 |
| Scale-out 传输 | UEC | 2024-06-26 向 The Next Platform 确认会员；2024-09 列入一般会员。无指导委员会席位。查无工作组主席或编辑（联盟不公布名册，所以是查无，不是证明零贡献） |
| RoCE | IBTA | Shainer：RoCE 在 IBTA 标准化，NVIDIA 在其中 |
| Scale-up 以太 | OCP ESUN、SUE-T | ESUN 2025-10-13 的 12 家创始含 NVIDIA 与 OpenAI。1.0 于 2026-02-12 批准，是需求基线，不是线协议，大部分引用 UEC 1.0。Broadcom 把 NVIDIA 列入 SUE-T 支持者 |
| Scale-up 协议 | UALink | 2024-05-30 发起时不在场。1.0（2025-04-08）200G/lane、每 pod 1024 加速器。2.0（2026-04-07）写入网内计算，早于 1.0 硅片出货 |
| 中国规范 | ODCC、GSE、ETH-X、ALS | 查无 NVIDIA。阿里、百度、字节、华为、腾讯在 2023-11 加入的是 UEC |

**UEC 1.0**（2025-06-11）已发布：UET 四子层，逐包多路径，无握手短连接，选择性重传，可选 LLR、CBFC、包修剪，NSCC / RCCC，可选网内集合，AI Base / AI Full / HPC。物理层和 IP 层不动。

**UEC 1.1** 截至 2026-09-28 未发布。2025-11 给 IEEE 的联络函写过 CSIG 计划在 2026 Q1 随 1.1 公布。1.0.3（2026-07-16）只补了 200 Gb/s 每车道。1.1 计划里有 scale-up、统一转发头、RODL、单向时延 <1 微秒、PCM。

功能对照是分析：

| 功能 | UEC | Spectrum-X |
| --- | --- | --- |
| 多路径 | Packet spray | 交换机自适应路由，SuperNIC 重排 |
| 拥塞控制 | NSCC / RCCC；1.1 计划 PCM，算法可跨网卡 | SuperNIC 可编程拥塞控制 |
| 遥测 | CSIG，4 或 8 字节 | 端到端高频遥测，线格式不公开 |
| 链路可靠 | LLR + CBFC | 单链路故障限制在该链路；无公开互操作规范 |
| 网内集合 | INC，可选 | SHARP，在 NVLink 与 IB |
| 传输 | UET | RoCEv2 加 NVIDIA 扩展 |
| Scale-up | 1.1 计划 | NVLink |

截至 2026-09-28，NVIDIA 没有 UEC 符合性声明。ConnectX-8 手册列 IEEE 802.3 与 IBTA 1.7。Broadcom Thor Ultra（2025-10-14）宣称 fully feature compliant。OFC 2026 首次公开的 LLR/CBFC 800GE 互通是 Keysight 加 Broadcom。

**SUE** 作者是 Broadcom，2025-04 贡献 OCP，修订史上唯一作者。SUE-Lite（2025-07）砍掉端到端可靠、拥塞控制和分区，只留逐跳 LLR，规范写明 IP 面积最多减少 50%。

**NVLink Fusion**（2025-05-18）许可 C2C、融合芯粒、交换机芯片和 MGX。协议文本没有捐给任何标准组织。投资：Intel 50 亿美元（2025-12 交割），Marvell 20 亿美元（2026-03），MediaTek 35 亿美元可转债（2026-08）。接入方含 AWS Trainium4、Fujitsu、Qualcomm、SiFive。

NVIDIA 原话：

- 2024-06-26，对 The Next Platform：加入 UEC 是为了支持对客户有用的规范；未来也许会在 Spectrum-X 之外再提供一个 UEC 版本的以太。
- Huang，Q2 FY2026：Spectrum Ethernet is not off the shelf。
- Shainer，theCUBE，2026-07-16：我们在 UEC、在 ESUN，并且有贡献；同时必须非常快，因为每年都有新的一代。

## 7. 定制：固定的核，可谈判的壳

**固定**

- 硅片。没有按客户加功能的公开记录。A800、H800、H20、L20、L2 是按司法辖区做的减法。
- Scale-up 域。NVL72 是单位。客户能否决 NVIDIA 自己提的变体，公开记录里没有客户另设计一个 NVIDIA scale-up 域。
- 有合同杠杆时的东西向织物。云伙伴规范 NET-2：多节点服务必须是 InfiniBand 或 Spectrum-X，没有第三项。
- 信任面：BlueField 南北向、TPM 2.0、安全启动、签名固件、关闭 IPMI。

**可谈判**

- 机柜机械、液冷、供电。Azure 把 Boost、自研 HSM、DC-SCM 放进 NVL72。
- CPU 插座。MGX 是认证菜单；NVLink Fusion 接 Fujitsu、Qualcomm。
- 交换机整机。Meta Minipack3N 是 Spectrum-4 芯片、Meta 机箱、Accton 代工、FBOSS。
- 客户自己做得动的 scale-out。AWS EFA/SRD、Google Jupiter、Oracle Acceleron，NVIDIA 照样卖 GPU。
- 设施。DSX 把参考设计伸到电力互联。

Huang 在 Computex 2025 问答里的买法：NVLink 芯粒、NVLink 交换机和脊、Spectrum-X 交换机，以及配套软件。CPU 可以是 Fujitsu 或 Qualcomm。转录存于第三方站点。

### 客户矩阵

| 客户 | Scale-up | 网卡 | 交换 | 读法 |
| --- | --- | --- | --- | --- |
| OpenAI 租用 | NVLink | NVIDIA | 经微软 / OCI / CoreWeave | MRC 为微软、OpenAI、NVIDIA 共研 |
| OpenAI 自研 | Broadcom 以太机柜 | Broadcom | Broadcom | 2025-10-13，10 GW 自研 ASIC。不预期替换现有 NVIDIA 集群 |
| xAI | NVLink | BlueField-3 | SN5600 | 2024-10-28：10 万 Hopper，122 天，以太不是 IB。参考部署 |
| 微软 | NVLink | NVIDIA | 集群内 Quantum-X800；跨站 Spectrum-X | NDv6 超过 4600 颗 Blackwell Ultra。机柜内有 Azure 自研硅 |
| Oracle | NVLink | Acceleron，也有 ConnectX | IB + Spectrum-X | 交换机可以是 NVIDIA 的，网卡是 Oracle 的 |
| CoreWeave | NVLink | ConnectX-8 | Quantum-X800 | XGS 首批，使用 DSX Air |
| Meta | NVL72；MTIA 自有域 | 多厂商 | Spectrum-4 进自研机箱 | SIGCOMM 2024 已选 RoCE，早于 Spectrum-X。买的是芯片 |
| AWS | 2025-12 起 Trainium4 用 NVLink 6 + MGX | Nitro / EFA / SRD | 自研 | Scale-out 仍拒绝。一次喷最多 64 条路径 |
| Google | NVL72；TPU 用 ICI | ConnectX-7（A3 Ultra） | Jupiter + 光电路交换 | NSDI 2024：OCS 资本开支不到 TPUv4 pod 的 5%，功耗不到 3% |

**OpenAI 合同结构**

| 日期 | 内容 | 等级 |
| --- | --- | --- |
| 2025-09-22 | 意向书：至少 10 GW，有意随部署投资最多 1000 亿美元。不是合同 | 官方 |
| 2026-02-27 | 1100 亿美元融资中 NVIDIA 300 亿为股权，不绑定部署里程碑。Vera Rubin 上 3 GW 推理 + 2 GW 训练 | 官方 |
| 2026-08-17 | 8-K：俄亥俄约 4.25 GW 残值担保，支付上限 1050 亿美元。独家 AI 算力基础设施提供方。扩容期权同一天两份文件写成约 3.8 GW 和 3.75 IT-GW | 官方 |

**中国 SKU，按当时的约束项做减法**

| 部件 | 砍掉的 | 留下的 |
| --- | --- | --- |
| H800（2023-03） | NVLink 从 900 降到约 400 GB/s | 算力不动。Epoch：400 GB/s 仍够把通信藏在计算后面 |
| H20（2023-11） | BF16 砍到 148 TFLOPS | NVLink 保持 900 GB/s，显存 96 GB。规则改考算力之后，砍法反过来 |
| 许可 | 2025-08-11 白宫确认以 15% 中国芯片销售收入换许可 | 2026-05 约 10 家获准买 H200，当时零交付。2026-08 NVIDIA 确认首批运抵，不到当季数据中心收入的 1% |

### 三条结构变化（2025–2026）

1. 以太成为 NVIDIA 自己参考设计的默认参数面。InfiniBand 留在要点名 SHARP 的集群内。
2. OpenAI 关系从部署挂钩的意向，变成股权加租赁残值担保，换园区独家。
3. AWS 接受 NVLink 6 和 MGX 做 Trainium4。互连进入用来替代 NVIDIA GPU 的芯片旁边。Scale-out 仍是 AWS 的。

收入背景（财报电话）：Q4 FY2026 网络业务单季 110 亿美元，同比超过 3.5 倍，全年超过 310 亿美元。Q2 FY2027 网络环比 +18%，Spectrum-X 以太同比 2.6 倍。每吉瓦收入机会约 180 亿（Hopper）、250 亿（Blackwell）、400 亿（Vera Rubin，含 CPU、GPU、NVLink、IB 或以太、Groq）。Huang 的效率论证是利用率从约 65% 到 85–90%，相对一座 500 亿美元的工厂，网络等于免费。这是厂商论证。

## 8. 公开信息不足，本套材料不采用

- NVLink Fusion 每套部署必须含至少一件 NVIDIA 产品。只有媒体报道。
- Kyber NVL144 延期到 2028。单一分析师来源，NVIDIA 称路线图不变。
- Colossus 2 的织物代际。没有一手来源。
- B30A / B40 的规格和价格。来源互相矛盾。
- Trainium4 的 72 颗、每芯片 3.6 TB/s。不在 NVIDIA 或 AWS 材料里。
- 「Spectrum-X 是 AI 工厂的神经系统」。追不到演讲原文。
- Meta 交易 500 亿美元。单一分析师估计。Abilene 600 MW 取消。Oracle 公开否认。
- ConnectX-9 的 4×200G 与 2×800G。只采用 1.6 Tb/s。

## 9. 主要来源

- 论文：https://arxiv.org/abs/2605.21187
- Spectrum-X：https://www.nvidia.com/en-us/networking/spectrumx/
- Quantum-X800：https://www.nvidia.com/en-us/networking/products/infiniband/quantum-x800/
- Vera Rubin 技术博客：https://developer.nvidia.com/blog/inside-the-nvidia-rubin-platform-six-new-chips-one-ai-supercomputer/
- UEC 规范史：https://ultraethernet.org/specification-history/
- UEC 会员确认：https://www.nextplatform.com/connect/2024/06/26/what-if-omni-path-morphs-into-the-best-ultra-ethernet/1638832
- ESUN：https://www.opencompute.org/blog/the-ocp-esun-10-specification-has-been-released
- NVLink Fusion：https://nvidianews.nvidia.com/news/nvidia-nvlink-fusion-semi-custom-ai-infrastructure-partner-ecosystem
- xAI：https://nvidianews.nvidia.com/news/spectrum-x-ethernet-networking-xai-colossus
- OpenAI 意向书：https://openai.com/index/openai-nvidia-systems-partnership/
- OpenAI 2026-02 融资：https://openai.com/index/scaling-ai-for-everyone/
- NVIDIA 8-K 2026-08-17：https://www.sec.gov/Archives/edgar/data/1045810/000104581026000069/nvda-20260817.htm
- Meta SIGCOMM 2024：https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf
- AWS Trainium4：https://developer.nvidia.com/blog/aws-integrates-ai-infrastructure-with-nvidia-nvlink-fusion-for-trainium4-deployment/
- Google NSDI 2024：https://www.usenix.org/system/files/nsdi24spring_prepub_zu.pdf
- 云伙伴 NET-2：https://docs.nvidia.com/dsx/ncp/nvidia-requirements-for-ai-clouds/home
