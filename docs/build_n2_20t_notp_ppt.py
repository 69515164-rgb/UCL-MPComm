#!/usr/bin/env python3
"""N+2 20T V4 with TP removed.

Parameter plane is 1.6 Tb/s. D2D is 57.6 Tb/s per GPU into the switch,
256 GPUs, no intra-node full mesh. Attention is DP=256, EP=256, TP=1.
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
# Prefill replica: smallest 8-GPU-aligned size whose baseline per-card
# batch still fits. Per-card batch stops rising once N >= 24 and TP = 1.
PF_N = 56
PF_TP = 1
PF_DP = PF_N // PF_TP
PF_EP = PF_N
L, H, DFF, TOPK = 61, 7168, 3072, 6
N_CSA, N_HCA = 30, 31
W_ONE = 3 * H * DFF * L
OTHER = 1_600_000_000_000 - 384 * W_ONE
E = math.ceil((2e13 - OTHER) / W_ONE)
TOTAL = E * W_ONE + OTHER
ATTN = 19.35e9
SHARED = float(W_ONE)
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
COLL = 5e-6
ROOM_GPU = HBM_CAP - ROUTED / EP - SHARED - ATTN / TP - RESERVE
ROOM = N * ROOM_GPU
PF_ROOM = HBM_CAP - ROUTED / PF_EP - SHARED - ATTN / PF_TP - RESERVE
BPT = N_CSA * (576 / 4 + 64 / 4) + N_HCA * (576 / 128)
FIXED = L * 128 * 576
PROJ = ATTN * 2
HIT = 0.995
LENGTHS = (65536, 131072, 262144, 524288, 1048576, 2097152, 4194304)
PIE_LENGTHS = (65536, 262144, 1048576, 4194304)

SLIDES = 9
FOOTER = "N+2    ·    20T    ·    Prefill 56 卡 TP=1    ·    Decode DP=256 EP=256    ·    参数面 1.6 Tb/s    ·    无 fullmesh"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY, TEAL, INK = ui.NAVY, ui.TEAL, ui.INK
PPT = "/agent/repos/ucl-mpcomm/docs/N+2-20T-V4-无TP.pptx"
C_HBM = "1B4F8A"
C_DDR = "E07A3D"


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def store_seq(s):
    return s * BPT + FIXED


def n_read(s):
    sel = min(1024.0, s / 4.0)
    return N_CSA * (s / 4.0) * 64 + N_HCA * (s / 128.0) * 576 + N_CSA * sel * 576 + FIXED


def expert(tokens, ng=N):
    tokens = max(float(tokens), 0.0)
    mean = tokens * TOPK / ng
    hot = min(tokens * TOPK, mean + 2 * math.sqrt(max(mean * (1 - 1 / ng), 0.0)))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / ng
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_rows = e_hot * math.ceil(tpe / 16) * 16 if e_hot else 0.0
    shared_rows = math.ceil(max(1, math.ceil(tokens / ng)) / 16) * 16
    tw = (e_hot * W_ONE * 0.5 + SHARED) / HBM_BW
    tg = (routed_rows + shared_rows) * 6 * H * DFF * L / PEAK
    td = L * (COLL + hot * H * 1 / D2D)
    tc = L * (COLL + hot * H * 2 / D2D)
    return {"t": td + max(tw, tg) + tc, "tw": tw, "tg": tg, "td": td, "tc": tc}


def prefill(bs, s, bw, hit=HIT):
    n = math.ceil(bs / PF_DP)
    p, q = hit * s, (1 - hit) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    flops = (
        N_CSA * 4096 * context
        + N_HCA * 2048 * context
        + N_CSA * 262144 * (1024 + 128) * q
        + PROJ * q
    )
    t_compute = n * flops / (PEAK * align(rows))
    prefix_bytes = p * BPT + L * min(p, 128) * 576
    t_pull = n * prefix_bytes / bw
    t_hbm = (ATTN + n * (store_seq(s) + q * BPT)) / HBM_BW
    moe = expert(bs * q, PF_N)
    body = t_pull + max(t_hbm, t_compute) + moe["t"]
    t_pd = n * store_seq(s) / PARAM
    tail = max(0.0, t_pd - body * (L - 1) / L)
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


def decode(bs, s, bw, cap):
    n = math.ceil(bs / DP)
    sel = min(1024.0, s / 4.0)
    score = N_CSA * 4096 * s + N_HCA * 2048 * s + N_CSA * 262144 * (sel + 128)
    kept = n * store_seq(s)
    spill = max(kept - ROOM_GPU, 0.0) / kept if kept else 0.0
    overflow = spill * kept
    if cap is not None and overflow > cap + 1.0:
        return None
    read = n * n_read(s)
    t_swap = read * spill / bw
    t_hbm = (read + ATTN) / HBM_BW
    t_ca = n * (score + PROJ) / (PEAK * align(n))
    moe = expert(float(bs))
    return {
        "t": t_swap + max(t_hbm, t_ca) + moe["t"],
        "swap": t_swap,
        "hbm": t_hbm,
        "ca": t_ca,
        "moe": moe["t"],
        "spill": spill,
        "n": n,
        "kv": kept,
        "hbm_kv": min(kept, ROOM_GPU),
        "ddr": overflow,
    }


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
    lo, hi = 1.0, 64e6
    for _ in range(48):
        mid = (lo + hi) / 2
        if prefill(1, mid, PREFIX_25, hit)["t"] > 10.0:
            hi = mid
        else:
            lo = mid
    return int(math.floor(lo))


def max_decode_s(limit):
    lo, hi = 1024.0, 2e10
    for _ in range(52):
        mid = (lo + hi) / 2
        row = decode(1, mid, HOST, None)
        if row["t"] <= limit:
            lo = mid
        else:
            hi = mid
    return int(math.floor(lo))


def collect():
    rows = []
    for s in LENGTHS:
        item = {"S": s}
        for key, bw in (("p25", PREFIX_25), ("p100", PREFIX_100)):
            bs, row = search(10.0, lambda b, bw=bw: prefill(b, s, bw))
            item[key] = {"bs": bs, "row": row}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            for key, bw, cap in (("h2d", HOST, DDR_CAP), ("p51", POOL_51, None), ("p26", POOL_26, None)):
                bs, row = search(limit, lambda b, bw=bw, cap=cap: decode(b, s, bw, cap))
                item[f"{key}{tag}"] = bs
                item[f"d{key}{tag}"] = row
        rows.append(item)
    return {
        "rows": rows,
        "cold_s": max_prefill_s(0.0),
        "hit_s": max_prefill_s(HIT),
        "dec10_s": max_decode_s(0.010),
        "dec30_s": max_decode_s(0.030),
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


def gb(n):
    if n >= 1e12:
        return f"{n / 1e12:.2f} TB"
    return f"{n / 1e9:.1f} GB"


def tps_p(bs, s, row):
    return bs * s / row["t"]


def tps_d(bs, row):
    return bs / row["t"]


def add_pie(slide, cx, cy, r, slices):
    alive = [(v, c) for v, c in slices if v > 0]
    if not alive:
        return
    if len(alive) == 1:
        oval = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - r), Inches(cy - r), Inches(2 * r), Inches(2 * r))
        ui.solid(oval, alive[0][1])
        return
    total = sum(v for v, _ in alive)
    theta = 0.0
    for value, color in alive:
        sweep = 360.0 * value / total
        steps = max(2, int(math.ceil(sweep / 6)))
        pts = [(cx, cy)]
        for i in range(steps + 1):
            ang = math.radians(theta + sweep * i / steps)
            pts.append((cx + r * math.sin(ang), cy - r * math.cos(ang)))
        theta += sweep
        builder = slide.shapes.build_freeform(Inches(pts[0][0]), Inches(pts[0][1]))
        builder.add_line_segments([(Inches(x), Inches(y)) for x, y in pts[1:]], close=True)
        ui.solid(builder.convert_to_shape(), color)


def slide_open(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "64K 到 4M 都能对上两组目标", "Prefill 56 卡    ·    基线拉 KV 50 GB/s    ·    Decode 256 卡走 H2D")
    ui.banner(slide, 0.92, "一组目标是 TTFT ≤ 10 秒且 TPOT ≤ 10 毫秒。另一组把 TPOT 放宽到 30 毫秒。Prefill 的批是 10 秒摸高。")
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
        f"冷请求不拉 prefix。单条冷请求摸到 10 秒的输入是 {data['cold_s']:,}。4M 冷请求 TTFT {sec(data['cold4'])}，超过 10 秒。\n"
        f"99.5% 命中的单条请求可以到 {data['hit_s']:,}，因为只有 0.5% 的 token 要现算。批量摸高仍看 64K 到 4M 这七档。\n"
        f"单条 Decode 把 TPOT 用到 10 毫秒的输入是 {data['dec10_s']:,}，用到 30 毫秒的是 {data['dec30_s']:,}。4M 的批量限制来自 HBM 和 10/30 毫秒，不是这条单请求上限。\n"
        "系统 Prefill TPS = 全局批 × 输入长度 / 实际 TTFT。系统 Decode TPS = 全局批 / 实际 TPOT。",
        14,
    )


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "只把路由专家从 384 加到 4951", "1.6T V4-Pro    ·    外推到 20T    ·    层和隐藏不动")
    ui.banner(slide, 0.92, "层数、隐藏、中间维、TopK 一变，KV 字节和激活都会变。20T 只加专家，用来把 FP4 专家表摊开。")
    head = ["项目", "1.6T 论文", "20T 外推"]
    body = [
        ["总参数", "1.600×10^12", f"{TOTAL/1e12:.4f}×10^12"],
        ["路由专家", "384", f"{E}"],
        ["层 / 隐藏 / 中间维", "61 / 7168 / 3072", "保持不动"],
        ["TopK / 激活", "6 路由 + 1 共享，4.9×10^10", "仍是 4.9×10^10"],
        ["激活比", "3.06%", "0.245%"],
        ["注意力", "30 CSA + 31 HCA", "压缩比 4 和 128 不动"],
        ["每 token KV", "4939.5 字节 + 滑窗", "同一条式子"],
        ["FP4 专家表", f"{384 * W_ONE * 0.5 / 1e12:.3f} TB", f"{ROUTED / 1e12:.3f} TB"],
    ]
    kinds = ["head"] + ["key" if i in (1, 7) else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.48, [2.70, 4.70, 5.10], [head] + body, [0.32] + [0.42] * 8, kinds, size=14)
    ui.gold(
        slide,
        5.55,
        1.30,
        f"E = ceil((2×10^13 − {OTHER/1e9:.3f}×10^9) / {W_ONE/1e9:.3f}×10^9) = {E}。单个专家 = 3×7168×3072×61 = {W_ONE/1e9:.3f}×10^9。\n"
        "K(S) = 4939.5×S + 4,497,408。1M 一条 5.184 GB，4M 一条 20.722 GB。这条 KV 现在整段落在一张卡上。",
        14,
    )


def slide_split(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "Prefill 用 56 卡，Decode 用满 256 卡", "两边都是 TP=1    ·    每卡批摸高不再随卡数上升")
    ui.banner(slide, 0.92, "机内 fullmesh 取消。TP 大于 1 就要在 D2D 上做 AllReduce，每卡批不增加，所以两边都取 TP=1。")
    head = ["", "Prefill", "Decode"]
    body = [
        ["规模", "56 卡，7 个 8 卡节点", "256 卡，整份超节点"],
        ["切分", "TP=1，DP=56，EP=56", "TP=1，DP=256，EP=256"],
        ["每卡路由专家", f"{ROUTED/PF_EP/1e9:.1f} GB，{E/PF_EP:.1f} 个", f"{ROUTED/EP/1e9:.1f} GB，{E/EP:.1f} 个"],
        ["每卡注意力", "19.35 GB，不再按 TP 切开", "19.35 GB，同样不切开"],
        ["KV 房间", f"{PF_ROOM/1e9:.1f} GB", f"{ROOM_GPU/1e9:.1f} GB"],
        ["寻优目标", "TTFT ≤ 10 秒下的每卡批", "TPOT ≤ 10 / 30 毫秒下的全局批"],
    ]
    kinds = ["head"] + ["key" if i in (0, 1) else "body" for i in range(6)]
    ui.add_table(slide, 0.42, 1.48, [2.20, 5.15, 5.15], [head] + body, [0.34] + [0.48] * 6, kinds, size=14)
    ui.gold(
        slide,
        5.00,
        1.85,
        "Prefill 的每卡批在 TP=1、卡数从 24 加到 256 时停在同一档：64K 是每卡 1,232 条。多出来的卡只把系统 TPS 按卡数放大。\n"
        "24 卡的房间只有 195 GB，64K 基线的每卡 KV 有 404 GB，放不下。56 卡房间 432 GB，是 8 卡对齐里基线七档都放得下的最小规模。\n"
        "Decode 要摊 9.975 TB 的专家表。EP 降到 16 时单是路由专家就有 623 GB，KV 没有地方放，所以 Decode 维持 EP=256。",
        14,
    )


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "TTFT 与 TPOT", "没有 AllReduce    ·    n 是一张卡上的条数")
    ui.banner(slide, 0.92, "Prefill 的 n = ceil(全局批 / 56)。Decode 的 n = ceil(全局批 / 256)。注意力由这一张卡承担。")
    left = (
        "Prefill，56 卡，命中 99.5%\n"
        "p = 0.995S，q = 0.005S\n"
        "T_pull = n×(p×4939.5 + 61×min(p,128)×576) / BW\n"
        "BW = 50 GB/s 或 200 GB/s\n"
        "T_compute = n×F / (33.60 P × align(n×q))\n"
        "T_HBM = (19.35 GB + n×(K(S)+q×4939.5)) / 26.40 TB/s\n"
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine\n"
        "T_tail = max(0, n×K(S)/160 GB/s − 主体×60/61)\n"
        "TTFT = T_pull + max(T_HBM, T_compute) + T_MoE + T_tail"
    )
    right = (
        "Decode，256 卡\n"
        "f = max(n×K(S) − 571.65 GB, 0) / (n×K(S))\n"
        "Read = 30×(S/4)×64 + 31×(S/128)×576\n"
        "      + 30×min(1024,S/4)×576 + 滑窗\n"
        "T_swap = f × n × Read / BW\n"
        "BW = 160 GB/s，或 6.40 / 3.20 TB/s\n"
        "T_HBM = (n×Read + 19.35 GB) / 26.40 TB/s\n"
        "T_compute = n×(F_score+3.87×10^10) / (33.60 P×align(n))\n"
        "TPOT = T_swap + max(T_HBM, T_compute) + T_MoE"
    )
    for x, title, text in ((0.42, "TTFT", left), (6.88, "TPOT", right)):
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.48), Inches(6.05), Inches(5.40))
        ui.solid(box, "F4F7FA")
        ui.textbox(slide, x + 0.16, 1.60, 5.70, 0.34, title, 18, True, NAVY, anchor=MSO_ANCHOR.TOP)
        ui.textbox(slide, x + 0.16, 2.02, 5.70, 4.65, text, 13, False, INK, anchor=MSO_ANCHOR.TOP)


def stage_cell(part, total):
    return f"{sec(part) if part >= 0.1 else ms(part)}  {part / total * 100:.1f}%"


def slide_cmp(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "基线对 NEW：都按 10 秒摸高", "56 卡 Prefill    ·    基线 50 GB/s    ·    NEW 200 GB/s")
    ui.banner(slide, 0.90, "批只受 TTFT ≤ 10 秒约束。尾部是 0。NEW 的 64K 到 2M，每卡 KV 是 466 到 1020 GB，超过 432 GB 房间。", size=12)
    head = ["输入", "方案", "每卡批", "系统 TPS", "TTFT", "拉 KV", "计算", "HBM", "MoE"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        for key, name in (("p25", "基线"), ("p100", "NEW")):
            item = row[key]
            r = item["row"]
            kinds.append("key" if name == "NEW" else "body")
            body.append([
                fmt_len(row["S"]),
                name,
                fmt_bs(r["n"]),
                fmt_rate(tps_p(item["bs"], row["S"], r)),
                sec(r["t"]),
                stage_cell(r["pull"], r["t"]),
                stage_cell(r["compute"], r["t"]),
                stage_cell(r["hbm"], r["t"]),
                stage_cell(r["moe"], r["t"]),
            ])
    ui.add_table(
        slide, 0.28, 1.42,
        [0.85, 0.75, 0.95, 1.25, 0.95, 1.85, 1.75, 1.70, 1.70],
        [head] + body,
        [0.32] + [0.36] * len(body),
        kinds,
        size=11,
    )


def slide_decode(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "Decode：30 毫秒里换入是大头", "H2D 160 GB/s    ·    每卡主机最多再放 96 GB")
    ui.banner(slide, 0.90, "2M 和 4M 的 10 毫秒停在还没溢出的批，实际约 5.8 毫秒；再加一条就开始换入，步时超过 10 毫秒。30 毫秒的换入从 64K 起超过 18 毫秒。")
    head = ["输入", "约束", "批", "换入", "HBM", "计算", "MoE", "TPOT"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        for tag, label in (("10", "10 毫秒"), ("30", "30 毫秒")):
            r = row[f"dh2d{tag}"]
            kinds.append("key" if tag == "30" and row["S"] in (65536, 4194304) else "body")
            body.append([
                fmt_len(row["S"]),
                label,
                fmt_bs(row[f"h2d{tag}"]),
                ms(r["swap"]),
                ms(r["hbm"]),
                ms(r["ca"]),
                ms(r["moe"]),
                ms(r["t"]),
            ])
    ui.add_table(slide, 0.32, 1.42, [1.05, 1.25, 1.45, 1.35, 1.25, 1.25, 1.25, 1.45], [head] + body, [0.28] + [0.32] * len(body), kinds, size=11)


def slide_case2(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 7, "DDR 池把 30 毫秒的长上下文抬上去", "Case 2    ·    51.2 Tb/s = 6.40 TB/s    ·    25.6 Tb/s = 3.20 TB/s")
    ui.banner(slide, 0.90, "51.2 Tb/s 是 D2D 57.6 Tb/s 的 88.8%，不再另乘 80%。池容量不限。提升以 H2D 160 GB/s、每卡 96 GB 为基线。")
    head = ["输入", "H2D·10ms", "51.2·10ms", "25.6·10ms", "H2D·30ms", "51.2·30ms", "25.6·30ms"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        kinds.append("key" if row["S"] in (65536, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_rate(tps_d(row["h2d10"], row["dh2d10"])),
            fmt_rate(tps_d(row["p5110"], row["dp5110"])) + "\n" + signed_pct(tps_d(row["p5110"], row["dp5110"]), tps_d(row["h2d10"], row["dh2d10"])),
            fmt_rate(tps_d(row["p2610"], row["dp2610"])) + "\n" + signed_pct(tps_d(row["p2610"], row["dp2610"]), tps_d(row["h2d10"], row["dh2d10"])),
            fmt_rate(tps_d(row["h2d30"], row["dh2d30"])),
            fmt_rate(tps_d(row["p5130"], row["dp5130"])) + "\n" + signed_pct(tps_d(row["p5130"], row["dp5130"]), tps_d(row["h2d30"], row["dh2d30"])),
            fmt_rate(tps_d(row["p2630"], row["dp2630"])) + "\n" + signed_pct(tps_d(row["p2630"], row["dp2630"]), tps_d(row["h2d30"], row["dh2d30"])),
        ])
    ui.add_table(slide, 0.32, 1.46, [1.15, 1.70, 1.85, 1.85, 1.70, 1.95, 1.95], [head] + body, [0.36] + [0.58] * len(body), kinds, size=11)
    r4 = data["rows"][-1]
    ui.gold(
        slide,
        5.95,
        1.05,
        f"2M 和 4M 的 10 毫秒，H2D 停在没溢出的批，实际只有 5.7 到 5.8 毫秒，TPS 更高。池把批加大并把 10 毫秒用满，TPS 低 22% 到 31%。\n"
        f"30 毫秒才拉开。4M：H2D 批 {fmt_bs(r4['h2d30'])}，51.2 Tb/s 批 {fmt_bs(r4['p5130'])}（{signed_pct(tps_d(r4['p5130'], r4['dp5130']), tps_d(r4['h2d30'], r4['dh2d30']))}），"
        f"25.6 Tb/s 批 {fmt_bs(r4['p2630'])}（{signed_pct(tps_d(r4['p2630'], r4['dp2630']), tps_d(r4['h2d30'], r4['dh2d30']))}）。",
        13,
    )


def slide_pies(prs, blank, data, page, limit_tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, "每卡 KV 落点    ·    上排 51.2 Tb/s    ·    下排 25.6 Tb/s")
    ui.banner(slide, 0.90, "饼是这一批 KV。权重和预留 68.35 GB 在每张卡上，不画进饼。HBM 里的 KV 不超过 571.65 GB。")
    by = {row["S"]: row for row in data["rows"]}
    for col, s in enumerate(PIE_LENGTHS):
        x = 0.28 + col * 3.26
        for i, key in enumerate(("p51", "p26")):
            y = 1.42 + i * 2.75
            row = by[s]
            dec = row[f"d{key}{limit_tag}"]
            name = "51.2 Tb/s" if key == "p51" else "25.6 Tb/s"
            ui.textbox(slide, x, y, 3.15, 0.26, f"{name}  ·  {fmt_len(s)}  ·  批 {fmt_bs(row[key + limit_tag])}", 11, True, NAVY)
            total = dec["hbm_kv"] + dec["ddr"]
            add_pie(slide, x + 0.72, y + 1.15, 0.58, [(dec["hbm_kv"], C_HBM), (dec["ddr"], C_DDR)])
            h = dec["hbm_kv"] / total * 100 if total else 0
            d = 0 if dec["ddr"] <= 0 else 100 - h
            ui.add_key(
                slide, x + 1.45, y + 0.55, 1.70,
                [
                    (C_HBM, f"HBM  {h:.1f}%\n{gb(dec['hbm_kv'])}"),
                    (C_DDR, f"DDR 池  {d:.1f}%\n{gb(dec['ddr'])}"),
                ],
                size=11, row=0.52,
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
    prs.core_properties.title = "N+2：20T V4，无 TP"
    blank = prs.slide_layouts[6]
    slide_open(prs, blank, data)
    slide_model(prs, blank)
    slide_split(prs, blank)
    slide_formula(prs, blank)
    slide_cmp(prs, blank, data)
    slide_decode(prs, blank, data)
    slide_case2(prs, blank, data)
    slide_pies(prs, blank, data, 8, "10", "10 毫秒：64K 全在 HBM，更长的开始溢出")
    slide_pies(prs, blank, data, 9, "30", "30 毫秒：KV 顶满 HBM 后进 DDR 池")
    prs.save(PPT)
    print("slides", len(prs.slides), "overflow", audit(prs))
    print("cold", data["cold_s"], "hit", data["hit_s"], "dec", data["dec10_s"], data["dec30_s"])
    for row in data["rows"]:
        print(
            fmt_len(row["S"]),
            "pf", row["p25"]["bs"], row["p25"]["row"]["n"], row["p100"]["bs"], row["p100"]["row"]["n"],
            "d10", row["h2d10"], row["p5110"], row["p2610"],
            "d30", row["h2d30"], row["p5130"], row["p2630"],
        )


if __name__ == "__main__":
    main()
