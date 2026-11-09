#!/usr/bin/env python3
"""A5 decode with a DDR pool: H2D ingress versus the pool's own bandwidth.

Same 10T model, 128-GPU split, and 340.2 TFLOP/s as the no-pool case.
KV hit rate stays 99.95% for the scenario. Decode reads each request's
full context. Swap bandwidth is 51.2 GB/s through H2D, or 384 GB/s on
the DDR pool (480 GB/s x 80%), capacity unlimited.
"""

from __future__ import annotations

import importlib.util
import math

spec = importlib.util.spec_from_file_location(
    "slo_ui", "/agent/repos/ucl-mpcomm/docs/build_deepseek_20t_slo_ppt.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches

N, NODE = 128, 8
TP, DP, EP = 8, 16, 128
L, H, DFF, TOPK = 61, 7168, 3072, 6
N_CSA, N_HCA = 30, 31
W_ONE = 3 * H * DFF * L
OTHER = 1_600_000_000_000 - 384 * W_ONE
E = math.ceil((1e13 - OTHER) / W_ONE)
TOTAL = E * W_ONE + OTHER
HBM_CAP = 96e9
HBM_BW = 4e12 * 0.80
PEAK = 486e12 * 0.70
D2D = 3.2e12 / 8 * 0.80
P2P = min(3.2e12 / 8, 7 * (400e9 / 8)) * 0.80
H2D = 64e9 * 0.80
DDR_SHARE = 1288.8e9 * 0.80 / NODE
POOL_NOMINAL = 480e9
POOL_DDR = POOL_NOMINAL * 0.80
POOL_H2D = min(H2D, DDR_SHARE, POOL_DDR)
COLL = 5e-6
ATTN = 19.35e9
SHARED = float(W_ONE)
ROUTED = E * W_ONE * 0.5
RESERVE = 6e9
ROOM_GPU = HBM_CAP - ROUTED / EP - SHARED - ATTN / TP - RESERVE
ROOM = N * ROOM_GPU
BPT = N_CSA * (576 / 4 + 64 / 4) + N_HCA * (576 / 128)
FIXED = L * 128 * 576
PROJ = ATTN * 2
HIT = 0.9995
LENGTHS = (131072, 262144, 524288, 1048576)
LIMITS = (0.010, 0.030)
MODES = (("h2d", "H2D", POOL_H2D), ("ddr", "DDR 池", POOL_DDR))

C_SWAP = "1B4F8A"
C_HBM = "5C6B73"
C_IDX = "1F8A70"
C_HCA = "7D5BA6"
C_CORE = "C48A2A"
C_PROJ = "8D6E63"
C_AR = "E07A3D"
C_DISP = "3D7A4A"
C_W = "A67C2D"
C_GEMM = "D4546A"
C_COMB = "2A6F97"
C_KV = "1B4F8A"
C_DDR = "E07A3D"

SLIDES = 8
FOOTER = "A5    ·    10T    ·    128 卡 TP=8 EP=128    ·    带 DDR 池    ·    99.95% KV 命中    ·    486T×70%"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY = ui.NAVY
DOC = "/agent/repos/ucl-mpcomm/docs/A5-10T-P-D-带DDR池-99.95KV命中.md"
PPT = "/agent/repos/ucl-mpcomm/docs/A5-10T-P-D-带DDR池-99.95KV命中.pptx"


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def store(s):
    return s * BPT + FIXED


def n_csa_read(s):
    sel = min(1024.0, s / 4.0)
    return N_CSA * (s / 4.0) * 64 + N_HCA * (s / 128.0) * 576 + N_CSA * sel * 576 + FIXED


def expert(tokens):
    tokens = max(float(tokens), 0.0)
    mean = tokens * TOPK / EP
    hot = min(tokens * TOPK, mean + 2 * math.sqrt(max(mean * (1 - 1 / EP), 0.0)))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / EP
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_rows = e_hot * math.ceil(tpe / 16) * 16 if e_hot else 0.0
    shared_rows = math.ceil(max(1, math.ceil(tokens / EP)) / 16) * 16
    tw = (e_hot * W_ONE * 0.5 + SHARED) / HBM_BW
    tg = (routed_rows + shared_rows) * 6 * H * DFF * L / PEAK
    td = L * (COLL + hot * H * 1 / D2D)
    tc = L * (COLL + hot * H * 2 / D2D)
    return {"tw": tw, "tg": tg, "td": td, "tc": tc, "inner": max(tw, tg), "name": "专家权重" if tw >= tg else "MoE GEMM"}


def decode(bs, s, bw):
    n = math.ceil(bs / DP)
    sel = min(1024.0, s / 4.0)
    flops = {
        "idx": N_CSA * 4096 * s,
        "hca": N_HCA * 2048 * s,
        "core": N_CSA * 262144 * (sel + 128),
        "proj": PROJ,
    }
    scale = n / (TP * PEAK * align(n))
    kept = bs * store(s)
    spill = max(kept - ROOM, 0.0) / kept if kept else 0.0
    read = n * n_csa_read(s) / TP
    swap = read * spill / bw
    t_hbm = (read + ATTN / TP) / HBM_BW
    t_ca = sum(flops.values()) * scale
    t_ar = L * (COLL + 2 * (TP - 1) / TP * n * H * 2 / P2P)
    moe = expert(float(bs))
    attn = t_hbm if t_hbm >= t_ca else t_ca
    total = swap + attn + t_ar + moe["td"] + moe["inner"] + moe["tc"]
    parts = [("swap", "换入", swap, C_SWAP)]
    if t_hbm >= t_ca:
        parts.append(("hbm", "Attention 访存", t_hbm, C_HBM))
    else:
        parts.extend(
            [
                ("idx", "CSA indexer", flops["idx"] * scale, C_IDX),
                ("hca", "HCA", flops["hca"] * scale, C_HCA),
                ("core", "稀疏核心", flops["core"] * scale, C_CORE),
                ("proj", "投影", flops["proj"] * scale, C_PROJ),
            ]
        )
    parts.extend(
        [
            ("ar", "AllReduce", t_ar, C_AR),
            ("disp", "MoE dispatch", moe["td"], C_DISP),
            ("inner", moe["name"], moe["inner"], C_W if moe["name"] == "专家权重" else C_GEMM),
            ("comb", "MoE combine", moe["tc"], C_COMB),
        ]
    )
    return {
        "t": total,
        "parts": parts,
        "spill": spill,
        "store": kept,
        "hbm_kv": min(kept, ROOM),
        "ddr_kv": max(kept - ROOM, 0.0),
        "covered_hbm": t_hbm,
        "covered_ca": t_ca,
        "covered_w": moe["tw"],
        "covered_g": moe["tg"],
        "moe_name": moe["name"],
    }


def search(s, bw, limit):
    def ok(bs):
        return decode(bs, s, bw)["t"] <= limit + 1e-12

    if not ok(1):
        return 0, decode(1, s, bw)
    lo, hi = 1, 2
    while ok(hi) and hi < 8_000_000:
        lo, hi = hi, hi * 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo, decode(lo, s, bw)


def collect():
    rows = []
    for s in LENGTHS:
        item = {"S": s, "cap": int(ROOM // store(s))}
        for key, _label, bw in MODES:
            item[key] = {}
            for limit in LIMITS:
                bs, row = search(s, bw, limit)
                item[key][limit] = {"bs": bs, "row": row, "tps": bs / row["t"]}
        rows.append(item)
    return rows


def fmt_len(s):
    return f"{s // 1024}K" if s < 1048576 else f"{s // 1048576}M"


def fmt_bs(n):
    return f"{int(n):,}"


def fmt_tps(v):
    if v >= 10000:
        return f"{v / 10000:.2f} 万"
    return f"{v:.0f}"


def fmt_bytes(n):
    if n >= 1e12:
        return f"{n / 1e12:.2f} TB"
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    return "0"


def dur_ms(v):
    if v >= 0.001:
        return f"{v * 1e3:.2f} 毫秒"
    return f"{v * 1e6:.0f} 微秒"


def shares(parts, total):
    raw = [v / total * 100 if total else 0 for _k, _n, v, _c in parts]
    shown = [math.floor(v * 10 + 1e-9) / 10 for v in raw]
    leftover = int(round((100.0 - sum(shown)) * 10))
    order = sorted(range(len(raw)), key=lambda i: raw[i] - shown[i], reverse=True)
    for i in order:
        if leftover <= 0:
            break
        shown[i] = round(shown[i] + 0.1, 1)
        leftover -= 1
    return shown


def add_pie(slide, cx, cy, r, slices):
    alive = [(v, c) for v, c in slices if v > 0]
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


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "10T 只增加路由专家", "A5    ·    带 DDR 池    ·    与无池场景共用模型")
    ui.banner(slide, 0.92, "DeepSeek 没有发布 10T。层数、隐藏维、中间维、TopK 保持 V4-Pro，专家个数对齐到 10^13。")
    head = ["项目", "取值"]
    body = [
        ["名义 / 整数参数", "1.000×10^13；整数和 10,001,877,729,280"],
        ["层 / 隐藏 / 中间维", "61 / 7168 / 3072。单个专家 4.030×10^9"],
        ["路由", "2469 个专家。TopK=6。前 3 层哈希，其后 top-6"],
        ["注意力", "30 CSA + 31 HCA。压缩 4 / 128。CSA 一步最多 1024"],
        ["KV", "每 token 4939.5 字节。滑窗 4,497,408 字节。K(S) = 4939.5×S + 滑窗"],
        ["精度", "路由 FP4。共享专家和注意力 FP8。AllReduce hidden 为 BF16"],
        ["MoE 通信", "dispatch FP8，每元素 1 字节。combine BF16，每元素 2 字节"],
        ["命中", "场景命中率 99.95%。Decode 仍按每条请求的完整上下文读 KV"],
    ]
    ui.add_table(slide, 0.42, 1.48, [2.55, 10.0], [head] + body, [0.34] + [0.46] * len(body), ["head"] + ["body"] * len(body), size=14)
    ui.gold(slide, 5.85, 1.15, "激活参数 4.9×10^10。词表 129,280。上下文 1,048,576。mHC 展开 4，MTP 深度 1。\nQuery 128 头，头维 512，压缩维 1536。", 15)


def slide_cluster(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "两种换入共用 128 卡切分", "A5    ·    方式 1 走 H2D    ·    方式 2 走 DDR 池")
    ui.banner(slide, 0.92, "Attention TP=8、DP=16，MoE EP=128。算力不含 108T。只改 Decode 溢出 KV 的换入带宽。")
    head = ["项目", "两种方式都用这一套"]
    body = [
        ["副本", "128 卡超节点，每机 8 卡。一条请求不跨副本"],
        ["算力 / HBM", "486T×70% = 340.2 TFLOP/s。HBM 96 GB，3.20 TB/s。预留 6 GB"],
        ["每卡 KV 空闲", "44.69 GB。128 卡合计 5.720 TB。权重每卡 45.31 GB"],
        ["D2D / AllReduce", "D2D 320 GB/s 走 MoE。AllReduce 用机内 280 GB/s。每层 5 微秒"],
        ["方式 1 · H2D", "标称 64 GB/s ×80% = 51.2 GB/s。池的流量也从这条链路进 GPU"],
        ["方式 2 · DDR 池", "标称每卡 480 GB/s ×80% = 384 GB/s。容量不限，不经 H2D"],
    ]
    kinds = ["head", "body", "body", "body", "body", "key", "key"]
    ui.add_table(slide, 0.42, 1.48, [2.70, 9.80], [head] + body, [0.36] + [0.52] * 6, kinds, size=15)
    ui.gold(slide, 5.70, 1.25, "系统 TPS = 全局批 / 实际 TPOT，单位是 token/s。\n10 毫秒四档的 KV 都小于 5.720 TB，换入是 0，两种方式的批和 TPS 相同。池带宽从 256K 的 30 毫秒开始起作用。", 15)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "TTFT 与 TPOT 的汇总式", "A5    ·    换入先做完，再进 HBM 里的 Decode")
    ui.banner(slide, 0.92, "溢出比例 f = max(全局批×K(S) − 5.720 TB, 0) / (全局批×K(S))。饼上只放关键路径。")
    left = (
        "Prefill，n = ⌈全局批 / 16⌉\n"
        "p = 0.9995S，q = 0.0005S\n"
        "C = q×p + q(q+1)/2\n"
        "T_pull = n×(p×4939.5 + 61×min(p,128)×576) / (8×BW)\n"
        "BW 仍是 12.5 或 50 GB/s\n"
        "T_compute = n×ΣF / (8×340.2×10^12×align)\n"
        "T_AR = 61×(5µs + 1.75×行×7168×2 / 280 GB/s)\n"
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine\n"
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail"
    )
    right = (
        "Decode，n = ⌈全局批 / 16⌉\n"
        "Read = 30×(S/4)×64 + 31×(S/128)×576\n"
        "      + 30×min(1024,S/4)×576 + 滑窗\n"
        "T_swap = f × n × Read / 8 / BW\n"
        "BW = 51.2 GB/s 或 384 GB/s\n"
        "T_HBM = (n×Read/8 + 19.35×10^9/8) / 3.20 TB/s\n"
        "T_compute = n×(F_score + 3.87×10^10) / (8×340.2×10^12×align(n))\n"
        "T_MoE 与 Prefill 同一套，token 数改为全局批\n"
        "TPOT = T_swap + max(T_HBM, T_compute) + T_AR + T_MoE"
    )
    for x, title, text in ((0.42, "TTFT", left), (6.88, "TPOT", right)):
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.48), Inches(6.05), Inches(5.50))
        ui.solid(box, "F4F7FA")
        ui.textbox(slide, x + 0.18, 1.62, 5.70, 0.36, title, 18, True, NAVY, anchor=MSO_ANCHOR.TOP)
        ui.textbox(slide, x + 0.18, 2.10, 5.70, 4.60, text, 14, False, ui.INK, anchor=MSO_ANCHOR.TOP)


def slide_tps(prs, blank, rows):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "30 毫秒的长上下文才拉开 TPS", "系统 TPS = 全局批 / 实际 TPOT")
    ui.banner(slide, 0.92, "10 毫秒两种方式相同。30 毫秒从 256K 起，DDR 池的批更大，TPS 以 H2D 为基线。")
    head = ["输入", "约束", "H2D 批", "H2D TPS", "DDR 池批", "DDR 池 TPS", "TPS 提升"]
    body, kinds = [], ["head"]
    for row in rows:
        for limit, label in ((0.010, "10 毫秒"), (0.030, "30 毫秒")):
            h, d = row["h2d"][limit], row["ddr"][limit]
            lift = d["tps"] / h["tps"] - 1
            kinds.append("key" if lift > 0.001 else "body")
            body.append([
                fmt_len(row["S"]),
                label,
                fmt_bs(h["bs"]),
                fmt_tps(h["tps"]),
                fmt_bs(d["bs"]),
                fmt_tps(d["tps"]),
                f"+{lift * 100:.1f}%" if lift > 0.001 else "0",
            ])
    ui.add_table(slide, 0.42, 1.50, [1.20, 1.45, 1.55, 1.70, 1.70, 2.05, 1.70], [head] + body, [0.36] + [0.48] * len(body), kinds, size=14)
    ui.gold(slide, 6.00, 0.95, "128K 的 30 毫秒批是 5,888，KV 3.84 TB，还没碰到 5.720 TB，所以池带宽用不上。\n1M 的 30 毫秒，H2D 批 1,179、TPS 3.94 万，DDR 池批 1,536、TPS 5.17 万，提升 31.3%。", 14)


def mem_panel(slide, x, y, w, title, row):
    ui.textbox(slide, x, y, w, 0.26, title, 12, True, NAVY)
    total = row["hbm_kv"] + row["ddr_kv"]
    add_pie(slide, x + 0.78, y + 1.15, 0.62, [(row["hbm_kv"], C_KV), (row["ddr_kv"], C_DDR)])
    h = row["hbm_kv"] / total * 100 if total else 0
    d = 100 - h if row["ddr_kv"] else 0
    ui.add_key(
        slide, x + 1.55, y + 0.55, w - 1.60,
        [
            (C_KV, f"HBM  {h:.1f}%\n{fmt_bytes(row['hbm_kv'])}"),
            (C_DDR, f"DDR 池  {d:.1f}%\n{fmt_bytes(row['ddr_kv'])}"),
        ],
        size=11, row=0.55,
    )


def slide_memory(prs, blank, rows):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒：KV 顶满 HBM 后溢出", "饼是这一批 KV 的落点    ·    上排 H2D    ·    下排 DDR 池")
    ui.banner(slide, 0.90, "10 毫秒四档 KV 都在 HBM，两种方式的饼是满圆。权重每卡 45.31 GB，不画进 KV 饼。")
    by = {row["S"]: row for row in rows}
    for col, s in enumerate(LENGTHS):
        x = 0.32 + col * 3.25
        for i, (key, label, _bw) in enumerate(MODES):
            y = 1.42 + i * 2.75
            item = by[s][key][0.030]
            mem_panel(slide, x, y, 3.15, f"{label}  ·  {fmt_len(s)}  ·  批 {fmt_bs(item['bs'])}", item["row"])


def time_panel(slide, x, y, w, title, row):
    ui.textbox(slide, x, y, w, 0.26, title, 13, True, NAVY)
    parts = row["parts"]
    pct = shares(parts, row["t"])
    add_pie(slide, x + 1.10, y + 1.45, 0.88, [(v, c) for _k, _n, v, c in parts])
    items = []
    for ( _k, name, value, color), share in zip(parts, pct):
        items.append((color, f"{share:4.1f}%   {name}   {dur_ms(value)}"))
    ui.add_key(slide, x + 2.15, y + 0.34, w - 2.20, items, size=12, row=0.28)


def slide_time(prs, blank, rows, page, title, kicker, limit, lengths):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, kicker)
    ui.banner(slide, 0.90, "扇区加总等于实际 TPOT。HBM 访存比计算短，不进饼。权重和 GEMM 只留更慢的一段。")
    by = {row["S"]: row for row in rows}
    slots = ((0.32, 1.40), (6.78, 1.40), (0.32, 4.22), (6.78, 4.22))
    pairs = []
    for s in lengths:
        for key, label, _bw in MODES:
            pairs.append((s, label, by[s][key][limit]))
    # 10 ms uses one pie per length; caller passes modes already filtered by passing lengths only
    if len(pairs) != 4:
        pairs = pairs[:4]
    for (x, y), (s, label, item) in zip(slots, pairs):
        time_panel(
            slide, x, y, 6.20,
            f"{fmt_len(s)}  ·  {label}  ·  批 {fmt_bs(item['bs'])}  ·  {item['row']['t']*1e3:.2f} 毫秒",
            item["row"],
        )


def slide_time_same(prs, blank, rows):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "10 毫秒：专家权重占住 TPOT", "两种换入相同    ·    换入是 0    ·    专家权重约八成")
    ui.banner(slide, 0.90, "扇区加总等于实际 TPOT。128K 到 512K 是访存盖住计算，1M 反过来。GEMM 比专家权重短，不进饼。")
    by = {row["S"]: row for row in rows}
    slots = ((0.32, 1.40), (6.78, 1.40), (0.32, 4.22), (6.78, 4.22))
    for (x, y), s in zip(slots, LENGTHS):
        item = by[s]["h2d"][0.010]
        time_panel(
            slide, x, y, 6.20,
            f"{fmt_len(s)}  ·  批 {fmt_bs(item['bs'])}  ·  {item['row']['t']*1e3:.2f} 毫秒",
            item["row"],
        )


def write_md(rows):
    lines = [
        "# A5-10T-P-D-带DDR池-99.95KV命中",
        "",
        "10T Decode 在带 DDR 池时的仿真口径。模型和 128 卡切分与「无 DDR 池」场景相同，算力不含 108T。命中率 99.95%。Decode 按每条请求的完整上下文读 KV。",
        "",
        "两种换入：",
        "",
        "- 方式 1，H2D。标称 64 GB/s ×80% = 51.2 GB/s。DDR 池的流量也从这条链路进入 GPU。",
        "- 方式 2，DDR 池。标称每卡 480 GB/s ×80% = 384 GB/s，容量不限，不经 H2D。",
        "",
        "系统 TPS = 全局批 / 实际 TPOT。",
        "",
        "## 1. 模型与并行",
        "",
        f"整数总参数 {TOTAL}。61 层，隐藏 7168，中间维 3072，路由专家 {E}，TopK=6。30 层 CSA + 31 层 HCA。每 token KV {BPT} 字节，滑窗 {int(FIXED)} 字节。",
        "",
        "一份副本 128 卡。Attention TP=8，DP=16。MoE EP=128。有效算力 340.2 TFLOP/s。HBM 有效带宽 3.20 TB/s。D2D 320 GB/s。AllReduce 280 GB/s。集合通信每层 5 微秒。",
        "",
        f"每卡权重 {(ROUTED/EP + SHARED + ATTN/TP)/1e9:.2f} GB，预留 6 GB，KV 空闲 {ROOM_GPU/1e9:.2f} GB。副本 KV 上限 {ROOM/1e12:.3f} TB。",
        "",
        "## 2. 公式",
        "",
        "```",
        "K(S) = 4939.5×S + 4,497,408",
        "f = max(BS×K(S) − 5.720×10^12, 0) / (BS×K(S))",
        "n = ⌈BS / 16⌉",
        "Read = 30×(S/4)×64 + 31×(S/128)×576 + 30×min(1024,S/4)×576 + 4,497,408",
        "T_swap = f × n × Read / 8 / BW",
        "T_HBM = (n×Read/8 + 1.935×10^10/8) / 3.20×10^12",
        "F_score = 30×4096×S + 31×2048×S + 30×262144×(min(1024,S/4)+128)",
        "T_compute = n × (F_score + 3.87×10^10) / (8 × 3.402×10^14 × align(n))",
        "T_AR = 61 × (5×10^-6 + 2×7/8 × n × 7168 × 2 / 2.80×10^11)",
        "T_dispatch = 61 × (5×10^-6 + hot × 7168 × 1 / 3.20×10^11)",
        "T_combine  = 61 × (5×10^-6 + hot × 7168 × 2 / 3.20×10^11)",
        "T_weight = (e_hot × 4.030×10^9 × 0.5 + 4.030×10^9) / 3.20×10^12",
        "T_gemm = (routed_rows + shared_rows) × 6 × 7168 × 3072 × 61 / 3.402×10^14",
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine",
        "TPOT = T_swap + max(T_HBM, T_compute) + T_AR + T_MoE",
        "```",
        "",
        "Prefill 的 TTFT 与无 DDR 池场景相同：T_pull 用 12.5 或 50 GB/s，TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail。",
        "",
        "## 3. 批量与系统 TPS",
        "",
        "| 输入 | 约束 | H2D 批 | H2D TPOT | H2D TPS | DDR 池批 | DDR 池 TPOT | DDR 池 TPS | 提升 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        for limit in LIMITS:
            h, d = row["h2d"][limit], row["ddr"][limit]
            lift = d["tps"] / h["tps"] - 1
            lines.append(
                f"| {fmt_len(row['S'])} | {limit*1e3:.0f} 毫秒 | {h['bs']} | {h['row']['t']*1e3:.2f} 毫秒 | {h['tps']:.0f} | {d['bs']} | {d['row']['t']*1e3:.2f} 毫秒 | {d['tps']:.0f} | {lift*100:.1f}% |"
            )
    lines += [
        "",
        "10 毫秒四档以及 128K 的 30 毫秒，KV 小于 5.720 TB，f = 0，两种方式相同。",
        "",
        "## 4. KV 落点",
        "",
        "HBM 中的 KV 不超过 5.720 TB。超出的部分记在 DDR 池。权重不计入这张饼。",
        "",
        "| 输入 | 方式 | 批量 | HBM KV | DDR 池 KV | 溢出比例 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        for limit in LIMITS:
            for key, label, _bw in MODES:
                item = row[key][limit]
                r = item["row"]
                lines.append(
                    f"| {fmt_len(row['S'])} {limit*1e3:.0f} 毫秒 | {label} | {item['bs']} | {fmt_bytes(r['hbm_kv'])} | {fmt_bytes(r['ddr_kv'])} | {r['spill']*100:.1f}% |"
                )
    lines += ["", "## 5. Decode 耗时", ""]
    for row in rows:
        for limit in LIMITS:
            for key, label, _bw in MODES:
                item = row[key][limit]
                r = item["row"]
                if limit == 0.010 and key == "ddr":
                    continue
                pct = shares(r["parts"], r["t"])
                lines.append(f"### {fmt_len(row['S'])}，{limit*1e3:.0f} 毫秒，{label}，批 {item['bs']}")
                lines.append("")
                lines.append("| 阶段 | 耗时 | 占 TPOT |")
                lines.append("| --- | ---: | ---: |")
                for ( _k, name, value, _c), share in zip(r["parts"], pct):
                    lines.append(f"| {name} | {value*1e3:.3f} 毫秒 | {share:.1f}% |")
                lines.append("")
                lines.append(
                    f"未进饼：Attention 计算 {r['covered_ca']*1e3:.3f} 毫秒，HBM 访存 {r['covered_hbm']*1e3:.3f} 毫秒，专家权重 {r['covered_w']*1e3:.3f} 毫秒，GEMM {r['covered_g']*1e3:.3f} 毫秒。饼上取其中更慢的一段。"
                )
                lines.append("")
    lines.append("10 毫秒的 DDR 池与 H2D 是同一批，耗时表不重复列。")
    lines.append("")
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


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
    rows = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "A5 10T：带 DDR 池，99.95% KV 命中"
    blank = prs.slide_layouts[6]
    slide_model(prs, blank)
    slide_cluster(prs, blank)
    slide_formula(prs, blank)
    slide_tps(prs, blank, rows)
    slide_memory(prs, blank, rows)
    slide_time_same(prs, blank, rows)
    slide_time(prs, blank, rows, 7, "30 毫秒：128K 仍无换入，256K 开始溢出", "左 H2D    ·    右 DDR 池", 0.030, (131072, 262144))
    slide_time(prs, blank, rows, 8, "30 毫秒：512K 和 1M 的换入升上来", "左 H2D    ·    右 DDR 池", 0.030, (524288, 1048576))
    prs.save(PPT)
    write_md(rows)
    bad = audit(prs)
    print("overflow", len(bad))
    for item in bad[:8]:
        print(item)
    for row in rows:
        h, d = row["h2d"][0.030], row["ddr"][0.030]
        print(fmt_len(row["S"]), "30ms", h["bs"], d["bs"], f"{d['tps']/h['tps']-1:.3f}", f"spill {h['row']['spill']:.3f}/{d['row']['spill']:.3f}")


if __name__ == "__main__":
    main()
