# 字节 / 阿里 / 腾讯：近三代 AI 集群建设和规划

一页对照，只收录公开论文、官网、大会口径，不发明未披露数字。配图见 `tri-ai-cluster-gens.pptx`。

共同走向：场景从训练专网走到训推一体与 PD；组网从三层多轨走向少层 / 超节点；协议从 RoCE 集合通信扩到 Scale-up 与 Token 面。

## 字节跳动

路标：MegaScale（NSDI'24）→ AI Rack 2.0 / xLLM（2025）→ Rack 3.0 + EthLink + Volcano HPN 6.0（2026）

最新架构：Scale-up 用 EthLink（Load/Store + RDMA），铜互联双柜 576 XPU，NPO 8 计算柜 + 2 交换柜到 1024 XPU；Scale-out 是 HPN 6.0 三层 Clos，102.4T / 128×800G，单 POD 65k，集群可线性扩到百万级。

| 维度 | 一代 MegaScale | 二代 Rack 2.0 / xLLM | 三代 Rack 3.0 + HPN 6.0 |
| --- | --- | --- | --- |
| 场景 | 预训练万卡 | 训练 + xLLM PD 分离 | 训推一体 / 混速多代 |
| 组网 | 三层 Clos 1:1，8×200G 多轨，ToR 400G→2×200G AOC，64 主机/ToR 组 | 双柜 256 XPU 超节点 + RDMA scale-out | 576 铜 / NPO 1024；三层 Clos，POD 65k → 百万 |
| 协议 | RoCEv2，400G | RDMA + NVLink 域 | EthLink（Ld/St+RDMA）；200/400/800G RDMA 混速 |
| 关键技术 | Tomahawk4 25.6T；12288 卡 175B，MFU 55.2% | PD 吞吐最高 5×（DeepSeek R1，限定 SLO）；超节点 256 XPU / 240kW | 102.4T；SyncMesh 微秒切换；算子级 + 任务级 QoS；多平面 Fast Failover |

来源：MegaScale NSDI'24；火山引擎 HPN 6.0 / 102.4T 交换机文章；EthLink 白皮书发布；OCP 高晓军 AI Rack 2.0/3.0；veMLP xLLM PD 文档。

## 阿里云

路标：灵骏早期万卡 ETH RDMA（2022–23）→ HPN 7.0（SIGCOMM'24）→ HPN 8.0 + UPN512 + TPN（WAIC / 云栖）

最新架构：三层叠在一起——UPN512 单层光 CLOS 接 512 xPU（LPO/NPO）；HPN 8.0 多平面 CLOS 做训推一体 Scale-out，单集群最高 13 万卡异构混布、可扩百万卡、支持 PD；TPN 两层 Token 面，公开相对指标为接入带宽 +2.5×、规模 +10×、时延 −1/3。

| 维度 | 一代 灵骏早期 | 二代 HPN 7.0 | 三代 HPN8 + UPN + TPN |
| --- | --- | --- | --- |
| 场景 | 训练万卡 | 训练专网，存算分离 | 训推一体 / PD / Token 推理 |
| 组网 | ETH RDMA 双平面，前后端分离 | 双 ToR 双平面；1024 GPU 一跳；两层约 15k | 多平面 CLOS 13 万 → 百万；UPN 单层 512 xPU |
| 协议 | RoCE + HPCC | 400G RoCE，自研 51.2T | 400G/800G；IPv6 Native；TPN 两层 Token 面 |
| 关键技术 | 计算 / 存储流量分网 | AllReduce +59.3%，JCT +14.9%，排队 −91.8%；生产 8+ 月 | TPN +2.5× / +10× / −1/3；LPO/NPO 可用 +3×、成本 −30%；分钟自愈，平均可用 99.7% |

口径并列：发布会另有「单集群 10 万卡 / GPU 互联 6.4T / 存储 800G」；WAIC 吴结生为「单集群最高 13 万卡、可扩百万」。两者都是公开口径，不合成一个数。

来源：HPN 7.0 SIGCOMM'24；席永青 HPN+UPN；吴结生 WAIC 灵骏；云栖 TPN；UPN512 架构解读。

## 腾讯云

路标：星脉 1.0（2023）→ 星脉 2.0 / Astral（2024–25）→ 星脉 3.0（2026）

最新架构：星脉 3.0 用光 Shuffle 做扁平二级单轨，适配 MoE All-to-All；通信库按阶段拆核——训练 / Prefill 走高带宽 A2A，Decode 走低时延 A2A；TRMT 对 DeepEP 的公开数字是 RoCEv2 +100%、IB +30%。GitHub 写明 3.0 仍在研发，目标是 Scale-out + Scale-up 双引擎。

| 维度 | 一代 星脉 1.0 | 二代 星脉 2.0 / Astral | 三代 星脉 3.0 |
| --- | --- | --- | --- |
| 场景 | 混元训练 | 训练扩到十万卡 | MoE 训推一体；Prefill / Decode 分核 |
| 组网 | Fat-Tree 多轨，1.6T（8×2×100G）；典型 2K / 最大 32K | 同轨聚合、三层等带宽；主机 3.2T；Block 1024 / Pod 64k / 集群约 512k | 光 Shuffle，扁平二级单轨 |
| 协议 | ETH RDMA；TiTa；TCCL | TiTa 2.0 网卡主动拥塞控制；TCCL 2.0 NVLink+NET | TRMT + RoCEv2；Prefill 高带宽核 / Decode 低时延核 |
| 关键技术 | GPU 利用 +40%；通信时延 −40% | 训练 +20%；通信 +60%；Hunyuan-MoE 8K 效率损约 0.6% | RoCE A2A +100%；IB +30%；双引擎规划中 |

口径并列：星脉 1.0 按开发者文章 1.6T / 2K / 32K，不与 2023 HCC 新闻「3.2T / 10 万卡」混用。后者对应后续 HCC / 星脉 2.0 量级。

来源：腾讯云星脉 1.0 开发者文；星脉 2.0 发布；Astral SIGCOMM'25；《电信科学》星脉 3.0；Tencent/hpn；TRMT / DeepEP 报道。
