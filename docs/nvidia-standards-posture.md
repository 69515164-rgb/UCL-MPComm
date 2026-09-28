# NVIDIA's Posture and Actions in Networking Standards Bodies

Research cut-off: **28 September 2026**. Compiled from public web sources; every claim carries a source URL, a date, and a confidence marker.

## Confidence key

| Marker | Meaning |
| --- | --- |
| `[FACT]` | Verifiable from a primary source (standards body, SEC/IR filing, official spec, meeting minutes, attendance record) |
| `[VENDOR]` | Vendor/consortium's own claim about its own product or position — true as a *statement*, not independently verified as a *fact* |
| `[PRESS]` | Reported by trade press or analysts, sourced but not primary |
| `[SPEC]` | Speculation, forward-looking projection, or analyst inference |
| `[ABSENT]` | Searched and found no evidence; a negative that cannot be proven absolutely |

Section 8 additionally uses `[UNVERIFIED]`, `[UNVERIFIED — PRESS ONLY]`, `[UNVERIFIED NEGATIVE]` and `[CONFLICTING PRIMARY SOURCES]` to grade the things I could not stand behind.

---

## 1. Ultra Ethernet Consortium (UEC)

### 1.1 Founding

| Item | Detail | Confidence |
| --- | --- | --- |
| Announced | 19 July 2023, as a Joint Development Foundation project hosted by the Linux Foundation | `[FACT]` |
| Founding members (9) | AMD, Arista, Broadcom, Cisco, Eviden (an Atos business), HPE, Intel, Meta, Microsoft | `[FACT]` |
| First Steering Committee (10) | The nine founders **plus Oracle** | `[FACT]` |
| New members opened | Q4 2023 | `[FACT]` |

Sources: [Linux Foundation press release, 19 Jul 2023](https://www.linuxfoundation.org/press/announcing-ultra-ethernet-consortium-uec); [jointdevelopment.org, 19 Jul 2023](https://jointdevelopment.org/announcement/2023/07/19/leading-cloud-service-semiconductor-and-system-providers-unite-to-form-ultra-ethernet-consortium/); [UEC, "Welcomes 27 New Members" (Nov 2023), which names the Steering Committee including Oracle](https://ultraethernet.org/ultra-ethernet-consortium-welcomes-27-new-members/).

Growth markers: 10 steering members Oct 2023 → 45 new members by ~Mar 2024 (715 experts across 8 working groups) → 97 total by Aug/Sep 2024 → "more than 100 companies and over 1,500 participants by end of 2024." Sources: [UEC growth post](https://ultraethernet.org/ultra-ethernet-consortium-experiences-exponential-growth-in-support-of-ethernet-for-high-performance-ai-and-hpc-networking/) `[FACT]`; [HPCwire, 9 Sep 2025](https://www.hpcwire.com/2025/09/09/ultra-ethernet-has-arrived-one-network-to-rule-them-all/) `[PRESS]`.

### 1.2 NVIDIA's membership: when, and at what tier

**NVIDIA is a UEC member but not a Steering member.** The public record has a wrinkle worth flagging in the deck: NVIDIA confirmed membership to *The Next Platform* in **June 2024**, roughly two months before UEC publicly listed it.

- **26 June 2024** — *The Next Platform* updates an article with an on-record NVIDIA statement: *"Nvidia is a member of the UEC because our strategy is to support networking specifications that can be beneficial to our customers. We may want to offer a UEC version of Ethernet in the future, alongside Spectrum-X and potentially other specifications in the future."* [Source](https://www.nextplatform.com/connect/2024/06/26/what-if-omni-path-morphs-into-the-best-ultra-ethernet/1638832) `[VENDOR]`
- **~29 August 2024** — UEC newsletter first flags NVIDIA's membership. `[PRESS]`
- **UEC post "Welcomes 40 New Industry Leaders"** (page last updated 9 Sep 2024) lists **NVIDIA** among 40 additions since March 2024, alongside Astera Labs, Cadence, Micron, Qualcomm, Rivos, Lenovo, LLNL, LANL, Sandia and others; total 97. [Source](https://ultraethernet.org/ultra-ethernet-consortium-welcomes-40-new-industry-leaders/) `[FACT]`
- **~10 September 2024** — Futuriom independently confirms with NVIDIA, and notes *"NVIDIA's logo now appears among those of general members on the group's homepage."* [Source](https://www.futuriom.com/articles/news/nvidia-has-joined-the-ultra-ethernet-consortium/2024/09) `[PRESS]`

**Tier:** UEC's charter recognises three classes — Steering, General, Contributor — with General and Contributor marketed at US$20,000 and US$5,000 annual project fees respectively, on top of Linux Foundation membership. NVIDIA appears as a **General member** (full technical-group access, no Steering Committee seat). `[PRESS]` for the tier (Futuriom's read of the member logos); `[FACT]` for the *absence* of NVIDIA from every published Steering Committee roster (2023 through Cisco's 2026 blog). Charter/fee detail: [btw.media analysis](https://btw.media/en/ultra-ethernet-consortium-rebuilding-ethernet-for-ai-at-scale-3) `[PRESS]`.

**Contributions and leadership roles:** **`[ABSENT]`** — I found no UEC working-group chair, editor, or named technical contribution attributable to NVIDIA. UEC does not publish working-group rosters. The only NVIDIA-sourced characterisation of its contribution level is Gilad Shainer's generic *"we're part of UEC, we're part of ESUN, we're part of many consortiums and we actually contribute to that"* (see §7). Contrast this with NVIDIA's *named, documented* leadership at OIF and IEEE 802.3 (§5) — the asymmetry is itself a finding.

### 1.3 Specification releases

| Version | Date | Content | Confidence |
| --- | --- | --- | --- |
| 1.0 | **11 June 2025** | Initial public release; 562–573 pages | `[FACT]` |
| 1.0.1 | 5 September 2025 | Editorial clarifications; correction to the RCCC source algorithm | `[FACT]` |
| 1.0.2 | 21 **or** 28 January 2026 | Correction to CMS congestion-control algorithms + editorial. **Official UEC documents disagree on the date** — the spec-history page says 28 Jan, the 1.0.3 release notes say 21 Jan | `[FACT]` (including the discrepancy) |
| 1.0.3 | **16 July 2026** | **Current published version.** Adds 200 Gb/s-per-lane signalling, a new Negotiation CP type; corrects UE PHY CtlOS corruption protection, retransmission handling when `pds.flags.syn=1` on PDC close, `MP_Range` < 128, and CBFC/LLR race conditions | `[FACT]` |
| **1.1** | **Not published as of 28 Sep 2026** | Planned; see below | `[FACT]` (non-publication verified against UEC's own spec-history page) |

Sources: [UEC Specification History](https://ultraethernet.org/specification-history/) (page last updated 5 Aug 2026); [1.0.2 release notes PDF](https://ultraethernet.org/wp-content/uploads/sites/20/2026/01/UE-Specification-1.0.2-release-notes.pdf); [1.0.3 release notes PDF](https://ultraethernet.org/wp-content/uploads/sites/20/2026/07/UE-Specification-1.0.3-release-notes-.pdf); [Spec v1.0.3 PDF](https://ultraethernet.org/wp-content/uploads/sites/20/2026/08/UE-Specification-1.0.3.pdf).

**Slippage is a deck-worthy point.** UEC's own chair wrote in the 2025 year-in-review that members were advancing PCM, CSIG, small-message performance, scale-up transport and INC, and the Aug 2025 blog said *"we hope to wrap up many of these technologies in an updated specification release the first half of next year"* ([source](https://ultraethernet.org/accelerating-ai-with-open-standards-uecs-expanding-vision/)). The UEC→IEEE 802.1 liaison of Nov 2025 stated CSIG *"is planned for publication as part of the UE 1.1 specification in Q1, 2026"* ([liaison PDF](https://www.ieee802.org/1/files/public/docs2025/liaison-UEC-CongestionSignalingCSIG-1125.pdf)). As of late September 2026, 1.1 has not shipped — roughly three quarters late against the CSIG target. `[FACT]`

### 1.4 What UEC 1.0 actually standardizes

Five-layer stack. Physical and network layers are deliberately *unchanged* (standard Ethernet PHY; standard IPv4/IPv6) so UEC runs over existing fabrics. The novelty is concentrated in transport.

- **Ultra Ethernet Transport (UET)** — a new transport with four sublayers: Semantics (SES), Packet Delivery (PDS), Congestion Management (CMS), Transport Security (TSS). Runs over IP/UDP or natively over IP. `[FACT]`
- **Packet spray (per-packet multipathing)** — every flow may simultaneously use all paths; path choice is coordinated between endpoints and switches under real-time congestion management rather than an ECMP hash. Receiver handles out-of-order natively, no reordering overhead. `[FACT]`
- **Ephemeral connections** — Packet Delivery Contexts established with **no handshake**; state created during communication and discarded at transaction end; a pool of connection resources shared across all active peers. Removes connection-setup RTT and bounds per-peer state. `[FACT]`
- **Selective retransmission** — per-packet loss recovery instead of go-back-N. `[FACT]`
- **Packet trimming** — optional switch feature letting the destination detect in-network drops. `[FACT]`
- **Link Level Retry (LLR)** — optional link-layer hop-by-hop retransmit, negotiated via LLDP extensions, replay buffer at the sender, go-back-N (sufficient at link RTT). Targets marginal links / transient BER, protecting tail latency. `[FACT]`
- **Credit-Based Flow Control (CBFC)** — optional link-layer extension alongside LLR. `[FACT]`
- **Congestion control** — sender-based (NSCC) and receiver-based (RCCC) algorithms, plus end-to-end telemetry. `[FACT]`
- **In-Network Collectives (INC)** — mechanisms to offload AllReduce-class operations into switches; **optional to implement**. UEC's own framing: *"When UEC v1.0 is available, it will be the first time such a technology is offered and standardized over Ethernet links!"* `[FACT]` / the superlative is `[VENDOR]`
- **Profiles** — AI Base, AI Full, HPC. `[FACT]`
- **No fragmentation**; all but the last packet of a message carry a full MTU payload. `[FACT]`

Sources: [UEC spec update blog](https://ultraethernet.org/ultra-ethernet-specification-update/); [UEC "progresses towards v1.0"](https://ultraethernet.org/uec-progresses-towards-v1-0-set-of-specifications/); ["Ultra Ethernet's Design Principles and Architectural Innovations," arXiv:2508.08906](https://arxiv.org/html/2508.08906); [Arista, "Demystifying Ultra Ethernet"](https://blogs.arista.com/blog/demystifying-ultra-ethernet).

### 1.5 What UEC 1.1 is planned to add

From Paul Congdon's ITU-T presentation, 11 July 2026 ([PDF](https://www.itu.int/en/ITU-T/Workshops-and-Seminars/2026/0711/Documents/6%20-%20Paul%20Congdon.pdf)) `[FACT]` (as a statement of plan):

| UET v1.0 | UET v1.1 adds |
| --- | --- |
| Scale-out focus | **Scale-up optimization** |
| Ethernet/IP/UDP headers | **Unified Forwarding Header (UFH)**, coexisting with traditional protocols on the same wire |
| ROD / RUD / RUDI / UUD delivery modes | **RODL** (Reliable Ordered Delivery for Local networks) — bidirectional PDCs, reduced state, ACKs piggybacked on reverse-direction requests, expected PSN folded into the CRC |
| 256k Ethernet ports | 32–4K ports |
| < 10 µs one-way latency | **< 1 µs** one-way latency |
| MPI / AI message efficiency | **Load/Store/Atomic** transaction efficiency |
| AI Base, AI Full, HPC profiles | **AI Local** profile |

Also in the 1.1 work item list: verbs mapping, In-Network Collectives, **Congestion Signaling (CSIG)**, inter-packet-gap idle reduction, LLDP negotiation enhancements, and **Programmable Congestion Management (PCM)** — a standard language so any congestion-control algorithm runs on any PCM-capable NIC.

**CSIG detail** `[FACT]`: a lightweight L2 tag, 4-byte "compact" and 8-byte "wide" variants, distinct EtherTypes, compare-and-replace semantics so the tag stays fixed-size across the path; switches strip the tag at domain boundaries; LLDP TLVs negotiate capability. UEC has asked IEEE 802.1 for EtherType allocation. Draft published at `github.com/opencomputeproject/OCP-...-UEC-CSIG`.

### 1.6 Overlap / competition with NVIDIA Spectrum-X proprietary mechanisms

This is the analytically important table. Confidence on the *mapping* is `[SPEC]` (my inference); confidence on each side's *existence* is `[FACT]`/`[VENDOR]` as marked.

| Function | UEC standard mechanism | NVIDIA Spectrum-X equivalent | Assessment |
| --- | --- | --- | --- |
| Multipath load balancing | Packet spray, per-packet, coordinated across endpoints+switches `[FACT]` | **Adaptive routing**: switch performs fine-grained load balancing, SuperNIC reorders out-of-order packets into destination memory `[VENDOR]` | Direct functional overlap. Different division of labour: UEC puts reordering in a standard transport; NVIDIA puts it in a proprietary switch↔NIC pair |
| Congestion control | NSCC/RCCC in 1.0; **PCM** (programmable, portable across any UEC NIC) planned for 1.1 `[FACT]` | **Programmable congestion control** on the SuperNIC, using in-band telemetry + deep-learning models for data metering `[VENDOR]` | Head-on. PCM's explicit pitch — *"usable on any NIC that supports UE PCM"* — is an attack on exactly the NIC-specific advantage Spectrum-X sells |
| Telemetry | **CSIG** 4B/8B in-band tags, compare-and-replace, reflected by the receiving NIC `[FACT]` | **End-to-end high-frequency telemetry**; RoCE congestion control collects in-band network telemetry `[VENDOR]` | Head-on, and CSIG would standardize the wire format NVIDIA currently keeps internal |
| Link-level reliability | **LLR + CBFC**, LLDP-negotiated `[FACT]` | Spectrum-X "inherently eliminates cascading performance issues from a lost link, limiting bandwidth loss to only that single link" `[VENDOR]`; link-level retry is long-standing InfiniBand practice NVIDIA carried into Ethernet | Overlap; NVIDIA has shipped equivalents for years without a public interop spec |
| In-network collectives | **INC** (optional) in 1.0; expanded in 1.1 `[FACT]` | **SHARP** (Scalable Hierarchical Aggregation and Reduction Protocol) — NVIDIA-proprietary, in NVLink Switch and InfiniBand/Spectrum switches `[VENDOR]` | Direct competition for NVIDIA's single most defensible in-network feature |
| Transport | UET, new RDMA-native transport `[FACT]` | **RoCEv2 + NVIDIA RoCE extensions** `[VENDOR]` | UEC bypasses the IBTA/RoCE lineage NVIDIA co-owns |
| Scale-up transport | UET v1.1 RODL/UFH, < 1 µs, 32–4K ports `[FACT]` as plan | **NVLink** (see §4) | This is the existential one: UEC 1.1 + ESUN + SUE-T together are an Ethernet assault on NVLink's domain |

Spectrum-X mechanism list from the [NVIDIA Spectrum-X datasheet](https://resources.nvidia.com/en-us-networking-ai/networking-ethernet-1): 200G SerDes, adaptive routing, programmable congestion control, performance isolation, hardware-accelerated multiplane architecture, end-to-end high-frequency telemetry, scale-across precision latency management, enhanced AI fabric security, co-packaged optics. `[VENDOR]`

Note the rhetorical move NVIDIA makes: Shainer argues Spectrum-X is *not* proprietary because it uses *"standard Ethernet protocols… you can connect Spectrum-X Switch to any other Ethernet switch and it's going to work."* ([theCUBE clip, 16 Jul 2026](https://video.cube365.net/c/AS6L_wqQ2AlBJcpBn4jp56avIgiOzHo6)) `[VENDOR]`. That is true at the *interoperability* layer and beside the point at the *performance* layer: the 1.6× uplift requires an NVIDIA switch **and** an NVIDIA SuperNIC. Jensen Huang says as much: *"Spectrum Ethernet is not off the shelf."*

### 1.7 Does NVIDIA ship UEC-compliant products?

**No public UEC-compliance claim by NVIDIA exists as of 28 Sep 2026.** `[ABSENT]`

- The [ConnectX-8 SuperNIC user manual](https://networking-docs.nvidia.com/connectx8hw/introduction) enumerates conformance to a long list of IEEE 802.3 clauses and to InfiniBand Architecture Specification v1.7. **UEC is not listed.** `[FACT]`
- The [Spectrum-X platform page](https://www.nvidia.com/en-us/networking/spectrumx/) and [Spectrum-X datasheet](https://resources.nvidia.com/en-us-networking-ai/networking-ethernet-1) list proprietary innovations, OCP SAI and SONiC support — **no UEC.** `[FACT]`
- The [Vera Rubin launch PR (GTC, March 2026)](https://nvidianews.nvidia.com/news/rubin-platform-ai-supercomputer) introduces ConnectX-9 SuperNIC (1.6 Tb/s per GPU, 4×200G SerDes) and Spectrum-6 Ethernet — **no UEC mention.** `[FACT]`
- Contrast: Broadcom's **Thor Ultra** 800G AI NIC (14 Oct 2025) is marketed as *"fully feature compliant with UEC specification"* by Ram Velaga ([GlobeNewswire](https://www.globenewswire.com/news-release/2025/10/14/3166262/19933/en/Broadcom-Introduces-Industry-s-First-800G-AI-Ethernet-NIC.html)) `[VENDOR]`, and Tomahawk Ultra is described as *"compliant with the UEC standard."* `[VENDOR]`

So: NVIDIA's only public commitment is Deierling's 2024 conditional — *"we will support new standards that may emerge"* — plus the June 2024 *"we may want to offer a UEC version of Ethernet in the future."* Both are options, not roadmap items. `[VENDOR]`

### 1.8 Plugfests and interop

- **First public UEC interop demonstration: OFC 2026, announced 16 March 2026** — Keysight + **Broadcom**, UEC **LLR and CBFC at full 800GE line rate**, Keysight Interconnect and Network Performance Tester against Broadcom Tomahawk Ultra. Keysight described as "a key contributor within the UEC and… active in the emerging ESUN ecosystem." [BusinessWire](https://www.businesswire.com/news/home/20260316488886/en/Keysight-Advances-AI-Networking-with-Ultra-Ethernet-LLR-and-CBFC-Interoperability-Demonstration-at-OFC-2026) `[VENDOR]` for the "industry's first" claim, `[FACT]` that the demo happened. **NVIDIA did not participate.** `[ABSENT]`
- UEC exhibited at **AI Infra Summit 2026, 15–17 Sep 2026**, Santa Clara. [UEC events](https://ultraethernet.org/events/) `[FACT]`
- **No formal UEC plugfest** (e.g. at UNH-IOL) found. UNH-IOL's only listed 2026 plugfest is Broadband Forum PON, 5–9 Oct 2026. `[ABSENT]`
- Broadcom states UEC "is also putting a concerted effort into compliance and interoperability verification." [Broadcom topic page](https://www.broadcom.com/topics/what-are-the-ethernet-standards-for-ai-infrastructure) `[VENDOR]`

---

## 2. Scale-Up Ethernet (SUE), SUE-Lite, SUE-T and OCP ESUN

### 2.1 SUE — authorship and contribution

- **Author: Broadcom.** Ram Velaga (SVP/GM Core Switching) announced on **29 April 2025**: *"Broadcom released the specification for Scale Up Ethernet. We contributed this specification to Open Compute Project (OCP)."* [LinkedIn](https://www.linkedin.com/posts/ram-velaga_scale-up-ethernet-sue-broadcom-released-activity-7323101532076310532-RieN) `[VENDOR]`. Broadcom's own topic page dates it "April 2025 initial SUE contribution." `[VENDOR]`
- The OCP-hosted spec's revision history shows Broadcom as sole author across **0.5.0 (April 2025, initial release) → 0.5.3 (16 July 2025) → 0.5.5 (Steering Committee review) → 0.5.7 (21 Aug 2025, adds AMBA AXI) → 1.0**. [OCP SUE spec](https://www.opencompute.org/documents/ocp-sue-spec-final-pdf-1) `[FACT]`

**What SUE specifies** `[FACT]`, from the [Broadcom Scale-Up Ethernet Framework Specification](https://docs.broadcom.com/doc/scale-up-ethernet-framework): an XPU-side Ethernet interface for scale-up. Transaction types Write (full/partial, posted/non-posted), Read, Message, Barrier; 256B transactions; transaction packing; DMA-ready block-write interface; AXI4 **and** signal-based core-side interfaces; LLR, CBFC and **AFH** (Adaptive/Accelerator Forwarding Header) headers; a **Reliable Transport Layer** for end-to-end reliability; **fixed-window congestion control**; a partition feature. With Tomahawk Ultra, Broadcom claims sub-400 ns XPU-to-XPU latency including switch transit. `[VENDOR]`

### 2.2 SUE-Lite

Introduced **15 July 2025** with the Tomahawk Ultra launch. [Broadcom/Nasdaq PR](https://www.nasdaq.com/press-release/broadcom-ships-tomahawk-ultra-reimagining-ethernet-switch-hpc-and-ai-scale-2025-07-15) `[VENDOR]`.

A **profile of SUE that cuts SUE IP area by up to 50%** for power/area-sensitive accelerators. Exact deltas, from the spec `[FACT]`:

| Attribute | SUE | SUE-Lite |
| --- | --- | --- |
| Transaction types | Write/Read/Message/Barrier | same |
| Transaction size | 256B | same |
| Transaction packing | Yes | Yes (up to 1 KB packed PDU, same {dest, VC}) |
| LLR, CBFC, AFH headers | Yes | Yes |
| Core-side interface | AXI4 **and** signal-based | **signal-based only** |
| End-to-end reliability | Yes (Reliable Transport Layer) | **No — hop-by-hop LLR only** |
| Congestion control | Yes (fixed window) | **No** |
| Partition feature | Yes | **No** (use address separation) |

Encapsulation: SUE-Lite drops the transport layer entirely; destination, source XPU address and VC all fit in the **6-byte AFH Gen 2 header**, and the payload R-CRC is removed. Ethernet MAC/Link/PHY size unchanged.

**Strategic read** `[SPEC]`: SUE-Lite is the anti-NVLink cost argument made concrete. It says a scale-up Ethernet port can be nearly as cheap in silicon as a bespoke link, because within a rack you can lean on hop-by-hop LLR and skip end-to-end reliability and congestion control altogether.

### 2.3 OCP ESUN (Ethernet for Scale-Up Networking)

| Item | Detail | Confidence |
| --- | --- | --- |
| Launched | **13 October 2025**, at OCP Global Summit 2025 | `[FACT]` |
| 12 founding participants | **AMD, Arista, Arm, Broadcom, Cisco, HPE Networking, Marvell, Meta, Microsoft, NVIDIA, OpenAI, Oracle** | `[FACT]` |
| Scope | The **network fabric** (L2/L3) side of scale-up: framing, header efficiency, lossless networking, error recovery | `[FACT]` |
| Leads | Manoj Wadekar (Meta), Pratik Marolia (Microsoft); organised under OCP's Networking Project; bi-weekly meetings | `[FACT]` |
| ESUN 1.0 | *"OCP ESUN — Network Operator Requirements Base Specification 1.0."* Rev 0.2 to community 10 Dec 2025 → Rev 1.0-Final 15 Jan 2026 → Networking Project 9 Feb 2026 → **Steering Committee 12 Feb 2026 → approved/published** | `[FACT]` |
| Scale | 12 founders → **175+ participating companies** (237 on the bi-weekly list per the IEEE liaison deck) | `[FACT]` |
| Relationship to UEC | ESUN found most of its requirements met by UEC 1.0 and **includes the UEC specs by reference**; where UEC fell short (compressed headers) ESUN wrote its own **ESUN Header**. Future UEC revisions will be considered for inclusion | `[VENDOR]` (Broadcom's characterisation) |

Sources: [OCP blog, "The OCP ESUN 1.0 Specification has been released!"](https://www.opencompute.org/blog/the-ocp-esun-10-specification-has-been-released); [OCP ESUN wiki](https://www.opencompute.org/wiki/Networking/ESUN); [ESUN 1.0 overview to IEEE workshop, April 2026](https://www.ieee802.org/1/files/public/docs2026/liaision-ESUN-OverviewIEEEworkshop-0426.pdf); [Broadcom ESUN announcement](https://www.broadcom.com/company/news/articles/networking/introducing-ethernet-scale-up-networking-advancing-ethernet-for-scale-up-ai-infrastructure); [Meta Engineering, OCP Summit 2025, 13 Oct 2025](https://engineering.fb.com/2025/10/13/data-infrastructure/ocp-summit-2025-the-open-future-of-networking-hardware-for-ai/).

### 2.4 Is NVIDIA in ESUN and SUE-T? Yes — and this matters

**NVIDIA is a named founding participant in ESUN.** Both Broadcom's launch article and Meta's engineering blog list NVIDIA in the initial 12. `[FACT]`

**NVIDIA is also listed as a SUE-T supporter.** Broadcom: *"SUE-T is now supported by a broad group of industry leaders within the OCP Networking Project, including AMD, Arista, Broadcom, Intel, Microsoft, Meta, Nvidia and others."* `[VENDOR]`

**Shainer confirms it from NVIDIA's side**: *"We are part of UEC, we're part of ESUN, we're part of many consortiums and we actually contribute to that."* ([theCUBE, 16 Jul 2026](https://video.cube365.net/c/AS6L_wqQ2AlBJcpBn4jp56avIgiOzHo6)) `[VENDOR]`

This is the single most counter-intuitive fact in the research: **NVIDIA sits inside the OCP workstream whose explicit purpose is to make Ethernet a viable replacement for NVLink.** Read charitably it is intelligence-gathering and ensuring its own Ethernet silicon stays sellable into scale-up sockets it does not own. Read cynically it is a slow-walk seat. Either way it fits the pattern in §7: NVIDIA joins where the standard threatens a *market* and abstains where the standard threatens the *moat* (UALink, §3). `[SPEC]`

### 2.5 SUE-T and how the pieces fit

**SUE-T (Scale-Up Ethernet Transport)** is the renamed, rescoped successor to SUE. Broadcom's original SUE covered both Transport **and** Network Fabric layers, overlapping ESUN; SUE was deprecated and the transport portion renamed SUE-T, focused on **endpoint (L4) functionality**. Workstream leads: Tom Emmons (Arista), Lowell Lamb (Broadcom). Reference documents include "SUE Specification v1.0" and "UEC ULN draft v1.1." [OCP SUE-T wiki](https://www.opencompute.org/wiki/Networking/SUE-T) `[FACT]`

Layer map for the deck `[SPEC]` (synthesis, grounded in the above):

```
Scale-up over Ethernet, as of Sept 2026
┌─────────────────────────────────────────────────────────┐
│ Endpoint / transport (L4)  → OCP SUE-T   (+ UEC UET 1.1) │
│ Network fabric (L2/L3)     → OCP ESUN 1.0 (refs UEC 1.0) │
│ PHY                        → IEEE 802.3 / OIF CEI        │
└─────────────────────────────────────────────────────────┘
Alternative full stack: UALink 1.0/2.0 (own protocol, Ethernet PHY)
Incumbent:              NVIDIA NVLink 6 (closed, licensed via Fusion)
```

The Ethernet Alliance 2026 roadmap states the relationship plainly: *"ESUN is developing specifications for L2/L3 framing, header efficiency, lossless networking, and error recovery, while SUE-T is focusing on transport solutions,"* and notes **UALink 1.0 "adopts the Ethernet PHY."** [Ethernet Alliance roadmap, Dec 2025](https://ethernetalliance.org/wp-content/uploads/2025/12/EthernetRoadmap-2026-Side2-Press-3.pdf) `[FACT]`

---

## 3. UALink

### 3.1 Formation and membership

| Item | Detail | Confidence |
| --- | --- | --- |
| Promoter Group announced | **30 May 2024** — AMD, Broadcom, Cisco, Google, HPE, Intel, Meta, Microsoft | `[FACT]` |
| Consortium incorporated | **October 2024** | `[FACT]` |
| Board / Promoter members | Alibaba, AMD, Apple, Astera Labs, AWS, Cisco, Google, HPE, Intel, Meta, Microsoft, Synopsys | `[FACT]` |
| Membership at 1.0 | 85+ companies; 70+ Contributor/Adopter members | `[FACT]` |
| **NVIDIA** | **Not a member. Not invited to the founding group.** | `[FACT]` (absence from every published roster) + `[PRESS]` (that it was not invited) |

Sources: [TechCrunch, 30 May 2024](https://techcrunch.com/2024/05/30/tech-giants-form-new-group-in-effort-to-wean-off-of-nvidia-hardware/); [DailyAI, May 2024](https://dailyai.com/2024/05/big-tech-forms-ai-connectivity-standard-excludes-nvidia/); [Tom's Hardware on incorporation](https://www.tomshardware.com/tech-industry/ualink-consortium-officially-incorporates-nvlink-competitor-headed-by-amd-and-intel-opens-doors-to-contributor-members); [UALink 1.0 white paper](https://ualinkconsortium.org/wp-content/uploads/2025/04/UALink-1.0-White_Paper_FINAL_UPDATED.pdf).

TechCrunch, 30 May 2024: *"Glaringly absent from the list of the group's members is Nvidia… Nvidia declined to comment for this story."* `[PRESS]`

### 3.2 Specification versions

| Spec | Date | Content | Confidence |
| --- | --- | --- | --- |
| **UALink 200G 1.0** | **8 April 2025** | 200G per lane, up to **1,024 accelerators per pod**; PHY, protocol interoperability, baseline reliability, link management. Publicly downloadable under an evaluation-copy EULA | `[FACT]` |
| UALink 128G DL/PL 1.0 | — | Lower-speed data link / physical layer variant | `[FACT]` |
| **UALink Common 2.0** | **7 April 2026** | **In-Network Compute** for UALink | `[FACT]` |
| UALink 200G DL/PL 2.0 | 7 April 2026 | DL/PL split out of Common so PHY/speed can move independently | `[FACT]` |
| UALink Manageability 1.0 | 7 April 2026 | Centralized control/management planes via gNMI, YANG, SAI, Redfish | `[FACT]` |
| UALink Chiplet 1.0 | 7 April 2026 | Interfaces, form factors, flow control for integrating UALink into chiplet SoCs | `[FACT]` |
| **UALink 3.0** | Targeted **2027** | Next step-change: extended reach across racks, larger scale | `[FACT]` as roadmap |

Sources: [UALink 200G 1.0 PR, 8 Apr 2025](https://ualinkconsortium.org/wp-content/uploads/2025/04/UALink-1.0-Specification-PR_FINAL.pdf); [UALink 2.0 PR, 7 Apr 2026](https://ualinkconsortium.org/wp-content/uploads/2026/04/UALink-2.0-Specification-PR_FINAL.pdf); [UALink press room](https://ualinkconsortium.org/news/); [UALink roadmap blog](https://ualinkconsortium.org/blog/ualink-roadmap-insights-accelerating-open-scalable-ai-networking-1296/); [UALink specifications page](https://ualinkconsortium.org/specification).

**Silicon reality check.** A headline in UALink's own press room, dated 7 April 2026, reads: *"No-Nvidia interconnect club delivers 2.0 spec before v1.0 silicon ships."* `[FACT]` that the headline exists; the underlying situation — spec ahead of silicon — is `[PRESS]`. Analyst commentary puts first UALink silicon at **2027 at the earliest**, giving NVLink Fusion a ~2-year production head start. `[SPEC]`

### 3.3 UALink vs NVLink positioning

| Dimension | UALink | NVLink | Confidence |
| --- | --- | --- | --- |
| Governance | Open consortium spec, publicly downloadable, any vendor may implement without licensing from NVIDIA | Proprietary; licensed selectively via NVLink Fusion | `[FACT]` |
| Domain size | 1,024 accelerators per pod (1.0); AMD says extensible to 4K | NVL72 today; roadmap to **1,152 accelerators** with co-packaged optics | `[FACT]` / `[VENDOR]` |
| Per-accelerator bandwidth | 200 GT/s per lane; x4 ≈ 800 GT/s ≈ ~0.4 TB/s effective | **NVLink 6: 3.6 TB/s per GPU**; 260 TB/s aggregate in an NVL72 domain | `[VENDOR]` both sides; the ~9× gap figure is `[SPEC]` |
| Power/area | AMD claims UALink is "simpler than a typical Ethernet solution… consumes less power" | NVIDIA claims 3× lower XPU-to-XPU latency and 10× higher packet rate vs off-the-shelf-Ethernet alternatives; NVLink-C2C up to 6× the energy efficiency of PCIe | `[VENDOR]` both sides — **neither independently benchmarked** |
| Division of labour | UALink for scale-up, UEC for scale-out — explicitly complementary per AMD | NVLink scale-up, Spectrum-X / InfiniBand scale-out, Spectrum-XGS scale-across — the same three-tier framing | `[VENDOR]` both |

AMD's framing ([UALink blog with Kurtis Bowman et al.](https://ualinkconsortium.org/blog/ualink-for-scale-up-and-uec-for-scale-out-an-in-depth-discussion-with-amd-958/)): *"UALink imagines up to 1k devices in a pod… UALink isn't looking at a super huge scale like UEC. They are considering 1M devices in a cluster. Given these differences, the two orgs complement each other."* `[VENDOR]`

**The awkward fact for the UALink pitch** `[FACT]`: several UALink board members are simultaneously NVLink Fusion partners. **AWS** is a UALink board member *and* is building Trainium4 on NVLink 6 + MGX (§4). **Astera Labs** and **Synopsys** are UALink board members *and* NVLink Fusion launch partners. **Marvell** is in the UEC, in ESUN, and took a $2B NVIDIA investment to join NVLink Fusion. **Intel** is a UALink board member *and* signed an NVLink deal with a $5B NVIDIA investment attached. Hedging is the dominant strategy across the board, and NVIDIA has been buying into the hedge (§4.4).

---

## 4. NVLink Fusion

### 4.1 What was opened, and when

**Announced at Computex, 18 May 2025.** [NVIDIA newsroom](https://nvidianews.nvidia.com/news/nvidia-nvlink-fusion-semi-custom-ai-infrastructure-partner-ecosystem) `[FACT]`

NVIDIA's own description: *"the high-bandwidth, low-latency connective technology and IP that enables hyperscalers and AI natives to deploy custom XPUs and CPUs into NVIDIA's world-leading AI infrastructure platform."* [NVLink Fusion page](https://www.nvidia.com/en-us/data-center/nvlink-fusion/) `[VENDOR]`

### 4.2 What is actually licensable

| Component | What it does | Confidence |
| --- | --- | --- |
| **NVLink-C2C IP** | Chip-to-chip coherent interconnect; lets a **custom CPU** attach coherently to an NVIDIA GPU (die-to-die or package-to-package via chiplets). The same C2C connects Vera CPU to Rubin GPU in NVIDIA's own parts | `[VENDOR]` (NVIDIA product page confirms C2C-for-partners; the "same as internal" detail is `[PRESS]`) |
| **NVLink Fusion chiplet / bridge** | Attaches a **custom XPU/ASIC** to the NVLink fabric. Press reports this as a **UCIe bridge chiplet** translating UCIe↔NVLink | `[PRESS]` for the UCIe mechanism; `[VENDOR]` that a fusion chiplet exists ("NVLink Fusion includes a NVLink chip") |
| **NVLink Switch chips** | Sold into third-party racks; **third-party hardware requires a license to use them** | `[PRESS]` |
| **MGX rack-scale architecture** | Rack, chassis, power, cooling, 800 VDC, supply chain — "available as a modular OCP MGX rack solution… enabling NVLink Fusion integration with any NIC, DPU, or scale-out switch" | `[VENDOR]` |
| **Surrounding platform** (optional) | Rubin GPUs, Vera CPUs, CPO switches, ConnectX SuperNICs, BlueField DPUs, Mission Control, NCCL/Dynamo/NIXL | `[VENDOR]` |

Sources: [NVIDIA technical blog, integrating semi-custom compute](https://developer.nvidia.com/blog/integrating-custom-compute-into-rack-scale-architecture-with-nvidia-nvlink-fusion/); [NVIDIA blog, "How XPUs Meet a World-Class AI Factory," 24 Aug 2026](https://blogs.nvidia.com/blog/nvlink-fusion-xpu-ai-factory/).

### 4.3 What NVIDIA retains control of

All of the following are **`[PRESS]` / `[SPEC]`, not confirmed by an NVIDIA primary source** — flag this clearly in the deck, because it is the crux of the lock-in argument and it rests on secondary reporting:

1. **Every NVLink Fusion deployment must include at least one NVIDIA product** — GPU, CPU, NVLink switch, or ConnectX NIC. Reported consistently by [TheNextWeb](https://thenextweb.com/news/nvidia-marvell-nvlink-fusion-ecosystem-lock-in), [Towards AI](https://pub.towardsai.net/nvlink-fusion-how-nvidia-turned-its-interconnect-into-a-platform-353c57ef0f50), and [Locsic](https://locsic.com/thinking/scaleup-network-design-deep-dive/). `[PRESS]`
2. **NVIDIA controls the communication-controller and PHY layers** that initialize and manage the links, and **the software that manages the connections**; partners cannot build truly independent mix-and-match systems. [TechPowerUp, June 2025](https://www.techpowerup.com/338156/nvidias-nvlink-fusion-stays-proprietary-third-parties-can-only-work-around-it) `[PRESS]`
3. **NVIDIA chooses who gets a license**, and may decline. A DigiTimes report (19 June 2025) claimed NVIDIA withheld key NVLink components and might not grant licenses to certain products; Tom's Hardware noted *"only the CPU designers seem to be able to implement NVLink both on hardware and software levels."* Alchip publicly pushed back with a supportive statement. [Tom's Hardware, 19 Jun 2025](https://www.tomshardware.com/tech-industry/nvidia-keeping-prized-nvlink-tech-closely-guarded-companies-warn-restrictions-could-hamper-deployment-of-some-solutions) `[PRESS]`
4. Tom's Hardware's summary judgement: *"Nvidia's NVLink Fusion program does not, by itself, make NVLink an open industry standard. Only select companies among Nvidia's partners get access to it."* `[PRESS]`

**NVIDIA's counter-framing**, in its own words:
- Shainer: *"NVLink Fusion is built in a way that you can connect it in a standard interface to any accelerator that you wish or any CPU that you wish… So you can choose NVLink Fusion or in the future you can choose any other scale up infrastructure that you wish."* `[VENDOR]`
- NVIDIA blog, 24 Aug 2026: *"The NVIDIA AI infrastructure platform is vertically integrated and horizontally open."* `[VENDOR]` — a quotable formulation of the whole strategy.

### 4.4 Partner timeline

| Date | Partner | What | Confidence |
| --- | --- | --- | --- |
| 18 May 2025 | **MediaTek, Marvell, Alchip, Astera Labs, Synopsys, Cadence** | First adopters, custom AI silicon / IP / design services — "available now" | `[FACT]` |
| 18 May 2025 | **Fujitsu, Qualcomm** | Custom CPUs coupled to NVIDIA GPUs via NVLink + Spectrum-X scale-out. Cristiano Amon and Vivek Mahajan quoted | `[FACT]` |
| 18 Sep 2025 | **Intel** | Intel to build **NVIDIA-custom x86 data-center CPUs** with NVLink, plus x86 SoCs with RTX GPU chiplets. NVIDIA invests **$5B** at $23.28/share. FTC approval 18 Dec 2025; closed 26 Dec 2025 (214,776,632 shares, ~4%) | `[FACT]` |
| Dec 2025 (re:Invent) | **AWS** | Trainium4 designed to integrate with **NVLink 6 and MGX**; "first of a multigenerational collaboration." Also Graviton CPUs, EFAs, Nitro | `[FACT]` |
| 15 Jan 2026 | **SiFive** | Adopting NVLink Fusion for data-center-class **RISC-V** compute subsystems | `[FACT]` |
| 31 Mar 2026 | **Marvell** | Strategic partnership: Marvell provides custom XPUs + NVLink-Fusion-compatible scale-up networking; joint silicon photonics and AI-RAN work. **NVIDIA invests $2B** | `[FACT]` |
| 24 Aug 2026 | Ecosystem update | NVIDIA blog quotes **Intel** (Tim Wilson), **MediaTek** (Vince Hu), **GUC** (Lie-Szu Juang), **QCT/Quanta** (Jack Luoh), **Annapurna Labs/Amazon** (CC Lee) | `[FACT]` |
| 31 Aug 2026 | **MediaTek** (expanded) | MediaTek formally **adopts NVLink Fusion** as the basis for custom XPUs it designs for third parties. **NVIDIA invests $3.5B in convertible bonds** — NVIDIA's largest direct investment outside the US | `[FACT]` |
| ongoing | **RIKEN FugakuNEXT** | FUJITSU-MONAKA-X CPUs paired with NVIDIA GPUs via NVLink Fusion | `[VENDOR]` |

Sources: [Intel PR, 18 Sep 2025](https://nvidianews.nvidia.com/news/nvidia-and-intel-to-develop-ai-infrastructure-and-personal-computing-products); [Reuters, 18 Sep 2025](https://www.reuters.com/world/asia-pacific/nvidia-bets-big-intel-with-5-billion-stake-chip-partnership-2025-09-18/); [Manufacturing Dive on FTC clearance](https://www.manufacturingdive.com/news/nvidia-intel-custom-chips-5-billion-stake-data-center-pc/760621/); [AWS Trainium4 blog](https://developer.nvidia.com/blog/aws-integrates-ai-infrastructure-with-nvidia-nvlink-fusion-for-trainium4-deployment/); [SiFive PR, 15 Jan 2026](https://www.sifive.com/press/sifive-nvidia-nvlinkfusion-datacenter); [Marvell PR, 31 Mar 2026](https://nvidianews.nvidia.com/news/nvidia-ai-ecosystem-expands-as-marvell-joins-forces-through-nvlink-fusion); [MediaTek PR, 31 Aug 2026](https://nvidianews.nvidia.com/news/nvidia-and-mediatek-deepen-long-standing-partnership-to-build-ai-edge-to-cloud-computing-platforms); [Bloomberg, 31 Aug 2026](https://www.bloomberg.com/news/articles/2026-08-31/nvidia-to-invest-3-5-billion-in-chipmaker-mediatek).

**Samsung**: one analyst source lists Samsung Foundry as providing design-to-manufacturing support in the NVLink Fusion ecosystem, and another says "Intel and Samsung have joined." I could **not** find an NVIDIA or Samsung primary announcement. **Treat Samsung as unverified.** `[SPEC]`

**Groq — a deliberate non-use of NVLink.** NVIDIA's ~$20B license-and-talent deal with Groq (agreement dated 24 Dec 2025; Jonathan Ross and Sunny Madra joined NVIDIA) produced **NVIDIA Groq 3 LPX**, in full production as of 24 Aug 2026 as an extension of the Vera Rubin platform ([NVIDIA PR](https://nvidianews.nvidia.com/news/nvidia-groq-3-lpx-now-in-full-production-with-world-class-speed-for-agentic-ai)) `[FACT]`. Press reports the LPX attaches over an **Ethernet backplane**, not NVLink, with Dynamo orchestrating the GPU/LPU split — attributed to Ian Buck at a GTC 2026 press Q&A `[PRESS]`. If accurate, it is a useful counterexample: NVIDIA itself picks Ethernet when the coupling is loose enough.

### 4.5 NVLink specification donation and public spec status

**No NVLink or NVLink-C2C specification has been donated to any standards body, and none is published as an open specification.** `[ABSENT]` / `[FACT]` (verified by absence from UALink, UEC, OCP, IEEE and OIF document sets, and by consistent press reporting that NVLink Fusion "does not, by itself, make NVLink an open industry standard").

The closest thing to openness is **structural, not specificational**: NVIDIA has contributed *rack and mechanical* artefacts to OCP (§5.3) and exposes NVLink Fusion through a UCIe-based bridge and an "open interface" — but the protocol document itself stays inside NVIDIA. Locsic's characterisation `[SPEC]`: *"the hardware protocol layer is open (PHY, link, transport, coherence, atomic), while the software layer remains controlled (link bring-up, NVSwitch licensing, platform must include at least one NVIDIA product)."*

---

## 5. Other bodies

### 5.1 IEEE 802.3 — 800G / 1.6T (P802.3dj)

**Project status** `[FACT]`:

| Milestone | Date |
| --- | --- |
| 1.6T + 200G/lane scope split out of 802.3df into 802.3dj | November 2022 |
| Timeline revision (Nov 2024): SA ballot Nov 2025→Jan 2026; standard approval **Jun 2026→Sept 2026** | 28 Nov 2024 |
| Working Group Ballot complete; **D3.0** generated; forwarded at IEEE 802 Plenary, Vancouver | 12 March 2026 |
| **Initial SA ballot closed successfully** — 159 voters, 131 returned (82% response), 77% approval, 487 comments | 26 March 2026 |
| Second recirculation SA ballot on **D3.2**; comment-resolution motions in electronic session; working toward **conditional approval to proceed to RevCom** | 9 September 2026 |

Sources: [802.3 DIALOG, SA ballot results, 28 Mar 2026](https://www.ieee802.org/3/email_dialog/msg01813.html); [IEEE 802.3 liaison forwarding D3.0, Mar 2026](https://www.ieee802.org/3/minutes/mar26/outgoing/IEEE_802d3_to_all_3dj_d3p0_0326_Redacted.pdf); [802.3dj D3.2 recirculation thread, Sep 2026](https://ieee802.org/3/B400G/email/msg01985.html); [D'Ambrosia timeline revision, Nov 2024](https://www.ieee802.org/3/dj/public/24_11/dambrosia_3dj_01_2411.pdf).

**NVIDIA's participation is deep and documented — the opposite of its UEC profile.** `[FACT]` The March 2026 task-force minutes' IMAT attendance list includes **Leon Bruckman, Piers Dawe, Bill Simms, Alexander Rysin, Barak Messica and Uri Elzur**, all NVIDIA. NVIDIA names appear as authors/co-authors on comment-resolution presentations through May 2026 (e.g. ILT/RTS loss-of-signal handling, 800GBASE-LR1 APSU, transmitter overshoot penalty) and on the optics ad-hoc (electrical parameters of DME, coefficient initial conditions, training patterns, multipath interference penalties). Zvi Rechtman and Amir Rubin appear on 200G/lane FEC inner-code-bypass work going back to 2023. Sources: [P802.3dj Mar 2026 minutes](https://www.ieee802.org/3/dj/public/26_03/minutes_3dj_2603_unapproved.pdf); [May 2026 session index](https://www.ieee802.org/3/dj/public/26_05/index.html); [optics ad hoc index](https://www.ieee802.org/3/dj/public/adhoc/optics/index.html).

### 5.2 OIF — CEI-224G, CEI-448G, co-packaged optics

| Item | Detail | Confidence |
| --- | --- | --- |
| CEI-224G project starts | Early 2022: **XSR** (die-to-die and die-to-optical-engine, ≥50 mm organic substrate), **VSR** (chip-to-module), **MR** (chip-to-chip, ≤500 mm PCB + 1 connector), **LR** (backplane, ≤1000 mm + 2 connectors) | `[FACT]` |
| CEI-224G status | **LR and MR draft specifications in OIF member review** as of the OFC 2026 deck | `[FACT]` |
| CEI-224G-Linear | Explicitly scoped to support *"Ethernet, Ultra Ethernet Consortium [UEC], AI/ML"* for LPO, CPO and NPO | `[FACT]` |
| **CEI-448G** | **Two new projects started February 2026**; exploring PAM6/PAM8 beyond PAM4, new channel materials, advanced DSP equalization, stronger FEC | `[FACT]` |
| CPO | **OIF-CPO-3.2T-01.0** Co-Packaged Optics Module Implementation Agreement (2025); Energy Efficient Interfaces framework project ongoing | `[PRESS]` for the IA number/date; `[FACT]` that the EEI framework exists |
| OFC 2026 interop demo | 40 member companies; 800ZR, 400ZR, multi-span optics, CEI-448G, CEI-224G, co-packaging, CMIS, EEI | `[FACT]` |

**NVIDIA's OIF position** `[FACT]`: NVIDIA is a listed OIF member company. **Karl Bois (NVIDIA) was elected OIF Technical Committee Vice Chair for 2026**, announced 14 Jan 2026 (term through 30 Sep 2026). NVIDIA does **not** hold an OIF Board seat (2026 board: TE Connectivity, HPE, Alphawave Semi, Ciena, Broadcom, Nokia, Cisco). NVIDIA is **not** among the 40 companies in the OFC 2026 interop demo. Sources: [OIF member companies](https://www.oiforum.com/about-oif/member-companies/); [OIF 2026 Board and Officers, 14 Jan 2026](https://www.oiforum.com/oif-announces-2026-board-of-directors-and-officers/); [OIF current work](https://www.oiforum.com/technical-work/current-work/); [OIF @ OFC 2026](https://www.oiforum.com/meetings-events/oif-ofc-2026/).

NVIDIA's own CPO position: Spectrum-X Ethernet Photonics claims **5× better network power efficiency, 10× greater MTBI, 5× longer uptime** vs pluggable transceivers, using an MMC-16 fibre form factor; Quantum-X Photonics on the InfiniBand side. `[VENDOR]` — [Spectrum-X page](https://www.nvidia.com/en-us/networking/spectrumx/). Worth noting Deierling's admission that in 2021 he *"took a 'clobbering' from Nvidia's optics team for saying CPO was a great technology that was five years away."* ([SDxCentral](https://www.sdxcentral.com/analysis/inside-spectrum-x-nvidias-ethernet-networking-platform/)) `[PRESS]`

### 5.3 Open Compute Project — MGX, ORV3/Kyber, power and cooling

**NVIDIA contributions** `[FACT]` unless marked:

| Date | Contribution |
| --- | --- |
| **15 Oct 2024** | Contributed foundational elements of the **Blackwell platform design** to OCP: rack architecture, compute and switch tray mechanicals, **NVLink cable cartridge volumetrics**, and key portions of the GB200 NVL72 electro-mechanical design. Simultaneously broadened **Spectrum-X support for OCP standards — SAI and SONiC**; ConnectX-8 SuperNIC for OCP 3.0 |
| **Oct 2025 (OCP Global Summit)** | Unveiled **Vera Rubin NVL72/NVL144 MGX-generation open architecture** rack specs; 50+ MGX system and component partners; ecosystem support for **Kyber** (576 Rubin Ultra GPUs, 2027, successor to Oberon); **800 VDC** power delivery, liquid cooling, mechanical design; 20+ partners on 800 VDC silicon/components. NVIDIA **"plans to contribute the upgraded rack as well as the compute tray innovations as an open standard for the OCP consortium"** `[VENDOR]` — a forward-looking commitment, not a completed contribution |
| **13 Oct 2025** | Meta and Oracle adopt Spectrum-X. Meta's **Minipack3N**, a 51.2 Tbps OCP switch on the **NVIDIA Spectrum-4 ASIC**, running OCP SAI + Meta FBOSS. Oracle to build giga-scale Vera Rubin AI factories on Spectrum-X |
| ongoing | **NVIDIA holds an OCP Steering Committee seat** — Elad Wind, **Time Appliances Project** |

Sources: [NVIDIA Blackwell-to-OCP PR, 15 Oct 2024](https://www.nasdaq.com/press-release/nvidia-contributes-blackwell-platform-design-open-hardware-ecosystem-accelerating-ai); [NVIDIA gigawatt AI factories / OCP blog](https://blogs.nvidia.com/blog/gigawatt-ai-factories-ocp-vera-rubin/); [StorageReview OCP coverage](https://www.storagereview.com/news/nvidia-offers-a-preview-of-whats-next-for-gigawatt-scale-ai-factories-at-the-ocp-global-summit); [NVIDIA Spectrum-X / Meta & Oracle PR, 13 Oct 2025](https://nvidianews.nvidia.com/news/nvidia-spectrum-x-ethernet-switches-speed-up-networks-for-meta-and-oracle); [OCP Steering Committee](https://www.opencompute.org/index.php/about/ocp-steering-committee); [NVIDIA MGX page](https://www.nvidia.com/en-us/data-center/products/mgx/).

**The 800 VDC divergence is a clean illustration of the pattern.** NVIDIA distributes **monopolar 800 V** (single +800 V rail plus return, isolated from protective earth) and ships its own reference design. OCP's **Diablo 400** rack-and-power base specification (May 2025) defines 3-phase AC in / **±400 VDC bipolar** out, with an 800 V 2-wire design option. One analyst account puts it bluntly: NVIDIA's monopolar 800 V *"sits entirely outside the open OCP power spec."* [Drybulb, 800VDC rollout](https://www.drybulb.com/writing/800vdc-power-architecture) `[SPEC]`; NVIDIA's own 800 VDC MGX architecture paper confirms the monopolar approach and its MV-rectifier / solid-state-transformer roadmap `[VENDOR]`. Net: NVIDIA contributes *mechanicals* to OCP and keeps the *electrical architecture* on its own reference design, with partners aligning to NVIDIA rather than the reverse. The same paper's framing — NVIDIA sets the timing because its GPUs are the load justifying the buildout — is the general principle.

### 5.4 Chinese bodies — ODCC, CCSA

**NVIDIA does not appear in any Chinese scale-up or AI-Ethernet standards effort I could find.** `[ABSENT]`

| Initiative | Lead / members | Status | Confidence |
| --- | --- | --- | --- |
| **GSE (Global Scheduling Ethernet)** | **China Mobile**-led; 50+ partners incl. CAICT, China Unicom, Tencent, Huawei, ZTE, Ruijie, H3C, Centec, Enflame, Pengcheng/Zijinshan Labs, Tsinghua, BUPT — **plus Broadcom, Intel, Spirent, Keysight**. Launched at the 2023 China Computing Conference | **27 Sep 2024**: full standard set released — GSE1.0 compute-network coordination, GSE2.0 **GSE-N2N** network-side, GSE2.0 **GSE-E2E** NIC-switch coordination. GSE1.0 switches deployed at China Mobile's Harbin intelligent-computing centre supporting an 18,000-GPU cluster; GSE2.0 switches with PKTC forwarding and dynamic global scheduling queues (DGSQ) claim >50% improvement over RoCEv2 | `[FACT]` for the announcement; performance figures `[VENDOR]` |
| **ETH-X / ETH-X Ultra (PAXI)** | **Tencent**-led with CAICT, Kuaishou, Enflame, Biren, Huaqin, Ruijie, H3C, Clounix, Centec, Luxshare, Accelink | Ethernet-based scale-up "hyper-bandwidth domain" (HBD). **PAXI** (Peer-to-peer AXI) transaction-layer protocol supports memory semantics, 256/512-card full interconnect over commodity Ethernet switches. *ETH-X Scale Up Interconnect Protocol White Paper V1.0* (Sept 2025, 103 pp). ODCC AI Network Lab published the **first open scale-up protocol test report**, 400G prototype beating RoCEv2; roadmap adds E2E Retry, LLR, 200G/800G ports, all-optical interconnect | `[FACT]` |
| **ALS / ALink System** | **Alibaba**-led; 18 founding entities incl. CAICT, Alibaba Cloud, **AMD**, Huaqin, H3C, Inspur, Kiwimoore | ALS-D data plane **uses UALink**; ALS-M provides unified management/control | `[PRESS]` (LightCounting) |
| **CCSA** | ODCC operates within the CAICT / CCSA ecosystem (ODCC site footer credits MIIT, CCSA and CAICT) | — | `[FACT]` |

Sources: [ODCC ETH-X PAXI test report](https://www.odcc.org.cn/news/p-1995728064631037953.html); [ODCC 2026 SPC supernode conference](https://www.odcc.org.cn/news/p-2016407351025557505.html) (roundtable with Tencent, Alibaba Cloud, ByteDance on ETH-X / UALink / Ethlink); [C114 GSE launch coverage, Sep 2024](https://www.c114.com.cn/expo/15/a1274520.html); [LightCounting ODCC 2024 note](https://www.lightcounting.com/newsletter/en/september-2024-alibaba-and-tencent-launched-two-new-initiatives-to-scale-up-ai-clusters-at-odcc-2024-365).

**Where NVIDIA and the Chinese players *do* meet: inside UEC.** Alibaba Cloud, Baidu, ByteDance, Huawei, New H3C, Samsung SDS and **Tencent** all joined UEC in the November 2023 cohort — the same consortium NVIDIA joined in 2024 ([UEC 27-new-members post](https://ultraethernet.org/ultra-ethernet-consortium-welcomes-27-new-members/)) `[FACT]`. C114's framing of the global split is worth quoting for the deck: two influential camps, *"超级以太网联盟（UEC）"* led by US companies and *"全调度以太网推进计划（GSE）"* led by Chinese companies. `[PRESS]`

---

## 6. Timeline: NVIDIA's standards-relevant moves, 2023 → September 2026

Rows marked **(context)** are not NVIDIA actions but are needed to read NVIDIA's.

| Date | Event | Confidence |
| --- | --- | --- |
| Nov 2022 | **(context)** IEEE splits 1.6T + 200G/lane out of 802.3df into **P802.3dj** | `[FACT]` |
| 19 Jul 2023 | **(context)** **UEC founded** — AMD, Arista, Broadcom, Cisco, Eviden, HPE, Intel, Meta, Microsoft. NVIDIA absent | `[FACT]` |
| 2023 | NVIDIA launches **Spectrum-X** (Computex keynote); Huang: *"we've brought the capabilities of InfiniBand to the Ethernet architecture"* | `[VENDOR]` |
| 2023 | **(context)** GSE promotion program launched at China Computing Conference | `[FACT]` |
| Nov 2023 | **(context)** UEC admits Alibaba Cloud, Baidu, ByteDance, Huawei, Marvell, Tencent, Keysight and 20 others | `[FACT]` |
| 28 Nov 2023 | **(context)** P802.3dj timeline adopted | `[FACT]` |
| 30 May 2024 | **(context)** **UALink Promoter Group** formed — NVIDIA not invited | `[FACT]` |
| **26 Jun 2024** | **NVIDIA confirms UEC membership** to The Next Platform: *"we may want to offer a UEC version of Ethernet in the future"* | `[VENDOR]` |
| ~29 Aug – 9 Sep 2024 | **NVIDIA publicly listed as a UEC member** (General tier) among 40 additions; total 97 | `[FACT]` |
| Sep 2024 | UEC announces alliances with **OCP, SNIA, OFA** and a **liaison with IEEE 802.3** | `[FACT]` |
| 27 Sep 2024 | **(context)** GSE full standard set released, China Mobile + 50 partners | `[FACT]` |
| Sep 2024 | **(context)** ODCC: Tencent launches **ETH-X**, Alibaba launches **ALink/ALS** | `[PRESS]` |
| Oct 2024 | **(context)** **UALink Consortium incorporated** | `[FACT]` |
| **15 Oct 2024** | **NVIDIA contributes Blackwell/GB200 NVL72 design elements to OCP** (rack, trays, NVLink cable cartridge volumetrics); Spectrum-X adds **OCP SAI + SONiC** support | `[FACT]` |
| 8 Apr 2025 | **(context)** **UALink 200G 1.0** ratified — 1,024 accelerators, 200G/lane | `[FACT]` |
| **~29 Apr 2025** | **(context)** **Broadcom contributes SUE to OCP** | `[VENDOR]` |
| **18 May 2025** | **NVLink Fusion announced (Computex)** — MediaTek, Marvell, Alchip, Astera Labs, Synopsys, Cadence; Fujitsu + Qualcomm CPUs | `[FACT]` |
| **11 Jun 2025** | **(context)** **UEC Specification 1.0 released** | `[FACT]` |
| 19 Jun 2025 | Report that NVIDIA withholds key NVLink components / may deny licenses; Alchip publicly disputes | `[PRESS]` |
| **15 Jul 2025** | **(context)** Broadcom ships **Tomahawk Ultra** and introduces **SUE-Lite** (≤50% IP area reduction) | `[VENDOR]` |
| Aug 2025 | NVIDIA announces **Spectrum-XGS** ("scale-across") at Hot Chips; CoreWeave first adopter | `[FACT]` |
| ~27 Aug 2025 | Huang, Q2 FY2026 earnings call: *"for supercomputing, for the leading model makers, InfiniBand, quantum InfiniBand is the unambiguous choice… Spectrum Ethernet is not off the shelf"* | `[FACT]` |
| 5 Sep 2025 | **(context)** UEC 1.0.1 | `[FACT]` |
| **18 Sep 2025** | **Intel–NVIDIA**: Intel to build NVIDIA-custom x86 CPUs with **NVLink**; NVIDIA invests **$5B** | `[FACT]` |
| **13 Oct 2025** | **OCP Global Summit**: **ESUN launched with NVIDIA as one of 12 founding participants**; NVIDIA unveils Vera Rubin NVL72/NVL144 MGX open rack specs, Kyber, 800 VDC; **Meta and Oracle adopt Spectrum-X**; Meta's Minipack3N built on NVIDIA Spectrum-4 | `[FACT]` |
| 14 Oct 2025 | **(context)** Broadcom **Thor Ultra**, "fully feature compliant with UEC" | `[VENDOR]` |
| Nov 2025 | **(context)** UEC→IEEE 802.1 liaison: CSIG *"planned for publication as part of the UE 1.1 specification in Q1, 2026"* | `[FACT]` |
| **~24 Dec 2025** | **NVIDIA–Groq**: ~$20B license + talent transfer (Jonathan Ross, Sunny Madra) | `[PRESS]` for terms; `[FACT]` that the deal happened |
| 18–26 Dec 2025 | FTC clears Intel transaction (18 Dec); NVIDIA's $5B closes (26 Dec, 214.8M shares) | `[FACT]` |
| **14 Jan 2026** | **Karl Bois (NVIDIA) elected OIF Technical Committee Vice Chair** | `[FACT]` |
| **15 Jan 2026** | **SiFive adopts NVLink Fusion** for RISC-V data-center platforms | `[FACT]` |
| 21/28 Jan 2026 | **(context)** UEC 1.0.2 (date disputed in UEC's own documents) | `[FACT]` |
| Feb 2026 | **(context)** OIF starts **CEI-448G** projects | `[FACT]` |
| **12 Feb 2026** | **(context)** **OCP ESUN 1.0** approved by Steering Committee; 175+ participants | `[FACT]` |
| 12 Mar 2026 | **(context)** P802.3dj **D3.0** forwarded to SA ballot | `[FACT]` |
| **Mar 2026 (GTC)** | NVIDIA launches **Vera Rubin**: Vera CPU, Rubin GPU, **NVLink 6 Switch**, **ConnectX-9 SuperNIC**, BlueField-4 DPU, **Spectrum-6 Ethernet** — "extreme codesign." No UEC claim | `[FACT]` |
| 16 Mar 2026 | **(context)** **Keysight + Broadcom**: first public UEC **LLR/CBFC interop at 800GE**, OFC 2026. NVIDIA absent | `[FACT]` |
| 26 Mar 2026 | **(context)** P802.3dj initial SA ballot closes, 77% approval, 487 comments | `[FACT]` |
| **31 Mar 2026** | **NVIDIA–Marvell**: NVLink Fusion partnership + silicon photonics + AI-RAN; **NVIDIA invests $2B** | `[FACT]` |
| **7 Apr 2026** | **(context)** **UALink 2.0** ratified (Common 2.0 with In-Network Compute, 200G DL/PL 2.0, Manageability 1.0, Chiplet 1.0) — before v1.0 silicon ships | `[FACT]` |
| 11 Jul 2026 | **(context)** UEC presents **UET v1.1 scale-up** plan (UFH, RODL, <1 µs, AI Local profile) at ITU-T | `[FACT]` |
| 16 Jul 2026 | **(context)** **UEC 1.0.3** — adds 200 Gb/s-per-lane signalling. Still no 1.1 | `[FACT]` |
| 16 Jul 2026 | Shainer on theCUBE: *"We are part of UEC, we're part of ESUN, we're part of many consortiums"* | `[VENDOR]` |
| **24 Aug 2026** | **NVIDIA Groq 3 LPX** in full production as a Vera Rubin extension; NVLink Fusion ecosystem blog quotes Intel, MediaTek, GUC, QCT, Annapurna Labs | `[FACT]` |
| 26 Aug 2026 | Q2 FY2027 call: networking revenue +18% QoQ; **Spectrum-X Ethernet +2.6× YoY**; revenue opportunity per gigawatt $18B (Hopper) → $25B (Grace Blackwell) → **$40B (Vera Rubin)** | `[FACT]` |
| **31 Aug 2026** | **MediaTek adopts NVLink Fusion** for third-party custom XPUs; **NVIDIA invests $3.5B** in convertible bonds — largest NVIDIA investment outside the US | `[FACT]` |
| 9 Sep 2026 | **(context)** P802.3dj D3.2 second-recirculation comment resolution; heading to RevCom | `[FACT]` |
| 15–17 Sep 2026 | **(context)** UEC exhibits at AI Infra Summit | `[FACT]` |
| **28 Sep 2026** | **Status at cut-off**: UEC 1.1 unpublished; no NVIDIA UEC-compliance claim; NVIDIA still not in UALink; NVLink still undonated | `[FACT]` |

---

## 7. Analysis material

### 7.1 The pattern, stated as a testable rule

NVIDIA's standards behaviour sorts cleanly along one axis: **does the standard threaten a market NVIDIA sells into, or the moat NVIDIA rents?**

| Layer | Threat type | NVIDIA posture | Evidence |
| --- | --- | --- | --- |
| **PHY / optics** (IEEE 802.3dj, OIF CEI) | Neither — a rising tide; NVIDIA buys and sells at these speeds | **Deep, named, leadership-level engagement.** Six-plus NVIDIA attendees on 802.3dj, authored comment resolutions; OIF Technical Committee **Vice Chair** | §5.1, §5.2 |
| **Rack / mechanical / power** (OCP) | Neither — standardizing the rack *expands* NVIDIA's addressable supply chain | **Generous contribution** of mechanicals; Steering Committee seat. But keeps the 800 VDC electrical architecture on its own monopolar reference design outside the OCP power spec | §5.3 |
| **Scale-out transport** (UEC) | Threatens a **market** — Ethernet AI networking, where NVIDIA is a strong but not sole supplier | **Join, participate, make no commitments.** General member, no Steering seat, no documented contribution, no compliance claim, no interop demo, but a standing option: *"we may want to offer a UEC version of Ethernet in the future"* | §1 |
| **Scale-up fabric** (ESUN, SUE-T) | Threatens the **moat** — but as an *Ethernet* effort NVIDIA can sell switches into it | **Join as a founding participant.** Named in ESUN's initial 12 and in SUE-T's supporter list | §2 |
| **Scale-up protocol** (UALink) | Threatens the **moat** directly, with a rival protocol NVIDIA cannot sell into | **Absent entirely.** Not invited, never joined, 2.5 years on | §3 |
| **NVLink itself** | The moat | **Never donated. Licensed, selectively, with NVIDIA-content requirements and control of the software and PHY layers** | §4 |

The rule: **NVIDIA standardizes the layers it buys, and licenses the layers it sells.** Ethernet compatibility is the defensive perimeter — it neutralizes "you're locked in" objections at procurement time — while the scale-up domain, where the performance gap is widest and switching costs highest, stays closed and monetized.

### 7.2 Direct quotes

**NVIDIA — on consortium participation**

> *"Nvidia is a member of the UEC because our strategy is to support networking specifications that can be beneficial to our customers. We may want to offer a UEC version of Ethernet in the future, alongside Spectrum-X and potentially other specifications in the future."*
> — NVIDIA statement, [The Next Platform, 26 Jun 2024](https://www.nextplatform.com/connect/2024/06/26/what-if-omni-path-morphs-into-the-best-ultra-ethernet/1638832) `[VENDOR]`

> *"We share the vision that Ethernet needs to evolve in the era of AI, and our Quantum and Spectrum-X end-to-end platforms already embody these AI compute fabric virtues. These platforms will continue to evolve, and we will support new standards that may emerge."*
> — Kevin Deierling, SVP Networking, [Futuriom, Sep 2024](https://www.futuriom.com/articles/news/nvidia-has-joined-the-ultra-ethernet-consortium/2024/09) `[VENDOR]`

> *"By the way, NVIDIA is part of the Ultra Ethernet Consortium. We're [happy] to join any consortium that exists, happy to participate, happy to help the ecosystem. The ecosystem is important. And of course, if we will see good technology being developed, being specified, happy to use it, happy to bring it to NVIDIA."*
> — Gilad Shainer, SVP Networking, [theCUBE / NYSE Wired](https://www.thecube.net/events/nyse/ai-factories-data-centers-of-the-future/content/Videos/5c0dd6a1-ccc7-4808-bcae-a4e09012452a) `[VENDOR]`

> *"We are part of a lot of standardization organizations and we continue to enhance the specifications… We are working with the IBTA Consortium, for example, which is where RoCE is being standardized… We are part of UEC, we're part of ESUN, we're part of many consortiums and we actually contribute to that. We continue to contribute a lot of open code, open source code to SONiC… At the same time, we need to continue and work very, very fast because we are in an era where every year there is a new generation that is being released."*
> — Gilad Shainer, [theCUBE, 16 Jul 2026](https://video.cube365.net/c/AS6L_wqQ2AlBJcpBn4jp56avIgiOzHo6) `[VENDOR]`
> **The last sentence is the strategic tell**: annual cadence as the justification for not waiting on consensus processes.

**NVIDIA — on openness and lock-in**

> *"First, we love ecosystem, and second, we love openness. And our infrastructure is based, for example, on open standardizations. InfiniBand, it's an open standard… Spectrum-X is built on ethernet. It's a full ethernet… interoperable with any ethernet device that exists… Even when we look on NVLink Fusion. NVLink Fusion, the interface of NVLink Fusion to connect to GPUs or connect to XPUs or connect to CPUs, it's based on an open interface. So you can choose to connect to it or you can choose to connect to anything else."*
> — Gilad Shainer, theCUBE `[VENDOR]`

> *"People can choose any element that we build and they can connect it to any other element that they choose… Every device that we have built has standard interface to it. Our SuperNIC can connect to any PCI Express device… Our switch has [Ethernet] connectivity to it… NVLink Fusion is connected to a standard interface."*
> — Gilad Shainer, answering a direct lock-in question, theCUBE `[VENDOR]`
> **Note the substitution**: the interviewer asked about *lock-in*; the answer is about *interfaces*. Interface openness and switching cost are different things.

> *"We understand how complicated it's to build scale-up infrastructure, and we wanted to share what we have built over the years to other people that can enjoy for that and can leverage from what we build."*
> — Gilad Shainer on why NVLink Fusion exists, theCUBE `[VENDOR]`

> *"The NVIDIA AI infrastructure platform is vertically integrated and horizontally open."*
> — [NVIDIA blog, 24 Aug 2026](https://blogs.nvidia.com/blog/nvlink-fusion-xpu-ai-factory/) `[VENDOR]`

**NVIDIA — on Ethernet vs InfiniBand**

> *"We have two types of networking, we have Infiniband, which has been used in supercomputing and AI factories all over the world… However, not every data center can handle InfiniBand, because they've already invested their ecosystem in Ethernet for too long, so what we've done is we've brought the capabilities of InfiniBand to the Ethernet architecture, which is incredibly hard."*
> — Jensen Huang, Computex keynote (Spectrum-X launch, 2023), [SDxCentral](https://www.sdxcentral.com/analysis/nvidia-gets-serious-about-ethernet-networking-with-spectrum-x/) `[VENDOR]`

> *"For supercomputing, for the leading model makers, InfiniBand, quantum InfiniBand is the unambiguous choice. If you were to benchmark an AI factory, ones with InfiniBand are the best performance. For those who would like to use Ethernet because their whole data center is built with Ethernet, we have a new type of Ethernet called Spectrum Ethernet. **Spectrum Ethernet is not off the shelf.** It has a whole bunch of new technologies designed for low latency and low jitter and congestion control, and it has the ability to come… much, much closer to InfiniBand than anything that is out there… All three of them are going to be fantastic. NVLink scale-up, Spectrum-X and InfiniBand, scale-out, and then Spectrum-XGS for scale across."*
> — Jensen Huang, Q2 FY2026 earnings call (~27 Aug 2025), [transcript](https://www.investing.com/news/transcripts/earnings-call-transcript-nvidia-q2-2025-strong-earnings-beat-drives-stock-uptick-93CH-4213615) `[FACT]`
> **Emphasis added.** "Not off the shelf" is NVIDIA conceding the differentiation is non-standard, in the same breath as calling Spectrum-X open.

> *"The traditional off-the-shelf ethernet was not designed to support distributed computing. It was designed for single server workload for single CPU workloads… if 99,999 finish the same time, but one is late, every GPU is waiting, and that's really expensive. So we needed to bring in an infrastructure that eliminated the jitter… you cannot solve the networking problem for AI on a single device. You cannot solve everything on a switch. You need the switch to work together with a SuperNIC."*
> — Gilad Shainer, theCUBE `[VENDOR]`
> **This is the load-bearing technical argument for why an end-to-end proprietary pair beats a switch-only standard** — and equally the reason UEC's standardized NIC+switch division is the real threat.

> *"There is a lot of purpose built, which are based on standards and open source for example, but they're all purpose-built. And what we did is essentially… took ethernet and created a purpose-built ethernet for AI."*
> — Gilad Shainer, theCUBE `[VENDOR]`

> *"InfiniBand connects more than 270 supercomputers on the [Top500] list, which is actually the highest number ever… InfiniBand is the gold standard for scale-out infrastructure for distributed computing workloads."*
> — Gilad Shainer, theCUBE `[VENDOR]`

> *"The only Ethernet infrastructure, not InfiniBand, that has managed to reach that scale (100,000 nodes) by running single-job workloads across the entire system."*
> — Gilad Shainer on xAI Colossus, [HPCwire, 9 Sep 2025](https://www.hpcwire.com/2025/09/09/ultra-ethernet-has-arrived-one-network-to-rule-them-all/) `[VENDOR]`

**Competitors and customers**

> *"Thor Ultra is the industry's first 800G Ethernet NIC and is **fully feature compliant with UEC specification**."*
> — Ram Velaga, Broadcom, [14 Oct 2025](https://www.globenewswire.com/news-release/2025/10/14/3166262/19933/en/Broadcom-Introduces-Industry-s-First-800G-AI-Ethernet-NIC.html) `[VENDOR]`
> The compliance claim is itself the competitive weapon — it is exactly what NVIDIA has not said.

> *"Verifying compliance and interoperability is key to creating an open ecosystem."*
> — Asad Khamisy, VP/GM Core Switch Group, Broadcom, [OFC 2026](https://www.businesswire.com/news/home/20260316488886/en/Keysight-Advances-AI-Networking-with-Ultra-Ethernet-LLR-and-CBFC-Interoperability-Demonstration-at-OFC-2026) `[VENDOR]`

> *"By integrating NVIDIA Spectrum Ethernet into the Minipack3N switch and FBOSS, we can **extend our open networking approach** while unlocking the efficiency and predictability needed to train ever-larger models."*
> — Gaya Nagarajan, VP networking engineering, Meta, [13 Oct 2025](https://nvidianews.nvidia.com/news/nvidia-spectrum-x-ethernet-switches-speed-up-networks-for-meta-and-oracle) `[VENDOR]`
> **Meta is the whole thesis in one company**: it buys NVIDIA switch silicon for near-term performance, wraps it in its own FBOSS/SAI software so the silicon is substitutable, and simultaneously co-leads ESUN and champions UEC/UALink to guarantee a future exit. Openness as an *option contract*, not an ideology.

> *"The growing size of AI clusters, combined with ongoing supply chain constraints, is driving the need for vendor diversity and therefore for Ethernet."*
> — Sameh Boujelbene, VP, Dell'Oro Group, quoted in [FirstPassLab](https://firstpasslab.com/blog/2026-03-10-meta-135-billion-nvidia-spectrum-x-ai-networking/) `[PRESS]`

> *"NVLink Fusion gives customers the ability to choose the CPU architecture, the performance level, the software capabilities that best meet their needs."*
> — Tim Wilson, VP/GM data center silicon engineering, **Intel**, [NVIDIA blog, 24 Aug 2026](https://blogs.nvidia.com/blog/nvlink-fusion-xpu-ai-factory/) `[VENDOR]`
> A UALink board member endorsing NVLink Fusion in an NVIDIA blog post is the clearest available evidence that the "open standards coalition" is not a coalition.

> *"With NVLink Fusion we can use proven NVL72 rack design to have time-to-market, and we can have access to multiple suppliers."*
> — CC Lee, senior hardware development manager, **Annapurna Labs (Amazon)**, NVIDIA blog `[VENDOR]`

> *"Nvidia's NVLink Fusion program does not, by itself, make NVLink an open industry standard. Only select companies among Nvidia's partners get access to it."*
> — [Tom's Hardware, 19 Jun 2025](https://www.tomshardware.com/tech-industry/nvidia-keeping-prized-nvlink-tech-closely-guarded-companies-warn-restrictions-could-hamper-deployment-of-some-solutions) `[PRESS]`

> *"[Joining UEC] signals recognition of Ethernet as an emerging standard in AI networking. At the same time, NVIDIA is understandably reticent about Ethernet's threat to InfiniBand."*
> — Futuriom, Sep 2024 `[PRESS]`

### 7.3 What each competitor is actually trying to achieve

`[SPEC]` throughout — these are inferences from the evidence above, not stated positions.

- **Broadcom** wants scale-up to be a *merchant silicon* market. SUE→SUE-T, SUE-Lite, ESUN, Tomahawk Ultra and Thor Ultra are one campaign: make an Ethernet port so cheap in area and power (SUE-Lite: −50% IP) and so low in latency (sub-400 ns XPU-to-XPU claim) that no XPU designer can justify licensing a proprietary link. Broadcom monetizes switches and NICs, so it wins whenever the fabric is standard and the accelerator is someone else's. Its biggest asset is that Thor Ultra can claim UEC compliance and NVIDIA cannot.
- **AMD** needs UALink because Instinct cannot beat NVIDIA on a per-rack basis without a comparable scale-up domain, and it cannot build one alone. Hence the explicit "UALink for scale-up, UEC for scale-out" division: a full stack assembled from standards, positioned as complementary rather than competitive with the Ethernet camp.
- **Marvell** is the purest hedger and the clearest measure of NVIDIA's strategy working. It is in UEC, in ESUN, in SUE-T support, and was an ESUN founder — and it took $2B from NVIDIA to plug custom XPUs into NVLink Fusion. Marvell's business is designing other people's chips; it will implement whatever the customer specifies. NVIDIA paid to make NVLink one of the things customers can specify.
- **Hyperscalers (Meta, Microsoft, AWS, Google, Oracle, OpenAI)** are not pursuing openness for its own sake; they are buying **optionality and supply-chain leverage**. Meta and Microsoft wrote ESUN 1.0 themselves (the CLA is in their names) while Meta buys NVIDIA switch ASICs. AWS sits on the UALink board while building Trainium4 on NVLink 6 and MGX. Oracle standardizes on Spectrum-X. The consistent behaviour is: deploy the fastest thing now, fund the substitute in parallel, keep the software layer (FBOSS, SONiC, SAI) portable so the hardware underneath stays swappable.
- **Intel** is a special case: a UALink board member and a UEC founder that also took $5B and agreed to build NVIDIA-custom x86 CPUs with NVLink. Intel's standards positions are now partly hostage to its balance sheet.
- **China (ODCC/GSE/ETH-X/ALS)** is pursuing the same scale-up-over-Ethernet goal for sovereignty reasons, partly by referencing Western standards (ALS-D uses UALink; ETH-X uses commodity Ethernet switches) and partly by building parallel ones (GSE, PAXI). NVIDIA is absent from all of it while its Chinese customers are simultaneously inside UEC.

### 7.4 Three arguments the evidence supports, with their weak points

1. **"Ethernet compatibility is a defensive perimeter, not a conversion."** Strong. NVIDIA joined UEC quietly and late, sits at General tier, has produced no documented contribution, has made no compliance claim on ConnectX-8/9 or Spectrum-6, and skipped the first public interop event — while simultaneously shipping a proprietary Ethernet platform that Huang concedes is "not off the shelf." *Weak point*: NVIDIA's IEEE 802.3 and OIF work is genuinely substantive, so "NVIDIA doesn't do standards" is false and should not be argued. The accurate claim is narrower and sharper: **NVIDIA does PHY standards and avoids transport standards.**
2. **"NVLink Fusion is lock-in dressed as openness."** Strong in shape, weaker in citation. The one-NVIDIA-product requirement, NVIDIA's control of the link software and PHY, and its discretion over who receives licenses are the load-bearing facts — and **all three rest on trade press and analyst reporting, not on an NVIDIA document I could locate.** Flag this in the deck. What *is* primary-sourced: NVIDIA never donated NVLink to any body; only selected partners get access; the marketing frames the platform as "vertically integrated and horizontally open"; and the investment pattern ($5B Intel, $2B Marvell, $3.5B MediaTek) is buying adoption at the exact chokepoints — the two dominant custom-ASIC houses and the x86 incumbent.
3. **"The open coalition is not coalescing fast enough to matter before 2027."** Supportable. UEC 1.1 — the release that carries scale-up transport, CSIG, PCM and INC — slipped from Q1 2026 and is still unpublished at the end of Q3 2026. UALink shipped a 2.0 spec before 1.0 silicon exists. ESUN 1.0 is a *requirements* document, not a wire protocol. Meanwhile NVLink 6 is in mass production and AWS, Intel, Marvell, MediaTek and SiFive have signed on. *Weak point*: this is a snapshot argument. The 175+/237-company ESUN participation and the Keysight/Broadcom 800GE interop show the ecosystem compounding, and NVIDIA's own $6.5B of adoption payments in 2026 suggest it does not believe the moat holds by itself.

### 7.5 Framing NVIDIA's revenue stake, for sizing the strategy

From the Q2 FY2027 call, 26 Aug 2026 ([transcript PDF](https://s201.q4cdn.com/141608511/files/content_files/TRANSCRIPT_-NVIDIA-Corp-NVDA-US-Q2-2027-Earnings-Call-26-August-2026-5_00-PM-ET.pdf)) `[FACT]`:

> *"Our revenue opportunity has grown from roughly $18 billion per gigawatt to $25 billion with Blackwell, to $40 billion with Vera Rubin, which now spans Vera CPU, Rubin GPU, NVLink, InfiniBand or Ethernet and Groq LPU."*
> *"Our Networking business had another record quarter, with revenue growing 18% on a sequential basis. Spectrum-X Ethernet, which grew 2.6x on a year-over-year basis."*

Huang also counts *"five different types of networking systems"* (scale-up, scale-out, scale-across, scale-in security, multi-campus). The per-gigawatt figure rising from $18B to $40B is the quantified reason NVIDIA cannot let any of those five layers become a commodity it does not sell — and the reason it will pay billions to keep NVLink present in racks full of other people's silicon.

---

## 8. Explicitly not verified

Items I searched for and could **not** confirm. Do not assert these in the deck without further sourcing.

1. **NVIDIA's exact UEC membership tier.** "General member" rests on Futuriom's reading of logo placement on the UEC homepage in Sept 2024. UEC does not publish a member register by class. `[UNVERIFIED]`
2. **Any NVIDIA contribution, chair role, editorship or authored proposal inside UEC.** Nothing found. UEC does not publish working-group rosters, so absence of evidence is genuinely weak evidence here. `[UNVERIFIED NEGATIVE]`
3. **Whether NVIDIA participates in ESUN/SUE-T beyond being named.** The founding-participant listing is solid; the *depth* of participation is unknown. The ESUN 1.0 CLA names only Meta and Microsoft. `[UNVERIFIED]`
4. **The "every NVLink Fusion deployment must include at least one NVIDIA product" rule.** Reported by at least three independent outlets, contradicted by none — but I found **no NVIDIA primary source** stating it. `[UNVERIFIED — PRESS ONLY]`
5. **NVIDIA's control of the NVLink Fusion communication controller / PHY / link bring-up software, and NVSwitch license requirements.** Same status: consistent press reporting, no NVIDIA document. `[UNVERIFIED — PRESS ONLY]`
6. **The UCIe bridge chiplet as the XPU attach mechanism.** Widely reported; NVIDIA's own pages say "NVLink Fusion includes a NVLink chip" without naming UCIe. `[UNVERIFIED]`
7. **Samsung in NVLink Fusion.** Two secondary sources assert it (Samsung Foundry as a design-to-manufacturing partner; "Intel and Samsung have joined"). No NVIDIA or Samsung press release found. `[UNVERIFIED]`
8. **Exact NVLink 6 vs UALink 1.0 bandwidth ratio (~9×).** Each side's number is vendor-stated under different measurement conventions (TB/s per GPU vs GT/s per lane). No neutral benchmark exists. `[UNVERIFIED]`
9. **"First UALink silicon in 2027 at the earliest."** Analyst projection consistent with UALink's own "commercial deployments through 2026 and 2027" language, but no shipping date is public. `[UNVERIFIED]`
10. **NVIDIA Groq 3 LPX using an Ethernet backplane rather than NVLink, and the attributed Ian Buck GTC 2026 statement.** Single secondary source; the NVIDIA PR does not specify the interconnect. `[UNVERIFIED]`
11. **Groq deal terms (~$20B, 24 Dec 2025, ~80% of engineering staff).** Reported by Forbes, Tom's Hardware and others; NVIDIA's public PR covers the resulting product, not the transaction terms. `[UNVERIFIED — PRESS ONLY]`
12. **UEC 1.0.2's actual release date.** UEC's own spec-history page says 28 Jan 2026; the 1.0.3 release notes say 21 Jan 2026. Leave the discrepancy visible. `[CONFLICTING PRIMARY SOURCES]`
13. **Whether a formal UEC plugfest has ever been held.** None found; UEC's events page lists conference exhibits only. Broadcom says UEC is "putting a concerted effort into compliance and interoperability verification," which implies a programme exists but does not describe one. `[UNVERIFIED NEGATIVE]`
14. **Whether NVIDIA has any presence in ODCC, CCSA, GSE, ETH-X or ALS.** Not present in any member list I examined. Chinese-language member rosters may be incomplete in my sources. `[UNVERIFIED NEGATIVE]`
15. **OIF CPO 3.2T IA number and date (OIF-CPO-3.2T-01.0, 2025).** Taken from a secondary citation list, not the OIF IA catalogue. `[UNVERIFIED]`
16. **Whether P802.3dj achieved final standard approval by the original September 2026 target.** As of 9 Sep 2026 it was still resolving second-recirculation comments and seeking conditional approval to proceed to RevCom. No approval announcement found. `[UNVERIFIED]`
17. **Total current UEC membership.** Figures are cumulative and overlapping across announcements (97 in Sept 2024, "100+ / 1,500 participants" end-2024, +27 in 2025); UEC states not all members are displayed, and departures are not reported. Do not quote a current total. `[UNVERIFIED]`
18. **Meta's reported $135B AI capex and associated Spectrum-X figures**, and the Huang quotation *"Spectrum-X is not just faster Ethernet — it's the nervous system of the AI factory."* Sourced only to a single analyst blog; I could not trace the quote to an NVIDIA transcript. **Do not use that quote.** `[UNVERIFIED]`
