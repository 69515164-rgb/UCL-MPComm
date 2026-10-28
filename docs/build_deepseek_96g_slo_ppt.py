#!/usr/bin/env python3
"""10T DeepSeek on a 96 GB, 486 T cluster, in the SLO deck layout.

Memory and communication bandwidths are at 80%. Compute is at 70%.
Attention and experts share one peak: 486 T x 70% = 340.2 T.

H2D is 64 GB/s per GPU: 51.2 GB/s effective, prefill only.
DDR5 is 1288.8 GB/s and 768 GB per 8-GPU machine.

D2D is 3.2 Tb/s per GPU: 400 GB/s peak, 320 GB/s effective.
P2P and the parameter plane are 400 Gb/s: 40 GB/s effective.
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
P2P = 400e9 / 8 * 0.80
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


def chrome(slide, page, title, kicker, total=8):
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


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def prefill_one(s):
    idx = N_CSA * 2048 * s * s
    hca = N_HCA * 1024 * s * s
    core = N_CSA * 262144 * (1024 + 128) * s
    t_idx = idx / (N * PEAK_FP8)
    t_hca = hca / (N * PEAK_FP8)
    t_core = core / (N * PEAK_FP8)
    t_proj = PROJ * s / (N * PEAK_FP8)
    t_moe = MOE * s / (N * PEAK_FP4)
    t_c = t_idx + t_hca + t_core + t_proj + t_moe
    t_w = (ROUTED / N + SHARED + ATTN / TP) / HBM_BW
    t_ship = s * BPT / (N * PARAM)
    return {
        "t": max(t_c, t_w) + t_ship,
        "idx": t_idx,
        "hca": t_hca,
        "core": t_core,
        "proj": t_proj,
        "moe": t_moe,
        "tc": t_c,
        "tw": t_w,
        "ship": t_ship,
    }


def max_input(limit=10.0):
    lo, hi = 1.0, 2e8
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
    frac = 1 - math.exp(-TOPK * bs / E)
    e = E / N
    std = math.sqrt(max(e * frac * (1 - frac), 0.0))
    e_hot = min(e, e * frac + 2 * std)
    tok = (bs * TOPK / E) / frac if frac > 1e-9 else 1.0
    ue, ua = align(tok), align(bs / DP)
    sel = min(1024.0, s / 4.0)
    score = N_CSA * 4096 * s + N_HCA * 2048 * s + N_CSA * 262144 * (sel + 128)
    t_w = (e_hot * W_ONE * 0.5 + SHARED) / HBM_BW
    store = bs * store_seq(s)
    read_gpu = bs * n_csa_read(s) / N
    spill = max(store - ROOM, 0.0) / store if store else 0.0
    t_kh = read_gpu * (1.0 - spill) / HBM_BW if store else 0.0
    t_pool = read_gpu * spill / POOL
    t_wa = (ATTN / TP) / HBM_BW
    t_ca = bs * (score + PROJ) / (N * PEAK_FP8 * ua)
    t_cm = bs * MOE / (N * PEAK_FP4 * ue)
    pairs = (e_hot / e) * (bs * TOPK / N)
    t_ep = pairs * 2 * H * L / D2D
    toks = math.ceil(bs / DP)
    t_ar = 2 * (TP - 1) / TP * (toks * H * 2) * L / P2P
    t_attn = max(t_ca, t_kh + t_wa, t_pool, t_ar)
    t_moe = max(t_cm, t_w, t_ep)
    return {
        "t": t_attn + t_moe,
        "t_attn": t_attn,
        "t_moe": t_moe,
        "t_ca": t_ca,
        "tw": t_w,
        "t_cm": t_cm,
        "t_ep": t_ep,
        "t_ar": t_ar,
        "t_kv": t_kh,
        "t_pool": t_pool,
        "t_wa": t_wa,
        "frac": frac,
        "e_hot": e_hot,
        "tok": tok,
        "ue": ue,
        "ua": ua,
        "toks": toks,
        "spill": spill,
        "store": store,
    }


def hbm_cap(s):
    return int(ROOM // store_seq(s))


def search_bs(s, limit):
    if decode(1, s)["t"] > limit:
        return 0
    ceiling = 500_000
    lo, hi, best = 1, 1, 0
    while hi < ceiling and decode(hi, s)["t"] <= limit:
        best = hi
        nxt = min(ceiling, hi * 2)
        if nxt == hi:
            break
        hi = nxt
    while lo <= hi:
        mid = (lo + hi) // 2
        if decode(mid, s)["t"] <= limit:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def prefill_batch(bs, s, hit=0.9):
    q = (1 - hit) * s
    tokens = bs * q
    idx = bs * N_CSA * 2048 * q * s
    hca = bs * N_HCA * 1024 * q * s
    core = bs * N_CSA * 262144 * (1024 + 128) * q
    ua = align(max(tokens / DP, 1e-9))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    e = E / N
    std = math.sqrt(max(e * frac * (1 - frac), 0.0))
    e_hot = min(e, e * frac + 2 * std) if frac > 0 else 0.0
    tok = (tokens * TOPK / E) / frac if frac > 1e-12 else 1.0
    ue = align(tok)
    t_idx = idx / (ua * N * PEAK_FP8)
    t_attn = (idx + hca + core + PROJ * tokens) / (ua * N * PEAK_FP8)
    t_moe = MOE * tokens / (ue * N * PEAK_FP4)
    t_we = ((e_hot * W_ONE * 0.5 + SHARED) if e_hot > 0 else SHARED) / HBM_BW
    t_kv = bs * hit * s * BPT / (N * PARAM)
    t_ar = 2 * (TP - 1) / TP * ((tokens / DP) * H * 2) * L / P2P
    t_ep = ((e_hot / e) * (tokens * TOPK / N) if e else 0.0) * 2 * H * L / D2D
    t_wa = (ATTN / TP) / HBM_BW
    t = t_kv + max(t_attn, t_ar, t_wa) + max(t_moe, t_we, t_ep)
    return {
        "t": t,
        "Q": tokens,
        "t_ar": t_ar,
        "t_attn": t_attn,
        "t_idx": t_idx,
        "t_moe": t_moe,
        "tkv": t_kv,
        "t_ep": t_ep,
        "t_we": t_we,
        "cap": hbm_cap(s),
    }


def max_prefill_bs(s, hit=0.9, limit=10.0):
    cap = hbm_cap(s)
    if cap < 1:
        return 0
    lo, hi, best = 1, 1, 0
    while hi < cap and prefill_batch(hi, s, hit)["t"] <= limit:
        hi = min(cap, hi * 2)
        if hi == cap:
            break
    while lo <= hi:
        mid = (lo + hi) // 2
        if prefill_batch(mid, s, hit)["t"] <= limit:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


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
        "P2P 与参数面 400 Gb/s 取 80% 为 40 GB/s。超节点 128 卡，机内 8 卡 fullmesh。",
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
        "DDR5 的 1.6 TB/s 和 1.3 TB 按一台 8 卡机器记。有效 1.28 TB/s，每卡分到 160 GB/s 和 162.5 GB，与 H2D 同速。超节点 16 台机器，本机 DDR 共 20.8 TB。"
        "D2D 写的是 3.2 Tb/s（小写 b，比特）：3.2×10^12 / 8 = 400 GB/s 峰值，80% 后 320 GB/s。机内 8 卡 fullmesh，P2P 400 Gb/s = 50 GB/s 峰值，80% 后 40 GB/s。参数面同样 400 Gb/s，80% 后 40 GB/s。"
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
        f"一条请求放在一个 128 卡副本上。计算 {sec(p['tc'])}，读权重 {ms(p['tw'])}，送 KV {ms(p['ship'])}。S² 占 {sec(p['idx'] + p['hca'])}，线性项占 {sec(p['core'] + p['proj'] + p['moe'])}。",
        size=13,
    )
    textbox(s2, 0.42, 1.46, 6.2, 0.24, "并行策略", 13, True, ACCENT)
    par_rows = [
        ["", "Attention", "MoE"],
        ["并行", "机内 TP=8\n16 台机器做 DP=16", "超节点 EP=128\n一份模型铺满 128 卡"],
        ["通信域", "8 卡 fullmesh\n有效 40 GB/s", "128 卡 D2D，有效 320 GB/s\nKV 走参数面，有效 40 GB/s"],
        [
            "每卡权重",
            f"注意力 19.35 GB / 8\n= {ATTN / TP / 1e9:.2f} GB FP8",
            f"路由专家 {E / N:.1f} 个，{ROUTED / N / 1e9:.1f} GB FP4\n共享专家 {SHARED / 1e9:.2f} GB，每卡一份",
        ],
        ["本阶段角色", "S² 来自 indexer 和 HCA\n决定输入能写多长", f"专家 GEMM 随 token 线性\n到这个长度约占 {sec(p['moe'])}"],
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
        ["CSA indexer", "30 层 × 2048 × S²，除以 128 × 340.2×10^12", sec(p["idx"])],
        ["HCA", "31 层 × 1024 × S²，除以同一个 340.2 T", sec(p["hca"])],
        ["专家 GEMM", "每 token 5.64×10^10 FLOP × S，除以 128 × 340.2×10^12", sec(p["moe"])],
        ["投影", "每 token 3.87×10^10 FLOP × S，除以 340.2 T", sec(p["proj"])],
        ["稀疏注意力", "每 token 看 1024 条压缩 KV + 128 滑窗", sec(p["core"])],
        [
            "读权重 + 送 KV",
            f"每卡 {weight_gb:.2f} GB / 3.20 TB/s；KV {kv_gb:.2f} GB / (128×40 GB/s)",
            f"{ms2(p['tw'])} + {ms2(p['ship'])}",
        ],
        ["合计", "计算和读权重取长的一项，再加送 KV。机内 allreduce 记在下一页", "10.0 秒"],
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
        "注意力在机内 8 卡做 TP，16 台机器是 16 路 DP。MoE 把 2469 个专家铺到 128 卡，每卡 19.3 个，路由权重 FP4，共享专家 FP8，注意力 FP8。"
        "时间 = max(计算, 读权重) + 把 KV 送到 Decode。注意力和专家的 FLOP 都除以 128×340.2×10^12，也就是 486 T 的 70%。"
        "这一页的冷启动单请求不把机内 allreduce 算进 10 秒，allreduce 记在下一页的批上。与原先 DeepSeek 六页的拆分相同。"
        f"在 S={s_show:.0f}：indexer {p['idx']:.4f}s，HCA {p['hca']:.4f}s，专家 {p['moe']:.4f}s，投影 {p['proj']:.4f}s，稀疏注意力 {p['core']:.4f}s，合计计算 {p['tc']:.4f}s。"
        f"读权重 {p['tw']*1e3:.2f} ms，KV 搬运 {p['ship']*1e3:.2f} ms。S² 合计 {p['idx']+p['hca']:.2f}s，线性项 {p['core']+p['proj']+p['moe']:.2f}s。"
        f"4K 单条 TTFT 是 {prefill_one(4096)['t']*1e3:.2f} 毫秒，停在读权重。1M 单条、无命中是 {prefill_one(1048576)['t']:.3f} 秒。"
        f"该长度的 KV 约 {kv_gb:.2f} GB，经 128×40 GB/s 的参数面送出。HBM 余量 {ROOM/1e12:.2f} TB，这一条放得下，H2D 不进这条 10 秒。"
        "H2D 64 GB/s 取 80% 为 51.2 GB/s，只在 prefill 需要主机内存时使用。权重已经在 HBM 里。"
    )

    # ----- slide 3 -----
    s3 = prs.slides.add_slide(blank)
    chrome(s3, 3, f"4K 的 prefill 全局批是 {p4['bs']}，1M 是 {p1m['bs']}", "Prefill    ·    TTFT ≤ 10 秒    ·    KV 命中 90%")
    banner(
        s3,
        0.92,
        "多条同时进同一份 128 卡副本。命中 90% 的 KV 走参数面，只现算 10%。4K 的注意力侧取 allreduce，1M 取注意力计算，再加专家 GEMM。",
        size=14,
    )
    textbox(s3, 0.42, 1.44, 12.5, 0.22, "10 秒在两个端点上怎么加完", 13, True, ACCENT)
    walk = [
        ["笔", "算法", f"4K，全局批 {p4['bs']}", f"1M，全局批 {p1m['bs']}"],
        ["现算 token", "批 × 输入 × 0.1", fmt_tok(p4["Q"]), fmt_tok(p1m["Q"])],
        [
            "机内 allreduce",
            "每组现算 token × 7168 × 2 字节\n61 层 × 2×7/8 / 40 GB/s",
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
            "专家计算",
            "现算 token × 5.64×10^10 FLOP\n除以 128 × 340.2×10^12",
            sec(p4["t_moe"]),
            sec(p1m["t_moe"]),
        ],
        ["相加", "4K 取 allreduce，1M 取注意力计算，专家侧取 GEMM", sec(p4["t"]), sec(p1m["t"])],
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
    sweep_head = ["输入", "10 秒全局批", "每卡", "现算 token", "allreduce", "专家计算", "注意力计算", "读 KV"]
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
        f"这些批的 KV 都放得进 HBM：4K 能放 {fmt_count(p4['cap'])} 条，1M 能放 {p1m['cap']} 条。参数面读命中 KV 约 {ms(p4['tkv'])}。",
        13,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    s3.notes_slide.notes_text_frame.text = (
        "这一页的批是 128 卡副本上的全局批，每卡条数 = 全局批 / 128。切分与上一页相同：注意力 TP=8、DP=16，MoE EP=128。"
        "KV 命中 90%。命中部分按参数面 40 GB/s 读。每条只把 10% 的 token 送进计算，这 10% 的 query 仍看全长上下文。"
        "时间 = 参数面读 KV + 注意力侧较长的一项 + 专家侧较长的一项。"
        "注意力侧在注意力计算、机内 allreduce、注意力权重之间取最大。专家侧在专家 GEMM、读专家权重、EP 之间取最大。这一页专家侧较长的是 GEMM。"
        "机内 allreduce：每组 token 数 = 现算 token / 16，每 token 7168×2 字节，环上 2×7/8，61 层，除以 40 GB/s。"
        "4K 的注意力侧是 allreduce。1M 的注意力计算已经长过 allreduce，注意力侧改取计算。"
        f"4K 全局批 {p4['bs']}：现算 {p4['Q']:.4e} token，allreduce {p4['t_ar']:.3f}s，注意力计算 {p4['t_attn']:.3f}s，专家计算 {p4['t_moe']:.3f}s，"
        f"EP {p4['t_ep']:.3f}s，读权重 {p4['t_we']*1e3:.2f} ms，读 KV {p4['tkv']*1e3:.1f} ms，合计 {p4['t']:.3f}s。"
        f"再加一条是 {prefill_batch(p4['bs']+1, 4096)['t']:.3f}s。"
        f"1M 全局批 {p1m['bs']}：现算 {p1m['Q']:.4e}，allreduce {p1m['t_ar']:.3f}s，注意力计算 {p1m['t_attn']:.3f}s（indexer {p1m['t_idx']:.3f}s），"
        f"专家计算 {p1m['t_moe']:.3f}s，EP {p1m['t_ep']:.3f}s，读 KV {p1m['tkv']*1e3:.1f} ms，合计 {p1m['t']:.3f}s。"
        f"HBM 余量 {ROOM/1e12:.2f} TB。4K 能放 {p4['cap']} 条，1M 能放 {p1m['cap']} 条，都高于这页的时间批，所以 H2D 不进这页的 10 秒。"
        f"单条、1,048,576 token、90% 命中的 TTFT 是 {one_1m['t']:.4f} 秒，其中参数面读 KV {one_1m['tkv']*1e3:.2f} 毫秒，allreduce {one_1m['t_ar']:.4f} 秒。"
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
        ["通信", f"每层机内 allreduce\n这一步 {ms2(d10['t_ar'])}", f"最忙卡 BF16 combine\n这一步 {ms2(d10['t_ep'])}"],
        ["访存", f"注意力权重 {ATTN/TP/1e9:.2f} GB\n这一步 {ms2(d10['t_wa'])}", f"醒了 {d10['e_hot']:.1f} / 19.3 个\n这一步 {ms2(d10['tw'])}"],
        ["计算", "行数 = ⌈BS / 16⌉\n按 16 行砖对齐", f"每个命中专家约 {d10['tok']:.1f} 个 token\n16 行砖，效率 {d10['ue']*100:.0f}%"],
    ]
    add_table(s4, 0.42, 1.78, [1.15, 2.55, 2.70], par4, [0.28, 0.58, 0.58, 0.62, 0.58], ["head", "body", "body", "key", "body"], size=12)
    step4 = [
        ["笔", "白话", "时间"],
        [f"命中", f"1 − exp(−6×{bs10} / 2469) = {d10['frac']*100:.0f}%\n最忙卡按均值 + 2σ，顶到 {d10['e_hot']:.1f} 个", "—"],
        ["读专家", f"{hot_gb:.2f} GB（路由 + 共享）\n除以 3.20 TB/s", ms2(d10["tw"])],
        ["机内通信", f"每组 {d10['toks']} 条 × 7168 × 2 字节\n61 层 × 2×7/8 / 40 GB/s", ms2(d10["t_ar"])],
        ["专家计算", f"每个命中专家约 {d10['tok']:.1f} 个 token\n16 行砖，效率 {d10['ue']*100:.0f}%", ms2(d10["t_cm"])],
        ["专家通信", "最忙卡送出的 BF16 combine / 320 GB/s", ms2(d10["t_ep"])],
        ["相加", f"注意力侧 {d10['t_ar']*1e3:.2f}，专家侧 {d10['tw']*1e3:.2f}", ms2(d10["t"])],
    ]
    add_table(
        s4,
        7.05,
        1.78,
        [1.20, 3.50, 1.15],
        step4,
        [0.28, 0.54, 0.50, 0.50, 0.48, 0.40, 0.38],
        ["head", "body", "key", "key", "body", "body", "sum"],
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
        "一步 = 注意力侧最长的一笔 + 专家侧最长的一笔。两段相加。"
        f"命中率 = 1 − exp(−6×{bs10} / 2469) = {d10['frac']:.4f}。最忙卡 = min(19.289, 均值 + 2σ) = {d10['e_hot']:.3f}，已经顶到每卡全部本地专家。"
        f"读权重 ({d10['e_hot']:.3f}×{EXPERT_GB:.3f} GB + {SHARED/1e9:.3f} GB) / 3.20 TB/s = {d10['tw']*1e3:.3f} ms。"
        "整卡 19.3 个专家加共享要 13.40 毫秒，长过 10 毫秒，所以这一档不能把本地专家读满。"
        f"机内 allreduce：ceil({bs10}/16) = {d10['toks']} 条，每条 7168×2 字节，环上每层 2×7/8，61 层除以 40 GB/s = {d10['t_ar']*1e3:.3f} ms。"
        f"两项相加 {d10['t']*1e3:.3f} ms。{bs10+1} 条是 {decode(bs10+1, 4096)['t']*1e3:.3f} ms。"
        f"专家计算 {d10['t_cm']*1e3:.3f} ms，效率 {d10['ue']:.3f}。EP {d10['t_ep']*1e3:.3f} ms。注意力计算 {d10['t_ca']*1e3:.3f} ms。注意力权重 {d10['t_wa']*1e3:.3f} ms。"
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
        ["通信", "allreduce 随批线性涨\n这一档是注意力侧最长", f"combine 走 320 GB/s\n{ms2(d30['t_ep'])}，短于读权重"],
        ["访存", "短输入全在 HBM\n放不下走每卡内存池 320 GB/s", f"{ROUTED/N/1e9:.1f} GB 路由 + {SHARED/1e9:.2f} GB 共享\n/ 3.20 TB/s = {ms2(d30['tw'])}"],
        ["计算", f"注意力计算 {ms2(d30['t_ca'])}\n短于 allreduce", f"每专家约 {d30['tok']:.1f} token\n16 行砖，效率 {d30['ue']*100:.0f}%，{ms2(d30['t_cm'])}"],
    ]
    add_table(s5, 0.42, 1.78, [1.15, 2.55, 2.70], par5, [0.28, 0.58, 0.58, 0.62, 0.58], ["head", "body", "key", "body", "body"], size=12)
    step5 = [
        ["笔", "白话", "时间"],
        ["读权重", f"命中率 {d30['frac']*100:.0f}%，{d30['e_hot']:.1f} 个专家全读\n{hot30:.2f} GB / 3.20 TB/s", ms2(d30["tw"])],
        ["机内通信", f"每组 {d30['toks']} 条 × 7168 × 2 字节\n61 层 × 2×7/8 / 40 GB/s", ms2(d30["t_ar"])],
        ["专家计算", f"{bs30} × 6 / 2469 ≈ {d30['tok']:.1f} token / 专家\n对齐效率 {d30['ue']*100:.0f}%", ms2(d30["t_cm"])],
        ["专家通信", "最忙卡 combine / 320 GB/s", ms2(d30["t_ep"])],
        ["注意力计算", "短输入的打分和投影", ms2(d30["t_ca"])],
        ["相加", f"注意力侧 {d30['t_ar']*1e3:.2f}，专家侧 {d30['tw']*1e3:.2f}", ms2(d30["t"])],
    ]
    add_table(
        s5,
        7.05,
        1.78,
        [1.25, 3.45, 1.15],
        step5,
        [0.28, 0.52, 0.52, 0.48, 0.40, 0.40, 0.42],
        ["head", "key", "key", "body", "body", "body", "sum"],
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
        f"BS={bs30} 时 6×{bs30}/2469 ≈ {bs30*6/E:.2f}，命中率 {d30['frac']:.4f}，每卡 {d30['e_hot']:.3f} 个专家全醒。"
        f"读权重 ({ROUTED/N/1e9:.2f} GB + {SHARED/1e9:.2f} GB) / 3.20 TB/s = {d30['tw']*1e3:.3f} ms。"
        f"机内 allreduce：ceil({bs30}/16) = {d30['toks']} 条，环上每层 2×7/8，61 层，除以 40 GB/s = {d30['t_ar']*1e3:.3f} ms。"
        f"两项相加 {d30['t']*1e3:.3f} ms。{bs30+1} 条是 {decode(bs30+1, 4096)['t']*1e3:.3f} ms。"
        f"再加一条时，每个专家的 token 跨过 16，16 行砖的效率从 {d30['ue']*100:.0f}% 掉到一半，专家 GEMM 变成专家侧最长的一笔。"
        f"专家 combine {d30['t_ep']*1e3:.3f} ms，专家计算 {d30['t_cm']*1e3:.3f} ms，效率 {d30['ue']:.3f}。注意力计算 {d30['t_ca']*1e3:.3f} ms。"
        "30 毫秒的通信限制在机内 8 卡 allreduce。EP 走 320 GB/s 的 D2D，这一步短于读权重。"
        f"显存：每卡 96 − {ROUTED/N/1e9:.2f} − {SHARED/1e9:.2f} − {ATTN/TP/1e9:.2f} − 6 = {(HBM_CAP - ROUTED/N - SHARED - ATTN/TP - RESERVE)/1e9:.2f} GB，128 卡共 {ROOM/1e12:.2f} TB。"
        "HBM 放不下的 KV 走每卡总线内存池。标称 480 GB/s，被 3.2 Tb/s 的口卡住，有效 320 GB/s，容量不设上限。H2D 只在 prefill。"
        f"256K、全局批 {by_len[262144]['b30']} 时，存量的 {by_len[262144]['d30']['spill']*100:.1f}% 在池上，稀疏读 {by_len[262144]['d30']['t_pool']*1e3:.2f} ms，短于 allreduce {by_len[262144]['d30']['t_ar']*1e3:.2f} ms，所以批保持 {bs30}。"
        f"512K 降到 {by_len[524288]['b30']}，池上读 {by_len[524288]['d30']['t_pool']*1e3:.2f} ms。1M 降到 {by_len[1048576]['b30']}，{s_label} 降到 {extra[s_show]['b30']}。"
        f"4K、输出 512、命中 90%：Prefill {prefill_rps:.1f} 请求/秒。10 毫秒 Decode {dec10_rps:.1f} 请求/秒，P:D ≈ 1:{pd10:.1f}。30 毫秒 Decode {dec30_rps:.1f} 请求/秒，P:D ≈ 1:{pd30:.1f}。"
    )

    # ----- slide 6 -----
    s6 = prs.slides.add_slide(blank)
    chrome(s6, 6, f"10 毫秒这些长度都不进池；256K 的 30 毫秒仍是 {bs30}", "Decode    ·    不同输入下的最大全局批")
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
        f"10 毫秒在 {span10} 都是 {bs10}，全在 HBM。一步是读专家 {d10['tw']*1e3:.2f} 毫秒加机内 allreduce {d10['t_ar']*1e3:.2f} 毫秒。"
        f"1M 降到 {by_len[1048576]['b10']}，{s_label} 是 {extra[s_show]['b10']}，仍然全在 HBM。\n"
        f"30 毫秒在 {span30} 仍是 {bs30}，全在 HBM。256K 仍是 {by_len[262144]['b30']}，{where(by_len[262144]['d30']['spill'])}："
        f"稀疏读 {by_len[262144]['d30']['t_pool']*1e3:.1f} 毫秒，短于 allreduce {by_len[262144]['d30']['t_ar']*1e3:.2f} 毫秒。"
        f"512K 降到 {by_len[524288]['b30']}，1M 为 {by_len[1048576]['b30']}，{s_label} 为 {extra[s_show]['b30']}。\n"
        f"Prefill 的 10 秒全局批在第 3 页：4K 为 {p4['bs']}，1M 为 {p1m['bs']}。"
        f"4K 进、512 出、90% 命中时，P:D 在 10 毫秒约 1:{pd10:.1f}，在 30 毫秒约 1:{pd30:.1f}。",
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
        "三条通路同时看，取最慢的一条，再和专家阶段相加。"
        + " ".join(lines)
        + f" 2M 的 10 毫秒批 {extra[2_000_000]['b10']}，池上读 {extra[2_000_000]['d10']['t_pool']*1e3:.2f} ms。"
        f"4×10^6 的 10 毫秒批 {extra[4_000_000]['b10']}，30 毫秒批 {extra[4_000_000]['b30']}。"
        f"{s_label} 的 10 毫秒批 {extra[s_show]['b10']}，30 毫秒批 {extra[s_show]['b30']}。"
        f"单条 1M、90% 命中的 TTFT 是 {one_1m['t']:.4f} 秒。冷的 1M 单条是 {prefill_one(1048576)['t']:.3f} 秒。"
        "第 3 页 Prefill："
        + "，".join(f"{fmt_len(row['S'])} {row['bs']}" for row in pb)
        + f"。P:D 按 4K 进、512 出、90% 命中：Prefill {prefill_rps:.1f} 请求/秒，"
        f"10 毫秒 Decode {dec10_rps:.1f} 请求/秒（1:{pd10:.2f}），30 毫秒 Decode {dec30_rps:.1f} 请求/秒（1:{pd30:.2f}）。"
        "副本数按这个吞吐比配置，单副本时延不变。"
    )

    def lane_bytes(d, bs, s):
        pairs = (d["e_hot"] / (E / N)) * (bs * TOPK / N)
        read_gpu = bs * n_csa_read(s) / N
        return {
            "w": d["e_hot"] * W_ONE * 0.5 + SHARED,
            "ar": 2 * (TP - 1) / TP * (d["toks"] * H * 2) * L,
            "ep": pairs * 2 * H * L,
            "hbm": read_gpu * (1.0 - d["spill"]),
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
            ("换入", d["t_pool"]),
            ("allreduce", d["t_ar"]),
            ("注意力计算", d["t_ca"]),
            ("HBM 读", d["t_kv"] + d["t_wa"]),
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
    bound = next(
        pt for pt in swap_pts
        if attn_name(pt["d30"])[0] == "换入"
    )
    g_hold = lane_bytes(hold["d30"], hold["b30"], hold["S"])
    g_bound = lane_bytes(bound["d30"], bound["b30"], bound["S"])

    def step_sum(d):
        side, _ = attn_name(d)
        expert = "读专家" if d["tw"] >= d["t_cm"] and d["tw"] >= d["t_ep"] else "专家计算"
        return f"{side} + {expert} · {ms2(d['t'])}"

    s7 = prs.slides.add_slide(blank)
    chrome(
        s7, 7,
        f"{len_name(hold['S'])} 每卡换入 {qty(g_hold['pool'])}，{len_name(bound['S'])} 换入成为最长的一笔",
        "Decode    ·    只统计进了 DDR 池的长度",
    )
    banner(
        s7, 0.92,
        "这两页只列 KV 换进 DDR 池的输入。一步仍是注意力侧最长的一笔，加上专家侧最长的一笔。",
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
        ["专家 combine", both(g_hold["ep"], hold["d30"]["t_ep"]), both(g_bound["ep"], bound["d30"]["t_ep"])],
        ["注意力计算", ms2(hold["d30"]["t_ca"]), ms2(bound["d30"]["t_ca"])],
        ["注意力权重", both(g_hold["attn"], hold["d30"]["t_wa"]), both(g_bound["attn"], bound["d30"]["t_wa"])],
        ["HBM 上的 KV", both(g_hold["hbm"], hold["d30"]["t_kv"]), both(g_bound["hbm"], bound["d30"]["t_kv"])],
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
        f"短于 allreduce {hold['d30']['t_ar']*1e3:.2f} 毫秒，批保持 {hold['b30']}。128 卡合计 {qty(g_hold['pool'] * N)}。\n"
        f"{len_name(bound['S'])} 换入 {qty(g_bound['pool'])}、{bound['d30']['t_pool']*1e3:.2f} 毫秒，长过 allreduce 和注意力计算，"
        f"和读专家 {bound['d30']['tw']*1e3:.2f} 毫秒相加，批降到 {bound['b30']}。128 卡合计 {qty(g_bound['pool'] * N)}。\n"
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
    census_head = ["输入", "30 毫秒批", "每卡", "溢出", "每卡换入", "128 卡合计", "换入耗时", "注意力侧取"]
    add_table(
        s8, 0.42, 1.48,
        [1.35, 1.25, 0.90, 1.05, 1.50, 1.65, 1.45, 3.15],
        [census_head] + [census_row(pt) for pt in swap_pts],
        [0.38] + [0.42] * len(swap_pts),
        ["head"] + ["key" if pt is hold or attn_name(pt["d30"])[0] == "换入" else "body" for pt in swap_pts],
        size=12,
    )
    textbox(s8, 0.42, 3.70, 12.5, 0.22, "同一批长度上，换入和另外几笔的耗时", 13, True, ACCENT)
    time_head = ["输入", "换入", "allreduce", "注意力计算", "HBM 上的 KV", "读专家", "一步"]
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
