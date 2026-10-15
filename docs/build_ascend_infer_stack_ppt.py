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


def kv_column(slide, x, y, w, h, pool_title, pool_body, xfer_fill, xfer_title, xfer_body, link=True):
    """Pool on top, its own transport underneath. The arrow is the byte path."""
    top_h = 0.42
    mid_h = 0.16
    bot_h = h - top_h - mid_h
    box(slide, x, y, w, top_h, GOLD, "")
    textbox(slide, x + 0.08, y + 0.01, w - 0.16, 0.20, pool_title, 13, True, WHITE)
    textbox(slide, x + 0.08, y + 0.21, w - 0.16, 0.20, pool_body, 11, False, WHITE)
    if link:
        arrow = slide.shapes.add_shape(
            MSO_SHAPE.DOWN_ARROW,
            Inches(x + w / 2 - 0.09),
            Inches(y + top_h),
            Inches(0.18),
            Inches(mid_h),
        )
        solid(arrow, xfer_fill)
    box(slide, x, y + top_h + mid_h, w, bot_h, xfer_fill, "")
    textbox(slide, x + 0.08, y + top_h + mid_h + 0.02, w - 0.16, 0.20, xfer_title, 13, True, WHITE)
    textbox(slide, x + 0.08, y + top_h + mid_h + 0.22, w - 0.16, bot_h - 0.24, xfer_body, 11, False, WHITE)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "昇腾推理软件栈分层"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    box(slide, 0, 0, 13.333, 0.08, ACCENT, "")
    textbox(slide, 0.32, 0.16, 12.6, 0.22, "昇腾  ·  推理软件栈  ·  MindIE 3.1", 13, True, ACCENT)
    textbox(
        slide,
        0.32,
        0.38,
        12.7,
        0.36,
        "Mooncake 的字节走 HIXL，MemCache 的字节走 MemFabric",
        22,
        True,
        NAVY,
    )
    textbox(
        slide,
        0.32,
        0.76,
        12.7,
        0.30,
        "两条服务在 CANN 汇合。默认推理不调用 SHMEM。HCOMM 是 HCCL 的基础库。",
        14,
        False,
        INK,
    )

    label_x, label_w = 0.28, 0.92
    bar_x, bar_w = 1.24, 11.76

    textbox(slide, label_x, 1.12, label_w, 0.30, "集群", 12, True, GOLD, anchor=MSO_ANCHOR.MIDDLE)
    band(
        slide,
        bar_x,
        1.12,
        bar_w,
        0.30,
        GOLD,
        "MindCluster",
        "调用链外侧。Pod、PD 分离、故障恢复。可选 CCAE。",
        title_w=1.70,
    )

    textbox(slide, label_x, 1.48, label_w, 2.16, "服务", 12, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)
    path_w = (bar_w - 0.12) / 2
    path_rows(
        slide,
        bar_x,
        1.48,
        path_w,
        2.16,
        TEAL,
        "路径 A  ·  MindIE LLM",
        (
            ("Server", "OpenAI、vLLM、Triton、TGI。"),
            ("LLM Manager", "连续组批。Engine 含 Scheduler。"),
            ("Text Generator", "自回归。Executor 跨节点下发。"),
            ("Modeling", "ACLGraph 与 ATBGraph。"),
        ),
    )
    path_rows(
        slide,
        bar_x + path_w + 0.12,
        1.48,
        path_w,
        2.16,
        ACCENT,
        "路径 B  ·  MindIE Motor",
        (
            ("Coordinator", "路由、限流、实例隔离。"),
            ("管控面", "Controller 与 NodeManager。"),
            ("EngineServer", "北向接 Coordinator、Controller。"),
            ("vLLM-Ascend", "当前唯一南向。前向与组批。"),
        ),
        control_index=1,
    )

    kv_y, kv_h = 3.72, 1.04
    textbox(slide, label_x, kv_y, label_w, kv_h, "KV", 12, True, GOLD, anchor=MSO_ANCHOR.MIDDLE)
    gap = 0.10
    col_w = (bar_w - gap * 2) / 3
    kv_column(
        slide,
        bar_x,
        kv_y,
        col_w,
        kv_h,
        "池  MemCache",
        "默认后端。元数据与 DRAM 池。",
        TEAL,
        "传输  MemFabric",
        "rdma、sdma、urma、host_shm。",
    )
    kv_column(
        slide,
        bar_x + col_w + gap,
        kv_y,
        col_w,
        kv_h,
        "池  Mooncake",
        "对象层。Conductor 只记位置。",
        ACCENT,
        "传输  HIXL",
        "ascend_direct。DataDist 拉推 KV。",
    )
    kv_column(
        slide,
        bar_x + (col_w + gap) * 2,
        kv_y,
        col_w,
        kv_h,
        "池  YuanRong",
        "第三种 backend。",
        HDK,
        "传输  随该后端",
        "由 AscendStoreConnector 选定。",
    )

    textbox(slide, label_x, 4.84, label_w, 0.32, "集合", 12, True, ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    band(
        slide,
        bar_x,
        4.84,
        bar_w,
        0.32,
        ACCENT,
        "HCCL",
        "基础库是 HCOMM。服务张量并行与专家并行。",
        title_w=1.70,
    )

    textbox(slide, label_x, 5.22, label_w, 0.44, "算子", 12, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
    box(slide, bar_x, 5.22, bar_w, 0.44, WHITE, line=LINE)
    box(slide, bar_x, 5.22, 1.70, 0.44, NAVY, "SHMEM", 13, True, WHITE)
    textbox(
        slide,
        bar_x + 1.82,
        5.22,
        bar_w - 1.96,
        0.44,
        "对称内存，给定制算子。默认的 MindIE / vLLM-Ascend 推理不调用。kv_shuffle 只是示例。",
        13,
        False,
        INK,
    )

    shared = (
        (ACCENT, "运行时", "CANN", "AscendCL、GE、Runtime、算子库、DVPP。推理包是 NNRT。", 0.28),
        (HDK, "驱动", "HDK", "驱动与固件，与 CANN 分版本配套。", 0.26),
        (NAVY, "硬件", "NPU", "推理任务在昇腾处理器上执行。", 0.26),
    )
    y = 5.74
    for fill, label, title, body, h in shared:
        textbox(slide, label_x, y, label_w, h, label, 12, True, fill, anchor=MSO_ANCHOR.MIDDLE)
        band(slide, bar_x, y, bar_w, h, fill, title, body, title_w=1.70)
        y += h + 0.04

    textbox(
        slide,
        0.32,
        6.68,
        12.7,
        0.72,
        "按层池化当前只接 MemCache。Conductor 只记位置，字节不经过它。HIXL 覆盖 D2D、D2H、H2D。\n"
        "MindIE 进程间的 /dev/shm 是主机共享内存里的标志位，和 CANN SHMEM 是两套。文档里的库名是 HCOMM。",
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
        "KV 池与传输不是并列关系。AscendStoreConnector.backend 在 memcache、mooncake、yuanrong 里选一个池。"
        "MemCache 是 Motor 3.1 默认池：MetaService 管元数据，LocalService 管 DRAM。它的字节走 MemFabric，协议有 device_rdma（A2）、device_sdma（A3）、host_rdma、device_urma（950）、同节点 host_shm。"
        "Mooncake 是对象层，mooncake_master 管池。昇腾上的字节走 Ascend Direct（adxl），建在 CANN 的 HIXL 上。ASCEND_USE_ASYNC_TRANSFER 打开 HIXL 异步传输。LLM-DataDist 是 HIXL 上的 KV 接口，做链路和 pull、push，覆盖 D2D、D2H、H2D。"
        "Conductor 只是位置索引，Coordinator 用它做亲和调度，字节不经过 Conductor。"
        "YuanRong 是第三种池后端。按层池化目前只支持 MemCache。"
        "HCCL 是集合通信，服务张量并行和专家并行。HCOMM 是 HCCL 的基础库，控制面管拓扑和资源，数据面管搬运和同步。用户所说的 HCOM 对应文档名 HCOMM。"
        "CANN SHMEM（aclshmem）是算子用的对称内存。仓库示例 kv_shuffle 做跨 PE 的 KV 块拷贝，不在默认服务路径上。"
        "MindIE 的 SharedMemCommunication 和 layerwise 的 share_memory 使用主机 POSIX 共享内存传控制标志，不是 CANN SHMEM。"
    )

    out = "/workspace/docs/ascend-infer-stack.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
