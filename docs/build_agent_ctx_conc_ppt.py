#!/usr/bin/env python3
"""Three slides: measured input length, production sub-agent concurrency, and
the width seen when dynamic concurrency is switched on."""

from __future__ import annotations

import importlib.util

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches

spec = importlib.util.spec_from_file_location(
    "slo_ui", "/agent/repos/ucl-mpcomm/docs/build_10t_hw2_slo_ppt.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

PPT = "/agent/repos/ucl-mpcomm/docs/长上下文与子agent并发.pptx"
TOTAL = 3


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


def chrome(slide, page, title, kicker, footer):
    bar = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    ui.solid(bar, ui.ACCENT)
    ui.textbox(slide, 0.42, 0.16, 10.6, 0.28, kicker, 12, True, ui.ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    ui.textbox(slide, 0.42, 0.42, 12.5, 0.42, title, 24, True, ui.NAVY, anchor=MSO_ANCHOR.MIDDLE)
    ui.textbox(slide, 11.4, 0.18, 1.5, 0.26, f"{page}  /  {TOTAL}", 12, False, ui.MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    ui.solid(rule, ui.LINE)
    ui.textbox(slide, 0.42, 7.20, 12.5, 0.24, footer, 11, False, ui.MUTED, anchor=MSO_ANCHOR.MIDDLE)


def note(slide, y, h, text, size=13):
    box = slide.shapes.add_shape(
        ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.36), Inches(y), Inches(12.60), Inches(h)
    )
    ui.solid(box, ui.GOLD_BG)
    ui.textbox(slide, 0.52, y + 0.06, 12.28, h - 0.10, text, size, False, ui.GOLD, anchor=MSO_ANCHOR.MIDDLE)


def slide_length(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        1,
        "10 万以上的输入，已经出现在生产流量里",
        "输入长度    ·    实测，不是窗口宣称",
        "Copilot  arXiv:2608.00101    ·    vLLM AgentX  2026-09-08    ·    SemiAnalysis cc-traces  2026-05-20",
    )
    ui.banner(slide, 0.96, "一轮的中位已经过 10 万。百万出现在 P90 和重用户身上，不是每一次调用。")
    head = ["来源", "样本", "测到的输入长度", "长上下文占了多少负载"]
    body = [
        [
            "GitHub Copilot\n2026 年 6 月一周",
            "320 万用户\n1300 万会话\n7.61 亿次调用",
            "单次调用中位 6.8 万 token，其中 6.3 万来自缓存。\n一轮中位 16.0 万 prompt，P90 超过 100 万。\n深循环用户占 9.2%，每一轮 110 万。",
            "prompt 超过 10 万的会话里，22.6% 做过压缩。\n发生压缩的会话只占 7.8%，却占全部 token 的 44.2%。",
        ],
        [
            "vLLM AgentX\n2026-09-08 复盘",
            "生产 coding-agent 会话",
            "中位输入 14.2 万 token。\n中位输出 444 token。",
            "长输入、短输出。\n44% 的会话里至少有一个子 agent。",
        ],
        [
            "Claude Code\n长会话切片",
            "219 条会话\n每条至少 20 轮\n2026-05-20",
            "公布的输入长度中位 11.0 万，P90 39.5 万。\n分词器是 o200k。卡片写 Anthropic 计费大约是这个数的 60%。",
            "按六成折算，中位约 6.6 万，P90 约 23.7 万。\n这是长会话切片，比全体流量更长。",
        ],
    ]
    ui.add_table(
        slide,
        0.36,
        1.52,
        [2.15, 2.15, 4.35, 3.95],
        [head] + body,
        [0.36, 1.28, 0.92, 1.28],
        ["head", "body", "body", "body"],
        size=12,
    )
    note(
        slide,
        5.50,
        1.54,
        "窗口标到 100 万，是产品承诺。DeepSeek-V4.1 按百万 token 的 agent 上下文做 KV 压缩，Claude 的 100 万窗口按普通单价开放。\n"
        "用量上，10 万以上已经是 coding agent 一轮的中位；百万集中在尾部和大约一成的重用户。\n"
        "没有公开的数字预测说，典型请求会变成百万上下文。",
        14,
    )


def slide_prod(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        2,
        "生产里子 agent 有，同时在跑的很少",
        "子 agent 并发    ·    默认流量，不是把开关打开",
        "同时在跑：Copilot 同一轮的调用重叠    ·    累计拉起：vLLM 与 SemiAnalysis，都不是同一时刻的宽度",
    )
    ui.banner(slide, 0.96, "要分开两件事：一个会话一共拉起过几个，和同一时刻有几个在跑。")
    head = ["来源", "量的是什么", "测到的数", "读法"]
    body = [
        [
            "GitHub Copilot\n同一周生产痕迹",
            "同一轮里，调用在时间上重叠的个数",
            "中位 1.15，P90 是 1.4。\n36.7% 的轮次完全串行。\n63.3% 有一点重叠。",
            "论文写重叠来自独立子任务或后台子 agent。\n宽度停在一两个。",
        ],
        [
            "vLLM AgentX",
            "一个会话里累计拉起的子 agent",
            "44% 的会话至少有一个。\n有子 agent 的会话里，中位 4 次 rollout。",
            "这是整段会话加起来的次数。\n博客没有给同时在跑的峰值。",
        ],
        [
            "Claude Code\n219 条长会话",
            "一个会话里累计的子 agent 组",
            "1994 组，平均每条会话 9.1 组。\n组内共 4.04 万次调用。",
            "同样是整段会话的累计。\n卡片没有公布同时在跑的峰值。样本要求至少 20 轮。",
        ],
    ]
    ui.add_table(
        slide,
        0.36,
        1.52,
        [2.20, 2.85, 3.70, 3.85],
        [head] + body,
        [0.36, 1.16, 1.16, 1.28],
        ["head", "body", "body", "body"],
        size=12,
    )
    note(
        slide,
        5.62,
        1.42,
        "产品已经往并行走。Claude Code 把并行子 agent 和动态工作流写成正式能力。Codex 写并行拉起再汇总，并说明比单 agent 更耗 token。\n"
        "生产中位还是一次一两个。会话里累计拉起几个，不能当成存储要同时喂几份相同前缀。",
        14,
    )


def slide_on(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        3,
        "开关打开后，难任务的同时在跑升到二十以上",
        "主动打开动态并发    ·    354 个任务的对照实验，不是生产中位数",
        "arXiv:2610.10263    ·    2026 年 7 月    ·    Codex / GPT-5.4，Claude Code / Opus 5，Kimi Code / K3    ·    2124 次执行",
    )
    ui.banner(slide, 0.96, "串行对照把子 agent 关掉。下面的峰值是同一时刻重叠的子 agent 个数。")
    head = ["谁", "任务", "累计创建", "同时在跑的峰值"]
    body = [
        [
            "三个 agent 合在一起",
            "全部任务，按难度",
            "简单 6.7，中等 7.5，难 15.8",
            "简单 3.7，中等 4.6，难 6.7",
        ],
        [
            "三个 agent 合在一起",
            "LoopsBench，最长的那组",
            "简单 16.3，难 68.2",
            "简单 6.0，难 21.8",
        ],
        [
            "Claude Code",
            "LoopsBench 难任务",
            "133.7",
            "25.5",
        ],
        [
            "Kimi Code",
            "LoopsBench 难任务",
            "67.0",
            "37.5",
        ],
        [
            "Codex",
            "各难度组",
            "主 agent 自己留着一部分实现",
            "1.2 到 3.0",
        ],
    ]
    ui.add_table(
        slide,
        0.36,
        1.50,
        [2.55, 3.15, 3.55, 3.35],
        [head] + body,
        [0.34, 0.46, 0.46, 0.46, 0.46, 0.46],
        ["head", "body", "body", "key", "key", "body"],
        size=13,
    )
    note(
        slide,
        4.78,
        2.26,
        "打开以后，token 是串行的 1.41 到 3.31 倍。任务通过率的变化从下降 11.9 个百分点到上升 2.3 个百分点。\n"
        "15 个 agent×基准组合里，14 个的平均耗时变长。长任务上通过率有增益，短的 SWE-bench 没有。\n"
        "公开材料能支持的判断：任务越长、越难，派出去的越多，同时在跑从个位数升到二十以上。\n"
        "没有一家给出数字预测，说典型生产请求的并发会升到几十。",
        14,
    )


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "长上下文与子 agent 并发"
    slide_length(prs)
    slide_prod(prs)
    slide_on(prs)
    prs.save(PPT)
    print(PPT)
    print("overflow", audit(prs))


if __name__ == "__main__":
    main()
