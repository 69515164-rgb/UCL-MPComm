#!/usr/bin/env python3
"""One slide on Sandisk's August 13, 2026 Investor Day HBF simulation.

The comparison freezes GPU performance, on-package bandwidth, GPU-to-GPU
bandwidth, and the LPDDR spill path. Capacity is the only difference:
4 TB HBF versus 192 GB HBM. Claims are Sandisk's internal test, not a
third-party silicon measurement.
"""

from __future__ import annotations

from pathlib import Path

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
LINE = "D6DCE2"
SOFT = "F4F7FA"
HEAD = "0E2A47"
WHITE = "FFFFFF"
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"

OUT = Path(__file__).resolve().parent / "sandisk-hbf-sim.pptx"


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


def set_cell_fill(cell, hex_color):
    tc_pr = cell._tc.get_or_add_tcPr()
    for old in tc_pr.findall(qn("a:solidFill")):
        tc_pr.remove(old)
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", hex_color)
    solid_fill.append(srgb)
    tc_pr.append(solid_fill)


def set_cell_borders(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", "6350")
        fill = OxmlElement("a:solidFill")
        color = OxmlElement("a:srgbClr")
        color.set("val", LINE)
        fill.append(color)
        ln.append(fill)
        tc_pr.append(ln)


def write_cell(cell, text, size, bold, color):
    cell.text = ""
    tf = cell.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Emu(70000)
    tf.margin_right = Emu(50000)
    tf.margin_top = Emu(20000)
    tf.margin_bottom = Emu(20000)
    body = getattr(tf, "_txBody", None)
    if body is not None:
        body_pr = body.find(qn("a:bodyPr"))
        if body_pr is not None:
            body_pr.set("anchor", "ctr")
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def add_table(slide, x, y, widths, rows, height):
    shape = slide.shapes.add_table(len(rows), len(widths), Inches(x), Inches(y), Inches(sum(widths)), Inches(height * len(rows)))
    table = shape.table
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    for r, row in enumerate(rows):
        table.rows[r].height = Inches(height)
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            head = r == 0
            set_cell_fill(cell, HEAD if head else (SOFT if c == 0 else WHITE))
            set_cell_borders(cell)
            color = WHITE if head else (NAVY if c == 0 else INK)
            write_cell(cell, text, 12, head or c == 0, color)
    return shape


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Sandisk HBF：容量带来的 GPU 规模和成本"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(
        slide,
        0.36,
        0.14,
        12.6,
        0.24,
        "Sandisk Investor Day    2026-08-13    ·    内部仿真    ·    HBF Only 对 HBM Only",
        12,
        True,
        ACCENT,
    )
    textbox(slide, 0.36, 0.38, 12.6, 0.40, "容量单独把 GPU 规模拉开：最少 8 张降到 1 张", 24, True, NAVY)

    cards = [
        (PALE, TEAL, "最少可运行配置", "8×", "1 张 HBF 对 8 张 HBM\nSandisk 称为 capex efficiency"),
        (GOLD_BG, GOLD, "同样的 token 输出", "2×", "4 张 HBF = 8 张 HBM\nSandisk 称为 GPU efficiency"),
        (SOFT, NAVY, "仿真里唯一的变量", "21×", "4 TB 对 192 GB\n算力、带宽、溢出口都相同"),
    ]
    for i, (fill, num_color, cap, num, body) in enumerate(cards):
        x = 0.36 + i * 4.30
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(0.90), Inches(4.16), Inches(1.42))
        solid(card, fill, LINE)
        textbox(slide, x + 0.16, 0.96, 3.84, 0.22, cap, 12, True, MUTED)
        textbox(slide, x + 0.16, 1.16, 3.84, 0.42, num, 26, True, num_color)
        textbox(slide, x + 0.16, 1.60, 3.84, 0.60, body, 13, False, INK, anchor=MSO_ANCHOR.TOP)

    textbox(slide, 0.36, 2.46, 6.2, 0.26, "两边锁死的条件", 14, True, NAVY)
    add_table(
        slide,
        0.36,
        2.76,
        [1.70, 4.35],
        [
            ["项目", "HBF 与 HBM 取同一值"],
            ["单卡算力", "4.5 PFLOPS"],
            ["片上带宽", "12.8 TB/s"],
            ["卡间带宽", "900 GB/s"],
            ["KV 溢出", "128 GB/s，接到 LPDDR"],
            ["模型", "Qwen3-480B-A35B"],
            ["权重", "960 GB，BF16"],
            ["负载", "多轮 agent，到达间隔对数正态"],
        ],
        0.36,
    )

    read = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.70), Inches(2.76), Inches(6.26), Inches(2.88))
    solid(read, SOFT, LINE)
    textbox(slide, 6.88, 2.88, 5.92, 0.26, "这组数字在说什么", 14, True, NAVY)
    textbox(
        slide,
        6.88,
        3.20,
        5.92,
        2.28,
        "960 GB 权重正好是 5 张 192 GB。\n"
        "仿真给出的最少配置却是 8 张，\n"
        "只把权重大切开还不够这次多轮负载。\n"
        "4 TB 放下 960 GB 后还剩约 3 TB，\n"
        "一张卡就能留下权重和 KV。\n"
        "溢出口 128 GB/s，是片上带宽的 1/100。\n"
        "HBM 的 KV 离开封装后，token 输出被这条口卡住。\n"
        "480B 里每次约激活 35B。算力按小的那份走，\n"
        "显存要放下全部专家。多出的卡是在为容量值班。",
        13,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )

    note = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.36), Inches(5.82), Inches(12.60), Inches(1.22))
    solid(note, PALE, LINE)
    textbox(
        slide,
        0.52,
        5.94,
        12.28,
        0.98,
        "8× 是最少能跑起来的卡数，1 张对 8 张。2× 是同样 token 输出的卡数，4 张对 8 张。两者都是 GPU 张数。\n"
        "产品口径另写容量是 HBM 的 8 到 16 倍、成本相近。这次仿真用的容量比是 4 TB / 192 GB，约 21 倍，高于那个产品口径。\n"
        "比较的是 HBF Only。算力和读带宽被设成与 HBM 相同，所以收益来自容量把权重和 KV 留在封装里。",
        13,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )

    textbox(
        slide,
        0.36,
        7.14,
        12.6,
        0.26,
        "来源：Sandisk 2026 Investor Day，HBF vs HBM Simulation。标注 Based on internal testing。未公布 token/s 坐标。",
        11,
        False,
        MUTED,
    )

    slide.notes_slide.notes_text_frame.text = (
        "Sandisk Investor Day, August 13, 2026. Slides HBF vs HBM Simulation Configurations "
        "and HBF vs HBM Performance Comparison for AI Inference.\n"
        "Locked: 4.5 PFLOPS, 12.8 TB/s, 900 GB/s GPU-to-GPU, 128 GB/s LPDDR spill.\n"
        "Capacity: 4 TB HBF vs 192 GB HBM. Model Qwen3-480B-A35B, 960 GB BF16.\n"
        "8x capex efficiency = minimum configuration, 1 HBF GPU vs 8 HBM GPUs.\n"
        "2x GPU efficiency = 4 HBF GPUs match the token output of 8 HBM GPUs.\n"
        "960/192 = 5 exactly for weights alone. 4 TB - 0.96 TB = 3.04 TB headroom. "
        "12.8 TB/s / 128 GB/s = 100. Active parameters are the model's published 35B."
    )
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
