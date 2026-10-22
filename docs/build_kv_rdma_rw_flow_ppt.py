#!/usr/bin/env python3
"""Editable flow of Mooncake TransferEngine READ vs WRITE. Not a sequence chart."""

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


def chrome(slide):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.42, 0.14, 10.2, 0.26, "TransferEngine    ·    单边 RDMA    ·    READ / WRITE", 12, True, ACCENT)
    textbox(slide, 0.42, 0.38, 12.5, 0.40, "两次交互都由本端发起，完成也回到本端", 26, True, NAVY)
    textbox(slide, 11.4, 0.16, 1.5, 0.24, "1  /  1", 12, False, MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    solid(rule, LINE)
    textbox(
        slide,
        0.42,
        7.20,
        12.5,
        0.24,
        "RC 事先建好    ·    slice 默认 64 KB    ·    WR 的 imm_data 为 0    ·    对端 CPU 不读 TransferRequest",
        11,
        False,
        MUTED,
    )


def flow(slide, y, title, tint, fill, actors, labels, back):
    head = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(y), Inches(12.5), Inches(0.32))
    solid(head, tint)
    textbox(slide, 0.56, y, 12.2, 0.32, title, 14, True, WHITE)

    box_w, box_h, arrow_w = 1.86, 0.78, 0.52
    x0 = 0.50
    box_y = y + 0.68
    for i, (name, sub) in enumerate(actors):
        x = x0 + i * (box_w + arrow_w)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(box_y), Inches(box_w), Inches(box_h))
        solid(card, fill, LINE)
        textbox(slide, x + 0.08, box_y + 0.08, box_w - 0.16, 0.32, name, 14, True, tint, PP_ALIGN.CENTER)
        textbox(slide, x + 0.08, box_y + 0.40, box_w - 0.16, 0.30, sub, 11, False, MUTED, PP_ALIGN.CENTER)
        if i < len(labels):
            ax = x + box_w
            arrow = slide.shapes.add_shape(
                MSO_SHAPE.RIGHT_ARROW, Inches(ax + 0.06), Inches(box_y + 0.28), Inches(arrow_w - 0.12), Inches(0.20)
            )
            solid(arrow, tint)
            textbox(slide, ax - 0.22, box_y - 0.30, arrow_w + 0.44, 0.28, labels[i], 10, True, tint, PP_ALIGN.CENTER)

    note = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(box_y + box_h + 0.08), Inches(12.5), Inches(0.40)
    )
    solid(note, fill)
    textbox(slide, 0.56, box_y + box_h + 0.08, 12.22, 0.40, back, 12, False, INK)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "TransferEngine READ 与 WRITE 的交互"
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide)
    banner = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(0.86), Inches(12.5), Inches(0.40))
    solid(banner, PALE)
    textbox(
        slide,
        0.56,
        0.86,
        12.22,
        0.40,
        "内存注册、rkey 公布和 QP 交换只做一次。下面每次 KV 访问都走已经建好的 RC。",
        14,
        True,
        TEAL,
    )

    actors = [
        ("调用方", "填好本次请求"),
        ("本端引擎", "切 slice，提交前控速"),
        ("本端网卡", "post WR，收 CQ"),
        ("对端网卡", "只做 DMA"),
        ("对端内存", "已注册的 DDR"),
    ]
    flow(
        slide,
        1.36,
        "READ    本端把远端 KV 拉回本地缓冲",
        NAVY,
        SOFT,
        actors,
        ["READ 请求", "RDMA READ", "地址 + rkey", "读出字节"],
        "返回：字节由对端网卡送回本端网卡，写入本地 source。CQ 在本端，调用方得到 COMPLETED。对端没有软件响应。",
    )
    flow(
        slide,
        3.78,
        "WRITE    本端把本地 KV 推进远端内存",
        TEAL,
        PALE,
        actors,
        ["WRITE 请求", "RDMA WRITE", "数据 + rkey", "写入字节"],
        "返回：对端网卡写完注册内存即结束。CQ 仍在本端，调用方得到 COMPLETED。对端没有软件响应。",
    )
    foot = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(6.22), Inches(12.5), Inches(0.82))
    solid(foot, GOLD_BG)
    textbox(
        slide,
        0.58,
        6.28,
        12.18,
        0.70,
        "控速点在本端引擎，post WR 之前。target_rate 加在 TransferRequest 上，只有这一侧读得到。\n"
        "READ 的速率是本端拉取的速度，WRITE 的速率是本端推送的速度。对端网卡按 rkey 搬运，不解析这个字段。",
        14,
        False,
        GOLD,
    )
    slide.notes_slide.notes_text_frame.text = (
        "这页是交互关系，不是时序图。参与者从左到右：调用方、本端 TransferEngine、本端网卡、对端网卡、对端已注册内存。"
        "建链一次：register 内存，元数据公布 addr、length、rkey；首次通信交换 QP，建成 RC。"
        "READ：调用方提交 opcode=READ、source、target_id、target_offset、length。"
        "引擎按默认 64KB 切 slice，选网卡，ibv_post_send 的 opcode 为 IBV_WR_RDMA_READ，imm_data=0。"
        "WR 里是本地地址和 lkey、远端地址和 rkey、长度。对端网卡从注册内存读出字节送回，本端写入 source。"
        "完成队列在本端，getTransferStatus 看到全部 slice 完成后返回 COMPLETED。"
        "WRITE：opcode=WRITE，source 是要推出去的 KV。WR 为 IBV_WR_RDMA_WRITE，数据随 WR 到对端网卡，写入 dest_addr。"
        "对端 CPU 不读 TransferRequest，也没有软件层的响应报文。"
        "因此 target_rate 只能由本端引擎在 post 之前用来放行 slice。READ 控的是拉取速度，WRITE 控的是推送速度。"
    )
    out = "/workspace/docs/kv-rdma-rw-flow.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
