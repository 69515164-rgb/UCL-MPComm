#!/usr/bin/env python3
"""Editable deck: GLM-5.3 extrapolated to 10T, TTFT 10s / TPOT 10ms / 30ms."""

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


def rgb(hex_color):
    h = hex_color
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


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
        bodyPr = body.find(qn("a:bodyPr"))
        if bodyPr is not None:
            bodyPr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
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
    tcPr = tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag == qn("a:solidFill"):
            tcPr.remove(child)
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", hex_color)
    solid_fill.append(srgb)
    tcPr.append(solid_fill)


def set_cell_borders(cell, hex_color="D6DCE2", width="6350"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        for child in list(tcPr):
            if child.tag == qn(f"a:{edge}"):
                tcPr.remove(child)
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", width)
        fill = OxmlElement("a:solidFill")
        srgb = OxmlElement("a:srgbClr")
        srgb.set("val", hex_color)
        fill.append(srgb)
        ln.append(fill)
        tcPr.append(ln)


def write_cell(cell, text, size, bold, color, align):
    tf = cell.text_frame
    tf.clear()
    tf.word_wrap = True
    cell.margin_left = Inches(0.08)
    cell.margin_right = Inches(0.08)
    cell.margin_top = Inches(0.04)
    cell.margin_bottom = Inches(0.03)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, line in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        pPr = p._p.get_or_add_pPr()
        ln_spc = OxmlElement("a:lnSpc")
        spc = OxmlElement("a:spcPct")
        spc.set("val", "100000")
        ln_spc.append(spc)
        pPr.append(ln_spc)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def add_table(slide, x, y, widths, rows, heights, kinds):
    """kinds: head / body / key / sum, one per row."""
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
            write_cell(cell, text, 12 if kind != "head" else 12, this_bold, this_color, align)
    return shape


def chrome(slide, page, title, kicker, total=5):
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
        "GLM-5.3 外推到 10T    ·    128 卡副本    ·    权重 FP8    ·    带宽取峰值 80%    ·    Cube 16 行对齐",
        11,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )


def banner(slide, y, text):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(y), Inches(12.5), Inches(0.48))
    solid(shape, PALE)
    textbox(slide, 0.58, y, 12.18, 0.48, text, 14, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)


import math


H = 6144
D_MOE = 2048
L = 78
L_MOE = 75
L_DENSE = 3
N_INDEX = 21
TOPK = 8
E0 = 256
E10 = 3526
N = 128
TP = 8
DP = N // TP
MLA = 165_019_648
IDX_P = 9_371_648
EXPERT = 3 * H * D_MOE
ONE = EXPERT * L_MOE
DENSE = 3 * H * 12288
ATTN = L * MLA + N_INDEX * IDX_P
VOCAB = 154880
REST = L_DENSE * DENSE + ONE + ATTN + 2 * VOCAB * H  # shared expert is ONE
PEAK = 486e12
HBM = 4e12 * 0.80
BUS = 400e9 * 0.80
P2P = 50e9 * 0.80
PARAM = 50e9 * 0.80
H2D = 64e9 * 0.80
BPT = L * 576 + N_INDEX * 132
LOCAL_DDR = 12.288e12


def align(M):
    return 1.0 if M <= 0 else M / (math.ceil(M / 16.0) * 16)


def store_seq(S):
    return BPT * S


def read_seq(S):
    return N_INDEX * 132 * S + L * min(2048, S) * 576


def room_bytes():
    routed = E10 * ONE
    return N * (96e9 - routed / N - ONE - L_DENSE * DENSE - ATTN / TP - 6e9)


def prefill(S, hit=0.9):
    q = S * (1 - hit)
    sel = min(2048, S)
    idx = N_INDEX * 8192 * q * S
    core = L * 65536 * sel * q
    moe = 2 * (TOPK + 1) * ONE * q
    den = 2 * DENSE * L_DENSE * q
    proj = 2 * ATTN * q
    ua = align(max(q / N, 1e-9))
    ue = align(q * TOPK / E10)
    tc = ((idx + core + proj) / ua + moe / ue + den) / (N * PEAK)
    tw = (E10 * ONE / N + ONE + L_DENSE * DENSE + ATTN / TP) / HBM
    tkv = hit * store_seq(S) / (N * PARAM)
    return {
        "tc": tc,
        "tw": tw,
        "tkv": tkv,
        "tt": tkv + max(tc, tw),
        "idx": idx / ua / (N * PEAK),
        "core": core / ua / (N * PEAK),
        "moe": moe / ue / (N * PEAK),
        "den": den / (N * PEAK),
        "proj": proj / ua / (N * PEAK),
    }


def decode(BS, S):
    frac = 1 - math.exp(-TOPK * BS / E10)
    e = E10 / N
    std = math.sqrt(max(e * frac * (1 - frac), 0.0))
    e_hot = min(e, e * frac + 2 * std)
    tok = (BS * TOPK / E10) / frac if frac > 1e-9 else 1.0
    ue, ua = align(tok), align(BS / DP)
    sel = min(2048, S)
    score = N_INDEX * 8192 * S + L * 65536 * sel
    proj = 2 * ATTN
    moe_f = 2 * (TOPK + 1) * ONE
    tw = (e_hot * ONE + ONE) / HBM
    room = room_bytes()
    total = BS * store_seq(S)
    hbm_b = min(total, room)
    loc_b = max(total - room, 0.0)
    f_l = loc_b / total if total else 0.0
    read_gpu = BS * read_seq(S) / N
    t_kh = read_gpu * (1 - f_l) / HBM
    t_h2d = read_gpu * f_l / H2D
    t_wa = (ATTN / TP) / HBM
    t_ca = BS * (score + proj) / (N * PEAK * ua)
    t_cm = BS * moe_f / (N * PEAK * ue)
    pairs = (e_hot / e) * (BS * TOPK / N)
    t_ep = pairs * 2 * H * L_MOE / BUS
    toks = math.ceil(BS / DP)
    t_ar = 2 * (TP - 1) / TP * (toks * H * 2) * L / P2P
    t_attn = max(t_ca, t_kh + t_wa, t_h2d, t_ar)
    t_moe = max(t_cm, tw, t_ep)
    return {
        "t": t_attn + t_moe,
        "w": tw,
        "cm": t_cm,
        "ar": t_ar,
        "ca": t_ca,
        "kh": t_kh,
        "wa": t_wa,
        "h2d": t_h2d,
        "ep": t_ep,
        "fl": f_l,
        "frac": frac,
        "ehot": e_hot,
        "ue": ue,
    }


def search(S, limit):
    cap = int((room_bytes() + LOCAL_DDR) // store_seq(S))
    lo, hi, best = 1, cap, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if decode(mid, S)["t"] <= limit:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def sweep():
    rows = []
    room = room_bytes()
    for S in (4096, 8192, 32768, 131072, 262144, 524288, 1048576):
        b10, b30 = search(S, 0.01), search(S, 0.03)
        rows.append(
            {
                "S": S,
                "store": store_seq(S),
                "cap": int(room // store_seq(S)),
                "b10": b10,
                "b30": b30,
                "spill": decode(b30, S)["fl"],
            }
        )
    return rows


def fmt_len(S):
    if S >= 1048576:
        return "1M"
    return f"{S // 1024}K"


def fmt_bytes(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB"


def fmt_count(n):
    if n >= 10000:
        v = n / 10000
        return f"{v:.1f} 万" if v >= 10 else f"{v:.2f} 万"
    return str(n)


def sec(v):
    return f"{v:.2f} 秒" if v < 9.5 else f"{v:.1f} 秒"


def ms(v):
    return f"{v * 1e3:.1f} 毫秒" if v < 0.1 else f"{v * 1e3:.0f} 毫秒"


def chips(slide, y, items):
    width = 12.5
    gap = 0.15
    n = len(items)
    cw = (width - gap * (n - 1)) / n
    for i, (cap, num, sub) in enumerate(items):
        x = 0.42 + i * (cw + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(cw), Inches(1.50))
        solid(card, SOFT, LINE)
        textbox(slide, x + 0.12, y + 0.06, cw - 0.24, 0.24, cap, 12, True, MUTED)
        textbox(slide, x + 0.12, y + 0.30, cw - 0.24, 0.46, num, 26, True, TEAL)
        textbox(slide, x + 0.12, y + 0.80, cw - 0.24, 0.58, sub, 12, False, INK)


def main():
    rows_s = sweep()
    by = {r["S"]: r for r in rows_s}
    p1 = prefill(1048576)
    d10 = decode(by[4096]["b10"], 4096)
    d30 = decode(by[4096]["b30"], 4096)
    total10 = E10 * ONE + REST
    total53 = E0 * ONE + REST
    active = TOPK * ONE + ONE + L_DENSE * DENSE + ATTN
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "GLM-5.3 外推到 10T：结构与 TTFT / TPOT"
    blank = prs.slide_layouts[6]

    s1 = prs.slides.add_slide(blank)
    chrome(s1, 1, "同一骨架，只加路由专家", "GLM-5.3 发布权重    ·    外推到 10T")
    textbox(
        s1,
        0.42,
        0.90,
        12.5,
        0.32,
        "最新发布权重是 GLM-5.3，架构与 GLM-5.2 相同。官方口径 744B / 40B。10T 冻结层数、宽度和 top-8，只加路由专家。",
        14,
        False,
        INK,
    )
    rows = [
        ["项目", "GLM-5.3 发布权重", "10T 外推", "备注"],
        ["回推总参数", "7.433×10^11", "1.000×10^13", "不含 MTP。官方 744B，差额是 MTP 与舍入"],
        ["路由专家", "256", "3526", "×13.8。增量只记在专家个数上"],
        ["激活参数", "3.92×10^10", "3.92×10^10", "每 token 仍是 8 个路由专家 + 1 个共享"],
        ["激活比", "5.28%", "0.39%", "专家表变大，单 token 激活不变"],
        ["FP8 专家表", "0.725 TB", "9.983 TB", "单专家全层 2.831 GB。发布精度是 FP8"],
        ["层 / 隐藏 / 中间维", "78 / 6144 / 2048", "同左", "前 3 层稠密，后 75 层 MoE"],
        ["注意力", "MLA-256，DSA top-2048", "同左", "21 层有 indexer，每 4 层共享一次"],
        ["单 token 专家通信", "1.106×10^7 字节", "同左", "8 × 3 × 6144 × 75，与专家总数无关"],
        ["单 token KV", "47700 字节", "同左", "78×576 + 21×132，按 FP8 布局"],
    ]
    add_table(s1, 0.42, 1.26, [2.35, 2.85, 2.45, 4.85], rows, [0.34] + [0.46] * 9, ["head"] + ["body"] * 9)
    note = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.84), Inches(12.5), Inches(1.20))
    solid(note, GOLD_BG)
    textbox(
        s1,
        0.58,
        5.92,
        12.18,
        1.04,
        "外推式：总参数 = 专家数 × 2.831×10^9 + 1.860×10^10。单个专家 = 3 × 6144 × 2048 × 75。\n"
        "GLM-4.5 到 GLM-5：总参数约 ×2.1（355B 到 744B），激活 ×1.25（32B 到 40B），层数从 92 降到 78。增量主要进专家表。\n"
        "技术报告正文写 80 层，发布 config 是 78 层。外推跟权重。",
        13,
        False,
        GOLD,
    )
    s1.notes_slide.notes_text_frame.text = (
        f"GLM-5.3 config：78 层，隐藏 6144，moe 中间维 2048，256 路由专家，1 个共享，top-8，前 3 层稠密。"
        f"MLA：kv_lora 512 + rope 64 = 576，64 头，qk 256，v 256，q_lora 2048。"
        f"DSA：index_topk 2048，indexer 头 32、维 128。indexer_types 里 21 层为 full，其余 shared，即 IndexShare 每 4 层一次。"
        f"主干回推 {total53/1e9:.1f}B，激活 {active/1e9:.2f}B。官方口径 744B-A40B。"
        f"10T：E={E10}，总参数 {total10:.3e}。专家 FP8 字节等于参数个数，因为发布量化是 FP8 e4m3，不是 FP4。"
        "上下文窗口发布值为 1,048,576。词表 154880。"
    )

    s2 = prs.slides.add_slide(blank)
    chrome(s2, 2, "1M 的 TTFT 是 0.47 秒", "Prefill    ·    TTFT ≤ 10 秒    ·    KV 命中 90%")
    banner(
        s2,
        0.92,
        f"一条请求在一个 128 卡副本上。90% 的 KV 走参数面，只现算 10%。1M 现算 {sec(p1['tc'])}，读 KV {ms(p1['tkv'])}，读权重 {ms(p1['tw'])}。",
    )
    textbox(s2, 0.42, 1.46, 6, 0.26, "并行策略", 13, True, ACCENT)
    add_table(
        s2,
        0.42,
        1.74,
        [1.45, 5.45, 5.60],
        [
            ["", "Attention", "MoE"],
            ["并行", "机内 TP=8\nKV 按 token 切到 8 卡，16 个节点 DP", "超节点 EP=128\n3526 个专家，每卡 27.5 个"],
            ["通信域", "8 卡 fullmesh，有效 40 GB/s", "D2D 总线有效 320 GB/s\n命中的 KV 走参数面 40 GB/s"],
            ["每卡权重", "注意力 13.07 GB / 8\n= 1.63 GB FP8", "路由专家 78.0 GB FP8\n共享专家 2.83 GB，每卡一份"],
            ["这一阶段", "indexer 按 q × S\nq = 0.1 × S", "专家 GEMM 只作用在现算的 10% 上"],
        ],
        [0.30, 0.58, 0.62, 0.58, 0.56],
        ["head", "body", "body", "body", "body"],
    )
    textbox(s2, 0.42, 4.50, 8, 0.24, "1M、90% 命中，10 秒怎么还有余量", 13, True, ACCENT)
    add_table(
        s2,
        0.42,
        4.76,
        [1.70, 7.70, 3.10],
        [
            ["这一笔", "算法", "1M 时"],
            ["indexer", "21 层 × 8192 × q × S / (128×486×10^12)", sec(p1["idx"])],
            ["稀疏 MLA", "78 层，每个新 token 看 2048 条", sec(p1["core"])],
            ["专家 GEMM", "9 个专家 × 2.831×10^9 参数 × 2 × q", sec(p1["moe"])],
            ["投影 + 稠密层", "注意力投影和前 3 层稠密 MLP", sec(p1["proj"] + p1["den"])],
            ["读 KV", "0.9 × S × 47700 / (128 × 40×10^9)", ms(p1["tkv"])],
            ["合计", "先读 KV，再取现算和读权重里较长的一项", sec(p1["tt"])],
        ],
        [0.26, 0.26, 0.26, 0.26, 0.26, 0.26, 0.28],
        ["head", "body", "body", "body", "body", "body", "sum"],
    )
    s2.notes_slide.notes_text_frame.text = (
        "命中率 90% 是本轮假设。现算 token q = 0.1S，每个新 token 仍要看满整个 S。"
        "indexer 点积：32 头 × 128 维 × 2 = 8192 FLOP/对。只有 21 层真的算 indexer，其余 57 层复用 top-2048 下标。"
        "稀疏 MLA：64 头 × 256 维，QK 和 AV 合计每条 65536 FLOP，78 层都做，但每 token 只看 2048 条。"
        f"1M：indexer {p1['idx']:.3f}s，稀疏 {p1['core']:.3f}s，专家 {p1['moe']:.3f}s，投影 {p1['proj']:.3f}s，稠密 {p1['den']:.3f}s，现算 {p1['tc']:.3f}s。"
        f"参数面读 KV {p1['tkv']*1e3:.2f} ms，读权重 {p1['tw']*1e3:.1f} ms。TTFT {p1['tt']:.3f}s。"
        "4K 到 128K 时现算还没超过读权重，TTFT 约 26 毫秒。512K 为 0.16 秒，1M 为 0.47 秒。"
    )

    s3 = prs.slides.add_slide(blank)
    chrome(s3, 3, "10 毫秒、短输入，全局批 98", "Decode    ·    TPOT ≤ 10 毫秒")
    banner(
        s3,
        0.92,
        "10 毫秒里 9.5 毫秒在读被叫醒的专家。每卡 27.5 个专家全部叫醒要 25.3 毫秒，这一档做不到。注意力侧只有 0.5 毫秒。",
    )
    textbox(s3, 0.42, 1.46, 6, 0.24, "并行策略", 13, True, ACCENT)
    textbox(s3, 7.15, 1.46, 5.6, 0.24, "短输入（4K）、全局批 98，这一步怎么加", 13, True, ACCENT)
    add_table(
        s3,
        0.42,
        1.72,
        [1.15, 2.55, 2.70],
        [
            ["", "Attention", "MoE"],
            ["并行", "TP=8，DP=16\n每组 token 数 = BS / 16", "EP=128\n每卡 27.5 个专家"],
            ["通信", "每层机内 allreduce\n这一步 0.3 毫秒", "最忙卡 BF16 combine\n这一步 0.01 毫秒"],
            ["访存", "注意力权重 1.63 GB\n这一步 0.5 毫秒", "只读被命中的专家\n这一步 9.5 毫秒"],
            ["计算", "Cube 行数 = BS / 16\n不足 16 按 16 行砖", "每个命中专家约 1.1 个 token\n效率约 7%"],
        ],
        [0.28, 0.62, 0.58, 0.62, 0.62],
        ["head", "body", "body", "key", "body"],
    )
    add_table(
        s3,
        7.05,
        1.72,
        [1.20, 3.50, 1.15],
        [
            ["笔", "白话", "时间"],
            ["命中", "1 − exp(−8×98 / 3526) = 20%\n最忙卡按均值 + 2σ，约 9.7 个", "—"],
            ["读专家", "9.7 × 2.831 GB + 共享 2.83 GB\n除以 3.2 TB/s", "9.5 毫秒"],
            ["读注意力", "1.63 GB / 3.2 TB/s\n长于机内 allreduce 的 0.3 毫秒", "0.5 毫秒"],
            ["专家计算", "每个命中专家约 1.1 个 token\n16 行砖，效率 7%", "1.2 毫秒"],
            ["两路通信", "机内 allreduce 0.3 毫秒\n专家 combine 0.01 毫秒", "更短"],
            ["相加", "注意力侧取 0.5，专家侧取 9.5", "10.0 毫秒"],
        ],
        [0.28, 0.58, 0.56, 0.52, 0.50, 0.42, 0.42],
        ["head", "body", "key", "body", "body", "body", "sum"],
    )
    chips(
        s3,
        5.52,
        [
            ("4K", "98", "全局批\n每卡 0.8 条"),
            ("32K", "97", "全局批\n每卡 0.8 条"),
            ("128K", "96", "全局批\n每卡 0.8 条"),
            ("1M", "29", "全局批，每卡 0.2 条\n39% 经 H2D 读"),
        ],
    )
    s3.notes_slide.notes_text_frame.text = (
        f"BS 是 128 卡全局批。BS=98 时命中率 {d10['frac']:.3f}，最忙卡 {d10['ehot']:.2f} 个专家。"
        f"读权重 {d10['w']*1e3:.2f} ms，专家计算 {d10['cm']*1e3:.2f} ms，allreduce {d10['ar']*1e3:.2f} ms，"
        f"注意力权重 {d10['wa']*1e3:.2f} ms，合计 {d10['t']*1e3:.2f} ms。"
        "全部路由专家加共享专家 (78.0+2.83) GB / 3.2 TB/s = 25.3 ms，超过 10 ms。"
        "1M 时 HBM 只能放 17 条，10 毫秒的批是 29，多出来的 KV 走本卡 H2D 51.2 GB/s。"
    )

    s4 = prs.slides.add_slide(blank)
    chrome(s4, 4, "30 毫秒、短输入，全局批 1808", "Decode    ·    TPOT ≤ 30 毫秒")
    banner(
        s4,
        0.92,
        "专家可以全部叫醒，读权重停在 25.3 毫秒。剩下的预算被机内 8 卡 allreduce 用掉，4.7 毫秒。专家域通信只有 0.3 毫秒。",
    )
    textbox(s4, 0.42, 1.46, 6.2, 0.24, "并行策略    ·    和 10 毫秒同一份切分", 13, True, ACCENT)
    textbox(s4, 7.15, 1.46, 5.6, 0.24, "短输入、全局批 1808，这一步怎么加", 13, True, ACCENT)
    add_table(
        s4,
        0.42,
        1.72,
        [1.15, 2.55, 2.70],
        [
            ["", "Attention", "MoE"],
            ["并行", "仍是 TP=8，DP=16\n1808 / 16 = 113 条 / 组", "仍是 EP=128\n每卡 27.5 个专家全醒"],
            ["通信", "allreduce 随批线性涨\n这一档是注意力侧最长", "combine 走 320 GB/s\n0.3 毫秒，短于读权重"],
            ["访存", "4K 全在 HBM\n更长则走本卡 H2D", "78.0 GB 路由 + 2.83 GB 共享\n/ 3.2 TB/s = 25.3 毫秒"],
            ["计算", "注意力计算 1.2 毫秒\n短于 allreduce", "每专家约 4 个 token\n效率 26%，计算 5.7 毫秒"],
        ],
        [0.28, 0.62, 0.62, 0.62, 0.62],
        ["head", "body", "key", "body", "body"],
    )
    add_table(
        s4,
        7.05,
        1.72,
        [1.25, 3.45, 1.15],
        [
            ["笔", "白话", "时间"],
            ["读权重", "命中率 98%，27.5 个专家全读\n加共享专家，除以 3.2 TB/s", "25.3 毫秒"],
            ["机内通信", "每组 113 条 × 6144 × 2 字节\n78 层 × 2×7/8 / 40 GB/s", "4.7 毫秒"],
            ["专家计算", "1808 × 8 / 3526 ≈ 4 token / 专家\n对齐效率 26%", "5.7 毫秒"],
            ["专家通信", "最忙卡 combine / 320 GB/s", "0.3 毫秒"],
            ["注意力计算", "短输入的 indexer、稀疏 MLA 和投影", "1.2 毫秒"],
            ["相加", "注意力侧取 4.7，专家侧取 25.3", "30.0 毫秒"],
        ],
        [0.28, 0.56, 0.56, 0.52, 0.40, 0.46, 0.46],
        ["head", "key", "key", "body", "body", "body", "sum"],
    )
    chips(
        s4,
        5.52,
        [
            ("4K – 8K", "1808", "全局批，每卡 14.1 条\n全在 HBM"),
            ("32K", "760", "全局批，每卡 5.9 条\n26% 经 H2D 读"),
            ("128K", "314", "全局批，每卡 2.5 条\n55% 经 H2D 读"),
            ("1M", "66", "全局批，每卡 0.5 条\n73% 经 H2D 读"),
        ],
    )
    s4.notes_slide.notes_text_frame.text = (
        f"BS=1808，命中率 {d30['frac']:.3f}，读权重 {d30['w']*1e3:.2f} ms，allreduce {d30['ar']*1e3:.2f} ms，"
        f"专家计算 {d30['cm']*1e3:.2f} ms，注意力计算 {d30['ca']*1e3:.2f} ms，专家通信 {d30['ep']*1e3:.2f} ms，"
        f"合计 {d30['t']*1e3:.2f} ms。"
        "HBM 余量：每卡 96 − 78.0 − 2.83 − 1.63 − 0.68 − 6 = 6.87 GB，128 卡共 879 GB。"
        "KV 47700 字节/token。4K 一条约 195 MB，HBM 能放 4498 条，1808 条不用 DDR。"
        "溢出进 GPU 的口是本卡 H2D，64×0.8 = 51.2 GB/s。远端 DDR 也走这条 H2D。"
    )

    s5 = prs.slides.add_slide(blank)
    chrome(s5, 5, "1M 时 10 毫秒批 29，30 毫秒批 66", "Decode    ·    不同输入下的最大全局批")
    banner(
        s5,
        0.92,
        "全局批是 128 卡一份副本上的条数，每卡 = 全局批 / 128。HBM 放不下的 KV 走本卡 H2D，每卡 51.2 GB/s。远端 DDR 进卡也走这条 H2D。",
    )
    body, kinds = [], ["head"]
    for row in rows_s:
        spill = row["spill"]
        if spill < 0.01:
            where, kind = "全在 HBM", "body"
        else:
            where, kind = f"{spill * 100:.0f}% 经本卡 H2D", "key"
        kinds.append(kind)
        body.append(
            [
                fmt_len(row["S"]),
                fmt_bytes(row["store"]),
                fmt_count(row["cap"]),
                str(row["b10"]),
                f"{row['b10'] / 128:.1f}",
                str(row["b30"]),
                f"{row['b30'] / 128:.1f}",
                where,
            ]
        )
    add_table(
        s5,
        0.42,
        1.56,
        [1.15, 1.45, 1.45, 1.70, 1.05, 1.75, 1.05, 2.90],
        [["输入", "每条 KV", "HBM 能放", "10 毫秒全局批", "每卡", "30 毫秒全局批", "每卡", "30 毫秒的 KV 放哪"]] + body,
        [0.40] + [0.48] * len(body),
        kinds,
    )
    note = s5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(5.50), Inches(12.5), Inches(1.52))
    solid(note, GOLD_BG)
    textbox(
        s5,
        0.58,
        5.58,
        12.18,
        1.36,
        "每卡 KV 余量 = 96 − 78.0 − 2.83 − 1.63 − 0.68 − 6 = 6.87 GB，128 卡合计 879 GB。专家表按 FP8 占掉 78 GB。\n"
        "10 毫秒在 128K 及更短仍卡在读专家权重，全局批约 96–98。1M 时 HBM 只能放 17 条，批开到 29，多出来的走 H2D。\n"
        "30 毫秒在 8K 及更短是 1808，卡在读满专家 25.3 毫秒加机内 allreduce 4.7 毫秒。从 32K 起 HBM 先满。\n"
        "Prefill 按 90% KV 命中。4K 到 1M 的 TTFT 都在 10 秒内，1M 是 0.47 秒。",
        13,
        False,
        GOLD,
    )
    s5.notes_slide.notes_text_frame.text = (
        "存量 = S × 47700 字节。一步读取 = 21×132×S 的 indexer 扫描，加上 78×min(2048,S)×576 的稀疏 latent。"
        "按 1,048,576 token 计，存量 50.0 GB，一步 indexer 扫描 2.91 GB，稀疏部分 92 MB。"
        "通路并行，取最慢的一条，再加专家阶段。"
        "10 毫秒全局批：4K 98，8K 98，32K 97，128K 96，256K 82，512K 50，1M 29。"
        "30 毫秒全局批：4K 1808，8K 1808，32K 760，128K 314，256K 197，512K 117，1M 66。"
    )

    out = "/workspace/docs/glm-10t-slo.pptx"
    prs.save(out)
    print(out)
    print("total53", total53, "total10", total10, "active", active, "room GB", room_bytes() / 1e9)
    print("1M prefill", {k: round(p1[k], 4) for k in p1})
    for r in rows_s:
        print(r["S"], r["b10"], r["b30"], r["cap"], round(r["spill"], 3))


if __name__ == "__main__":
    main()
