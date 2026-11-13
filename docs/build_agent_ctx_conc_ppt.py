#!/usr/bin/env python3
"""Four slides: eight-quarter input-length trend, current length measurements,
production sub-agent concurrency plus vendor rationale, and high-concurrency sources."""

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
TOTAL = 4

# Quarter means read off OpenRouter Figure 14 (weekly average prompt tokens).
# Each value is the mean of the weekly line inside that quarter, in thousands,
# rounded to 0.1. 2025Q4 is October through mid-November only.
QUARTERS = [
    ("24Q1", 1.7),
    ("24Q2", 1.4),
    ("24Q3", 1.5),
    ("24Q4", 2.0),
    ("25Q1", 2.8),
    ("25Q2", 3.6),
    ("25Q3", 4.5),
    ("25Q4", 5.3),
]


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
    ui.textbox(slide, 0.42, 0.42, 12.5, 0.40, title, 24, True, ui.NAVY, anchor=MSO_ANCHOR.MIDDLE)
    ui.textbox(slide, 11.4, 0.18, 1.5, 0.26, f"{page}  /  {TOTAL}", 12, False, ui.MUTED, PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    ui.solid(rule, ui.LINE)
    ui.textbox(slide, 0.42, 7.20, 12.5, 0.24, footer, 11, False, ui.MUTED, anchor=MSO_ANCHOR.MIDDLE)


def note(slide, y, h, text, size=13):
    box = slide.shapes.add_shape(
        ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.36), Inches(y), Inches(12.60), Inches(h)
    )
    ui.solid(box, ui.GOLD_BG)
    ui.textbox(slide, 0.52, y + 0.06, 12.28, h - 0.12, text, size, False, ui.GOLD, anchor=MSO_ANCHOR.MIDDLE)


def slide_trend(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        1,
        "全体请求的平均输入，八个季度从 1.7 千涨到 5.3 千",
        "输入长度的趋势    ·    同一口径的周线，按季平均",
        "OpenRouter / a16z    arXiv:2601.10088    Figure 14    ·    周线在季内取平均，取整到 0.1 千    ·    2025Q4 只到 11 月",
    )
    ui.banner(slide, 0.94, "2024 年二季度回落过一次。从三季度起到 2025 年 11 月，每个季度都比上一季高。")
    ymax = 6.0
    plot_left, plot_right = 1.28, 12.85
    base_y, plot_h = 4.62, 2.72
    n = len(QUARTERS)
    slot = (plot_right - plot_left) / n
    bar_w = 0.70
    for tick in (0, 2, 4, 6):
        y = base_y - (tick / ymax) * plot_h
        grid = slide.shapes.add_shape(
            ui.MSO_SHAPE.RECTANGLE, Inches(plot_left), Inches(y), Inches(plot_right - plot_left), Inches(0.012)
        )
        ui.solid(grid, ui.LINE)
        ui.textbox(slide, 0.42, y - 0.12, 0.78, 0.24, str(tick), 12, False, ui.MUTED, PP_ALIGN.RIGHT)
    ui.textbox(slide, 0.36, 1.48, 0.90, 0.36, "千 token", 11, True, ui.MUTED, PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.TOP)
    for i, (name, val) in enumerate(QUARTERS):
        h = (val / ymax) * plot_h
        x = plot_left + i * slot + (slot - bar_w) / 2
        top = base_y - h
        bar = slide.shapes.add_shape(
            ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(top), Inches(bar_w), Inches(h)
        )
        ui.solid(bar, ui.TEAL if i == n - 1 else ui.ACCENT)
        ui.textbox(
            slide, x - 0.12, top - 0.28, bar_w + 0.24, 0.26,
            f"{val:.1f}", 13, True, ui.NAVY, PP_ALIGN.CENTER,
        )
        ui.textbox(
            slide, x - 0.16, base_y + 0.04, bar_w + 0.32, 0.26,
            name, 12, True, ui.INK, PP_ALIGN.CENTER,
        )
    note(
        slide,
        5.08,
        1.96,
        "这是全体请求的平均，不是 coding agent。论文正文把两端概括为 2024 年初约 1.5 千、2025 年 11 月超过 6 千；"
        "图上 10–11 月的周线大约在 4.8 千到 5.7 千，季内平均是 5.3 千。\n"
        "编程类从 2025 年 5 月才单独统计，序列长度大约 1.2 万到 2.4 万，是全体平均的 3–4 倍（Figure 18）。\n"
        "coding agent 网关的另一次测量：Requesty，2025 年 5 月每次调用平均输入约 5.0 万，2026 年 4 月约 8.4 万。单次中位到 10 万以上的，在下一页。",
        13,
    )


def slide_length(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        2,
        "10 万以上的输入，已经出现在生产流量里",
        "输入长度    ·    2026 年的实测，不是窗口宣称",
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
        "上一页的全体平均还在几千。拉高平均的是编程和 agent，不是每一次聊天。",
        14,
    )


def slide_prod(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        3,
        "生产里同时在跑的很少，厂商仍把并行写成方向",
        "子 agent 并发    ·    生产统计，加上厂商自己的说法",
        "Copilot  arXiv:2608.00101    ·    Anthropic Research 2025-06    ·    OpenAI 多 agent 文档    ·    Cognition 2025-06 / 2026-04",
    )
    ui.banner(slide, 0.94, "生产中位仍是一次一两个。厂商公开的理由是：拆开以后覆盖更全，长任务的通过率更高。")
    chips = [
        ("Copilot，同一轮的调用重叠", "1.15", "中位。P90 是 1.4。36.7% 的轮次完全串行。"),
        ("vLLM，一个会话累计拉起", "44%", "的会话至少有一个。有的话，中位 4 次 rollout。"),
        ("Claude Code，219 条长会话", "9.1 组", "平均累计拉起。卡片没有给同时在跑的峰值。"),
    ]
    for i, (cap, num, sub) in enumerate(chips):
        x = 0.36 + i * 4.22
        card = slide.shapes.add_shape(ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.50), Inches(4.05), Inches(1.18))
        ui.solid(card, ui.SOFT, ui.LINE)
        ui.textbox(slide, x + 0.14, 1.54, 3.76, 0.24, cap, 12, True, ui.MUTED)
        ui.textbox(slide, x + 0.14, 1.76, 3.76, 0.40, num, 22, True, ui.TEAL)
        ui.textbox(slide, x + 0.14, 2.16, 3.76, 0.44, sub, 12, False, ui.INK)
    head = ["厂商", "他们公开写出的结果", "出发点"]
    body = [
        [
            "Anthropic\nResearch\n2025 年 6 月",
            "内部研究评测上，Opus 4 主 agent 加 Sonnet 4 子 agent，比单用 Opus 4 高 90.2%。\n复杂问题一次拉起 3–5 个，更难的超过 10 个。研究时间最多缩短 90%。",
            "宽查询要同时查很多方向。主上下文超过 20 万 token 会被截断。\n多 agent 的 token 大约是聊天的 15 倍。他们写明，多数写代码任务能并行的部分比研究少。",
        ],
        [
            "OpenAI\n多 agent 文档",
            "独立的研究、分析、实现同时做。每个子 agent 只拿一段任务，自带一块上下文。\n根 agent 负责创建、等待和汇总。Codex 把并行子 agent 做成产品。",
            "并行是为了缩短时间。分开的上下文是为了减少无关内容互相干扰。",
        ],
        [
            "Cognition\nDevin",
            "2025 年 6 月写过不要让多个 agent 同时改同一份代码。\n2026 年 4 月改成：能落地的是多人提供判断，写入仍由一条线完成。",
            "产品和前两家一样在用多 agent。他们把边界收在并行读、串行写，例如只读审查。",
        ],
    ]
    ui.add_table(
        slide,
        0.36,
        2.82,
        [1.85, 5.45, 5.30],
        [head] + body,
        [0.32, 1.05, 0.88, 0.88],
        ["head", "body", "body", "body"],
        size=11,
    )
    note(
        slide,
        6.08,
        0.98,
        "90.2% 是 Anthropic 自己的研究评测，不是 coding 基准。三家的共同点是都把并行子 agent 做成产品方向；分歧在写入要不要并行。\n"
        "生产流量没有跟着宣传走到「同时几十个」。下一页是把并发真正拉高的论文和工程材料。",
        13,
    )


def slide_high(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        4,
        "并发度拉高的材料，同时都碰到长任务",
        "论文和公开技术材料    ·    同时在跑的个数，加上输入或任务规模",
        "arXiv:2610.10263    ·    Anthropic Research 2025-06    ·    Cohere  团队实验，cohere.com/blog",
    )
    ui.banner(slide, 0.94, "这三份写的是实验或工程把并发打开以后的宽度，不是上一页的生产中位数。")
    head = ["材料", "同时在跑", "长输入或长任务", "通过率"]
    body = [
        [
            "动态并发对照\narXiv:2610.10263\n2026 年 10 月",
            "LoopsBench 难任务。\nClaude Code 峰值 25.5。\nKimi Code 峰值 37.5。\n三个 agent 平均峰值 21.8。\nCodex 各难度只有 1.2–3.0。",
            "三个 agent 在难任务上平均创建 68 个子 agent，Claude 这一组是 134。\ntoken 是串行的 1.41–3.31 倍。\n论文没有公布单次 prompt 有多长。",
            "长任务上 Claude 的任务通过率从 7.1% 到 21.4%。\n短的 SWE-bench 从 83% 降到 59%。",
        ],
        [
            "Anthropic\n研究系统\n2025 年 6 月",
            "复杂查询并行 3–5 个子 agent。\n更难的超过 10 个。",
            "主上下文超过 20 万 token 就被截断，计划要放到外部记忆。\n多 agent 的 token 大约是聊天的 15 倍。",
            "内部研究评测比单 agent 高 90.2%。\n同一篇材料，见上一页。",
        ],
        [
            "Cohere\n团队实验\n以及文中列举的工程",
            "实验把队伍固定到 2、4、8、16 个 worker。\n文中列举 Bun 移植峰值 64 个 Claude agent 并行。",
            "ProgramBench 含 SQLite、FFmpeg 这一级的程序。每个 worker 一块新上下文。\n文中另举 16 个 agent 写出约 10 万行的 C 编译器。单次 prompt 长度没有公布。",
            "Sol 团队平均测通 61.8%，单 agent 是 52.1%。\n成本大约是单 agent 的 4–7 倍。",
        ],
    ]
    ui.add_table(
        slide,
        0.28,
        1.48,
        [2.15, 3.15, 4.05, 3.40],
        [head] + body,
        [0.32, 1.42, 1.18, 1.42],
        ["head", "body", "body", "body"],
        size=11,
    )
    note(
        slide,
        5.96,
        1.10,
        "能放在一起的事实是：任务一大，主 agent 就拆给多个子 agent，每个子 agent 再带一份自己的上下文，token 跟着变成数倍。\n"
        "单次输入有没有到 10 万，这三份里只有 Anthropic 写出了 20 万的截断线。生产中位并发仍是 1.15，不是这里的二十、六十。",
        13,
    )


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "长上下文与子 agent 并发"
    slide_trend(prs)
    slide_length(prs)
    slide_prod(prs)
    slide_high(prs)
    prs.save(PPT)
    print(PPT)
    print("overflow", audit(prs))


if __name__ == "__main__":
    main()
