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
    textbox(slide, 0.32, 0.14, 12.4, 0.22, "PD 分离  ·  KV 交接    1 / 2", 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
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

    add_recompute_slide(prs)
    out = "/workspace/docs/kv-handoff-timeline.pptx"
    prs.save(out)
    print(out, "chart_end", round(x_end, 2))


def add_recompute_slide(prs):
    """Prefill reads historical KV from the pool and recomputes the miss locally."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.32, 0.14, 12.4, 0.22, "PD 分离  ·  Prefill 与 KV 池    2 / 2", 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, 0.32, 0.36, 12.6, 0.34, "读历史 KV，本地只重算未命中的一段", 24, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    box(slide, 0.32, 0.78, 0.07, 0.36, ACCENT, "")
    textbox(
        slide,
        0.48,
        0.74,
        12.5,
        0.42,
        "历史段按层从 KV 池读，未命中的一段在本地算。同一层要等历史 KV 到位才能算。读得比算得慢时，等待出现在首 token 之前。",
        14,
        True,
        INK,
        anchor=MSO_ANCHOR.MIDDLE,
    )

    # Prompt split is a token cut, not the time axis.
    label_x, label_w = 0.28, 1.52
    chart_x = 1.88
    split_y = 1.24
    textbox(slide, label_x, split_y, label_w, 0.36, "上下文切分", 13, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    split_w = 10.85
    hist_w = split_w * 0.70
    box(slide, chart_x, split_y, hist_w, 0.36, GOLD, "历史段：KV 池已有，只读取", 13, True, WHITE)
    box(slide, chart_x + hist_w, split_y, split_w - hist_w, 0.36, ACCENT, "重算段：未命中，本地计算", 13, True, WHITE)
    textbox(
        slide,
        chart_x,
        split_y + 0.36,
        split_w,
        0.22,
        "上面是 token 切分，不是时间轴。下面每一格才是时间。",
        11,
        False,
        MUTED,
    )

    # Time geometry. Each history load is longer than the local compute of one layer,
    # so a wait appears before the next local layer.
    decide_w = 1.12
    load_w = 1.92
    comp_w = 1.12
    n = 4
    x0 = chart_x + decide_w
    lane_h = 0.58
    y_zone = 1.88
    y_load = 2.16
    gap_dep = 0.30
    y_comp = y_load + lane_h + gap_dep
    zone_bottom = y_comp + lane_h

    def load_x(i):
        return x0 + i * load_w

    x_token = load_x(n) + comp_w
    token_w = 1.05
    x_end = x_token + token_w

    box(slide, chart_x, y_zone, x_end - chart_x, zone_bottom - y_zone, COVER_BG, "")
    textbox(slide, chart_x, y_zone, x_end - chart_x - token_w, 0.24, "时间  →    读历史可与上一层本地计算重叠", 12, True, TEAL, align=PP_ALIGN.CENTER)
    textbox(slide, x_token - 0.15, y_zone, token_w + 0.2, 0.24, "首 token", 12, True, GREEN, align=PP_ALIGN.CENTER)

    textbox(slide, label_x, y_load, label_w, lane_h, "KV 池读取", 13, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    textbox(slide, label_x, y_comp, label_w, lane_h, "本地重计算", 13, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)

    box(slide, chart_x + 0.06, y_load + 0.08, decide_w - 0.10, lane_h - 0.16, NAVY, "判定命中", 12, True, WHITE)
    textbox(
        slide,
        chart_x + 0.06,
        y_comp,
        decide_w - 0.08,
        lane_h,
        "等切分完成",
        11,
        True,
        MUTED,
        align=PP_ALIGN.CENTER,
    )

    for i in range(n):
        box(slide, load_x(i), y_load + 0.06, load_w - 0.06, lane_h - 0.12, GOLD, f"历史 {i + 1}", 13, True, WHITE)

    # First layer cannot compute until its history arrives. Later stalls appear
    # because each load is drawn longer than the compute it overlaps.
    box(slide, load_x(0), y_comp + 0.06, load_w - 0.06, lane_h - 0.12, (255, 220, 210), "等历史 1", 12, True, CORAL)
    for i in range(n):
        box(slide, load_x(i) + load_w, y_comp + 0.06, comp_w - 0.06, lane_h - 0.12, ACCENT, f"重算 {i + 1}", 12, True, WHITE)
        if i < n - 1:
            stall_x = load_x(i) + load_w + comp_w
            stall_w = load_w - comp_w - 0.06
            box(slide, stall_x, y_comp + 0.06, stall_w, lane_h - 0.12, (255, 220, 210), "等", 11, True, CORAL)

    box(slide, x_token, y_comp + 0.06, token_w - 0.08, lane_h - 0.12, GREEN, "首 token", 12, True, WHITE)
    box(slide, x_token - 0.015, y_zone + 0.24, 0.03, zone_bottom - (y_zone + 0.24), GREEN, "")

    textbox(
        slide,
        x0,
        y_load + lane_h,
        n * load_w,
        gap_dep,
        "依赖：该层历史 KV 到位，本地才能算这一层",
        12,
        True,
        ACCENT,
        align=PP_ALIGN.CENTER,
    )

    notes = [
        (TEAL, "被盖住", "历史 2 到历史 4 的读取，落在上一层本地重计算的时间里。重算 1 与历史 2 同时进行，重算 2 与历史 3 同时进行。"),
        (CORAL, "露出，可优化", "本地一层已经算完，下一层历史 KV 还没到，中间就是等待。池带宽变低、历史段变长，等待变长。更便宜的一小段改在本地重算，可以把等待拿掉。"),
        (GREEN, "露出落在 TTFT", "汇合在首 token 之前，等待直接进入 TTFT。上一页的露出在首 token 和第 2 token 之间，这一页的露出在首 token 之前。"),
    ]
    card_y, card_h = 4.72, 1.95
    card_gap = 0.12
    card_w = (13.333 - 0.56 - 2 * card_gap) / 3
    for i, (color, title, body) in enumerate(notes):
        cx = 0.28 + i * (card_w + card_gap)
        box(slide, cx, card_y, card_w, card_h, WHITE, "", line=(214, 220, 226))
        box(slide, cx, card_y, 0.08, card_h, color, "")
        textbox(slide, cx + 0.18, card_y + 0.10, card_w - 0.30, 0.30, title, 14, True, color)
        textbox(slide, cx + 0.18, card_y + 0.44, card_w - 0.30, 1.40, body, 13, False, INK, anchor=MSO_ANCHOR.TOP)

    textbox(
        slide,
        0.28,
        6.85,
        12.7,
        0.48,
        "层间等待 = max(0, 该层历史 KV 读完的时刻 - 上一层本地算完的时刻)。\n图按每层读取长于每层重计算来画，所以层与层之间有等待；读取更快时，这些等待消失，prefill 时间等于首层读取加上各层本地计算。",
        12,
        False,
        MUTED,
        anchor=MSO_ANCHOR.TOP,
    )

    slide.notes_slide.notes_text_frame.text = (
        "上下文先切成两段：KV 池里已经有的历史段只读取，未命中的一段在本地重计算。"
        "依赖在层上：本地计算第 i 层的 attention 之前，第 i 层的历史 KV 必须已经到位。"
        "读取第 i+1 层可以和本地计算第 i 层重叠。读取慢于计算时，两层之间出现等待，这段在首 token 之前，进入 TTFT。"
        "层间等待 = max(0, 该层历史 KV 读完的时刻 - 上一层本地算完的时刻)。"
        "若某一小段在本地重算比从池里读取更便宜，就把这一段从读取改成重算，用来消掉等待。"
    )


if __name__ == "__main__":
    main()
