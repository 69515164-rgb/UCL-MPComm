#!/usr/bin/env python3
"""One editable slide: what algorithm switches cost on Ascend 950."""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

FONT = "Microsoft YaHei"
NAVY = "0E2A47"
TEAL = "0E7A76"
INK = "1C242E"
MUTED = "5A636E"
WHITE = "FFFFFF"
LINE = "D5DCE3"
SOFT = "F4F7FA"
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"
GOLD_LINE = "E2C48A"
CHIP = "E8EEF5"
RED = "9C3B2E"
RED_BG = "F8E8E4"

OUT = "/agent/repos/ucl-mpcomm/docs/昇腾950-换算法启动.pptx"


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


def solid(shape, fill, line=None, line_pt=1.0):
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(line_pt)
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


def rect(slide, x, y, w, h, fill, line=None, line_pt=1.0, rounded=True):
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line, line_pt)
    if rounded:
        shape.adjustments[0] = 0.12
    return shape


def down_arrow(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill)
    return shape


def flow(slide, x, y, w, steps, hot):
    node_h = 0.32
    gap = 0.14
    chip_w = 0.62
    for i, (label, hw) in enumerate(steps):
        yy = y + i * (node_h + gap)
        marked = i in hot
        rect(
            slide,
            x,
            yy,
            w,
            node_h,
            RED_BG if marked else WHITE,
            GOLD_LINE if marked else LINE,
            1.25 if marked else 1.0,
        )
        textbox(
            slide,
            x + 0.06,
            yy,
            w - chip_w - 0.10,
            node_h,
            label,
            11,
            marked,
            RED if marked else NAVY,
            PP_ALIGN.LEFT,
        )
        textbox(
            slide,
            x + w - chip_w,
            yy,
            chip_w - 0.04,
            node_h,
            hw,
            10,
            True,
            RED if marked else TEAL,
            PP_ALIGN.RIGHT,
        )
        if i + 1 < len(steps):
            down_arrow(slide, x + w / 2 - 0.06, yy + node_h + 0.005, 0.12, 0.13, "B7C3CE")


def outcome(slide, x, y, w, kind, title, body):
    if kind == "sw":
        fill, accent, title_c = PALE, TEAL, TEAL
    else:
        fill, accent, title_c = CHIP, NAVY, NAVY
    rect(slide, x, y, w, 1.18, fill)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(0.06), Inches(1.18))
    solid(bar, accent)
    textbox(slide, x + 0.14, y + 0.04, w - 0.22, 0.24, title, 11, True, title_c)
    textbox(slide, x + 0.14, y + 0.28, w - 0.22, 0.86, body, 11, False, INK, anchor=MSO_ANCHOR.TOP)


def column(slide, x, y, w, name, note, steps, hot, contradiction, sw, hw):
    rect(slide, x, y, w, 6.28, SOFT, LINE, 1.0)
    rect(slide, x + 0.10, y + 0.10, w - 0.20, 0.36, NAVY)
    textbox(slide, x + 0.16, y + 0.10, w - 0.32, 0.36, name, 14, True, WHITE, PP_ALIGN.CENTER)
    textbox(slide, x + 0.10, y + 0.48, w - 0.20, 0.22, note, 10, False, MUTED, PP_ALIGN.CENTER)
    flow(slide, x + 0.16, y + 0.76, w - 0.32, steps, hot)
    rect(slide, x + 0.10, y + 2.62, w - 0.20, 0.78, GOLD_BG, GOLD_LINE, 1.0)
    textbox(slide, x + 0.18, y + 2.64, w - 0.36, 0.22, "换算法的矛盾", 11, True, GOLD)
    textbox(slide, x + 0.18, y + 2.86, w - 0.36, 0.50, contradiction, 11, False, INK, anchor=MSO_ANCHOR.TOP)
    outcome(slide, x + 0.10, y + 3.50, w - 0.20, "sw", "软件能收到", sw)
    outcome(slide, x + 0.10, y + 4.78, w - 0.20, "hw", "下一代硬件能收到", hw)


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "昇腾 950 换集合通信算法的启动开销"
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5))
    solid(bg, WHITE)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.06))
    solid(bar, TEAL)

    textbox(slide, 0.28, 0.12, 9.2, 0.34, "换算法时，启动里哪一步最贵", 22, True, NAVY)
    textbox(
        slide,
        0.28,
        0.46,
        8.8,
        0.24,
        "建链只做一次。每一步右边是在哪块硬件上。红框是换算法要重做的。",
        12,
        False,
        MUTED,
    )
    textbox(slide, 9.3, 0.16, 3.75, 0.24, "次数 = 这一步做不做，不是实测微秒", 11, True, RED, PP_ALIGN.RIGHT)

    left_x, top, col_w, gap = 0.22, 0.78, 2.82, 0.10
    column(
        slide,
        left_x,
        top,
        col_w,
        "AICPU",
        "默认。大数据走这里",
        [("挑算法", "主机"), ("拆成搬运单", "AICPU"), ("送回调度器", "AICPU"), ("派去搬运", "STARS")],
        {1},
        "大头是拆单这一遍。\n换算法，这一遍一点省不掉。",
        "形状不变：拆单 1 遍变 0。\n换算法：仍是每次 1 遍。",
        "换算法也不用拆。\n盖 1 次章，拆单变成 0 遍。",
    )
    column(
        slide,
        left_x + col_w + gap,
        top,
        col_w,
        "AIV",
        "只用于推理，小数据",
        [("程序只装一次", "主机"), ("每次发一个核", "STARS"), ("核里自己搬", "AIV"), ("核被通信占住", "AIV")],
        {3},
        "发核不是大头。\n大头是核被占，且只能 1 个域。",
        "程序不重装。\n换算法仍是 1 次发核。",
        "派核仍是 1 次。\n多组核可以同时做通信。",
    )
    column(
        slide,
        left_x + 2 * (col_w + gap),
        top,
        col_w,
        "CCU",
        "片上专核。装不下就退回 AICPU",
        [("空跑，把步骤记下", "主机"), ("微码写进片上", "主机"), ("提交一次任务", "STARS"), ("自己搬数据、做加法", "CCU")],
        {0, 1},
        "大头是微码重写进片上。\n长度一变，记和装都重做。",
        "几套提前译好。\n换算法从 3 段收成 1 次。",
        "微码不用再装。\n换算法只写 1 个号。",
    )

    rx, ry, rw = 8.96, 0.78, 4.10
    rect(slide, rx, ry, rw, 6.28, SOFT, LINE, 1.0)
    rect(slide, rx + 0.12, ry + 0.10, rw - 0.24, 0.36, TEAL)
    textbox(slide, rx + 0.18, ry + 0.10, rw - 0.36, 0.36, "推理融合算子", 14, True, WHITE, PP_ALIGN.CENTER)
    textbox(slide, rx + 0.12, ry + 0.48, rw - 0.24, 0.22, "整段都在 Vector 核里，不再走 HCCL", 10, False, MUTED, PP_ALIGN.CENTER)

    rect(slide, rx + 0.90, ry + 0.76, 2.30, 0.32, NAVY)
    textbox(slide, rx + 0.90, ry + 0.76, 2.30, 0.32, "一层只发 1 次核 · AIV", 12, True, WHITE, PP_ALIGN.CENTER)
    down_arrow(slide, rx + 1.93, ry + 1.10, 0.14, 0.14, "B7C3CE")

    rect(slide, rx + 0.16, ry + 1.28, 1.84, 0.78, WHITE, LINE, 1.0)
    textbox(slide, rx + 0.22, ry + 1.30, 1.72, 0.22, "机柜内 · UB", 11, True, TEAL, PP_ALIGN.CENTER)
    textbox(slide, rx + 0.22, ry + 1.52, 1.72, 0.50, "核直接写对方内存\n再软件空等标志", 11, False, INK, PP_ALIGN.CENTER, MSO_ANCHOR.TOP)

    rect(slide, rx + 2.10, ry + 1.28, 1.84, 0.78, WHITE, LINE, 1.0)
    textbox(slide, rx + 2.16, ry + 1.30, 1.72, 0.22, "跨柜 · URMA", 11, True, TEAL, PP_ALIGN.CENTER)
    textbox(slide, rx + 2.16, ry + 1.52, 1.72, 0.50, "核来填搬运单\n每个目的敲 1 次", 11, False, INK, PP_ALIGN.CENTER, MSO_ANCHOR.TOP)

    rect(slide, rx + 0.14, ry + 2.16, rw - 0.28, 0.96, GOLD_BG, GOLD_LINE, 1.0)
    textbox(slide, rx + 0.26, ry + 2.18, rw - 0.52, 0.22, "换算法的矛盾", 11, True, GOLD)
    textbox(
        slide,
        rx + 0.26,
        ry + 2.40,
        rw - 0.52,
        0.68,
        "主机这边没有第二次启动。\n还在付的是：数一数各去多少，1 次来回；\n跨柜时，每个目的再敲 1 次门铃。",
        12,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )
    outcome(
        slide,
        rx + 0.14,
        ry + 3.22,
        rw - 0.28,
        "sw",
        "软件能收到",
        "连接提前建好，整层收进图里。\n主机下发从每层 1 次变成 0。\n计数来回和敲门还在。",
    )
    outcome(
        slide,
        rx + 0.14,
        ry + 4.52,
        rw - 0.28,
        "hw",
        "下一代硬件能收到",
        "不用软件空等。\n敲门从每条 1 次收成填个长度。\n还剩 1 次片上的计数来回。",
    )

    textbox(
        slide,
        0.28,
        7.16,
        12.7,
        0.24,
        "青字是现有软件能少做的次数    深蓝是下一代片上还能再少的    图模式 AICPU 最多 6 个，CCU 同时最多 32 个任务",
        11,
        False,
        MUTED,
    )
    prs.save(OUT)


if __name__ == "__main__":
    build()
