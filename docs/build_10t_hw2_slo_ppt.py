#!/usr/bin/env python3
"""10T DeepSeek on infrastructure config 2: TTFT 10s, TPOT 10ms and 30ms."""

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
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"

# --- hardware, config 2 ---
# Network figures are given in Gb/s. 400 Gb/s = 50 GB/s peak.
N = 128
TP = 16
NODE = 16
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
DDR_PER_GPU = DDR_NODE_BW / NODE
SPILL = min(H2D, DDR_PER_GPU)
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
    store = bs * (s * BPT + FIXED)
    read = n_csa_read(s)
    read_gpu = bs * read / N
    hbm_b = min(store, ROOM)
    loc_b = min(max(store - ROOM, 0.0), LOCAL_DDR)
    t_kh = read_gpu * (hbm_b / store) / HBM_BW
    t_h2d = read_gpu * (loc_b / store) / SPILL
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
        "t_ep": t_ep,
        "t_ar": t_ar,
        "t_kv": t_kh,
        "t_h2d": t_h2d,
    }


def n_csa_read(s):
    sel = min(1024.0, s / 4.0)
    return N_CSA * (s / 4.0) * 64 + N_HCA * (s / 128.0) * 576 + N_CSA * sel * 576 + FIXED


def store_seq(s):
    return s * BPT + FIXED


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
    t_attn = (idx + hca + core + PROJ * tokens) / (ua * N * PEAK_FP8)
    t_moe = MOE * tokens / (ue * N * PEAK_FP4)
    t_we = ((e_hot * W_ONE * 0.5 + SHARED) if e_hot > 0 else SHARED) / HBM_BW
    t_kv = bs * hit * s * BPT / (N * PARAM)
    t_ar = 2 * (TP - 1) / TP * ((tokens / DP) * H * 2) * L / P2P
    t_ep = ((e_hot / e) * (tokens * TOPK / N) if e else 0.0) * 2 * H * L / D2D
    t_wa = (ATTN / TP) / HBM_BW
    return t_kv + max(t_attn, t_ar, t_wa) + max(t_moe, t_we, t_ep)


def max_prefill_bs(s, hit=0.9, limit=10.0):
    cap = hbm_cap(s)
    if cap < 1:
        return 0
    lo, hi, best = 1, 1, 0
    while hi < cap and prefill_batch(hi, s, hit) <= limit:
        hi = min(cap, hi * 2)
        if hi == cap:
            break
    while lo <= hi:
        mid = (lo + hi) // 2
        if prefill_batch(mid, s, hit) <= limit:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


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
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for child in list(tc_pr):
        if child.tag == qn("a:solidFill"):
            tc_pr.remove(child)
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", color)
    solid_fill.append(srgb)
    tc_pr.append(solid_fill)


def set_cell_borders(cell):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
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
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def add_table(slide, x, y, widths, rows, heights, kinds, size=12):
    shape = slide.shapes.add_table(
        len(rows), len(widths), Inches(x), Inches(y), Inches(sum(widths)), Inches(sum(heights))
    )
    table = shape.table
    table.horz_banding = False
    table.vert_banding = False
    tbl = shape._element.graphic.graphicData.tbl
    tbl_pr = tbl.tblPr
    for child in list(tbl_pr):
        if child.tag == qn("a:tableStyleId"):
            tbl_pr.remove(child)
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    style = {
        "head": (NAVY, WHITE, True),
        "body": (WHITE, INK, False),
        "key": (PALE, TEAL, True),
        "sum": (SOFT, NAVY, True),
    }
    for r, (row, h, kind) in enumerate(zip(rows, heights, kinds)):
        table.rows[r].height = Inches(h)
        fill, color, bold = style[kind]
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            set_cell_fill(cell, NAVY if kind == "head" else (fill if c else SOFT))
            set_cell_borders(cell)
            this_bold = bold or c == 0
            this_color = WHITE if kind == "head" else (NAVY if c == 0 and kind == "body" else color)
            write_cell(cell, text, size, this_bold, this_color, PP_ALIGN.LEFT)
    return shape


def chrome(slide, page, title, kicker, total=5):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.42, 0.16, 10.4, 0.26, kicker, 12, True, ACCENT)
    textbox(slide, 0.42, 0.40, 12.5, 0.40, title, 24, True, NAVY)
    textbox(slide, 11.3, 0.16, 1.6, 0.26, f"{page}  /  {total}", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(
        slide,
        0.42,
        7.22,
        12.5,
        0.22,
        "配置 2    ·    10T 外推    ·    一份模型 128 卡    ·    访存与通信取峰值 80%    ·    专家 GEMM 用 FP4，注意力用 FP8",
        11,
        False,
        MUTED,
    )


def card(slide, x, y, w, h, kicker, value, note):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, PALE)
    textbox(slide, x + 0.16, y + 0.10, w - 0.32, 0.26, kicker, 12, True, TEAL)
    textbox(slide, x + 0.16, y + 0.38, w - 0.32, 0.48, value, 26, True, NAVY)
    textbox(slide, x + 0.16, y + 0.92, w - 0.32, h - 1.04, note, 12, False, INK, anchor=MSO_ANCHOR.TOP)


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def sec(v):
    if v >= 1:
        return f"{v:.2f} 秒"
    ms = v * 1e3
    if ms < 0.05:
        return "<0.1 毫秒"
    return f"{ms:.1f} 毫秒"


def build():
    s_max = max_input()
    p_max = prefill_one(s_max)
    p_4k = prefill_one(4096)
    p_1m = prefill_one(1048576)
    lengths = (4096, 131072, 1048576, int(s_max))
    rows_bs = []
    for s in lengths:
        b10 = search_bs(s, 0.01)
        b30 = search_bs(s, 0.03)
        rows_bs.append((s, hbm_cap(s), b10, b30, decode(b10, s), decode(b30, s)))
    d10 = decode(784, 4096)
    d30 = decode(4688, 4096)
    pf_4k = max_prefill_bs(4096)
    pf_1m = max_prefill_bs(1048576)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "10T DeepSeek 配置2：TTFT 10秒与 TPOT"
    blank = prs.slide_layouts[6]

    # ----- 1 conclusion -----
    s = prs.slides.add_slide(blank)
    chrome(s, 1, "两个时延目标都能在一份 128 卡副本上达到", "10T DeepSeek    ·    配置 2")
    textbox(
        s, 0.42, 1.00, 12.5, 0.36,
        "TTFT 和 TPOT 分开算。最大输入由单条请求的 10 秒 TTFT 决定，两个目标共用这个输入。全局批由 Decode 的 TPOT 决定。",
        14, False, INK,
    )
    card(
        s, 0.42, 1.50, 4.05, 2.05,
        "最大输入    ·    TTFT = 10.0 秒",
        "6.54×10⁶",
        "单条、无前缀命中。\n6,535,920 token。\n4K 单条只要 6.1 毫秒。",
    )
    card(
        s, 4.64, 1.50, 4.05, 2.05,
        "TPOT ≤ 10 毫秒",
        "全局批 784",
        "每卡 6.1 条。\n4K 到 1M 都是这个批。\n一份副本 7.86×10⁴ token/s。",
    )
    card(
        s, 8.86, 1.50, 4.05, 2.05,
        "TPOT ≤ 30 毫秒",
        "全局批 4688",
        "每卡 36.6 条。\n约 70 万 token 以内不变。\n一份副本 1.56×10⁵ token/s。",
    )
    add_table(
        s, 0.42, 3.72, [2.3, 3.4, 3.4, 3.4],
        [
            ["输入", "HBM 能放", "10 毫秒全局批", "30 毫秒全局批"],
            ["4K", "67.2 万条", "784    每卡 6.1", "4688    每卡 36.6"],
            ["128K", "2.55 万条", "784    每卡 6.1", "4688    每卡 36.6"],
            ["1M", "3207 条", "784    每卡 6.1", "3502    每卡 27.4"],
            ["6.54×10⁶", "514 条", "523    每卡 4.1", "564    每卡 4.4"],
        ],
        [0.36, 0.40, 0.40, 0.40, 0.42],
        ["head", "body", "body", "body", "key"],
    )
    textbox(
        s, 0.42, 6.20, 12.5, 0.84,
        "6.54×10⁶ 这一档，10 毫秒和 30 毫秒的批落到 HBM 容量附近：HBM 放 514 条，多出来的工作集走 H2D。\n"
        "4K、命中 90% 时，同一份副本在 10 秒内还能同时做 3964 条 Prefill。Prefill 与 Decode 的副本数按到达率另配。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    notes(
        s,
        "\n".join([
            f"Smax={s_max:.0f}, t={p_max['t']:.4f}",
            f"4K TTFT={p_4k['t']*1e3:.2f} ms, 1M TTFT={p_1m['t']:.3f} s",
            f"prefill bs 4K/90%={pf_4k}, 1M/90%={pf_1m}",
            f"10ms @4K t={d10['t']*1e3:.2f} ar={d10['t_ar']*1e3:.2f} tw={d10['tw']*1e3:.2f}",
            f"30ms @4K t={d30['t']*1e3:.2f} ar={d30['t_ar']*1e3:.2f} tw={d30['tw']*1e3:.2f}",
        ]),
    )

    # ----- 2 hardware -----
    s = prs.slides.add_slide(blank)
    chrome(s, 2, "链路按 Gb/s 换算，算力按精度拆开", "硬件    ·    配置 2")
    add_table(
        s, 0.42, 1.05, [2.6, 3.3, 3.3, 3.3],
        [
            ["项目", "给出的峰值", "80% 后参与计时", "用在哪"],
            ["专家 GEMM", "7 P @ FP4", "7.00×10¹⁵ FLOP/s", "路由专家和共享专家"],
            ["注意力", "FP4 的一半，FP8", "3.50×10¹⁵ FLOP/s", "indexer、HCA、稀疏注意力、投影"],
            ["HBM", "180 GB，9 TB/s", "带宽 7.2 TB/s", "权重和驻留 KV"],
            ["H2D", "每卡单向 800 Gb/s", "80 GB/s", "主机到卡"],
            ["D2D", "每卡单向 400 Gb/s", "40 GB/s", "128 卡超节点上的专家 EP"],
            ["机内 P2P", "16 卡 fullmesh，400 Gb/s", "40 GB/s", "注意力 TP=16 的 allreduce"],
            ["参数面", "400 Gb/s", "40 GB/s", "Prefill 把 KV 交给 Decode"],
            ["机器 DDR", "768 GB，1288.8 GB/s", "带宽 1031 GB/s", "16 卡一台，进卡再受 H2D 限制"],
        ],
        [0.34, 0.42, 0.42, 0.40, 0.40, 0.40, 0.40, 0.40, 0.44],
        ["head"] + ["body"] * 7 + ["sum"],
        size=12,
    )
    textbox(
        s, 0.42, 4.85, 12.5, 2.15,
        "400 Gb/s = 50 GB/s 峰值，有效 40 GB/s。800 Gb/s 有效 80 GB/s。\n"
        "进卡的换入带宽取较慢的一条：H2D 80 GB/s，单卡分到的 DDR 为 1031/16 = 64.4 GB/s，所以按 64.4 GB/s。\n"
        "128 卡 = 8 台 16 卡机器。注意力 TP=16、DP=8，留在机内 fullmesh。2469 个专家 EP=128，走 D2D。每卡 FP4 路由权重 38.9 GB，KV 余量 16.63 TB。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    notes(
        s,
        "FP8 peak is FP4/2, the same ratio as Ascend 950 MXFP4 vs FP8. "
        "Attention weights in the 10T model are FP8 (19.35 GB). "
        f"ROOM={ROOM/1e12:.3f} TB, SPILL={SPILL/1e9:.2f} GB/s, "
        f"routed/GPU={ROUTED/N/1e9:.2f} GB, attn/GPU={ATTN/TP/1e9:.2f} GB.",
    )

    # ----- 3 max input -----
    s = prs.slides.add_slide(blank)
    chrome(s, 3, "10 秒输入停在 6.54×10⁶，停在 indexer 和 HCA", "Prefill    ·    单条    ·    TTFT ≤ 10 秒")
    add_table(
        s, 0.42, 1.05, [2.5, 5.6, 2.2, 2.2],
        [
            ["这一笔", "算法", "6.54×10⁶", "4K"],
            ["CSA indexer", "30 层 × 2048 × S² / (128 × 3.50×10¹⁵)", sec(p_max["idx"]), sec(p_4k["idx"])],
            ["HCA", "31 层 × 1024 × S² / 同一 FP8 算力", sec(p_max["hca"]), sec(p_4k["hca"])],
            ["稀疏注意力", "每 token 1024 条压缩 KV + 128 滑窗", sec(p_max["core"]), sec(p_4k["core"])],
            ["投影", "每 token 3.87×10¹⁰ FLOP，FP8", sec(p_max["proj"]), sec(p_4k["proj"])],
            ["专家 GEMM", "每 token 5.64×10¹⁰ FLOP，FP4 的 7 P", sec(p_max["moe"]), sec(p_4k["moe"])],
            ["读权重", "每卡 38.9 + 4.03 + 1.21 GB / 7.2 TB/s", sec(p_max["tw"]), sec(p_4k["tw"])],
            ["送 KV", "S × 4939.5 字节 / (128 × 40 GB/s)", sec(p_max["ship"]), sec(p_4k["ship"])],
            ["合计", "计算与读权重取较长的一项，再加送 KV", "10.00 秒", "6.1 毫秒"],
        ],
        [0.34, 0.44, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.40],
        ["head"] + ["body"] * 7 + ["key"],
        size=12,
    )
    textbox(
        s, 0.42, 4.95, 12.5, 2.05,
        "S² 两项合计 8.89 秒，线性项 1.11 秒。读权重 6.1 毫秒，送 KV 6.3 毫秒，都不改变这个长度。\n"
        "1M 单条 TTFT 是 0.41 秒。若注意力按 BF16、算力再减半到 1.75 P，同一公式的最大输入是 4.58×10⁶。本页按 FP8 计。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    notes(s, f"Smax={s_max:.3f}. 1M t={p_1m['t']:.4f}. BF16-attn sensitivity computed separately as 4.581e6.")

    # ----- 4 decode table -----
    s = prs.slides.add_slide(blank)
    chrome(s, 4, "短上下文的批不随长度变，约 80 万 token 后 30 毫秒先降", "Decode    ·    TPOT ≤ 10 毫秒 与  30 毫秒")
    body = []
    kinds = ["head"]
    labels = {4096: "4K", 131072: "128K", 1048576: "1M", int(s_max): "6.54×10⁶"}
    for s_len, cap, b10, b30, p10, p30 in rows_bs:
        body.append([
            labels[s_len],
            f"{cap:,}",
            f"{b10:,}",
            f"{b10 / N:.1f}",
            f"{p10['t'] * 1e3:.1f} 毫秒",
            f"{b30:,}",
            f"{b30 / N:.1f}",
            f"{p30['t'] * 1e3:.1f} 毫秒",
        ])
        kinds.append("key" if s_len in (4096, int(s_max)) else "body")
    add_table(
        s, 0.42, 1.10,
        [1.5, 1.5, 1.5, 1.2, 1.7, 1.6, 1.3, 1.7],
        [["输入", "HBM 条数", "10ms 批", "每卡", "这一步", "30ms 批", "每卡", "这一步"]] + body,
        [0.40, 0.48, 0.48, 0.48, 0.52],
        kinds,
        size=13,
    )
    textbox(
        s, 0.42, 4.00, 12.5, 2.95,
        "一步时间 = 注意力阶段 + 专家阶段，两段相加，沿用上一份 10T 时延模型。\n"
        "4K、全局批 784：注意力阶段是机内 allreduce 4.02 毫秒，专家阶段是读权重 5.96 毫秒，合计 10.0 毫秒。专家 GEMM 0.10 毫秒，D2D 上的 EP 0.80 毫秒。\n"
        "4K、全局批 4688：allreduce 24.0 毫秒，读权重仍是 5.96 毫秒，相加 30.0 毫秒。EP 4.8 毫秒，还没有超过 allreduce。\n"
        "每卡 19.3 个专家在批到几百条时都被命中，读权重就停在 5.96 毫秒，不再随批变大。批再加大，只把 allreduce 拉长。\n"
        "1M 的 30 毫秒批降到 3502，是因为 4688 条的存量超出 16.63 TB，溢出部分经 64.4 GB/s 的 H2D 读，这一笔变成 24 毫秒。10 毫秒在 1M 仍是 784，KV 读只有 0.57 毫秒。",
        14, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    notes(
        s,
        "\n".join(
            f"S={s_len} cap={cap} b10={b10} t10={p10['t']:.4f} ar={p10['t_ar']:.4f} "
            f"h2d={p10['t_h2d']:.4f} b30={b30} t30={p30['t']:.4f} h2d30={p30['t_h2d']:.4f}"
            for s_len, cap, b10, b30, p10, p30 in rows_bs
        ),
    )

    # ----- 5 binding and PD -----
    s = prs.slides.add_slide(blank)
    chrome(s, 5, "批停在机内 allreduce，副本数按到达率再配", "为什么是这个批    ·    Prefill 与 Decode 分开布")
    add_table(
        s, 0.42, 1.05, [2.4, 5.05, 5.05],
        [
            ["", "TPOT 10 毫秒，批 784", "TPOT 30 毫秒，批 4688"],
            ["机内 allreduce", "4.02 毫秒", "24.0 毫秒"],
            ["读专家权重", "5.96 毫秒", "5.96 毫秒"],
            ["专家 GEMM", "0.10 毫秒", "0.51 毫秒"],
            ["D2D 上的 EP", "0.80 毫秒", "4.8 毫秒"],
            ["相加", "9.98 毫秒", "30.0 毫秒"],
        ],
        [0.36, 0.40, 0.40, 0.40, 0.40, 0.42],
        ["head", "body", "body", "body", "body", "key"],
    )
    textbox(
        s, 0.42, 3.55, 12.5, 1.15,
        "allreduce 走 16 卡 fullmesh。TP=16、DP=8，每层字节是 2×(15/16)×⌈全局批/8⌉×7168×2，61 层除以 40 GB/s。\n"
        "D2D 有效只有 40 GB/s，但这个批上的 EP 仍短于 allreduce。把 D2D 加宽，10 毫秒和 30 毫秒的批不会先变大。要加批，得缩短机内 allreduce，或让两段在时间上叠起来。",
        14, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    add_table(
        s, 0.42, 4.85, [3.2, 3.1, 3.1, 3.1],
        [
            ["4K、输出 512、命中 90%", "Prefill 请求/秒", "Decode 请求/秒", "副本比 P:D"],
            ["TPOT 10 毫秒", "396", "153", "1 : 2.6"],
            ["TPOT 30 毫秒", "396", "305", "1 : 1.3"],
        ],
        [0.38, 0.42, 0.42],
        ["head", "body", "key"],
    )
    textbox(
        s, 0.42, 6.20, 12.5, 0.82,
        "一份 128 卡副本的 Prefill，在 10 秒、4K、90% 命中下是 3964 条、396 请求/秒。Decode 按上面的批和 TPOT 出 token，再除以 512。\n"
        "节点数可以按这个比加副本。单副本的 TTFT 和 TPOT 不随副本数变化。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    notes(
        s,
        "Decode req/s at 10ms = 784/0.00998/512. At 30ms = 4688/0.02998/512. "
        f"Prefill req/s = {pf_4k}/10.",
    )

    out = "/workspace/docs/10t-hw2-slo.pptx"
    prs.save(out)
    print("wrote", out)
    print("Smax", round(s_max), "pf4k", pf_4k, "pf1m", pf_1m)
    for item in rows_bs:
        print(item[0], item[1], item[2], item[3])


if __name__ == "__main__":
    build()
