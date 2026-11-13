#!/usr/bin/env python3
"""One slide: measured prefix-cache hit rates inside one agent session."""

from __future__ import annotations

import importlib.util

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Inches

spec = importlib.util.spec_from_file_location(
    "slo_ui", "/agent/repos/ucl-mpcomm/docs/build_10t_hw2_slo_ppt.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

FOOTER = "前缀重复    ·    同一条会话里下一次请求沿用上次的 KV    ·    不是多条请求同时各带一份"

PPT = "/agent/repos/ucl-mpcomm/docs/agent前缀重复.pptx"


def audit(prs):
    wide, low = Inches(13.333), Inches(7.50)
    bad = []
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.left is None:
                continue
            if shape.left + shape.width > wide + Emu(40000) or shape.top + shape.height > low + Emu(40000):
                bad.append((i, int(shape.left), int(shape.top), int(shape.width), int(shape.height)))
            if shape.top < 0 or shape.left < 0:
                bad.append((i, "neg", int(shape.left), int(shape.top)))
    return bad


def chrome(slide, title, kicker):
    bar = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    ui.solid(bar, ui.ACCENT)
    ui.textbox(slide, 0.42, 0.16, 10.6, 0.28, kicker, 12, True, ui.ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    ui.textbox(slide, 0.42, 0.42, 12.5, 0.42, title, 26, True, ui.NAVY, anchor=MSO_ANCHOR.MIDDLE)
    ui.textbox(slide, 11.4, 0.18, 1.5, 0.26, "1  /  1", 12, False, ui.MUTED, ui.PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    ui.solid(rule, ui.LINE)
    ui.textbox(slide, 0.42, 7.20, 12.5, 0.24, FOOTER, 11, False, ui.MUTED, anchor=MSO_ANCHOR.MIDDLE)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "同一 agent 任务的前缀重复"
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(slide, "同一条 agent 会话里，前缀重复率有多高", "三次生产测量    ·    命中率 = 本次 prompt 里能沿用上次 KV 的 token 比例")
    ui.banner(slide, 1.02, "高命中发生在工具循环内部。第一次调用、用户隔一轮、人离开几分钟、改写前文，都会掉下去。")
    head = ["来源", "规模", "工具循环里的命中", "什么时候掉下去"]
    body = [
        [
            "GitHub Copilot\n2026 年 6 月抽样",
            "1300 万会话\n7.61 亿次调用",
            "一轮之内平均约 90%。中位 prompt 6.8 万 token，其中 6.3 万来自缓存。\n第 1 次约 45%，第 2 次约 86%。\n第 3 次以后停在 92–94%。",
            "跨用户轮次降到约 55%。\n空闲超过 10 分钟，中位接近 0–5%。",
        ],
        [
            "FreeInference\n13 种 coding agent",
            "1.2 万会话\n1.19 亿次请求",
            "缓存占全部输入 token 的 97.3%。中位请求约 12.2 万输入，未缓存约 500。\n普通工具间隙的平均命中率 97.2%。",
            "15–30 分钟约 62%，超过 1 小时约 19%。\n46.4% 的会话会改写前文，前缀从改写点起失效。",
        ],
        [
            "Claude Code 与 Codex\nTraceLab",
            "约 4300 个会话\n35 万步",
            "按 token 加权 95.7%。\n工具结果步 97.5%。",
            "用户主动发起的下一步是 84.4%。\n空闲超过 5 分钟开始掉，超过 1 小时几乎全灭。",
        ],
    ]
    kinds = ["head", "body", "body", "body"]
    ui.add_table(
        slide,
        0.36,
        1.56,
        [2.20, 2.25, 4.30, 3.75],
        [head] + body,
        [0.38, 1.28, 1.28, 1.18],
        kinds,
        size=12,
    )
    note = slide.shapes.add_shape(
        ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.36), Inches(5.82), Inches(12.50), Inches(1.22)
    )
    ui.solid(note, ui.GOLD_BG)
    ui.textbox(
        slide,
        0.52,
        5.92,
        12.18,
        1.02,
        "三次都是同一条会话里上下文只往后接：下一次请求复用上一次已经算好的前缀。\n"
        "Copilot  arXiv:2608.00101。FreeInference  From Requests to Sessions。TraceLab  arXiv:2606.30560。",
        14,
        False,
        ui.GOLD,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    prs.save(PPT)
    print(PPT)
    print("overflow", audit(prs))


if __name__ == "__main__":
    main()
