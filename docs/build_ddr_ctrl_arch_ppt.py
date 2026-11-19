#!/usr/bin/env python3
"""Two slides: a DDR5 controller path, and why bank-group choice sets the data-bus duty cycle.

Numbers follow DDR5 as commonly specified: a DIMM has two 32-bit sub-channels,
default burst length 16, so one column burst is 64 bytes. tCCD_S is 8 nCK.
tCCD_L is at least 8 nCK and 5 ns, which is 16 nCK at DDR5-6400, so back-to-back
reads in one bank group fill about half of that sub-channel. An x8 die is drawn
as 8 bank groups of 4 banks, with about 1 KB in the open row.
"""

from __future__ import annotations

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
DIM = "E4E9EF"

SLIDES = 2
FOOTER = "DDR5    ·    一条子通道 32 bit    ·    BL16 = 64 字节    ·    tCCD_S = 8 nCK    ·    tCCD_L ≥ 5 ns"
PPT = "/agent/repos/ucl-mpcomm/docs/DDR控制器架构.pptx"


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
        shape.line.width = Pt(1.0)
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


def chrome(slide, page, title, kicker):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.42, 0.14, 10.6, 0.26, kicker, 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 0.42, 0.40, 12.5, 0.40, title, 24, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 11.4, 0.16, 1.5, 0.24, f"{page}  /  {SLIDES}", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(slide, 0.42, 7.20, 12.5, 0.24, FOOTER, 11, False, MUTED, anchor=MSO_ANCHOR.MIDDLE)


def rect(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line)
    return shape


def rounded(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line)
    return shape


def down_arrow(slide, x, y, w=0.20, h=0.16):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, ACCENT)
    return shape


def slide_arch(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, 1, "DDR 控制器：一次读怎么落到颗粒上", "DDR5    ·    一条子通道一次突发 64 字节")

    rect(slide, 0.42, 1.46, 7.55, 5.52, SOFT)
    textbox(slide, 0.58, 1.54, 7.2, 0.26, "控制器里，从上到下", 12, True, MUTED)

    steps = [
        (1.86, 0.54, NAVY, WHITE, WHITE, "核    ·    缓存未命中", "送出来的是一条 64 字节缓存行"),
        (2.58, 0.58, WHITE, ACCENT, INK, "读队列    ·    写队列", "分开排队。调度器每次挑一条命令出去"),
        (3.34, 0.72, PALE, TEAL, INK, "地址映射", "通道 · 子通道 · Rank · Bank Group\nBank · 行 · 列"),
        (4.24, 0.88, TEAL, WHITE, WHITE, "调度器", "这一行已经打开：只发列读\n下一条列读换到别的 Bank Group"),
        (5.30, 0.64, NAVY, WHITE, WHITE, "PHY", "时钟、命令/地址、DQ、DQS"),
    ]
    left = 0.58
    width = 7.23
    for i, (y, h, fill, title_color, body_color, title, body) in enumerate(steps):
        line = LINE if fill == WHITE else None
        rect(slide, left, y, width, h, fill, line)
        textbox(slide, left + 0.16, y + 0.04, width - 0.32, 0.26, title, 14, True, title_color)
        textbox(slide, left + 0.16, y + 0.30, width - 0.32, h - 0.34, body, 13, False, body_color, anchor=MSO_ANCHOR.TOP)
        if i < len(steps) - 1:
            down_arrow(slide, left + width / 2 - 0.10, y + h + 0.02)

    textbox(slide, left, 6.04, width, 0.22, "一颗 DDR5 DIMM 两条子通道，命令和数据各自独立", 12, False, MUTED)
    rounded(slide, left, 6.28, 3.50, 0.50, WHITE, TEAL)
    textbox(slide, left + 0.12, 6.28, 3.26, 0.50, "子通道 0    32 bit", 14, True, TEAL, PP_ALIGN.CENTER)
    rounded(slide, left + 3.73, 6.28, 3.50, 0.50, WHITE, TEAL)
    textbox(slide, left + 3.85, 6.28, 3.26, 0.50, "子通道 1    32 bit", 14, True, TEAL, PP_ALIGN.CENTER)

    rect(slide, 8.15, 1.46, 4.76, 5.52, SOFT)
    textbox(slide, 8.31, 1.54, 4.44, 0.26, "一颗 die 里，调度器选的就是这里", 12, True, MUTED)
    textbox(slide, 8.31, 1.82, 4.44, 0.40, "常见 x8：8 个 Bank Group\n每个里面 4 个 Bank", 13, True, NAVY, anchor=MSO_ANCHOR.TOP)

    groups = ["BG0", "BG1", "BG2", "BG3", "BG4", "BG5", "BG6", "BG7"]
    cell_w = 1.02
    gap = 0.08
    for i, name in enumerate(groups):
        col, row = i % 4, i // 4
        x = 8.31 + col * (cell_w + gap)
        y = 2.30 + row * 0.48
        fill = TEAL if i == 0 else DIM
        color = WHITE if i == 0 else NAVY
        rect(slide, x, y, cell_w, 0.40, fill)
        textbox(slide, x, y, cell_w, 0.40, name, 13, True, color, PP_ALIGN.CENTER)

    textbox(slide, 8.31, 3.32, 4.44, 0.24, "点亮的 BG0，四个 Bank", 12, True, TEAL)
    for i in range(4):
        x = 8.31 + i * (cell_w + gap)
        fill = TEAL if i == 0 else DIM
        color = WHITE if i == 0 else NAVY
        rect(slide, x, 3.58, cell_w, 0.36, fill)
        textbox(slide, x, 3.58, cell_w, 0.36, f"B{i}", 12, True, color, PP_ALIGN.CENTER)

    rounded(slide, 8.31, 4.08, 4.44, 1.42, WHITE, TEAL)
    textbox(slide, 8.47, 4.16, 4.12, 0.26, "Bank 0 的行缓冲", 14, True, TEAL)
    textbox(
        slide, 8.47, 4.46, 4.12, 0.94,
        "只打开一行。x8 上大约 1 KB。\n"
        "列地址从这一行取出 64 字节。\n"
        "行还开着，下一次不用再激活。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )

    rounded(slide, 8.31, 5.62, 4.44, 1.20, GOLD_BG)
    textbox(slide, 8.47, 5.70, 4.12, 0.26, "列命令的两种间隔", 14, True, GOLD)
    textbox(
        slide, 8.47, 6.00, 4.12, 0.72,
        "同一 Bank Group：tCCD_L，至少 5 ns。\n"
        "换 Bank Group：tCCD_S = 8 个时钟，\n"
        "和一次突发一样长。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )


def slide_timing(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, 2, "数据脚满不满，看有没有换 Bank Group", "DDR5-6400    ·    同一 Bank Group 要等 16 个时钟")

    rect(slide, 0.42, 1.00, 6.20, 4.42, SOFT)
    textbox(slide, 0.58, 1.10, 5.88, 0.30, "重复读，落在同一个 Bank Group", 15, True, NAVY)
    slots = [("BG0", TEAL, WHITE), ("空", GOLD_BG, GOLD), ("BG0", TEAL, WHITE), ("空", GOLD_BG, GOLD)]
    slot_w = 1.38
    for i, (label, fill, color) in enumerate(slots):
        x = 0.58 + i * (slot_w + 0.08)
        line = GOLD if fill == GOLD_BG else None
        rect(slide, x, 1.54, slot_w, 0.58, fill, line)
        textbox(slide, x, 1.54, slot_w, 0.58, label, 14, True, color, PP_ALIGN.CENTER)
        textbox(slide, x, 2.16, slot_w, 0.22, "8 个时钟", 11, False, MUTED, PP_ALIGN.CENTER)
    textbox(
        slide, 0.58, 2.52, 5.88, 1.70,
        "DDR5-6400 上，同一 Bank Group 的下一条列读要等 16 个时钟。\n"
        "一次突发只占其中 8 个，中间这条数据脚是空的。\n"
        "行缓冲已经命中，也补不上这 8 个时钟。",
        14, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    rounded(slide, 0.58, 4.40, 5.88, 0.82, WHITE, GOLD)
    textbox(slide, 0.74, 4.48, 5.56, 0.28, "这条子通道大约 12.8 GB/s", 15, True, GOLD)
    textbox(slide, 0.74, 4.78, 5.56, 0.34, "25.6 GB/s × 8/16。空档占一半。", 13, False, INK)

    rect(slide, 6.80, 1.00, 6.12, 4.42, SOFT)
    textbox(slide, 6.96, 1.10, 5.80, 0.30, "连续地址，轮转 8 个 Bank Group", 15, True, NAVY)
    names = ["BG0", "BG1", "BG2", "BG3", "BG4", "BG5", "BG6", "BG7"]
    cell = 0.64
    for i, name in enumerate(names):
        x = 6.96 + i * (cell + 0.05)
        rect(slide, x, 1.54, cell, 0.58, TEAL)
        textbox(slide, x, 1.54, cell, 0.58, name, 11, True, WHITE, PP_ALIGN.CENTER)
    textbox(slide, 6.96, 2.16, 5.80, 0.22, "每格 8 个时钟，和一次突发一样长", 11, False, MUTED)
    textbox(
        slide, 6.96, 2.52, 5.80, 1.70,
        "调度器把列读摊到不同 Bank Group。\n"
        "下一条只等 tCCD_S，8 个时钟。数据脚一拍接一拍，可以排满。\n"
        "单核发不够请求时，仍然到不了这个数。",
        14, False, INK, anchor=MSO_ANCHOR.TOP,
    )
    rounded(slide, 6.96, 4.40, 5.80, 0.82, WHITE, TEAL)
    textbox(slide, 7.12, 4.48, 5.48, 0.28, "这条子通道接近 25.6 GB/s", 15, True, TEAL)
    textbox(slide, 7.12, 4.78, 5.48, 0.34, "DDR5-6400，32 bit。两条子通道合计 51.2 GB/s。", 13, False, INK)

    cards = [
        (PALE, TEAL, "行已经打开", "这一行里接着读，只发列命令。\n预充电和激活，两种顺序读都不用付。"),
        (GOLD_BG, GOLD, "S 还在缓存里", "后 99 次停在 L1、L2 或 L3。\nDDR 只搬第一遍，大约 S 字节。"),
        (SOFT, NAVY, "两边都落到 DDR", "S 大于末级缓存，又盖住全部 Bank Group。\n每字节代价相同，带宽接近。"),
    ]
    for i, (fill, title_color, title, body) in enumerate(cards):
        x = 0.42 + i * 4.22
        line = LINE if fill == SOFT else None
        rounded(slide, x, 5.58, 4.06, 1.42, fill, line)
        textbox(slide, x + 0.16, 5.66, 3.74, 0.28, title, 14, True, title_color)
        textbox(slide, x + 0.16, 5.98, 3.74, 0.88, body, 13, False, INK, anchor=MSO_ANCHOR.TOP)


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "DDR 控制器架构"
    slide_arch(prs)
    slide_timing(prs)
    prs.save(PPT)
    print(f"slides {len(prs.slides)} -> {PPT}")


if __name__ == "__main__":
    build()
