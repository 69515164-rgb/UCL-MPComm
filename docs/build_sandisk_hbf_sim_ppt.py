#!/usr/bin/env python3
"""One slide on Sandisk's August 13, 2026 Investor Day HBF simulation.

Pages 87 and 88 are the published slides, placed as images. The reading
under them is ours: capacity is the only input that differs.
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

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "sandisk-hbf-sim.pptx"
PAGE_87 = ROOT / "images" / "sandisk" / "investor-day-p-87.png"
PAGE_88 = ROOT / "images" / "sandisk" / "investor-day-p-88.png"


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

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.06))
    solid(bar, ACCENT)
    textbox(
        slide,
        0.32,
        0.10,
        9.6,
        0.22,
        "原图取自 Sandisk Investor Day 2026-08-13 第 87、88 页    ·    内部仿真",
        12,
        True,
        ACCENT,
    )
    textbox(slide, 0.32, 0.32, 12.7, 0.34, "容量单独把 GPU 规模拉开：最少 8 张降到 1 张", 22, True, NAVY)

    # Source pages are 960×540. Keep that ratio.
    img_w, img_h = 6.22, 6.22 * 540 / 960
    y_img = 1.02
    slide.shapes.add_picture(str(PAGE_87), Inches(0.36), Inches(y_img), Inches(img_w), Inches(img_h))
    slide.shapes.add_picture(str(PAGE_88), Inches(0.36 + img_w + 0.16), Inches(y_img), Inches(img_w), Inches(img_h))
    cap_y = y_img + img_h + 0.02
    textbox(slide, 0.36, cap_y, img_w, 0.20, "第 87 页  仿真配置", 11, False, MUTED, PP_ALIGN.CENTER)
    textbox(slide, 0.36 + img_w + 0.16, cap_y, img_w, 0.20, "第 88 页  token 输出和两套倍数", 11, False, MUTED, PP_ALIGN.CENTER)

    cards = [
        (
            "唯一拉开结果的是容量",
            "算力 4.5 PFLOPS、片上 12.8 TB/s、卡间 900 GB/s、溢出 128 GB/s，两边相同。不同的是 4 TB 对 192 GB，约 21 倍。4 TB 放下 960 GB 后还剩约 3 TB。",
        ),
        (
            "右图里的 8× 和 2×",
            "8× 是最少能跑起来的卡数，1 张对 8 张。2× 是同样 token 输出：绿线 4 张 HBF 与蓝线 8 张 HBM 叠在一起。黄线是 1 张，能跑，输出更低。",
        ),
        (
            "卡数由容量决定",
            "960 GB 权重正好 5 张 192 GB，最少配置仍是 8 张。溢出口是片上带宽的 1/100，KV 离开封装后 token 被卡住。每次约激活 35B，多出的卡在为容量值班。",
        ),
    ]
    card_y = cap_y + 0.24
    card_h = 1.78
    for i, (title, body) in enumerate(cards):
        x = 0.32 + i * 4.32
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(card_y), Inches(4.18), Inches(card_h))
        solid(card, PALE if i == 1 else SOFT, LINE)
        textbox(slide, x + 0.14, card_y + 0.08, 3.90, 0.28, title, 13, True, NAVY, anchor=MSO_ANCHOR.TOP)
        textbox(slide, x + 0.14, card_y + 0.40, 3.90, card_h - 0.50, body, 13, False, INK, anchor=MSO_ANCHOR.TOP)

    textbox(
        slide,
        0.32,
        card_y + card_h + 0.06,
        12.7,
        0.22,
        "两套倍数都是 GPU 张数。产品口径另写容量为 HBM 的 8 到 16 倍、成本相近。比较的是 HBF Only，标注 Based on internal testing。",
        11,
        False,
        MUTED,
    )

    slide.notes_slide.notes_text_frame.text = (
        "Images are pages 87 and 88 of the Sandisk Investor Day 2026 presentation, "
        "13 August 2026, 98 pages, 960×540 pt.\n"
        "8x is the minimum configuration. 2x is equal token output. "
        "The chart axis is tokens per second versus elapsed time; this slide does not read numbers off that axis."
    )
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
