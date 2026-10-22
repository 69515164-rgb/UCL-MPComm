#!/usr/bin/env python3
"""Shared bus DDR pool: what decode asks the master, and how often."""

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


def rgb(hex_color):
    return RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def set_run_font(run, size, bold, color, name=FONT):
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
        shape.line.width = Pt(1)
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


def node(slide, x, y, w, h, title, sub, fill, title_color):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, LINE)
    textbox(slide, x + 0.12, y + 0.06, w - 0.24, 0.32, title, 15, True, title_color, PP_ALIGN.CENTER)
    textbox(slide, x + 0.12, y + 0.36, w - 0.24, h - 0.44, sub, 12, False, INK, PP_ALIGN.CENTER, MSO_ANCHOR.TOP)


def arrow_row(slide, col_x, col_w, y, text, color):
    label_w = 3.55
    group = 0.22 + 0.08 + label_w
    x = col_x + (col_w - group) / 2
    arrow = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y + 0.08), Inches(0.22), Inches(0.28))
    solid(arrow, color)
    textbox(slide, x + 0.30, y, label_w, 0.44, text, 13, True, color, anchor=MSO_ANCHOR.MIDDLE)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "DDR 池直挂总线时 Decode 与 Master 的交互"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.42, 0.14, 10.4, 0.22, "Decode    ·    DDR 池直挂总线    ·    拉高 batch", 12, True, ACCENT)
    textbox(slide, 0.42, 0.36, 11.6, 0.40, "每次都问 Master，换入换出会被控制面堵住", 24, True, NAVY)
    textbox(slide, 11.4, 0.16, 1.5, 0.22, "1  /  1", 12, False, MUTED, PP_ALIGN.RIGHT)

    banner = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(0.84), Inches(12.5), Inches(0.40))
    solid(banner, PALE)
    textbox(
        slide,
        0.56,
        0.84,
        12.22,
        0.40,
        "HBM 只留当前 batch 的工作集。其余 KV 在直挂总线的 DDR 池。KV 字节走 DMA，Master 只发池内偏移和租约。",
        14,
        True,
        TEAL,
    )

    col_w = 6.16
    left = 0.42
    right = 6.76
    head_y = 1.36
    for x, title, fill in (
        (left, "每次 swap 都问    控制面堵住 DMA", NAVY),
        (right, "块还在池里    只查卡上的块表", TEAL),
    ):
        head = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(head_y), Inches(col_w), Inches(0.34))
        solid(head, fill)
        textbox(slide, x + 0.14, head_y, col_w - 0.28, 0.34, title, 14, True, WHITE)

    nw = col_w - 0.32
    nx = left + 0.16
    node(slide, nx, 1.82, nw, 0.72, "Decode 卡", "要换入或换出一块 KV", SOFT, NAVY)
    arrow_row(slide, left, col_w, 2.54, "块 id，字节数，换入或换出", NAVY)
    node(slide, nx, 3.00, nw, 0.72, "Master", "查目录，分配或续租", SOFT, NAVY)
    arrow_row(slide, left, col_w, 3.72, "池内偏移，长度，租约", NAVY)
    node(slide, nx, 4.18, nw, 0.72, "Decode 卡", "拿到地址后才发 DMA", SOFT, NAVY)
    arrow_row(slide, left, col_w, 4.90, "KV 字节，走总线", TEAL)
    node(slide, nx, 5.36, nw, 0.72, "DDR 池", "按偏移读写这块 KV", PALE, TEAL)

    rx = right + 0.16
    node(slide, rx, 1.82, nw, 0.92, "Decode 卡 · 块表", "已有池内偏移、长度和租约", PALE, TEAL)
    arrow_row(slide, right, col_w, 2.78, "KV 字节，走总线", TEAL)
    node(slide, rx, 3.26, nw, 0.84, "DDR 池", "按块表里的偏移读写", PALE, TEAL)
    idle = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(rx), Inches(4.26), Inches(nw), Inches(1.82))
    solid(idle, SOFT, LINE)
    textbox(slide, rx + 0.16, 4.36, nw - 0.32, 0.32, "Master", 15, True, MUTED, PP_ALIGN.CENTER)
    textbox(
        slide,
        rx + 0.20,
        4.72,
        nw - 0.40,
        1.20,
        "这次没有消息。租约未到期，块也未被释放。\n再问一次，返回的仍是块表里的同一行。",
        14,
        False,
        INK,
        PP_ALIGN.CENTER,
        MSO_ANCHOR.TOP,
    )

    foot = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.46), Inches(12.5), Inches(0.66))
    solid(foot, GOLD_BG)
    textbox(
        slide,
        0.56,
        6.46,
        12.22,
        0.66,
        "有必要再问的时机：新块第一次进池、块从池中释放、租约到期。\n"
        "一块 4 MB、总线 64 GB/s 时 DMA 约 0.06 ms。一次往返按 0.2 ms 计，多卡排队后更长，先于总线饱和。",
        13,
        False,
        GOLD,
    )
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.20), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(
        slide,
        0.42,
        7.22,
        12.5,
        0.22,
        "跨卡共享的 DDR 池才设 Master    ·    单机进程内的 host DDR 块表不走这跳    ·    0.06 ms / 0.2 ms 是估算量级",
        11,
        False,
        MUTED,
    )
    slide.notes_slide.notes_text_frame.text = (
        "这页描述的是一个为拉高 batch 而把 DDR 池做成跨卡共享、并由 Master 发放池内偏移的设计。"
        "数据面是 Decode 卡经总线对 DDR 池做 DMA，KV 字节不进 Master。"
        "控制面每次如果都走，Decode 送出块 id、字节数、换入或换出；Master 返回池内偏移、长度、租约。"
        "地址写进卡上块表之后，租约未到期且块未被释放时，换入换出只查块表。"
        "有必要再问 Master 的是三类事件：新块第一次进池、块从池中释放、租约到期。"
        "估算：4 MB / 64 GB/s 约 0.06 ms。不排队的一次 RPC 按 0.2 ms。一步 20 ms、batch 32、每请求换入换出各一块时，"
        "单卡约 3200 次/秒；8 卡约 2.6 万次/秒，单线程 Master 按 50 us 服务约 2 万次/秒，队列会涨。"
        "当前 vLLM OffloadingConnector 与 SGLang HiCache L2 的 host DDR 是进程内块表，路径上没有这跳 Master。"
        "MooncakeStore 的 PutStart / GetReplicaList 用在跨节点对象池的写入和未命中读取，不是每个 decode step 的换入换出。"
    )
    out = "/workspace/docs/ddr-pool-master-swap.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
