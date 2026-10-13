#!/usr/bin/env python3
"""Editable logic diagram of the NVIDIA STX storage rack connections."""

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


def link(slide, x1, y1, x2, y2, color):
    shape = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(2.25)
    ln = shape.line._get_or_add_ln()
    tail = OxmlElement("a:tailEnd")
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "sm")
    ln.append(tail)
    return shape


def chip(slide, x, y, w, h, fill, text, fg=NAVY):
    box(slide, x, y, w, h, fill, text, 11, True, fg, line=fill)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "NVIDIA STX 存储机架连线"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.32, 0.12, 12.6, 0.20, "NVIDIA Vera Rubin POD  ·  BlueField-4 STX", 12, True, ACCENT)
    textbox(slide, 0.32, 0.32, 12.7, 0.32, "每条线是一种连接：托盘内 NVMe，机架内铜缆，出机架单层光", 20, True, NAVY)
    box(slide, 0.32, 0.70, 0.07, 0.32, ACCENT, "")
    textbox(
        slide,
        0.48,
        0.66,
        12.5,
        0.38,
        "两条托盘的铜缆汇进同一条 Spine。交换机后端口接 Spine，前置光口离开机架，再接到计算节点。",
        14,
        True,
        INK,
    )

    # Geometry. Lines are drawn after the nodes so the arrow meets the box edge.
    nvme_x, nvme_w = 0.40, 1.42
    bf_x, bf_w = 2.48, 2.28
    spine_x, spine_w = 6.05, 1.18
    sw_x, sw_w = 7.78, 1.32
    row_h = 1.18
    rows = (1.48, 2.86)
    cy = [y + row_h / 2 for y in rows]

    box(slide, 0.26, 1.22, 9.00, 3.05, RACK, line=ACCENT)
    textbox(slide, 0.38, 1.24, 5.6, 0.20, "机架内  ·  MGX ETL", 11, True, ACCENT)

    for i, y in enumerate(rows):
        box(slide, nvme_x, y, nvme_w, row_h, GOLD, "")
        textbox(slide, nvme_x + 0.08, y + 0.08, nvme_w - 0.16, 0.26, "NVMe 闪存", 13, True, WHITE)
        textbox(slide, nvme_x + 0.08, y + 0.36, nvme_w - 0.16, 0.72, f"托盘 {i + 1}\nKV 介质\nG3.5", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)

        box(slide, bf_x, y, bf_w, row_h, WHITE, line=LINE)
        box(slide, bf_x, y, 0.07, row_h, TEAL, "")
        textbox(slide, bf_x + 0.14, y + 0.04, bf_w - 0.22, 0.22, "BlueField-4 STX", 12, True, TEAL)
        box(slide, bf_x + 0.14, y + 0.28, bf_w - 0.24, 0.38, (232, 243, 242), "")
        textbox(slide, bf_x + 0.18, y + 0.28, bf_w - 0.32, 0.38, "Vera CPU    DOCA Memos", 11, True, NAVY)
        box(slide, bf_x + 0.14, y + 0.78, bf_w - 0.24, 0.34, (226, 236, 246), "")
        textbox(slide, bf_x + 0.18, y + 0.78, bf_w - 0.32, 0.34, "ConnectX-9    数据面", 11, True, NAVY)
        link(slide, bf_x + 0.55, y + 0.66, bf_x + 0.55, y + 0.78, TEAL)
        textbox(slide, bf_x + 0.68, y + 0.62, 0.70, 0.18, "片内", 10, True, TEAL, align=PP_ALIGN.LEFT)

    box(slide, spine_x, rows[0], spine_w, rows[1] + row_h - rows[0], NAVY, "")
    textbox(slide, spine_x + 0.06, rows[0] + 0.12, spine_w - 0.12, 2.2, "铜质\nSpine\n\n预集成\n线缆盒\n\n多对多\n一层网络", 12, True, WHITE, anchor=MSO_ANCHOR.TOP)

    box(slide, sw_x, 1.85, sw_w, 1.85, ACCENT, "")
    textbox(slide, sw_x + 0.06, 1.95, sw_w - 0.12, 1.65, "Spectrum-6\n交换机托盘\n机架中部\n\n后端口入\n前置光口出", 12, True, WHITE, anchor=MSO_ANCHOR.TOP)

    # Outside the rack, same vertical rhythm so the optical line stays straight.
    out_x, out_w = 9.55, 3.50
    box(slide, out_x, 1.22, out_w, 5.55, WHITE, line=OPTIC)
    textbox(slide, out_x + 0.12, 1.26, out_w - 0.24, 0.20, "机架外", 11, True, OPTIC)
    spx_y, spx_h = 1.85, 1.15
    comp_y, comp_h = 3.55, 1.25
    hbm_y, hbm_h = 5.30, 1.15
    box(slide, out_x + 0.36, spx_y, out_w - 0.54, spx_h, OPTIC, "")
    textbox(slide, out_x + 0.46, spx_y + 0.08, out_w - 0.74, 0.28, "Spectrum-6 SPX", 14, True, WHITE)
    textbox(slide, out_x + 0.46, spx_y + 0.40, out_w - 0.74, 0.64, "POD 内机架互联\n东西向与南北向", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)
    box(slide, out_x + 0.18, comp_y, out_w - 0.36, comp_h, TEAL, "")
    textbox(slide, out_x + 0.28, comp_y + 0.08, out_w - 0.56, 0.28, "计算节点 BlueField-4", 14, True, WHITE)
    textbox(slide, out_x + 0.28, comp_y + 0.40, out_w - 0.56, 0.74, "KV I/O 平面\n终结 NVMe-oF 与对象 RDMA", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)
    box(slide, out_x + 0.18, hbm_y, out_w - 0.36, hbm_h, GREEN, "")
    textbox(slide, out_x + 0.28, hbm_y + 0.08, out_w - 0.56, 0.28, "Rubin GPU  HBM", 14, True, WHITE)
    textbox(slide, out_x + 0.28, hbm_y + 0.40, out_w - 0.56, 0.64, "热 KV\n解码前从 CMX 预取", 12, False, WHITE, anchor=MSO_ANCHOR.TOP)

    # Labeled wires. Chips sit on the open part of each segment.
    for y in cy:
        link(slide, nvme_x + nvme_w, y, bf_x, y, GOLD)
        link(slide, bf_x + bf_w, y, spine_x, y, TEAL)
    chip(slide, 1.86, 2.55, 0.58, 0.24, WHITE, "NVMe", GOLD)
    chip(slide, 4.82, 2.48, 1.16, 0.40, WHITE, "200 Gb/s\n铜缆", TEAL)

    sw_cy = 1.85 + 1.85 / 2
    link(slide, spine_x + spine_w, sw_cy, sw_x, sw_cy, NAVY)
    chip(slide, 7.18, sw_cy - 0.36, 0.58, 0.28, WHITE, "后端口", NAVY)

    spx_cy = spx_y + spx_h / 2
    link(slide, sw_x + sw_w, spx_cy, out_x + 0.36, spx_cy, OPTIC)
    chip(slide, 9.12, spx_cy - 0.20, 0.76, 0.40, WHITE, "32×OSFP\n单层光", OPTIC)

    mid_x = out_x + out_w / 2
    link(slide, mid_x, spx_y + spx_h, mid_x, comp_y, OPTIC)
    chip(slide, mid_x + 0.12, (spx_y + spx_h + comp_y) / 2 - 0.14, 0.62, 0.26, WHITE, "RDMA", OPTIC)
    link(slide, mid_x, comp_y + comp_h, mid_x, hbm_y, GREEN)
    chip(slide, mid_x + 0.12, (comp_y + comp_h + hbm_y) / 2 - 0.14, 0.72, 0.26, WHITE, "KV 预取", GREEN)

    textbox(
        slide,
        0.32,
        6.92,
        12.7,
        0.40,
        "片内连线在 BlueField-4 的 Vera CPU 与 ConnectX-9 之间。托盘数和盘数公开材料没有给出，图中两条托盘只代表接法。STX 用的是 Spectrum-X 铜缆，不是 NVLink。",
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
