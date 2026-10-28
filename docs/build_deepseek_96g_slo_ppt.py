#!/usr/bin/env python3
"""10T DeepSeek on a 96 GB, 486 T cluster, in the SLO deck layout.

Memory and communication bandwidths are at 80%. Compute is at 70%.
Attention and experts share one peak: 486 T x 70% = 340.2 T.

H2D is 64 GB/s per GPU: 51.2 GB/s effective, prefill only.
DDR5 is 1288.8 GB/s and 768 GB per 8-GPU machine.
Prefix-cache hits use the 40 GB/s effective parameter plane, not H2D.

D2D is 3.2 Tb/s per GPU: 400 GB/s peak, 320 GB/s effective.
Each link in the 8-GPU fullmesh is 400 Gb/s.  Seven links run in
parallel per GPU, so TP collectives get 280 GB/s effective, below the
3.2 Tb/s D2D-port ceiling.  The parameter plane remains 40 GB/s.
The supernode is 128 GPUs, intra-machine fullmesh is 8 GPUs.

The bus DDR pool is rated 480 GB/s per GPU but is capped by that
400 GB/s D2D port, so the swap path is also 320 GB/s effective.
Pool capacity is unlimited. Decode KV swap uses the pool; H2D does not.

Slides 7 and 8 are the DDR-swap pages. They list only input lengths where
the reported decode batch spills KV into the bus pool. Lengths that stay
in HBM, including a whole SLO curve with zero swap, stay on the earlier
sweep and are not repeated here as zeros. Keep this filter on later decks.
"""

from __future__ import annotations

import math

from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
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

N, TP, NODE = 128, 8, 8
DP = N // TP
PEAK_FP4 = 486e12 * 0.70
PEAK_FP8 = PEAK_FP4
HBM_CAP = 96e9
HBM_BW = 4e12 * 0.80
D2D_PEAK = 3.2e12 / 8
POOL_PEAK = min(480e9, D2D_PEAK)
D2D = D2D_PEAK * 0.80
POOL = POOL_PEAK * 0.80
P2P_LINK = 400e9 / 8
P2P = min(D2D_PEAK, (NODE - 1) * P2P_LINK) * 0.80
PARAM = 400e9 / 8 * 0.80
H2D = 64e9 * 0.80
DDR_NODE_BW = 1288.8e9 * 0.80
DDR_SHARE = DDR_NODE_BW / NODE
HOST = min(H2D, DDR_SHARE)
DDR_PER_GPU_CAP = 768e9 / NODE

E, L, H, DFF, TOPK = 2469, 61, 7168, 3072, 6
N_CSA, N_HCA = 30, 31
W_ONE = 3 * H * DFF * L
ROUTED = E * W_ONE * 0.5
SHARED = float(W_ONE)
ATTN = 19.35e9
MOE = TOPK * L * 6 * H * DFF + L * 6 * H * DFF
PROJ = ATTN * 2
BPT = N_CSA * (576 / 4 + 64 / 4) + N_HCA * (576 / 128)
FIXED = L * 128 * 576
PREFIX_HIT = 0.98
RESERVE = 6e9
ROOM = N * (HBM_CAP - ROUTED / N - SHARED - ATTN / TP - RESERVE)
EXPERT_GB = W_ONE * 0.5 / 1e9


def rgb(hex_color):
    return RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def set_run_font(run, size, bold, color, name=FONT):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    rpr = run._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        el = rpr.find(qn(f"a:{tag}"))
        if el is None:
            el = OxmlElement(f"a:{tag}")
            rpr.append(el)
        el.set("typeface", name)


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


def set_cell_fill(cell, hex_color):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for child in list(tc_pr):
        if child.tag == qn("a:solidFill"):
            tc_pr.remove(child)
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", hex_color)
    solid_fill.append(srgb)
    tc_pr.append(solid_fill)


def set_cell_borders(cell, hex_color="D6DCE2", width="6350"):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        for child in list(tc_pr):
            if child.tag == qn(f"a:{edge}"):
                tc_pr.remove(child)
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", width)
        fill = OxmlElement("a:solidFill")
        srgb = OxmlElement("a:srgbClr")
        srgb.set("val", hex_color)
        fill.append(srgb)
        ln.append(fill)
        tc_pr.append(ln)


def write_cell(cell, text, size, bold, color, align):
    tf = cell.text_frame
    tf.clear()
    tf.word_wrap = True
    cell.margin_left = Inches(0.06)
    cell.margin_right = Inches(0.06)
    cell.margin_top = Inches(0.03)
    cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, line in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        p_pr = p._p.get_or_add_pPr()
        ln_spc = OxmlElement("a:lnSpc")
        spc = OxmlElement("a:spcPct")
        spc.set("val", "100000")
        ln_spc.append(spc)
        p_pr.append(ln_spc)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def add_table(slide, x, y, widths, rows, heights, kinds, size=12):
    n_row, n_col = len(rows), len(widths)
    shape = slide.shapes.add_table(n_row, n_col, Inches(x), Inches(y), Inches(sum(widths)), Inches(sum(heights)))
    table = shape.table
    table.horz_banding = False
    table.vert_banding = False
    tbl = shape._element.graphic.graphicData.tbl
    tbl_pr = tbl.find(qn("a:tblPr"))
    if tbl_pr is None:
        tbl_pr = tbl.tblPr
    for child in list(tbl_pr):
        if child.tag == qn("a:tableStyleId"):
            tbl_pr.remove(child)
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    style = {
        "head": (HEAD, WHITE, True, PP_ALIGN.LEFT),
        "body": (WHITE, INK, False, PP_ALIGN.LEFT),
        "key": (PALE, TEAL, True, PP_ALIGN.LEFT),
        "sum": (SOFT, NAVY, True, PP_ALIGN.LEFT),
        "note": (GOLD_BG, INK, False, PP_ALIGN.LEFT),
    }
    for r, (row, h, kind) in enumerate(zip(rows, heights, kinds)):
        table.rows[r].height = Inches(h)
        fill, color, bold, align = style[kind]
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            set_cell_fill(cell, fill if c or kind == "head" else SOFT)
            if kind == "head":
                set_cell_fill(cell, HEAD)
            set_cell_borders(cell)
            this_bold = True if c == 0 and kind != "head" else bold
            this_color = NAVY if c == 0 and kind == "body" else color
            if kind in ("key", "sum", "head", "note"):
                this_color = color
                this_bold = bold or c == 0
            write_cell(cell, text, size, this_bold, this_color, align)
    return shape


def chrome(slide, page, title, kicker, total=13):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.42, 0.16, 10.6, 0.28, kicker, 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 0.42, 0.42, 12.5, 0.42, title, 26, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 11.4, 0.18, 1.5, 0.26, f"{page}  /  {total}", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(
        slide,
        0.42,
        7.20,
        12.5,
        0.24,
        "10T 为外推    ·    96 GB / 486 T、一份 128 卡副本    ·    访存与通信 80%    ·    计算 70%",
        11,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )


def banner(slide, y, text, size=14):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(y), Inches(12.5), Inches(0.46))
    solid(shape, PALE)
    textbox(slide, 0.58, y, 12.18, 0.46, text, size, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)


def chips(slide, items, number_size=28):
    for i, (cap, num, sub) in enumerate(items):
        x = 0.42 + i * 3.20
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(5.40), Inches(3.05), Inches(1.62))
        solid(card, SOFT, LINE)
        textbox(slide, x + 0.16, 5.48, 2.75, 0.26, cap, 12, True, MUTED)
        textbox(slide, x + 0.16, 5.74, 2.75, 0.50, num, number_size, True, TEAL)
        textbox(slide, x + 0.16, 6.26, 2.75, 0.64, sub, 13, False, INK)


def add_hbm_pie(slide, x, title, bs, kv_hbm, free, pool=0.0):
    """Add one per-busiest-GPU 96 GB HBM pie."""
    weights = (ROUTED / N + SHARED + ATTN / TP) / 1e9
    reserve = RESERVE / 1e9
    data = ChartData()
    data.categories = ["模型权重", "系统预留", "KV cache", "空闲"]
    data.add_series("", (weights, reserve, kv_hbm, max(free, 0.0)))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.PIE,
        Inches(x),
        Inches(1.72),
        Inches(3.86),
        Inches(3.42),
        data,
    ).chart
    chart.has_legend = False
    chart.chart_style = 10
    colors = (NAVY, GOLD, TEAL, "DCE3E9")
    for point, color in zip(chart.series[0].points, colors):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = rgb(color)
        point.format.line.color.rgb = rgb(WHITE)
    chart.plots[0].has_data_labels = True
    labels = chart.plots[0].data_labels
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.show_category_name = True
    labels.show_percentage = True
    labels.show_value = False
    labels.number_format = "0.0%"
    labels.font.name = FONT
    labels.font.size = Pt(9)
    labels.font.bold = True
    labels.font.color.rgb = rgb(INK)
    textbox(slide, x, 1.38, 3.86, 0.30, title, 15, True, NAVY, PP_ALIGN.CENTER)
    textbox(
        slide,
        x,
        5.12,
        3.86,
        0.58,
        f"BS {bs}    权重 {weights:.2f} GB    预留 {reserve:.0f} GB\n"
        f"HBM KV {kv_hbm:.2f} GB  ｜  空闲 {max(free, 0.0):.2f} GB",
        11,
        False,
        INK,
        PP_ALIGN.CENTER,
    )
    pool_text = f"DDR 池 KV（图外）：{pool:.2f} GB / 卡" if pool > 0 else "DDR 池 KV（图外）：0"
    textbox(slide, x, 5.72, 3.86, 0.28, pool_text, 11, pool > 0, GOLD if pool > 0 else MUTED, PP_ALIGN.CENTER)


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def expert_stage(tokens):
    """Full-model MoE latency for `tokens` global tokens.

    EP dispatch and combine are serialized around the fused expert kernel.
    Inside the kernel, weight reads and GEMM overlap.  The busiest EP rank is
    mean + 2 sigma.  Rows are padded separately for every active expert.
    """
    if tokens <= 0:
        tokens = 0.0
    mean_assign = tokens * TOPK / N
    hot_assign = min(
        tokens * TOPK,
        mean_assign + 2 * math.sqrt(max(mean_assign * (1 - 1 / N), 0.0)),
    )
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / N
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tokens_per_expert = hot_assign / e_hot if e_hot > 0 else 0.0
    routed_rows = e_hot * math.ceil(tokens_per_expert / 16) * 16 if e_hot else 0.0
    shared_tokens = max(1, math.ceil(tokens / N))
    shared_rows = math.ceil(shared_tokens / 16) * 16
    t_weight = (e_hot * W_ONE * 0.5 + SHARED) / HBM_BW
    t_gemm = (routed_rows + shared_rows) * 6 * H * DFF * L / PEAK_FP4
    t_dispatch = hot_assign * H * 2 * L / D2D
    t_combine = t_dispatch
    return {
        "t": t_dispatch + max(t_weight, t_gemm) + t_combine,
        "tw": t_weight,
        "tc": t_gemm,
        "dispatch": t_dispatch,
        "combine": t_combine,
        "ep": t_dispatch + t_combine,
        "e_hot": e_hot,
        "hot_assign": hot_assign,
        "tok": tokens_per_expert,
        "ue": tokens_per_expert / (math.ceil(tokens_per_expert / 16) * 16)
        if tokens_per_expert > 0
        else 1.0,
    }


def prefill_flops(p, q):
    context = q * p + q * (q + 1) / 2
    idx = N_CSA * 4096 * context
    hca = N_HCA * 2048 * context
    core = N_CSA * 262144 * (1024 + 128) * q
    proj = PROJ * q
    return idx, hca, core, proj


def prefill_batch(bs, s, hit=PREFIX_HIT):
    """TTFT data-plane model.

    Prefix pull, fused attention and TP allreduce form a chunk pipeline, so
    attention keeps the longest complete-model lane.  Attention and MoE stay
    serialized.  P-to-D sends the full KV layer by layer; only an exposed tail
    enters TTFT.  Fixed software/small-op latency is disclosed, not invented.
    Prefill attention assumes ideal tile reuse: each KV byte is read once.
    """
    n = math.ceil(bs / DP)
    p, q = hit * s, (1 - hit) * s
    rows = n * q
    idx, hca, core, proj = prefill_flops(p, q)
    row_eff = align(rows)
    denom = TP * PEAK_FP8 * row_eff
    t_idx = n * idx / denom
    t_hca = n * hca / denom
    t_core = n * core / denom
    t_proj = n * proj / denom
    t_compute = t_idx + t_hca + t_core + t_proj
    # Prefix hits reside behind the parameter plane, not in host DDR.
    prefix_bytes = p * BPT + L * min(p, 128) * 576
    t_pull = n * prefix_bytes / (TP * PARAM)
    # Ideal fused-kernel reuse: read the context once and write new KV once.
    hbm_bytes = ATTN / TP + n * (store_seq(s) + q * BPT) / TP
    t_hbm = hbm_bytes / HBM_BW
    t_ar = 2 * (TP - 1) / TP * (rows * H * 2) * L / P2P
    t_attention = max(t_pull, t_hbm, t_compute, t_ar)
    moe = expert_stage(bs * q)
    prefill = t_attention + moe["t"]
    t_pd = n * store_seq(s) / (TP * PARAM)
    # First layer releases early.  At this scale the full P-to-D transfer is
    # hidden; retain a conservative one-layer startup before overlap begins.
    overlap = prefill * (L - 1) / L
    t_tail = max(0.0, t_pd - overlap)
    return {
        "t": prefill + t_tail,
        "Q": bs * q,
        "n": n,
        "t_attention": t_attention,
        "t_ar": t_ar,
        "t_attn": t_compute,
        "t_idx": t_idx,
        "t_hca": t_hca,
        "t_core": t_core,
        "t_proj": t_proj,
        "t_hbm": t_hbm,
        "t_pull": t_pull,
        "t_moe": moe["t"],
        "t_ep": moe["ep"],
        "t_dispatch": moe["dispatch"],
        "t_combine": moe["combine"],
        "t_we": moe["tw"],
        "t_gemm": moe["tc"],
        "tkv": t_pull,
        "t_pd": t_pd,
        "t_tail": t_tail,
        "cap": hbm_cap(s),
    }


def prefill_one(s):
    row = prefill_batch(1, s, hit=0.0)
    return {
        **row,
        "idx": row["t_idx"],
        "hca": row["t_hca"],
        "core": row["t_core"],
        "proj": row["t_proj"],
        "moe": row["t_moe"],
        "tc": row["t_attn"],
        "tw": row["t_hbm"],
        "ship": row["t_pd"],
    }


def max_input(limit=10.0):
    lo, hi = 1.0, 5e6
    for _ in range(80):
        mid = (lo + hi) / 2
        if prefill_one(mid)["t"] > limit:
            hi = mid
        else:
            lo = mid
    return lo


def n_csa_read(s):
    sel = min(1024.0, s / 4.0)
    return N_CSA * (s / 4.0) * 64 + N_HCA * (s / 128.0) * 576 + N_CSA * sel * 576 + FIXED


def store_seq(s):
    return s * BPT + FIXED


def decode(bs, s):
    n = math.ceil(bs / DP)
    sel = min(1024.0, s / 4.0)
    score = N_CSA * 4096 * s + N_HCA * 2048 * s + N_CSA * 262144 * (sel + 128)
    store = bs * store_seq(s)
    read_gpu = n * n_csa_read(s) / TP
    spill = max(store - ROOM, 0.0) / store if store else 0.0
    t_pool = read_gpu * spill / POOL
    t_hbm = (read_gpu + ATTN / TP) / HBM_BW
    t_ca = n * (score + PROJ) / (TP * PEAK_FP8 * align(n))
    t_ar = 2 * (TP - 1) / TP * (n * H * 2) * L / P2P
    t_attn = t_pool + max(t_ca, t_hbm) + t_ar
    moe = expert_stage(bs)
    return {
        "t": t_attn + moe["t"],
        "t_attn": t_attn,
        "t_moe": moe["t"],
        "t_ca": t_ca,
        "tw": moe["tw"],
        "t_cm": moe["tc"],
        "t_ep": moe["ep"],
        "t_dispatch": moe["dispatch"],
        "t_combine": moe["combine"],
        "t_ar": t_ar,
        "t_kv": t_hbm,
        "t_hbm": t_hbm,
        "t_pool": t_pool,
        "t_wa": (ATTN / TP) / HBM_BW,
        "frac": 1 - math.exp(-TOPK * bs / E),
        "e_hot": moe["e_hot"],
        "tok": moe["tok"],
        "ue": moe["ue"],
        "ua": align(n),
        "toks": n,
        "n": n,
        "spill": spill,
        "store": store,
    }


def hbm_cap(s):
    return int(ROOM // store_seq(s))


def search_bs(s, limit):
    best = 0
    for bs in range(1, 50_001):
        if decode(bs, s)["t"] <= limit:
            best = bs
        elif best and bs > best + 4096:
            break
    return best


def max_prefill_bs(s, hit=PREFIX_HIT, limit=10.0):
    lo, hi = 0, 1
    while prefill_batch(hi, s, hit)["t"] <= limit:
        lo, hi = hi, hi * 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if prefill_batch(mid, s, hit)["t"] <= limit:
            lo = mid
        else:
            hi = mid
    return lo


def fmt_tok(n):
    if n >= 1e6:
        return f"{n / 1e6:.2f}×10^6"
    if n >= 1e3:
        return f"{n / 1e3:.1f}×10^3"
    return f"{n:.0f}"


def fmt_len(s):
    if s >= 1048576 and s % 1048576 == 0:
        return f"{s // 1048576}M"
    if s % 1024 == 0 and s >= 1024:
        return f"{s // 1024}K"
    return str(s)


def fmt_bytes(n):
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    return f"{n / 1e6:.1f} MB"


def fmt_count(n):
    if n >= 10000:
        v = n / 10000
        return f"{v:.1f} 万" if v >= 10 else f"{v:.2f} 万"
    return str(n)


def per_card(bs):
    v = bs / N
    return f"{v:.1f}" if v >= 1 else f"{v:.2f}"


def ms(v):
    return f"{v * 1e3:.1f} 毫秒"


def ms2(v):
    return f"{v * 1e3:.2f} 毫秒"


def sec(v):
    if v >= 9.95:
        return f"{v:.1f} 秒"
    return f"{v:.2f} 秒"


def where(spill):
    if spill < 0.005:
        return "全在 HBM"
    return f"{spill * 100:.1f}% 在总线内存池"


def hbm_span(rows, batch_key, dec_key, bs):
    labels = []
    for row in rows:
        if row[batch_key] == bs and row[dec_key]["spill"] < 0.005:
            labels.append(fmt_len(row["S"]))
        else:
            break
    if not labels:
        return "短输入"
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]} – {labels[-1]}"


def main():
    s_max = max_input()
    s_show = int(s_max)
    p = prefill_one(s_show)
    weight_gb = (ROUTED / N + SHARED + ATTN / TP) / 1e9
    kv_gb = s_show * BPT / 1e9
    bs10 = search_bs(4096, 0.010)
    bs30 = search_bs(4096, 0.030)
    d10 = decode(bs10, 4096)
    d30 = decode(bs30, 4096)

    lengths = (4096, 8192, 32768, 131072, 262144, 524288, 1048576)
    sweep = []
    for s in lengths:
        b10 = search_bs(s, 0.010)
        b30 = search_bs(s, 0.030)
        sweep.append({
            "S": s,
            "store": store_seq(s),
            "cap": hbm_cap(s),
            "b10": b10,
            "b30": b30,
            "d10": decode(b10, s),
            "d30": decode(b30, s),
        })
    extra = {}
    for s in (2_000_000, 4_000_000, s_show):
        b10 = search_bs(s, 0.010)
        b30 = search_bs(s, 0.030)
        extra[s] = {
            "b10": b10,
            "b30": b30,
            "d10": decode(b10, s),
            "d30": decode(b30, s),
            "cap": hbm_cap(s),
        }
    by_len = {row["S"]: row for row in sweep}

    pb = []
    for s in lengths:
        bs = max_prefill_bs(s)
        row = prefill_batch(bs, s)
        row["S"] = s
        row["bs"] = bs
        pb.append(row)
    by_s = {row["S"]: row for row in pb}
    p4, p1m = by_s[4096], by_s[1048576]
    one_1m = prefill_batch(1, 1048576)
    span10 = hbm_span(sweep, "b10", "d10", bs10)
    span30 = hbm_span(sweep, "b30", "d30", bs30)
    prefill_rps = p4["bs"] / 10.0
    dec10_rps = bs10 / 0.010 / 512
    dec30_rps = bs30 / 0.030 / 512
    pd10 = prefill_rps / dec10_rps
    pd30 = prefill_rps / dec30_rps
    s_label = f"{s_show / 1e6:.2f}×10^6"

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "10T DeepSeek：96 GB / 486 T 上的 TTFT / TPOT"
    blank = prs.slide_layouts[6]

    # ----- slide 1 -----
    s1 = prs.slides.add_slide(blank)
    chrome(s1, 1, "同一骨架，只加路由专家", "模型结构    ·    1.6T 论文到 10T 外推")
    textbox(
        s1,
        0.42,
        0.90,
        12.5,
        0.30,
        "1.6T 是 V4-Pro 论文原模型。10T 沿用层数、隐藏和中间维，用路由专家个数把总参数对齐到 10^13。",
        14,
        False,
        INK,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    rows = [
        ["项目", "1.6T  论文 V4-Pro", "10T  外推", "备注"],
        ["总参数", "1.600×10^12", "1.000×10^13", "DeepSeek 未发布 10T，本档是外推"],
        ["路由专家", "384", "2469", "×6.43。增量全部记在专家个数上"],
        ["激活参数", "4.9×10^10", "4.9×10^10", "每 token 仍激活 6 个路由专家 + 1 个共享"],
        ["激活比", "3.06%", "0.49%", "专家表变大，单 token 激活不变"],
        ["FP4 专家表", "0.774 TB", "4.975 TB", "单个专家全层 2.015 GB"],
        ["层 / 隐藏 / 中间维", "61 / 7168 / 3072", "同左", "外推不动这三项"],
        ["注意力", "CSA m=4，topk=1024\nHCA m′=128，滑窗 128", "同左", "30 层 CSA、31 层 HCA。KV 仍是 4939.5 B/token"],
        ["单 token 专家通信", "7.87×10^6 字节", "同左", "6 × 3 × 7168 × 61，与专家总数无关"],
        ["640 GB 卡下限", "2 张", "8 张", "只按 FP4 专家表。时延页用本档 96 GB × 128 卡"],
    ]
    add_table(
        s1,
        0.42,
        1.24,
        [2.15, 3.15, 2.55, 4.65],
        rows,
        [0.32] + [0.40] * 6 + [0.44] + [0.40] * 2,
        ["head"] + ["body"] * 9,
        size=12,
    )
    note = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.42), Inches(12.5), Inches(1.44))
    solid(note, GOLD_BG)
    textbox(
        s1,
        0.58,
        5.48,
        12.18,
        1.32,
        "外推式：总参数 = 专家数 × 4.030×10^9 + 5.260×10^10。单个专家 = 3 × 7168 × 3072 × 61。\n"
        "本档：96 GB HBM，4 TB/s 取 80% 为 3.20 TB/s。算力 486 T 取 70% 为 340.2 T，注意力和专家共用。H2D 每卡 64 GB/s 取 80% 为 51.2 GB/s，只在 prefill。机内 DDR5 每机 1288.8 GB/s、768 GB。\n"
        "D2D 每卡 3.2 Tb/s = 400 GB/s，取 80% 为 320 GB/s。内存池标称 480 GB/s，被这条 400 GB/s 的口卡住，有效也是 320 GB/s，容量不设上限。"
        "8卡fullmesh每条链路400 Gb/s，7链路并发后取80%为280 GB/s；参数面仍为40 GB/s。",
        13,
        False,
        GOLD,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    s1.notes_slide.notes_text_frame.text = (
        "1.6T 来自 V4-Pro 论文 arXiv:2606.19348：61 层，隐藏 7168，384 个路由专家，中间维 3072，每 token 激活 6 个，激活参数 49B。"
        "单个路由专家在全部层上是 3×7168×3072×61 = 4.030×10^9。"
        "384 个专家为 1.547×10^12，总参数 1.600×10^12 减去这一项，其余 5.260×10^10 含共享专家、注意力、mHC、词表和 MTP。"
        "10T 把专家数解成 2469，总参数 = 2469×4.030×10^9 + 5.260×10^10 = 1.000×10^13。"
        "FP4 容量 = 2469×4.030×10^9×0.5 字节 = 4.975 TB。640 GB 卡下限是 ceil(4.975 TB / 640 GB) = 8。"
        "单 token 通信量 6×3×7168×61 = 7.87×10^6 字节。每 token 仍只派 6 个专家，通信量不随专家总数变。"
        "后面几页是 96 GB、486 T 这一档。算力 486×10^12 再乘 70%，有效 340.2×10^12。注意力和专家用同一个峰值。"
        "HBM 96 GB，带宽 4 TB/s，计时取 80% 即 3.20 TB/s。"
        "H2D 是 64 GB/s（字节），80% 后 51.2 GB/s。这条链路只在 prefill 使用。权重放得进 HBM，冷的 10 秒不走 H2D。"
        "D2D 3.2 Tb/s：换算400 GB/s峰值，80%后320 GB/s。8卡fullmesh每卡有7条400 Gb/s链路：聚合350 GB/s峰值，受D2D口约束前已较低，80%后AllReduce按280 GB/s。参数面400 Gb/s，80%后40 GB/s。"
        "DDR5 的 1288.8 GB/s 和 768 GB 按一台 8 卡机器记。有效 1031 GB/s，每卡分到 128.9 GB/s 和 96 GB。H2D 只有 51.2 GB/s，主机路径被 H2D 卡住。"
        "超节点内直挂总线的 DDR 池容量不设上限，标称每卡 480 GB/s。GPU 单向口只有 400 GB/s，池的访问取两者里较慢的，80% 后 320 GB/s。换入发生在注意力阶段，专家 combine 发生在 MoE 阶段，两段各用满这条 320 GB/s。"
        "本页的池带宽按每卡，不把 480 GB/s 理解成 128 卡共享。"
        "注意力 TP=8 留在机内 fullmesh，16 台机器做 DP=16。MoE EP=128 走 D2D。"
        f"每卡扣掉路由 {ROUTED/N/1e9:.2f} GB、共享 {SHARED/1e9:.2f} GB、注意力 {ATTN/TP/1e9:.2f} GB 和 6 GB 预留后，128 卡 KV 余量 {ROOM/1e12:.2f} TB。"
        "Prefill 与 Decode 的副本数可以按吞吐配，副本个数不改变单副本的 TTFT 和 TPOT。"
    )

    # ----- slide 2 -----
    s2 = prs.slides.add_slide(blank)
    chrome(s2, 2, f"10 秒对应的最大输入是 {s_label}", "Prefill    ·    TTFT ≤ 10 秒")
    banner(
        s2,
        0.92,
        f"冷请求：Attention {sec(p['t_attention'])}（AR {sec(p['t_ar'])}、计算 {sec(p['t_attn'])}），MoE {sec(p['t_moe'])}；P→D {ms(p['t_pd'])} 全部隐藏。",
        size=13,
    )
    textbox(s2, 0.42, 1.46, 6.2, 0.24, "并行策略", 13, True, ACCENT)
    par_rows = [
        ["", "Attention", "MoE"],
        ["并行", "机内 TP=8\n16 台机器做 DP=16", "超节点 EP=128\n一份模型铺满 128 卡"],
        ["通信域", "8卡 fullmesh，7链路并发\nAllReduce 有效 280 GB/s", "128卡 D2D，有效320 GB/s\nKV走参数面，有效40 GB/s"],
        [
            "每卡权重",
            f"注意力 19.35 GB / 8\n= {ATTN / TP / 1e9:.2f} GB FP8",
            f"路由专家 {E / N:.1f} 个，{ROUTED / N / 1e9:.1f} GB FP4\n共享专家 {SHARED / 1e9:.2f} GB，每卡一份",
        ],
        ["本阶段角色", "Attention 取计算、HBM、AR 的瓶颈\n按实际最长通路决定", f"dispatch + 融合专家 kernel + combine\n到这个长度合计 {sec(p['moe'])}"],
    ]
    add_table(
        s2,
        0.42,
        1.74,
        [1.55, 5.40, 5.55],
        par_rows,
        [0.28, 0.50, 0.56, 0.52, 0.50],
        ["head", "body", "body", "body", "body"],
    )
    textbox(s2, 0.42, 4.26, 12.5, 0.22, "10 秒怎么落到这个输入长度", 13, True, ACCENT)
    calc_rows = [
        ["这一笔", "算法", f"S = {s_show / 1e6:.2f}×10^6 时"],
        ["CSA indexer", "30 层 × 2048 × S²；TP=8，按 16 行砖", sec(p["idx"])],
        ["HCA", "31 层 × 1024 × S²；同一个融合 kernel", sec(p["hca"])],
        ["MoE", "dispatch + max(专家权重, GEMM) + combine", sec(p["moe"])],
        ["投影", "每 token 3.87×10^10 FLOP；按 TP=8 分担", sec(p["proj"])],
        ["稀疏注意力", "每 token 看 1024 条压缩 KV + 128 滑窗", sec(p["core"])],
        [
            "AR + P→D",
            "AR 在 Attention 内取瓶颈；完整 KV 按层发送",
            f"{sec(p['t_ar'])} + {ms2(p['t_pd'])}",
        ],
        ["合计", "Attention 9.60 秒 + MoE 0.40 秒；P→D 尾巴为 0", "10.0 秒"],
    ]
    add_table(
        s2,
        0.42,
        4.60,
        [1.70, 7.55, 3.25],
        calc_rows,
        [0.26, 0.26, 0.26, 0.26, 0.26, 0.26, 0.28, 0.28],
        ["head", "body", "body", "body", "body", "body", "body", "sum"],
        size=12,
    )
    s2.notes_slide.notes_text_frame.text = (
        "单请求不跨副本。增加 Prefill 节点是多放几份 128 卡副本，提高并发，单条 TTFT 不变。"
        "冷请求没有 prefix 拉取。Attention = max(HBM, compute, AR)，MoE = dispatch + max(weight, GEMM) + combine，两段相加。"
        f"在 S={s_show:.0f}：indexer {p['idx']:.4f}s，HCA {p['hca']:.4f}s，投影 {p['proj']:.4f}s，稀疏注意力 {p['core']:.4f}s，"
        f"Attention 计算 {p['t_attn']:.4f}s，AR {p['t_ar']:.4f}s，所以 Attention 取 {p['t_attention']:.4f}s。"
        f"MoE {p['t_moe']:.4f}s。完整 KV 的 P-D 传输 {p['t_pd']*1e3:.2f} ms，layer-wise 发送后尾巴 {p['t_tail']*1e3:.2f} ms。"
        f"数据面合计 {p['t']:.4f}s。固定开销没有实测，不计入；生产最大长度必须再留余量。"
    )

    # ----- slide 3 -----
    s3 = prs.slides.add_slide(blank)
    chrome(s3, 3, f"4K 的 prefill 全局批是 {p4['bs']}，1M 是 {p1m['bs']}", "Prefill    ·    TTFT ≤ 10 秒    ·    KV 命中 98%")
    banner(
        s3,
        0.92,
        "98% prefix 经参数面 40 GB/s 拉入 HBM，只现算 2%。Attention 取拉取、融合 kernel、AR 的瓶颈，再加完整 MoE。",
        size=14,
    )
    textbox(s3, 0.42, 1.44, 12.5, 0.22, "10 秒在两个端点上怎么加完", 13, True, ACCENT)
    walk = [
        ["笔", "算法", f"4K，全局批 {p4['bs']}", f"1M，全局批 {p1m['bs']}"],
        ["现算 token", "批 × 输入 × 0.02", fmt_tok(p4["Q"]), fmt_tok(p1m["Q"])],
        [
            "机内 allreduce",
            "每组现算 token × 7168 × 2 字节\n61 层 × 2×7/8 / 280 GB/s",
            sec(p4["t_ar"]),
            sec(p1m["t_ar"]),
        ],
        [
            "注意力计算",
            "indexer、HCA、稀疏注意力、投影\n除以 340.2 T",
            sec(p4["t_attn"]),
            sec(p1m["t_attn"]),
        ],
        [
            "MoE",
            "dispatch + max(专家权重, GEMM) + combine",
            sec(p4["t_moe"]),
            sec(p1m["t_moe"]),
        ],
        ["相加", "Attention 瓶颈 + 完整 MoE；P→D 尾巴为 0", sec(p4["t"]), sec(p1m["t"])],
    ]
    add_table(
        s3,
        0.42,
        1.68,
        [1.70, 5.15, 2.85, 2.80],
        walk,
        [0.26, 0.30, 0.50, 0.48, 0.50, 0.32],
        ["head", "body", "key", "body", "body", "sum"],
    )
    textbox(s3, 0.42, 4.18, 12.5, 0.22, "同一条 10 秒，输入从 4K 到 1M", 13, True, ACCENT)
    sweep_head = ["输入", "10 秒全局批", "每卡", "现算 token", "allreduce", "MoE", "注意力计算", "拉 prefix"]
    sweep_body, sweep_kinds = [], ["head"]
    for row in pb:
        sweep_kinds.append("key" if row["S"] in (4096, 1048576) else "body")
        sweep_body.append([
            fmt_len(row["S"]),
            f"{row['bs']}",
            per_card(row["bs"]),
            fmt_tok(row["Q"]),
            sec(row["t_ar"]),
            sec(row["t_moe"]),
            sec(row["t_attn"]),
            ms(row["tkv"]),
        ])
    add_table(
        s3,
        0.42,
        4.50,
        [1.05, 1.55, 0.95, 1.70, 1.55, 1.55, 1.85, 2.30],
        [sweep_head] + sweep_body,
        [0.24] + [0.24] * len(sweep_body),
        sweep_kinds,
        size=11,
    )
    textbox(
        s3,
        0.42,
        6.66,
        12.5,
        0.28,
        f"98% prefix 走参数面：4K 这一批拉取 {ms(p4['t_pull'])}，1M 拉取 {ms(p1m['t_pull'])}；均短于 Attention 主瓶颈。",
        13,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    s3.notes_slide.notes_text_frame.text = (
        "这一页的批是 128 卡副本上的全局批，每卡条数 = 全局批 / 128。切分与上一页相同：注意力 TP=8、DP=16，MoE EP=128。"
        "KV 命中 98%，命中部分经每卡 40 GB/s 的参数面拉到 HBM。每条只现算 2%，这些 query 的平均上下文约为 99%S。"
        "Attention = max(prefix pull, HBM, compute, AR)。MoE = dispatch + max(weight, GEMM) + combine。Attention 与 MoE 相加。"
        f"4K 全局批 {p4['bs']}：现算 {p4['Q']:.4e} token，allreduce {p4['t_ar']:.3f}s，注意力计算 {p4['t_attn']:.3f}s，专家计算 {p4['t_moe']:.3f}s，"
        f"EP 双向 {p4['t_ep']:.3f}s，读专家权重 {p4['t_we']*1e3:.2f} ms，拉 prefix {p4['t_pull']*1e3:.1f} ms，合计 {p4['t']:.3f}s。"
        f"再加一条是 {prefill_batch(p4['bs']+1, 4096)['t']:.3f}s。"
        f"1M 全局批 {p1m['bs']}：现算 {p1m['Q']:.4e}，allreduce {p1m['t_ar']:.3f}s，注意力计算 {p1m['t_attn']:.3f}s（indexer {p1m['t_idx']:.3f}s），"
        f"MoE {p1m['t_moe']:.3f}s，EP 双向 {p1m['t_ep']:.3f}s，拉 prefix {p1m['t_pull']*1e3:.1f} ms，合计 {p1m['t']:.3f}s。"
        f"P-D 完整 KV 分层发送：4K {p4['t_pd']*1e3:.2f} ms，1M {p1m['t_pd']*1e3:.2f} ms；尾巴都是 0。固定开销未计入。"
    )

    # ----- slide 4 -----
    s4 = prs.slides.add_slide(blank)
    chrome(s4, 4, f"10 毫秒、短输入，全局批 {bs10}", "Decode    ·    TPOT ≤ 10 毫秒")
    banner(
        s4,
        0.92,
        f"读专家 {ms2(d10['tw'])}，只醒了 {d10['e_hot']:.1f} 个。机内 allreduce {ms2(d10['t_ar'])}。专家 GEMM {ms2(d10['t_cm'])}。",
        size=14,
    )
    textbox(s4, 0.42, 1.46, 6.0, 0.24, "并行策略", 13, True, ACCENT)
    textbox(s4, 7.15, 1.46, 5.7, 0.24, "短输入（4K）这一步怎么加到 10 毫秒", 13, True, ACCENT)
    hot_gb = (d10["e_hot"] * W_ONE * 0.5 + SHARED) / 1e9
    par4 = [
        ["", "Attention", "MoE"],
        ["并行", "TP=8，DP=16\n每组 token 数 = ⌈BS / 16⌉", "EP=128\n2469 个专家，每卡 19.3 个"],
        ["通信", f"AR 在融合 kernel 后单独加\n{ms2(d10['t_ar'])}", f"dispatch + combine\n合计 {ms2(d10['t_ep'])}"],
        ["访存", f"全部 KV + 2.42 GB 权重\n{ms2(d10['t_hbm'])}", f"醒了 {d10['e_hot']:.1f} / 19.3 个\n读权重 {ms2(d10['tw'])}"],
        ["计算", f"行数 = ⌈BS / 16⌉\n融合 kernel {ms2(d10['t_ca'])}", f"逐专家 16 行 padding\nGEMM {ms2(d10['t_cm'])}"],
    ]
    add_table(s4, 0.42, 1.78, [1.15, 2.55, 2.70], par4, [0.28, 0.58, 0.58, 0.62, 0.58], ["head", "body", "body", "key", "body"], size=12)
    step4 = [
        ["笔", "白话", "时间"],
        ["Attn kernel", f"max(HBM {d10['t_hbm']*1e3:.2f}, 计算 {d10['t_ca']*1e3:.2f})", ms2(max(d10["t_hbm"], d10["t_ca"]))],
        ["AR", f"每组 {d10['toks']} 条；61层 fullmesh\n7链路并发，不与kernel重叠", ms2(d10["t_ar"])],
        ["MoE 通信", "最忙卡 dispatch + combine\n两个方向分别统计", ms2(d10["t_ep"])],
        ["专家 kernel", f"max(读权重 {d10['tw']*1e3:.2f}, GEMM {d10['t_cm']*1e3:.2f})", ms2(max(d10["tw"], d10["t_cm"]))],
        ["相加", f"Attention {d10['t_attn']*1e3:.2f} + MoE {d10['t_moe']*1e3:.2f}", ms2(d10["t"])],
    ]
    add_table(
        s4,
        7.05,
        1.78,
        [1.20, 3.50, 1.15],
        step4,
        [0.28, 0.54, 0.52, 0.52, 0.52, 0.42],
        ["head", "key", "key", "body", "body", "sum"],
        size=12,
    )
    chips(
        s4,
        [
            (span10, str(bs10), f"全局批，每卡 {per_card(bs10)} 条\n全在 HBM"),
            ("128K", str(by_len[131072]["b10"]), f"全局批，每卡 {per_card(by_len[131072]['b10'])} 条\n{where(by_len[131072]['d10']['spill'])}"),
            ("1M", str(by_len[1048576]["b10"]), f"全局批，每卡 {per_card(by_len[1048576]['b10'])} 条\n{where(by_len[1048576]['d10']['spill'])}"),
            (s_label, str(extra[s_show]["b10"]), f"全局批，每卡 {per_card(extra[s_show]['b10'])} 条\n{where(extra[s_show]['d10']['spill'])}"),
        ],
    )
    s4.notes_slide.notes_text_frame.text = (
        "Decode 与 Prefill 用同一份 128 卡副本：注意力 TP=8、DP=16，MoE EP=128。"
        "加 Decode 节点是多副本，单副本的 TPOT 不变。"
        "Attention = SWAP + max(HBM, compute) + AR。MoE = dispatch + max(weight, GEMM) + combine。两段相加。"
        f"命中率 = 1 − exp(−6×{bs10} / 2469) = {d10['frac']:.4f}。最忙卡激活专家 {d10['e_hot']:.3f}。"
        f"读权重 ({d10['e_hot']:.3f}×{EXPERT_GB:.3f} GB + {SHARED/1e9:.3f} GB) / 3.20 TB/s = {d10['tw']*1e3:.3f} ms。"
        f"机内 allreduce：ceil({bs10}/16) = {d10['toks']} 条，每条7168×2字节，每层通信量2×7/8，61层除以280 GB/s = {d10['t_ar']*1e3:.3f} ms。"
        f"Attention {d10['t_attn']*1e3:.3f} ms，MoE {d10['t_moe']*1e3:.3f} ms，合计 {d10['t']*1e3:.3f} ms。{bs10+1} 条是 {decode(bs10+1, 4096)['t']*1e3:.3f} ms。"
        f"专家计算 {d10['t_cm']*1e3:.3f} ms，EP 双向 {d10['t_ep']*1e3:.3f} ms。注意力计算 {d10['t_ca']*1e3:.3f} ms，HBM {d10['t_hbm']*1e3:.3f} ms。"
        f"{span10} 的全局批都是 {bs10}，KV 全在 HBM。"
        f"2M 降到 {extra[2_000_000]['b10']}，存量约 {extra[2_000_000]['d10']['spill']*100:.1f}% 在总线内存池，池上稀疏读 {extra[2_000_000]['d10']['t_pool']*1e3:.2f} ms，已经顶到 allreduce 留下的预算。"
        f"1M 降到 {by_len[1048576]['b10']}，{s_label} 降到 {extra[s_show]['b10']}。这些批的存量都放得进 HBM，池上换入是 0。H2D 只在 prefill。"
    )

    # ----- slide 5 -----
    s5 = prs.slides.add_slide(blank)
    chrome(s5, 5, f"30 毫秒、短输入，全局批 {bs30}", "Decode    ·    TPOT ≤ 30 毫秒")
    banner(
        s5,
        0.92,
        f"专家整卡读完 {ms2(d30['tw'])}，机内 allreduce {ms2(d30['t_ar'])}。D2D 上的 EP {ms2(d30['t_ep'])}。",
        size=14,
    )
    textbox(s5, 0.42, 1.46, 6.2, 0.24, "并行策略    ·    和 10 毫秒同一份切分", 13, True, ACCENT)
    textbox(s5, 7.15, 1.46, 5.7, 0.24, f"短输入、全局批 {bs30}，这一步怎么加", 13, True, ACCENT)
    hot30 = (d30["e_hot"] * W_ONE * 0.5 + SHARED) / 1e9
    par5 = [
        ["", "Attention", "MoE"],
        ["并行", f"仍是 TP=8，DP=16\n{bs30} / 16 = {d30['toks']} 条 / 组", "仍是 EP=128\n每卡 19.3 个专家全醒"],
        ["通信", "AR 在融合 kernel 后单独加\n这一档不能隐藏", f"dispatch + combine 走 320 GB/s\n合计 {ms2(d30['t_ep'])}"],
        ["访存", "短输入全在 HBM\n放不下走每卡内存池 320 GB/s", f"{ROUTED/N/1e9:.1f} GB 路由 + {SHARED/1e9:.2f} GB 共享\n/ 3.20 TB/s = {ms2(d30['tw'])}"],
        ["计算", f"注意力计算 {ms2(d30['t_ca'])}\n与HBM取大后再加AR", f"每专家约 {d30['tok']:.1f} token\n16 行砖，效率 {d30['ue']*100:.0f}%，{ms2(d30['t_cm'])}"],
    ]
    add_table(s5, 0.42, 1.78, [1.15, 2.55, 2.70], par5, [0.28, 0.58, 0.58, 0.62, 0.58], ["head", "body", "key", "body", "body"], size=12)
    step5 = [
        ["笔", "白话", "时间"],
        ["Attn kernel", f"max(HBM {d30['t_hbm']*1e3:.2f}, 计算 {d30['t_ca']*1e3:.2f})", ms2(max(d30["t_hbm"], d30["t_ca"]))],
        ["AR", f"每组 {d30['toks']} 条；61层 fullmesh\n7链路并发，不与kernel重叠", ms2(d30["t_ar"])],
        ["MoE 通信", "最忙卡 dispatch + combine\n两个方向分别统计", ms2(d30["t_ep"])],
        ["专家 kernel", f"max(读权重 {d30['tw']*1e3:.2f}, GEMM {d30['t_cm']*1e3:.2f})", ms2(max(d30["tw"], d30["t_cm"]))],
        ["相加", f"Attention {d30['t_attn']*1e3:.2f} + MoE {d30['t_moe']*1e3:.2f}", ms2(d30["t"])],
    ]
    add_table(
        s5,
        7.05,
        1.78,
        [1.25, 3.45, 1.15],
        step5,
        [0.28, 0.52, 0.52, 0.52, 0.52, 0.42],
        ["head", "key", "key", "body", "body", "sum"],
        size=12,
    )
    chips(
        s5,
        [
            (span30, str(bs30), f"全局批，每卡 {per_card(bs30)} 条\n全在 HBM"),
            ("256K", str(by_len[262144]["b30"]), f"全局批，每卡 {per_card(by_len[262144]['b30'])} 条\n{where(by_len[262144]['d30']['spill'])}"),
            ("512K", str(by_len[524288]["b30"]), f"全局批，每卡 {per_card(by_len[524288]['b30'])} 条\n{where(by_len[524288]['d30']['spill'])}"),
            (s_label, str(extra[s_show]["b30"]), f"全局批，每卡 {per_card(extra[s_show]['b30'])} 条\n{where(extra[s_show]['d30']['spill'])}"),
        ],
        number_size=26,
    )
    s5.notes_slide.notes_text_frame.text = (
        "30 毫秒用的切分与 10 毫秒相同：TP=8，DP=16，EP=128，128 卡一份副本。"
        f"BS={bs30} 时命中率 {d30['frac']:.4f}，最忙卡激活 {d30['e_hot']:.3f} 个专家。"
        f"读权重 ({ROUTED/N/1e9:.2f} GB + {SHARED/1e9:.2f} GB) / 3.20 TB/s = {d30['tw']*1e3:.3f} ms。"
        f"机内 allreduce：ceil({bs30}/16) = {d30['toks']} 条，每层通信量2×7/8，61层，除以280 GB/s = {d30['t_ar']*1e3:.3f} ms。"
        f"Attention {d30['t_attn']*1e3:.3f} ms，MoE {d30['t_moe']*1e3:.3f} ms，合计 {d30['t']*1e3:.3f} ms。{bs30+1} 条是 {decode(bs30+1, 4096)['t']*1e3:.3f} ms。"
        f"EP 双向 {d30['t_ep']*1e3:.3f} ms，专家计算 {d30['t_cm']*1e3:.3f} ms，效率 {d30['ue']:.3f}。注意力计算 {d30['t_ca']*1e3:.3f} ms。"
        f"显存：每卡 96 − {ROUTED/N/1e9:.2f} − {SHARED/1e9:.2f} − {ATTN/TP/1e9:.2f} − 6 = {(HBM_CAP - ROUTED/N - SHARED - ATTN/TP - RESERVE)/1e9:.2f} GB，128 卡共 {ROOM/1e12:.2f} TB。"
        "HBM 放不下的 KV 走每卡总线内存池。标称 480 GB/s，被 3.2 Tb/s 的口卡住，有效 320 GB/s，容量不设上限。H2D 只在 prefill。"
        f"256K、全局批 {by_len[262144]['b30']} 时已有 {by_len[262144]['d30']['spill']*100:.1f}% KV 在池中，池上读 {by_len[262144]['d30']['t_pool']*1e3:.2f} ms。"
        f"512K 降到 {by_len[524288]['b30']}，池上读 {by_len[524288]['d30']['t_pool']*1e3:.2f} ms。1M 降到 {by_len[1048576]['b30']}，{s_label} 降到 {extra[s_show]['b30']}。"
        f"4K、输出 512、命中 98%：Prefill {prefill_rps:.1f} 请求/秒。10 毫秒 Decode {dec10_rps:.1f} 请求/秒，P:D ≈ 1:{pd10:.1f}。30 毫秒 Decode {dec30_rps:.1f} 请求/秒，P:D ≈ 1:{pd30:.1f}。"
    )

    # ----- slide 6 -----
    s6 = prs.slides.add_slide(blank)
    chrome(s6, 6, "10 毫秒都不进池；30 毫秒从 256K 开始使用 DDR 池", "Decode    ·    不同输入下的最大全局批")
    banner(
        s6,
        0.92,
        "全局批是 128 卡上的条数。放不下的 KV 进每卡总线内存池。池标称 480 GB/s，被 3.2 Tb/s 卡住，有效 320 GB/s。",
        size=13,
    )
    head = ["输入", "每条 KV", "HBM 能放", "10 毫秒全局批", "每卡", "30 毫秒全局批", "每卡", "30 毫秒的 KV 放哪"]
    body, kinds = [], ["head"]
    for row in sweep:
        spill = row["d30"]["spill"]
        kinds.append("key" if spill >= 0.005 else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bytes(row["store"]),
            fmt_count(row["cap"]),
            f"{row['b10']}",
            per_card(row["b10"]),
            f"{row['b30']}",
            per_card(row["b30"]),
            where(spill),
        ])
    add_table(
        s6,
        0.42,
        1.50,
        [1.15, 1.35, 1.35, 1.70, 1.00, 1.75, 1.00, 3.20],
        [head] + body,
        [0.36] + [0.42] * len(body),
        kinds,
        size=12,
    )
    d1m = by_len[1048576]["d30"]
    note = s6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.02), Inches(12.5), Inches(1.84))
    solid(note, GOLD_BG)
    textbox(
        s6,
        0.58,
        5.08,
        12.18,
        1.72,
        f"10 毫秒在 {span10} 都是 {bs10}，全在 HBM。短输入 Attention {d10['t_attn']*1e3:.2f} 毫秒，MoE {d10['t_moe']*1e3:.2f} 毫秒。"
        f"1M 降到 {by_len[1048576]['b10']}，{s_label} 是 {extra[s_show]['b10']}，仍然全在 HBM。\n"
        f"30 毫秒短输入为 {bs30}。256K 为 {by_len[262144]['b30']}，已有 {by_len[262144]['d30']['spill']*100:.1f}% KV 在池中；"
        f"Attention {by_len[262144]['d30']['t_attn']*1e3:.1f} 毫秒，MoE {by_len[262144]['d30']['t_moe']*1e3:.1f} 毫秒。"
        f"512K 降到 {by_len[524288]['b30']}，1M 为 {by_len[1048576]['b30']}，{s_label} 为 {extra[s_show]['b30']}。\n"
        f"Prefill 的 10 秒全局批在第 3 页：4K 为 {p4['bs']}，1M 为 {p1m['bs']}。"
        f"4K 进、512 出、98% 命中时，P:D 在 10 毫秒约 1:{pd10:.1f}，在 30 毫秒约 1:{pd30:.1f}。",
        14,
        False,
        GOLD,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    lines = []
    for row in sweep:
        lines.append(
            f"S={row['S']} store={row['store']/1e6:.1f}MB cap={row['cap']} "
            f"b10={row['b10']} spill10={row['d10']['spill']*100:.2f}% pool10={row['d10']['t_pool']*1e3:.2f}ms "
            f"b30={row['b30']} spill30={row['d30']['spill']*100:.2f}% pool30={row['d30']['t_pool']*1e3:.2f}ms "
            f"t30={row['d30']['t']*1e3:.2f}ms"
        )
    s6.notes_slide.notes_text_frame.text = (
        "BS 一律是 128 卡副本的全局批。每卡条数 = 全局批 / 128。"
        "存量 = S×4939.5 字节 + 4.50 MB。一步真正读的是压缩 indexer、最多 1024 条完整 KV 和 HCA，所以溢出比例高时，池上的读时延仍可能短于 allreduce。"
        f"HBM 余量 {ROOM/1e12:.2f} TB。溢出进 GPU 的口是每卡总线内存池，有效 {POOL/1e9:.0f} GB/s，容量不设上限。"
        "这个带宽是 min(480 GB/s, 3.2 Tb/s = 400 GB/s) 再取 80%。专家通信在 MoE 阶段走同一条 320 GB/s。H2D 64 GB/s 只在 prefill，decode 换入走内存池。"
        "Decode Attention = SWAP + max(HBM, compute) + AR；再加完整 MoE。"
        + " ".join(lines)
        + f" 2M 的 10 毫秒批 {extra[2_000_000]['b10']}，池上读 {extra[2_000_000]['d10']['t_pool']*1e3:.2f} ms。"
        f"4×10^6 的 10 毫秒批 {extra[4_000_000]['b10']}，30 毫秒批 {extra[4_000_000]['b30']}。"
        f"{s_label} 的 10 毫秒批 {extra[s_show]['b10']}，30 毫秒批 {extra[s_show]['b30']}。"
        f"单条 1M、98% 命中的 TTFT 是 {one_1m['t']:.4f} 秒。冷的 1M 单条是 {prefill_one(1048576)['t']:.3f} 秒。"
        "第 3 页 Prefill："
        + "，".join(f"{fmt_len(row['S'])} {row['bs']}" for row in pb)
        + f"。P:D 按 4K 进、512 出、98% 命中：Prefill {prefill_rps:.1f} 请求/秒，"
        f"10 毫秒 Decode {dec10_rps:.1f} 请求/秒（1:{pd10:.2f}），30 毫秒 Decode {dec30_rps:.1f} 请求/秒（1:{pd30:.2f}）。"
        "副本数按这个吞吐比配置，单副本时延不变。"
    )

    def lane_bytes(d, bs, s):
        read_gpu = d["n"] * n_csa_read(s) / TP
        return {
            "w": d["e_hot"] * W_ONE * 0.5 + SHARED,
            "ar": 2 * (TP - 1) / TP * (d["toks"] * H * 2) * L,
            "ep": d["t_ep"] * D2D,
            "hbm": read_gpu + ATTN / TP,
            "pool": read_gpu * d["spill"],
            "attn": ATTN / TP,
        }

    def qty(n):
        if n >= 1e9:
            return f"{n / 1e9:.2f} GB"
        if n >= 1e6:
            return f"{n / 1e6:.1f} MB"
        return f"{n / 1e3:.0f} KB"

    def both(n, t):
        return f"{qty(n)} · {ms2(t)}"

    def len_name(s):
        return s_label if s == s_show else fmt_len(s)

    def attn_name(d):
        cands = (
            ("注意力计算", d["t_ca"]),
            ("HBM 读", d["t_hbm"]),
        )
        name, t = max(cands, key=lambda item: item[1])
        return name, t

    def pack(s, src):
        return {
            "S": s,
            "store": store_seq(s),
            "b30": src["b30"],
            "d30": src["d30"],
            "d10": src["d10"],
        }

    # Slides 7–8 keep only lengths whose decode KV actually enters the DDR pool.
    swap_pts = [pack(row["S"], row) for row in sweep if row["d30"]["spill"] >= 0.005 or row["d10"]["spill"] >= 0.005]
    if extra[s_show]["d30"]["spill"] >= 0.005 or extra[s_show]["d10"]["spill"] >= 0.005:
        swap_pts.append(pack(s_show, extra[s_show]))
    if not swap_pts:
        raise SystemExit("slides 7–8 need at least one length with DDR KV swap")
    for pt in swap_pts:
        if pt["d30"]["spill"] < 0.005 and pt["d10"]["spill"] < 0.005:
            raise SystemExit(f"non-swap length leaked onto the swap pages: {pt['S']}")

    hold = swap_pts[0]
    bound = swap_pts[-1]
    g_hold = lane_bytes(hold["d30"], hold["b30"], hold["S"])
    g_bound = lane_bytes(bound["d30"], bound["b30"], bound["S"])

    def step_sum(d):
        side, _ = attn_name(d)
        expert = "读专家" if d["tw"] >= d["t_cm"] and d["tw"] >= d["t_ep"] else "专家计算"
        return f"换入 + {side} + AR + {expert} · {ms2(d['t'])}"

    s7 = prs.slides.add_slide(blank)
    chrome(
        s7, 7,
        f"{len_name(hold['S'])} 每卡换入 {qty(g_hold['pool'])}，{len_name(bound['S'])} 换入 {qty(g_bound['pool'])}",
        "Decode    ·    只统计进了 DDR 池的长度",
    )
    banner(
        s7, 0.92,
        "这两页只列 KV 换进 DDR 池的输入。一步 = SWAP + max(HBM, 计算) + AR + 完整 MoE。",
        size=14,
    )
    step_rows = [
        [
            "步骤",
            f"{len_name(hold['S'])} · 批 {hold['b30']} · 溢出 {hold['d30']['spill']*100:.1f}%",
            f"{len_name(bound['S'])} · 批 {bound['b30']} · 溢出 {bound['d30']['spill']*100:.1f}%",
        ],
        ["读专家权重", both(g_hold["w"], hold["d30"]["tw"]), both(g_bound["w"], bound["d30"]["tw"])],
        ["机内 allreduce", both(g_hold["ar"], hold["d30"]["t_ar"]), both(g_bound["ar"], bound["d30"]["t_ar"])],
        ["专家 GEMM", f"效率 {hold['d30']['ue']*100:.0f}% · {ms2(hold['d30']['t_cm'])}", f"效率 {bound['d30']['ue']*100:.0f}% · {ms2(bound['d30']['t_cm'])}"],
        ["EP 双向", both(g_hold["ep"], hold["d30"]["t_ep"]), both(g_bound["ep"], bound["d30"]["t_ep"])],
        ["注意力计算", ms2(hold["d30"]["t_ca"]), ms2(bound["d30"]["t_ca"])],
        ["注意力权重", both(g_hold["attn"], hold["d30"]["t_wa"]), both(g_bound["attn"], bound["d30"]["t_wa"])],
        ["HBM KV + 权重", both(g_hold["hbm"], hold["d30"]["t_hbm"]), both(g_bound["hbm"], bound["d30"]["t_hbm"])],
        ["DDR 池换入", both(g_hold["pool"], hold["d30"]["t_pool"]), both(g_bound["pool"], bound["d30"]["t_pool"])],
        ["相加", step_sum(hold["d30"]), step_sum(bound["d30"])],
    ]
    add_table(
        s7, 0.42, 1.48, [2.20, 5.05, 5.25], step_rows,
        [0.36, 0.34, 0.34, 0.34, 0.34, 0.32, 0.34, 0.34, 0.38, 0.40],
        ["head", "body", "body", "body", "body", "body", "body", "body", "key", "sum"],
        size=13,
    )
    note = s7.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.30), Inches(12.5), Inches(1.56))
    solid(note, GOLD_BG)
    textbox(
        s7, 0.58, 5.36, 12.18, 1.44,
        f"字节按每卡。{len_name(hold['S'])} 溢出 {hold['d30']['spill']*100:.1f}%，换入 {qty(g_hold['pool'])} / 320 GB/s = {hold['d30']['t_pool']*1e3:.2f} 毫秒，"
        f"然后从 HBM 再读全部 KV；Attention {hold['d30']['t_attn']*1e3:.2f} 毫秒，MoE {hold['d30']['t_moe']*1e3:.2f} 毫秒。128 卡换入合计 {qty(g_hold['pool'] * N)}。\n"
        f"{len_name(bound['S'])} 换入 {qty(g_bound['pool'])}、{bound['d30']['t_pool']*1e3:.2f} 毫秒；"
        f"Attention {bound['d30']['t_attn']*1e3:.2f} 毫秒，MoE {bound['d30']['t_moe']*1e3:.2f} 毫秒，批 {bound['b30']}。128 卡换入合计 {qty(g_bound['pool'] * N)}。\n"
        f"10 毫秒到 {s_label} 仍全在 HBM，没有进池的长度，不进这两页。后面的分析沿用这个口径。",
        13, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s7.notes_slide.notes_text_frame.text = (
        "第 7、8 页只统计 decode KV 溢出到 DDR 池的输入长度。全在 HBM 的长度留在第 6 页，不在这里记 0。"
        f"{len_name(hold['S'])} BS={hold['b30']} pool={g_hold['pool']/1e6:.1f} MB t={hold['d30']['t_pool']*1e3:.3f} ms "
        f"ar={hold['d30']['t_ar']*1e3:.3f} ca={hold['d30']['t_ca']*1e3:.3f} step={hold['d30']['t']*1e3:.3f}。"
        f"{len_name(bound['S'])} BS={bound['b30']} pool={g_bound['pool']/1e6:.1f} MB t={bound['d30']['t_pool']*1e3:.3f} ms "
        f"step={bound['d30']['t']*1e3:.3f}。"
        "10 毫秒曲线在本档没有溢出长度。"
    )

    def census_row(pt):
        d = pt["d30"]
        g = lane_bytes(d, pt["b30"], pt["S"])
        side, side_t = attn_name(d)
        return [
            len_name(pt["S"]),
            str(pt["b30"]),
            per_card(pt["b30"]),
            f"{d['spill']*100:.1f}%",
            qty(g["pool"]),
            qty(g["pool"] * N),
            ms2(d["t_pool"]),
            f"{side} {side_t*1e3:.2f} 毫秒",
        ]

    s8 = prs.slides.add_slide(blank)
    last = swap_pts[-1]
    chrome(
        s8, 8,
        f"进池的长度从 {len_name(hold['S'])} 起，批从 {hold['b30']} 降到 {last['b30']}",
        "Decode    ·    DDR 池换入的量和时间",
    )
    banner(
        s8, 0.92,
        "只统计 KV 换进 DDR 池的输入。换入量 = 溢出比例 × 这一步的稀疏读，每卡带宽 320 GB/s。",
        size=14,
    )
    census_head = ["输入", "30 毫秒批", "每卡", "溢出", "每卡换入", "128 卡合计", "换入耗时", "kernel 瓶颈"]
    add_table(
        s8, 0.42, 1.48,
        [1.35, 1.25, 0.90, 1.05, 1.50, 1.65, 1.45, 3.15],
        [census_head] + [census_row(pt) for pt in swap_pts],
        [0.38] + [0.42] * len(swap_pts),
        ["head"] + ["key" if pt is hold or attn_name(pt["d30"])[0] == "换入" else "body" for pt in swap_pts],
        size=12,
    )
    textbox(s8, 0.42, 3.70, 12.5, 0.22, "同一批长度上，换入和另外几笔的耗时", 13, True, ACCENT)
    time_head = ["输入", "换入", "allreduce", "注意力计算", "HBM KV+权重", "读专家", "一步"]
    time_body = []
    time_kinds = ["head"]
    for pt in swap_pts:
        d = pt["d30"]
        time_body.append([
            len_name(pt["S"]),
            ms2(d["t_pool"]),
            ms2(d["t_ar"]),
            ms2(d["t_ca"]),
            ms2(d["t_kv"]),
            ms2(d["tw"]),
            ms2(d["t"]),
        ])
        time_kinds.append("key" if attn_name(d)[0] == "换入" else "body")
    add_table(
        s8, 0.42, 4.06,
        [1.45, 1.70, 1.80, 1.90, 1.80, 1.70, 1.95],
        [time_head] + time_body,
        [0.36] + [0.36] * len(swap_pts),
        time_kinds,
        size=12,
    )
    note = s8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.04), Inches(12.5), Inches(1.00))
    solid(note, GOLD_BG)
    textbox(
        s8, 0.58, 6.08, 12.18, 0.92,
        "稀疏读不是整段存量：30 层压缩 indexer、31 层 HCA、最多 1024 条完整 latent，再加 4.50 MB。带宽 320 GB/s。\n"
        f"10 毫秒到 {s_label} 仍全在 HBM，128K 也全在 HBM。这两页只保留溢出大于 0 的长度，后面的分析沿用这个口径。",
        13, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s8.notes_slide.notes_text_frame.text = (
        "池上字节 = spill × bs × n_csa_read(S) / 128。带宽 320 GB/s。"
        "n_csa_read = 30×(S/4)×64 + 31×(S/128)×576 + 30×min(1024,S/4)×576 + 61×128×576。"
        + " ".join(
            f"{len_name(pt['S'])} bs={pt['b30']} spill={pt['d30']['spill']*100:.2f}% "
            f"pool={lane_bytes(pt['d30'], pt['b30'], pt['S'])['pool']/1e6:.1f}MB "
            f"t={pt['d30']['t_pool']*1e3:.3f}ms step={pt['d30']['t']*1e3:.3f}ms"
            for pt in swap_pts
        )
        + " 口径已固化：第 7、8 页不收录换入为 0 的输入长度。"
    )

    # ----- slide 9: fixed assumptions -----
    s9 = prs.slides.add_slide(blank)
    chrome(s9, 9, "计算口径：只在融合 kernel 与显式流水里计算重叠", "公式    ·    共同假设")
    banner(
        s9,
        0.92,
        "Attention 与 MoE 前后相加。权重/数据读取与本地计算可在融合 kernel 内重叠；通信是否重叠按阶段单独说明。",
        size=13,
    )
    assumptions = [
        ["项目", "TTFT", "TPOT"],
        ["并行域", "Attention TP=8、DP=16；MoE EP=128", "同左；最忙 TP 组 n=⌈BS/16⌉"],
        ["Attention", "拉 prefix、融合 kernel、AR 跨 query chunk 流水，取瓶颈", "SWAP 在前；融合 kernel 后再加 AR"],
        ["MoE", "dispatch + max(权重, GEMM) + combine", "同左；两个 EP 方向分别统计"],
        ["KV 位置", "98% prefix 在远端 KV 缓存，经参数面拉取；Decode 没有副本", "HBM 放不下先从 DDR 池写回 HBM"],
        ["P→D", "完整 KV 按层发送；只加未被后续计算隐藏的尾巴", "不进入单步 TPOT"],
        ["负载", "Attention 按 TP=8；MoE 取最忙 EP 卡，逐专家 16 行 padding", "同左"],
        ["固定开销", "不伪造数值；单列为未计入项", "不伪造数值；SLO 结果是数据面理论上限"],
    ]
    add_table(
        s9, 0.42, 1.50, [1.65, 5.42, 5.43], assumptions,
        [0.36, 0.56, 0.58, 0.58, 0.58, 0.58, 0.58, 0.58],
        ["head", "body", "body", "key", "body", "body", "body", "note"],
        size=12,
    )
    note = s9.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.24), Inches(12.5), Inches(0.78))
    solid(note, GOLD_BG)
    textbox(
        s9, 0.58, 6.28, 12.18, 0.70,
        "固定开销 = 调度 + kernel 启动 + collective 启动 + RMSNorm / RoPE / Router / 激活 / residual + logits / sampling + P/D 控制。"
        "当前没有实测值，不并入 BS 摸高；生产 SLO 必须从 10/30 毫秒预算里另留余量。",
        12, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s9.notes_slide.notes_text_frame.text = (
        "这一页是后续固化口径。TTFT 的 chunk 流水忽略显式 fill/drain 气泡，气泡和软件固定开销都放在未计入项。"
        "Prefill attention 假设融合 kernel 有理想 tile 复用，每个 KV 字节从 HBM 读一次；没有实测 IO 放大系数。"
        "Decode 不假设输出投影与 collective 融合，AR 单独加。"
    )

    # ----- slide 10: TTFT formula -----
    s10 = prs.slides.add_slide(blank)
    chrome(s10, 10, "TTFT = Attention + MoE + P→D 尾时延 + 固定开销", "公式    ·    TTFT")
    banner(
        s10,
        0.92,
        "本页所有时间已经包含完整 61 层。98% prefix 经参数面拉取，Decode 没有副本。",
        size=14,
    )
    ttft_rows = [
        ["部分", "公式", "注释"],
        ["Attention", "max(拉 prefix，HBM，Attention 计算，AR)", "四条通路跨 query chunk 流水"],
        ["拉 prefix", "⌈BS/16⌉ × K(0.98S) / (8 × 40 GB/s)", "K(x)=4939.5x+滑窗；远端 KV → HBM"],
        ["计算上下文", "C = 0.02S × 0.98S + 0.02S × (0.02S + 1) / 2", "新 token 平均看到约 99% 的完整上下文"],
        ["融合 kernel", "max(Attention HBM，Attention FLOP / 340.2 T)", "HBM 含权重、prefix KV、新 KV 和激活"],
        ["MoE", "dispatch + max(专家权重，专家 GEMM) + combine", "最忙 EP 卡；逐专家 16 行 padding"],
        ["P→D 总量", "⌈BS/16⌉ × K(S) / (8 × 40 GB/s)", "K(S)=4939.5S+4.50 MB；发送完整 KV"],
        ["P→D 尾巴", "max(0，P→D 总量 − 可重叠计算时间)", "layer-wise 发送；只加最后没隐藏的部分"],
        ["最终", "TTFT = Attention + MoE + P→D 尾巴 + fixed", "本档计算中 P→D 尾巴为 0"],
    ]
    add_table(
        s10, 0.42, 1.48, [1.70, 6.15, 4.65], ttft_rows,
        [0.34, 0.48, 0.52, 0.52, 0.48, 0.48, 0.48, 0.48, 0.48],
        ["head", "key", "body", "body", "body", "key", "body", "body", "sum"],
        size=12,
    )
    cold = prefill_one(s_show)
    note = s10.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.98), Inches(12.5), Inches(1.04))
    solid(note, GOLD_BG)
    textbox(
        s10, 0.58, 6.03, 12.18, 0.94,
        f"冷请求最大输入 {fmt_count(s_show)}：Attention {cold['t_attention']:.2f} 秒，其中 AR {cold['t_ar']:.2f} 秒、计算 {cold['t_attn']:.2f} 秒；"
        f"MoE {cold['t_moe']:.2f} 秒；P→D 总量 {cold['t_pd']*1e3:.1f} 毫秒，全部被后续计算隐藏；数据面合计 {cold['t']:.2f} 秒。"
        "固定开销未计入。",
        13, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s10.notes_slide.notes_text_frame.text = (
        f"冷请求 S={s_show}，Attention={cold['t_attention']:.6f}s，AR={cold['t_ar']:.6f}s，"
        f"compute={cold['t_attn']:.6f}s，HBM={cold['t_hbm']:.6f}s，MoE={cold['t_moe']:.6f}s，"
        f"P-D={cold['t_pd']:.6f}s，tail={cold['t_tail']:.6f}s，total={cold['t']:.6f}s。"
    )

    # ----- slide 11: TPOT formula -----
    s11 = prs.slides.add_slide(blank)
    chrome(s11, 11, "TPOT = Decode Attention + Decode MoE + 固定开销", "公式    ·    TPOT")
    banner(
        s11,
        0.92,
        "Decode 不用 H2D。DDR 池里的 KV 必须先写回 HBM；标准执行不假设 GEMM 与 AR 融合。",
        size=13,
    )
    tpot_rows = [
        ["部分", "公式", "注释"],
        ["最忙 TP 组", "n = ⌈BS / 16⌉；每卡 KV 读量 = n × RKV(S) / 8", "不再按 BS/128 的平均值"],
        ["溢出比例", "f = max(0，(BS × KV 存量 − 5.72 TB) / (BS × KV 存量))", "池容量不设上限"],
        ["SWAP", "f × 每卡 KV 读量 / 320 GB/s", "DDR 池 → D2D → HBM；必须先完成"],
        ["Attention kernel", "max((全部 KV + 2.42 GB 权重) / 3.20 TB/s，FLOP / 340.2 T)", "换入 KV 仍从 HBM 再读；kernel 内访存/计算重叠"],
        ["AR", "61 × 2×7/8 × n×7168×2 / 280 GB/s", "8卡fullmesh七链路并发；单独加在kernel后"],
        ["Decode Attention", "SWAP + Attention kernel + AR", "三段存在业务依赖"],
        ["Decode MoE", "dispatch + max(专家权重，专家 GEMM) + combine", "EP 两个方向分别统计；最忙卡、逐专家 padding"],
        ["最终", "TPOT = Decode Attention + Decode MoE + fixed", "固定开销未计入，结果是数据面理论上限"],
    ]
    add_table(
        s11, 0.42, 1.48, [1.72, 6.42, 4.36], tpot_rows,
        [0.34, 0.48, 0.50, 0.48, 0.56, 0.48, 0.46, 0.54, 0.48],
        ["head", "body", "body", "key", "body", "body", "sum", "key", "sum"],
        size=12,
    )
    note = s11.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.02), Inches(12.5), Inches(1.00))
    solid(note, GOLD_BG)
    textbox(
        s11, 0.58, 6.07, 12.18, 0.90,
        f"4K：10 毫秒批 {bs10}，Attention {d10['t_attn']*1e3:.2f} 毫秒 + MoE {d10['t_moe']*1e3:.2f} 毫秒 = {d10['t']*1e3:.2f} 毫秒；"
        f"30 毫秒批 {bs30}，Attention {d30['t_attn']*1e3:.2f} 毫秒 + MoE {d30['t_moe']*1e3:.2f} 毫秒 = {d30['t']*1e3:.2f} 毫秒。"
        "两档都没有给 fixed 留余量。",
        13, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s11.notes_slide.notes_text_frame.text = (
        f"4K 10ms BS={bs10} data-plane={d10['t']*1e3:.6f}ms；"
        f"4K 30ms BS={bs30} data-plane={d30['t']*1e3:.6f}ms。"
        "生产摸高需要先给 measured fixed overhead 预留预算，再重新搜索 BS。"
    )

    def hbm_pie_values(bs, s):
        """Busiest active GPU, not the 128-GPU average."""
        n = math.ceil(bs / DP)
        raw_kv = n * store_seq(s) / TP / 1e9
        room_gpu = ROOM / N / 1e9
        kv_hbm = min(raw_kv, room_gpu)
        pool_kv = max(raw_kv - room_gpu, 0.0)
        weights = (ROUTED / N + SHARED + ATTN / TP) / 1e9
        free = HBM_CAP / 1e9 - weights - RESERVE / 1e9 - kv_hbm
        return kv_hbm, max(free, 0.0), pool_kv

    # ----- slide 12: Prefill HBM pies -----
    s12 = prs.slides.add_slide(blank)
    chrome(s12, 12, "Prefill：输入变长后，时间摸高批下降，单卡 KV 占用仍小", "HBM 容量    ·    TTFT ≤ 10 秒    ·    98% prefix 命中")
    banner(
        s12,
        0.92,
        "每个饼是最忙活跃卡的 96 GB HBM。模型权重固定 45.31 GB，系统预留 6 GB；prefix 经参数面拉入 HBM。",
        size=13,
    )
    pf_pies = [
        (4096, p4["bs"], "4K"),
        (262144, next(row["bs"] for row in pb if row["S"] == 262144), "256K"),
        (1048576, p1m["bs"], "1M"),
    ]
    for x, (s, bs, label) in zip((0.42, 4.72, 9.02), pf_pies):
        kv_hbm, free, pool_kv = hbm_pie_values(bs, s)
        add_hbm_pie(s12, x, label, bs, kv_hbm, free, pool_kv)
    note = s12.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.16), Inches(12.5), Inches(0.86))
    solid(note, GOLD_BG)
    textbox(
        s12, 0.58, 6.20, 12.18, 0.78,
        "Prefill 的长输入先被 TTFT 限制：4K / 256K / 1M 的最大批分别是 "
        f"{pf_pies[0][1]} / {pf_pies[1][1]} / {pf_pies[2][1]}，最忙卡 HBM KV 只有 "
        f"{hbm_pie_values(pf_pies[0][1], pf_pies[0][0])[0]:.2f} / "
        f"{hbm_pie_values(pf_pies[1][1], pf_pies[1][0])[0]:.2f} / "
        f"{hbm_pie_values(pf_pies[2][1], pf_pies[2][0])[0]:.2f} GB，均不需要 DDR 池。",
        12, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s12.notes_slide.notes_text_frame.text = (
        "饼图按最忙活跃 GPU，不按 128 卡平均。每卡固定：路由专家 38.864 GB，共享专家 4.030 GB，"
        "Attention 2.419 GB，系统预留 6 GB。KV = ceil(BS/16) × store_seq(S) / 8。"
        + " ".join(
            f"{label}: BS={bs}, kv={hbm_pie_values(bs, s)[0]:.3f}GB, free={hbm_pie_values(bs, s)[1]:.3f}GB."
            for s, bs, label in pf_pies
        )
    )

    # ----- slide 13: Decode HBM pies -----
    s13 = prs.slides.add_slide(blank)
    chrome(s13, 13, "Decode：30 毫秒摸高时，256K 起把 HBM KV 房间占满", "HBM 容量    ·    TPOT ≤ 30 毫秒")
    banner(
        s13,
        0.92,
        "饼图只画单卡 96 GB HBM；放不下的 KV 在饼图外标出 DDR 池占用。仍按最忙活跃卡。",
        size=13,
    )
    d_pies = [
        (4096, by_len[4096]["b30"], "4K"),
        (262144, by_len[262144]["b30"], "256K"),
        (1048576, by_len[1048576]["b30"], "1M"),
    ]
    for x, (s, bs, label) in zip((0.42, 4.72, 9.02), d_pies):
        kv_hbm, free, pool_kv = hbm_pie_values(bs, s)
        add_hbm_pie(s13, x, label, bs, kv_hbm, free, pool_kv)
    d10_4 = hbm_pie_values(by_len[4096]["b10"], 4096)
    d10_512 = hbm_pie_values(by_len[524288]["b10"], 524288)
    d10_1m = hbm_pie_values(by_len[1048576]["b10"], 1048576)
    note = s13.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.16), Inches(12.5), Inches(0.86))
    solid(note, GOLD_BG)
    textbox(
        s13, 0.58, 6.20, 12.18, 0.78,
        f"30 毫秒：256K / 1M 的最忙卡各有 {hbm_pie_values(d_pies[1][1], d_pies[1][0])[2]:.2f} / "
        f"{hbm_pie_values(d_pies[2][1], d_pies[2][0])[2]:.2f} GB KV 在 DDR 池。"
        f"10 毫秒批更小，4K / 512K / 1M 的 HBM KV 仅 {d10_4[0]:.2f} / {d10_512[0]:.2f} / {d10_1m[0]:.2f} GB，均不进池。",
        12, False, GOLD, anchor=MSO_ANCHOR.MIDDLE,
    )
    s13.notes_slide.notes_text_frame.text = (
        "Decode 饼图使用 30ms 最大批，按最忙活跃 GPU。HBM KV 上限 44.687 GB。"
        + " ".join(
            f"{label}: BS={bs}, hbm_kv={hbm_pie_values(bs, s)[0]:.3f}GB, "
            f"pool={hbm_pie_values(bs, s)[2]:.3f}GB, free={hbm_pie_values(bs, s)[1]:.3f}GB."
            for s, bs, label in d_pies
        )
    )

    out = "/workspace/docs/deepseek-96g-slo.pptx"
    prs.save(out)
    print(out)
    print("ROOM_TB", round(ROOM / 1e12, 3))
    print("S", s_show, "tc", round(p["tc"], 4), "tw", round(p["tw"] * 1e3, 3), "ship", round(p["ship"] * 1e3, 3))
    print("idx", round(p["idx"], 4), "hca", round(p["hca"], 4), "core", round(p["core"], 4), "proj", round(p["proj"], 4), "moe", round(p["moe"], 4))
    print(
        "d10", bs10, round(d10["t"] * 1e3, 3),
        "ar", round(d10["t_ar"] * 1e3, 3),
        "tw", round(d10["tw"] * 1e3, 3),
        "cm", round(d10["t_cm"] * 1e3, 3),
        "ep", round(d10["t_ep"] * 1e3, 3),
        "tok", round(d10["tok"], 2),
        "ue", round(d10["ue"], 3),
        "ehot", round(d10["e_hot"], 3),
        "next", round(decode(bs10 + 1, 4096)["t"] * 1e3, 3),
    )
    print(
        "d30", bs30, round(d30["t"] * 1e3, 3),
        "ar", round(d30["t_ar"] * 1e3, 3),
        "cm", round(d30["t_cm"] * 1e3, 3),
        "ep", round(d30["t_ep"] * 1e3, 3),
        "ca", round(d30["t_ca"] * 1e3, 3),
        "tok", round(d30["tok"], 2),
        "ue", round(d30["ue"], 3),
        "next", round(decode(bs30 + 1, 4096)["t"] * 1e3, 3),
    )
    print("span", span10, span30)
    print("pf", p4["bs"], round(p4["t"], 3), p1m["bs"], round(p1m["t"], 3))
    print("PD", round(pd10, 2), round(pd30, 2), "rps", round(prefill_rps, 1), round(dec10_rps, 1), round(dec30_rps, 1))
    print("4k_ttft_ms", round(prefill_one(4096)["t"] * 1e3, 2), "1m_cold", round(prefill_one(1048576)["t"], 3))
    for row in sweep:
        print(
            fmt_len(row["S"]),
            "b10", row["b10"], where(row["d10"]["spill"]),
            "b30", row["b30"], where(row["d30"]["spill"]),
            "pool30", round(row["d30"]["t_pool"] * 1e3, 2),
            "store", fmt_bytes(row["store"]),
            "cap", row["cap"],
        )
    for s, row in extra.items():
        print(
            "extra", s, "b10", row["b10"], where(row["d10"]["spill"]), round(row["d10"]["t_pool"] * 1e3, 2),
            "b30", row["b30"], where(row["d30"]["spill"]), round(row["d30"]["t_pool"] * 1e3, 2),
        )
    if not (p["t"] <= 10.0 + 1e-6 and d10["t"] <= 0.010 + 1e-9 and d30["t"] <= 0.030 + 1e-9):
        raise SystemExit("SLO miss")
    if bs10 < 1 or bs30 < 1 or p4["bs"] < 1:
        raise SystemExit("empty batch")


if __name__ == "__main__":
    main()
