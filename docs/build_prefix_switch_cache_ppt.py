#!/usr/bin/env python3
"""Two slides: where a shared prefix sits, and who reads it.

AS-IS: every Prefill card reads the same prefix from storage.
TO-BE: the first request fills the switch HBM; the rest hit there.
"""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
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
LINE = "D6DCE2"
SOFT = "F4F7FA"
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"
AMBER = "C46B2C"
AMBER_BG = "F8E6D4"
CHIP = "E8EEF5"

OUT = "/agent/repos/ucl-mpcomm/docs/共享前缀交换cache.pptx"
SLIDES = 2
FOOTER = "共享前缀    ·    128K ≈ 117 MB    ·    第一份落在交换 HBM    ·    后面的 P 卡不再打到存储"


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
        shape.adjustments[0] = 0.08
    return shape


def chrome(slide, page, title, kicker):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, TEAL)
    textbox(slide, 0.40, 0.16, 10.4, 0.26, kicker, 13, True, TEAL)
    textbox(slide, 0.40, 0.42, 12.5, 0.42, title, 26, True, NAVY)
    textbox(slide, 11.15, 0.18, 1.75, 0.26, f"{page}  /  {SLIDES}", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.40), Inches(7.18), Inches(12.55), Inches(0.012))
    solid(rule, LINE)
    textbox(slide, 0.40, 7.22, 12.55, 0.22, FOOTER, 11, False, MUTED)


def link(slide, x1, y1, x2, y2, color, width=2.0, arrow=True):
    shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(width)
    if arrow:
        ln = shape.line._get_or_add_ln()
        tail = OxmlElement("a:tailEnd")
        tail.set("type", "triangle")
        tail.set("w", "med")
        tail.set("h", "med")
        ln.append(tail)
    return shape


def down_arrow(slide, cx, y, h, color, w=0.18):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(cx - w / 2), Inches(y), Inches(w), Inches(h))
    solid(shape, color)
    return shape


def slide_topology(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, 1, "P 卡先汇到交换芯片，存储在芯片后面", "组网")

    rect(slide, 0.36, 1.16, 8.72, 5.22, WHITE, LINE, 1.25, rounded=False)
    rect(slide, 0.36, 1.16, 8.72, 0.42, NAVY, rounded=False)
    textbox(slide, 0.52, 1.16, 6.4, 0.42, "这一平面", 16, True, WHITE)
    textbox(slide, 5.40, 1.16, 3.48, 0.42, "P 节点都挂在这一颗交换芯片上", 12, False, WHITE, PP_ALIGN.RIGHT)

    cards = (("P1", "请求 1"), ("P2", "请求 2"), ("P3", "请求 3"), ("P4", "请求 4"))
    card_w, card_h, gap = 1.78, 1.18, 0.22
    total = 4 * card_w + 3 * gap
    x0 = 0.36 + (8.72 - total) / 2
    card_y = 1.78
    centers = []
    for i, (name, req) in enumerate(cards):
        x = x0 + i * (card_w + gap)
        rect(slide, x, card_y, card_w, card_h, SOFT, "C5D0DE", 1.15)
        textbox(slide, x, card_y + 0.16, card_w, 0.36, name, 20, True, NAVY, PP_ALIGN.CENTER)
        textbox(slide, x, card_y + 0.52, card_w, 0.26, "P 节点 · Prefill", 11, False, MUTED, PP_ALIGN.CENTER)
        textbox(slide, x, card_y + 0.76, card_w, 0.26, req, 13, True, TEAL, PP_ALIGN.CENTER)
        centers.append(x + card_w / 2)

    switch_x, switch_y, switch_w, switch_h = 2.15, 3.72, 5.14, 2.28
    meet_x = switch_x + switch_w / 2
    meet_y = switch_y
    for cx in centers:
        link(slide, cx, card_y + card_h, meet_x, meet_y, TEAL, 1.75, arrow=False)
    down_arrow(slide, meet_x, meet_y - 0.22, 0.22, TEAL, 0.26)
    textbox(slide, 0.52, 3.05, 1.40, 0.48, "D2D", 13, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)

    rect(slide, switch_x, switch_y, switch_w, switch_h, CHIP, "C5D2E4", 1.25)
    textbox(slide, switch_x + 0.20, switch_y + 0.10, switch_w - 0.40, 0.32, "交换芯片", 16, True, NAVY)
    rect(slide, switch_x + 0.28, switch_y + 0.52, switch_w - 0.56, 1.12, PALE, TEAL, 1.25)
    textbox(slide, switch_x + 0.40, switch_y + 0.60, switch_w - 0.80, 0.34, "合封 HBM  ·  64 GB", 16, True, TEAL, PP_ALIGN.CENTER)
    textbox(slide, switch_x + 0.40, switch_y + 0.98, switch_w - 0.80, 0.48, "热前缀留在这一层\n容量只够留热的那几份", 13, False, INK, PP_ALIGN.CENTER)

    store_x, store_y, store_w, store_h = 9.78, 3.85, 3.16, 2.15
    link(slide, switch_x + switch_w, switch_y + switch_h / 2, store_x, store_y + store_h / 2, AMBER, 2.25, arrow=True)
    textbox(slide, 8.55, 3.42, 1.15, 0.36, "存储链路", 12, True, AMBER, PP_ALIGN.CENTER)

    rect(slide, store_x, store_y, store_w, store_h, GOLD_BG, "E4D3B0", 1.25)
    textbox(slide, store_x + 0.16, store_y + 0.14, store_w - 0.32, 0.34, "存储系统", 16, True, GOLD)
    textbox(slide, store_x + 0.16, store_y + 0.54, store_w - 0.32, 0.70, "KV 全量在这里\n128K 前缀约 117 MB", 14, False, INK)
    textbox(slide, store_x + 0.16, store_y + 1.36, store_w - 0.32, 0.58, "只是全量里的一块\n卡不直接连存储", 13, False, GOLD)

    rect(slide, 0.36, 6.50, 12.58, 0.56, PALE, "B7D9D7", 1.0)
    textbox(
        slide,
        0.52,
        6.50,
        12.26,
        0.56,
        "4 张 P 卡是示意。同一条前缀拆到几张卡，就有几个读者。读请求先到交换芯片，再到存储。下一页看这 117 MB 被读几次。",
        14,
        False,
        TEAL,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    return slide


def panel_header(slide, x, y, w, fill, title, sub):
    rect(slide, x, y, w, 0.58, fill, rounded=False)
    textbox(slide, x + 0.16, y + 0.02, 1.70, 0.54, title, 18, True, WHITE)
    textbox(slide, x + 1.80, y + 0.02, w - 1.98, 0.54, sub, 13, False, WHITE, PP_ALIGN.RIGHT)


def draw_cards(slide, x, y, w, labels, colors):
    n = len(labels)
    gap = 0.12
    margin = 0.18
    card_w = (w - 2 * margin - (n - 1) * gap) / n
    card_h = 0.82
    centers = []
    for i, (name, req) in enumerate(labels):
        cx = x + margin + i * (card_w + gap)
        rect(slide, cx, y, card_w, card_h, SOFT, colors[i], 1.35)
        textbox(slide, cx, y + 0.08, card_w, 0.34, name, 16, True, NAVY, PP_ALIGN.CENTER)
        textbox(slide, cx, y + 0.42, card_w, 0.28, req, 12, True, colors[i], PP_ALIGN.CENTER)
        centers.append(cx + card_w / 2)
    return centers, y + card_h


def slide_paths(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, 2, "第一份留在交换机，后面的请求不再打到存储", "同一条 128K 前缀  ·  约 117 MB")

    labels = (("P1", "请求 1"), ("P2", "请求 2"), ("P3", "请求 3"), ("P4", "请求 4"))
    panels = (
        (0.32, AMBER, "AS-IS", "每张卡都读存储", False),
        (6.82, TEAL, "TO-BE", "第一份留下，其余读交换机", True),
    )
    for x, head, title, sub, cached in panels:
        w = 6.18
        panel_header(slide, x, 1.02, w, head, title, sub)
        colors = [AMBER, AMBER, AMBER, AMBER] if not cached else [AMBER, TEAL, TEAL, TEAL]
        centers, card_bottom = draw_cards(slide, x, 1.76, w, labels, colors)

        switch_y, switch_h = 3.12, 1.48
        for cx, color in zip(centers, colors):
            down_arrow(slide, cx, card_bottom + 0.06, switch_y - card_bottom - 0.08, color, 0.16)

        rect(slide, x + 0.18, switch_y, w - 0.36, switch_h, CHIP, "C5D2E4", 1.15)
        if cached:
            textbox(slide, x + 0.32, switch_y + 0.08, w - 0.64, 0.30, "交换芯片", 15, True, NAVY)
            rect(slide, x + 0.32, switch_y + 0.44, w - 0.64, 0.90, PALE, TEAL, 1.25)
            textbox(slide, x + 0.44, switch_y + 0.50, w - 0.88, 0.32, "HBM 留着这 117 MB", 15, True, TEAL, PP_ALIGN.CENTER)
            textbox(slide, x + 0.44, switch_y + 0.84, w - 0.88, 0.40, "请求 2、3、4 从这里返回", 13, False, INK, PP_ALIGN.CENTER)
        else:
            textbox(slide, x + 0.32, switch_y + 0.08, w - 0.64, 0.30, "交换芯片  ·  只转发", 15, True, NAVY)
            rect(slide, x + 0.32, switch_y + 0.44, w - 0.64, 0.90, SOFT, LINE, 1.15)
            textbox(slide, x + 0.44, switch_y + 0.50, w - 0.88, 0.32, "HBM 空着", 15, True, MUTED, PP_ALIGN.CENTER)
            textbox(slide, x + 0.44, switch_y + 0.84, w - 0.88, 0.40, "四次读都穿过去", 13, False, MUTED, PP_ALIGN.CENTER)

        store_y, store_h = 5.14, 0.78
        if cached:
            down_arrow(slide, centers[0], switch_y + switch_h + 0.05, store_y - (switch_y + switch_h) - 0.08, AMBER, 0.18)
            textbox(slide, centers[0] + 0.16, switch_y + switch_h + 0.08, 1.15, 0.36, "仅第 1 次", 12, True, AMBER)
        else:
            for cx in centers:
                down_arrow(slide, cx, switch_y + switch_h + 0.05, store_y - (switch_y + switch_h) - 0.08, AMBER, 0.15)

        rect(slide, x + 0.18, store_y, w - 0.36, store_h, GOLD_BG, "E4D3B0", 1.15)
        if cached:
            textbox(slide, x + 0.32, store_y, 2.2, store_h, "存储系统", 15, True, GOLD, anchor=MSO_ANCHOR.MIDDLE)
            textbox(slide, x + 2.40, store_y, w - 2.80, store_h, "同一份只被读 1 次", 15, True, GOLD, PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        else:
            textbox(slide, x + 0.32, store_y, 2.2, store_h, "存储系统", 15, True, GOLD, anchor=MSO_ANCHOR.MIDDLE)
            textbox(slide, x + 2.40, store_y, w - 2.80, store_h, "同一份被读 4 次", 15, True, AMBER, PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)

        note_y = 6.06
        rect(slide, x, note_y, w, 0.98, SOFT, LINE, 1.0)
        if cached:
            lines = "1   请求 1 穿过交换机，到存储读 117 MB\n2   回程时写进交换 HBM\n3   请求 2、3、4 在交换机命中，不再往下"
            note_color = TEAL
        else:
            lines = "1   四张 P 卡各发一次读\n2   四次都穿过交换芯片\n3   四次都落到存储，HBM 不留"
            note_color = AMBER
        textbox(slide, x + 0.16, note_y + 0.06, w - 0.32, 0.86, lines, 13, False, note_color, anchor=MSO_ANCHOR.MIDDLE)
    return slide


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "共享前缀交换cache"
    prs.core_properties.subject = "同一条前缀：每张 P 卡读存储，或第一份留在交换 HBM"
    slide_topology(prs)
    slide_paths(prs)
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
