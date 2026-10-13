#!/usr/bin/env python3
"""Editable one-page flow of one inference request under PD separation."""

from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

FONT = "Microsoft YaHei"
NAVY = (14, 42, 71)
INK = (28, 36, 46)
MUTED = (90, 99, 110)
WHITE = (255, 255, 255)
ACCENT = (20, 90, 150)
TEAL = (14, 122, 118)
GOLD = (122, 84, 28)
GREEN = (27, 110, 72)
CORAL = (176, 64, 52)
COVER = (232, 243, 242)
TPOT_BG = (226, 242, 232)
PILL = (255, 248, 240)
REJECT_BG = (255, 241, 238)


def rgb(c):
    return RGBColor(*c)


def set_run_font(run, size, bold=False, color=INK, name=FONT):
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
        shape.line.width = Pt(1.0)
    strip_shadow(shape)


def write(shape, text, size, bold, color, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Inches(0.08)
    tf.margin_right = Inches(0.08)
    tf.margin_top = Inches(0.04)
    tf.margin_bottom = Inches(0.04)
    body = getattr(tf, "_txBody", None)
    if body is not None:
        bodyPr = body.find(qn("a:bodyPr"))
        if bodyPr is not None:
            bodyPr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(2)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def box(slide, x, y, w, h, fill, text="", size=12, bold=True, color=WHITE, line=None, align=PP_ALIGN.CENTER):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line)
    if text:
        write(shape, text, size, bold, color, align)
    return shape


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


def link(slide, x1, y1, x2, y2, color, width=2.25):
    shape = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(width)
    ln = shape.line._get_or_add_ln()
    tail = OxmlElement("a:tailEnd")
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "sm")
    ln.append(tail)
    return shape


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "推理阶段业务流程"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.36, 0.18, 12.6, 0.22, "推理业务流程  ·  PD 分离  ·  一次请求", 13, True, ACCENT)
    textbox(
        slide,
        0.36,
        0.42,
        12.6,
        0.42,
        "首 token 由 prefill 产出，decode 接住槽位后放行",
        26,
        True,
        NAVY,
    )
    textbox(
        slide,
        0.36,
        0.90,
        12.6,
        0.32,
        "TTFT 从接受到这次放行。放行之后，decode 的每一步是 TPOT。",
        16,
        False,
        INK,
    )

    # Five stages on one line. Arrows occupy the gaps; labels stay inside the nodes.
    margin = 0.36
    box_w, gap, box_h = 2.14, 0.48, 1.86
    box_y = 1.40
    stages = [
        (NAVY, "接受", "请求进入服务\nTTFT 从这里起算"),
        (GOLD, "准入", "容量和预测 TTFT\n通过才进入 Prefill"),
        (TEAL, "Prefill", "计算这段 prompt\n产出首 token"),
        (ACCENT, "KV 交接", "按层送往 decode\n目的地已经选定"),
        (GREEN, "Decode", "槽位接住后放行\n之后每步一个 token"),
    ]
    xs = [margin + i * (box_w + gap) for i in range(5)]
    mid_y = box_y + box_h / 2

    for x, (fill, title, body) in zip(xs, stages):
        box(slide, x, box_y, box_w, box_h, fill, "")
        textbox(slide, x + 0.10, box_y + 0.28, box_w - 0.20, 0.46, title, 22, True, WHITE, align=PP_ALIGN.CENTER)
        textbox(slide, x + 0.10, box_y + 0.84, box_w - 0.20, 0.78, body, 14, False, WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)

    for i in range(4):
        link(slide, xs[i] + box_w, mid_y, xs[i + 1], mid_y, NAVY)

    # Two exits from 准入. They leave the main path.
    admit_x = xs[1]
    pill_y, pill_h, pill_w = 3.58, 0.78, 2.46
    pill_gap = 0.14
    pair_w = pill_w * 2 + pill_gap
    pair_x = admit_x + box_w / 2 - pair_w / 2
    defer_x = pair_x
    reject_x = pair_x + pill_w + pill_gap

    link(slide, admit_x + 0.42, box_y + box_h, defer_x + pill_w / 2, pill_y, GOLD, 1.75)
    link(slide, admit_x + box_w - 0.42, box_y + box_h, reject_x + pill_w / 2, pill_y, CORAL, 1.75)

    box(slide, defer_x, pill_y, pill_w, pill_h, PILL, "", line=GOLD)
    textbox(slide, defer_x + 0.10, pill_y + 0.06, pill_w - 0.20, 0.30, "推迟", 14, True, GOLD, align=PP_ALIGN.CENTER)
    textbox(slide, defer_x + 0.10, pill_y + 0.36, pill_w - 0.20, 0.34, "已接受，等待计入 TTFT", 12, False, INK, align=PP_ALIGN.CENTER)

    box(slide, reject_x, pill_y, pill_w, pill_h, REJECT_BG, "", line=CORAL)
    textbox(slide, reject_x + 0.10, pill_y + 0.06, pill_w - 0.20, 0.30, "拒绝", 14, True, CORAL, align=PP_ALIGN.CENTER)
    textbox(slide, reject_x + 0.10, pill_y + 0.36, pill_w - 0.20, 0.34, "未接受，没有 TTFT 样本", 12, False, INK, align=PP_ALIGN.CENTER)

    # Clock split follows the same five stages: release is the entrance of Decode.
    bar_y, bar_h = 4.58, 0.42
    ttft_w = xs[4] - margin
    box(slide, margin, bar_y, ttft_w, bar_h, COVER, "")
    textbox(slide, margin, bar_y, ttft_w, bar_h, "TTFT：从接受到首 token 放行", 14, True, TEAL, align=PP_ALIGN.CENTER)
    box(slide, xs[4], bar_y, box_w, bar_h, TPOT_BG, "")
    textbox(slide, xs[4], bar_y, box_w, bar_h, "TPOT：之后每一步", 14, True, GREEN, align=PP_ALIGN.CENTER)

    textbox(
        slide,
        0.36,
        5.20,
        12.6,
        1.85,
        "TTFT = 排队 + prefill 计算 + KV 搬运 + 等 decode 槽位\n"
        "TPOT = 首 token 放行之后，decode 每一步的时间\n"
        "槽位 = 上下文的 KV 容量 + 当前批里的一个席位。不够就继续等。\n"
        "容量内才算通过：输入 token/min、输出 token/min、在途上下文。",
        16,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )

    slide.notes_slide.notes_text_frame.text = (
        "业务流程按 PD 分离、且 TTFT 含 P 到 D 的 KV 搬运来画。"
        "TTFT 起算于服务接受请求，结束于首 token 放行。"
        "首 token 由 prefill 在 prompt 最后一步产出。放行条件是 KV 已按层交到事先选定的 decode，并且 decode 槽位已经接住。"
        "槽位是这段上下文的 KV 容量，加上当前 decode 批里的一个席位。任一不够，请求继续等，不失败，也不退回 prefill。"
        "推迟表示已经接受，等待计入最终 TTFT。拒绝发生在接受之前，没有 TTFT 样本。"
        "TPOT 从第二个 token 起，等于 decode 池这一步的时间。"
        "容量三件事：输入 token/min、输出 token/min、在途上下文。"
    )

    out = "/workspace/docs/infer-request-flow.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
