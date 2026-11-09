#!/usr/bin/env python3
"""TTFT mix for the 2026-11-06 afternoon N+2 comparison.

That deck keeps one 256-GPU replica, TP=8, EP=256, and only changes
the prefix-pull rate from 25% to 100% of the 800 Gb/s parameter plane.
Each pie is the 10 s batch for that rate. Slices are the attention and
MoE stages on the critical path, so they add up to TTFT.
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

N, NODE = 256, 8
TP = 8
DP = N // TP
L, H, DFF, TOPK = 61, 7168, 3072, 6
N_CSA, N_HCA = 30, 31
W_ONE = 3 * H * DFF * L
OTHER = 1_600_000_000_000 - 384 * W_ONE
E = math.ceil((2e13 - OTHER) / W_ONE)
HBM_BW = 33e12 * 0.80
PEAK = 48e15 * 0.70
D2D = 48e12 / 8 * 0.80
P2P = (NODE - 1) * (1.6e12 / 8) * 0.80
PARAM_PEAK = 800e9 / 8
PREFIX_25 = PARAM_PEAK * 0.25
PREFIX_100 = PARAM_PEAK
COLL = 5e-6
ATTN = 19.35e9
SHARED = float(W_ONE)
BPT = N_CSA * (576 / 4 + 64 / 4) + N_HCA * (576 / 128)
FIXED = L * 128 * 576
PROJ = ATTN * 2
HIT = 0.995
LENGTHS = (65536, 131072, 262144, 524288, 1048576, 2097152, 4194304)
SHOWN = (65536, 262144, 1048576, 4194304)

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

SLIDES = 3
FOOTER = "N+2    ·    2026-11-06 下午    ·    20T    ·    256 卡 TP=8 EP=256    ·    拉 KV 25% 与 100%    ·    TTFT ≤ 10 秒"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY = ui.NAVY


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def expert(tokens):
    tokens = max(float(tokens), 0.0)
    mean = tokens * TOPK / N
    hot = min(tokens * TOPK, mean + 2 * math.sqrt(max(mean * (1 - 1 / N), 0.0)))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / N
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_rows = e_hot * math.ceil(tpe / 16) * 16 if e_hot else 0.0
    shared_rows = math.ceil(max(1, math.ceil(tokens / N)) / 16) * 16
    t_w = (e_hot * W_ONE * 0.5 + SHARED) / HBM_BW
    t_g = (routed_rows + shared_rows) * 6 * H * DFF * L / PEAK
    t_d = L * (COLL + hot * H * 1 / D2D)
    t_c = L * (COLL + hot * H * 2 / D2D)
    return {"t": t_d + max(t_w, t_g) + t_c, "tw": t_w, "tg": t_g, "td": t_d, "tc": t_c}


def breakdown(bs, s, prefix):
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
    prefix_bytes = p * BPT + L * min(p, 128) * 576
    store = s * BPT + FIXED
    t_pull = n * prefix_bytes / (TP * prefix)
    t_hbm = (ATTN / TP + n * (store + q * BPT) / TP) / HBM_BW
    t_ar = L * (COLL + 2 * (TP - 1) / TP * rows * H * 2 / P2P)
    moe = expert(bs * q)
    t_compute = sum(flops.values()) * scale
    body = t_pull + max(t_hbm, t_compute) + t_ar + moe["t"]
    t_pd = n * store / (TP * (PARAM_PEAK * 0.80))
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
    total = sum(parts.values()) + tail
    return {
        "t": body + tail,
        "parts": parts,
        "hbm": t_hbm,
        "weight": moe["tw"],
        "tail": tail,
        "total": total,
        "q": q,
    }


def search(s, prefix, limit=10.0):
    def ok(bs):
        return breakdown(bs, s, prefix)["t"] <= limit + 1e-9

    lo, hi = 1, 2
    while ok(hi) and hi < 20_000_000:
        lo, hi = hi, hi * 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo, breakdown(lo, s, prefix)


def collect():
    rows = []
    for s in LENGTHS:
        b25, d25 = search(s, PREFIX_25)
        b100, d100 = search(s, PREFIX_100)
        rows.append({"S": s, "b25": b25, "d25": d25, "b100": b100, "d100": d100})
    return rows


def fmt_len(s):
    if s >= 1048576 and s % 1048576 == 0:
        return f"{s // 1048576}M"
    return f"{s // 1024}K"


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


def slide_config(prs, blank, rows):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "切分和集群相同，只改拉 KV", "2026-11-06 下午    ·    N+2 20T    ·    25% 与 100% 对照")
    ui.banner(slide, 0.92, "一份 256 卡副本。Attention TP=8、DP=32，MoE EP=256。两种带宽各自在 TTFT ≤ 10 秒下摸高批量。")
    head = ["项目", "25% 和 100% 都用这一套"]
    body = [
        ["模型", "20T 外推。61 层，隐藏 7168，中间维 3072，TopK=6，路由专家 4951"],
        ["注意力", "30 层 CSA + 31 层 HCA。TP=8，留在 8 卡 fullmesh"],
        ["MoE", "EP=256。dispatch 每元素 1 字节，combine 每元素 2 字节"],
        ["副本", "Prefill 和 Decode 都铺满 256 卡，单条请求不跨副本"],
        ["算力 / HBM", "48P ×70% = 33.60 P。HBM 640 GB，33 TB/s ×80% = 26.40 TB/s"],
        ["参数面", "每卡 800 Gb/s，物理 100 GB/s。P→D 取 80%，每卡 80 GB/s"],
        ["交换 / AllReduce", "D2D 48 Tb/s ×80% = 4.80 TB/s。AllReduce 用机内 1.12 TB/s"],
        ["命中", "99.5%。拉 KV 取物理带宽的 25% 或 100%，不另乘 80%"],
    ]
    kinds = ["head"] + ["key" if i == 7 else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.40, [2.35, 10.15], [head] + body, [0.30] + [0.32] * 8, kinds, size=12)
    head2 = ["输入", "25% 批", "25% TTFT", "100% 批", "100% TTFT", "25% 拉KV", "100% 拉KV"]
    body2, kinds2 = [], ["head"]
    for row in rows:
        if row["S"] not in SHOWN:
            continue
        kinds2.append("key" if row["S"] in (65536, 4194304) else "body")
        body2.append([
            fmt_len(row["S"]),
            fmt_bs(row["b25"]),
            dur(row["d25"]["t"]),
            fmt_bs(row["b100"]),
            dur(row["d100"]["t"]),
            f"{shares(row['d25']['parts'], row['d25']['t'])[0]:.1f}%",
            f"{shares(row['d100']['parts'], row['d100']['t'])[0]:.1f}%",
        ])
    ui.add_table(slide, 0.42, 4.42, [1.15, 1.70, 1.70, 1.85, 1.85, 1.85, 2.40], [head2] + body2, [0.28] + [0.28] * len(body2), kinds2, size=12)
    ui.gold(
        slide,
        6.00,
        1.05,
        "饼图用上面四档的摸高批。128K、512K、2M 落在相邻两档之间。\n"
        "HBM 访存被 Attention 计算盖住，专家权重读取被 GEMM 盖住，P→D 尾巴是 0。这三项不进饼，饼内各段相加等于 TTFT。",
        13,
    )


def panel(slide, x, y, w, h, title, detail):
    pct = shares(detail["parts"], detail["t"])
    ui.textbox(slide, x, y, w, 0.28, title, 13, True, NAVY, PP_ALIGN.LEFT)
    add_pie(
        slide,
        x + 1.20,
        y + 1.48,
        0.92,
        [(detail["parts"][key], color) for key, _, color in STAGES],
    )
    items = []
    for (key, name, color), share in zip(STAGES, pct):
        items.append((color, f"{share:4.1f}%   {name}   {dur(detail['parts'][key])}"))
    ui.add_key(slide, x + 2.30, y + 0.36, w - 2.40, items, size=11, row=0.25)


def slide_pies(prs, blank, rows, page, title, lengths):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, "关键路径各段 ÷ TTFT    ·    左 25%    ·    右 100%    ·    颜色表示同一阶段")
    ui.banner(slide, 0.90, "扇区加总等于 TTFT。秒数随各自的 10 秒批量变化，占比才是两种带宽的对照。")
    by = {row["S"]: row for row in rows}
    slots = ((0.32, 1.40), (6.78, 1.40), (0.32, 4.22), (6.78, 4.22))
    pairs = []
    for s in lengths:
        pairs.append((s, "25", by[s]["b25"], by[s]["d25"]))
        pairs.append((s, "100", by[s]["b100"], by[s]["d100"]))
    for (x, y), (s, rate, bs, detail) in zip(slots, pairs):
        panel(
            slide, x, y, 6.20, 2.70,
            f"{fmt_len(s)}  ·  拉 KV {rate}%  ·  批 {fmt_bs(bs)}  ·  TTFT {dur(detail['t'])}",
            detail,
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
            if shape.top < 0 or shape.left < 0:
                bad.append((i, "neg", int(shape.left), int(shape.top)))
    return bad


def main():
    rows = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2 20T：25% 与 100% 拉 KV 的 TTFT 组成"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank, rows)
    slide_pies(prs, blank, rows, 2, "64K 拉 KV 仍是大头，4M 上计算升上来", (65536, 4194304))
    slide_pies(prs, blank, rows, 3, "256K 和 1M 落在 64K 与 4M 之间", (262144, 1048576))
    out = "/agent/repos/ucl-mpcomm/docs/deepseek-20t-kv25-100-ttft-pie.pptx"
    prs.save(out)
    bad = audit(prs)
    print(out, "overflow", len(bad))
    for item in bad[:12]:
        print(item)
    for row in rows:
        if row["S"] in SHOWN:
            p25 = shares(row["d25"]["parts"], row["d25"]["t"])
            p100 = shares(row["d100"]["parts"], row["d100"]["t"])
            print(fmt_len(row["S"]), "25", row["b25"], p25, "100", row["b100"], p100)


if __name__ == "__main__":
    main()
