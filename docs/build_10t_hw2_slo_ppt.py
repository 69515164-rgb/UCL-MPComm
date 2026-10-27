#!/usr/bin/env python3
"""10T DeepSeek on infrastructure config 2, in the 6-slide SLO deck layout.

Network rates in the brief are Gb/s. 400 Gb/s = 50 GB/s peak = 40 GB/s at 80%.
800 Gb/s = 100 GB/s peak = 80 GB/s at 80%. Experts use the FP4 peak. Attention
uses FP8 at half that peak, matching the FP8 attention bytes in the 10T model.
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

N, TP, NODE = 128, 16, 16
DP = N // TP
PEAK_FP4 = 7e15
PEAK_FP8 = PEAK_FP4 / 2
HBM_CAP = 180e9
HBM_BW = 9e12 * 0.80
D2D = 400e9 / 8 * 0.80
P2P = 400e9 / 8 * 0.80
PARAM = 400e9 / 8 * 0.80
H2D = 800e9 / 8 * 0.80
DDR_NODE_BW = 1288.8e9 * 0.80
SPILL = min(H2D, DDR_NODE_BW / NODE)
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
LOCAL_DDR = N * DDR_PER_GPU_CAP
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


def chrome(slide, page, title, kicker, total=6):
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
        "10T 为外推    ·    一份 128 卡副本    ·    访存与通信取峰值的 80%    ·    专家 FP4、注意力 FP8，Cube 按 16 行对齐",
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
    hbm_b = min(store, ROOM)
    loc_b = min(max(store - ROOM, 0.0), LOCAL_DDR)
    spill = loc_b / store if store else 0.0
    t_kh = read_gpu * (hbm_b / store) / HBM_BW if store else 0.0
    t_h2d = read_gpu * spill / SPILL
    t_wa = (ATTN / TP) / HBM_BW
    t_ca = bs * (score + PROJ) / (N * PEAK_FP8 * ua)
    t_cm = bs * MOE / (N * PEAK_FP4 * ue)
    pairs = (e_hot / e) * (bs * TOPK / N)
    t_ep = pairs * 2 * H * L / D2D
    toks = math.ceil(bs / DP)
    t_ar = 2 * (TP - 1) / TP * (toks * H * 2) * L / P2P
    t_attn = max(t_ca, t_kh + t_wa, t_h2d, t_ar)
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
        "t_h2d": t_h2d,
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
    cap = int((ROOM + LOCAL_DDR) // store_seq(s))
    if cap < 1 or decode(1, s)["t"] > limit:
        return 0
    lo, hi, best = 1, cap, 0
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
    x = v * 1e3
    if x >= 10:
        return f"{x:.1f} 毫秒"
    return f"{x:.2f} 毫秒"


def sec(v):
    if v >= 9.95:
        return f"{v:.1f} 秒"
    return f"{v:.2f} 秒"


def where(spill):
    if spill < 0.005:
        return "全在 HBM"
    pct = spill * 100
    text = f"{pct:.1f}%" if pct < 10 else f"{pct:.0f}%"
    return f"{text} 经本卡 H2D"


def main():
    s_max = max_input()
    s_show = int(s_max)
    p = prefill_one(s_show)
    weight_gb = (ROUTED / N + SHARED + ATTN / TP) / 1e9
    kv_gb = s_show * BPT / 1e9
    bs10, bs30 = 784, 4688
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
    for s in (2_000_000, 5_000_000, s_show):
        b10 = search_bs(s, 0.010)
        b30 = search_bs(s, 0.030)
        extra[s] = {"b10": b10, "b30": b30, "d10": decode(b10, s), "d30": decode(b30, s), "cap": hbm_cap(s)}

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

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "10T DeepSeek：结构外推与 TTFT / TPOT（配置 2）"
    blank = prs.slide_layouts[6]

    # ----- slide 1 -----
    s1 = prs.slides.add_slide(blank)
    chrome(s1, 1, "同一骨架，只加路由专家", "模型结构    ·    1.6T 论文到 10T 外推")
    textbox(
        s1,
        0.42,
        0.90,
        12.5,
        0.32,
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
        ["640 GB 卡下限", "2 张", "8 张", "只按 FP4 专家表。时延页用 180 GB × 128 卡"],
    ]
    add_table(s1, 0.42, 1.28, [2.15, 3.15, 2.55, 4.65], rows, [0.34] + [0.46] * 9, ["head"] + ["body"] * 9)
    note = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.22), Inches(12.5), Inches(0.86))
    solid(note, GOLD_BG)
    textbox(
        s1,
        0.58,
        6.26,
        12.18,
        0.78,
        "外推式：总参数 = 专家数 × 4.030×10^9 + 5.260×10^10。单个专家 = 3 × 7168 × 3072 × 61。\n"
        "时延页按配置 2：专家 7 P FP4，注意力 3.50 P FP8，HBM 180 GB / 9 TB/s。400 Gb/s 取 80% 为 40 GB/s，800 Gb/s 取 80% 为 80 GB/s。",
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
        "后面几页是配置 2，不再用 96 GB 和 486×10^12。"
        "每卡 HBM 180 GB，带宽 9 TB/s，计时取 80% 即 7.2 TB/s。专家 GEMM 用 7×10^15 FP4。注意力权重在字节模型里是 FP8（19.35 GB），算力取 FP4 的一半，3.50×10^15。"
        "链路按 Gb/s 换算：D2D、机内 P2P、参数面都是 400 Gb/s = 50 GB/s 峰值，80% 后 40 GB/s。H2D 800 Gb/s = 100 GB/s 峰值，80% 后 80 GB/s。"
        "机器 DDR 768 GB、1288.8 GB/s 是一台 16 卡机器的数。进卡取 H2D 80 GB/s 与单卡 DDR 份额 1031/16 = 64.4 GB/s 里较慢的一条。"
        "128 卡超节点 = 8 台机器。注意力 TP=16 留在机内 fullmesh，DP=8。MoE EP=128 走 D2D。"
        "每卡扣掉路由 38.86 GB、共享 4.03 GB、注意力 1.21 GB 和 6 GB 预留后，128 卡 KV 余量 16.63 TB。"
    )

    # ----- slide 2 -----
    s2 = prs.slides.add_slide(blank)
    chrome(s2, 2, "10 秒对应的最大输入是 6.54×10^6", "Prefill    ·    TTFT ≤ 10 秒")
    banner(
        s2,
        0.92,
        f"一条请求放在一个 128 卡副本上。计算 {sec(p['tc'])}，读权重 {ms(p['tw'])}，送 KV {ms(p['ship'])}。S² 占 {sec(p['idx'] + p['hca'])}，线性项占 {sec(p['core'] + p['proj'] + p['moe'])}。",
    )
    textbox(s2, 0.42, 1.46, 6.2, 0.26, "并行策略", 13, True, ACCENT)
    par_rows = [
        ["", "Attention", "MoE"],
        ["并行", "机内 TP=16\n8 台机器做 DP=8", "超节点 EP=128\n一份模型铺满 128 卡"],
        ["通信域", "16 卡 fullmesh\n有效 40 GB/s", "128 卡 D2D，有效 40 GB/s\nKV 走参数面，有效 40 GB/s"],
        [
            "每卡权重",
            f"注意力 19.35 GB / 16\n= {ATTN / TP / 1e9:.2f} GB FP8",
            f"路由专家 {E / N:.1f} 个，{ROUTED / N / 1e9:.1f} GB FP4\n共享专家 {SHARED / 1e9:.2f} GB，每卡一份",
        ],
        ["本阶段角色", "S² 来自 indexer 和 HCA\n决定输入能写多长", f"专家 GEMM 随 token 线性\n到这个长度约占 {sec(p['moe'])}"],
    ]
    add_table(
        s2,
        0.42,
        1.72,
        [1.55, 5.40, 5.55],
        par_rows,
        [0.30, 0.52, 0.58, 0.52, 0.52],
        ["head", "body", "body", "body", "body"],
    )
    textbox(s2, 0.42, 4.26, 12.5, 0.24, "10 秒怎么落到这个输入长度", 13, True, ACCENT)
    calc_rows = [
        ["这一笔", "算法", f"S = {s_show / 1e6:.2f}×10^6 时"],
        ["CSA indexer", "30 层 × 2048 × S²，除以 128 × 3.50×10^15", sec(p["idx"])],
        ["HCA", "31 层 × 1024 × S²，除以同一 FP8 算力", sec(p["hca"])],
        ["专家 GEMM", "每 token 5.64×10^10 FLOP × S，除以 128 × 7.00×10^15", sec(p["moe"])],
        ["投影", "每 token 3.87×10^10 FLOP × S，除以 FP8 算力", sec(p["proj"])],
        ["稀疏注意力", "每 token 看 1024 条压缩 KV + 128 滑窗", sec(p["core"])],
        [
            "读权重 + 送 KV",
            f"每卡 {weight_gb:.1f} GB / 7.2 TB/s；KV {kv_gb:.1f} GB / (128×40 GB/s)",
            f"{ms(p['tw'])} + {ms(p['ship'])}",
        ],
        ["合计", "计算和读权重取长的一项，再加送 KV。S 再大，前两行先超", "10.0 秒"],
    ]
    add_table(
        s2,
        0.42,
        4.52,
        [1.70, 7.55, 3.25],
        calc_rows,
        [0.26, 0.26, 0.26, 0.26, 0.26, 0.26, 0.28, 0.30],
        ["head", "body", "body", "body", "body", "body", "body", "sum"],
        size=12,
    )
    s2.notes_slide.notes_text_frame.text = (
        "单请求不跨副本。增加 Prefill 节点是多放几份 128 卡副本，提高并发，不缩短这一条的 TTFT。"
        "注意力在机内 16 卡做 TP，8 台机器是 8 路 DP。MoE 把 2469 个专家铺到 128 卡，每卡 19.3 个，路由权重 38.9 GB FP4，共享专家 4.03 GB FP8，注意力 1.21 GB FP8。"
        "时间 = max(计算, 读权重) + 把 KV 送到 Decode。注意力 FLOP 除以 128×3.50×10^15，专家 FLOP 除以 128×7.00×10^15。"
        f"在 S={s_show:.0f}：indexer {p['idx']:.3f}s，HCA {p['hca']:.3f}s，专家 {p['moe']:.3f}s，投影 {p['proj']:.3f}s，稀疏注意力 {p['core']:.3f}s，合计计算 {p['tc']:.3f}s。"
        f"读权重 {p['tw']*1e3:.2f} ms，KV 搬运 {p['ship']*1e3:.2f} ms。S² 合计 {p['idx']+p['hca']:.2f}s，线性项 {p['core']+p['proj']+p['moe']:.2f}s。"
        "4K 单条 TTFT 是 6.1 毫秒，停在读权重。1M 单条、无命中是 0.41 秒。"
        "若注意力改按 BF16、算力再减半到 1.75×10^15，同一公式的最大输入降到 4.58×10^6。本页按 FP8。"
        "400 Gb/s 写成 50 GB/s 再取 80%。若原话是 GB/s，瓶颈会换边，本页的 40 GB/s 不再成立。"
        "下一页换成 90% KV 命中，问同一份副本上 TTFT 仍不超过 10 秒时能同时放进多少条。"
    )

    # ----- slide 3 -----
    s3 = prs.slides.add_slide(blank)
    chrome(s3, 3, "4K 的 prefill 全局批是 3964，1M 是 15", "Prefill    ·    TTFT ≤ 10 秒    ·    KV 命中 90%")
    banner(
        s3,
        0.92,
        "多条同时进同一份 128 卡副本。命中 90% 的 KV 走参数面，只现算 10%。注意力侧取 allreduce，再加专家侧较长的一项。",
    )
    textbox(s3, 0.42, 1.46, 12.5, 0.24, "10 秒在两个端点上怎么加完", 13, True, ACCENT)
    walk = [
        ["笔", "算法", "4K，全局批 3964", "1M，全局批 15"],
        ["现算 token", "批 × 输入 × 0.1", fmt_tok(p4["Q"]), fmt_tok(p1m["Q"])],
        [
            "机内 allreduce",
            "每组现算 token × 7168 × 2 字节\n61 层 × 2×15/16 / 40 GB/s",
            sec(p4["t_ar"]),
            sec(p1m["t_ar"]),
        ],
        [
            "注意力计算",
            "indexer、HCA、稀疏注意力、投影\n除以 FP8 的 3.50 P",
            sec(p4["t_attn"]),
            sec(p1m["t_attn"]),
        ],
        [
            "专家计算",
            "现算 token × 5.64×10^10 FLOP\n除以 128 × 7.00×10^15",
            sec(p4["t_moe"]),
            sec(p1m["t_moe"]),
        ],
        [
            "相加",
            "两侧取较长的一项，再加参数面读 KV",
            sec(p4["t"]),
            sec(p1m["t"]),
        ],
    ]
    add_table(
        s3,
        0.42,
        1.72,
        [1.70, 5.15, 2.85, 2.80],
        walk,
        [0.28, 0.30, 0.56, 0.52, 0.48, 0.34],
        ["head", "body", "key", "body", "body", "sum"],
    )
    textbox(s3, 0.42, 4.28, 12.5, 0.22, "同一条 10 秒，输入从 4K 到 1M", 13, True, ACCENT)
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
        4.52,
        [1.05, 1.55, 0.95, 1.70, 1.55, 1.55, 1.85, 2.30],
        [sweep_head] + sweep_body,
        [0.26] + [0.24] * len(sweep_body),
        sweep_kinds,
        size=11,
    )
    textbox(
        s3,
        0.42,
        6.66,
        12.5,
        0.30,
        f"这些批的 KV 都放得进 HBM：4K 能放 {fmt_count(p4['cap'])} 条，1M 能放 {p1m['cap']} 条。参数面读命中 KV 约 {ms(p4['tkv'])}。",
        13,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    s3.notes_slide.notes_text_frame.text = (
        "这一页的批是 128 卡副本上的全局批，每卡条数 = 全局批 / 128。切分与上一页相同：注意力 TP=16、DP=8，MoE EP=128。"
        "KV 命中 90%。命中部分按参数面 40 GB/s 读。每条只把 10% 的 token 送进计算，这 10% 的 query 仍看全长上下文。"
        "时间 = 参数面读 KV + 注意力侧较长的一项 + 专家侧较长的一项。"
        "注意力侧在注意力计算、机内 allreduce、注意力权重之间取最大。专家侧在专家 GEMM、读专家权重、EP 之间取最大。"
        "机内 allreduce：每组 token 数 = 现算 token / 8，每 token 7168×2 字节，环上 2×15/16，61 层，除以 40 GB/s。"
        f"4K 全局批 3964：现算 {p4['Q']:.4e} token，allreduce {p4['t_ar']:.3f}s，注意力计算 {p4['t_attn']:.3f}s，专家计算 {p4['t_moe']:.3f}s，"
        f"EP {p4['t_ep']:.3f}s，读权重 {p4['t_we']*1e3:.2f} ms，读 KV {p4['tkv']*1e3:.1f} ms，合计 {p4['t']:.3f}s。3965 条超过 10 秒。"
        f"1M 全局批 15：现算 {p1m['Q']:.4e}，allreduce {p1m['t_ar']:.3f}s，注意力计算 {p1m['t_attn']:.3f}s（indexer {p1m['t_idx']:.3f}s），"
        f"专家计算 {p1m['t_moe']:.3f}s，合计 {p1m['t']:.3f}s。16 条是 {prefill_batch(16, 1048576)['t']:.2f}s。"
        "4K 到 128K，allreduce 和专家 GEMM 都只跟现算 token 数有关，全局批大致按输入反比下降，现算总量停在约 1.62×10^6。"
        "1M 时注意力计算升到 0.51 秒，仍短于 allreduce 的 8.06 秒。"
        f"HBM 余量 {ROOM/1e12:.2f} TB。4K 能放 {p4['cap']} 条，1M 能放 {p1m['cap']} 条，都高于这页的时间批。"
        f"单条、1,048,576 token、90% 命中的 TTFT 是 {one_1m['t']:.2f} 秒，其中参数面读 KV {one_1m['tkv']*1e3:.2f} 毫秒，allreduce {one_1m['t_ar']:.2f} 秒。"
    )

    # ----- slide 4 -----
    s4 = prs.slides.add_slide(blank)
    chrome(s4, 4, "10 毫秒、短输入，全局批 784", "Decode    ·    TPOT ≤ 10 毫秒")
    banner(
        s4,
        0.92,
        f"整卡专家 {ms2(d10['tw'])}，机内 allreduce {ms2(d10['t_ar'])}。专家 GEMM {ms2(d10['t_cm'])}，D2D 上的 EP {ms2(d10['t_ep'])}。",
    )
    textbox(s4, 0.42, 1.46, 6.0, 0.26, "并行策略", 13, True, ACCENT)
    textbox(s4, 7.15, 1.46, 5.7, 0.26, "短输入（4K）这一步怎么加到 10 毫秒", 13, True, ACCENT)
    par4 = [
        ["", "Attention", "MoE"],
        ["并行", "TP=16，DP=8\n每组 token 数 = ⌈BS / 8⌉", "EP=128\n2469 个专家，每卡 19.3 个"],
        ["通信", f"每层机内 allreduce\n这一步 {ms2(d10['t_ar'])}", f"最忙卡 BF16 combine\n这一步 {ms2(d10['t_ep'])}"],
        ["访存", f"注意力权重 {ATTN/TP/1e9:.2f} GB\n这一步 {ms2(d10['t_wa'])}", f"19.3 个专家这一步 {ms2(d10['tw'])}\n整张本地表都读到"],
        ["计算", "行数 = ⌈BS / 8⌉\n按 16 行砖对齐", f"每个命中专家约 {d10['tok']:.1f} 个 token\n16 行砖，效率 {d10['ue']*100:.0f}%"],
    ]
    add_table(s4, 0.42, 1.74, [1.15, 2.55, 2.70], par4, [0.28, 0.62, 0.62, 0.66, 0.62], ["head", "body", "body", "key", "body"], size=12)
    step4 = [
        ["笔", "白话", "时间"],
        [f"命中", f"1 − exp(−6×784 / 2469) = {d10['frac']*100:.0f}%\n最忙卡按均值 + 2σ，顶到 {d10['e_hot']:.1f} 个", "—"],
        ["读专家", f"{d10['e_hot']:.1f} × {EXPERT_GB:.3f} GB + 共享 {SHARED/1e9:.2f} GB\n除以 7.2 TB/s", ms2(d10["tw"])],
        ["机内通信", f"每组 {d10['toks']} 条 × 7168 × 2 字节\n61 层 × 2×15/16 / 40 GB/s", ms2(d10["t_ar"])],
        ["专家计算", f"每个命中专家约 {d10['tok']:.1f} 个 token\n16 行砖，效率 {d10['ue']*100:.0f}%", ms2(d10["t_cm"])],
        ["专家通信", "最忙卡送出的 BF16 combine / 40 GB/s", ms2(d10["t_ep"])],
        ["相加", f"注意力侧 {ms2(d10['t_ar'])}，专家侧 {ms2(d10['tw'])}", "10.0 毫秒"],
    ]
    add_table(
        s4,
        7.05,
        1.74,
        [1.20, 3.50, 1.15],
        step4,
        [0.28, 0.58, 0.56, 0.54, 0.50, 0.44, 0.42],
        ["head", "body", "key", "key", "body", "body", "sum"],
        size=12,
    )
    d10_2m = extra[2_000_000]["d10"]
    d10_5m = extra[5_000_000]["d10"]
    d10_max = extra[s_show]["d10"]
    chips(
        s4,
        [
            ("4K – 1M", "784", f"全局批，每卡 {per_card(784)} 条\n全在 HBM"),
            ("2M", "784", f"全局批，每卡 {per_card(784)} 条\n{where(d10_2m['spill'])}"),
            ("5×10^6", f"{extra[5_000_000]['b10']}", f"全局批，每卡 {per_card(extra[5_000_000]['b10'])} 条\n{where(d10_5m['spill'])}"),
            ("6.54×10^6", f"{extra[s_show]['b10']}", f"全局批，每卡 {per_card(extra[s_show]['b10'])} 条\n{where(d10_max['spill'])}"),
        ],
    )
    s4.notes_slide.notes_text_frame.text = (
        "Decode 与 Prefill 用同一份 128 卡副本：注意力 TP=16、DP=8，MoE EP=128。"
        "加 Decode 节点是多副本，单副本的 TPOT 不变。"
        "一步 = 注意力侧最长的一笔 + 专家侧最长的一笔。两段相加。"
        f"命中率 = 1 − exp(−6×784 / 2469) = {d10['frac']:.3f}。最忙卡 = min(19.289, 均值 + 2σ) = {d10['e_hot']:.3f}，已经顶到每卡全部本地专家。"
        f"读权重 ({d10['e_hot']:.3f}×{EXPERT_GB:.3f} GB + {SHARED/1e9:.3f} GB) / 7.2 TB/s = {d10['tw']*1e3:.3f} ms。"
        f"机内 allreduce：ceil(784/8) = {d10['toks']} 条，每条 7168×2 字节，环上每层 2×15/16，61 层除以 40 GB/s = {d10['t_ar']*1e3:.3f} ms。"
        f"两项相加 {d10['t']*1e3:.2f} ms，表上记 10.0 毫秒。785 条是 {decode(785, 4096)['t']*1e3:.2f} ms。"
        f"专家计算 {d10['t_cm']*1e3:.3f} ms，效率 {d10['ue']:.3f}。EP {d10['t_ep']*1e3:.3f} ms。注意力计算 {d10['t_ca']*1e3:.3f} ms。注意力权重 {d10['t_wa']*1e3:.3f} ms。"
        "4K 到 2M，全局批都是 784，KV 全在 HBM。5×10^6 降到 683，6.54×10^6 降到 523，多出来的存量走本卡 H2D 64.4 GB/s。"
        "把 D2D 加宽，这一档的批先不变：EP 只有 0.80 毫秒，短于 allreduce。"
    )

    # ----- slide 5 -----
    s5 = prs.slides.add_slide(blank)
    chrome(s5, 5, "30 毫秒、短输入，全局批 4688", "Decode    ·    TPOT ≤ 30 毫秒")
    banner(
        s5,
        0.92,
        f"专家整卡读完，读权重停在 {ms2(d30['tw'])}。剩下的预算被机内 16 卡 allreduce 用掉，{ms2(d30['t_ar'])}。专家域通信 {ms2(d30['t_ep'])}。",
    )
    textbox(s5, 0.42, 1.46, 6.2, 0.26, "并行策略    ·    和 10 毫秒同一份切分", 13, True, ACCENT)
    textbox(s5, 7.15, 1.46, 5.7, 0.26, "短输入、全局批 4688，这一步怎么加", 13, True, ACCENT)
    par5 = [
        ["", "Attention", "MoE"],
        ["并行", f"仍是 TP=16，DP=8\n4688 / 8 = {d30['toks']} 条 / 组", "仍是 EP=128\n每卡 19.3 个专家全醒"],
        ["通信", "allreduce 随批线性涨\n这一档是注意力侧最长", f"combine 走 40 GB/s\n{ms2(d30['t_ep'])}，短于读权重"],
        ["访存", "短输入全在 HBM\n放不下走本卡 H2D 64.4 GB/s", f"{ROUTED/N/1e9:.1f} GB 路由 + {SHARED/1e9:.2f} GB 共享\n/ 7.2 TB/s = {ms2(d30['tw'])}"],
        ["计算", f"注意力计算 {ms2(d30['t_ca'])}\n短于 allreduce", f"每专家约 {d30['tok']:.1f} token\n16 行砖，效率 {d30['ue']*100:.0f}%，{ms2(d30['t_cm'])}"],
    ]
    add_table(s5, 0.42, 1.74, [1.15, 2.55, 2.70], par5, [0.28, 0.62, 0.62, 0.66, 0.62], ["head", "body", "key", "body", "body"], size=12)
    step5 = [
        ["笔", "白话", "时间"],
        ["读权重", f"命中率 {d30['frac']*100:.0f}%，{d30['e_hot']:.1f} 个专家全读\n加共享专家，除以 7.2 TB/s", ms2(d30["tw"])],
        ["机内通信", f"每组 {d30['toks']} 条 × 7168 × 2 字节\n61 层 × 2×15/16 / 40 GB/s", ms2(d30["t_ar"])],
        ["专家计算", f"4688 × 6 / 2469 ≈ {d30['tok']:.1f} token / 专家\n对齐效率 {d30['ue']*100:.0f}%", ms2(d30["t_cm"])],
        ["专家通信", "最忙卡 combine / 40 GB/s", ms2(d30["t_ep"])],
        ["注意力计算", "短输入的打分和投影", ms2(d30["t_ca"])],
        ["相加", f"注意力侧 {ms2(d30['t_ar'])}，专家侧 {ms2(d30['tw'])}", "30.0 毫秒"],
    ]
    add_table(
        s5,
        7.05,
        1.74,
        [1.25, 3.45, 1.15],
        step5,
        [0.28, 0.56, 0.56, 0.52, 0.44, 0.42, 0.46],
        ["head", "key", "key", "body", "body", "body", "sum"],
        size=12,
    )
    b30_1m = sweep[6]["b30"]
    b30_2m = extra[2_000_000]["b30"]
    b30_max = extra[s_show]["b30"]
    chips(
        s5,
        [
            ("4K – 512K", "4688", f"全局批，每卡 {per_card(4688)} 条\n全在 HBM"),
            ("1M", f"{b30_1m}", f"全局批，每卡 {per_card(b30_1m)} 条\n{where(sweep[6]['d30']['spill'])}"),
            ("2M", f"{b30_2m}", f"全局批，每卡 {per_card(b30_2m)} 条\n{where(extra[2_000_000]['d30']['spill'])}"),
            ("6.54×10^6", f"{b30_max}", f"全局批，每卡 {per_card(b30_max)} 条\n{where(extra[s_show]['d30']['spill'])}"),
        ],
        number_size=26,
    )
    s5.notes_slide.notes_text_frame.text = (
        "30 毫秒用的切分与 10 毫秒相同：TP=16，DP=8，EP=128，128 卡一份副本。"
        f"BS=4688 时 6×4688/2469 ≈ {4688*6/E:.2f}，命中率 {d30['frac']:.4f}，每卡 {d30['e_hot']:.3f} 个专家全醒。"
        f"读权重 (38.86 GB + 4.03 GB) / 7.2 TB/s = {d30['tw']*1e3:.3f} ms。"
        f"机内 allreduce：ceil(4688/8) = {d30['toks']} 条，环上每层 2×15/16，61 层，除以 40 GB/s = {d30['t_ar']*1e3:.3f} ms。"
        f"两项相加 {d30['t']*1e3:.2f} ms，表上记 30.0 毫秒。4689 条是 {decode(4689, 4096)['t']*1e3:.2f} ms。"
        f"专家 combine {d30['t_ep']*1e3:.3f} ms，专家计算 {d30['t_cm']*1e3:.3f} ms，效率 {d30['ue']:.3f}。注意力计算 {d30['t_ca']*1e3:.3f} ms。"
        "30 毫秒的通信限制在机内 16 卡 allreduce。EP 走的 D2D 同样是 40 GB/s，这一步只有 4.80 毫秒。"
        "显存：每卡 180 − 38.86 − 4.03 − 1.21 − 6 = 129.9 GB，128 卡共 16.63 TB。"
        "HBM 放不下的 KV 走本卡换入。H2D 有效 80 GB/s，单卡分到的 DDR 是 1288.8×0.8/16 = 64.4 GB/s，取较慢的 64.4 GB/s。"
        "约 70 万 token 以内全局批仍是 4688。80 万 token 起下降。1M 为 3502，2M 为 1839，6.54×10^6 为 564。"
        "4K、输出 512、命中 90%：Prefill 396 请求/秒。10 毫秒 Decode 154 请求/秒，P:D ≈ 1:2.6。30 毫秒 Decode 305 请求/秒，P:D ≈ 1:1.3。"
    )

    # ----- slide 6 -----
    s6 = prs.slides.add_slide(blank)
    chrome(s6, 6, "输入越长，30 毫秒的全局批掉得越快", "Decode    ·    不同输入下的最大全局批")
    banner(
        s6,
        0.92,
        "全局批是 128 卡上的条数。溢出 KV 走本卡 H2D，按 64.4 GB/s：800 Gb/s 的 80% 与每卡 DDR 份额里较慢的一条。",
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
        1.52,
        [1.15, 1.35, 1.35, 1.70, 1.00, 1.75, 1.00, 3.20],
        [head] + body,
        [0.38] + [0.46] * len(body),
        kinds,
        size=12,
    )
    note = s6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.58), Inches(12.5), Inches(1.48))
    solid(note, GOLD_BG)
    b10_max = extra[s_show]["b10"]
    textbox(
        s6,
        0.58,
        5.66,
        12.18,
        1.32,
        "10 毫秒到 2M 都是 784，全在 HBM。一步是机内 allreduce 4.02 毫秒加读专家 5.96 毫秒。"
        f"5×10^6 降到 {extra[5_000_000]['b10']}，6.54×10^6 降到 {b10_max}。\n"
        "30 毫秒在约 70 万 token 以内仍是 4688，卡在 allreduce 24.0 毫秒加读权重 5.96 毫秒。"
        f"1M 为 {b30_1m}（{where(sweep[6]['d30']['spill'])}），2M 为 {b30_2m}，6.54×10^6 为 {b30_max}。\n"
        f"Prefill 的 10 秒全局批在第 3 页：4K 为 3964，1M 为 15。4K、输出 512、90% 命中时，P:D 在 10 毫秒约 1:2.6，在 30 毫秒约 1:1.3。",
        14,
        False,
        GOLD,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    lines = []
    for row in sweep:
        lines.append(
            f"S={row['S']} store={row['store']/1e6:.1f}MB cap={row['cap']} "
            f"b10={row['b10']} spill10={row['d10']['spill']*100:.2f}% "
            f"b30={row['b30']} spill30={row['d30']['spill']*100:.2f}% t30={row['d30']['t']*1e3:.2f}ms"
        )
    s6.notes_slide.notes_text_frame.text = (
        "BS 一律是 128 卡副本的全局批。每卡条数 = 全局批 / 128。"
        "存量 = S×4939.5 字节 + 4.50 MB。一步真正读的是压缩 indexer、最多 1024 条完整 KV 和 HCA。"
        f"HBM 余量 {ROOM/1e12:.2f} TB。溢出进 GPU 的口是本卡换入，有效 {SPILL/1e9:.2f} GB/s。"
        "这个口是 min(H2D 80 GB/s, 机器 DDR 有效 1031 GB/s / 16)。远端 DDR 进这张卡也走这张卡的 H2D。"
        "三条通路同时走，取最慢的一条，再和专家阶段相加。"
        + " ".join(lines)
        + " 10 毫秒在 4M 仍是 784，5M 为 683，6.54×10^6 为 523。"
        "30 毫秒在 70 万 token 仍是 4688，80 万 token 为 4585。1M 为 3502，其中约 8.4% 的存量经 H2D 读，这一笔约 24 毫秒。"
        f"单条 1M、90% 命中的 TTFT 是 {one_1m['t']:.2f} 秒。冷的 1M 单条是 0.41 秒。"
        "第 3 页 Prefill：4K 3964，8K 1982，32K 495，128K 123，256K 61，512K 30，1M 15。"
    )

    out = "/workspace/docs/10t-hw2-slo.pptx"
    prs.save(out)
    print(out)
    print("S", s_show, "tc", round(p["tc"], 3), "tw", round(p["tw"] * 1e3, 2), "ship", round(p["ship"] * 1e3, 2))
    print("d10", round(d10["t"] * 1e3, 3), "ar", round(d10["t_ar"] * 1e3, 3), "tw", round(d10["tw"] * 1e3, 3), "cm", round(d10["t_cm"] * 1e3, 3), "ep", round(d10["t_ep"] * 1e3, 3))
    print("d30", round(d30["t"] * 1e3, 3), "ar", round(d30["t_ar"] * 1e3, 3), "cm", round(d30["t_cm"] * 1e3, 3), "ep", round(d30["t_ep"] * 1e3, 3), "ca", round(d30["t_ca"] * 1e3, 3))
    print("pf", p4["bs"], p1m["bs"])
    for row in sweep:
        print(fmt_len(row["S"]), row["b10"], row["b30"], where(row["d30"]["spill"]), fmt_bytes(row["store"]), fmt_count(row["cap"]))
    for s, row in extra.items():
        print("extra", s, row["b10"], where(row["d10"]["spill"]), row["b30"], where(row["d30"]["spill"]))


if __name__ == "__main__":
    main()
