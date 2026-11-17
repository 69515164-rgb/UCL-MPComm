#!/usr/bin/env python3
"""Two slides: HBM4 stack interface, and the two access constraints on it.

Numbers follow JEDEC JESD270-4 as published in April 2025: 32 channels,
64-bit DDR data per channel, two 32-bit pseudo-channels, burst length 8,
up to 8 Gb/s across a 2048-bit interface (about 2 TB/s, one direction).
Vendor bins can raise the pin rate. The burst size and the shared
bidirectional data pins do not change with that rate.
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
AMBER = "C4841D"
DIM = "E4E9EF"

SLIDES = 2
FOOTER = "HBM4    ·    JEDEC JESD270-4    ·    2025-04    ·    标准速率 8 Gb/s    ·    厂商 pin 可以更快，颗粒和半双工不变"
PPT = "/agent/repos/ucl-mpcomm/docs/HBM4-架构.pptx"


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
    textbox(slide, 0.42, 0.16, 10.6, 0.28, kicker, 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 0.42, 0.42, 12.5, 0.42, title, 24, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 11.4, 0.18, 1.5, 0.26, f"{page}  /  {SLIDES}", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(slide, 0.42, 7.20, 12.5, 0.24, FOOTER, 11, False, MUTED, anchor=MSO_ANCHOR.MIDDLE)


def rounded(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line)
    return shape


def rect(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line)
    return shape


def down_arrow(slide, x, y, w=0.22, h=0.20):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, ACCENT)
    return shape


def note(slide, x, y, w, h, fill, title, body, title_color, line=None):
    rounded(slide, x, y, w, h, fill, line)
    textbox(slide, x + 0.16, y + 0.08, w - 0.32, 0.30, title, 14, True, title_color, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, x + 0.16, y + 0.40, w - 0.32, h - 0.50, body, 12, False, INK, anchor=MSO_ANCHOR.TOP)


def slide_arch(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, 1, "HBM4 一颗 stack：2048 bit，32 个通道", "JEDEC JESD270-4    ·    单方向约 2 TB/s")
    rounded(slide, 0.42, 0.96, 12.5, 0.40, PALE)
    textbox(
        slide, 0.58, 0.96, 12.18, 0.40,
        "数据从计算 die 进控制器，再铺到 2048 根数据脚。脚按 32 个通道切开。通道之间独立。",
        13, True, TEAL,
    )

    rect(slide, 0.48, 1.50, 7.85, 5.52, SOFT)
    textbox(slide, 0.64, 1.56, 7.5, 0.26, "一颗 HBM4 stack，自上而下", 12, True, MUTED)

    rect(slide, 0.68, 1.88, 7.45, 0.62, NAVY)
    textbox(slide, 0.84, 1.88, 7.15, 0.62, "计算 die    ·    内存控制器按通道发命令", 15, True, WHITE)

    down_arrow(slide, 4.20, 2.54)
    rect(slide, 0.68, 2.78, 7.45, 0.58, TEAL)
    textbox(
        slide, 0.84, 2.78, 7.15, 0.58,
        "2048 bit 数据脚    ·    半双工    ·    8 Gb/s × 2048 ≈ 2 TB/s（单方向）",
        13, True, WHITE,
    )

    down_arrow(slide, 4.20, 3.40)
    textbox(slide, 0.68, 3.60, 7.45, 0.24, "32 个通道，每通道 64 bit。下面点亮的是其中 1 个。", 12, True, NAVY)
    gap = 0.045
    cell_w = (7.45 - 15 * gap) / 16
    for row in range(2):
        for col in range(16):
            idx = row * 16 + col
            fill = TEAL if idx == 0 else DIM
            rect(slide, 0.68 + col * (cell_w + gap), 3.88 + row * 0.34, cell_w, 0.28, fill)

    down_arrow(slide, 4.20, 4.56)
    rounded(slide, 0.68, 4.80, 7.45, 1.18, WHITE, TEAL)
    textbox(slide, 0.84, 4.86, 7.15, 0.24, "打开的这一通道    ·    64 bit 拆成两条 pseudo-channel", 12, True, TEAL)
    rounded(slide, 0.86, 5.16, 3.45, 0.70, PALE)
    textbox(slide, 0.98, 5.16, 3.22, 0.70, "PC0    32 bit 数据脚\n突发长度 8  →  32 字节", 13, True, NAVY)
    rounded(slide, 4.48, 5.16, 3.45, 0.70, PALE)
    textbox(slide, 4.60, 5.16, 3.22, 0.70, "PC1    32 bit 数据脚\n突发长度 8  →  32 字节", 13, True, NAVY)

    textbox(slide, 0.68, 6.04, 7.45, 0.22, "命令总线这一通道共用。下面四种叠层高度是四选一，不是四颗并排。", 12, False, MUTED)
    for i, label in enumerate(("DRAM 4-Hi", "8-Hi", "12-Hi", "16-Hi · 最高 64 GB")):
        bar = rect(slide, 0.68 + i * 1.88, 6.32, 1.78, 0.48, NAVY if i == 3 else "1E4E86")
        textbox(slide, 0.68 + i * 1.88, 6.32, 1.78, 0.48, label, 11, True, WHITE, PP_ALIGN.CENTER)

    note(
        slide, 8.52, 1.50, 4.40, 1.28, GOLD_BG,
        "最小颗粒 32 字节",
        "一个 pseudo-channel 上，8 × 32 bit = 32 字节。\n要 4 字节，这一次突发也占满。",
        GOLD,
    )
    note(
        slide, 8.52, 2.90, 4.40, 1.28, PALE,
        "小位宽只用到少数脚",
        "整颗 2048 根数据脚。一条 32 bit 子通道\n是 32/2048。其余通道不会来补。",
        TEAL,
    )
    note(
        slide, 8.52, 4.30, 4.40, 1.28, SOFT,
        "数据脚是半双工",
        "同一时刻只有一个方向。约 2 TB/s 是\n单方向峰值。读写不能同时打满同一条脚。",
        NAVY,
    )
    note(
        slide, 8.52, 5.70, 4.40, 1.28, WHITE,
        "通道之间可以反向",
        "通道 A 读、通道 B 写可以同时。\n限制在同一条数据脚，不在整颗 stack。",
        ACCENT, LINE,
    )


def slide_constraints(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, 2, "小访问填不满 32 字节，读写共用同一条数据脚", "半双工，不是单工    ·    标称带宽不要再除一次 2")

    rect(slide, 0.42, 1.02, 6.20, 5.95, SOFT)
    textbox(slide, 0.58, 1.12, 5.90, 0.30, "一条 4 字节访问，带宽怎么掉下去", 15, True, NAVY)

    steps = [
        (TEAL, "整颗 stack", "单方向约 2 TB/s", "32 个通道都传满"),
        (ACCENT, "1 个通道", "64 GB/s", "64 bit × 8 Gb/s，是 1/32"),
        ("1E4E86", "1 条 pseudo-channel", "32 GB/s", "32 bit，是整颗的 1/64"),
        (AMBER, "其中 4 字节有用", "约 4 GB/s", "32 字节突发里只用 4 字节，12.5%"),
    ]
    for i, (color, title, rate, detail) in enumerate(steps):
        y = 1.54 + i * 0.92
        width = 5.70 - i * 0.85
        rect(slide, 0.62, y, width, 0.78, color)
        textbox(slide, 0.76, y + 0.06, width - 0.28, 0.32, f"{title}    {rate}", 14, True, WHITE)
        textbox(slide, 0.76, y + 0.38, width - 0.28, 0.30, detail, 12, False, WHITE)

    textbox(
        slide, 0.62, 5.28, 5.80, 1.45,
        "换行还会再掉。打开一行要先预充电再激活，这段时间不传数据。\n"
        "顺序大块能在同一行上连取很多个 32 字节。跳着的小块经常一次激活只拿走一个突发。",
        13, False, INK, anchor=MSO_ANCHOR.TOP,
    )

    rect(slide, 6.80, 1.02, 6.12, 4.55, SOFT)
    textbox(slide, 6.96, 1.12, 5.80, 0.30, "同一条数据脚上的读写", 15, True, NAVY)

    tracks = [
        ("纯读", TEAL, None, "接近单向峰值，约 2 TB/s"),
        ("纯写", NAVY, None, "也可以接近 2 TB/s，不能和上面同时发生"),
        ("对半、少换向", TEAL, NAVY, "读约 1 TB/s + 写约 1 TB/s，合计仍约 2 TB/s"),
        ("每个突发都换向", TEAL, NAVY, "周转空隙把合计打到比 2 TB/s 更低"),
    ]
    for i, (name, left, right, caption) in enumerate(tracks):
        y = 1.54 + i * 0.95
        textbox(slide, 6.96, y, 5.80, 0.24, name, 13, True, NAVY)
        if right is None:
            rect(slide, 6.96, y + 0.28, 5.64, 0.22, left)
        elif i == 2:
            rect(slide, 6.96, y + 0.28, 2.76, 0.22, left)
            rect(slide, 9.78, y + 0.28, 2.82, 0.22, right)
        else:
            x = 6.96
            for k in range(8):
                rect(slide, x, y + 0.28, 0.48, 0.22, left if k % 2 == 0 else right)
                x += 0.72
        textbox(slide, 6.96, y + 0.52, 5.80, 0.28, caption, 12, False, INK)

    rounded(slide, 6.80, 5.70, 6.12, 1.27, GOLD_BG)
    textbox(
        slide, 6.96, 5.80, 5.80, 1.08,
        "约 2 TB/s 已经是单方向峰值，不是读加写。\n"
        "并发时两个方向加起来大约还是这么多，不是再砍一半。\n"
        "先写入、以后再读出，同一份数据走两遍，那才要按两倍字节算。",
        13, False, GOLD, anchor=MSO_ANCHOR.TOP,
    )


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "HBM4 架构与访存约束"
    slide_arch(prs)
    slide_constraints(prs)
    prs.save(PPT)
    print(f"slides {len(prs.slides)} -> {PPT}")


if __name__ == "__main__":
    build()
