#!/usr/bin/env python3
"""Editable logic diagram of the NVIDIA STX storage rack connections."""

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
GOLD = (122, 84, 28)
GREEN = (27, 110, 72)
LINE = (214, 220, 226)
SOFT = (244, 247, 250)
RACK = (232, 240, 246)
OPTIC = (88, 62, 130)


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
    tf.margin_left = Inches(0.05)
    tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
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


def arrow(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill)
    return shape


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "NVIDIA STX 存储机架内部连接"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.32, 0.14, 12.6, 0.20, "NVIDIA Vera Rubin POD  ·  BlueField-4 STX", 12, True, ACCENT)
    textbox(slide, 0.32, 0.34, 12.7, 0.34, "盘只进本托盘的 BlueField-4，托盘之间只经过铜质 Spine", 22, True, NAVY)
    box(slide, 0.32, 0.76, 0.07, 0.34, ACCENT, "")
    textbox(
        slide,
        0.48,
        0.72,
        12.5,
        0.40,
        "出机架只有交换机托盘前置的光口。单层光连到 Spectrum-6 SPX，再接到计算节点上的 BlueField-4。",
        14,
        True,
        INK,
    )

    # Rack interior.
    rack_x, rack_y, rack_w, rack_h = 0.28, 1.22, 9.05, 4.05
    box(slide, rack_x, rack_y, rack_w, rack_h, RACK, line=ACCENT)
    textbox(slide, rack_x + 0.12, rack_y + 0.04, 6.2, 0.24, "STX 存储机架内部  ·  MGX ETL，Spectrum-X 铜质 Spine", 12, True, ACCENT)

    rows = (1.56, 3.22)
    nvme_x, nvme_w, row_h = 0.44, 1.48, 1.52
    bf_x, bf_w = 2.22, 2.72
    spine_x, spine_w = 5.28, 1.42
    sw_x, sw_w = 7.02, 2.12
    for i, y in enumerate(rows):
        box(slide, nvme_x, y, nvme_w, row_h, GOLD, "", line=None)
        textbox(slide, nvme_x + 0.08, y + 0.10, nvme_w - 0.16, 0.28, "NVMe 闪存", 14, True, WHITE)
        textbox(slide, nvme_x + 0.08, y + 0.42, nvme_w - 0.16, 0.96, "本托盘的 KV 介质。\nG3.5 上下文层。\n不直接上交换机。", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)
        arrow(slide, nvme_x + nvme_w + 0.04, y + 0.62, 0.22, 0.22, GOLD)
        textbox(slide, nvme_x + nvme_w - 0.02, y + row_h - 0.28, 0.70, 0.22, "NVMe", 10, True, GOLD, align=PP_ALIGN.CENTER)

        box(slide, bf_x, y, bf_w, row_h, WHITE, line=LINE)
        box(slide, bf_x, y, 0.08, row_h, TEAL, "")
        textbox(slide, bf_x + 0.16, y + 0.06, bf_w - 0.24, 0.24, f"存储托盘 {i + 1}  ·  BlueField-4 STX", 12, True, TEAL)
        box(slide, bf_x + 0.16, y + 0.36, bf_w - 0.28, 0.50, (232, 243, 242), "")
        textbox(slide, bf_x + 0.22, y + 0.36, bf_w - 0.40, 0.50, "Vera CPU\nDOCA Memos：KV 放置与存储服务", 11, False, NAVY, anchor=MSO_ANCHOR.MIDDLE)
        box(slide, bf_x + 0.16, y + 0.92, bf_w - 0.28, 0.50, (226, 236, 246), "")
        textbox(slide, bf_x + 0.22, y + 0.92, bf_w - 0.40, 0.50, "ConnectX-9 SuperNIC\nNVMe-oF / RDMA，加密与 CRC", 11, False, NAVY, anchor=MSO_ANCHOR.MIDDLE)
        arrow(slide, bf_x + bf_w + 0.04, y + 0.62, 0.26, 0.22, TEAL)

    box(slide, spine_x, rows[0], spine_w, rows[1] + row_h - rows[0], NAVY, "")
    textbox(slide, spine_x + 0.08, rows[0] + 0.16, spine_w - 0.16, 2.6, "铜质 Spine\n\n预集成线缆盒\n\n后端口进来\n\n托盘之间\n多对多\n\n仍是一层网络", 12, True, WHITE, anchor=MSO_ANCHOR.TOP)
    arrow(slide, spine_x + spine_w + 0.04, rows[0] + 1.35, 0.24, 0.22, NAVY)

    box(slide, sw_x, rows[0], sw_w, rows[1] + row_h - rows[0], ACCENT, "")
    textbox(
        slide,
        sw_x + 0.10,
        rows[0] + 0.12,
        sw_w - 0.20,
        2.9,
        "Spectrum-6\n1U 交换机托盘\n机架中部\n\n后端口\n接铜质 Spine\n\n前置 32 个 OSFP\n光口朝机架外",
        13,
        True,
        WHITE,
        anchor=MSO_ANCHOR.TOP,
    )

    # Outside the rack.
    out_x, out_w = 9.52, 3.52
    box(slide, out_x, rack_y, out_w, rack_h, WHITE, line=OPTIC)
    textbox(slide, out_x + 0.12, rack_y + 0.04, out_w - 0.24, 0.24, "机架外  ·  单层光", 12, True, OPTIC)
    box(slide, out_x + 0.14, 1.58, out_w - 0.28, 0.95, OPTIC, "")
    textbox(slide, out_x + 0.22, 1.62, out_w - 0.44, 0.28, "Spectrum-6 SPX 机架", 13, True, WHITE)
    textbox(slide, out_x + 0.22, 1.92, out_w - 0.44, 0.52, "POD 内机架到机架。\n东西向与南北向都从这里走。", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)
    arrow(slide, out_x + 1.55, 2.58, 0.28, 0.20, OPTIC)
    box(slide, out_x + 0.14, 2.84, out_w - 0.28, 1.05, TEAL, "")
    textbox(slide, out_x + 0.22, 2.88, out_w - 0.44, 0.26, "计算节点 BlueField-4", 13, True, WHITE)
    textbox(slide, out_x + 0.22, 3.16, out_w - 0.44, 0.64, "KV I/O 平面。\n终结 NVMe-oF 与对象 RDMA。", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)
    arrow(slide, out_x + 1.55, 3.94, 0.28, 0.20, GREEN)
    box(slide, out_x + 0.14, 4.20, out_w - 0.28, 0.88, GREEN, "")
    textbox(slide, out_x + 0.22, 4.24, out_w - 0.44, 0.26, "Rubin GPU  HBM", 13, True, WHITE)
    textbox(slide, out_x + 0.22, 4.52, out_w - 0.44, 0.48, "热 KV。解码前由 CMX 预取回来。", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)

    # Optical hop label on the rack boundary.
    textbox(slide, 8.55, 4.55, 1.55, 0.55, "32×OSFP\n单层光", 11, True, OPTIC, align=PP_ALIGN.CENTER)

    notes = (
        (GOLD, "盘到处理器", "NVMe 只接到本托盘的 BlueField-4。Vera CPU 跑 DOCA Memos，ConnectX-9 走数据面。"),
        (NAVY, "机架内铜缆", "200 Gb/s 通道经多台 Spectrum-6 交换机扇出。托盘之间多对多，仍然是一层网络。"),
        (OPTIC, "机架外光缆", "BlueField-4 STX 对计算侧的端口最高 800 Gb/s。计算侧由 Dynamo 与 NIXL 安排 KV 预取。"),
    )
    card_y, card_h, card_gap = 5.42, 1.38, 0.12
    card_w = (12.77 - 2 * card_gap) / 3
    for i, (color, title, body) in enumerate(notes):
        x = 0.28 + i * (card_w + card_gap)
        box(slide, x, card_y, card_w, card_h, WHITE, line=LINE)
        box(slide, x, card_y, card_w, 0.08, color, "")
        textbox(slide, x + 0.14, card_y + 0.16, card_w - 0.28, 0.26, title, 14, True, color)
        textbox(slide, x + 0.14, card_y + 0.46, card_w - 0.28, 0.82, body, 13, False, INK, anchor=MSO_ANCHOR.TOP)

    textbox(
        slide,
        0.32,
        6.88,
        12.7,
        0.42,
        "托盘数和每托盘盘数公开架构没有给出，图中只画两条托盘代表接法。STX 是 MGX ETL 存储机架，不是 NVLink 计算域。",
        12,
        False,
        MUTED,
    )

    slide.notes_slide.notes_text_frame.text = (
        "依据 NVIDIA Vera Rubin POD 技术博客（2026-03-19）与 CMX 技术博客（2026-03-16），"
        "以及 BlueField-4 STX 存储处理器产品说明。"
        "STX 存储机架基于 MGX ETL，Spine 为 Spectrum-X 以太网铜缆，不是 NVLink。"
        "1U Spectrum-6 交换机托盘位于机架中部，后端口接铜质 Spine，前置 32 个 OSFP 以单层光连接 POD 其余部分。"
        "机架内为 Spectrum-X 多平面，200 Gb/s 通道经多台交换机扇出，节点之间多对多且仍是一层网络。"
        "BlueField-4 STX 融合 Vera CPU 与 ConnectX-9，经 Spectrum-X 连接计算，每端口最高 800 Gb/s。"
        "CMX 是跑在该架构上的 G3.5 上下文层：NVMe 闪存保存可复用 KV，计算节点上的 BlueField-4 终结 NVMe-oF 与对象 RDMA。"
        "DOCA Memos 管理 KV 放置；Dynamo 与 NIXL 安排预取。Grove 按 KV 位置放置工作负载。"
        "盘数与托盘数未公开，图不标注具体个数。"
    )

    out = "/workspace/docs/stx-storage-pod.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
