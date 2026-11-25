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
    node_h = 0.30
    gap = 0.16
    for i, label in enumerate(steps):
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
            w - 0.12,
            node_h,
            label,
            11,
            marked,
            RED if marked else NAVY,
            PP_ALIGN.CENTER,
        )
        if i + 1 < len(steps):
            down_arrow(slide, x + w / 2 - 0.06, yy + node_h + 0.01, 0.12, 0.14, "B7C3CE")


def outcome(slide, x, y, w, kind, title, body):
    if kind == "sw":
        fill, accent, title_c = PALE, TEAL, TEAL
    else:
        fill, accent, title_c = CHIP, NAVY, NAVY
    rect(slide, x, y, w, 1.18, fill)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(0.06), Inches(1.18))
    solid(bar, accent)
    textbox(slide, x + 0.14, y + 0.04, w - 0.22, 0.24, title, 11, True, title_c)
    textbox(slide, x + 0.14, y + 0.28, w - 0.22, 0.84, body, 12, False, INK, anchor=MSO_ANCHOR.TOP)


def column(slide, x, y, w, name, note, steps, hot, contradiction, sw, hw):
    rect(slide, x, y, w, 6.28, SOFT, LINE, 1.0)
    rect(slide, x + 0.10, y + 0.10, w - 0.20, 0.36, NAVY)
    textbox(slide, x + 0.16, y + 0.10, w - 0.32, 0.36, name, 14, True, WHITE, PP_ALIGN.CENTER)
    textbox(slide, x + 0.10, y + 0.48, w - 0.20, 0.22, note, 10, False, MUTED, PP_ALIGN.CENTER)
    flow(slide, x + 0.16, y + 0.76, w - 0.32, steps, hot)
    rect(slide, x + 0.10, y + 2.62, w - 0.20, 0.78, GOLD_BG, GOLD_LINE, 1.0)
    textbox(slide, x + 0.18, y + 2.64, w - 0.36, 0.22, "换算法的矛盾", 11, True, GOLD)
    textbox(slide, x + 0.18, y + 2.86, w - 0.36, 0.50, contradiction, 12, False, INK, anchor=MSO_ANCHOR.TOP)
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

    textbox(slide, 0.28, 0.12, 10.4, 0.34, "换算法时，启动开销收在哪一步", 22, True, NAVY)
    textbox(
        slide,
        0.28,
        0.46,
        9.6,
        0.24,
        "昇腾 950    ·    建域一次：rank 表、Jetty、窗口。换算法都不拆",
        12,
        False,
        MUTED,
    )
    textbox(slide, 10.3, 0.16, 2.75, 0.24, "红框 = 换算法重做的那一跳", 11, True, RED, PP_ALIGN.RIGHT)

    left_x, top, col_w, gap = 0.22, 0.78, 2.82, 0.10
    column(
        slide,
        left_x,
        top,
        col_w,
        "AICPU_TS",
        "默认 · 大数据",
        ["主机选择算法", "AICPU 展开描述符", "描述符交回 STARS", "执行器搬运"],
        {1},
        "缓存按形状存。\n换算法或改 count，展开整段重来。",
        "同形状第二次跳过展开。\n换算法仍是全额展开。",
        "按算法号直接盖 WQE。\n展开消失，只剩派发。",
    )
    column(
        slide,
        left_x + col_w + gap,
        top,
        col_w,
        "AIV",
        "仅推理 · 小数据",
        ["二进制只装一次", "每次 Kernel launch", "核内跑 Mesh", "占住 Vector 核"],
        {3},
        "启动已是一次 launch。\n单域独占核，多域不能并行。",
        "句柄常驻，核内可分支。\n换算法仍是一次 launch。",
        "多组 Vector 可同时通信。\nlaunch 几乎不动，单域限制打开。",
    )
    column(
        slide,
        left_x + 2 * (col_w + gap),
        top,
        col_w,
        "CCU",
        "MS 中转 / SCHED 调度",
        ["空跑记成 REP", "翻译并装入微码", "rtCCULaunch", "Mission 执行"],
        {0, 1},
        "快路径把 count 写进标签。\n一变就重录、重装微码。",
        "建域时预翻译多套。\n换算法只剩一次 launch。",
        "多套微码常驻，改入口。\n装入消失，写成一个算法号。",
    )

    rx, ry, rw = 8.96, 0.78, 4.10
    rect(slide, rx, ry, rw, 6.28, SOFT, LINE, 1.0)
    rect(slide, rx + 0.12, ry + 0.10, rw - 0.24, 0.36, TEAL)
    textbox(slide, rx + 0.18, ry + 0.10, rw - 0.36, 0.36, "推理融合算子", 14, True, WHITE, PP_ALIGN.CENTER)
    textbox(slide, rx + 0.12, ry + 0.48, rw - 0.24, 0.22, "只用 AIV    ·    不再调用 HCCL", 10, False, MUTED, PP_ALIGN.CENTER)

    rect(slide, rx + 1.15, ry + 0.78, 1.80, 0.34, NAVY)
    textbox(slide, rx + 1.15, ry + 0.78, 1.80, 0.34, "一次 AIV 核", 12, True, WHITE, PP_ALIGN.CENTER)
    down_arrow(slide, rx + 1.93, ry + 1.14, 0.14, 0.16, "B7C3CE")

    rect(slide, rx + 0.18, ry + 1.34, 1.78, 0.72, WHITE, LINE, 1.0)
    textbox(slide, rx + 0.26, ry + 1.36, 1.62, 0.26, "UB Memory", 12, True, TEAL, PP_ALIGN.CENTER)
    textbox(slide, rx + 0.26, ry + 1.62, 1.62, 0.40, "访存指令\n+ 软件标志", 12, False, INK, PP_ALIGN.CENTER, MSO_ANCHOR.TOP)

    rect(slide, rx + 2.14, ry + 1.34, 1.78, 0.72, WHITE, LINE, 1.0)
    textbox(slide, rx + 2.22, ry + 1.36, 1.62, 0.26, "URMA", 12, True, TEAL, PP_ALIGN.CENTER)
    textbox(slide, rx + 2.22, ry + 1.62, 1.62, 0.40, "逐条 SQE\n+ doorbell", 12, False, INK, PP_ALIGN.CENTER, MSO_ANCHOR.TOP)

    rect(slide, rx + 0.14, ry + 2.18, rw - 0.28, 0.92, GOLD_BG, GOLD_LINE, 1.0)
    textbox(slide, rx + 0.26, ry + 2.22, rw - 0.52, 0.22, "换算法的矛盾", 11, True, GOLD)
    textbox(
        slide,
        rx + 0.26,
        ry + 2.46,
        rw - 0.52,
        0.58,
        "选择发生在核内，主机没有第二次启动。\n还在付的是计数交换，和 URMA 的逐条 doorbell。",
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
        "窗口和 Jetty 都预建，图捕获掉 launch。\n主机下发归零。计数往返和 doorbell 还在。",
    )
    outcome(
        slide,
        rx + 0.14,
        ry + 4.52,
        rw - 0.28,
        "hw",
        "下一代硬件能收到",
        "硬件标志替换轮询，WQE 模板合并 doorbell。\n剩一次片上的计数交换。",
    )

    textbox(
        slide,
        0.28,
        7.16,
        12.7,
        0.24,
        "青 = 现有软件能缓存的程度        深蓝 = 下一代片上能再收掉的程度        资源不够时 CCU 仍退回 AICPU",
        11,
        False,
        MUTED,
    )
    prs.save(OUT)


if __name__ == "__main__":
    build()
