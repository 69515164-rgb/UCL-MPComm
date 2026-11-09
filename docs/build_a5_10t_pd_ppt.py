#!/usr/bin/env python3
"""A5: 10T prefill/decode on the fixed 128-GPU cluster, no DDR pool.

Hit rate is 99.95%. Tensor peak is 486T x 70% only; the 108T incremental
core is not included. Prefix pull is compared at 25% and 100% of the
physical 50 GB/s parameter-plane rate. Each rate takes its own maximum
batch with TTFT <= 10 s. There is no DDR pool, so the KV footprint of
that batch is reported against the 44.69 GB left on each GPU.
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
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches

N, NODE = 128, 8
TP = 8
DP = N // TP
EP = N
L, H, DFF, TOPK = 61, 7168, 3072, 6
N_CSA, N_HCA = 30, 31
W_ONE = 3 * H * DFF * L
OTHER = 1_600_000_000_000 - 384 * W_ONE
E = math.ceil((1e13 - OTHER) / W_ONE)
TOTAL = E * W_ONE + OTHER
HBM_CAP = 96e9
HBM_BW = 4e12 * 0.80
PEAK = 486e12 * 0.70
D2D_PEAK = 3.2e12 / 8
D2D = D2D_PEAK * 0.80
P2P = min(D2D_PEAK, (NODE - 1) * (400e9 / 8)) * 0.80
PARAM_PEAK = 400e9 / 8
PARAM = PARAM_PEAK * 0.80
PREFIX = {"25": PARAM_PEAK * 0.25, "100": PARAM_PEAK}
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

STAGES = (
    ("pull", "拉 KV", "1B4F8A"),
    ("idx", "CSA indexer", "1F8A70"),
    ("hca", "HCA", "7D5BA6"),
    ("core", "稀疏核心", "C48A2A"),
    ("proj", "投影", "5C6B73"),
    ("ar", "AllReduce", "E07A3D"),
    ("disp", "MoE dispatch", "3D7A4A"),
    ("gemm", "MoE GEMM", "D4546A"),
    ("comb", "MoE combine", "2A6F97"),
)

SLIDES = 5
FOOTER = "A5    ·    10T    ·    128 卡 TP=8 EP=128    ·    无 DDR 池    ·    99.95% KV 命中    ·    486T×70%"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY = ui.NAVY
DOC = "/agent/repos/ucl-mpcomm/docs/A5-10T-P-D-无DDR池-99.95KV命中.md"
PPT = "/agent/repos/ucl-mpcomm/docs/A5-10T-P-D-无DDR池-99.95KV命中.pptx"


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def store(s):
    return s * BPT + FIXED


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
    return {"t": td + max(tw, tg) + tc, "tw": tw, "tg": tg, "td": td, "tc": tc, "hot": hot, "e": e_hot}


def prefill(bs, s, prefix):
    n = math.ceil(bs / DP)
    p, q = HIT * s, (1 - HIT) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    flops = {
        "idx": N_CSA * 4096 * context,
        "hca": N_HCA * 2048 * context,
        "core": N_CSA * 262144 * (1024 + 128) * q,
        "proj": PROJ * q,
    }
    scale = n / (TP * PEAK * align(rows))
    t_pull = n * (p * BPT + L * min(p, 128) * 576) / (TP * prefix)
    t_hbm = (ATTN / TP + n * (store(s) + q * BPT) / TP) / HBM_BW
    t_ar = L * (COLL + 2 * (TP - 1) / TP * rows * H * 2 / P2P)
    moe = expert(bs * q)
    t_compute = sum(flops.values()) * scale
    body = t_pull + max(t_hbm, t_compute) + t_ar + moe["t"]
    t_pd = n * store(s) / (TP * PARAM)
    tail = max(0.0, t_pd - body * (L - 1) / L)
    parts = {
        "pull": t_pull,
        "idx": flops["idx"] * scale,
        "hca": flops["hca"] * scale,
        "core": flops["core"] * scale,
        "proj": flops["proj"] * scale,
        "ar": t_ar,
        "disp": moe["td"],
        "gemm": moe["tg"],
        "comb": moe["tc"],
    }
    return {
        "t": body + tail,
        "parts": parts,
        "hbm": t_hbm,
        "weight": moe["tw"],
        "tail": tail,
        "n": n,
        "q": q,
        "kv": n * store(s) / TP,
        "compute": t_compute,
    }


def search_prefill(s, prefix, limit=10.0):
    def ok(bs):
        return prefill(bs, s, prefix)["t"] <= limit + 1e-9

    if not ok(1):
        return 0, prefill(1, s, prefix)
    lo, hi = 1, 2
    while ok(hi) and hi < 30_000_000:
        lo, hi = hi, hi * 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo, prefill(lo, s, prefix)


def n_csa_read(s):
    sel = min(1024.0, s / 4.0)
    return N_CSA * (s / 4.0) * 64 + N_HCA * (s / 128.0) * 576 + N_CSA * sel * 576 + FIXED


def decode(bs, s):
    n = math.ceil(bs / DP)
    sel = min(1024.0, s / 4.0)
    score = N_CSA * 4096 * s + N_HCA * 2048 * s + N_CSA * 262144 * (sel + 128)
    if bs * store(s) > ROOM + 1.0:
        return None
    read = n * n_csa_read(s) / TP
    t_hbm = (read + ATTN / TP) / HBM_BW
    t_ca = n * (score + PROJ) / (TP * PEAK * align(n))
    t_ar = L * (COLL + 2 * (TP - 1) / TP * n * H * 2 / P2P)
    moe = expert(float(bs))
    return {
        "t": max(t_ca, t_hbm) + t_ar + moe["t"],
        "ca": t_ca,
        "hbm": t_hbm,
        "ar": t_ar,
        "moe": moe["t"],
        "gemm": moe["tg"],
        "disp": moe["td"],
        "comb": moe["tc"],
        "n": n,
    }


def search_decode(s, limit):
    cap = int(ROOM // store(s))

    def ok(bs):
        if bs > cap:
            return False
        row = decode(bs, s)
        return row is not None and row["t"] <= limit + 1e-12

    if cap < 1 or not ok(1):
        return 0, cap, None
    lo, hi = 1, 2
    while ok(hi) and hi < cap:
        lo, hi = hi, min(cap, hi * 2)
    if hi > cap:
        hi = cap
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    while lo < cap and ok(lo + 1):
        lo += 1
    return lo, cap, decode(lo, s)


def collect():
    rows = []
    for s in LENGTHS:
        item = {"S": s, "cap": int(ROOM // store(s))}
        for name, bw in PREFIX.items():
            bs, row = search_prefill(s, bw)
            item[name] = {"bs": bs, "row": row}
        dec = {}
        for limit in LIMITS:
            bs, cap, row = search_decode(s, limit)
            dec[limit] = {"bs": bs, "cap": cap, "row": row}
        item["dec"] = dec
        rows.append(item)
    return rows


def fmt_len(s):
    return f"{s // 1024}K" if s < 1048576 else f"{s // 1048576}M"


def fmt_bs(n):
    return f"{int(n):,}"


def dur(v):
    if v >= 1:
        return f"{v:.2f} 秒"
    return f"{v * 1e3:.0f} 毫秒"


def shares(parts, total):
    raw = [parts[key] / total * 100 for key, _, _ in STAGES]
    shown = [math.floor(v * 10 + 1e-9) / 10 for v in raw]
    leftover = int(round(1000 - sum(int(round(v * 10)) for v in shown)))
    order = sorted(range(len(raw)), key=lambda i: (raw[i] * 10) - math.floor(raw[i] * 10 + 1e-9), reverse=True)
    for i in order:
        if leftover <= 0:
            break
        shown[i] = round(shown[i] + 0.1, 1)
        leftover -= 1
    return shown


def add_pie(slide, cx, cy, r, slices):
    total = sum(v for v, _ in slices if v > 0)
    theta = 0.0
    for value, color in slices:
        if value <= 0 or total <= 0:
            continue
        sweep = 360.0 * value / total
        if sweep >= 0.4:
            steps = max(2, int(math.ceil(sweep / 6)))
            pts = [(cx, cy)]
            for i in range(steps + 1):
                ang = math.radians(theta + sweep * i / steps)
                pts.append((cx + r * math.sin(ang), cy - r * math.cos(ang)))
            builder = slide.shapes.build_freeform(Inches(pts[0][0]), Inches(pts[0][1]))
            builder.add_line_segments([(Inches(x), Inches(y)) for x, y in pts[1:]], close=True)
            ui.solid(builder.convert_to_shape(), color)
        theta += sweep


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "10T 只增加路由专家", "A5    ·    模型    ·    V4-Pro 1.6T 外推")
    ui.banner(slide, 0.92, "DeepSeek 没有发布 10T。层数、隐藏维、中间维、TopK 保持 1.6T，专家个数对齐到 10^13。")
    head = ["项目", "取值"]
    body = [
        ["名义 / 整数参数", "1.000×10^13；整数和 10,001,877,729,280，多 1.878×10^8"],
        ["层 / 隐藏 / 中间维", "61 / 7168 / 3072。单个专家 4.030×10^9 = 3×7168×3072×61"],
        ["路由", "2469 个专家。TopK=6。前 3 层按 token id 哈希，其后 top-6"],
        ["共享专家", "每层 1 个，FP8，每卡一份 4.030 GB"],
        ["注意力", "前 2 层 HCA，其后交错。30 CSA + 31 HCA。压缩 4 / 128，CSA 最多 1024"],
        ["KV", "每 token 4939.5 字节。滑窗 61×128×576 = 4,497,408 字节"],
        ["精度", "路由 FP4。共享专家和注意力 FP8。TP AllReduce 的 hidden 为 BF16"],
        ["MoE 通信", "dispatch FP8，每元素 1 字节。combine BF16，每元素 2 字节"],
        ["其余", "激活参数 4.9×10^10。词表 129,280。上下文 1,048,576。mHC 展开 4，MTP 深度 1"],
    ]
    kinds = ["head"] + ["body"] * len(body)
    ui.add_table(slide, 0.42, 1.48, [2.55, 10.0], [head] + body, [0.32] + [0.42] * len(body), kinds, size=13)
    ui.gold(slide, 5.70, 1.28, "命中率按本场景取 99.95%。命中的 prefix 不在本副本上，经参数面拉取。\n现算部分是 0.05% 的新 token。Query、128 头、头维 512、压缩维 1536 沿用 V4-Pro。", 14)


def slide_cluster(prs, blank, rows):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "128 卡切分两种带宽相同", "A5    ·    集群与并行    ·    去掉 108T    ·    无 DDR 池")
    ui.banner(slide, 0.92, "一份 128 卡副本。Attention TP=8、DP=16，MoE EP=128。只改拉 KV。批量各自摸到 TTFT ≤ 10 秒。")
    head = ["项目", "两种带宽都用这一套"]
    body = [
        ["副本", "128 卡超节点，每机 8 卡。一条请求不跨副本"],
        ["Attention", "TP=8，留在 8 卡 fullmesh。DP=16"],
        ["MoE", "EP=128。每卡 19.29 个专家。dispatch / combine 走 D2D"],
        ["算力", "486T × 70% = 340.2 TFLOP/s。不含 108T 增量核"],
        ["HBM", "96 GB。4 TB/s × 80% = 3.20 TB/s。预留 6 GB"],
        ["参数面", "每卡 400 Gb/s，物理 50 GB/s。P→D 取 80%，每卡 40 GB/s"],
        ["交换 / AllReduce", "D2D 3.2 Tb/s × 80% = 320 GB/s。AllReduce 用机内 280 GB/s"],
        ["启动项", "AllReduce、dispatch、combine 每层各付 5 微秒"],
    ]
    kinds = ["head"] + ["key" if i == 3 else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.46, [2.45, 10.1], [head] + body, [0.30] + [0.32] * 8, kinds, size=13)
    head2 = ["输入", "25% 批", "25% TTFT", "25% KV/卡", "100% 批", "100% TTFT", "100% KV/卡"]
    body2, kinds2 = [], ["head"]
    for row in rows:
        kinds2.append("body")
        d25, d100 = row["25"]["row"], row["100"]["row"]
        body2.append([
            fmt_len(row["S"]),
            fmt_bs(row["25"]["bs"]),
            dur(d25["t"]),
            f"{d25['kv'] / 1e9:.1f} GB",
            fmt_bs(row["100"]["bs"]),
            dur(d100["t"]),
            f"{d100['kv'] / 1e9:.1f} GB",
        ])
    ui.add_table(slide, 0.42, 4.55, [1.15, 1.55, 1.70, 1.85, 1.70, 1.85, 2.15], [head2] + body2, [0.30] + [0.30] * 4, kinds2, size=12)
    ui.gold(slide, 6.15, 0.90, "摸高只看 TTFT ≤ 10 秒。无 DDR 池时，每卡扣掉权重和 6 GB 预留后只剩 44.69 GB。上表每卡 KV 都超过这 44.69 GB，这批在 HBM 里放不下。", 13)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "TTFT 与 TPOT 的汇总式", "A5    ·    公式    ·    饼图各段相加等于 TTFT")
    ui.banner(slide, 0.92, "HBM 访存被 Attention 计算盖住，专家权重读取被 GEMM 盖住，P→D 尾巴是 0。这三项不进饼。")
    left = (
        "Prefill，n = ⌈全局批 / 16⌉，p = 0.9995S，q = 0.0005S\n"
        "T_pull = n × (p×4939.5 + 61×min(p,128)×576) / (8×BW)\n"
        "BW = 12.5 GB/s 或 50 GB/s，不另乘 80%\n"
        "T_compute = n × (F_idx+F_hca+F_core+F_proj) / (8×340.2×10^12×align)\n"
        "F_idx = 30×4096×C，F_hca = 31×2048×C，C = q×p + q(q+1)/2\n"
        "F_core = 30×262144×1152×q，F_proj = 3.87×10^10×q\n"
        "T_AR = 61 × (5×10^-6 + 1.75×n×q×7168×2 / 280 GB/s)\n"
        "T_dispatch = 61 × (5×10^-6 + hot×7168×1 / 320 GB/s)\n"
        "T_combine = 61 × (5×10^-6 + hot×7168×2 / 320 GB/s)\n"
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine\n"
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail"
    )
    right = (
        "Decode，无 DDR 池，没有换入项\n"
        "容量：全局批 × K(S) ≤ 5.720×10^12 字节\n"
        "K(S) = 4939.5×S + 4,497,408\n"
        "sel = min(1024, S/4)\n"
        "Read = 30×(S/4)×64 + 31×(S/128)×576 + 30×sel×576 + 滑窗\n"
        "T_HBM = (n×Read/8 + 19.35×10^9/8) / 3.20 TB/s\n"
        "F_score = 30×4096×S + 31×2048×S + 30×262144×(sel+128)\n"
        "T_compute = n × (F_score + 3.87×10^10) / (8×340.2×10^12×align(n))\n"
        "T_AR、T_MoE 与 Prefill 同一套，token 数改为全局批\n"
        "TPOT = max(T_HBM, T_compute) + T_AR + T_MoE\n"
        "10 毫秒和 30 毫秒都再受上面的 HBM 容量截断"
    )
    for x, title, text in ((0.42, "TTFT", left), (6.88, "TPOT", right)):
        box = slide.shapes.add_shape(ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.48), Inches(6.05), Inches(5.50))
        ui.solid(box, "F4F7FA")
        ui.textbox(slide, x + 0.18, 1.58, 5.70, 0.32, title, 16, True, NAVY, anchor=ui.MSO_ANCHOR.TOP)
        ui.textbox(slide, x + 0.18, 1.96, 5.70, 4.80, text, 12, False, ui.INK, anchor=ui.MSO_ANCHOR.TOP)


def panel(slide, x, y, w, title, detail):
    pct = shares(detail["parts"], detail["t"])
    ui.textbox(slide, x, y, w, 0.28, title, 13, True, NAVY, PP_ALIGN.LEFT)
    add_pie(slide, x + 1.15, y + 1.48, 0.90, [(detail["parts"][key], color) for key, _, color in STAGES])
    items = []
    for (key, name, color), share in zip(STAGES, pct):
        items.append((color, f"{share:4.1f}%   {name}   {dur(detail['parts'][key])}"))
    ui.add_key(slide, x + 2.22, y + 0.36, w - 2.30, items, size=11, row=0.24)


def slide_pies(prs, blank, rows, page, title, lengths):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, "TTFT ≤ 10 秒摸高    ·    左 25%    ·    右 100%    ·    颜色表示同一阶段")
    ui.banner(slide, 0.90, "各自摸到 TTFT ≤ 10 秒。扇区加总等于该带宽自己的 TTFT。100% 的批更大，AllReduce 和 MoE 的秒数跟着变长。")
    by = {row["S"]: row for row in rows}
    slots = ((0.32, 1.40), (6.78, 1.40), (0.32, 4.22), (6.78, 4.22))
    pairs = []
    for s in lengths:
        for name in ("25", "100"):
            pairs.append((s, name, by[s][name]))
    for (x, y), (s, rate, item) in zip(slots, pairs):
        panel(
            slide, x, y, 6.20,
            f"{fmt_len(s)}  ·  拉 KV {rate}%  ·  批 {fmt_bs(item['bs'])}  ·  TTFT {dur(item['row']['t'])}",
            item["row"],
        )


def write_md(rows):
    lines = [
        "# A5-10T-P-D-无DDR池-99.95KV命中",
        "",
        "10T Prefill / Decode 仿真口径。Prefill 固定 128 卡超节点，去掉 108T 增量核，其余沿用已保存的 96 GB / 486T 集群和 TP=8、DP=16、EP=128。无 DDR 池。KV 命中率 99.95%。",
        "",
        "两种拉 KV 带宽是参数面物理 50 GB/s 的 25% 和 100%，每卡 12.5 GB/s 和 50 GB/s，不另乘 80%。P→D 仍是每卡 40 GB/s。Prefill 的全局批按 TTFT ≤ 10 秒各自摸高。无 DDR 池时每卡只剩 44.69 GB 放 KV，这些摸高批都超过这个容量。",
        "",
        "## 1. 模型",
        "",
        "骨架是论文 V4-Pro 1.6T。10T 只增加路由专家。DeepSeek 没有发布这一档。",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        "| 名义总参数 | 1.000×10^13 |",
        f"| 整数总参数 | {TOTAL} |",
        "| 层数 / 隐藏维 / 专家中间维 | 61 / 7168 / 3072 |",
        "| 路由专家 | 2469 |",
        "| 单个专家参数 | 4,029,677,568 = 3×7168×3072×61 |",
        "| TopK | 6。前 3 层按 token id 哈希，其后 top-6 |",
        "| 每层共享专家 | 1 |",
        "| 激活参数 | 4.9×10^10 |",
        "| 注意力 | 30 层 CSA + 31 层 HCA。前 2 层 HCA，其后交错 |",
        "| CSA / HCA 压缩 | 4 / 128。Decode 一步 CSA 最多 1024 条 |",
        "| latent / indexer | 576 字节 / 64 字节。576 已是 K/V 合并 |",
        "| 滑窗 | 128 token，61×128×576 = 4,497,408 字节 |",
        "| 每 token KV | 4939.5 字节 = 30×(576/4+64/4) + 31×(576/128) |",
        "| 存量 | K(S) = 4939.5×S + 4,497,408 |",
        "| Query | 128 头，头维 512，压缩维 1536 |",
        "| 词表 / 上下文 | 129,280 / 1,048,576 |",
        "| mHC / MTP | 残差展开 4，MTP 深度 1 |",
        "| 路由专家 | FP4，整表 4,974,636,957,696 字节 |",
        "| 共享专家 / 注意力 | FP8，4,029,677,568 / 19,350,000,000 字节 |",
        "| AllReduce hidden | BF16，2 字节 |",
        "| MoE dispatch / combine | FP8 每元素 1 字节 / BF16 每元素 2 字节 |",
        "",
        "## 2. 集群",
        "",
        "带宽有效值 = 标称 × 80%，拉 KV 除外。1 GB = 10^9 字节。",
        "",
        "| 项 | 标称 | 有效 |",
        "| --- | --- | --- |",
        "| 张量算力 | 486 TFLOP/s | 340.2 TFLOP/s（×0.70）。不含 108T |",
        "| HBM 容量 | 96 GB | 扣权重和 6 GB 预留后每卡 44.69 GB 给 KV |",
        "| HBM 带宽 | 4 TB/s | 3.20 TB/s |",
        "| D2D | 3.2 Tb/s | 320 GB/s |",
        "| 机内 fullmesh | 7×400 Gb/s，聚合峰值 350 GB/s | 280 GB/s |",
        "| 参数面 | 每卡 400 Gb/s，物理 50 GB/s | P→D 40 GB/s |",
        "| 拉 KV 25% | 物理 50 GB/s 的 25% | 12.5 GB/s，不叠乘 80% |",
        "| 拉 KV 100% | 物理 50 GB/s | 50 GB/s，不叠乘 80% |",
        "| 集合通信启动 | 每层每次 5 µs | AllReduce、dispatch、combine 各付一次 |",
        "",
        "每卡权重 = 路由 FP4 / 128 + 共享 FP8 + 注意力 FP8 / 8 = 45.31 GB。副本 KV 上限 5.720 TB。无 DDR 池，超出这个上限的批量不能跑。",
        "",
        "## 3. 并行",
        "",
        "一份副本 128 卡。Attention TP=8，DP=16，TP 组留在 8 卡 fullmesh。MoE EP=128，每卡 19.29 个专家，dispatch 和 combine 走 D2D。一条请求不跨副本。",
        "",
        "25% 和 100% 用同一套切分、同一套集群、同一套算力。差别只有拉 KV 带宽。",
        "",
        "## 4. 公式",
        "",
        "n = ⌈全局批 / 16⌉。命中 p = 0.9995×S，现算 q = 0.0005×S。align(m) = m / (⌈m/16⌉×16)。",
        "",
        "Prefill 的计算上下文 C = q×p + q×(q+1)/2。",
        "",
        "```",
        "F_idx  = 30 × 4096 × C",
        "F_hca  = 31 × 2048 × C",
        "F_core = 30 × 262144 × (1024+128) × q",
        "F_proj = 2 × 1.935×10^10 × q",
        "T_pull = n × (p×4939.5 + 61×min(p,128)×576) / (8 × BW)",
        "T_compute = n × (F_idx + F_hca + F_core + F_proj) / (8 × 3.402×10^14 × align(n×q))",
        "T_HBM = (1.935×10^10/8 + n×(K(S) + q×4939.5)/8) / 3.20×10^12",
        "T_AR = 61 × (5×10^-6 + 2×7/8 × n×q × 7168 × 2 / 2.80×10^11)",
        "T_dispatch = 61 × (5×10^-6 + hot × 7168 × 1 / 3.20×10^11)",
        "T_combine  = 61 × (5×10^-6 + hot × 7168 × 2 / 3.20×10^11)",
        "T_weight = (e_hot × 4.030×10^9 × 0.5 + 4.030×10^9) / 3.20×10^12",
        "T_gemm = (routed_rows + shared_rows) × 6 × 7168 × 3072 × 61 / 3.402×10^14",
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine",
        "T_Attention = T_pull + max(T_HBM, T_compute) + T_AR",
        "T_PD = n × K(S) / (8 × 4.0×10^10)",
        "T_tail = max(0, T_PD - (T_Attention + T_MoE) × 60/61)",
        "TTFT = T_Attention + T_MoE + T_tail",
        "```",
        "",
        "hot 是 EP=128 上最忙卡的指派次数，mean + 2σ，且不超过 tokens×6。routed_rows 按每个活跃专家向上取整到 16。",
        "",
        "本场景四档都是 T_HBM < T_compute，T_weight < T_gemm，T_tail = 0。饼图九段是 T_pull、T_idx、T_hca、T_core、T_proj、T_AR、T_dispatch、T_gemm、T_combine，相加等于 TTFT。",
        "",
        "Decode 无换入项。容量约束是全局批 × K(S) ≤ 5.720×10^12。",
        "",
        "```",
        "sel = min(1024, S/4)",
        "Read = 30×(S/4)×64 + 31×(S/128)×576 + 30×sel×576 + 4,497,408",
        "F_score = 30×4096×S + 31×2048×S + 30×262144×(sel+128)",
        "T_HBM = (n × Read / 8 + 1.935×10^10 / 8) / 3.20×10^12",
        "T_compute = n × (F_score + 3.87×10^10) / (8 × 3.402×10^14 × align(n))",
        "T_AR、T_MoE 与 Prefill 同一套，现算 token 数改为全局批",
        "TPOT = max(T_HBM, T_compute) + T_AR + T_MoE",
        "```",
        "",
        "## 5. Prefill 批量",
        "",
        "每种带宽各自把全局批摸到 TTFT ≤ 10 秒，搜索不再用 HBM 容量截断。无 DDR 池时每卡只剩 44.69 GB 放 KV，下表的每卡 KV 都超过这个数，这批在卡上放不下。",
        "",
        "| 输入 | 25% 批 | 25% 每卡 | 25% TTFT | 25% KV/卡 | 100% 批 | 100% 每卡 | 100% TTFT | 100% KV/卡 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        d25, d100 = row["25"]["row"], row["100"]["row"]
        lines.append(
            f"| {fmt_len(row['S'])} | {row['25']['bs']} | {row['25']['bs'] / N:.2f} | {d25['t']:.3f} 秒 | {d25['kv'] / 1e9:.1f} GB | {row['100']['bs']} | {row['100']['bs'] / N:.2f} | {d100['t']:.3f} 秒 | {d100['kv'] / 1e9:.1f} GB |"
        )
    lines += [
        "",
        "## 6. 各段占 TTFT",
        "",
        "百分比按最大余数修到一位小数，九段相加为 100%。秒数是该段在各自 10 秒摸高批上的耗时。",
        "",
    ]
    for row in rows:
        lines.append(f"### {fmt_len(row['S'])}，25% 批 {row['25']['bs']}，100% 批 {row['100']['bs']}")
        lines.append("")
        lines.append("| 阶段 | 25% 耗时 | 25% 占比 | 100% 耗时 | 100% 占比 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        p25 = shares(row["25"]["row"]["parts"], row["25"]["row"]["t"])
        p100 = shares(row["100"]["row"]["parts"], row["100"]["row"]["t"])
        for i, (key, name, _) in enumerate(STAGES):
            a = row["25"]["row"]["parts"][key]
            b = row["100"]["row"]["parts"][key]
            lines.append(f"| {name} | {a:.4f} 秒 | {p25[i]:.1f}% | {b:.4f} 秒 | {p100[i]:.1f}% |")
        lines.append("")
        lines.append(
            f"未进饼：HBM {row['25']['row']['hbm']*1e3:.2f} 毫秒，专家权重 {row['25']['row']['weight']*1e3:.2f} 毫秒，尾巴 {row['25']['row']['tail']*1e3:.2f} 毫秒。"
        )
        lines.append("")
    lines += [
        "## 7. Decode",
        "",
        "无 DDR 池。10 毫秒和 30 毫秒各自在 HBM 容量内摸高。容量先满时，TPOT 会停在约束下面。",
        "",
        "| 输入 | HBM 上限批 | 10 毫秒批 | 10 毫秒 TPOT | 30 毫秒批 | 30 毫秒 TPOT |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        d10, d30 = row["dec"][0.010], row["dec"][0.030]
        lines.append(
            f"| {fmt_len(row['S'])} | {d10['cap']} | {d10['bs']} | {d10['row']['t']*1e3:.2f} 毫秒 | {d30['bs']} | {d30['row']['t']*1e3:.2f} 毫秒 |"
        )
    lines += [
        "",
        "10 毫秒四档都由时间摸高，批量低于 HBM 上限。256K、512K、1M 的 30 毫秒批量贴住 HBM 上限，TPOT 分别是 27.01、23.28、22.12 毫秒。",
        "",
    ]
    text = "\n".join(lines)
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write(text)


def audit(prs):
    wide, low = Inches(13.333), Inches(7.50)
    bad = []
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.left is None:
                continue
            if shape.left + shape.width > wide + Emu(40000) or shape.top + shape.height > low + Emu(40000):
                bad.append((i, int(shape.left), int(shape.top), int(shape.width), int(shape.height)))
            if shape.top < 0 or shape.left < 0:
                bad.append((i, "neg", int(shape.left), int(shape.top)))
    return bad


def main():
    rows = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "A5 10T：无 DDR 池，99.95% KV 命中"
    blank = prs.slide_layouts[6]
    slide_model(prs, blank)
    slide_cluster(prs, blank, rows)
    slide_formula(prs, blank)
    slide_pies(prs, blank, rows, 4, "10 秒摸高：128K 和 256K 拉 KV 仍是最大一块", (131072, 262144))
    slide_pies(prs, blank, rows, 5, "10 秒摸高：512K 和 1M 计算占比上升", (524288, 1048576))
    prs.save(PPT)
    write_md(rows)
    bad = audit(prs)
    print(PPT)
    print("overflow", len(bad))
    for item in bad[:12]:
        print(item)
    for row in rows:
        print(fmt_len(row["S"]), row["25"]["bs"], f"{row['25']['row']['t']:.3f}", f"{row['100']['row']['t']:.3f}", shares(row["25"]["row"]["parts"], row["25"]["row"]["t"]))


if __name__ == "__main__":
    main()
