# How NVIDIA Customizes AI Systems and Networking for Large Customers

Research compiled **28 September 2026**. Every claim carries a source URL, the date of
the source, and a confidence marker.

## Confidence markers

| Marker | Meaning |
| --- | --- |
| `[C]` **Confirmed** | Primary document: SEC filing, named-company press release, company engineering blog, peer-reviewed paper, or earnings-call transcript. The *fact of the statement* is verifiable. |
| `[V]` **Vendor claim** | A performance, efficiency, or superiority assertion made by the party that benefits from it. Not independently verified. |
| `[P]` **Press report / rumour** | Journalism citing unnamed sources, analyst-firm estimates, or aggregator reporting. Includes credible outlets (Reuters, FT, Bloomberg) where the underlying fact is not on the record. |

A `[C]` on a vendor press release means "NVIDIA definitely said this," not "this is true."
Where a source is an SEO aggregator or an AI-generated content farm, it is flagged inline
and the claim is downgraded. See [§10](#10-what-i-could-not-verify) for everything that
could not be nailed down.

---

## 1. Executive summary — the patterns in the evidence

NVIDIA's customization strategy is best understood as **a fixed core with a negotiable
shell**. Across every customer examined, the same boundary recurs.

**What NVIDIA holds fixed for everyone:**

1. **The die.** There is no per-customer silicon. The only differentiated parts in the
   entire dataset — A800, H800, H20, L20, L2, and the unshipped B30A — are
   *per-jurisdiction*, not per-customer, and they are **subtractive**: capabilities removed
   to clear an export threshold, never capabilities added for a buyer.
2. **The scale-up domain.** NVL72 is the unit. When NVIDIA itself proposed a variant
   (NVL72x2 back-to-back), hyperscalers rejected it — customers can *veto* a scale-up
   topology but the evidence shows none of them *designing* one.
3. **The back-end RDMA fabric, where NVIDIA has contractual leverage.** NVIDIA's own NCP
   requirements document makes an InfiniBand or Spectrum-X east–west fabric a hard `MUST`
   for any cloud partner hosting DGX Cloud.
4. **CUDA and "one architecture."** Huang's most consistent public position across a decade.

**What NVIDIA will bend, and increasingly does:**

1. **Rack mechanicals, cooling, and power** — Microsoft's Callan/Sidekick heat exchangers,
   Azure Boost, Azure Integrated HSM, and DC-SCM all sit inside NVL72 racks.
2. **The CPU** — via MGX host-processor modules and NVLink Fusion (Fujitsu, Qualcomm).
3. **The switch *system*, while keeping the switch *ASIC*** — Meta's Minipack3N is an
   NVIDIA Spectrum-4 ASIC in a Meta-designed, Accton-built chassis running Meta's FBOSS.
   This is the deepest concession in the dataset: NVIDIA sold a component, not a platform.
4. **The scale-out fabric, where the customer has real alternatives** — AWS (EFA/SRD),
   Google (Jupiter/OCS), Oracle (Acceleron RoCE NICs) all keep their own, and NVIDIA still
   sells them GPUs.
5. **The facility itself** — DSX (March 2026) extends NVIDIA's reference-design reach from
   the rack out to the grid interconnect.

**The three structural shifts visible in 2025–2026:**

- **Ethernet won the default slot.** The Vera Rubin DSX reference design names
  "NVIDIA Spectrum-X Ethernet networking" — not InfiniBand — as the fabric of the flagship
  2026 architecture. Meta and Oracle both standardized on Spectrum-X in October 2025; Meta
  extended it across its whole footprint in February 2026.
- **NVIDIA moved from selling systems to underwriting real estate.** The OpenAI relationship
  went from a $100B deployment-linked investment LOI (Sept 2025) → a $30B unconditional
  equity stake (Feb 2026) → a $105B residual-value lease guarantee on an Ohio campus
  (Aug 2026). The capital is now backstopping *the customer's balance sheet*, not the
  hardware purchase.
- **NVLink crossed into competitors' racks.** AWS — the hyperscaler that has rejected
  NVIDIA networking longest and hardest — announced in December 2025 that Trainium4 will
  use NVLink 6 and the MGX rack architecture. NVIDIA's interconnect now ships inside the
  rack of a chip designed to displace NVIDIA GPUs.

---

## 2. OpenAI

### 2.1 The September 2025 partnership, and what happened to it

| Date | Event | Confidence |
| --- | --- | --- |
| 22 Sep 2025 | **Letter of intent**: ≥10 GW of NVIDIA systems; NVIDIA "intends to invest up to $100 billion in OpenAI progressively as each gigawatt is deployed"; first phase H2 2026 on Vera Rubin | `[C]` announcement is real; the LOI is explicitly *not* a contract |
| Nov 2025 | NVIDIA Form 10-Q risk factor: "There is no assurance that we will enter into definitive agreements with respect to the OpenAI opportunity" | `[P]` quoted from the filing by secondary press |
| 19–20 Feb 2026 | Reuters/CNBC/FT: NVIDIA close to a **$30B equity investment**, *not tied to deployment milestones*, replacing the September framework | `[P]` unnamed sources |
| 27 Feb 2026 | **OpenAI confirms**: $110B round at $730B pre-money — $30B SoftBank, $30B NVIDIA, $50B Amazon. NVIDIA collaboration expanded to **3 GW dedicated inference + 2 GW training on Vera Rubin systems**, building on "Hopper and Blackwell systems already in operation across Microsoft, OCI, and CoreWeave" | `[C]` |
| 4 Mar 2026 | Huang at Morgan Stanley TMT reportedly says the $100B figure is "probably not in the cards" because OpenAI is going public | `[P]` single secondary source, not verified against a transcript |
| 17 Aug 2026 | **8-K**: NVIDIA residual-value guaranties with SB Energy for ~4.25 GW IT load at the Portsmouth / PORTS-Pike site, Pike County, Ohio. OpenAI is the tenant | `[C]` SEC filing |

Sources: <https://openai.com/index/openai-nvidia-systems-partnership/> (22 Sep 2025) ·
<https://openai.com/index/scaling-ai-for-everyone/> (27 Feb 2026) ·
<https://www.reuters.com/business/nvidia-close-finalizing-30-billion-investment-openai-funding-round-ft-reports-2026-02-20/> (20 Feb 2026) ·
<https://www.cnbc.com/2026/02/19/nvidia-is-in-talks-to-invest-up-to-30-billion-in-openai-source-says.html> (19 Feb 2026) ·
<https://www.cnbc.com/2026/02/27/open-ai-funding-round-amazon.html> (27 Feb 2026) ·
<https://gadgetbond.com/nvidia-openai-100-billion-deal-uncertainty/> (10-Q quote, secondary)

**Analyst read:** the headline number *fell* (from up to $100B to $30B) while the
*commitment quality rose* (from milestone-contingent intent to closed equity). The
gigawatt figure also fell, from ≥10 GW to 5 GW of Vera Rubin. Treat the original
"$100B / 10 GW" as a superseded framework, not a live deal.

### 2.2 The Ohio guarantee — NVIDIA as landlord-of-last-resort

From the **8-K filed 17 August 2026** `[C]`
(<https://www.sec.gov/Archives/edgar/data/1045810/000104581026000069/nvda-20260817.htm>):

- Multiple **residual value guaranties** with SB Energy Corp. (lessor) covering leases for
  **~4.25 GW of IT load** at the Portsmouth Site.
- **Aggregate payment obligation capped at $105 billion** for the initial commitment.
- Payment obligations conditional on ready-for-service, **"expected beginning in 2028."**
- Option for NVIDIA to provide credit support for **~3.8 GW more**, at its sole discretion.
- Trigger events: OpenAI insolvency or payment failure. NVIDIA then pays the shortfall
  between guaranteed minimum lease value and recovery, and may assume the lease, force a
  relet, force a sale, allow termination, or defer for up to a year.
- Obligations terminate at the earliest of: 20th anniversary of lease commencement, OpenAI
  terminating the lease, **OpenAI achieving a satisfactory credit rating**, or customary events.
- OpenAI indemnifies NVIDIA for amounts actually paid.

From the accompanying **press release, 17 August 2026** `[C]`
(<https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Guarantees-SB-Energys-PORTS-Pike-Technology-Campus-in-Ohio-to-Exclusively-Host-NVIDIA-AI-Compute/default.aspx>):

- NVIDIA is the **exclusive AI compute infrastructure provider** at PORTS-Pike.
- **OpenAI is the customer for 8 IT-GW**; SB Energy builds, owns and operates under a
  **20-year lease** to OpenAI.
- NVIDIA invests **$1.5B in SB Energy**, alongside SoftBank Group and OpenAI.
- SB Energy and SoftBank to build **≥10 GW of new generation** (yielding 8 IT-GW) and
  **≥$4.2B in regional grid infrastructure** with AEP Ohio.
- OpenAI will deploy **NVIDIA's full-stack DSX AI factory platform** at the site,
  "subject to limited exceptions."

> **Discrepancy worth flagging in the deck:** the 8-K puts the expansion option at
> "approximately an additional 3.8 gigawatts"; the same-day press release calls it
> "the remaining 3.75 IT-GW." Both are NVIDIA documents filed the same day. `[C]`

**Why this matters for a customization thesis:** the "subject to limited exceptions"
clause and the "exclusive AI compute infrastructure provider" language mean NVIDIA has
purchased *architectural exclusivity* with a balance-sheet guarantee. This is a
customization mechanism of a kind that did not exist before 2026 — not a technical
concession to the customer, but a financial concession in exchange for the customer
*not* customizing away from NVIDIA.

### 2.3 Stargate — sites, power, hardware

| Site | Operator / owner | Stated capacity | Status | Confidence |
| --- | --- | --- | --- | --- |
| Abilene, TX | Crusoe built/operates; Oracle Cloud Infrastructure | 1.2 GW planned, 8 buildings, ~875–1,100 acres | Phase 1 live 30 Sep 2025; first **NVIDIA GB200 racks delivered June 2025** | `[C]` |
| Milam County, TX | SoftBank-owned hardware (reported) | ~1.1 GW reported | Under construction | `[P]` |
| Shackelford County, TX | Oracle-owned hardware (reported) | not reliably stated | Under construction | `[P]` |
| Doña Ana County, NM | Oracle (reported) | ~0.6 GW reported | Under construction | `[P]` |
| Lordstown, OH | SoftBank/Foxconn JV (manufacturing + DC) | ≤0.3–1.0 GW, figures conflict | Early | `[P]` |
| Wisconsin | — | ~0.5 GW reported | Early | `[P]` |
| Michigan | — | ~0.6 GW reported | Early | `[P]` |

Confirmed facts, Abilene `[C]`
(<https://www.crusoe.ai/resources/newsroom/crusoe-announces-flagship-abilene-data-center-is-live>, 30 Sep 2025):
construction began June 2024; first two buildings energized within a year; **Oracle began
delivering NVIDIA GB200 racks in June 2025**; at completion the eight-building campus will
support "hundreds of thousands of GPUs on a single integrated network fabric"; mixed
liquid and air cooling.

Program framing `[C]`: Stargate announced January 2025 by OpenAI, Oracle, SoftBank and MGX
with a stated $500B four-year envelope.

**Contested:** Epoch AI estimates seven US sites totalling >9 GW planned with ~0.3 GW
operational at Abilene as of spring 2026, and revised its own earlier 0.6 GW estimate down
after an Oracle post implied only ~200 MW live as of 22 April
`[P]` (<https://epochai.substack.com/p/openai-stargate-where-the-us-sites>).
Multiple outlets report a **600 MW Abilene expansion was scrapped in March/April 2026**
after financing stalled, with capacity redirected to Wisconsin and Michigan — but
**Oracle publicly denied any setback** and said the site remains on track
`[P]` (<https://www.datacenterknowledge.com/ai-data-centers/stargate-update-ai-s-biggest-data-center-buildout-meets-reality>).
Do not present the cancellation as fact.

> **Source-quality warning:** several sites returned by search for Stargate site lists
> (`kovastack.ai`, `presenc.ai`, `resources.rework.com`) are AI-generated content farms
> that disagree with each other on capacity figures and site names. Their numbers are
> excluded above except where corroborated.

### 2.4 Hardware generations and co-design

- **GB200 NVL72** — deployed at Abilene from June 2025 `[C]`; also the Microsoft Fairwater
  Wisconsin configuration `[C]`.
- **GB300 NVL72** — Microsoft's NDv6 GB300 cluster serves OpenAI workloads `[C]`.
- **Vera Rubin** — the stated platform for the first OpenAI gigawatt (H2 2026) in the
  Sept 2025 LOI `[C]`, and for the 3 GW inference + 2 GW training in the Feb 2026 round `[C]`.
- **Multi-Path Reliable Connected (MRC)** — a wide-area Ethernet transport protocol
  Microsoft says it developed **jointly with OpenAI and NVIDIA** for the AI WAN linking
  Fairwater sites `[C]`
  (<https://www.sdxcentral.com/news/microsoft-details-ai-wan-connecting-distributed-fairwater-ai-superfactory/>).
  This is the clearest documented instance of three-party protocol co-design involving
  OpenAI.
- OpenAI is also a **founding participant in OCP's ESUN** (Ethernet for Scale-Up
  Networking) alongside NVIDIA, Meta, Microsoft, Oracle, AMD, Broadcom, Arm and others `[C]`
  (<https://engineering.fb.com/2025/10/13/data-infrastructure/ocp-summit-2025-the-open-future-of-networking-hardware-for-ai/>).

### 2.5 The counter-move: OpenAI's own silicon

This belongs in any NVIDIA customization deck as the *limit case* of a customer
customizing around the vendor.

- **13 Oct 2025** `[C]` — OpenAI + Broadcom: 10 GW of OpenAI-designed accelerators.
  Critically: *"The racks, scaled entirely with Ethernet and other connectivity solutions
  from Broadcom."* Deployment targeted to start H2 2026, complete by end 2029.
  (<https://openai.com/index/openai-and-broadcom-announce-strategic-collaboration/>)
- **Jalapeño** — the first-generation inference ASIC. OpenAI claims **1.5–1.9× more work
  per watt** and **1.7–3.6× lower end-to-end latency** versus the best recorded GB200/GB300
  results on the InferenceX benchmark, across GPT-OSS 120B, DeepSeek R1 and Kimi K2.5 1T
  `[V]` — OpenAI's own benchmarking.
  (<https://openai.com/index/openai-broadcom-jalapeno-inference-chip/> ·
  <https://www.theverge.com/ai-artificial-intelligence/984290/openai-jalapeno-ai-chip-benchmarks>)
- OpenAI hardware VP Richard Ho: deployment in "small volumes" by end of 2026, ramping in
  2027; OpenAI does **not** expect to replace its NVIDIA fleet `[C]`.
- SemiAnalysis reports a scale-up topology of 128 ASICs per rack over a copper backplane
  and 2,048 across 16 racks via a rail-only global domain using Broadcom Tomahawk 6
  switches and optical circuit switches `[P]` analyst reporting, not confirmed by OpenAI.
  (<https://newsletter.semianalysis.com/p/openai-jalapeno-better-than-nvidia>)

---

## 3. xAI / Colossus

### 3.1 Colossus 1 — the Ethernet proof point

NVIDIA newsroom, **28 October 2024** `[C]`
(<https://nvidianews.nvidia.com/news/spectrum-x-ethernet-networking-xai-colossus>):

- 100,000 NVIDIA Hopper GPUs in Memphis, using **Spectrum-X Ethernet for the RDMA network** —
  not InfiniBand.
- Built by xAI and NVIDIA in **122 days**; **19 days** from first rack on the floor to
  training start.
- **Spectrum SN5600** switch (Spectrum-4 ASIC, 51.2 Tbps, 64×800 GbE in 2U) paired with
  **BlueField-3 SuperNICs**, 400 GbE per GPU.
- In process of doubling to 200,000 Hopper GPUs.

Performance claims `[V]` — these are NVIDIA's numbers, repeated by press but never
independently measured: **95% data throughput**, and "zero application latency degradation
or packet loss due to flow collisions" across all three fabric tiers. The commonly quoted
"95% vs 60% for standard Ethernet" comparison is NVIDIA marketing framing.
(<https://www.theregister.com/on-prem/2024/10/29/xais-100000-h100-colossus-is-glued-together-using-ethernet/418032> ·
<https://www.datacenterdynamics.com/en/news/xai-to-double-colossus-compute-capacity-reveals-cluster-uses-nvidia-spectrum-x-ethernet/>)

Supermicro built the compute nodes; each GPU server carries ~3.6 Tbps aggregate, with a
separate 400 GbE fabric for CPU/storage traffic `[C]`
(<https://www.supermicro.com/CaseStudies/Success_Story_xAI_Colossus_Cluster.pdf>).

### 3.2 Colossus 2 — current scale

Elon Musk, post on X, **25 September 2026**, reported by Bloomberg and others
`[P]` — a founder claim, not independently verified, and explicitly hedged by Musk himself:

- **Colossus 1**: 150k H100 + 50k H200 + 30k GB200 (~230k accelerators).
- **Colossus 2**: **110k GB200 + 440k GB300 = ~550k**, entirely Blackwell-generation.
- +220k GB300 "fully operational next week"; +220k in November; "if we get lucky, yet
  another 220k GB300 by late December."
- Full schedule ⇒ ~1.21M in Colossus 2 (1.1M of them GB300), ~1.44M across both.

(<https://www.tomshardware.com/tech-industry/data-centers/elon-musks-spacexai-to-add-another-660-000-ai-gpus-this-year-nearing-a-total-of-1-44-million-in-operation-firm-is-building-1-2-gigawatt-power-plant-to-bring-systems-fully-online>)

Power `[P]`: Reuters reported in July that 59 natural-gas turbines were installed without
federal clean-air permits; xAI says it is replacing temporary generation with a **1.2 GW
permanent plant**. The December tranche is power-gated, not supply-gated.

Also reported but **weakly sourced** `[P]`: that xAI was folded into SpaceX in February 2026,
and that Colossus 1 — inefficient for Grok training because of its mixed Hopper/Blackwell
population — has been rented to Anthropic and Google for inference. Verify before use.

### 3.3 NVIDIA's role and the scale-across layer

- NVIDIA co-built the facility and system, per its own release `[C]`.
- **Spectrum-XGS Ethernet** (announced Hot Chips, 22 Aug 2025) is the "scale-across"
  third pillar: distance-aware congestion control, precision latency management, end-to-end
  telemetry, **1.9× NCCL performance** in cross-datacenter environments `[V]`.
  (<https://nvidianews.nvidia.com/news/nvidia-introduces-spectrum-xgs-ethernet-to-connect-distributed-data-centers-into-giga-scale-ai-super-factories>)
- I could **not** find a primary NVIDIA or xAI statement confirming the specific fabric
  generation used in Colossus 2. Do not assume it is Spectrum-X without a source.

**Read:** xAI is NVIDIA's flagship *reference customer*, not a customization customer. It
took the standard stack — NVIDIA switches, NVIDIA SuperNICs, NVIDIA racks — and
differentiated purely on deployment velocity and self-supplied power. The one architectural
choice it made (Ethernet over InfiniBand, in 2024) was a choice NVIDIA had already built a
product for.

---

## 4. Meta

Meta is the most instructive case, because it is simultaneously NVIDIA's largest
customization *concession* and its largest customization *resistance*.

### 4.1 The 2024 dual-cluster experiment

Meta built **two 24,576-GPU H100 clusters** with deliberately different back-end fabrics
so it could compare them `[C]`:

- One with **400G RoCEv2** on Arista 7800 switches.
- One with **400G NDR InfiniBand** on NVIDIA Quantum-2 switches.
- Each: 3,072 Grand Teton nodes, 1,536 racks, 8 pods.
- T0→T1 links **undersubscribed 2:1** (deliberately over-provisioned to absorb RoCEv2's
  congestion behaviour); T1→T2 **oversubscribed 7:1**, with the collective library made
  taper-aware.

(<https://glennklockwood.com/garden/systems/meta's-h100-clusters> summarising Meta's
"Building Meta's GenAI Infrastructure" and the Llama 3 paper)

The SIGCOMM 2024 paper **"RDMA over Ethernet for Distributed AI Training at Meta Scale"**
`[C]` (<https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf>)
states Meta's reasoning for RoCE explicitly: proprietary interconnects — it names
InfiniBand, NVSwitch, Elastic Fabric Adapter and Google's inter-rack ICI together —
"deliver significantly improved performance, [but] their proprietary nature restricts
their deployment flexibility." Meta chose RoCE for verb-semantics compatibility, reuse of
existing Clos design and tooling, and multi-vendor support. The paper also documents a
**receiver-driven traffic admission** scheme in the collective library rather than relying
on DCQCN — i.e. Meta moved congestion control *out of the network vendor's hands* and into
software it owns.

Topology from the paper `[C]`: rack = 16 GPUs across two servers on a shallow-buffer RTSW;
**AI Zone = 4,096 GPUs** at full bisection via CTSW; **DC-scale cluster = 8 AI Zones,
up to 32k GPUs** via ATSW, with deliberate oversubscription at that tier because
hierarchical collectives tolerate it.

### 4.2 DSF, NSF, and the Minipack3N concession

OCP Global Summit, **13 October 2025** `[C]`
(<https://engineering.fb.com/2025/10/13/data-infrastructure/ocp-summit-2025-the-open-future-of-networking-hardware-for-ai/>):

- **Disaggregated Scheduled Fabric (DSF)** — VOQ-based, OCP-SAI + FBOSS, open Ethernet/RoCE
  interface to endpoints "across several xPUs and NICs, **including Meta's MTIA** as well as
  from several vendors." Evolved to a **2-stage architecture, non-blocking up to
  18,432 XPUs**, used to build 18k-GPU building-scale clusters.
- **Non-Scheduled Fabric (NSF)** — new, entirely shallow-buffer disaggregated Ethernet,
  lower latency, targeted at Meta's largest gigawatt-scale clusters such as **Prometheus**.
- **Minipack3N** — a 51.2 Tbps switch **based on the NVIDIA Spectrum-4 ASIC**, designed by
  Meta, manufactured by Accton, running OCP SAI and FBOSS. It sits alongside Minipack3,
  which uses Broadcom Tomahawk silicon.
- Meta is a founding ESUN participant.

Same day, NVIDIA's framing `[C]`
(<https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Spectrum-X-Ethernet-Switches-Speed-Up-Networks-for-Meta-and-Oracle/default.aspx>):
"Meta and Oracle are standardizing on Spectrum-X Ethernet switches." Gaya Nagarajan, Meta
VP of networking engineering, on the record: "By integrating NVIDIA Spectrum Ethernet into
the Minipack3N switch and FBOSS, we can extend our open networking approach."

> **This is the single most important customization datapoint in the report.** NVIDIA sold
> Meta a *switch ASIC*, not a Spectrum-X platform. Meta kept the chassis design, the
> manufacturer, the NOS, the fabric architecture (DSF/NSF), and the congestion-control
> policy. NVIDIA's press release nonetheless describes this as Meta "standardizing on
> Spectrum-X." Both statements are true; they describe very different things. Note the
> naming: Meta and NVIDIA both say "Spectrum **Ethernet**" for the ASIC in the Meta
> quotes, while NVIDIA's headline says "Spectrum-**X**."

### 4.3 The February 2026 expansion

NVIDIA newsroom **17 February 2026** `[C]`
(<https://nvidianews.nvidia.com/news/meta-builds-ai-infrastructure-with-nvidia>) and Meta's
own post the same day `[C]`
(<https://about.fb.com/news/2026/02/meta-nvidia-announce-long-term-infrastructure-partnership/>):

- Multiyear, multigenerational partnership spanning on-prem, cloud and AI infrastructure.
- **Millions of NVIDIA Blackwell and Rubin GPUs**, plus **Vera Rubin NVL72 rack-scale systems**.
- **Arm-based NVIDIA Grace CPUs for Meta's data-center production applications** — widely
  read as the first large-scale standalone Grace-only deployment at a hyperscaler `[P]` for
  the "first" framing; the deployment itself is `[C]`. **NVIDIA Vera CPUs** with potential
  for large-scale deployment in 2027.
- **Spectrum-X Ethernet adopted "across its infrastructure footprint."**
- **NVIDIA Confidential Computing adopted for WhatsApp** private processing.
- Zuckerberg, on the record: building "leading-edge clusters using their Vera Rubin platform."
- Reuters: no value disclosed; **one analyst estimated ~$50 billion** `[P]`
  (<https://www.reuters.com/business/nvidia-sell-meta-millions-chips-multiyear-deal-2026-02-17/>).

The CPU element is the strategically novel part: hyperscalers have historically sourced
general-purpose CPUs from Intel and AMD. Grace-only servers at Meta scale is NVIDIA
expanding *out* of the accelerator socket.

### 4.4 How much of Meta's fabric is NVIDIA vs self-designed

| Layer | Owner | Evidence |
| --- | --- | --- |
| Accelerator (majority) | **NVIDIA** — millions of Blackwell/Rubin | `[C]` Feb 2026 |
| Accelerator (growing minority) | **Meta** — MTIA, with Broadcom + TSMC | `[C]` |
| Scale-up domain | NVIDIA NVL72 for GPUs; **Meta's own 72-accelerator domain for MTIA 400** | `[C]` |
| Server / rack | **Meta** — Grand Teton, Open Rack, OCP | `[C]` |
| Switch ASIC | **Mixed** — NVIDIA Spectrum-4 (Minipack3N) and Broadcom Tomahawk (Minipack3) | `[C]` |
| Switch chassis | **Meta** (built by Accton) | `[C]` |
| Network OS | **Meta** — FBOSS on OCP SAI | `[C]` |
| Fabric architecture | **Meta** — DSF (VOQ, 2-stage, 18,432 XPU non-blocking) and NSF | `[C]` |
| Congestion control | **Meta** — receiver-driven admission in the collective library | `[C]` |
| CPU | **Shifting to NVIDIA** — Grace now, Vera potentially 2027 | `[C]` |

### 4.5 MTIA and what it implies

Meta AI blog `[C]` (<https://ai.meta.com/blog/meta-mtia-scale-ai-chips-for-billions/>),
corroborated by DCD and Tom's Hardware:

| Chip | Role | Status |
| --- | --- | --- |
| MTIA 300 | R&R training; "cost-effective foundation" | In production |
| MTIA 400 | GenAI + R&R; **72-accelerator scale-up domain** | Lab testing complete, deploying |
| MTIA 450 | GenAI inference; **2× HBM bandwidth vs 400**; MX4 low-precision | Mass deployment **early 2027** |
| MTIA 500 | GenAI inference; **+50% HBM bandwidth vs 450**, up to +80% capacity | Mass deployment **2027** |

- MTIA 300 → 500: **HBM bandwidth ×4.5, compute FLOPs ×25** `[C]` (Meta's figures).
- MTIA 450's HBM bandwidth is "much higher than that of existing leading commercial
  products" `[V]` — Meta's claim about NVIDIA parts.
- **400, 450 and 500 share the same chassis, rack and network infrastructure**, which Meta
  says is what enables a **~6-month chip cadence** `[C]`.
- Software runs natively on PyTorch, vLLM and Triton with `torch.compile`/`torch.export`,
  so production models deploy on GPUs and MTIA without MTIA-specific rewrites `[C]`.
- Designed with **Broadcom**, fabbed at TSMC `[C]`.

**The implication for NVIDIA:** Meta copied NVIDIA's own playbook — a 72-accelerator
scale-up domain, a fixed rack that spans generations, tight hardware/software co-design —
and applied it to inference silicon where HBM bandwidth, not FLOPs, is the binding
constraint. Meta's explicit argument is that GPUs "carry a cost and power overhead that
Meta says is unnecessary for inference workloads." That is a direct attack on the
one-architecture premise, from NVIDIA's second-largest customer, while that customer
simultaneously buys millions of Rubin GPUs and adopts Grace CPUs.

**Scale context** `[P]`: a Meta internal memo reviewed by Reuters (July 2026) put 2026
deployment at ~7 GW and a 2027 target of 14 GW, with AI infrastructure spend of up to
$145B for the year. Separate press reporting cites a $115–135B 2026 range. **These figures
conflict; use the Reuters memo figure and label it as an internal memo.** Meta reportedly
had ~1.3M H100-equivalents by end of 2025 `[P]`.

---

## 5. Microsoft / Azure

### 5.1 Fairwater

| Fact | Source | Confidence |
| --- | --- | --- |
| Fairwater Wisconsin announced 18 Sep 2025: 315 acres, 3 buildings, 1.2M sq ft, 46.6 mi of foundation piles, 26.5M lb structural steel | Microsoft blog | `[C]` |
| Runs "a single, massive cluster of interconnected NVIDIA GB200 servers"; 72 Blackwell GPUs per rack in one NVLink domain, 1.8 TB/s GPU-to-GPU, **14 TB pooled memory per rack** | Microsoft blog | `[C]` |
| **865,000 tokens/second per rack, "the highest throughput of any cloud platform available today"** | Microsoft blog | `[V]` |
| Norway and UK AI datacenters to use similar clusters with **GB300** | Microsoft blog | `[C]` |
| Fairwater Atlanta began operation October 2025; second in the family; **two-story design**; **no on-site generation or UPS** (Atlanta grid reliability) | Microsoft Source / SDxCentral | `[C]` |
| AI WAN: Microsoft grew its fibre network **>25% in one year to ~120,000 miles** to link Fairwater sites | Microsoft Source / SDxCentral | `[C]` |

Sources: <https://blogs.microsoft.com/blog/2025/09/18/inside-the-worlds-most-powerful-ai-datacenter/> ·
<https://news.microsoft.com/source/features/ai/from-wisconsin-to-atlanta-microsoft-connects-datacenters-to-build-its-first-ai-superfactory/> ·
<https://www.sdxcentral.com/news/microsoft-details-ai-wan-connecting-distributed-fairwater-ai-superfactory/>

### 5.2 Azure-specific networking — Microsoft runs *both* NVIDIA fabrics

This is the nuance most summaries get wrong. Azure does not choose between InfiniBand and
Spectrum-X; it uses each where it fits.

- **Scale-out inside a cluster: InfiniBand.** The NDv6 GB300 VM series — "the first at-scale
  production cluster of NVIDIA GB300 NVL72 systems," **>4,600 Blackwell Ultra GPUs** —
  is connected with **NVIDIA Quantum-X800 InfiniBand** `[C]`
  (<https://azure.microsoft.com/en-us/blog/building-the-future-together-microsoft-and-nvidia-announce-ai-advancements-at-gtc-dc/>).
  Azure's first GB200 racks were also publicly described as "leveraging InfiniBand
  networking" `[C]`.
- **Scale-across between sites: Spectrum-X Ethernet.** At Ignite (November 2025) NVIDIA
  announced Microsoft is deploying **next-generation Spectrum-X Ethernet switches in the
  Fairwater AI superfactory**, and **>100,000 Blackwell Ultra GPUs in GB300 NVL72 systems
  globally for inference** `[C]`
  (<https://blogs.nvidia.com/blog/nvidia-microsoft-ai-superfactories/>).
- **Wide-area transport: MRC, co-developed.** Multi-Path Reliable Connected, built by
  Microsoft **with OpenAI and NVIDIA**, routes inter-site traffic over the most optimal
  path congestion-free `[C]`.

### 5.3 Documented co-engineering inside the NVIDIA rack

From Azure's GB300 technical post `[C]`
(<https://techcommunity.microsoft.com/blog/azureinfrastructureblog/reimagining-ai-at-scale-nvidia-gb300-nvl72-on-azure/4464556>):

- **Azure Boost** — purpose-built I/O offload accelerator, inside the NVL72 rack.
- **Azure Integrated HSM** — Microsoft's own hardware security module silicon.
- **Custom Datacenter-secure Control Module (DC-SCM)** — Microsoft's modular control plane
  on a hardware root of trust.
- ~**136 kW per rack**; direct liquid cooling for all major components; **closed coolant
  loop with treated water-glycol**, supporting **both facility-water and air-cooled
  environments** so the same rack deploys across Microsoft's whole footprint.
- Leak-detection cables per tray plus rack-base smart management.

The liquid-to-air heat exchanger paired with these racks is reportedly called **Callan**,
an evolution of the publicly announced **Sidekick** `[P]` — ServeTheHome relaying a comment,
not a Microsoft statement.
(<https://www.servethehome.com/new-microsoft-azure-nvidia-gb200-systems-shown/>)

For Rubin, Azure claims its cooling abstraction layer, power redesign (CDU scaling,
high-amp busways) and rack geometries were pre-built for HBM4/HBM4e thermal envelopes, so
"Rubin integrates directly into Azure's platform without rework" `[V]`
(<https://azure.microsoft.com/en-us/blog/microsofts-strategic-ai-datacenter-planning-enables-seamless-large-scale-nvidia-rubin-deployments/>).

Microsoft also built an early **32-GPU custom Blackwell rack** for liquid-cooling
validation before standardising on NVL72 `[P]`
(<https://www.tomshardware.com/tech-industry/artificial-intelligence/microsoft-azure-flaunts-worlds-first-custom-nvidia-blackwell-racks>).

NVIDIA states Microsoft, Dell and CoreWeave have each stood up **Vera Rubin NVL72
engineering racks** `[V]` (NVIDIA social post, 2026).

---

## 6. Oracle OCI, CoreWeave, and the neoclouds

### 6.1 Oracle — the customer that buys NVIDIA networking *and* builds its own NIC

| Generation | Scale | Fabric | Confidence |
| --- | --- | --- | --- |
| H100 Supercluster | up to 16,384 GPUs, 65 EF, 13 Pb/s | RoCEv2, ConnectX-7 | `[C]` |
| H200 Supercluster | up to 65,536 GPUs, 260 EF, 52 Pb/s | RoCEv2 | `[C]` |
| Blackwell Zettascale (Sep 2024) | **up to 131,072 GPUs, 2.4 ZFLOPS** | RoCEv2 with ConnectX-7/ConnectX-8 **or NVIDIA Quantum-2 InfiniBand**; GB200 NVL72 instances IB-based with **SHARP** | `[C]` |
| Zettascale10 (Oct 2025) | **up to 800,000 NVIDIA GPUs, 16 ZFLOPS**, multi-gigawatt, multi-datacenter | **Oracle Acceleron RoCE** fabric + InfiniBand | `[C]` |

Sources: <https://www.oracle.com/news/announcement/ocw24-oracle-offers-first-zettascale-cloud-computing-cluster-2024-09-11/> ·
<https://blogs.oracle.com/cloud-infrastructure/first-principles-zettascale-oci-superclusters> ·
<https://www.oracle.com/cloud/ai-world-oci-roundup/> ·
<https://blogs.oracle.com/cloud-infrastructure/zettascale-in-practice-scaling-beyond-limits>

Oracle's published cluster-network design `[C]`: three-tier Clos, 400 Gbps non-blocking per
GPU, **52 Pbps aggregate**, with tier latencies of **~2 µs (to 256 GPUs) / 5 µs (to 2,048) /
8 µs (to 131,072)**. Oracle also describes **collectives-aware load balancing** — switches
using knowledge of ML collective patterns to map flows to paths. Oracle's claims of
"5× higher network bandwidth performance and up to 5× lower network latency compared to
competitors" are `[V]`.

**The Acceleron deviation is the notable part.** Oracle designed its own RoCE NICs that
"include their own four-port Ethernet switches," enabling **hardware-accelerated
multi-plane traffic steering** so traffic spreads across multiple independent non-blocking
planes, each with its own buffering, congestion control and fault domain — explicitly to
"extend lossless RDMA scalability beyond what any single fabric — or single ASIC — can
support" `[C]` Oracle's own description; the ~4× practical scaling headroom figure is `[V]`.

Yet Oracle **also** appears in NVIDIA's 13 October 2025 release as "standardizing on
Spectrum-X Ethernet switches" and building "giga-scale AI supercomputers" with them `[C]`.
Both are true: Oracle buys NVIDIA switches and builds its own NICs. This is a cleaner
split of the fabric than any other customer in the dataset.

### 6.2 CoreWeave — the reference-architecture maximalist

`[C]` (<https://investors.coreweave.com/news/news-details/2025/CoreWeave-Becomes-First-Hyperscaler-to-Deploy-NVIDIA-GB300-NVL72-Platform/default.aspx>,
3 July 2025):

- First AI cloud provider to deploy **GB300 NVL72**, in Dell's integrated rack-scale system,
  with Switch and Vertiv.
- **NVIDIA Quantum-X800 InfiniBand switches + ConnectX-8 SuperNICs, 800 Gb/s per GPU.**
- Differentiation is in software and operations, not hardware: CoreWeave Kubernetes Service
  (CKS), Slurm on Kubernetes (SUNK), and a custom **Rack LifeCycle Controller (RLCC)**.
- Previously first to GB200 NVL72 GA, and among the first to H200.
- Initial adopter of **Spectrum-XGS** `[V]` (NVIDIA earnings call).
- Uses **NVIDIA DSX Air** to build and test AI-factory digital twins in the cloud and run
  operational rehearsals ahead of physical delivery `[C]` (NVIDIA, March 2026).

Independent comparison `[P]` puts CoreWeave on a dual strategy — Quantum InfiniBand
(400 Gb/s NDR, non-blocking rail-optimised fat-tree) for H100/H200/B200, and
**Spectrum-X RoCE with BlueField-3 and ConnectX-8 on GB300**
(<https://saturncloud.io/reports/gpu-cloud-comparison-report/>).

### 6.3 Other neoclouds

| Provider | Back-end fabric | Note | Confidence |
| --- | --- | --- | --- |
| **Nebius** | InfiniBand (Quantum-2, 400 Gb/s), + RoCEv2/Spectrum-X on newer Blackwell | **Reference Platform NCP** — NVIDIA's designation for partners operating large clusters "built in coordination with NVIDIA" adhering to "a tested and optimized reference architecture." Virtualised (KubeVirt) rather than bare-metal, with no virtualisation layer on IB or GPUs | `[C]` for NCP status and IB; `[P]` for performance parity |
| **Crusoe** | InfiniBand, rail-optimised | Builds and operates Stargate Abilene | `[P]` |
| **Nscale** | **Ultra Ethernet Consortium (UEC)-compliant, Nokia 7220 IXR-H6** — neither InfiniBand nor NVIDIA Spectrum-X | The clearest fabric deviation among NCPs | `[P]` |
| **Lambda** | NVIDIA reference designs | | `[P]` |
| **SoftBank Corp.** | — | Listed by NVIDIA as a Reference Platform NCP | `[C]` |

Nscale and Caterpillar are separately named by NVIDIA as bringing **DSX Vera Rubin
reference designs** to a multi-gigawatt West Virginia site `[C]` (NVIDIA, 16 Mar 2026) —
so a UEC-fabric operator is still a DSX reference-design adopter at the facility layer.

Sources: <https://www.nvidia.com/en-us/data-center/gpu-cloud-computing/partners/> ·
<https://nebius.com/> · <https://newsletter.semianalysis.com/p/clustermax-20-the-industry-standard>

---

## 7. The hyperscalers that reject NVIDIA's network — and the 2025 reversal

### 7.1 Amazon AWS

**The rejection, and its engineering basis.** AWS built **Scalable Reliable Datagram (SRD)**
and exposes it through the **Elastic Fabric Adapter (EFA)**, implemented in hardware on
**Nitro** cards. From AWS's own HPC blog `[C]`
(<https://aws.amazon.com/blogs/hpc/in-the-search-for-performance-theres-more-than-one-way-to-build-a-network/>):

> "SRD is an Ethernet-based transport. We have a massive investment in Ethernet, which
> provides as such a depth and breadth of control over outcomes that we don't want to give
> it up."

- SRD **relaxes in-order delivery**, pushing all packets of a block across many paths at once
  — in practice **64 paths at a time** from hundreds or thousands available. AWS reports
  **p99 tail latency dropping by roughly 10×** by eliminating head-of-line blocking `[C]`
  (AWS's own measurement — treat the magnitude as `[V]`).
- The `amzn-drivers` SRD specification `[C]`
  (<https://github.com/amzn/amzn-drivers/blob/master/kernel/linux/efa/SRD.txt>) documents
  the QP-scaling rationale: RC requires O(N·p²) queue pairs for all-to-all; SRD provides
  reliable, **out-of-order** delivery with no limit on outstanding messages.
- EFA is proprietary and cannot be installed on-premises `[C]`
  (<https://dl.acm.org/doi/fullHtml/10.1145/3533737.3538506>).
- Practical constraint on P6-B300: the primary network card is **ENA-only, up to 350 Gbps**;
  secondary cards carry up to **400 Gbps EFA**; **EFA and ENA share underlying resources**,
  so checkpoint writes contend with all-reduce traffic `[C]` (AWS documentation).

So on P5/P6 GPU instances AWS buys NVIDIA GPUs and attaches them to its *own* transport,
its *own* NIC, and its *own* switch fabric. No NVIDIA SuperNIC, no NVIDIA switch.

**The reversal — 2 December 2025, re:Invent.** `[C]`

> "AWS is designing Trainium4 to integrate with **NVLink 6 and the NVIDIA MGX rack
> architecture**, the first of a multigenerational collaboration between NVIDIA and AWS for
> NVLink Fusion." — NVIDIA Technical Blog
> (<https://developer.nvidia.com/blog/aws-integrates-ai-infrastructure-with-nvidia-nvlink-fusion-for-trainium4-deployment/>)

Corroborated by Reuters `[C]`
(<https://www.reuters.com/business/retail-consumer/amazon-use-nvidia-tech-ai-chips-roll-out-new-servers-2025-12-02/>)
and confirmed on NVIDIA's Q4 FY2026 earnings call: "In Q4, we announced that we will enable
AWS with NVLink to integrate with their custom silicon" `[C]`.

The scope covers **Trainium4, Graviton CPUs, EFA and the Nitro System**. ServeTheHome's
reading `[P]`: because AWS is using NVLink for in-rack scale-up, it will *not* be using
Broadcom Tomahawk Ultra or another Ethernet scale-up silicon for that role.

**The precise shape of AWS's position after December 2025:**

| Layer | AWS's choice |
| --- | --- |
| Scale-up (in-rack) | **NVIDIA NVLink 6** ← *new as of Dec 2025* |
| Rack architecture | **NVIDIA MGX** ← *new as of Dec 2025* |
| Scale-out (inter-node) | **AWS EFA / SRD on Nitro** — unchanged |
| Switch fabric | **AWS** — unchanged |
| Accelerator | **Both** — Trainium4 and NVIDIA GPUs |

**Unverified `[P]`:** a secondary analysis claims Trainium4 connects up to 72 ASICs
all-to-all at 3.6 TB/s per chip for 260 TB/s total via a UCIe bridge chiplet, and that
every NVLink Fusion deployment must contain at least one NVIDIA product. Neither figure
appears in NVIDIA's or AWS's own materials. Do not put these numbers on a slide.
(<https://pub.towardsai.net/nvlink-fusion-how-nvidia-turned-its-interconnect-into-a-platform-353c57ef0f50>)

### 7.2 Google

Google is the most complete rejection of NVIDIA networking, and it published the cost case.

From the NSDI '24 paper *Resiliency at Scale: Managing Google's TPUv4 Machine Learning
Supercomputer* `[C]` (<https://www.usenix.org/system/files/nsdi24spring_prepub_zu.pdf>):

> "Using OCS scales TPUv4 pod with low cost: the OCS and optical fiber costs are **< 5% of a
> TPUv4 pod's total capital cost**, and their operating power is **< 3% of a pod's total
> power**. The capital and operating cost of TPUv4 OCS supercomputer is considerably lower
> than the alternative of scaling with packet switches such as Infiniband."

The paper explicitly contrasts the designs: "Nvidia uses a 2-tier NVswitch-based fat tree
network over NVlink for inter-GPU collectives. These represent a different design point
compared with ours: OCS simplifies the ICI network design compared to introducing packet
switches because it establishes dedicated physical channels without the need to control
shared traffic."

- Google's scale-up interconnect is **ICI**, its own, playing NVLink's role.
- **Optical circuit switches** tilt mirrors to redirect light without opto-electronic
  conversion, letting Google reconfigure a 3D torus and mix hardware generations in one
  fabric.
- **Jupiter** — the datacenter fabric — now scales to **13 Pb/s** with OCS, WDM and the
  Orion SDN controller, and Google cites OCS specifically for "in-place physical upgrades
  and an ever-evolving, heterogeneous network that supports multiple hardware generations
  in a single fabric" `[C]`
  (<https://cloud.google.com/blog/products/networking/speed-scale-reliability-25-years-of-data-center-networking>).

**But Google does buy NVIDIA networking silicon — just not NVIDIA switches.** The same
Google Cloud post confirms A3 Ultra VMs "feature **NVIDIA ConnectX-7 networking**, supports
non-blocking 3.2 Tbps per server of GPU-to-GPU traffic over **RoCE**" with "future
offerings based on NVIDIA GB200 NVL72" `[C]`. Google buys the NIC and the NVL72 scale-up
domain; the switching layer stays Jupiter.

Analyst estimate `[P]`: SemiAnalysis puts all-in TCO per Ironwood (TPUv7) chip in a full 3D
torus at **~44% below a GB200 server**, and ~30–41% below GB200/GB300 even after Google's
margin when leased externally. Estimate, not a disclosed figure.
(<https://newsletter.semianalysis.com/p/tpuv7-google-takes-a-swing-at-the>)

### 7.3 Tesla

| Date | Event | Confidence |
| --- | --- | --- |
| Q4 2024 earnings | **Cortex** complete: "~50k H100 training cluster at Gigafactory Texas" | `[C]` Tesla earnings |
| Q2 2025 earnings | +16k H200, bringing Cortex to **67k H100-equivalents** | `[C]` Tesla earnings |
| July 2025 | $16.5B Samsung deal for AI6 | `[C]`/`[P]` |
| 7 Aug 2025 | Bloomberg: **Dojo team disbanded**; Peter Bannon departing; ~20 staff to DensityAI | `[P]` unnamed sources |
| ~10 Aug 2025 | Musk on X: "Once it became clear that all paths converged to AI6, I had to shut down Dojo... Dojo 2 was now an evolutionary dead end. Dojo 3 arguably lives on in the form of a large number of AI6 SoCs on a single board." | `[C]` |
| 18–19 Jan 2026 | Bloomberg: Musk says Tesla **will resume work on Dojo3** after AI5 design progress | `[P]` |

Sources: <https://techcrunch.com/2025/08/11/elon-musk-confirms-shutdown-of-tesla-dojo-an-evolutionary-dead-end/> ·
<https://www.datacenterdynamics.com/en/news/musks-tesla-ends-dojo-supercomputer-effort-shifts-compute-to-nvidia-and-samsung-report/> ·
<https://www.bloomberg.com/news/articles/2026-01-19/musk-says-tesla-will-restart-work-on-chip-project-dojo3>

Tesla is the clean example of **failed vertical integration reverting to NVIDIA**: it
built custom silicon (D1), a custom supercomputer (Dojo), and a $500M facility, then
consolidated onto AI5/AI6 for inference and NVIDIA GPUs for training. Claims circulating
that Dojo3 is a space-based, NVIDIA-free system built on AI7 are **not verified** — see §10.

### 7.4 Accept / reject matrix

| Customer | Scale-up | Scale-out NIC | Scale-out switch | Scale-across |
| --- | --- | --- | --- | --- |
| **OpenAI** (via partners) | NVIDIA NVLink | NVIDIA | NVIDIA | MRC, co-designed |
| **OpenAI** (own racks) | Broadcom Ethernet | Broadcom | Broadcom | Broadcom / OCS `[P]` |
| **xAI** | NVIDIA NVLink | **NVIDIA BlueField-3** | **NVIDIA Spectrum SN5600** | Spectrum-XGS `[V]` |
| **Microsoft** | NVIDIA NVLink | NVIDIA | **NVIDIA IB (Quantum-X800) + Spectrum-X** | **MRC over Microsoft AI WAN** |
| **Oracle** | NVIDIA NVLink | **Oracle Acceleron** (also ConnectX) | **NVIDIA IB + Spectrum-X** | Oracle multi-plane |
| **CoreWeave** | NVIDIA NVLink | NVIDIA ConnectX-8 | **NVIDIA Quantum-X800 IB** | Spectrum-XGS `[V]` |
| **Meta** | NVIDIA NVL72 (GPU) / Meta (MTIA) | Multi-vendor | **NVIDIA ASIC in Meta chassis** | Meta DSF/NSF |
| **AWS** | **NVIDIA NVLink 6** *(from Dec 2025)* | **AWS Nitro/EFA** | **AWS** | AWS |
| **Google** | NVIDIA NVL72 (GPU) / Google ICI (TPU) | **NVIDIA ConnectX-7** (GPU VMs) | **Google Jupiter + OCS** | Google |
| **Tesla** | NVIDIA | NVIDIA | NVIDIA | n/a |

**Pattern:** every hyperscaler with a mature in-house network organisation (AWS, Google,
Meta, Oracle) keeps the switching layer. Every customer without one (xAI, CoreWeave,
Nebius, Tesla, and OpenAI when renting) takes NVIDIA's whole fabric. The scale-up layer is
where NVIDIA is winning uncontested — including, now, inside AWS.

---

## 8. China and export-control-driven customization

This is the only place NVIDIA has ever shipped materially different silicon, and the
customization is **regulatory, subtractive, and per-jurisdiction — never per-customer.**

### 8.1 The SKU lineage

| Part | Announced | What was cut | Confidence |
| --- | --- | --- | --- |
| **A800** | Nov 2022 | NVLink bandwidth reduced (A100's 600 GB/s cut to 400 GB/s) | `[C]` Reuters |
| **H800** | Mar 2023 | **NVLink cut from 900 GB/s to ~400 GB/s**; FP64 capped ~1 TFLOPS. **Compute unchanged** — same FP8/FP16 Transformer Engine, 80 GB HBM3 | `[C]` Reuters + Epoch AI |
| **H20** | Nov 2023 | **The inverse cut.** Compute slashed to 148 TFLOPS BF16/FP16 and 296 TFLOPS FP8 (H100: 1,979 TFLOPS FP16 w/ sparsity), FP64 to 1 TFLOPS — **but NVLink left at the full 900 GB/s** and memory *increased* to 96 GB HBM3 at 4.0 TB/s | `[C]` spec table |
| **L20 PCIe** | Nov 2023 | Ada Lovelace, 48 GB GDDR6, 864 GB/s, 239 TFLOPS FP8, 275 W | `[C]` |
| **L2 PCIe** | Nov 2023 | Ada Lovelace, 24 GB GDDR6, 300 GB/s, 193 TFLOPS FP8 | `[C]` |
| **B30A / B40 / B30 / "RTX Pro 6000D"** | reported 2025 | Blackwell-derived China part. **Never shipped.** Naming, specs, and even whether it is one product or several are unresolved | `[P]`/**rumour** |

Sources: <https://www.reuters.com/technology/exclusive-nvidia-offers-new-advanced-chip-china-that-meets-us-export-controls-2022-11-08/> ·
<https://www.reuters.com/technology/nvidia-tweaks-flagship-h100-chip-export-china-h800-2023-03-21/> ·
<https://www.reuters.com/technology/nvidia-plans-release-three-new-chips-china-local-media-2023-11-09/> ·
<https://www.tomshardware.com/pc-components/gpus/new-nvidia-ai-gpus-designed-to-get-around-us-export-bans-come-to-china-h20-l20-and-l2-to-fill-void-left-by-restricted-models> (spec table, originally SemiAnalysis) ·
<https://epoch.ai/gradient-updates/us-export-controls-china-ai>

**The H800 → H20 inversion is the single sharpest technical point available.** Epoch AI's
analysis `[C]` shows why:

> "The threshold set by the [October 2022 rules] happens to be exactly equal to the NVLink
> bandwidth of the A100... NVIDIA got around this restriction by lowering the H800's NVLink
> bandwidth to 400 GB/s, compared to the 900 GB/s supported by the H100, ensuring the H800
> remained below the bar... detailed calculations show that 400 GB/s of NVLink bandwidth is
> still enough to orchestrate a frontier training run without running into communication
> bottlenecks, mostly because we can hide network communication behind useful work done by
> the GPUs. In this setting training efficiency is largely about FLOP per second per dollar,
> and on this metric the H800 was about as good as the H100."

When the October 2023 rules dropped the interconnect criterion and made the test purely
compute-based, the H800 became non-exportable overnight, and NVIDIA had to cut the thing it
had previously protected. **NVIDIA customizes exactly to the letter of the binding
constraint, and no further.**

- H20 launch was delayed from ~16 Nov 2023 to Q1 2024 `[C]` Reuters.
- April 2025: BIS restricted the H20. July 2025: reversed `[C]`/`[P]`.

### 8.2 The 2025 licensing saga and the revenue share

| Date | Event | Confidence |
| --- | --- | --- |
| 11 Aug 2025 | **White House confirms** NVIDIA and AMD agreed to pay **15% of China chip-sale revenue** to the US government in exchange for export licences (NVIDIA H20, AMD MI308) | `[C]` — confirmed by the White House |
| 12 Aug 2025 | Reuters: Trump "upended decades of U.S. national security policy, creating an entirely new category of corporate risk" | `[C]` Reuters analysis |
| 15 Aug 2025 | Rep. Krishnamoorthi letter to the President: ECRA "expressly prohibits" fees "in connection with the submission, processing, or consideration of any application for a license" | `[C]` primary document |
| Dec 2025 | Extended: **25% for H200**, with similar arrangements for AMD and Intel | `[P]` Lawfare |
| 14 Jan 2026 | 25% formally imposed via **presidential proclamation** | `[P]` Lawfare |
| 15–16 Jan 2026 | BIS reportedly moved H200 and AMD MI325X from presumption of denial to **case-by-case review**, subject to a 21,000 TPP / 6,500 GB/s DRAM-bandwidth threshold; Blackwell-class parts **not** included | `[P]` — see §10 |

Sources: <https://www.cnbc.com/2025/08/11/trump-nvidia-amd-china-chip-revenue-deal-implications.html> ·
<https://www.reuters.com/legal/government/trumps-unusual-nvidia-deal-raises-new-corporate-national-security-risks-2025-08-12/> ·
<https://democrats-selectcommitteeontheccp.house.gov/sites/evo-subsites/democrats-selectcommitteeontheccp.house.gov/files/evo-media-document/2025.08.15-krishnamoorthi-letter-to-president-trump-export-controls_0.pdf> ·
<https://www.lawfaremedia.org/article/trump-s-illegal-ai-chip-export-controls--and-who-can-challenge-them>

Legal exposure `[C]` as characterised by Lawfare: ECRA bars BIS from charging any licence
fee; the Constitution's Export Clause bars any "Tax or Duty" on exports; and taxation is a
congressional power. The administration styles the payments as voluntary agreements to
sidestep both. No successful challenge has been reported.

### 8.3 Beijing's counter-controls, and who actually bought what

**August 2025 — the discouragement campaign.** Reuters `[C]` reports that the **Cyberspace
Administration of China** and other agencies summoned **Tencent and ByteDance** over H20
purchases and held meetings with **Baidu** and smaller firms, asking why they needed NVIDIA
chips rather than domestic suppliers, and raising concerns that materials NVIDIA required
for US government review could contain client data. Reuters' sources said the companies
**had not been formally ordered to stop**.
(<https://www.reuters.com/world/china/china-cautions-tech-firms-over-nvidia-h20-ai-chip-purchases-sources-say-2025-08-12/>)

Separately and **not confirmed by Reuters** `[P]`: Bloomberg reported official notices
discouraging H20 use for government/national-security work; *The Information* reported that
**ByteDance, Alibaba and Tencent were ordered by the CAC to suspend NVIDIA purchases
altogether** pending a security investigation. Reuters stated it could not confirm these.
Present the CAC suspension as *reported and unconfirmed*.

**2026 — the two-gate regime.**

| Date | Event | Confidence |
| --- | --- | --- |
| 14 May 2026 | **Reuters exclusive**: the US cleared ~10 Chinese firms — including **Alibaba, Tencent, ByteDance and JD.com** — to buy H200, plus **Lenovo and Foxconn as approved distributors**. **Not a single delivery had been made.** | `[C]` Reuters |
| ~May 2026 | Lutnick testifies the US will not sell its most advanced chips to China under any circumstances, and that **China's own government is blocking its cloud providers from buying** the permitted hardware | `[P]` Reuters via secondary |
| Aug 2026 | **FT**: ByteDance and Tencent each took delivery of **~10,000 H200s**; every purchase requires case-by-case **NDRC** approval; Beijing directs most licensed volume to **Hong Kong** rather than the mainland; NVIDIA reportedly holds ~500,000 H200s built for Chinese customers | `[P]` FT via Tom's Hardware |
| 27 Aug 2026 | **NVIDIA confirms** first H200 shipments to China; **less than 1% of its $89B Q2 data-centre revenue** | `[C]` company disclosure |

Sources: <https://www.reuters.com/business/retail-consumer/us-clears-h200-chip-sales-10-china-firms-nvidia-ceo-looks-breakthrough-2026-05-14/> ·
<https://www.tomshardware.com/pc-components/gpus/first-nvidia-h200-shipments-reach-bytedance-and-tencent-as-beijing-loosens-its-import-block> ·
<https://www.scmp.com/tech/big-tech/article/3365383/nvidia-ships-first-h200s-china-forecasts-no-data-centre-computing-revenue>

Huang's claim that NVIDIA's China market share "fell from 95% to zero" is `[V]`.
TrendForce's estimate that domestic Chinese silicon is approaching **90% share** three
years after the first Hopper bans is `[P]` analyst estimate.

**Grey-market flows** `[P]`: C4ADS, a US-government-funded nonprofit, documented
**$13.4M of A100, H100/GH100 and AD102-series GPUs** routed through Vietnam, India and
Malaysia between 2022 and 2025 in a "consistent pattern"
(<https://www.tomshardware.com/tech-industry/artificial-intelligence/billions-worth-of-export-restricted-ai-accelerators-sold-to-china-report-details-how-chinese-firms-skirt-trumps-regulations>).

**The structural irony worth a slide:** the US restricts what may be sold; China restricts
what may be bought. Both use the same two instruments — case-by-case licensing and
end-location conditions. NVIDIA's China customization problem is now *bilateral*, and its
product differentiation cannot solve a demand-side ban.

> **Source warning:** `tech-insider.org` asserts NVIDIA "sells legally" the B30A and B40
> in China. This contradicts Reuters, Commerce Department testimony and NVIDIA's own
> disclosures. Disregard.

---

## 9. Mechanisms of customization

### 9.1 MGX — modular reference architecture

`[C]` (<https://investor.nvidia.com/news/press-release-details/2023/NVIDIA-MGX-Gives-System-Makers-Modular-Architecture-to-Meet-Diverse-Accelerated-Computing-Needs-of-Worlds-Data-Centers/default.aspx>,
28 May 2023; <https://www.nvidia.com/en-us/data-center/products/mgx/>):

- Launched at Computex 2023 with ASRock Rack, ASUS, GIGABYTE, Pegatron, QCT and Supermicro.
- **>100 server variations** at launch; now "over 100 combinations" from single node to
  rack scale, with **>200 ecosystem partners** on third-generation rack-scale MGX.
- Partners select GPU, DPU and CPU — **Grace, Vera, x86, and other Arm CPUs** — from a
  certified menu.
- Explicitly contrasted with HGX: "MGX differs from NVIDIA HGX in that it offers flexible,
  multi-generational compatibility... In contrast, HGX is based on an NVLink-connected,
  multi-GPU baseboard."
- Compatible with **OCP and EIA racks**.
- MGX 6U supports multiple **host-processor modules (HPMs)** in one chassis, spanning x86
  and Vera, so a partner standardises on one server design across CPU architectures.

Claims: "slash development costs by up to three-quarters" `[V]`; typical design cycles of
18–24 months and several $M compressed to "a couple of months" `[V]` (NVIDIA exec quoted by
The NextPlatform, <https://www.nextplatform.com/compute/2023/05/30/mgx-nvidia-standardizes-multi-generation-server-designs/1648356>).

**What MGX actually is:** a *menu*, not a design service. Customization means choosing from
NVIDIA-certified combinations; the ODM adds BMC, firmware and final qualification. It
converts per-customer engineering into per-customer SKU selection.

### 9.2 NVLink Fusion — semi-custom silicon

`[C]` (<https://nvidianews.nvidia.com/news/nvidia-nvlink-fusion-semi-custom-ai-infrastructure-partner-ecosystem>,
18 May 2025):

- **XPU/ASIC design partners**: MediaTek, Marvell, Alchip, Astera Labs, Synopsys, Cadence.
- **CPU partners**: Fujitsu and Qualcomm, each coupling custom CPUs with NVIDIA GPUs,
  NVLink scale-up and Spectrum-X scale-out.
- Two integration paths `[C]`: **NVLink-C2C** for coherent CPU↔GPU die/package connections
  (the same technology joining Vera to Rubin), and a **UCIe bridge chiplet** for custom
  ASICs/XPUs.
- Adopters get the **MGX rack-scale architecture and NVIDIA's own supply chain**, which
  NVIDIA pitches as eliminating new rack design and supplier management.
- **RIKEN FugakuNEXT** will pair Fujitsu MONAKA-X CPUs with NVIDIA GPUs over NVLink Fusion `[C]`.
- **AWS Trainium4** is the flagship adopter (see §7.1) `[C]`.

Huang's own description of the business model, Computex 2025 Q&A `[C]` (transcript hosted
on a secondary site — <https://ourcoders.com/news/show/39290/>):

> "The more likely vision is that they will buy an NVLink chiplet, and they'll buy the
> NVLink switch, and the NVLink spine, and the Spectrum-X switch, and all of the necessary
> software to go along with it... So one architecture, one hardware architecture, one NVLink
> architecture, one networking architecture, sometimes it's three CPUs, sometimes it's
> Fujitsu CPUs, sometimes Qualcomm CPUs, it's very nice for the customer... All of a sudden,
> Nvidia's entire ecosystem becomes integrated with theirs, fused with theirs. Pretty clever, huh?"

This is the clearest statement of the strategy in NVIDIA's own words: **allow variation at
the compute socket, monetise the interconnect, the rack and the switch.**

### 9.3 DSX — the reference design goes to the grid

`[C]` (<https://nvidianews.nvidia.com/news/nvidia-releases-vera-rubin-dsx-ai-factory-reference-design-and-omniverse-dsx-digital-twin-blueprint-with-broad-industry-support>,
16 March 2026, GTC):

- **Vera Rubin DSX AI Factory reference design** — "outlines how to design, build and
  operate the entire AI factory infrastructure stack, spanning compute, **NVIDIA Spectrum-X
  Ethernet networking** and storage" plus power, cooling and control systems.
- **Omniverse DSX Blueprint** GA on build.nvidia.com for physically accurate digital twins.
- Software libraries: **DSX Max-Q** (maximise tokens/W within a fixed power budget),
  **DSX Flex** (grid-responsive power orchestration), **DSX Exchange** (IT/OT signal
  integration), **DSX Sim** (digital twin modelling of GPUs, networking and partner
  infrastructure), **DSX OS**.
- Ecosystem: Cadence, Dassault Systèmes, Eaton, Jacobs, Nscale, Phaidra, Procore, PTC,
  Schneider Electric, Siemens, Switch, Trane, Vertiv, plus energy firms Emerald AI,
  GE Vernova, Hitachi and Siemens Energy.
- Vertiv is building **Vertiv OneCore Rubin DSX**, a prefabricated converged infrastructure
  product `[C]`. Phaidra claims DSX Max-Q integration delivers **~10% more compute** by
  reducing cooling spikes `[V]`.
- NVIDIA's framing of the constraint: "over $300 billion in equipment backlogs and more than
  200 gigawatts of projects waiting in U.S. interconnection queues" `[V]`.

**Note for the deck:** the flagship 2026 reference design names **Spectrum-X Ethernet**, not
InfiniBand. Combined with Meta, Oracle and Microsoft all adopting Spectrum-X in 2025–26,
this is NVIDIA repositioning Ethernet as the default and InfiniBand as the specialist option.

Architecturally, DSX is MGX applied one level up: standardised building blocks, a certified
partner menu, and a digital twin so the customer can *simulate* variation instead of
*building* it.

### 9.4 NCP reference architectures and DGX Cloud — where the hard limits are written down

NVIDIA publishes its requirements for Cloud Partners hosting DGX Cloud. These documents are
the best available evidence for **what NVIDIA refuses to customize**, because they are
written as `MUST`/`SHALL` obligations.

From *NVIDIA Requirements for AI Clouds* `[C]`
(<https://docs.nvidia.com/dsx/ncp/nvidia-requirements-for-ai-clouds/home>) and
*Inference Provider Platform Requirements on GB300 NVL72 for NCPs* `[C]`
(<https://docs.nvidia.com/dsx/ncp/inference-provider-requirements/home>):

**Fixed by NVIDIA — non-negotiable:**

| Requirement | Text |
| --- | --- |
| Fabric | **`NET-2` (MUST)**: "East-west back-end RDMA fabric (**InfiniBand or Spectrum-X**) for multi-node serving: NCCL collectives (SHARP where supported)." No third option. |
| Cluster design | "The NCP adheres to the following reference designs as a starting point: the **DSX Facilities Infrastructure Design Guide**...; the **GB300 NVL72 Reference Design** for cluster architecture, server specification, and **network cabling**" — distributed via the NVOnline partner portal |
| Control plane | A **north-south plane on the BlueField-3 DPU** enforcing zero trust, multi-tenancy, control plane, storage and external connectivity; BGP underlay with EVPN, VXLAN overlay, ACLs on the DPU |
| Scale-up awareness | **`CNP03`**: "For NVL72, the API **must** support NVLink domain-aware allocation." **`NET02`**: the API **shall** return the NVLink domain identifier for each node (GB200, GB300, **Vera Rubin**) |
| Break-fix | "**NVLink must be reconfigured properly** to take a node out of the tenancy" |
| Security | **`SEC22`** TPM 2.0 hardware root of trust + UEFI Secure Boot, **mandatory across all platforms**; **`CNP09`** all firmware cryptographically signed and attested at boot, returned to a known-good state between tenants; **`SEC21`** cryptographic erase of data drives, sanitisation of persistent *and volatile* memory **including GPU memory**, TPM and BIOS reset; **`SEC12`** BMC on a dedicated isolated network; **`CNP10`** Redfish over TLS with **IPMI disabled**; **`SEC19`** SOC 2 Type 1 or better |
| Storage | **`DIR02`**: "**Must Be NFS Storage** — NVIDIA requires NFSv4 protocol shared storage to work"; **`HSS08`** must be able to allocate ≥1 PiB growing past 10 PiB |
| Operations | 99.99% availability on a 30-day rolling SLO; telemetry delivered with ≤120 s latency, OpenTelemetry preferred; benchmarking via `github.com/NVIDIA/dgxc-benchmarking` on a uniform cluster, results shared with NVIDIA |
| Process | API readiness and transport established **≥12 weeks before GPU delivery**; storage API integrated **8 weeks before**. **`CAP03`**: "It is **not acceptable** to have [capacity] be 'handed' to DGXC through a phone, slack or email message" |

**Explicitly left to the partner:**

- Bare metal *or* VMs (BMaaS or VMaaS both acceptable) — which is why Nebius can run
  KubeVirt all the way down and still be a Reference Platform NCP.
- IP addressing and inter-host routing (BGP as the protocol).
- Enforcement technology for edge security — **`SEC16`** merely requires the NCP to
  *specify* whether it uses hardware firewalls, SDN or DPUs/SmartNICs and where in the
  packet path.
- **`K8S25`**: "Provider-default accelerator operators and drivers **shall be replaceable or
  overridable**" — the tenant can override even NVIDIA's GPU Operator version.

NVIDIA also formally tiers its partners: **Reference Platform NCPs** are "select partners
who operate large clusters built in coordination with NVIDIA, and adhere to a tested and
optimized reference architecture" — Nebius and SoftBank Corp. are named `[C]`
(<https://www.nvidia.com/en-us/data-center/gpu-cloud-computing/partners/> ·
<https://nebius.com/>).

### 9.5 Rack and NVL configuration variation — and its limits

- **GB200 NVL72** is the canonical unit; **NVL36×2** exists as an air-cooled-friendlier
  variant; Microsoft built an early **32-GPU** Blackwell rack for cooling validation before
  standardising `[P]`.
- NVIDIA proposed **NVL72×2** — two Oberon racks back-to-back — as a copper alternative to
  Kyber. SemiAnalysis reports it was **cancelled after heavy pushback from CSPs and
  hyperscalers over its odd design and operational burden** `[P]`.
- **Kyber NVL144** reportedly **delayed to 2028** (from 2027) because a ~1 m², **78-layer**
  orthogonal backplane PCB with ≤25 µm traces cannot be yielded reliably at 448 Gb/s
  per-GPU signalling; **NVL576** delayed or low-volume because co-packaged optics is not
  ready; the 4-compute-die Rubin Ultra reportedly cancelled `[P]`.
  **NVIDIA has not confirmed any of this and says its roadmap is intact.**
  (<https://www.linkedin.com/posts/semianalysis_massive-delay-just-3-months-after-jensen-activity-7479640455542992896-U-pO>,
  6 July 2026 · <https://www.cnbctv18.com/technology/nvidia-kyber-nvl144-ai-server-rack-system-delayed-to-2028-what-we-know-19939290.htm>)

This sequence is the best available evidence of the **direction of influence**: NVIDIA
designs scale-up topologies, customers accept or reject them, and NVIDIA absorbs the
schedule risk. No customer in the dataset designed its own NVIDIA scale-up domain.

### 9.6 Current platform baseline (for deck accuracy)

- **Vera Rubin** described by NVIDIA as a multi-rack pod-scale system unifying five
  rack-scale systems: **Vera Rubin NVL72, a Vera CPU rack, Groq 3 LPX, Vera BlueField-4 STX,
  and Spectrum-6 SPX Ethernet** `[V]` (NVIDIA social post, 2026).
- Component set: Vera CPU (88 custom Armv9.2 "Olympus" cores), Rubin GPU, **NVLink 6**,
  **ConnectX-9 SuperNIC**, **BlueField-4 DPU**, **Spectrum-6 Ethernet switch** `[C]`
  NVIDIA earnings commentary; per-GPU figures (50 PFLOPS FP4, 288 GB HBM4) are `[V]`
  (<https://www.techpowerup.com/346786/nvidia-ships-first-vera-rubin-vr200-samples-to-customers>).
- CFO Colette Kress: first Vera Rubin samples shipped to customers; production shipments on
  track for **H2**; "Rubin will deliver improved resiliency and serviceability relative to
  Blackwell" via a **modular, cable-free tray design**; "**We expect every cloud model
  builder to deploy Vera Rubin**" `[C]`.
- **Spectrum-X co-packaged optical switch** announced at GTC 2026 as the industry's first
  in production, developed with TSMC `[V]`
  (<https://www.datacenterfrontier.com/machine-learning/news/55364406/jensen-huang-maps-the-ai-factory-era-at-nvidia-gtc-2026>).
- **Disaggregated inference with Groq**: Rubin systems execute model computation, Groq
  accelerators handle token generation, orchestrated by NVIDIA Dynamo; "up to 35×" for
  certain inference workloads `[V]`.

### 9.7 Commercial scale of the networking business

NVIDIA Q4 FY2026 earnings call, 25 February 2026 `[C]`
(<https://s201.q4cdn.com/141608511/files/doc_financials/2026/q4/NVDA-Q4-2026-Earnings-Call-25-February-2026-5_00-PM-ET.pdf>):

- **Networking revenue $11B in Q4**, up more than **3.5× YoY**.
- **Full-year networking exceeded $31B**, up more than **10×** versus fiscal 2021 (the
  Mellanox acquisition year).
- **Grace Blackwell systems were roughly two-thirds of data-centre revenue** in the quarter.
- Spectrum-X annualised run rate: **~$10B in H1 FY2026**, stepping to **~$11–12B in H2**
  (the latter framed by a JPMorgan analyst and not disputed).
- Huang: "**Ethernet has been a home run for us.**"

Huang's economic argument for why customers accept NVIDIA networking `[V]`, Q2 FY2026 call:

> "The performance, the throughput improvement going from 65% to 85% or 90% — that kind of
> step up because of your networking capability effectively **makes networking free**...
> the AI factory could be $50 billion. And so the ability to improve the efficiency of that
> factory by tens of percent in results is $1 or $2 trillion dollars' worth of effective benefit."

### 9.8 What NVIDIA refuses to customize — consolidated

| Refusal | Evidence |
| --- | --- |
| **Per-customer silicon** | No instance found. All differentiated parts are jurisdictional (§8) and subtractive. Huang: ASICs "don't make sense"; NVIDIA spends ~$20B/yr on R&D rising toward $45B, with ~45,000 people on AI and computing — a barrier he names explicitly `[P]` DigiTimes via Yahoo Finance |
| **Multiple architectures** | "The fact that we are singularly focused and completely dedicated to this one architecture... allows everybody to trust us... nobody's going to be able to support five architectures forever" `[C]` |
| **The back-end fabric, where NVIDIA has leverage** | `NET-2` MUST be InfiniBand or Spectrum-X for DGX Cloud capacity `[C]` |
| **The scale-up domain** | NVL72/NVL144 fixed; NVLink-domain-aware allocation mandated by API; NVL72×2 was NVIDIA's own proposal, withdrawn after customer rejection `[C]`/`[P]` |
| **The trust and control plane** | BlueField DPU north-south plane, TPM 2.0, Secure Boot, signed+attested firmware, IPMI disabled `[C]` |
| **The software contract** | CUDA; `dgxc-benchmarking` results shared with NVIDIA; programmatic capacity discovery mandatory `[C]` |

| Concession | Evidence |
| --- | --- |
| Rack mechanicals, cooling, power | Azure Callan/Sidekick, closed-loop glycol, facility-water *or* air-cooled `[C]` |
| In-rack offload/security silicon | Azure Boost, Azure Integrated HSM, DC-SCM inside NVL72 `[C]` |
| CPU socket | MGX HPMs; NVLink Fusion with Fujitsu, Qualcomm `[C]` |
| Switch *system* while keeping the *ASIC* | Meta Minipack3N `[C]` |
| Scale-out NIC | Oracle Acceleron, AWS Nitro/EFA `[C]` |
| Scale-out switching | AWS, Google, Meta all keep their own `[C]` |
| Accelerator co-existence | AWS Trainium4 on NVLink 6 + MGX `[C]` |
| Facility and grid design | DSX reference design, Omniverse DSX twins `[C]` |
| Provisioning model | BMaaS or VMaaS; tenant may override NVIDIA's own GPU Operator `[C]` |

---

## 10. What I could not verify

Items a deck should either drop or explicitly label as unconfirmed.

1. **NVIDIA's 10-Q OpenAI risk-factor language.** Quoted by secondary press
   (`gadgetbond.com`) but not read against the filing itself.
2. **Huang's "probably not in the cards" remark** (Morgan Stanley TMT, 4 Mar 2026). Found
   only in a single Substack citing CNBC. No CNBC article or transcript located.
3. **The Abilene 600 MW cancellation.** Reported by several outlets; **Oracle publicly
   denied it**. Unresolved.
4. **Colossus 2 fabric.** No primary source confirms which NVIDIA fabric generation
   Colossus 2 uses. Do not assume Spectrum-X continuity.
5. **All Colossus GPU counts after Colossus 1.** Musk's X post is the sole source; no
   independent infrastructure verification exists. Musk himself hedged the December tranche.
6. **xAI folded into SpaceX; Colossus 1 rented to Anthropic and Google.** Weak aggregator
   sourcing only.
7. **Trainium4 NVLink specifics** — "72 ASICs, 3.6 TB/s per chip, 260 TB/s total" and the
   "every NVLink Fusion deployment must include at least one NVIDIA product" requirement.
   Neither appears in NVIDIA or AWS primary materials.
8. **Trainium4 availability date.** NVIDIA and AWS gave none; "late 2026 / early 2027"
   appears only in secondary analysis. Reuters explicitly noted no date was specified.
9. **B30A/B40 specifications, naming, and pricing.** Published estimates contradict each
   other (7.5 PFLOPS FP4 by halving B300 vs 3.5 PFLOPS by halving B100); the effort has been
   called RTX Pro 6000D, B40, B30 and B30A. NVIDIA neither confirms nor denies. **No number
   here is safe to publish.**
10. **The January 2026 BIS thresholds** (21,000 TPP / 6,500 GB/s DRAM bandwidth; 50% volume
    cap) and the **14 January 2026 proclamation**. Sourced to Lawfare and a vendor blog, not
    to a Federal Register notice. Verify against the primary rule before citing.
11. **Meta's 2026 capex.** Sources give $115–135B and "up to $145B." The $145B figure traces
    to a Reuters-reviewed internal memo; the others to company guidance ranges. They may
    measure different things.
12. **The claim that Meta's Spectrum-X decision was "the technology that convinced Meta to
    choose Ethernet over InfiniBand."** Meta's own SIGCOMM 2024 paper shows it chose RoCE
    *before* Spectrum-X existed, for open-standards reasons. The causal claim is wrong;
    the Spectrum-4 ASIC purchase is a later, narrower fact.
13. **Kyber NVL144 / NVL576 delays and the Rubin Ultra die-count cancellation.** Single
    analyst source (SemiAnalysis); NVIDIA has not confirmed and says the roadmap is intact.
14. **Tesla Dojo3 as a space-based, NVIDIA-free AI7 system.** Bloomberg confirms only that
    Musk said work would resume. The space/AI7/no-NVIDIA characterisation is unsourced.
15. **Stargate per-site capacities** other than Abilene. The site tables circulating online
    come largely from AI-generated content farms and disagree with each other.
16. **"$50 billion" value of the NVIDIA–Meta February 2026 deal.** A single analyst
    estimate (Ben Bajarin, Creative Strategies) relayed by Reuters/CNBC. Neither company
    disclosed a value.
17. **Which ten Chinese firms** received H200 clearance. Reuters names four (Alibaba,
    Tencent, ByteDance, JD.com) of approximately ten.
18. **The exact Spectrum-X H2 FY2026 run rate.** The $11–12B figure was put to NVIDIA by a
    JPMorgan analyst and not explicitly confirmed by management. Only the ">$10B in H1"
    figure is stated by the CFO.

---

## 11. Source-quality appendix

**Primary and reliable** — SEC EDGAR filings; `nvidianews.nvidia.com`;
`investor.nvidia.com`; NVIDIA earnings-call transcripts on the IR site; `docs.nvidia.com`;
`openai.com`; `about.fb.com`; `engineering.fb.com`; `ai.meta.com`; `blogs.microsoft.com`;
`news.microsoft.com`; `azure.microsoft.com`; `techcommunity.microsoft.com`; `oracle.com`
and `blogs.oracle.com`; `coreweave.com` and `investors.coreweave.com`; `crusoe.ai`;
`aws.amazon.com/blogs/hpc`; `github.com/amzn/amzn-drivers`; `cloud.google.com/blog`;
`usenix.org`; `dl.acm.org`; Reuters; Bloomberg; Financial Times; CNBC; SCMP;
`democrats-selectcommitteeontheccp.house.gov`.

**Credible secondary / analyst** — SemiAnalysis, Epoch AI, The Register, ServeTheHome,
Data Center Dynamics, Data Center Frontier, Data Center Knowledge, Tom's Hardware,
SDxCentral, HPCwire/AIwire, TechCrunch, The Verge, Lawfare, glennklockwood.com.

**Used with caution** — `saturncloud.io` (fabric comparison table, plausible but
uncorroborated); `hidekazu-konishi.com` (quotes AWS docs directly, so the quotes are
checkable); `ourcoders.com` (Computex transcript hosted on a third-party site);
`techpowerup.com` (relays earnings-call quotes).

**Excluded as unreliable** — `kovastack.ai`, `presenc.ai`, `resources.rework.com`,
`tech-insider.org`, `firstpasslab.com`, `flopper.io`, `willitrunai.com`, `spheron.network`,
`aiweekly.co`, `aiindustrytoday.com`, `finance.biggo.com`, `gate.com`, `introl.com`,
`theaitrack.com`, `pub.towardsai.net`. These are AI-generated or SEO-farm content. Several
returned specific, confident, mutually contradictory numbers. Anything appearing **only** in
these sources has been omitted or explicitly flagged.
