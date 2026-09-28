# NVIDIA 参数面：只谈 scale-out

研究截止 **2026-09-28**。幻灯片 `docs/nvidia-param-plane.pptx`，16 页。

参数面指东西向 RDMA 织物。NVLink、BlueField 南北向、上下文存储、出口管制 SKU、股权和园区担保不在这套材料里。

NVIDIA 自有方案是 Spectrum-X 以太和 Quantum InfiniBand。同一颗 ConnectX-8、同一代 Spectrum，也可以跑客户的传输。OpenAI 与微软的 MRC 是这一层的公开样本。

## 1. 自有方案

两条织物：

| | Spectrum-X 以太 | Quantum InfiniBand |
| --- | --- | --- |
| 交换 | Spectrum-4 到 Spectrum-6。Spectrum-6 为 102.4 Tb/s/芯片，200G SerDes。SN6600 为 128×800G，SN6800 为 512×800G、5U | Quantum-X800，144×800 Gb/s |
| 端点 | BF-3、CX-7/8/9，与交换机配对 | CX-8 / CX-9 |
| 均衡 | 交换机逐包自适应路由，网卡再选平面 | 自适应路由 |
| 可靠性 | 无损 PFC。论文称两年生产未见 PFC 风暴 | InfiniBand 链路层 |
| 网内归约 | 公开特性清单没有交换机侧 SHARP | SHARP v4 |
| 落点 | xAI：SN5600 + BF-3，10 万 Hopper。DSX 参考设计的默认织物 | Azure NDv6、CoreWeave GB300 |

ConnectX-9 只采用两边口径一致的每 GPU 1.6 Tb/s。端口拆分（4×200G 与 2×800G）互相算不平，不写。

### 拓扑与三条控制环

来源：Khashab 等，arXiv:2605.21187，2026-05-20。片子嵌了 Figure 2、4、5、8、13。

平面在交换机侧断开，网卡经无源光 shuffle box 接入全部平面。容量上界：两层 12.8 万端点，三层 1600 万。对应用只暴露一个 RoCE 设备。乱序在网卡里重排后直接落内存。

| 环 | 位置 | 时间 | 信号 |
| --- | --- | --- | --- |
| 自适应路由 | 交换机 fabric 口 | 数百纳秒 | 出口队列深度 |
| 平面负载均衡 | 网卡 | 逐包，故障在数个 RTT 内 | 每平面速率额度，再看本地队列 |
| 拥塞控制 | 发送端 | RTT | RTT 探针。ECN 只在均衡容量用尽后标记 |

分开的原因：微突发会抬高 RTT，拥塞控制若把它读成 incast，会在所有平面上一起限速。平面内不对称很小，平面之间不对称很大。

四平面断一平面，硬件在 3 毫秒内回到 75% 线速。软件均衡要 1.08 秒。永久少 10% 链路，带宽大约少 11%（378 到 335 Gb/s），p99 从 14.97 到 15.96 微秒。

对照 DCQCN+ECMP 的实测：p01 到线速的 98%；75% 负载下 p99 为 8–9 微秒；有背景流量时 DeepSeek 代理步时停在 668 ms，以太从 735 ms 涨到 1.18 秒。部署陈述是数十个客户集群、合计超过 100 万 GPU，未经第三方审计。

SHARP 在 Quantum 上，不在以太交换机上。Spectrum-XGS 是跨园区延伸，10 公里大消息 1.9 倍是厂商内部实验，具名客户是 CoreWeave。共封装光是 Spectrum-6 的光形态，不改变三条控制环。

## 2. 标准

| 层 | 组织 | NVIDIA |
| --- | --- | --- |
| 物理层 | IEEE 802.3dj、OIF | 深。802.3dj 有点名工程师。Karl Bois 任 OIF 技术委员会副主席 |
| Scale-out 传输 | UEC | 2024-09 一般会员。无指导席。无符合性声明。1.1 截至 2026-09-28 未发布 |
| RoCE | IBTA | 继续改自己参与的传输。MRC 延伸的是这条血统 |
| 织物需求 | OCP ESUN | 12 家创始之一，名单含 OpenAI。1.0 是需求基线，大多引用 UEC 1.0 |
| 端点事务 | SUE / SUE-Lite | 作者是 Broadcom。SUE-Lite 砍掉端到端可靠和拥塞控制，只留逐跳重传 |
| 另一套 scale-up | UALink | 名册上没有 NVIDIA。和参数面没有直接接口 |

UEC 1.0 与 Spectrum-X 的功能重叠在多路径、拥塞、遥测、链路可靠和网内集合。实现位置相反：UEC 放进标准传输，Spectrum-X 放进交换机与 SuperNIC 的配对。ConnectX-8 手册列的是 IEEE 802.3 和 IBTA 1.7。Thor Ultra 宣称符合 UEC。

判断：物理层做成标准，传输层保留一套自有方案，同时把开放传输做进同一颗网卡。年度换代被用来解释为什么不等共识流程。

## 3. 定制：MRC

来源：OpenAI、Microsoft、NVIDIA、AMD、Broadcom，*Resilient AI Supercomputer Networking using MRC and SRv6*。传输规范论文 arXiv:2606.18170。规范在 OCP。NVIDIA 通讯作者 Sayantan Sur。片子嵌了该文 Figure 1。

MRC 做三件事：端点按熵值逐包喷洒，多平面把十万以上 GPU 收进两层，静态 SRv6 让端点自己绕故障。动态路由关掉，因为两套自适应会互相打扰。PFC 关掉，以太工作在有损模式。SACK 做选择性重传，可选包修剪。

| 集群 | 网卡 | 交换 | 拓扑 |
| --- | --- | --- | --- |
| A | GB200 + CX-8，800 Gb/s | Spectrum-4 与 Tomahawk 5 混布 | 两层，4×200G |
| B | GB200 + CX-8 | 论文写 Spectrum-5 | 两层，8×100G |
| C | MI355 + Pollara | Tomahawk 5 | 两层，4×100G |
| D | RTX 6000 + Thor Ultra | Tomahawk 5 | 两层，400G 单平面 |

50K GPU 作业里，一个光模块连闪四条链路，吞吐大约掉 25% 约一分钟，然后回到全速，作业没有崩溃。75K GPU 启动时不预填坏路径，第一分钟每个 QP 丢包少于 5 个。

和 Spectrum-X 的分歧：均衡在端点还是在交换机，有损还是无损，静态源路由还是 BGP 权重。两边都用多平面。

## 4. 其他客户改了哪一层

| 客户 | scale-out 上留下的 | 换掉的 |
| --- | --- | --- |
| xAI | 整套 Spectrum-X | 没有。参考部署 |
| CoreWeave、Azure NDv6 | Quantum-X800 整套 IB | 没有。Azure 的 MRC 在另一张网上 |
| Meta | Spectrum-4 芯片 | 机箱、FBOSS、拥塞策略。RoCE 的决定早于 Spectrum-X |
| Oracle | 交换可以是 NVIDIA | Acceleron 网卡，自己做多平面 |
| AWS | 不买 | SRD / EFA，一次最多 64 条路径 |
| Google GPU 虚机 | ConnectX-7 | 交换留在 Jupiter |

三档：整套拿走；买芯片或网卡、控制面留下；在 NVIDIA 硅片上跑客户的开放传输。NET-2（必须是 InfiniBand 或 Spectrum-X）是托管 DGX Cloud 的合同条款，不是硅片的能力上限。

## 5. 不采用

出口管制 SKU、股权与园区担保、NVLink Fusion 投资金额、Kyber 延期、Colossus 2 织物代际、ConnectX-9 互相矛盾的端口拆分、找不到原文的营销引语。
