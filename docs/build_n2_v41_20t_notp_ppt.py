#!/usr/bin/env python3
"""N+2 20T V4.1 with TP removed, and a two-level DDR pool.

Hardware matches the no-TP V4 deck: parameter plane 1.6 Tb/s, D2D
57.6 Tb/s per GPU, Prefill 64 cards, Decode 256 cards, TP=1.
The model is the V4.1-Flash skeleton extrapolated to 20T.

KV is 890 bytes per token. The sliding window and the indexer stay on
the GPU. Each decode step moves 5.16 MB: the 16384-entry candidate
pool plus three encoder Top-512 groups. Overflow of the main KV fills
the 51.2 Tb/s tier up to 9728 GB, then the unlimited 25.6 Tb/s tier.
The baseline is HBM plus 96 GB of host DDR per card at 160 GB/s.
"""

from __future__ import annotations

import importlib.util
import math

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches

spec = importlib.util.spec_from_file_location(
    "slo_ui", "/agent/repos/ucl-mpcomm/docs/build_deepseek_20t_slo_ppt.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

N = 256
TP = 1
DP = 256
EP = 256
PF_N = 64
PF_TP = 1
PF_DP = PF_N // PF_TP
PF_EP = PF_N
L, L_ENC = 40, 20
H, DFF, TOPK = 5120, 2304, 6
W_LAYER = 3 * H * DFF
W_ONE = W_LAYER * L
BACKBONE = 552e9
PUB_EXPERTS = 384
OTHER = BACKBONE - PUB_EXPERTS * W_ONE
E = math.ceil((2e13 - OTHER) / W_ONE)
TOTAL = E * W_ONE + OTHER
SHARED = float(W_ONE)
EMBED = 2 * 129280 * H
ATTN = OTHER - SHARED - EMBED
ACT_DEC = 7 * W_ONE + ATTN + 129280 * H
ACT_PF = 7 * W_LAYER * L_ENC + ATTN * (L_ENC / L) + 129280 * H
ROUTED = E * W_ONE * 0.5
RESERVE = 6e9
HBM_CAP = 640e9
HBM_BW = 33e12 * 0.80
PEAK = 48e15 * 0.70
D2D = 57.6e12 / 8 * 0.80
PARAM = 1.6e12 / 8 * 0.80
PREFIX_25 = 1.6e12 / 8 * 0.25
PREFIX_100 = 1.6e12 / 8
HOST = min(1.6e12 / 8 * 0.80, 2e12 * 0.80 / 8)
DDR_CAP = 96e9
POOL_51 = 51.2e12 / 8
POOL_26 = 25.6e12 / 8
POOL_51_TOTAL = 9728e9
POOL_51_CAP = POOL_51_TOTAL / N
COLL = 5e-6
ROOM_GPU = HBM_CAP - ROUTED / EP - SHARED - ATTN / TP - RESERVE
PF_ROOM = HBM_CAP - ROUTED / PF_EP - SHARED - ATTN / PF_TP - RESERVE

MAIN, INDEX = 288, 68
BPT = 890
WIN, SWA_B = 128, 512
FIXED = L * WIN * SWA_B
INDEX_FLOP = 2 * 32 * 128
CORE_FLOP = 2 * 2 * 64 * 512
POOL_POS = 2048 * 8
STEP = 3 * 512 * MAIN + POOL_POS * MAIN
HIT = 0.995
LENGTHS = (65536, 131072, 262144, 524288, 1048576, 2097152, 4194304)

SLIDES = 8
FOOTER = "N+2    ·    V4.1 外扩 20T    ·    Prefill 64 卡 TP=1    ·    Decode DP=256 EP=256    ·    参数面 1.6 Tb/s    ·    无 fullmesh"
PPT = "/agent/repos/ucl-mpcomm/docs/N+2-20T-V4.1-无TP.pptx"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY, TEAL = ui.NAVY, ui.TEAL


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def pool_pos(s):
    return min(float(s), POOL_POS)


def index_seq(s):
    return 2.5 * s * INDEX + FIXED


def main_seq(s):
    return 2.5 * s * MAIN


def store_seq(s):
    return s * BPT + FIXED


def offload_bytes(s):
    enc = 3 * min(512.0, s / 2.0) * MAIN
    return enc + pool_pos(s) * MAIN


def index_read(s):
    return index_seq(s) + 4 * pool_pos(s) * INDEX


def score_flops(s):
    sel_e = min(512.0, s / 2.0)
    sel_d = min(512.0, float(s))
    idx = 3 * (s / 2.0) * INDEX_FLOP + s * INDEX_FLOP + 4 * pool_pos(s) * INDEX_FLOP
    core = (18 * (sel_e + WIN) + 20 * (sel_d + WIN) + 2 * WIN) * CORE_FLOP
    return idx + core


def expert(tokens, ngpu, layers):
    tokens = max(float(tokens), 0.0)
    mean = tokens * TOPK / ngpu
    hot = min(tokens * TOPK, mean + 2 * math.sqrt(max(mean * (1 - 1 / ngpu), 0.0)))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / ngpu
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_rows = e_hot * math.ceil(tpe / 16) * 16 if e_hot else 0.0
    shared_rows = math.ceil(max(1, math.ceil(tokens / ngpu)) / 16) * 16
    tw = (e_hot * W_LAYER * layers * 0.5 + W_LAYER * layers) / HBM_BW
    tg = (routed_rows + shared_rows) * 6 * H * DFF * layers / PEAK
    td = layers * (COLL + hot * H * 1 / D2D)
    tc = layers * (COLL + hot * H * 2 / D2D)
    return {"t": td + max(tw, tg) + tc, "tw": tw, "tg": tg, "td": td, "tc": tc}


def prefill(bs, s, bw, hit=HIT):
    n = math.ceil(bs / PF_DP)
    if n * store_seq(s) > PF_ROOM + 1.0:
        return None
    p, q = hit * s, (1 - hit) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    idx = 3 * INDEX_FLOP * (context / 2.0)
    sel = min(512.0, s / 2.0)
    core = 18 * CORE_FLOP * (sel + WIN) * q + 2 * CORE_FLOP * WIN * q
    proj = 2 * ATTN * (L_ENC / L) * q
    t_compute = n * (idx + core + proj) / (PEAK * align(rows))
    t_pull = n * (p * BPT) / bw
    t_hbm = (ATTN + n * (store_seq(s) + q * BPT)) / HBM_BW
    moe = expert(bs * q, PF_N, L_ENC)
    body = t_pull + max(t_hbm, t_compute) + moe["t"]
    t_pd = n * store_seq(s) / PARAM
    tail = max(0.0, t_pd - body * (L_ENC - 1) / L_ENC)
    return {
        "t": body + tail,
        "pull": t_pull,
        "hbm": t_hbm,
        "compute": t_compute,
        "moe": moe["t"],
        "tail": tail,
        "n": n,
        "kv": n * store_seq(s),
    }


def _place(bs, s):
    n = math.ceil(bs / DP)
    idx = n * index_seq(s)
    main = n * main_seq(s)
    if idx > ROOM_GPU + 1.0 or main <= 0:
        return None
    overflow = max(main - (ROOM_GPU - idx), 0.0)
    return n, main, overflow


def _time(bs, s, n, main, overflow, parts):
    moved = offload_bytes(s)
    spill = overflow / main if main else 0.0
    t_swap = 0.0
    if main:
        for part, bw in parts:
            t_swap += n * moved * (part / main) / bw
    resident = (1.0 - spill) * moved
    t_hbm = (n * (index_read(s) + resident) + ATTN) / HBM_BW
    t_ca = n * (score_flops(s) + 2 * ATTN) / (PEAK * align(n))
    moe = expert(float(bs), N, L)
    return {
        "t": t_swap + max(t_hbm, t_ca) + moe["t"],
        "swap": t_swap,
        "hbm": t_hbm,
        "ca": t_ca,
        "td": moe["td"],
        "tw": moe["tw"],
        "tg": moe["tg"],
        "tc": moe["tc"],
        "n": n,
        "ddr": overflow,
    }


def decode_host(bs, s):
    placed = _place(bs, s)
    if placed is None:
        return None
    n, main, overflow = placed
    if overflow > DDR_CAP + 1.0:
        return None
    return _time(bs, s, n, main, overflow, [(overflow, HOST)] if overflow else [])


def decode_tier(bs, s):
    placed = _place(bs, s)
    if placed is None:
        return None
    n, main, overflow = placed
    tier1 = min(overflow, POOL_51_CAP)
    tier2 = overflow - tier1
    parts = []
    if tier1:
        parts.append((tier1, POOL_51))
    if tier2:
        parts.append((tier2, POOL_26))
    row = _time(bs, s, n, main, overflow, parts)
    row["tier1"] = tier1 * N
    row["tier2"] = tier2 * N
    return row


def search(limit, fn):
    if fn(1) is None or fn(1)["t"] > limit + 1e-9:
        return 0, fn(1)
    lo, hi = 1, 2
    while hi < 8_000_000:
        row = fn(hi)
        if row is None or row["t"] > limit + 1e-9:
            break
        lo, hi = hi, hi * 2
    else:
        return hi, fn(hi)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        row = fn(mid)
        if row is not None and row["t"] <= limit + 1e-9:
            lo = mid
        else:
            hi = mid
    return lo, fn(lo)


def max_prefill_s(hit):
    lo, hi = 1.0, 512e6
    for _ in range(48):
        mid = (lo + hi) / 2
        row = prefill(1, mid, PREFIX_25, hit)
        if row is None or row["t"] > 10.0:
            hi = mid
        else:
            lo = mid
    return int(math.floor(lo))


def max_decode_s(limit):
    lo, hi = 1024.0, 2e10
    for _ in range(52):
        mid = (lo + hi) / 2
        row = decode_host(1, mid)
        if row is not None and row["t"] <= limit:
            lo = mid
        else:
            hi = mid
    return int(math.floor(lo))


def collect():
    rows = []
    for s in LENGTHS:
        item = {"S": s}
        for key, bw in (("p25", PREFIX_25), ("p100", PREFIX_100)):
            bs, row = search(10.0, lambda b, bw=bw, s=s: prefill(b, s, bw))
            item[key] = {"bs": bs, "row": row}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            bs, row = search(limit, lambda b, s=s: decode_host(b, s))
            item[f"h2d{tag}"] = bs
            item[f"dh2d{tag}"] = row
            bs, row = search(limit, lambda b, s=s: decode_tier(b, s))
            item[f"tier{tag}"] = bs
            item[f"dtier{tag}"] = row
        rows.append(item)
    return {
        "rows": rows,
        "cold_s": max_prefill_s(0.0),
        "hit_s": max_prefill_s(HIT),
        "dec_cap_s": (cap_s := max_decode_s(0.010)),
        "dec_cap_t": decode_host(1, cap_s)["t"],
        "cold4": prefill(1, 4194304, PREFIX_25, 0.0)["t"],
    }


def fmt_len(s):
    return f"{s // 1048576}M" if s >= 1048576 else f"{s // 1024}K"


def fmt_bs(n):
    return f"{int(n):,}"


def fmt_rate(v):
    if v >= 1e8:
        return f"{v / 1e8:.2f} 亿"
    x = v / 1e4
    if x >= 100:
        return f"{x:.0f} 万"
    if x >= 10:
        return f"{x:.1f} 万"
    return f"{x:.2f} 万"


def signed_pct(new, old):
    if not old:
        return "—"
    return f"{(new / old - 1) * 100:+.1f}%"


def sec(v):
    return f"{v:.2f} 秒"


def ms(v):
    if v >= 0.1:
        return f"{v:.2f} 秒"
    return f"{v * 1e3:.1f} 毫秒"


def ms2(v):
    return f"{v * 1e3:.2f}"


def mem_total(n):
    if n < 1.0:
        return "0 GB"
    if n < 10e12:
        return f"{n / 1e9:,.0f} GB"
    return f"{n / 1e12:.2f} TB"


def tps_p(bs, s, row):
    return bs * s / row["t"]


def tps_d(bs, row):
    return bs / row["t"]


def stage_cell(part, total):
    shown = sec(part) if part >= 0.1 else ms(part)
    return f"{shown}  {part / total * 100:.1f}%"


def slide_open(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "64K 到 4M 都能对上两组目标", "V4.1 外扩 20T    ·    Prefill 64 卡    ·    基线拉 KV 50 GB/s")
    ui.banner(slide, 0.92, "一组目标是 TTFT ≤ 10 秒且 TPOT ≤ 10 毫秒。另一组把 TPOT 放宽到 30 毫秒。Decode 基线是 HBM 加每卡主机 96 GB。")
    r64, r4 = data["rows"][0], data["rows"][-1]
    head = ["约束", "64K 全局批", "64K 系统 TPS", "4M 全局批", "4M 系统 TPS", "4M 实际耗时"]
    body = [
        ["TTFT ≤ 10 秒", fmt_bs(r64["p25"]["bs"]), fmt_rate(tps_p(r64["p25"]["bs"], r64["S"], r64["p25"]["row"])), fmt_bs(r4["p25"]["bs"]), fmt_rate(tps_p(r4["p25"]["bs"], r4["S"], r4["p25"]["row"])), sec(r4["p25"]["row"]["t"])],
        ["TPOT ≤ 10 毫秒", fmt_bs(r64["h2d10"]), fmt_rate(tps_d(r64["h2d10"], r64["dh2d10"])), fmt_bs(r4["h2d10"]), fmt_rate(tps_d(r4["h2d10"], r4["dh2d10"])), ms(r4["dh2d10"]["t"])],
        ["TPOT ≤ 30 毫秒", fmt_bs(r64["h2d30"]), fmt_rate(tps_d(r64["h2d30"], r64["dh2d30"])), fmt_bs(r4["h2d30"]), fmt_rate(tps_d(r4["h2d30"], r4["dh2d30"])), ms(r4["dh2d30"]["t"])],
    ]
    ui.add_table(slide, 0.42, 1.50, [2.20, 1.90, 2.15, 1.90, 2.15, 2.20], [head] + body, [0.40, 0.48, 0.48, 0.48], ["head", "key", "body", "body"], size=14)
    ui.gold(
        slide,
        3.55,
        3.20,
        f"冷请求不拉 prefix。单条冷请求摸到 10 秒的输入是 {data['cold_s']:,}。4M 冷请求 TTFT {sec(data['cold4'])}。\n"
        f"99.5% 命中的单条请求可以到 {data['hit_s']:,}。批量摸高仍看 64K 到 4M 这七档。\n"
        f"单条 Decode 在输入 {data['dec_cap_s']:,} 时先顶到每卡主机 96 GB，TPOT {ms2(data['dec_cap_t'])} 毫秒，到不了 10 毫秒。\n"
        "系统 Prefill TPS = 全局批 × 输入长度 / 实际 TTFT。系统 Decode TPS = 全局批 / 实际 TPOT。两级池的对照在第 7、8 页。",
        14,
    )


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "层数和隐藏不动，路由专家加到 14123", "V4.1-Flash 552B    ·    外推到 20T    ·    Engram 不进这 20T")
    ui.banner(slide, 0.92, "CED：Prefill 走编码器 20 层。CSA2 的 Full 在 2、8、14、20，Reindex 在 24、28、32、36。TopK 仍是 6。")
    head = ["项目", "V4.1-Flash 论文", "20T 外推"]
    body = [
        ["骨干参数", "5.52×10^11", f"{TOTAL/1e12:.4f}×10^12"],
        ["路由专家", "384，中间维 2304", f"{E}，中间维仍 2304"],
        ["层 / 隐藏", "40 层，d = 5120", "保持 40 / 5120"],
        ["编码器 / 解码器", "20 + 20", "切分不动，解码 KV 由编码器投影"],
        ["每 token 激活", "Prefill 8B，Decode 16B", f"{ACT_PF/1e9:.2f}B / {ACT_DEC/1e9:.2f}B"],
        ["CSA2", "Full 4，Reindex 4，Reuse 其余", "压缩比：编码器 2，解码器 1"],
        ["注意力 Top-K / 滑窗", "512 / 128", "保持 512 / 128"],
        ["Engram", "196B，放在主机", "不计入 20T，不占 GPU HBM"],
    ]
    kinds = ["head"] + ["key" if i in (1, 5) else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.46, [2.55, 4.85, 5.10], [head] + body, [0.30] + [0.42] * 8, kinds, size=13)
    ui.gold(
        slide,
        5.30,
        1.55,
        f"E = ceil((2×10^13 − {OTHER/1e9:.3f}×10^9) / {W_ONE/1e9:.3f}×10^9) = {E}。单个专家 = 3×5120×2304×40 = {W_ONE/1e9:.3f}×10^9。\n"
        f"全局 KV = 890×S + 2,621,440。4M 一条 {store_seq(4194304)/1e9:.2f} GB。TP=1，这条 KV 整段落在一张卡上。\n"
        "索引和滑窗留在 GPU。每步卸载是候选池 4.72 MB 加编码器三组 Top-512 共 0.44 MB，合计 5.16 MB。",
        14,
    )


def slide_split(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "Prefill 用 64 卡，Decode 用满 256 卡", "两边都是 TP=1    ·    每卡批摸高不再随卡数上升")
    ui.banner(slide, 0.92, "机内 fullmesh 取消。TP 大于 1 就要在 D2D 上做 AllReduce，每卡批不增加，所以两边都取 TP=1。")
    head = ["", "Prefill", "Decode"]
    body = [
        ["规模", "64 卡，8 个 8 卡节点", "256 卡，整份超节点"],
        ["切分", "TP=1，DP=64，EP=64", "TP=1，DP=256，EP=256"],
        ["每卡路由专家", f"{ROUTED/PF_EP/1e9:.1f} GB，{E/PF_EP:.1f} 个", f"{ROUTED/EP/1e9:.1f} GB，{E/EP:.1f} 个"],
        ["每卡注意力", f"{ATTN/1e9:.2f} GB，不再按 TP 切开", f"{ATTN/1e9:.2f} GB，同样不切开"],
        ["KV 房间", f"{PF_ROOM/1e9:.1f} GB", f"{ROOM_GPU/1e9:.1f} GB"],
        ["寻优目标", "TTFT ≤ 10 秒下的每卡批", "TPOT ≤ 10 / 30 毫秒下的全局批"],
    ]
    kinds = ["head"] + ["key" if i in (0, 1) else "body" for i in range(6)]
    ui.add_table(slide, 0.42, 1.48, [2.20, 5.15, 5.15], [head] + body, [0.34] + [0.48] * 6, kinds, size=14)
    n64 = data["rows"][0]["p25"]["row"]["n"]
    kv64 = data["rows"][0]["p25"]["row"]["kv"] / 1e9
    ui.gold(
        slide,
        5.00,
        1.85,
        f"Prefill 固定 64 卡。64K 基线是每卡 {fmt_bs(n64)} 条，每卡 KV {kv64:.0f} GB，房间 {PF_ROOM/1e9:.0f} GB 放得下。\n"
        f"Decode 每卡 KV 房间 {ROOM_GPU/1e9:.1f} GB。索引必须整段留在这间房间里，主 KV 装不下的部分才进主机或两级池。\n"
        f"专家表 {ROUTED/1e12:.3f} TB。EP 降到 16 时单是路由专家就有 {ROUTED/16/1e9:.0f} GB，KV 没有地方放，所以 Decode 维持 EP=256。",
        14,
    )


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "TTFT 与 TPOT", "没有 AllReduce    ·    n 是一张卡上的条数")
    ui.banner(slide, 0.92, "Prefill 的 n = ceil(全局批 / 64)。Decode 的 n = ceil(全局批 / 256)。注意力由这一张卡承担。")
    room = f"{ROOM_GPU/1e9:.1f}"
    panels = (
        (
            0.36,
            "TTFT    ·    Prefill 64 卡",
            [
                ["n", "ceil(全局批 / 64)"],
                ["命中", "p = 0.995 S，q = 0.005 S"],
                ["拉 KV", "n × p × 890 / BW"],
                ["带宽", "基线 50 GB/s，NEW 200 GB/s"],
                ["计算", "编码器 20 层。n × F / (33.60 P × align(n×q))"],
                ["HBM", f"({ATTN/1e9:.2f} GB + n×(K(S) + q×890)) / 26.40 TB/s"],
                ["MoE", "20 层的 dispatch + max(权重, GEMM) + combine"],
                ["尾部", "max(0, n×K(S) / 160 GB/s − 主体×19/20)"],
                ["TTFT", "拉 KV + max(HBM, 计算) + MoE + 尾部"],
            ],
        ),
        (
            6.86,
            "TPOT    ·    Decode 256 卡",
            [
                ["n", "ceil(全局批 / 256)"],
                ["存量", "索引 2.5×S×68 + 滑窗留在 GPU\n主 KV = 2.5×S×288"],
                ["溢出", f"max(n×主KV − ({room} GB − n×索引), 0)"],
                ["换入", "溢出 / 主KV × n × 5.16 MB / BW"],
                ["带宽", "基线 H2D 160 GB/s，每卡 96 GB\n1 级 6.40 TB/s，总计 9728 GB\n2 级 3.20 TB/s，容量不限"],
                ["HBM", "索引全文 + 留在 GPU 的那截 5.16 MB"],
                ["计算", "n × (F_score + 2×注意力) / (33.60 P × align(n))"],
                ["MoE", "40 层 dispatch / combine，D2D 5.76 TB/s"],
                ["TPOT", "换入 + max(HBM, 计算) + MoE"],
            ],
        ),
    )
    for x, title, rows in panels:
        ui.textbox(slide, x, 1.42, 6.10, 0.28, title, 16, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
        kinds = ["head"] + ["key" if i == len(rows) - 1 else "body" for i in range(len(rows))]
        heights = [0.28]
        for label, _text in rows:
            if label == "带宽" and x > 6:
                heights.append(0.78)
            elif label in ("存量", "带宽"):
                heights.append(0.58)
            else:
                heights.append(0.40)
        ui.add_table(slide, x, 1.72, [1.05, 5.05], [["项", "公式"]] + rows, heights, kinds, size=11)


def slide_cmp(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "基线对 NEW：都按 10 秒摸高", "64 卡 Prefill    ·    基线 50 GB/s    ·    NEW 200 GB/s")
    tails = [row[key]["row"]["tail"] for row in data["rows"] for key in ("p25", "p100")]
    tail_note = "尾部是 0。" if max(tails) < 1e-6 else "尾部是 P→D 没被主体盖住的那一截。"
    ui.banner(slide, 0.90, f"批只受 TTFT ≤ 10 秒和每卡 {PF_ROOM/1e9:.0f} GB 房间约束。提升是 NEW 的系统 TPS 相对基线。{tail_note}", size=12)
    head = ["输入", "方案", "每卡批", "系统 TPS", "提升", "TTFT", "拉 KV", "计算", "HBM", "MoE"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        base = tps_p(row["p25"]["bs"], row["S"], row["p25"]["row"])
        for key, name in (("p25", "基线"), ("p100", "NEW")):
            item = row[key]
            r = item["row"]
            rate = tps_p(item["bs"], row["S"], r)
            kinds.append("key" if name == "NEW" else "body")
            body.append([
                fmt_len(row["S"]),
                name,
                fmt_bs(r["n"]),
                fmt_rate(rate),
                "—" if name == "基线" else signed_pct(rate, base),
                sec(r["t"]),
                stage_cell(r["pull"], r["t"]),
                stage_cell(r["compute"], r["t"]),
                stage_cell(r["hbm"], r["t"]),
                stage_cell(r["moe"], r["t"]),
            ])
    ui.add_table(
        slide, 0.28, 1.42,
        [0.72, 0.68, 0.78, 1.12, 0.88, 0.86, 1.78, 1.68, 1.48, 1.62],
        [head] + body,
        [0.32] + [0.36] * len(body),
        kinds,
        size=10,
    )


def slide_decode(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "Decode 基线：HBM 加每卡主机 96 GB", "换入 160 GB/s    ·    每步搬走的是 5.16 MB 里的溢出比例")
    ui.banner(
        slide,
        0.90,
        "耗时单位毫秒。TPOT = 换入 + max(HBM, 计算) + 派发 + max(权重, GEMM) + 合并。索引和滑窗留在 GPU，不进主机。",
        size=12,
    )
    head = ["输入", "约束", "批", "换入", "HBM", "计算", "派发", "权重", "GEMM", "合并", "TPOT"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        for tag, label in (("10", "10 毫秒"), ("30", "30 毫秒")):
            r = row[f"dh2d{tag}"]
            kinds.append("key" if tag == "30" and row["S"] in (65536, 4194304) else "body")
            body.append([
                fmt_len(row["S"]),
                label,
                fmt_bs(row[f"h2d{tag}"]),
                ms2(r["swap"]),
                ms2(r["hbm"]),
                ms2(r["ca"]),
                ms2(r["td"]),
                ms2(r["tw"]),
                ms2(r["tg"]),
                ms2(r["tc"]),
                ms2(r["t"]),
            ])
    ui.add_table(
        slide, 0.28, 1.42,
        [0.82, 1.08, 1.32, 1.18, 1.15, 1.15, 1.15, 1.18, 1.15, 1.15, 1.28],
        [head] + body,
        [0.30] + [0.36] * len(body),
        kinds,
        size=11,
    )


def slide_tier(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, "1 级 51.2 Tb/s · 合计 9728 GB    ·    2 级 25.6 Tb/s · 容量不限")
    legend = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.32), Inches(0.92), Inches(12.68), Inches(0.70))
    ui.solid(legend, ui.PALE)
    ui.textbox(
        slide, 0.46, 0.94, 12.40, 0.66,
        "主 KV 的溢出先填 1 级，256 卡合计最多 9728 GB，带宽 6.40 TB/s。剩下的进 2 级，带宽 3.20 TB/s。\n"
        "换入 = 5.16 MB × n × 1 级占比 / 6.40 TB/s + 5.16 MB × n × 2 级占比 / 3.20 TB/s。基线是 HBM 加每卡主机 96 GB、160 GB/s。总量是 256 卡相加。",
        12, True, TEAL, anchor=MSO_ANCHOR.MIDDLE,
    )
    head = ["输入", "基线批", "基线毫秒", "基线吞吐", "两级批", "两级毫秒", "1 级总量", "2 级总量", "两级吞吐", "相对基线"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        base = row[f"dh2d{tag}"]
        tier = row[f"dtier{tag}"]
        kinds.append("key" if row["S"] in (65536, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row[f"h2d{tag}"]),
            ms2(base["t"]),
            fmt_rate(tps_d(row[f"h2d{tag}"], base)),
            fmt_bs(row[f"tier{tag}"]),
            ms2(tier["t"]),
            mem_total(tier["tier1"]),
            mem_total(tier["tier2"]),
            fmt_rate(tps_d(row[f"tier{tag}"], tier)),
            signed_pct(tps_d(row[f"tier{tag}"], tier), tps_d(row[f"h2d{tag}"], base)),
        ])
    shape = ui.add_table(
        slide, 0.30, 1.74,
        [0.78, 1.40, 1.15, 1.25, 1.40, 1.15, 1.52, 1.52, 1.25, 1.28],
        [head] + body,
        [0.36] + [0.52] * len(body),
        kinds,
        size=12,
    )
    for cell in shape.table.iter_cells():
        cell.margin_top = Inches(0.02)
        cell.margin_bottom = Inches(0.02)
        cell.margin_left = Inches(0.05)
        cell.margin_right = Inches(0.04)
    r64, r4 = data["rows"][0], data["rows"][-1]
    full = [row for row in data["rows"] if row[f"dtier{tag}"]["tier1"] >= POOL_51_TOTAL - 1.0]
    if len(full) == len(data["rows"]):
        full_txt = "七档都把 1 级的 9728 GB 装满"
    elif full:
        full_txt = "1 级被装满的是 " + "、".join(fmt_len(row["S"]) for row in full)
    else:
        full_txt = "七档的 1 级都还有空位"
    ui.gold(
        slide,
        5.86,
        1.16,
        f"{full_txt}。64K 两级批 {fmt_bs(r64[f'tier{tag}'])}，"
        f"1 级 {mem_total(r64[f'dtier{tag}']['tier1'])}，2 级 {mem_total(r64[f'dtier{tag}']['tier2'])}，"
        f"吞吐相对基线 {signed_pct(tps_d(r64[f'tier{tag}'], r64[f'dtier{tag}']), tps_d(r64[f'h2d{tag}'], r64[f'dh2d{tag}']))}。\n"
        f"4M 两级批 {fmt_bs(r4[f'tier{tag}'])}，TPOT {ms2(r4[f'dtier{tag}']['t'])} 毫秒，"
        f"1 级 {mem_total(r4[f'dtier{tag}']['tier1'])}，2 级 {mem_total(r4[f'dtier{tag}']['tier2'])}，"
        f"吞吐相对基线 {signed_pct(tps_d(r4[f'tier{tag}'], r4[f'dtier{tag}']), tps_d(r4[f'h2d{tag}'], r4[f'dh2d{tag}']))}。",
        13,
    )


def audit(prs):
    wide, low = Inches(13.333), Inches(7.50)
    bad = []
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.left is None:
                continue
            if shape.left + shape.width > wide + Emu(40000) or shape.top + shape.height > low + Emu(40000):
                bad.append((i, int(shape.left), int(shape.top), int(shape.width), int(shape.height)))
    return bad


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2：20T V4.1，无 TP"
    blank = prs.slide_layouts[6]
    slide_open(prs, blank, data)
    slide_model(prs, blank)
    slide_split(prs, blank, data)
    slide_formula(prs, blank)
    slide_cmp(prs, blank, data)
    slide_decode(prs, blank, data)
    slide_tier(prs, blank, data, 7, "10", "10 毫秒：两级池摸高，对照 HBM 加主机")
    slide_tier(prs, blank, data, 8, "30", "30 毫秒：两级池摸高，对照 HBM 加主机")
    prs.save(PPT)
    print("slides", len(prs.slides), "overflow", audit(prs))
    print("room", f"{ROOM_GPU/1e9:.2f}", "pf", f"{PF_ROOM/1e9:.2f}", "attn", f"{ATTN/1e9:.3f}", "E", E)
    print("cold", data["cold_s"], "hit", data["hit_s"], "dec_cap", data["dec_cap_s"], f"{data['dec_cap_t']*1e3:.2f}", "cold4", f"{data['cold4']:.3f}")
    for row in data["rows"]:
        print(
            fmt_len(row["S"]),
            "pf", row["p25"]["bs"], row["p100"]["bs"],
            "h2d", row["h2d10"], row["h2d30"],
            "tier", row["tier10"], row["tier30"],
            mem_total(row["dtier10"]["tier1"]), mem_total(row["dtier10"]["tier2"]),
            mem_total(row["dtier30"]["tier1"]), mem_total(row["dtier30"]["tier2"]),
            "swap10", f"{row['dtier10']['swap']*1e3:.3f}",
            "swap30", f"{row['dtier30']['swap']*1e3:.3f}",
        )


if __name__ == "__main__":
    main()
