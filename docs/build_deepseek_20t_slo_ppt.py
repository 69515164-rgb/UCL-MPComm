#!/usr/bin/env python3
"""N+2: 20T DeepSeek on a 640 GB, 48P FP4, 256-GPU supernode.

The skeleton stays at the V4-Pro 1.6T shape. Only the routed-expert
count is raised, the same way the 10T deck went from 384 to 2469.
One replica is one 256-GPU supernode: attention TP=8 inside the
8-GPU fullmesh, MoE EP=256 on the switch. Prefill and decode replica
counts scale independently and do not change a single request's
TTFT or TPOT.

Communication and HBM use 80%. Prefix pull uses 25% of the physical
parameter-plane rate and does not stack another 80%. Tensor FLOPs
use 70% of the 48P FP4 peak for both attention and expert GEMM.
"""

from __future__ import annotations

import math

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

FONT = "Microsoft YaHei"
NAVY = "0E2A47"
ACCENT = "145A96"
TEAL = "0E7A76"
INK = "1C242E"
MUTED = "5A636E"
WHITE = "FFFFFF"
LINE = "D6DCE2"
SOFT = "F4F7FA"
HEAD = "0E2A47"
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"
AMBER = "C4841D"
DDR_COLOR = "C46B2C"

N, NODE = 256, 8
TP = 8
DP = N // TP
# Prefill replica: smallest multiple of the 8-GPU node whose 10 s batch is still time-limited.
PF_N = 24
PF_DP = PF_N // TP
L, H, DFF, TOPK = 61, 7168, 3072, 6
N_CSA, N_HCA = 30, 31
W_ONE = 3 * H * DFF * L
OTHER = 1_600_000_000_000 - 384 * W_ONE
E = math.ceil((2e13 - OTHER) / W_ONE)
TOTAL_PARAMS = E * W_ONE + OTHER

HBM_CAP = 640e9
HBM_BW = 33e12 * 0.80
PEAK = 48e15 * 0.70
D2D_PEAK = 48e12 / 8
D2D = D2D_PEAK * 0.80
P2P_LINK = 1.6e12 / 8
P2P = (NODE - 1) * P2P_LINK * 0.80
H2D_PEAK = 1.6e12 / 8
H2D = H2D_PEAK * 0.80
DDR_NODE = 2e12
DDR_SHARE = DDR_NODE * 0.80 / NODE
HOST = min(H2D, DDR_SHARE)
DDR_CAP = 768e9 / NODE
PARAM_PEAK = 800e9 / 8
PARAM = PARAM_PEAK * 0.80
PREFIX_25 = PARAM_PEAK * 0.25
PREFIX_100 = PARAM_PEAK
POOL_PEAK = 51.2e12 / 8
POOL = POOL_PEAK * 0.80
COLL = 5e-6

ATTN = 19.35e9
SHARED = float(W_ONE)
ROUTED = E * W_ONE * 0.5
RESERVE = 6e9
ROOM = N * (HBM_CAP - ROUTED / N - SHARED - ATTN / TP - RESERVE)
BPT = N_CSA * (576 / 4 + 64 / 4) + N_HCA * (576 / 128)
FIXED = L * 128 * 576
PROJ = ATTN * 2
HIT = 0.995
OUT_LEN = 512
LENGTHS = (65536, 131072, 262144, 524288, 1048576, 2097152, 4194304)
SLIDES = 13
FOOTER = "N+2    ·    20T 为外推    ·    640 GB / 48P FP4、一份 256 卡副本    ·    参数面 800 Gb/s    ·    拉 KV 25%    ·    张量 33.60 P"


def rgb(value):
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def set_run_font(run, size, bold, color):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    rpr = run._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        el = rpr.find(qn(f"a:{tag}"))
        if el is None:
            el = OxmlElement(f"a:{tag}")
            rpr.append(el)
        el.set("typeface", FONT)


def strip_shadow(shape):
    effect = shape._element.spPr.find(qn("a:effectLst"))
    if effect is not None:
        shape._element.spPr.remove(effect)


def solid(shape, fill, line=None):
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(1)
    strip_shadow(shape)


def textbox(slide, x, y, w, h, text, size, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    body = getattr(tf, "_txBody", None)
    if body is not None:
        body_pr = body.find(qn("a:bodyPr"))
        if body_pr is not None:
            body_pr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)
    return shape


def set_cell_fill(cell, color):
    tc_pr = cell._tc.get_or_add_tcPr()
    for child in list(tc_pr):
        if child.tag == qn("a:solidFill"):
            tc_pr.remove(child)
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", color)
    solid_fill.append(srgb)
    tc_pr.append(solid_fill)


def set_cell_borders(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        for child in list(tc_pr):
            if child.tag == qn(f"a:{edge}"):
                tc_pr.remove(child)
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", "6350")
        fill = OxmlElement("a:solidFill")
        srgb = OxmlElement("a:srgbClr")
        srgb.set("val", "D6DCE2")
        fill.append(srgb)
        ln.append(fill)
        tc_pr.append(ln)


def write_cell(cell, text, size, bold, color, align):
    tf = cell.text_frame
    tf.clear()
    tf.word_wrap = True
    cell.margin_left = Inches(0.05)
    cell.margin_right = Inches(0.05)
    cell.margin_top = Inches(0.03)
    cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, line in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def add_table(slide, x, y, widths, rows, heights, kinds, size=12):
    shape = slide.shapes.add_table(len(rows), len(widths), Inches(x), Inches(y), Inches(sum(widths)), Inches(sum(heights)))
    table = shape.table
    table.horz_banding = False
    table.vert_banding = False
    tbl_pr = shape._element.graphic.graphicData.tbl.tblPr
    for child in list(tbl_pr):
        if child.tag == qn("a:tableStyleId"):
            tbl_pr.remove(child)
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    style = {
        "head": (HEAD, WHITE, True),
        "body": (WHITE, INK, False),
        "key": (PALE, TEAL, True),
        "sum": (SOFT, NAVY, True),
    }
    for r, (row, h, kind) in enumerate(zip(rows, heights, kinds)):
        table.rows[r].height = Inches(h)
        fill, color, bold = style[kind]
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            set_cell_fill(cell, HEAD if kind == "head" else (fill if c or kind != "body" else SOFT))
            if kind == "body" and c == 0:
                set_cell_fill(cell, SOFT)
            set_cell_borders(cell)
            this_color = NAVY if c == 0 and kind == "body" else color
            this_bold = True if c == 0 and kind != "head" else bold
            if kind in ("key", "sum", "head"):
                this_color = color
                this_bold = bold or c == 0
            write_cell(cell, text, size, this_bold, this_color, PP_ALIGN.LEFT)
    return shape


def chrome(slide, page, title, kicker):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.42, 0.16, 10.6, 0.28, kicker, 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 0.42, 0.42, 12.5, 0.42, title, 24, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 11.4, 0.18, 1.5, 0.26, f"{page}  /  {SLIDES}", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(slide, 0.42, 7.20, 12.5, 0.24, FOOTER, 11, False, MUTED, anchor=MSO_ANCHOR.MIDDLE)


def banner(slide, y, text, size=13):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(y), Inches(12.5), Inches(0.42))
    solid(shape, PALE)
    textbox(slide, 0.58, y, 12.18, 0.42, text, size, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)


def gold(slide, y, h, text, size=13):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(y), Inches(12.5), Inches(h))
    solid(box, GOLD_BG)
    textbox(slide, 0.58, y + 0.04, 12.18, h - 0.08, text, size, False, GOLD, anchor=MSO_ANCHOR.MIDDLE)


def add_pie(slide, cx, cy, r, slices):
    total = sum(v for v, _ in slices if v > 0.05)
    theta = 0.0
    for value, color in slices:
        if value <= 0.05 or total <= 0:
            continue
        sweep = 360.0 * value / total
        steps = max(2, int(math.ceil(sweep / 6)))
        pts = [(cx, cy)]
        for i in range(steps + 1):
            ang = math.radians(theta + sweep * i / steps)
            pts.append((cx + r * math.sin(ang), cy - r * math.cos(ang)))
        theta += sweep
        builder = slide.shapes.build_freeform(Inches(pts[0][0]), Inches(pts[0][1]))
        builder.add_line_segments([(Inches(x), Inches(y)) for x, y in pts[1:]], close=True)
        solid(builder.convert_to_shape(), color)


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def allreduce(rows):
    per = 2 * (TP - 1) / TP * rows * H * 2
    return L * (COLL + per / P2P)


def room_bytes(ngpu):
    per = HBM_CAP - ROUTED / ngpu - SHARED - ATTN / TP - RESERVE
    return per, ngpu * per


def expert(tokens, ngpu=None):
    gpu = N if ngpu is None else ngpu
    tokens = max(float(tokens), 0.0)
    mean = tokens * TOPK / gpu
    hot = min(tokens * TOPK, mean + 2 * math.sqrt(max(mean * (1 - 1 / gpu), 0.0)))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / gpu
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_rows = e_hot * math.ceil(tpe / 16) * 16 if e_hot else 0.0
    shared_rows = math.ceil(max(1, math.ceil(tokens / gpu)) / 16) * 16
    t_w = (e_hot * W_ONE * 0.5 + SHARED) / HBM_BW
    t_g = (routed_rows + shared_rows) * 6 * H * DFF * L / PEAK
    t_d = L * (COLL + hot * H * 1 / D2D)
    t_c = L * (COLL + hot * H * 2 / D2D)
    return {
        "t": t_d + max(t_w, t_g) + t_c,
        "tw": t_w,
        "tg": t_g,
        "td": t_d,
        "tc": t_c,
        "hot": hot,
        "e": e_hot,
    }


def store_seq(s):
    return s * BPT + FIXED


def n_csa_read(s):
    sel = min(1024.0, s / 4.0)
    return N_CSA * (s / 4.0) * 64 + N_HCA * (s / 128.0) * 576 + N_CSA * sel * 576 + FIXED


def prefill(bs, s, hit=HIT, prefix=PREFIX_25, ngpu=None):
    gpu = N if ngpu is None else ngpu
    n = math.ceil(bs / (gpu // TP))
    p, q = hit * s, (1 - hit) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    idx = N_CSA * 4096 * context
    hca = N_HCA * 2048 * context
    core = N_CSA * 262144 * (1024 + 128) * q
    proj = PROJ * q
    denom = TP * PEAK * align(rows)
    t_compute = n * (idx + hca + core + proj) / denom
    prefix_bytes = p * BPT + L * min(p, 128) * 576
    t_pull = n * prefix_bytes / (TP * prefix) if prefix else 0.0
    hbm_bytes = ATTN / TP + n * (store_seq(s) + q * BPT) / TP
    t_hbm = hbm_bytes / HBM_BW
    t_ar = allreduce(rows)
    moe = expert(bs * q, gpu)
    body = t_pull + max(t_hbm, t_compute) + t_ar + moe["t"]
    t_pd = n * store_seq(s) / (TP * PARAM)
    tail = max(0.0, t_pd - body * (L - 1) / L)
    return {
        "t": body + tail,
        "pull": t_pull,
        "hbm": t_hbm,
        "compute": t_compute,
        "ar": t_ar,
        "moe": moe["t"],
        "tail": tail,
        "pd": t_pd,
        "n": n,
        "q": q,
    }


def decode(bs, s, pool):
    n = math.ceil(bs / DP)
    sel = min(1024.0, s / 4.0)
    score = N_CSA * 4096 * s + N_HCA * 2048 * s + N_CSA * 262144 * (sel + 128)
    store = bs * store_seq(s)
    read_gpu = n * n_csa_read(s) / TP
    spill = max(store - ROOM, 0.0) / store if store else 0.0
    t_swap = read_gpu * spill / pool
    t_hbm = (read_gpu + ATTN / TP) / HBM_BW
    t_ca = n * (score + PROJ) / (TP * PEAK * align(n))
    t_ar = allreduce(n)
    moe = expert(bs)
    return {
        "t": t_swap + max(t_ca, t_hbm) + t_ar + moe["t"],
        "swap": t_swap,
        "hbm": t_hbm,
        "ca": t_ca,
        "kernel": max(t_ca, t_hbm),
        "ar": t_ar,
        "moe": moe["t"],
        "spill": spill,
        "store": store,
        "n": n,
        "moe_d": moe,
    }


def fits_ddr(row, cap):
    if cap is None:
        return True
    return row["spill"] * row["store"] / N <= cap + 1.0


def search_prefill(s, prefix, limit=10.0, ngpu=None, mem=False):
    gpu = N if ngpu is None else ngpu
    cap = 20_000_000
    if mem:
        per, _ = room_bytes(gpu)
        cap = int(per * gpu // store_seq(s)) if per > 0 else 0
        if cap < 1:
            return 0, prefill(1, s, prefix=prefix, ngpu=gpu)

    def ok(bs):
        return bs <= cap and prefill(bs, s, prefix=prefix, ngpu=gpu)["t"] <= limit + 1e-9

    if not ok(1):
        return 0, prefill(1, s, prefix=prefix, ngpu=gpu)
    lo, hi = 1, 2
    while ok(hi) and hi < cap:
        lo, hi = hi, min(cap, hi * 2)
    if ok(hi) and hi == cap:
        lo = cap
    else:
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if ok(mid):
                lo = mid
            else:
                hi = mid
    while lo > 1 and not ok(lo):
        lo -= 1
    while lo < cap and ok(lo + 1):
        lo += 1
    return lo, prefill(lo, s, prefix=prefix, ngpu=gpu)


def search_decode(s, limit, pool, cap):
    def ok(bs):
        row = decode(bs, s, pool)
        return row["t"] <= limit + 1e-9 and fits_ddr(row, cap)

    if not ok(1):
        return 0, decode(1, s, pool)
    lo, hi = 1, 2
    while ok(hi) and hi < 8_000_000:
        lo, hi = hi, hi * 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    while lo > 1 and not ok(lo):
        lo -= 1
    while ok(lo + 1) and lo < 8_000_000:
        lo += 1
    return lo, decode(lo, s, pool)


def max_cold(limit=10.0):
    lo, hi = 1.0, 20e6
    for _ in range(60):
        mid = (lo + hi) / 2
        if prefill(1, mid, hit=0.0)["t"] > limit:
            hi = mid
        else:
            lo = mid
    s = int(math.floor(lo))
    while prefill(1, s, hit=0.0)["t"] > limit and s > 1:
        s -= 1
    while prefill(1, s + 1, hit=0.0)["t"] <= limit:
        s += 1
    return s, prefill(1, s, hit=0.0)


def mem_slice(bs, s):
    store = bs * store_seq(s)
    weight = (ROUTED / N + SHARED + ATTN / TP) / 1e9
    reserve = RESERVE / 1e9
    room = (HBM_CAP - ROUTED / N - SHARED - ATTN / TP - RESERVE) / 1e9
    kv = store / N / 1e9
    hbm_kv = min(kv, room)
    ddr = max(kv - room, 0.0)
    free = HBM_CAP / 1e9 - weight - reserve - hbm_kv
    return {
        "weight": weight + reserve,
        "hbm": hbm_kv,
        "free": max(free, 0.0),
        "ddr": ddr,
    }


def fmt_len(s):
    if s >= 1048576 and s % 1048576 == 0:
        return f"{s // 1048576}M"
    if s % 1024 == 0:
        return f"{s // 1024}K"
    return f"{s:,}"


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
    if old == 0:
        return "—"
    return f"{(new - old) / old * 100:+.1f}%"


def sec(v):
    if v >= 0.1:
        return f"{v:.2f} 秒"
    return f"{v * 1e3:.1f} 毫秒"


def ms(v):
    return f"{v * 1e3:.2f} 毫秒"


def collect():
    cold_s, cold = max_cold()
    rows = []
    for s in LENGTHS:
        b25, p25 = search_prefill(s, PREFIX_25)
        b24, p24 = search_prefill(s, PREFIX_25, ngpu=PF_N)
        b100, p100 = search_prefill(s, PREFIX_100)
        b10, d10 = search_decode(s, 0.010, HOST, DDR_CAP)
        p10b, d10p = search_decode(s, 0.010, POOL, None)
        b30, d30 = search_decode(s, 0.030, HOST, DDR_CAP)
        p30b, d30p = search_decode(s, 0.030, POOL, None)
        rows.append({
            "S": s,
            "b25": b25, "p25": p25,
            "b24": b24, "p24": p24,
            "b100": b100, "p100": p100,
            "b10": b10, "d10": d10,
            "p10": p10b, "d10p": d10p,
            "b30": b30, "d30": d30,
            "p30": p30b, "d30p": d30p,
            "m10": mem_slice(p10b, s),
            "m30": mem_slice(p30b, s),
        })
    return {"cold_s": cold_s, "cold": cold, "cold4": prefill(1, 4194304, hit=0.0), "rows": rows}


def by_len(data, s):
    return next(row for row in data["rows"] if row["S"] == s)


def req_pair(bs_p, t_p, bs_d, t_d):
    rp = bs_p / t_p
    rd = (bs_d / t_d) / OUT_LEN
    return rp, rd, rd / rp


def slide_conclusion(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 1, "10 秒和 10 毫秒都能摸高，冷的 4M 过线", "N+2    ·    20T DeepSeek    ·    本页是 256 卡副本    ·    Prefill 最优为 24 卡")
    banner(slide, 0.92, f"99.5% 命中。参数面 800 Gb/s，拉 KV 基线每卡 {PREFIX_25/1e9:.0f} GB/s。Decode 换入取 min(H2D {H2D/1e9:.0f}, DDR 每卡 {DDR_SHARE/1e9:.0f}) = {HOST/1e9:.0f} GB/s。")
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    head = ["约束", "64K 全局批", "64K 系统 TPS", "4M 全局批", "4M 系统 TPS", "4M 实际耗时"]
    body = [
        ["TTFT ≤ 10 秒", fmt_bs(r64["b25"]), fmt_rate(r64["b25"] * r64["S"] / r64["p25"]["t"]), fmt_bs(r4["b25"]), fmt_rate(r4["b25"] * r4["S"] / r4["p25"]["t"]), sec(r4["p25"]["t"])],
        ["TPOT ≤ 10 毫秒", fmt_bs(r64["b10"]), fmt_rate(r64["b10"] / r64["d10"]["t"]), fmt_bs(r4["b10"]), fmt_rate(r4["b10"] / r4["d10"]["t"]), ms(r4["d10"]["t"])],
        ["TPOT ≤ 30 毫秒", fmt_bs(r64["b30"]), fmt_rate(r64["b30"] / r64["d30"]["t"]), fmt_bs(r4["b30"]), fmt_rate(r4["b30"] / r4["d30"]["t"]), ms(r4["d30"]["t"])],
    ]
    add_table(slide, 0.42, 1.50, [2.05, 1.85, 2.15, 1.85, 2.20, 2.40], [head] + body, [0.40, 0.46, 0.46, 0.46], ["head", "key", "body", "body"], size=14)
    rp, rd, ratio = req_pair(r64["b25"], r64["p25"]["t"], r64["b10"], r64["d10"]["t"])
    rp24, _, ratio24 = req_pair(r64["b24"], r64["p24"]["t"], r64["b10"], r64["d10"]["t"])
    gold(
        slide,
        3.50,
        1.85,
        f"冷请求不拉 prefix。最大输入 {data['cold_s']:,}，TTFT {sec(data['cold']['t'])}。4M 冷请求是 {sec(data['cold4']['t'])}，过 10 秒。\n"
        f"99.5% 命中下，64K 到 4M 的摸高批都落在 10 秒、10 毫秒、30 毫秒里面。系统 Prefill TPS = 全局批 × 输入长度 / 实际 TTFT。系统 Decode TPS = 全局批 / 实际 TPOT。\n"
        f"本页 Prefill 按 256 卡计。64K、10 毫秒：Prefill {rp:.0f} 请求/秒，Decode {rd:.0f} 请求/秒，{ratio:.2f} 份 Prefill 配 1 份 Decode。\n"
        f"Prefill 改到 24 卡后每卡吞吐不变。同一 Decode 要 {ratio24:.1f} 份 24 卡 Prefill，一份的请求速率是 {rp24:.0f} /秒。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = (
        f"cold {data['cold_s']} t={data['cold']['t']:.6f} cold4={data['cold4']['t']:.6f} "
        f"64k pf {r64['b25']} {r64['p25']['t']:.4f} d10 {r64['b10']} {r64['d10']['t']:.6f} "
        f"4m pf {r4['b25']} {r4['p25']['t']:.4f}"
    )


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 2, "同一骨架，只把路由专家加到 4951", "N+2    ·    模型结构    ·    1.6T 论文到 20T 外推")
    banner(slide, 0.92, "激活参数、KV 字节和单 token 的专家通信量都由 TopK=6 决定。层数和隐藏一变，注意力 FLOP 与 AllReduce 字节都会变，这一档不动。")
    head = ["项目", "1.6T  论文 V4-Pro", "20T  外推"]
    body = [
        ["总参数", "1.600×10^12", "2.000×10^13"],
        ["路由专家", "384", f"{E}"],
        ["层 / 隐藏 / 中间维", "61 / 7168 / 3072", "保持 61 / 7168 / 3072"],
        ["每 token 激活", "6 路由 + 1 共享，4.9×10^10", "仍是 4.9×10^10"],
        ["激活比", "3.06%", "0.245%"],
        ["注意力", "30 层 CSA + 31 层 HCA", "层数和压缩比不动"],
        ["专家字节", "路由按 FP4，共享按 FP8", "同一套精度"],
        ["FP4 专家表", f"{384 * W_ONE * 0.5 / 1e12:.3f} TB", f"{ROUTED / 1e12:.3f} TB"],
    ]
    kinds = ["head"] + ["key" if i in (1, 7) else "body" for i in range(len(body))]
    add_table(slide, 0.42, 1.48, [2.70, 4.90, 4.90], [head] + body, [0.32] + [0.36] * len(body), kinds, size=13)
    gold(
        slide,
        5.55,
        1.45,
        f"外推式：E = ceil((2×10^13 − {OTHER/1e10:.3f}×10^10) / {W_ONE/1e9:.3f}×10^9) = {E}。\n"
        f"整数和 {TOTAL_PARAMS/1e12:.4f}×10^12，比 2×10^13 多 {(TOTAL_PARAMS - 2e13)/1e9:.2f}×10^9。单个专家 = 3 × 7168 × 3072 × 61 = {W_ONE/1e9:.3f}×10^9。\n"
        "1.6T 来自 V4-Pro。384 个专家占 1.547×10^12，其余 5.260×10^10 是共享专家、注意力、词表、mHC 和 MTP。10T 用同一条式子得到 2469 个专家。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = f"E={E} total={TOTAL_PARAMS} routed_bytes={ROUTED:.0f} other={OTHER}"


def slide_hardware(prs, blank):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 3, "标称先乘效率，再拿来计时", "N+2    ·    参数面 800 Gb/s    ·    D2D 48 Tb/s    ·    拉 KV 25%")
    head = ["项目", "标称", "计时用的数"]
    body = [
        ["FP4 算力", "每卡 48 P", "×70% = 33.60 P。注意力和专家 GEMM 共用"],
        ["HBM", "640 GB，33 TB/s", "带宽 ×80% = 26.40 TB/s"],
        ["H2D", "每卡单向 1.6 Tb/s", "200 GB/s ×80% = 160 GB/s"],
        ["DDR5", "每机 2 TB/s，768 GB", f"×80% 后每卡 {DDR_SHARE/1e9:.0f} GB/s、{DDR_CAP/1e9:.0f} GB"],
        ["H2D 换入", "链路和 DDR5 取更小的", f"{HOST/1e9:.0f} GB/s。H2D 比每卡 DDR {DDR_SHARE/1e9:.0f} GB/s 更窄"],
        ["D2D", "每卡单向 48 Tb/s，256 卡", f"{D2D_PEAK/1e12:.2f} TB/s ×80% = {D2D/1e12:.2f} TB/s"],
        ["机内 fullmesh", "两卡之间 P2P 1.6 Tb/s", "7 条并发，×80% = 1.12 TB/s"],
        ["参数面", "每卡 800 Gb/s", f"物理 {PARAM_PEAK/1e9:.0f} GB/s。P→D {PARAM/1e9:.0f}。拉 KV {PREFIX_25/1e9:.0f}"],
        ["总线 DDR 池", "每卡 51.2 Tb/s，容量不限", f"×80% = {POOL/1e12:.2f} TB/s。只在 case 2"],
    ]
    kinds = ["head"] + ["key" if i in (4, 6, 8) else "body" for i in range(len(body))]
    add_table(slide, 0.42, 1.42, [2.15, 4.55, 5.80], [head] + body, [0.30] + [0.40] * len(body), kinds, size=13)
    gold(
        slide,
        5.85,
        1.18,
        f"两卡之间的 P2P 是 1.6 Tb/s。一卡连另外 7 卡，7 条同时可用，聚合峰值 1.40 TB/s。D2D 口 {D2D_PEAK/1e12:.2f} TB/s 高于这条聚合，AllReduce 用 {P2P/1e12:.2f} TB/s。\n"
        f"拉 KV 取物理 {PARAM_PEAK/1e9:.0f} GB/s 的 25%，每卡 {PREFIX_25/1e9:.0f} GB/s，不再叠乘 80%。P→D 取 80%，每卡 {PARAM/1e9:.0f} GB/s。集合通信每层另加 5 微秒。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = (
        f"PEAK={PEAK:.3e} HBM_BW={HBM_BW:.3e} HOST={HOST:.3e} D2D={D2D:.3e} P2P={P2P:.3e} "
        f"PREFIX25={PREFIX_25:.3e} POOL={POOL:.3e} DDR_CAP={DDR_CAP:.3e}"
    )


def slide_parallel(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 4, "Prefill 收到 24 卡，Decode 仍用 256", "N+2    ·    Prefill TP=8 EP=24 DP=3    ·    Decode TP=8 EP=256 DP=32")
    banner(slide, 0.92, "每卡 Prefill 吞吐从 24 卡到 256 卡持平。24 卡是 8 卡对齐下，10 秒批量仍由时间决定的最小副本。")
    head = ["", "Prefill", "Decode"]
    pf_room, pf_cluster = room_bytes(PF_N)
    dc_room, dc_cluster = room_bytes(N)
    body = [
        ["切分", "TP=8，EP=24，DP=3\n一份副本 3 个机内组", "TP=8，EP=256，DP=32\n一份副本铺满超节点"],
        ["理由", "拉 KV 是每卡 25 GB/s\n加大 EP 不提高每卡 token/s", "64K、30 毫秒存量约 146 TB\n要吃满 151 TB 的 KV 房间"],
        ["每卡权重", f"路由 {ROUTED/PF_N/1e9:.0f} GB FP4\n注意力 {ATTN/TP/1e9:.2f} GB", f"路由 {ROUTED/N/1e9:.1f} GB FP4\n注意力 {ATTN/TP/1e9:.2f} GB"],
        ["KV 房间", f"每卡 {pf_room/1e9:.0f} GB\n副本 {pf_cluster/1e12:.2f} TB", f"每卡 {dc_room/1e9:.0f} GB\n副本 {dc_cluster/1e12:.1f} TB"],
    ]
    add_table(slide, 0.42, 1.48, [1.70, 5.40, 5.40], [head] + body, [0.34, 0.62, 0.70, 0.62, 0.62], ["head", "key", "body", "body", "key"], size=13)
    r64 = by_len(data, 65536)
    per24 = r64["b24"] * r64["S"] / r64["p24"]["t"] / PF_N
    per256 = r64["b25"] * r64["S"] / r64["p25"]["t"] / N
    b16, p16 = search_prefill(4194304, PREFIX_25, ngpu=16, mem=True)
    per16 = (b16 * 4194304 / p16["t"] / 16) if b16 else 0.0
    per4 = by_len(data, 4194304)
    per4_24 = per4["b24"] * per4["S"] / per4["p24"]["t"] / PF_N
    gold(
        slide,
        5.05,
        1.95,
        f"64K 每卡 Prefill TPS：24 卡 {fmt_rate(per24)}，256 卡 {fmt_rate(per256)}。AllReduce 仍在机内 1.12 TB/s，专家通信仍按每卡 {D2D/1e12:.2f} TB/s。\n"
        f"16 卡每卡 KV 只剩 {room_bytes(16)[0]/1e9:.1f} GB。4M 摸高批被显存卡在 {b16}，每卡吞吐 {fmt_rate(per16)}，是 24 卡的 {per16 / per4_24 * 100:.0f}%。\n"
        "单条请求不跨副本。Decode 不跟着缩小。24 卡的系统 TPS、耗时和 HBM 占用见后三页。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = f"PF_N={PF_N} PF_DP={PF_DP} room24={pf_room:.3e} room256={dc_room:.3e} ep16_4m={b16}"


def slide_tps(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 5, "64K 到 4M，系统 TPS 随输入下降", "N+2    ·    256 卡副本    ·    TTFT ≤ 10 秒    ·    TPOT ≤ 10 / 30 毫秒")
    banner(slide, 0.92, f"基线：拉 KV 25%，Decode 换入 {HOST/1e9:.0f} GB/s。Prefill TPS 用完整输入 token。Decode TPS 是这一步新 token 的吞吐。")
    head = ["输入", "10 秒批", "Prefill TPS", "10 毫秒批", "10 毫秒 TPS", "30 毫秒批", "30 毫秒 TPS"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row["b25"]),
            fmt_rate(row["b25"] * row["S"] / row["p25"]["t"]),
            fmt_bs(row["b10"]),
            fmt_rate(row["b10"] / row["d10"]["t"]),
            fmt_bs(row["b30"]),
            fmt_rate(row["b30"] / row["d30"]["t"]),
        ])
    add_table(slide, 0.42, 1.50, [1.15, 1.70, 2.05, 1.85, 2.05, 1.85, 1.85], [head] + body, [0.36] + [0.38] * len(body), kinds, size=14)
    r512 = by_len(data, 524288)
    r4m = by_len(data, 4194304)
    gold(
        slide,
        5.05,
        1.95,
        "10 毫秒在 64K、128K、256K 全在 HBM，换入带宽不影响批量。\n"
        f"512K 起溢出，每卡主机 DDR {r512['d10']['spill'] * r512['d10']['store'] / N / 1e9:.1f} GB。"
        f"4M 溢出 {r4m['d10']['spill'] * 100:.1f}%，每卡 {r4m['d10']['spill'] * r4m['d10']['store'] / N / 1e9:.1f} GB。\n"
        "30 毫秒从 128K 起进入主机 DDR。4M 每卡溢出约 "
        f"{r4m['d30']['spill'] * r4m['d30']['store'] / N / 1e9:.1f} GB，"
        f"低于每卡 {DDR_CAP/1e9:.0f} GB 的 DDR5 空间。批量是被 {HOST/1e9:.0f} GB/s 卡住的，768 GB 的机器空间还没用完。\n"
        f"Prefill 的 10 秒里，拉 KV 是大头，所以输入从 64K 加到 4M，系统 TPS 从 {fmt_rate(by_len(data, 65536)['b25'] * 65536 / by_len(data, 65536)['p25']['t'])} 降到 {fmt_rate(r4m['b25'] * r4m['S'] / r4m['p25']['t'])}。",
        14,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} pf={row['b25']} d10={row['b10']} d30={row['b30']}" for row in data["rows"]
    )


def slide_prefill(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 6, "拉 KV 占掉 10 秒里的大部分", "N+2    ·    256 卡 Prefill    ·    TTFT 拆解    ·    DP=32")
    banner(slide, 0.92, "HBM 只有几毫秒，计算列就是 Attention FLOP。P→D 尾巴在这些批上是 0。四段相加等于 TTFT。")
    head = ["输入", "全局批", "拉 KV", "计算", "AR", "MoE", "HBM", "TTFT", "拉KV占比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        p = row["p25"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row["b25"]),
            sec(p["pull"]),
            sec(p["compute"]),
            sec(p["ar"]),
            sec(p["moe"]),
            ms(p["hbm"]),
            sec(p["t"]),
            f"{p['pull'] / p['t'] * 100:.1f}%",
        ])
    add_table(
        slide,
        0.42,
        1.48,
        [0.85, 1.25, 1.35, 1.25, 1.25, 1.25, 1.25, 1.30, 1.75],
        [head] + body,
        [0.34] + [0.36] * len(body),
        kinds,
        size=13,
    )
    gold(
        slide,
        4.55,
        2.45,
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail。\n"
        f"T_pull = n × (p×4939.5 + 61×min(p,128)×576) / (8 × {PREFIX_25/1e9:.0f} GB/s)。p = 0.995×S，n = ceil(全局批 / 32)。\n"
        "T_compute = n × (F_idx + F_hca + F_core + F_proj) / (8 × 33.60 P × align(n×q))。q = 0.005×S。\n"
        f"T_AR = 61 × (5 微秒 + 2×7/8 × n×q × 7168 × 2 / {P2P/1e12:.2f} TB/s)。\n"
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine。\n"
        f"dispatch 每元素 1 字节，combine 每元素 2 字节，带宽 {D2D/1e12:.2f} TB/s。两段各加每层 5 微秒，彼此不重叠。\n"
        "T_tail = max(0, T_P→D − 前 60 层能盖住的时间)。这些批上尾巴是 0。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} pull={row['p25']['pull']:.4f} comp={row['p25']['compute']:.4f} "
        f"ar={row['p25']['ar']:.4f} moe={row['p25']['moe']:.4f} hbm={row['p25']['hbm']:.6f} t={row['p25']['t']:.4f}"
        for row in data["rows"]
    )


def slide_pf_tps(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 7, "24 卡系统 TPS 按卡数缩小，每卡持平", "N+2    ·    Prefill EP=24    ·    对照 256 卡    ·    TTFT ≤ 10 秒")
    banner(slide, 0.92, "版式同第 5 页。系统 TPS 是一份副本的吞吐。24 卡约为 256 卡的 24/256，每卡 token/s 相同。")
    head = ["输入", "24卡批", "24卡 TPS", "24卡每卡", "256卡 TPS", "256卡每卡", "每卡比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        t24 = row["b24"] * row["S"] / row["p24"]["t"]
        t256 = row["b25"] * row["S"] / row["p25"]["t"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row["b24"]),
            fmt_rate(t24),
            fmt_rate(t24 / PF_N),
            fmt_rate(t256),
            fmt_rate(t256 / N),
            f"{(t24 / PF_N) / (t256 / N) * 100:.1f}%",
        ])
    add_table(slide, 0.42, 1.50, [1.05, 1.45, 1.90, 1.80, 2.05, 2.10, 2.15], [head] + body, [0.36] + [0.38] * len(body), kinds, size=14)
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    cap64 = int(room_bytes(PF_N)[1] // store_seq(65536))
    rp, rd, ratio = req_pair(r64["b24"], r64["p24"]["t"], r64["b10"], r64["d10"]["t"])
    gold(
        slide,
        5.05,
        1.95,
        f"64K：24 卡批 {fmt_bs(r64['b24'])}，TTFT {sec(r64['p24']['t'])}，系统 TPS {fmt_rate(r64['b24'] * r64['S'] / r64['p24']['t'])}。"
        f"256 卡批 {fmt_bs(r64['b25'])}，系统 TPS {fmt_rate(r64['b25'] * r64['S'] / r64['p25']['t'])}。\n"
        f"4M：24 卡批 {fmt_bs(r4['b24'])}，系统 TPS {fmt_rate(r4['b24'] * r4['S'] / r4['p24']['t'])}；"
        f"256 卡批 {fmt_bs(r4['b25'])}，系统 TPS {fmt_rate(r4['b25'] * r4['S'] / r4['p25']['t'])}。\n"
        f"64K 的 24 卡显存上限是 {fmt_bs(cap64)} 条，时间批 {fmt_bs(r64['b24'])} 条，仍由 10 秒卡住。\n"
        f"按输出 {OUT_LEN} token、64K、10 毫秒：一份 24 卡 Prefill {rp:.0f} 请求/秒，Decode {rd:.0f} 请求/秒，{ratio:.1f} 份 Prefill 配 1 份 Decode。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} b24={row['b24']} t={row['p24']['t']:.4f}" for row in data["rows"]
    )


def slide_pf_time(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 8, "24 卡的 10 秒拆解和 256 卡同构", "N+2    ·    24 卡 Prefill    ·    TTFT 拆解    ·    DP=3")
    banner(slide, 0.92, "版式同第 6 页。HBM 仍是几毫秒。拉 KV 占比不变，批量约为 256 卡的 24/256。四段相加等于 TTFT。")
    head = ["输入", "全局批", "拉 KV", "计算", "AR", "MoE", "HBM", "TTFT", "拉KV占比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        p = row["p24"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row["b24"]),
            sec(p["pull"]),
            sec(p["compute"]),
            sec(p["ar"]),
            sec(p["moe"]),
            ms(p["hbm"]),
            sec(p["t"]),
            f"{p['pull'] / p['t'] * 100:.1f}%",
        ])
    add_table(
        slide,
        0.42,
        1.48,
        [0.85, 1.25, 1.35, 1.25, 1.25, 1.25, 1.25, 1.30, 1.75],
        [head] + body,
        [0.34] + [0.36] * len(body),
        kinds,
        size=13,
    )
    r64 = by_len(data, 65536)
    gold(
        slide,
        4.55,
        2.45,
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail。\n"
        f"T_pull = n × (p×4939.5 + 61×min(p,128)×576) / (8 × {PREFIX_25/1e9:.0f} GB/s)。p = 0.995×S，n = ceil(全局批 / {PF_DP})。\n"
        "T_compute = n × (F_idx + F_hca + F_core + F_proj) / (8 × 33.60 P × align(n×q))。q = 0.005×S。\n"
        f"T_AR = 61 × (5 微秒 + 2×7/8 × n×q × 7168 × 2 / {P2P/1e12:.2f} TB/s)。\n"
        f"T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine。dispatch 1 字节，combine 2 字节，带宽 {D2D/1e12:.2f} TB/s。\n"
        f"64K 拉 KV 占 {r64['p24']['pull'] / r64['p24']['t'] * 100:.1f}%，256 卡同一输入是 {r64['p25']['pull'] / r64['p25']['t'] * 100:.1f}%。这些批的尾巴是 0。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} pull={row['p24']['pull']:.4f} comp={row['p24']['compute']:.4f} "
        f"ar={row['p24']['ar']:.4f} moe={row['p24']['moe']:.4f} t={row['p24']['t']:.4f}"
        for row in data["rows"]
    )


def _hbm_cells(ngpu, bs, s):
    per, cluster = room_bytes(ngpu)
    kv = bs * store_seq(s) / ngpu
    free = HBM_CAP - (ROUTED / ngpu + SHARED + ATTN / TP + RESERVE) - kv
    return per, cluster, kv, free


def slide_pf_hbm(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 9, "24 卡把专家权重放进 HBM", "N+2    ·    每卡 HBM    ·    10 秒摸高批    ·    256 卡对照 24 卡")
    banner(slide, 0.92, "同一条 10 秒批上，每卡实际 KV 几乎一样。24 卡的差别是路由权重大，KV 空闲被压到 64K 的边上。")
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    room256, cluster256, kv64_256, free64_256 = _hbm_cells(N, r64["b25"], 65536)
    _, _, kv4_256, free4_256 = _hbm_cells(N, r4["b25"], 4194304)
    room24, cluster24, kv64_24, free64_24 = _hbm_cells(PF_N, r64["b24"], 65536)
    _, _, kv4_24, free4_24 = _hbm_cells(PF_N, r4["b24"], 4194304)
    head = ["项目", "256 卡", "24 卡"]
    body = [
        ["路由专家", f"{ROUTED/N/1e9:.1f} GB", f"{ROUTED/PF_N/1e9:.1f} GB"],
        ["共享专家", f"{SHARED/1e9:.2f} GB", f"{SHARED/1e9:.2f} GB"],
        ["注意力", f"{ATTN/TP/1e9:.2f} GB", f"{ATTN/TP/1e9:.2f} GB"],
        ["预留", "6 GB", "6 GB"],
        ["KV 房间", f"{room256/1e9:.1f} GB", f"{room24/1e9:.1f} GB"],
        ["64K 实际 KV", f"{kv64_256/1e9:.1f} GB", f"{kv64_24/1e9:.1f} GB"],
        ["64K 空闲", f"{free64_256/1e9:.1f} GB", f"{free64_24/1e9:.1f} GB"],
        ["4M 实际 KV", f"{kv4_256/1e9:.1f} GB", f"{kv4_24/1e9:.1f} GB"],
        ["4M 空闲", f"{free4_256/1e9:.1f} GB", f"{free4_24/1e9:.1f} GB"],
        ["副本 KV 房间", f"{cluster256/1e12:.1f} TB", f"{cluster24/1e12:.2f} TB"],
    ]
    kinds = ["head"] + ["key" if i in (4, 6, 8) else "body" for i in range(len(body))]
    add_table(slide, 0.42, 1.42, [3.30, 4.60, 4.60], [head] + body, [0.30] + [0.34] * len(body), kinds, size=13)
    cap64 = int(cluster24 // store_seq(65536))
    b16, _ = search_prefill(4194304, PREFIX_25, ngpu=16, mem=True)
    gold(
        slide,
        5.28,
        1.72,
        "切分调整的理由：拉 KV 占 64K TTFT 的约 71%，带宽是每卡 25 GB/s。EP 从 24 加到 256，每卡 token/s 不变，系统 TPS 只按卡数放大。\n"
        f"16 卡每卡 KV 房间 {room_bytes(16)[0]/1e9:.1f} GB，一条 4M 序列 {store_seq(4194304)/1e9:.1f} GB。摸高批被显存卡在 {b16}，每卡吞吐掉下来。\n"
        f"24 卡是 8 卡对齐下的最小时间受限副本。64K 显存上限 {fmt_bs(cap64)} 条，时间批 {fmt_bs(r64['b24'])} 条，空闲 {free64_24/1e9:.0f} GB。\n"
        f"Decode 保持 256 卡。64K、30 毫秒存量 {r64['d30']['store']/1e12:.0f} TB，256 卡房间 {cluster256/1e12:.0f} TB 几乎被用满。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = (
        f"kv64_24={kv64_24:.3e} free64_24={free64_24:.3e} kv4_24={kv4_24:.3e} free4_24={free4_24:.3e} "
        f"kv64_256={kv64_256:.3e} free64_256={free64_256:.3e}"
    )


def slide_decode(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 10, "10 毫秒少换入，30 毫秒从 128K 起换入是大头", f"N+2    ·    Decode    ·    TPOT 拆解    ·    H2D {HOST/1e9:.0f} GB/s")
    head = ["输入", "批", "SWAP", "计算", "AR", "MoE", "TPOT", "溢出"]

    def rows_for(batch_key, dec_key):
        body, kinds = [], ["head"]
        for row in data["rows"]:
            d = row[dec_key]
            kinds.append("key" if d["spill"] >= 0.005 else "body")
            body.append([
                fmt_len(row["S"]),
                fmt_bs(row[batch_key]),
                ms(d["swap"]),
                ms(d["kernel"]),
                ms(d["ar"]),
                ms(d["moe"]),
                ms(d["t"]),
                f"{d['spill'] * 100:.1f}%",
            ])
        return body, kinds

    textbox(slide, 0.42, 1.38, 4.0, 0.22, "TPOT ≤ 10 毫秒", 13, True, ACCENT)
    b10, k10 = rows_for("b10", "d10")
    add_table(slide, 0.42, 1.60, [0.95, 1.45, 1.45, 1.55, 1.45, 1.45, 1.55, 2.65], [head] + b10, [0.26] + [0.26] * len(b10), k10, size=11)
    textbox(slide, 0.42, 3.78, 4.0, 0.22, "TPOT ≤ 30 毫秒", 13, True, ACCENT)
    b30, k30 = rows_for("b30", "d30")
    add_table(slide, 0.42, 4.00, [0.95, 1.45, 1.45, 1.55, 1.45, 1.45, 1.55, 2.65], [head] + b30, [0.26] + [0.26] * len(b30), k30, size=11)
    gold(
        slide,
        6.12,
        0.92,
        f"TPOT = T_SWAP + max(T_HBM, T_compute) + T_AR + T_MoE。T_SWAP = 溢出比例 × 每卡稀疏读 / {HOST/1e9:.0f} GB/s。\n"
        f"计算列是 max(HBM, Attention FLOP)。T_AR 用机内 {P2P/1e12:.2f} TB/s。MoE 的 dispatch 与 combine 走 {D2D/1e12:.2f} TB/s，加在 GEMM 外面。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} 10 {row['b10']} swap={row['d10']['swap']*1e3:.3f} ker={row['d10']['kernel']*1e3:.3f} "
        f"hbm={row['d10']['hbm']*1e3:.3f} ca={row['d10']['ca']*1e3:.3f} ar={row['d10']['ar']*1e3:.3f} moe={row['d10']['moe']*1e3:.3f} "
        f"30 {row['b30']} swap={row['d30']['swap']*1e3:.3f} t={row['d30']['t']*1e3:.3f}"
        for row in data["rows"]
    )


def slide_case1(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 11, "拉 KV 从基线改到 NEW，TPS 上升不到 4 倍", f"N+2 Case 1    ·    基线 {PREFIX_25/1e9:.0f} GB/s    ·    NEW {PREFIX_100/1e9:.0f} GB/s")
    banner(slide, 0.92, f"基线是物理带宽的 25%，每卡 {PREFIX_25/1e9:.0f} GB/s。NEW 是物理 {PREFIX_100/1e9:.0f} GB/s，不叠乘 80%。TPS 提升以基线列计算。")
    head = ["输入", "基线批", "NEW批", "基线 TPS", "NEW TPS", "TPS提升", "基线占比", "NEW占比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        t25 = row["b25"] * row["S"] / row["p25"]["t"]
        t100 = row["b100"] * row["S"] / row["p100"]["t"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row["b25"]),
            fmt_bs(row["b100"]),
            fmt_rate(t25),
            fmt_rate(t100),
            signed_pct(t100, t25),
            f"{row['p25']['pull'] / row['p25']['t'] * 100:.1f}%",
            f"{row['p100']['pull'] / row['p100']['t'] * 100:.1f}%",
        ])
    add_table(slide, 0.42, 1.46, [0.90, 1.40, 1.50, 1.70, 1.80, 1.45, 1.85, 1.90], [head] + body, [0.30] + [0.28] * len(body), kinds, size=12)
    head2 = ["输入", "基线拉KV", "NEW拉KV", "基线计算", "NEW计算", "基线 AR", "NEW AR", "基线 MoE", "NEW MoE"]
    body2, kinds2 = [], ["head"]
    for row in data["rows"]:
        a, b = row["p25"], row["p100"]
        kinds2.append("key" if row["S"] in (65536, 4194304) else "body")
        body2.append([
            fmt_len(row["S"]),
            sec(a["pull"]), sec(b["pull"]),
            sec(a["compute"]), sec(b["compute"]),
            sec(a["ar"]), sec(b["ar"]),
            sec(a["moe"]), sec(b["moe"]),
        ])
    add_table(slide, 0.42, 3.85, [0.78, 1.46, 1.46, 1.46, 1.46, 1.46, 1.46, 1.46, 1.50], [head2] + body2, [0.28] + [0.26] * len(body2), kinds2, size=11)
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    tps64 = signed_pct(r64["b100"] * r64["S"] / r64["p100"]["t"], r64["b25"] * r64["S"] / r64["p25"]["t"])
    tps4 = signed_pct(r4["b100"] * r4["S"] / r4["p100"]["t"], r4["b25"] * r4["S"] / r4["p25"]["t"])
    gold(
        slide,
        6.10,
        0.95,
        f"64K：基线拉 KV {sec(r64['p25']['pull'])}，NEW {sec(r64['p100']['pull'])}，占比 {r64['p25']['pull']/r64['p25']['t']*100:.1f}% → {r64['p100']['pull']/r64['p100']['t']*100:.1f}%，TPS {tps64}。\n"
        f"4M：基线拉 KV {sec(r4['p25']['pull'])}，NEW {sec(r4['p100']['pull'])}，占比 {r4['p25']['pull']/r4['p25']['t']*100:.1f}% → {r4['p100']['pull']/r4['p100']['t']*100:.1f}%，TPS {tps4}。NEW 带宽是基线的 4 倍，AR 和 MoE 随批量变长，所以 TPS 不到 4 倍。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} {row['b25']}->{row['b100']} "
        f"pull {row['p25']['pull']:.4f}->{row['p100']['pull']:.4f} "
        f"comp {row['p25']['compute']:.4f}->{row['p100']['compute']:.4f} "
        f"ar {row['p25']['ar']:.4f}->{row['p100']['ar']:.4f} "
        f"moe {row['p25']['moe']:.4f}->{row['p100']['moe']:.4f}"
        for row in data["rows"]
    )


def slide_case2(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 12, "总线 DDR 池把长上下文的 30 毫秒 TPS 抬上去", f"N+2 Case 2    ·    H2D {HOST/1e9:.0f} GB/s 对照池 {POOL/1e12:.2f} TB/s")
    banner(slide, 0.92, f"池是每卡 51.2 Tb/s ×80% = {POOL/1e12:.2f} TB/s，容量不限，不经 H2D，也不用 48 Tb/s 的交换平面截断。提升以 H2D 为基线。")
    head = ["输入", "H2D·10毫秒", "池·10毫秒", "10毫秒提升", "H2D·30毫秒", "池·30毫秒", "30毫秒提升"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        h10, p10 = row["b10"] / row["d10"]["t"], row["p10"] / row["d10p"]["t"]
        h30, p30 = row["b30"] / row["d30"]["t"], row["p30"] / row["d30p"]["t"]
        kinds.append("key" if row["S"] >= 524288 else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_rate(h10), fmt_rate(p10), signed_pct(p10, h10),
            fmt_rate(h30), fmt_rate(p30), signed_pct(p30, h30),
        ])
    add_table(slide, 0.42, 1.46, [1.05, 1.90, 1.90, 1.55, 2.05, 2.05, 2.00], [head] + body, [0.30] + [0.28] * len(body), kinds, size=12)
    head2 = ["输入", "10ms H2D批", "10ms 池批", "30ms H2D批", "30ms 池批", "30ms H2D溢出", "30ms 池溢出"]
    body2, kinds2 = [], ["head"]
    for row in data["rows"]:
        kinds2.append("key" if row["d30p"]["spill"] >= 0.005 else "body")
        body2.append([
            fmt_len(row["S"]),
            fmt_bs(row["b10"]), fmt_bs(row["p10"]),
            fmt_bs(row["b30"]), fmt_bs(row["p30"]),
            f"{row['d30']['spill']*100:.1f}%",
            f"{row['d30p']['spill']*100:.1f}%",
        ])
    add_table(slide, 0.42, 3.85, [1.05, 1.85, 1.70, 1.95, 1.85, 2.10, 2.00], [head2] + body2, [0.28] + [0.26] * len(body2), kinds2, size=11)
    r4 = by_len(data, 4194304)
    gold(
        slide,
        6.08,
        0.96,
        "10 毫秒在 64K 到 256K 的提升是 0%：KV 还在 HBM 里。4M 的 10 毫秒 TPS "
        f"{signed_pct(r4['p10']/r4['d10p']['t'], r4['b10']/r4['d10']['t'])}。\n"
        f"30 毫秒从 128K 起上升。4M 批量 {fmt_bs(r4['b30'])} → {fmt_bs(r4['p30'])}，TPS "
        f"{signed_pct(r4['p30']/r4['d30p']['t'], r4['b30']/r4['d30']['t'])}。"
        "池上的溢出比例更高，是因为更大的批把更多 KV 挤出 150.7 TB 的 HBM。",
        13,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} 10 {row['b10']}->{row['p10']} 30 {row['b30']}->{row['p30']} "
        f"spill30 {row['d30']['spill']*100:.2f}->{row['d30p']['spill']*100:.2f}"
        for row in data["rows"]
    )


def slide_pies(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    chrome(slide, 13, "30 毫秒把 KV 房间占满，多出来的进 DDR 池", "N+2 Case 2    ·    每卡 HBM 占用和 DDR 池溢出")
    banner(slide, 0.92, "上表和饼图都是池上的批，按每卡。四块是权重加预留、HBM 里的 KV、HBM 空闲，以及溢出到 DDR 池的 KV。")
    head = ["输入", "池10ms HBM", "池10ms DDR", "池30ms HBM", "池30ms DDR", "30ms 溢出"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        a, b = row["m10"], row["m30"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            f"{a['hbm']:.0f} GB",
            f"{a['ddr']:.0f} GB",
            f"{b['hbm']:.0f} GB",
            f"{b['ddr']:.0f} GB",
            f"{row['d30p']['spill']*100:.1f}%",
        ])
    add_table(slide, 0.42, 1.42, [1.15, 2.25, 2.05, 2.35, 2.15, 2.55], [head] + body, [0.28] + [0.26] * len(body), kinds, size=12)
    shown = [by_len(data, s) for s in (65536, 262144, 1048576, 4194304)]
    colors = (NAVY, TEAL, "D5DDE6", DDR_COLOR)
    labels = ("权重+预留", "HBM KV", "HBM 空闲", "DDR 池")
    for i, row in enumerate(shown):
        x0 = 0.42 + i * 3.22
        mem = row["m30"]
        values = (mem["weight"], mem["hbm"], mem["free"], mem["ddr"])
        add_pie(slide, x0 + 0.70, 4.55, 0.62, list(zip(values, colors)))
        textbox(slide, x0, 5.28, 3.05, 0.24, f"{fmt_len(row['S'])} · 30 毫秒 · 批 {fmt_bs(row['p30'])}", 12, True, NAVY, PP_ALIGN.CENTER)
        legend = "\n".join(f"{name}  {val:.0f} GB" for name, val in zip(labels, values))
        textbox(slide, x0 + 0.15, 5.52, 2.90, 1.05, legend, 12, False, INK, anchor=MSO_ANCHOR.TOP)
    gold(
        slide,
        6.62,
        0.46,
        f"64K 的 30 毫秒批还放得进 HBM，DDR 池是 0。1M 和 4M 的空闲是 0，KV 房间 {ROOM/N/1e9:.0f} GB 被占满，其余在池里。"
        f"10 毫秒的溢出见上表，4M 每卡 {by_len(data, 4194304)['m10']['ddr']:.0f} GB。",
        12,
    )
    slide.notes_slide.notes_text_frame.text = " ".join(
        f"{fmt_len(row['S'])} 10 hbm={row['m10']['hbm']:.2f} ddr={row['m10']['ddr']:.2f} "
        f"30 hbm={row['m30']['hbm']:.2f} ddr={row['m30']['ddr']:.2f} free={row['m30']['free']:.2f}"
        for row in data["rows"]
    )


def write_md(path, data):
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    lines = [
        "# N+2：20T DeepSeek 在 640 GB / 48P、256 卡上的 SLO",
        "",
        "这一档命名为 N+2。DeepSeek 没有发布 20T。外推只增加路由专家，层数、隐藏、中间维和 TopK 保持 V4-Pro。",
        "一份副本是一个 256 卡超节点。注意力 TP=8、DP=32，MoE EP=256。",
        "逐步演算在 deepseek-20t-n2-slo-calc.docx。本页只保留结果。",
        "命中率 99.5%。参数面 800 Gb/s。通信和访存效率 80%，张量计算效率 70%，拉 KV 取参数面物理带宽的 25%。",
        "",
        "## 1. 模型",
        "",
        "```",
        f"W_ONE = 3 × 7168 × 3072 × 61 = {W_ONE}",
        f"其余 = 1.600e12 − 384 × W_ONE = {OTHER}",
        f"E = ceil((2e13 − 其余) / W_ONE) = {E}",
        f"总参数 = {TOTAL_PARAMS}",
        f"FP4 专家表 = {ROUTED:.0f} 字节 = {ROUTED/1e12:.3f} TB",
        "```",
        "",
        "激活参数仍约 4.9×10^10。激活比从 3.06% 降到 0.245%。",
        "",
        "## 2. 有效带宽",
        "",
        "| 项目 | 计时值 |",
        "| --- | --- |",
        f"| 张量 | {PEAK/1e15:.2f} P，注意力与专家 GEMM 共用 |",
        f"| HBM | {HBM_BW/1e12:.2f} TB/s，容量 640 GB |",
        f"| DDR5 | 每机 {DDR_NODE/1e12:.0f} TB/s ×80% / 8 = 每卡 {DDR_SHARE/1e9:.0f} GB/s，容量每卡 {DDR_CAP/1e9:.0f} GB |",
        f"| H2D 换入 | {HOST/1e9:.0f} GB/s，min(H2D {H2D/1e9:.0f}, DDR 每卡 {DDR_SHARE/1e9:.0f}) |",
        f"| D2D | {D2D/1e12:.2f} TB/s，标称每卡单向 48 Tb/s |",
        f"| 总线 DDR 池 | {POOL/1e12:.2f} TB/s，标称每卡 51.2 Tb/s，容量不限 |",
        f"| AllReduce | {P2P/1e9:.0f} GB/s，两卡之间 1.6 Tb/s，7 条 × 80% |",
        f"| P→D / 拉 KV 基线 / 拉 KV NEW | {PARAM/1e9:.0f} / {PREFIX_25/1e9:.0f} / {PREFIX_100/1e9:.0f} GB/s |",
        f"| 每卡 KV 房间 | {ROOM/N/1e9:.1f} GB，副本合计 {ROOM/1e12:.2f} TB |",
        "",
        "两卡之间的 P2P 是 1.6 Tb/s。7 条同时可用，聚合峰值 1.40 TB/s，低于 D2D 口 6.00 TB/s，AllReduce 用 1.12 TB/s。",
        "",
        "## 3. 能否匹配",
        "",
        f"冷请求最大输入 {data['cold_s']:,}，TTFT {data['cold']['t']:.4f} 秒。4M 冷请求 {data['cold4']['t']:.4f} 秒，超过 10 秒。",
        "99.5% 命中下，64K 到 4M 的摸高批同时满足 TTFT ≤ 10 秒、TPOT ≤ 10 毫秒和 TPOT ≤ 30 毫秒。",
        "",
        "系统 Prefill TPS = 全局批 × 输入长度 / 实际 TTFT。系统 Decode TPS = 全局批 / 实际 TPOT。",
        "",
        "| 输入 | 10秒批 | Prefill TPS | 10毫秒批 | 10毫秒 TPS | 30毫秒批 | 30毫秒 TPS |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        lines.append(
            f"| {fmt_len(row['S'])} | {row['b25']} | {row['b25']*row['S']/row['p25']['t']:.3e} | "
            f"{row['b10']} | {row['b10']/row['d10']['t']:.3e} | {row['b30']} | {row['b30']/row['d30']['t']:.3e} |"
        )
    lines += [
        "",
        "## 4. 公式",
        "",
        "```",
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail",
        f"T_pull = n × (0.995×S×4939.5 + 61×min(p,128)×576) / (8 × {PREFIX_25:.3e})",
        "T_compute = n × (F_idx+F_hca+F_core+F_proj) / (8 × 33.60e15 × align(n×q))",
        f"T_AR = 61 × (5e-6 + 2×7/8 × 行 × 7168 × 2 / {P2P:.3e})",
        "T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine",
        f"T_dispatch = 61 × (5e-6 + hot × 7168 × 1 / {D2D:.3e})",
        f"T_combine  = 61 × (5e-6 + hot × 7168 × 2 / {D2D:.3e})",
        "TPOT = T_SWAP + max(T_HBM, T_compute) + T_AR + T_MoE",
        "T_SWAP = spill × 每卡稀疏读 / 换入带宽",
        "```",
        "",
        "n = ceil(全局批 / 32)。q = 0.005×S。这些 Prefill 批的 T_tail 是 0。",
        "",
        "## 5. Case 1：拉 KV 从基线改到 NEW",
        "",
        "| 输入 | 基线批 | NEW批 | TPS提升 | 基线拉KV | NEW拉KV | 基线占比 | NEW占比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        t25 = row["b25"] * row["S"] / row["p25"]["t"]
        t100 = row["b100"] * row["S"] / row["p100"]["t"]
        lines.append(
            f"| {fmt_len(row['S'])} | {row['b25']} | {row['b100']} | {signed_pct(t100, t25)} | "
            f"{row['p25']['pull']:.3f}s | {row['p100']['pull']:.3f}s | "
            f"{row['p25']['pull']/row['p25']['t']*100:.1f}% | {row['p100']['pull']/row['p100']['t']*100:.1f}% |"
        )
    lines += [
        "",
        "## 6. Case 2：总线 DDR 池",
        "",
        f"池带宽每卡 {POOL/1e12:.2f} TB/s，容量不限。对照是 H2D 路径 {HOST/1e9:.0f} GB/s。D2D 交换平面是 {D2D/1e12:.2f} TB/s，不截断这条池。",
        "",
        "| 输入 | 10ms H2D批 | 10ms 池批 | 10ms TPS提升 | 30ms H2D批 | 30ms 池批 | 30ms TPS提升 | 30ms 池 DDR/卡 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        h10, p10 = row["b10"] / row["d10"]["t"], row["p10"] / row["d10p"]["t"]
        h30, p30 = row["b30"] / row["d30"]["t"], row["p30"] / row["d30p"]["t"]
        lines.append(
            f"| {fmt_len(row['S'])} | {row['b10']} | {row['p10']} | {signed_pct(p10, h10)} | "
            f"{row['b30']} | {row['p30']} | {signed_pct(p30, h30)} | {row['m30']['ddr']:.1f} GB |"
        )
    lines += [
        "",
        f"64K、输出 {OUT_LEN}、10 毫秒的副本配比见第 4 页。单条请求不跨副本。",
        "",
        "## 7. Prefill 改到 24 卡",
        "",
        "TP=8，EP=24，DP=3。Decode 仍是 TP=8，EP=256，DP=32。",
        "每卡 Prefill TPS 与 256 卡相同。一份 24 卡副本的系统 TPS 约为 256 卡的 24/256。",
        "16 卡的 KV 房间装不下 4M 摸高批。24 卡是 8 卡对齐下，10 秒批仍由时间决定的最小副本。",
        "",
        "| 输入 | 24卡批 | 24卡TPS | 24卡每卡TPS | 256卡TPS | 拉KV秒 | TTFT秒 | 拉KV占比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        t24 = row["b24"] * row["S"] / row["p24"]["t"]
        t256 = row["b25"] * row["S"] / row["p25"]["t"]
        lines.append(
            f"| {fmt_len(row['S'])} | {row['b24']} | {t24:.6e} | {t24 / PF_N:.6e} | {t256:.6e} | "
            f"{row['p24']['pull']:.4f} | {row['p24']['t']:.4f} | {row['p24']['pull'] / row['p24']['t'] * 100:.1f}% |"
        )
    r64 = by_len(data, 65536)
    per, cluster = room_bytes(PF_N)
    kv64 = r64["b24"] * store_seq(65536) / PF_N
    lines += [
        "",
        f"24 卡每卡路由权重 {ROUTED / PF_N / 1e9:.1f} GB，KV 房间 {per / 1e9:.1f} GB，副本 {cluster / 1e12:.2f} TB。",
        f"64K 摸高批每卡实际 KV {kv64 / 1e9:.1f} GB。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2：20T DeepSeek 在 640 GB / 48P、256 卡上的 TTFT / TPOT"
    blank = prs.slide_layouts[6]
    slide_conclusion(prs, blank, data)
    slide_model(prs, blank)
    slide_hardware(prs, blank)
    slide_parallel(prs, blank, data)
    slide_tps(prs, blank, data)
    slide_prefill(prs, blank, data)
    slide_pf_tps(prs, blank, data)
    slide_pf_time(prs, blank, data)
    slide_pf_hbm(prs, blank, data)
    slide_decode(prs, blank, data)
    slide_case1(prs, blank, data)
    slide_case2(prs, blank, data)
    slide_pies(prs, blank, data)
    out = "/agent/repos/ucl-mpcomm/docs/deepseek-20t-n2-slo.pptx"
    prs.save(out)
    write_md("/agent/repos/ucl-mpcomm/docs/deepseek-20t-n2-slo.md", data)
    print(out)
    print("E", E, "ROOM_TB", round(ROOM / 1e12, 2), "cold", data["cold_s"], round(data["cold"]["t"], 4), "cold4", round(data["cold4"]["t"], 3))
    for row in data["rows"]:
        print(
            fmt_len(row["S"]),
            "pf", row["b25"], round(row["p25"]["t"], 3),
            "d10", row["b10"], f"{row['d10']['spill']*100:.1f}%",
            "d30", row["b30"], f"{row['d30']['spill']*100:.1f}%",
            "pool30", row["p30"], f"{row['d30p']['spill']*100:.1f}%",
            "ddr", round(row["m30"]["ddr"], 1),
        )


if __name__ == "__main__":
    main()
