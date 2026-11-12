#!/usr/bin/env python3
"""One slide: agent KV lookup is a radix prefix tree.

Redrawn from the public RadixAttention description. The tree is not a
copy of the LMSYS figure. LMSYS Org, "Fast and Expressive LLM Inference
with RadixAttention and SGLang", 2024-01-17, Figures 3 and 4:
https://www.lmsys.org/blog/2024-01-17-sglang/

vLLM stores the same prefix relation as a parent-hash chain rather than
an explicit tree:
https://docs.vllm.ai/en/stable/design/prefix_caching/
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

OUT = "/agent/repos/ucl-mpcomm/docs/KV前缀树.pptx"
FOOTER = "KV 前缀树    ·    按 LMSYS RadixAttention 2024-01-17 的基数树重画    ·    vLLM 用父块哈希表达同一条链"


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


def solid(shape, fill, line=None, line_pt=1.25):
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


def rect(slide, x, y, w, h, fill, line=None, line_pt=1.25, rounded=True):
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line, line_pt)
    if rounded:
        shape.adjustments[0] = 0.12
    return shape


def hbar(slide, x, y, w, color=ACCENT):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y - 0.013), Inches(w), Inches(0.026)
    )
    solid(shape, color)
    return shape


def vbar(slide, x, y, h, color=ACCENT):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x - 0.013), Inches(y), Inches(0.026), Inches(h)
    )
    solid(shape, color)
    return shape


def node(slide, x, y, w, h, title, sub, fill, line, title_c, sub_c):
    rect(slide, x, y, w, h, fill, line, 1.5)
    textbox(slide, x + 0.06, y + 0.06, w - 0.12, h * 0.48, title, 13, True, title_c, PP_ALIGN.CENTER, MSO_ANCHOR.BOTTOM)
    textbox(slide, x + 0.06, y + h * 0.50, w - 0.12, h * 0.42, sub, 11, False, sub_c, PP_ALIGN.CENTER, MSO_ANCHOR.TOP)


def trunk(slide, parent_right, parent_cy, child_left, child_cys):
    trunk_x = (parent_right + child_left) / 2
    hbar(slide, parent_right, parent_cy, trunk_x - parent_right)
    top = min(child_cys)
    bot = max(child_cys)
    if bot > top:
        vbar(slide, trunk_x, top, bot - top)
    for cy in child_cys:
        hbar(slide, trunk_x, cy, child_left - trunk_x)


def card(slide, x, y, w, h, index, title, body):
    rect(slide, x, y, w, h, WHITE, LINE, 1.0)
    circ = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.14), Inches(y + 0.14), Inches(0.32), Inches(0.32))
    solid(circ, NAVY)
    textbox(slide, x + 0.14, y + 0.14, 0.32, 0.32, index, 12, True, WHITE, PP_ALIGN.CENTER)
    textbox(slide, x + 0.54, y + 0.12, w - 0.70, 0.34, title, 14, True, NAVY)
    textbox(slide, x + 0.16, y + 0.52, w - 0.32, h - 0.64, body, 12, False, INK, anchor=MSO_ANCHOR.TOP)


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Agent 任务的 KV 查找是一棵前缀树"
    prs.core_properties.subject = "RadixAttention prefix tree, redrawn from LMSYS 2024-01-17"
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    notes = slide.notes_slide.notes_text_frame
    notes.text = (
        "Redrawn from LMSYS Org, Fast and Expressive LLM Inference with "
        "RadixAttention and SGLang, 2024-01-17, Figures 3 and 4. "
        "https://www.lmsys.org/blog/2024-01-17-sglang/\n"
        "vLLM automatic prefix caching stores the same parent-before-child "
        "relation as a block hash that includes the parent hash, without an "
        "explicit tree. https://docs.vllm.ai/en/stable/design/prefix_caching/"
    )

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.40, 0.14, 10.4, 0.24, "公开材料    ·    SGLang RadixAttention    ·    2024-01-17", 12, True, ACCENT)
    textbox(slide, 11.2, 0.14, 1.72, 0.24, "1  /  1", 12, False, MUTED, PP_ALIGN.RIGHT)
    textbox(slide, 0.40, 0.38, 12.5, 0.40, "Agent 任务的 KV 查找是一棵前缀树", 26, True, NAVY)
    textbox(
        slide,
        0.40,
        0.80,
        12.5,
        0.28,
        "基数树把多条任务收成一条前缀链。每条边是一段连续 token，边上挂着这段的 KV。",
        13,
        False,
        MUTED,
    )

    legend = [
        (TEAL, "共享前缀，KV 只留一份"),
        (ACCENT, "该任务私有"),
        (AMBER, "含模型输出，下一轮可复用"),
    ]
    legend_x = [0.40, 3.55, 6.55]
    legend_w = [2.90, 2.70, 4.20]
    for (color, label), x, w in zip(legend, legend_x, legend_w):
        rect(slide, x, 1.18, 0.18, 0.18, color, None, rounded=False)
        textbox(slide, x + 0.26, 1.12, w, 0.28, label, 12, False, INK)

    rect(slide, 0.40, 1.50, 8.72, 4.58, WHITE, LINE, 1.0)
    textbox(
        slide,
        0.56,
        1.58,
        8.40,
        0.30,
        "T1、T2 共享到「工具说明」，T3 只共享「系统提示」。框内文字是边上的 token 段。",
        12,
        False,
        MUTED,
    )

    # Shifted below the caption. Each parent sits on the midline of its children.
    root = (0.58, 3.76, 0.76, 0.76)  # cy 4.14
    sys = (1.78, 3.68, 1.92, 0.92)  # cy 4.14
    tool = (4.28, 2.50, 1.96, 0.84)  # cy 2.92
    alt = (4.28, 4.94, 1.96, 0.84)  # cy 5.36
    qa = (6.78, 1.98, 2.12, 0.78)  # cy 2.37
    qb = (6.78, 3.00, 2.12, 0.78)  # cy 3.39
    qc = (6.78, 4.97, 2.12, 0.78)  # cy 5.36

    trunk(slide, root[0] + root[2], 4.14, sys[0], [4.14])
    trunk(slide, sys[0] + sys[2], 4.14, tool[0], [2.92, 5.36])
    trunk(slide, tool[0] + tool[2], 2.92, qa[0], [2.37, 3.39])
    trunk(slide, alt[0] + alt[2], 5.36, qc[0], [5.36])

    oval = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(root[0]), Inches(root[1]), Inches(root[2]), Inches(root[3]))
    solid(oval, NAVY)
    textbox(slide, root[0], root[1], root[2], root[3], "根", 14, True, WHITE, PP_ALIGN.CENTER)

    node(slide, *sys, "系统提示", "T1 · T2 · T3 共用", PALE, TEAL, TEAL, TEAL)
    node(slide, *tool, "工具说明", "T1 · T2 共用", PALE, TEAL, TEAL, TEAL)
    node(slide, *alt, "另一套工具", "仅 T3", SOFT, ACCENT, NAVY, MUTED)
    node(slide, *qa, "问题 A → 回答 A", "仅 T1", GOLD_BG, AMBER, GOLD, GOLD)
    node(slide, *qb, "问题 B", "仅 T2", SOFT, ACCENT, NAVY, MUTED)
    node(slide, *qc, "问题 C", "仅 T3", SOFT, ACCENT, NAVY, MUTED)

    card(
        slide,
        9.28,
        1.50,
        3.64,
        1.42,
        "1",
        "匹配最长前缀",
        "从根沿边往下走。T2 停在「工具说明」，这段 KV 直接复用；「问题 B」现算后成为新叶子。",
    )
    card(
        slide,
        9.28,
        3.08,
        3.64,
        1.42,
        "2",
        "一个父节点，多个读者",
        "「问题 A」和「问题 B」的父前缀都是「工具说明」。每个节点只有一个父节点，读者可以有多个。",
    )
    card(
        slide,
        9.28,
        4.66,
        3.64,
        1.42,
        "3",
        "边可以从中间拆开",
        "新请求只对上一段 token 的前半时，这条边拆成两截。前半继续共享，后半和新后缀各成一支。",
    )

    box = rect(slide, 0.40, 6.20, 12.52, 0.84, GOLD_BG, None, rounded=True)
    box.adjustments[0] = 0.08
    textbox(
        slide,
        0.56,
        6.28,
        12.20,
        0.68,
        "LMSYS《RadixAttention》2024-01-17，Figure 3 与 Figure 4：边是一段 token，树在 CPU，KV 在 GPU，LRU 从叶子淘汰。\n"
        "vLLM 用父块哈希表达同一条前缀链。lmsys.org/blog/2024-01-17-sglang    ·    docs.vllm.ai/en/stable/design/prefix_caching",
        12,
        False,
        GOLD,
        anchor=MSO_ANCHOR.MIDDLE,
    )

    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.40), Inches(7.16), Inches(12.52), Inches(0.012))
    solid(rule, LINE)
    textbox(slide, 0.40, 7.18, 12.52, 0.24, FOOTER, 11, False, MUTED)

    prs.save(OUT)


if __name__ == "__main__":
    build()
