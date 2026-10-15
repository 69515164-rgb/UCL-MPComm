#!/usr/bin/env python3
"""Editable layer diagram of the Ascend inference software stack."""

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
LINE = (214, 220, 226)
SOFT = (244, 247, 250)
PILL = (236, 240, 244)
HDK = (46, 74, 110)
GOLD_BG = (255, 248, 240)


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
    tf.margin_left = Inches(0.06)
    tf.margin_right = Inches(0.06)
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


def band(slide, x, y, w, h, fill, title, body, title_w=1.70):
    box(slide, x, y, title_w, h, fill, title, 13, True, WHITE)
    box(slide, x + title_w, y, w - title_w, h, fill, "")
    textbox(
        slide,
        x + title_w + 0.12,
        y,
        w - title_w - 0.20,
        h,
        body,
        13,
        False,
        WHITE,
        anchor=MSO_ANCHOR.MIDDLE,
    )


def path_rows(slide, x, y, w, h, head_fill, head, rows, control_index=None):
    box(slide, x, y, w, h, WHITE, line=LINE)
    box(slide, x, y, w, 0.34, head_fill, head, 14, True, WHITE)
    top = y + 0.42
    gap = 0.06
    row_h = (h - 0.50 - gap * (len(rows) - 1)) / len(rows)
    name_w = 1.78
    for i, (name, desc) in enumerate(rows):
        ry = top + i * (row_h + gap)
        fill = GOLD if i == control_index else head_fill
        body_fill = GOLD_BG if i == control_index else SOFT
        body_ink = INK
        box(slide, x + 0.08, ry, name_w, row_h, fill, name, 12, True, WHITE)
        box(slide, x + 0.08 + name_w, ry, w - name_w - 0.16, row_h, body_fill, "")
        textbox(
            slide,
            x + name_w + 0.18,
            ry,
            w - name_w - 0.30,
            row_h,
            desc,
            12,
            False,
            body_ink,
            anchor=MSO_ANCHOR.MIDDLE,
        )


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "昇腾推理软件栈分层"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.32, 0.16, 12.6, 0.22, "昇腾  ·  推理软件栈  ·  MindIE 3.1", 13, True, ACCENT)
    textbox(slide, 0.32, 0.40, 12.7, 0.40, "两条推理路径在 CANN 汇合，下面共用 HDK 和 NPU", 24, True, NAVY)
    textbox(
        slide,
        0.32,
        0.84,
        12.7,
        0.32,
        "新部署走 MindIE Motor，南向当前是 vLLM-Ascend。MindIE LLM 仍保留原生层次，已进入维护。",
        15,
        False,
        INK,
    )

    label_x, label_w = 0.28, 0.92
    bar_x, bar_w = 1.24, 11.76

    textbox(slide, label_x, 1.24, label_w, 0.48, "集群", 13, True, GOLD, anchor=MSO_ANCHOR.MIDDLE)
    band(
        slide,
        bar_x,
        1.24,
        bar_w,
        0.48,
        GOLD,
        "MindCluster",
        "调用链外侧。承接两条路径的 Pod、PD 分离 CRD 和故障恢复。可选 CCAE 做算存网运维。",
        title_w=1.70,
    )

    textbox(slide, label_x, 1.86, label_w, 3.22, "服务", 13, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)
    path_w = (bar_w - 0.12) / 2
    path_rows(
        slide,
        bar_x,
        1.86,
        path_w,
        3.22,
        TEAL,
        "路径 A  ·  MindIE LLM 原生引擎",
        (
            ("Server", "服务入口。Endpoint 兼容 OpenAI、vLLM、Triton、TGI。"),
            ("LLM Manager", "请求调度与 KV 池。Engine 内含 Scheduler、Block Manager。"),
            ("Text Generator", "前处理、自回归、后处理。Executor 负责跨节点下发。"),
            ("Modeling", "ATB 模型与图执行。后端为 ACLGraph 和 ATBGraph。"),
        ),
    )
    path_rows(
        slide,
        bar_x + path_w + 0.12,
        1.86,
        path_w,
        3.22,
        ACCENT,
        "路径 B  ·  MindIE Motor",
        (
            ("Coordinator", "数据面入口。路由、限流、实例隔离。"),
            ("管控面", "Controller 管 P/D 身份和故障。NodeManager 拉起节点并上报心跳。"),
            ("EngineServer", "节点入口。北向接 Coordinator 和 Controller。"),
            ("vLLM-Ascend", "当前版本唯一南向引擎。前向和实例内组批在这里。"),
        ),
        control_index=1,
    )

    shared = (
        (ACCENT, "运行时", "CANN", "AscendCL、GE、Runtime、算子库、HCCL、DVPP。推理运行包用 NNRT。", 0.56),
        (HDK, "驱动", "HDK / Driver", "驱动与固件，与 CANN 分版本配套。", 0.42),
        (NAVY, "硬件", "昇腾 NPU", "推理任务在昇腾处理器上执行。", 0.42),
    )
    y = 5.20
    for fill, label, title, body, h in shared:
        textbox(slide, label_x, y, label_w, h, label, 13, True, fill, anchor=MSO_ANCHOR.MIDDLE)
        band(slide, bar_x, y, bar_w, h, fill, title, body, title_w=1.70)
        y += h + 0.06

    textbox(
        slide,
        0.32,
        6.78,
        12.7,
        0.56,
        "两条路径互不为下层。Motor 不跑模型前向；实例内组批在 LLM Manager，或在 vLLM-Ascend。\n"
        "EngineServer 的接口写了 vLLM、SGLang 和 MindIE，这一版只支持 vLLM。",
        13,
        False,
        MUTED,
        anchor=MSO_ANCHOR.TOP,
    )

    slide.notes_slide.notes_text_frame.text = (
        "依据 MindIE 3.1 用户手册 Overview 与 MindIE Motor 3.1 架构说明。"
        "MindIE LLM 进入维护，官方建议新部署使用 MindIE Motor 加 vLLM-Ascend。"
        "MindIE LLM 自上而下为 Server、LLM Manager、Text Generator、Modeling。"
        "LLM Manager 内的 Engine 编排 Scheduler、Executor 和 Worker；Block Manager 管 KV 池。"
        "Executor 把调度结果下发给 Text Generator，覆盖跨节点、跨设备。"
        "Text Generator 含前处理、Generator、Sampler，并支持可插拔的并行解码。"
        "Modeling 提供 ATB Models；开发者架构说明同时支持 ACLGraph 和 ATBGraph。"
        "Motor：Coordinator 为数据面入口；Controller 与 NodeManager 为管控面；EngineServer 北向接二者，南向当前仅 vLLM。"
        "架构页写明南向接口包括 vLLM、SGLang 和 MindIE，当前版本只支持 vLLM。"
        "MindCluster 提供 Kubernetes、PD 分离 CRD 和 Operator，位于调用链外侧。CCAE 可选。"
        "CANN 组成沿用方案概述：AscendCL、GE、Runtime、算子库、HCCL、DVPP。推理运行包为 NNRT。"
    )

    out = "/workspace/docs/ascend-infer-stack.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
