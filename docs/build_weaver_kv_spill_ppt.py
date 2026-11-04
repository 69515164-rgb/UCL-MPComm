#!/usr/bin/env python3
"""One slide: Weaver spec comparison and the blog's KV-spill bandwidth cliff.

The chart is Credo's own figure from the 2026-10-02 blog
"Breaking the Memory Wall", rasterized from the published SVG.
Numbers in the table are the figures stated in that post.
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
PALE = "E7F3F2"
WHITE = "FFFFFF"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"

ROOT = Path(__file__).resolve().parent
CHART = ROOT / "images" / "credo" / "sustained-vs-peak-bandwidth.png"
OUT = ROOT / "weaver-kv-spill.pptx"


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
    for old in tc_pr.findall(qn("a:solidFill")):
        tc_pr.remove(old)
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", hex_color)
    solid_fill.append(srgb)
    tc_pr.append(solid_fill)


def set_cell_borders(cell):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", "6350")
        fill = OxmlElement("a:solidFill")
        color = OxmlElement("a:srgbClr")
        color.set("val", LINE)
        fill.append(color)
        ln.append(fill)
        tc_pr.append(ln)


def write_cell(cell, text, size, bold, color, align):
    cell.text = ""
    tf = cell.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Emu(60000)
    tf.margin_right = Emu(50000)
    tf.margin_top = Emu(30000)
    tf.margin_bottom = Emu(20000)
    body = getattr(tf, "_txBody", None)
    if body is not None:
        body_pr = body.find(qn("a:bodyPr"))
        if body_pr is not None:
            body_pr.set("anchor", "ctr")
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def add_table(slide, x, y, widths, rows, heights):
    table_shape = slide.shapes.add_table(len(rows), len(widths), Inches(x), Inches(y), Inches(sum(widths)), Inches(sum(heights)))
    table = table_shape.table
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    for r, (row, h) in enumerate(zip(rows, heights)):
        table.rows[r].height = Inches(h)
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            head = r == 0
            set_cell_fill(cell, HEAD if head else (WHITE if c else SOFT))
            set_cell_borders(cell)
            color = WHITE if head else (NAVY if c == 0 else INK)
            write_cell(cell, text, 11, head or c == 0, color, PP_ALIGN.LEFT)
    return table_shape


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Weaver：KV 溢出后的持续带宽与推理减速"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.36, 0.14, 10.4, 0.24, "Credo 博客  2026-10-02    ·    架构估算    ·    右图为原文插图", 12, True, ACCENT)
    textbox(slide, 0.36, 0.38, 12.6, 0.40, "KV 溢出后，decode 大约慢 10 倍，再溢到 CXL 大约慢 100 倍", 24, True, NAVY)

    textbox(slide, 0.36, 0.88, 4.55, 0.28, "同等 die edge 的规格对比", 14, True, NAVY)
    add_table(
        slide,
        0.36,
        1.18,
        [1.28, 1.48, 1.72],
        [
            ["项目", "HBM4", "Weaver + LPDDR"],
            ["边沿密度", "约 2.0 TB/s/mm", "约 10× 并行 LPDDR"],
            ["带宽", "6.1 TB/s", "6.4 TB/s"],
            ["容量", "192 GB", "4.8 TB"],
            ["封装", "先进封装", "有机基板，无 CoWoS"],
        ],
        [0.32, 0.40, 0.36, 0.36, 0.40],
    )

    notes = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.36), Inches(3.16), Inches(4.48), Inches(2.22))
    solid(notes, SOFT, LINE)
    textbox(
        slide,
        0.50,
        3.28,
        4.20,
        1.98,
        "边沿：LPDDR5X 0.18，GDDR7 0.4，\n"
        "HBM4 约 2.0，单位 TB/s/mm。\n"
        "基板直连 LPDDR 大约 256 GB。\n"
        "链路 250 mm，往返约 50 ns，含 FEC。\n"
        "物理层约 0.75 pJ/bit。\n"
        "余边约 10 mm 再挂 LPDDR6，\n"
        "+1.5 TB、+3.7 TB/s。\n"
        "加上 8 颗 HBM4：1.8 TB、25.7 TB/s。",
        12,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )

    # 2400×1400 source. Keep the aspect ratio; do not stretch.
    slide.shapes.add_picture(str(CHART), Inches(5.08), Inches(0.88), Inches(7.88), Inches(4.60))

    cards = [
        (PALE, TEAL, "KV 还在 HBM", "1×", "短上下文两条线重合。\nPrefill 仍按计算受限。"),
        (GOLD_BG, GOLD, "溢到 CPU 侧 LPDDR", "约 1/10", "Decode 每 token 重读 KV。\nTPOT 约 ×10，吞吐约 ÷10。"),
        (GOLD_BG, GOLD, "再溢到 CXL", "约 1/100", "同一条 decode 路径再放大。\nTPOT 约 ×100，吞吐约 ÷100。"),
    ]
    for i, (fill, num_color, cap, num, body) in enumerate(cards):
        x = 0.36 + i * 4.30
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(5.56), Inches(4.16), Inches(1.52))
        solid(card, fill, LINE)
        textbox(slide, x + 0.16, 5.62, 3.84, 0.24, cap, 12, True, MUTED)
        textbox(slide, x + 0.16, 5.84, 3.84, 0.36, num, 20, True, num_color)
        textbox(slide, x + 0.16, 6.22, 3.84, 0.74, body, 13, False, INK, anchor=MSO_ANCHOR.TOP)

    textbox(
        slide,
        0.36,
        7.16,
        12.6,
        0.26,
        "来源：credosemi.com 博客 Breaking the Memory Wall，2026-10-02。图为 sustained-vs-peak-bandwidth.svg。10 倍和 100 倍是博客对分层内存的估算。",
        11,
        False,
        MUTED,
    )

    notes_slide = slide.notes_slide
    notes_slide.notes_text_frame.text = (
        "Blog: https://credosemi.com/blogs/breaking-the-memory-wall-how-omniconnect-decouples-memory-from-compute/\n"
        "Figure file: https://credosemi.com/wp-content/uploads/sustained-vs-peak-bandwidth.svg\n"
        "Decode is the memory-bound stage in the post. A 10x or 100x drop in sustained bandwidth "
        "stretches the per-token KV read by the same factor when that read sets the step time. "
        "The post does not publish a model benchmark."
    )
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
