#!/usr/bin/env python3
"""Four slides: coding-agent input through 2026 Q4, measured lengths,
large-scale coding-agent teams, and coding-concurrency studies.

Every plotted or tabulated number carries a [n] marker. The matching note is the citation.
"""

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

# Coding-agent input per call, 万 token. Only the two [2] points share a definition.
# The October bar is a range, not a single average.
CALLS = [
    ("25-05\n平均", 5.0, 5.0, "2", "145A96"),
    ("26-04\n平均", 8.4, 8.4, "2", "145A96"),
    ("26-06\n中位", 6.8, 6.8, "3", "2F6F9F"),
    ("26-09\n中位", 14.2, 14.2, "4", "0E7A76"),
    ("26-10\n平均", 11.8, 23.0, "5", "7A541C"),
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
        "coding agent 的单次输入，接到 2026 年 10 月仍在变长",
        "输入长度    ·    同一颜色才是同一口径，不能连成一条线",
        "方括号是出处，写在本页下方    ·    纵轴单位是万 token",
    )
    ui.banner(
        slide,
        0.92,
        "[2] 是同一家网关的前后对比：2025 年 5 月 5.0 万，2026 年 4 月 8.4 万。后面三根接到三季度和 10 月，口径不同。",
    )
    ymax = 26.0
    plot_left, plot_right = 1.15, 12.85
    base_y, plot_h = 4.28, 2.28
    n = len(CALLS)
    slot = (plot_right - plot_left) / n
    bar_w = 1.15
    for tick in (0, 5, 10, 15, 20, 25):
        y = base_y - (tick / ymax) * plot_h
        grid = slide.shapes.add_shape(
            ui.MSO_SHAPE.RECTANGLE, Inches(plot_left), Inches(y), Inches(plot_right - plot_left), Inches(0.01)
        )
        ui.solid(grid, ui.LINE)
        ui.textbox(slide, 0.28, y - 0.11, 0.78, 0.22, str(tick), 11, False, ui.MUTED, PP_ALIGN.RIGHT)
    ui.textbox(slide, 0.22, 1.42, 0.90, 0.28, "万 token", 11, True, ui.MUTED, PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.TOP)
    for i, (name, lo, hi, mark, color) in enumerate(CALLS):
        x = plot_left + i * slot + (slot - bar_w) / 2
        top = base_y - (hi / ymax) * plot_h
        height = ((hi - lo) / ymax) * plot_h if hi > lo else (hi / ymax) * plot_h
        if hi == lo:
            top = base_y - height
        bar = slide.shapes.add_shape(
            ui.MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(top), Inches(bar_w), Inches(max(height, 0.08))
        )
        ui.solid(bar, color)
        label = f"{lo:.1f} [{mark}]" if hi == lo else f"{lo:.1f}–{hi:.0f} [{mark}]"
        ui.textbox(slide, x - 0.16, top - 0.26, bar_w + 0.32, 0.24, label, 12, True, ui.NAVY, PP_ALIGN.CENTER)
        ui.textbox(slide, x - 0.12, base_y + 0.02, bar_w + 0.24, 0.42, name, 11, True, ui.INK, PP_ALIGN.CENTER)
    note(
        slide,
        4.82,
        2.22,
        "[1] 全体请求更早的一段，不画在上图：OpenRouter 图 14，季内周线平均从 2024Q1 的 1.7 千升到 2025 年 10–11 月的 5.3 千。"
        "正文概括为约 1.5 千到超过 6 千。arXiv:2601.10088。系列停在 2025 年 11 月。\n"
        "[2] Requesty《The Coding Agent Economy》。九种 coding agent，每次调用平均输入，2025-05 约 5.0 万，2026-04 约 8.4 万，增加 68%。"
        "文中 Claude Code 在 2026-04 的平均 prompt 也是 8.4 万。\n"
        "[3] Copilot 生产，arXiv:2608.00101，2026 年 6 月第一周，单次调用 prompt 中位 6.8 万。中位低于 [2] 的平均，是长尾把平均拉高，不是输入变短。\n"
        "[4] vLLM AgentX，2026-09-08，会话中位输入 14.2 万。[5] Requesty Data，2026 年 10 月，网关内平均输入：Claude Code 11.8 万，Copilot 16 万，Cline 23 万。"
        "该文写明 Copilot 和 Cursor 多数不走这家网关。",
        11,
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
    ui.banner(slide, 0.96, "数字后的方括号对到页底。一轮的中位已经过 10 万；百万出现在 P90 和重用户。")
    head = ["来源", "样本", "测到的输入长度", "长上下文占了多少负载"]
    body = [
        [
            "GitHub Copilot\n2026 年 6 月一周 [1]",
            "320 万用户\n1,350 万会话\n7.61 亿次调用 [1]",
            "单次调用中位 6.8 万，缓存中位 6.3 万 [1]。\n表 4：一轮中位 22.8 万，P90 150 万 [1]。\n正文另写一轮中位 16.0 万 [1]。深循环用户 9.2%，一轮 110 万 [1]。",
            "prompt 超过 10 万的会话里，22.6% 做过压缩 [1]。\n发生压缩的会话占 7.8%，却占全部 token 的 44.2% [1]。",
        ],
        [
            "vLLM AgentX\n2026-09-08 [2]",
            "生产 coding-agent 会话",
            "中位输入 14.2 万 [2]。\n中位输出 444 [2]。",
            "长输入、短输出。\n44% 的会话里至少有一个子 agent [2]。",
        ],
        [
            "Claude Code\n长会话切片 [3]",
            "219 条会话\n每条至少 20 轮\n2026-05-20 [3]",
            "公布中位 11.0 万，P90 39.5 万 [3]。\n分词器是 o200k。卡片写计费大约是六成 [3]。",
            "按六成折算，中位约 6.6 万，P90 约 23.7 万。\n这是长会话切片，比全体流量更长。",
        ],
    ]
    ui.add_table(
        slide,
        0.36,
        1.52,
        [2.15, 2.15, 4.35, 3.95],
        [head] + body,
        [0.32, 1.42, 0.78, 1.12],
        ["head", "body", "body", "body"],
        size=11,
    )
    note(
        slide,
        5.28,
        1.76,
        "[1] arXiv:2608.00101。单次中位见正文和图 10。表 4 的一轮 prompt 中位是 22.8 万、P90 是 150 万；正文另写一轮中位 16.0 万、P90 超过 100 万。两处不一致，都过了 10 万。\n"
        "[2] vLLM 博客，2026-09-08，AgentX。[3] SemiAnalysis cc-traces，2026-05-20。六成是卡片自己的计费口径说明，不是另一次测量。",
        12,
    )


def slide_prod(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        3,
        "大型软件工程里，已经有几十到上百个 coding agent 同时在跑",
        "AI coding    ·    三份一手工程记录，不是研究问答的多 agent",
        "数字后的方括号对到页底",
    )
    ui.banner(slide, 0.92, "三份都是把一个大代码库交给一批 coding agent。同时在跑的个数和代码规模分开标。")
    head = ["工程", "同时在跑", "代码规模和花费", "他们怎么组织"]
    body = [
        [
            "C 编译器\nAnthropic\n2026-02-05 [1]",
            "16 个 Claude 并行 [1]。\n没有总控 agent [1]。",
            "约 2,000 次会话，约 2 万美元 [1]。\n约 10 万行 Rust，能编 Linux 6.9 [1]。",
            "用 git 锁认领任务。编内核时 16 个 agent 卡在同一个错误上，改动互相覆盖 [1]。",
        ],
        [
            "浏览器\nCursor [2]",
            "几百个 agent 同时跑一个项目 [2]。",
            "将近一周。超过 100 万行，约 1,000 个文件 [2]。\n累计 token 写成万亿级，那是总消耗，不是单次输入 [2]。",
            "规划 agent 可以再派子规划。worker 不互相协调，做完自己的任务再提交 [2]。",
        ],
        [
            "Bun 从 Zig 移植到 Rust\n2026-05-03 至 05-14 [3]",
            "约 50 条工作流 [3]。\n峰值 4 个工作区，每个 16 个 Claude，约 64 个同时在跑 [3]。",
            "53.5 万行 Zig，6,502 次提交 [3]。\n未缓存输入 59 亿 token，缓存读 720 亿，输出 6.9 亿，约 16.5 万美元 [3]。",
            "1 个实现者配 2 个以上审查者。审查在另一块上下文里，只找错误 [3]。",
        ],
    ]
    ui.add_table(
        slide,
        0.28,
        1.46,
        [2.35, 3.15, 3.85, 3.40],
        [head] + body,
        [0.32, 1.22, 1.22, 1.38],
        ["head", "body", "body", "body"],
        size=11,
    )
    note(
        slide,
        5.74,
        1.30,
        "[1] Nicholas Carlini，Building a C compiler with a team of parallel Claudes，2026-02-05。anthropic.com/research/building-c-compiler。\n"
        "[2] Cursor，Scaling long-running autonomous coding。cursor.com/blog/scaling-agents。博文写的是 hundreds，没有给出精确峰值。\n"
        "[3] Jarred Sumner，Rewriting Bun in Rust，2026-07-08。bun.com/blog/bun-in-rust。64 是峰值同时在跑，不是一共只有 64 个 agent。",
        12,
    )


def slide_high(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        slide,
        4,
        "对照实验里，大型 coding 任务的并发到了几十",
        "AI coding    ·    论文和受控实验    ·    与日常流量分开",
        "数字后的方括号对到页底    ·    上一页的编译器、浏览器、Bun 不在这张表里重复",
    )
    ui.banner(slide, 0.92, "打开并发以后，长的 coding 任务通过率有上升，短任务会下降。日常 Copilot 的中位仍是一次一两个。")
    head = ["材料", "同时在跑", "任务和 token", "通过率"]
    body = [
        [
            "三个 coding agent\n开关对照 [1]",
            "LoopsBench 难任务。\nClaude Code 峰值 25.5 [1]。\nKimi Code 峰值 37.5 [1]。\n三家平均峰值 21.8 [1]。\nCodex 各难度 1.2–3.0 [1]。",
            "难任务上三家平均创建 68 个，Claude 这一组 134 个 [1]。\ntoken 是串行的 1.41–3.31 倍 [1]。\n单次 prompt 长度没有公布 [1]。",
            "长任务上 Claude 从 7.1% 到 21.4% [1]。\n短的 SWE-bench 从 83% 降到 59% [1]。",
        ],
        [
            "Cohere\nProgramBench [2]",
            "队伍规模单独测过 2、4、8、16 个 worker [2]。\n下面的通过率不是这组固定人数。",
            "200 个程序，含 SQLite、FFmpeg 这一级 [2]。\n每个 worker 一块新上下文 [2]。\n单次 prompt 长度没有公布。",
            "最小提示下，会等待的 Sol 团队 61.8%，单 agent 52.1% [2]。\n四种 Sol 团队的成本是单 agent 的 4–7 倍 [2]。",
        ],
        [
            "日常 coding 流量\n不是大型工程实验",
            "Copilot 同一轮重叠，中位 1.15，P90 1.4 [3]。\n36.7% 的轮次完全串行 [3]。",
            "vLLM：44% 的会话至少有一个子 agent，有的话中位 4 次 [4]。\n这是累计次数，不是同时在跑。",
            "Claude Code 219 条长会话平均累计 9.1 组 [5]。\n卡片没有同时在跑的峰值。",
        ],
    ]
    ui.add_table(
        slide,
        0.24,
        1.46,
        [2.20, 3.45, 3.85, 3.25],
        [head] + body,
        [0.30, 1.38, 1.22, 1.22],
        ["head", "body", "body", "body"],
        size=11,
    )
    note(
        slide,
        5.72,
        1.32,
        "[1] arXiv:2610.10263。354 个任务，2026 年 7 月的 agent 配置，并发开关打开对关闭。峰值是同一时刻重叠的子 agent。\n"
        "[2] Cohere，Lessons from scaling teams of coding agents。cohere.com/blog。61.8% 对 52.1% 用的是会阻塞等待的团队，人数由主 agent 自己定。\n"
        "[3] arXiv:2608.00101。[4] vLLM，2026-09-08。[5] SemiAnalysis cc-traces，2026-05-20，1,994 组 / 219 条。",
        12,
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
