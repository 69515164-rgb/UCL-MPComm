#!/usr/bin/env python3
"""Editable timeline: KV handoff dependencies and the exposed tail."""

from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
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
CORAL = (176, 64, 52)
GOLD = (140, 100, 36)
GREEN = (27, 110, 72)
GRAY = (226, 230, 234)
COVER_BG = (232, 243, 242)
EXPOSE_BG = (255, 240, 236)
SOFT = (244, 247, 250)


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
        shape.line.width = Pt(0.75)
    strip_shadow(shape)


def write(shape, text, size, bold, color, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Inches(0.04)
    tf.margin_right = Inches(0.04)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    body = getattr(tf, "_txBody", None)
    if body is not None:
        bodyPr = body.find(qn("a:bodyPr"))
        if bodyPr is not None:
            bodyPr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
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


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "KV 交接时序：依赖与露出"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.32, 0.14, 12.4, 0.22, "PD 分离  ·  KV 交接", 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 0.32, 0.36, 12.6, 0.34, "搬运的时序：谁依赖谁，哪一段露在外面", 24, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    box(slide, 0.32, 0.78, 0.07, 0.36, ACCENT, "")
    textbox(
        slide,
        0.48,
        0.74,
        12.5,
        0.42,
        "目的地先选定。首 token 由 prefill 返回。按层送出的 KV 能被后续计算盖住；盖不住的最后一段，出现在第一个字和第二个字之间。",
        14,
        True,
        INK,
        anchor=MSO_ANCHOR.MIDDLE,
    )

    # Geometry of the Gantt. Four compute layers; KV of layer i starts when that layer finishes.
    label_x, label_w = 0.28, 1.48
    chart_x = 1.82
    select_w = 1.15
    layer_w = 1.38
    layer_gap = 0.05
    exposed_w = 2.55
    token2_w = 1.55
    layers_w = 4 * layer_w + 3 * layer_gap
    chart_w = select_w + layers_w + exposed_w + token2_w

    lane_h = 0.56
    y_zone = 1.28
    y0 = 1.58
    # gaps after each lane
    gaps = [0.08, 0.26, 0.08, 0.26]
    ys = [y0]
    for g in gaps:
        ys.append(ys[-1] + lane_h + g)

    x_select = chart_x
    x_layers = chart_x + select_w
    x_exposed = x_layers + layers_w
    x_token2 = x_exposed + exposed_w
    x_end = x_token2 + token2_w

    def layer_x(i):
        return x_layers + i * (layer_w + layer_gap)

    # Zone backgrounds span all five lanes.
    zone_bottom = ys[4] + lane_h
    box(slide, x_select, y_zone, x_exposed - x_select, zone_bottom - y_zone, COVER_BG, "")
    box(slide, x_exposed, y_zone, x_end - x_exposed, zone_bottom - y_zone, EXPOSE_BG, "")

    textbox(slide, x_select, y_zone, x_exposed - x_select, 0.26, "被 prefill 盖住", 12, True, TEAL, align=PP_ALIGN.CENTER)
    textbox(slide, x_exposed, y_zone, x_end - x_exposed, 0.26, "露出，可优化", 12, True, CORAL, align=PP_ALIGN.CENTER)

    labels = ["选定目的地", "Prefill 计算", "本次 KV", "历史前缀", "Decode"]
    for i, name in enumerate(labels):
        textbox(slide, label_x, ys[i], label_w, lane_h, name, 13, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)

    # Lane 1: destination must be chosen before any transfer.
    box(slide, x_select + 0.06, ys[0] + 0.08, select_w - 0.12, lane_h - 0.16, NAVY, "选定 decode", 12, True, WHITE)

    # Lane 2: four compute layers. First token is produced at the end of layer 4.
    for i in range(4):
        box(slide, layer_x(i), ys[1] + 0.06, layer_w, lane_h - 0.12, ACCENT, f"层 {i + 1}", 13, True, WHITE)
    textbox(
        slide,
        x_exposed - 0.62,
        y_zone,
        1.24,
        0.26,
        "首 token",
        12,
        True,
        GREEN,
        align=PP_ALIGN.CENTER,
    )

    # Lane 3: KV i is sent only after layer i finishes, so it aligns with the next compute slot.
    # K4 falls entirely after the first token: that is the exposed tail.
    for i in range(3):
        box(slide, layer_x(i + 1), ys[2] + 0.06, layer_w, lane_h - 0.12, TEAL, f"KV {i + 1}", 13, True, WHITE)
    k4_w = layer_w
    box(slide, x_exposed + 0.06, ys[2] + 0.06, k4_w, lane_h - 0.12, CORAL, "KV 4  露出", 12, True, WHITE)
    bubble_x = x_exposed + 0.06 + k4_w + 0.06
    bubble_w = x_token2 - bubble_x - 0.06
    box(slide, bubble_x, ys[2] + 0.06, bubble_w, lane_h - 0.12, (255, 220, 210), "气泡可压短", 11, True, CORAL)

    # Lane 4: historical prefix depends only on the destination, and runs beside prefill.
    prefix_x = x_layers
    prefix_w = layer_x(2) + layer_w - prefix_x
    box(slide, prefix_x, ys[3] + 0.08, prefix_w, lane_h - 0.16, GOLD, "历史前缀并行加载，不依赖本次逐层计算", 12, True, WHITE)

    # Lane 5: decode waits until KV 4 arrives, then emits token 2.
    box(slide, x_exposed, ys[4] + 0.08, exposed_w, lane_h - 0.16, GRAY, "等待 KV 到齐", 12, True, MUTED)
    box(slide, x_token2 + 0.06, ys[4] + 0.08, token2_w - 0.12, lane_h - 0.16, GREEN, "第 2 token", 13, True, WHITE)

    # Dependency captions sit in the taller gaps.
    textbox(
        slide,
        x_layers,
        ys[1] + lane_h,
        layers_w,
        gaps[1],
        "依赖：某一层算完，才能送出这一层的 KV",
        11,
        True,
        ACCENT,
        align=PP_ALIGN.CENTER,
    )
    textbox(
        slide,
        x_exposed,
        ys[3] + lane_h,
        exposed_w + token2_w,
        gaps[3],
        "依赖：KV 到齐，才能开算第 2 token",
        11,
        True,
        CORAL,
        align=PP_ALIGN.CENTER,
    )
    textbox(
        slide,
        x_layers + 0.08,
        ys[0],
        layers_w - 0.1,
        lane_h,
        "依赖：目的地选定之后，本次 KV 与历史前缀才能开搬",
        12,
        True,
        NAVY,
        anchor=MSO_ANCHOR.MIDDLE,
    )

    # Vertical cut at first token.
    box(slide, x_exposed - 0.015, y_zone + 0.26, 0.03, zone_bottom - (y_zone + 0.26), CORAL, "")

    # Three reading notes.
    notes = [
        (TEAL, "被盖住", "KV 1 到 KV 3 的搬运，落在后面几层的计算时间里。用户等到的首 token，仍等于 prefill 加排队。"),
        (CORAL, "露出，可优化", "最后一层要等算完才能送，所以伸到首 token 之后。带宽变低、KV 变大、多条同时搬，气泡在这里变长。"),
        (GREEN, "露出落在哪", "首 token 已经返回时，这段进第一个 TPOT。若改成等 KV 到齐才吐首字，同一段进入 TTFT。"),
    ]
    card_y, card_h = 5.55, 1.28
    card_gap = 0.12
    card_w = (13.333 - 0.56 - 2 * card_gap) / 3
    for i, (color, title, body) in enumerate(notes):
        cx = 0.28 + i * (card_w + card_gap)
        box(slide, cx, card_y, card_w, card_h, WHITE, "", line=(214, 220, 226))
        box(slide, cx, card_y, 0.08, card_h, color, "")
        textbox(slide, cx + 0.2, card_y + 0.08, card_w - 0.32, 0.28, title, 14, True, color)
        textbox(slide, cx + 0.2, card_y + 0.40, card_w - 0.32, 0.80, body, 12, False, INK, anchor=MSO_ANCHOR.TOP)

    textbox(
        slide,
        0.28,
        7.05,
        12.7,
        0.28,
        "露出的时间 = max(0, 单条搬运时间 - prefill 计算时间)。图中每层搬运与每层计算等长，所以露出正好是最后一层；搬运更慢时，气泡再往右长。",
        12,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )

    slide.notes_slide.notes_text_frame.text = (
        "时序按 DistServe 的定义：TTFT 是 prefill 阶段，首 token 在 prefill 侧生成；TPOT 从第二个 token 起算。"
        "按层搬运见 Splitwise / DéjàVu 以及后续的 SmartGen、BanaServe：算完一层即可送往已经选定的 decode。"
        "历史前缀来自 KV 池，只依赖目的地，可与本次 prefill 并行。"
        "露出的时间 = max(0, 单条搬运时间 - prefill 计算时间)。"
        "DistServe 的平均速率条件：所需带宽 = 每秒完成的 prefill 条数 × 单条 KV 字节 × 8。"
        "OPT-66B、512 token 约 1.13 GB，10 次/秒约合 90 Gbps，低于此带宽则排队积累。"
    )

    out = "/workspace/docs/kv-handoff-timeline.pptx"
    prs.save(out)
    print(out, "chart_end", round(x_end, 2))


if __name__ == "__main__":
    main()
