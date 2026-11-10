#!/usr/bin/env python3
"""Plain-language walkthrough of the V4.1 20T three-way KV placement.

The numbers come from docs/build_deepseek_v41_20t_slo_ppt.py. This deck
only explains CSA2 and where the 2048-block candidate pool sits.
"""

from __future__ import annotations

import importlib.util

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches

spec = importlib.util.spec_from_file_location(
    "v41", "/agent/repos/ucl-mpcomm/docs/build_deepseek_v41_20t_slo_ppt.py"
)
v41 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v41)
ui = v41.ui

SLIDES = 8
FOOTER = "DS 4.1 在网 cache    ·    讲的是 V4.1 外扩 20T 那一版    ·    CSA2 的 2048 块"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER

NAVY = ui.NAVY
TEAL = ui.TEAL
INK = ui.INK
WHITE = ui.WHITE
PALE = ui.PALE
GOLD_BG = ui.GOLD_BG
GOLD = ui.GOLD
MUTED = ui.MUTED
DDR = ui.DDR_COLOR
HOST = "C46B2C"
SOFT = "E8EEF4"
PPT = "/agent/repos/ucl-mpcomm/docs/DS 4.1在网cache.pptx"


def card(slide, x, y, w, h, fill, title, body, title_c=WHITE, body_c=WHITE, title_size=15, body_size=13):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    ui.solid(shape, fill)
    try:
        shape.adjustments[0] = 0.08
    except Exception:
        pass
    ui.textbox(slide, x + 0.14, y + 0.08, w - 0.28, 0.32, title, title_size, True, title_c, anchor=MSO_ANCHOR.TOP)
    ui.textbox(slide, x + 0.14, y + 0.42, w - 0.28, h - 0.52, body, body_size, False, body_c, anchor=MSO_ANCHOR.TOP)
    return shape


def arrow_right(slide, x, y, w=0.28, h=0.22, fill=NAVY):
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    ui.solid(shape, fill)
    return shape


def arrow_down(slide, x, y, w=0.22, h=0.26, fill=NAVY):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    ui.solid(shape, fill)
    return shape


def pill(slide, x, y, w, h, fill, text, color, size=11):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    ui.solid(shape, fill)
    try:
        shape.adjustments[0] = 0.18
    except Exception:
        pass
    ui.textbox(slide, x + 0.04, y, w - 0.08, h, text, size, True, color, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
    return shape


def layer_row(slide, y, items):
    gap = 0.16
    width = 1.38
    for i, (fill, color, text) in enumerate(items):
        x = 0.36 + i * (width + gap)
        pill(slide, x, y, width, 0.62, fill, text, color, 11)
        if i + 1 < len(items):
            arrow_right(slide, x + width + 0.01, y + 0.20, 0.14, 0.18, MUTED)


def slide_csa2_map(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "CSA2 坐在每一层的注意力里", "编码器负责把全文收成块    ·    解码器不再回去扫全文")
    ui.banner(slide, 0.90, "40 层是编码器 20 层加解码器 20 层。变的只是这一层的注意力用 Full、Reindex 还是 Reuse。")
    ui.textbox(slide, 0.36, 1.40, 6.2, 0.26, "编码器 · 层 1–20 · 从全文里挑块", 13, True, NAVY)
    layer_row(
        slide, 1.70,
        [
            (SOFT, NAVY, "层 1\nReuse"),
            (TEAL, WHITE, "层 2\nFull"),
            (SOFT, NAVY, "层 3–7\nReuse"),
            (TEAL, WHITE, "层 8\nFull"),
            (SOFT, NAVY, "层 9–13\nReuse"),
            (TEAL, WHITE, "层 14\nFull"),
            (SOFT, NAVY, "层 15–19\nReuse"),
            (TEAL, WHITE, "层 20\nFull"),
        ],
    )
    ui.textbox(slide, 0.36, 2.46, 8.0, 0.26, "解码器 · 层 21–40 · 只在已经选出的块里挑", 13, True, NAVY)
    layer_row(
        slide, 2.76,
        [
            (SOFT, NAVY, "层 21–23\nReuse"),
            (HOST, WHITE, "层 24\nReindex"),
            (SOFT, NAVY, "层 25–27\nReuse"),
            (HOST, WHITE, "层 28\nReindex"),
            (SOFT, NAVY, "层 29–31\nReuse"),
            (HOST, WHITE, "层 32\nReindex"),
            (SOFT, NAVY, "层 33–35\nReuse"),
            (HOST, WHITE, "层 36\nReindex"),
        ],
    )
    ui.textbox(slide, 0.36, 3.48, 12.4, 0.24, "层 37–40 仍是 Reuse。Reuse 不再挑块，沿用上一层已经选出的 512。", 12, False, MUTED)
    flow = [
        (SOFT, NAVY, INK, "全文", "每个 token\n890 字节\n冷数据"),
        (TEAL, WHITE, WHITE, "4 个 Full", "压缩比 2\n从全文里\n选出块"),
        (NAVY, WHITE, WHITE, "候选池", "2048 块 × 8\n= 4.72 MB\n+ Top-512 0.44 MB"),
        (HOST, WHITE, WHITE, "4 个 Reindex", "只在 16384 条里\n再挑 512\n后面的层沿用"),
    ]
    for i, (fill, tc, bc, title, body) in enumerate(flow):
        x = 0.36 + i * 3.25
        card(slide, x, 3.84, 2.95, 1.72, fill, title, body, tc, bc, 15, 13)
        if i < 3:
            arrow_right(slide, x + 2.98, 4.52, 0.22, 0.18, NAVY)
    ui.gold(
        slide,
        5.72,
        1.28,
        "热路径到候选池就停了：每步要靠近计算的是 4.72 + 0.44 = 5.16 MB / 序列。4M 全文有 3.74 GB，留在主 KV 里，Full 层打完分之后不再整段重读。\n"
        "滑窗 40×128 条单独留在 GPU，不进这 5.16 MB。",
        14,
    )


def slide_placement(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "模块位置不动，变的是哪一段离开 GPU", "上：在网 cache    ·    中：GPU    ·    下：主机    ·    左：DDR 池")
    ui.banner(slide, 0.90, "索引和滑窗三种方案都留在 GPU。出卡的只有主 KV，或者 CSA2 每步要重读的那 5.16 MB。")

    card(slide, 0.32, 1.48, 3.55, 2.05, "F3E6D4", "DDR 池", "主 KV 全量，容量不限。\n方案 3 整份存放。\n不在每步热路径上。", DDR, INK, 16, 14)
    arrow_right(slide, 3.92, 2.30, 0.48, 0.20, DDR)
    ui.textbox(slide, 0.32, 3.62, 3.55, 0.70, "这条箭头只把主 KV 放进池里。GPU 不每步回来读它。", 13, False, INK, anchor=MSO_ANCHOR.TOP)

    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4.55), Inches(1.48), Inches(4.35), Inches(1.02))
    ui.solid(box, "D5EBE3")
    ui.textbox(slide, 4.68, 1.52, 4.10, 0.30, "在网 cache · 交换芯片 HBM", 14, True, TEAL, PP_ALIGN.CENTER)
    ui.textbox(slide, 4.68, 1.84, 4.10, 0.55, "30×64 GB。方案 3 的 2048 块常驻。\n向下每步搬 5.16 MB，4.80 TB/s。", 13, False, INK, PP_ALIGN.CENTER)
    arrow_down(slide, 6.60, 2.54, 0.22, 0.24, TEAL)

    card(
        slide, 4.55, 2.84, 4.35, 1.62, SOFT, "GPU HBM",
        "索引 + 滑窗：三种都留在这。\n方案 1 的主 KV 和 2048 块也留在这。",
        NAVY, INK, 16, 14,
    )
    arrow_down(slide, 6.60, 4.50, 0.22, 0.24, HOST)
    card(slide, 4.55, 4.80, 4.35, 1.35, "F8E6D4", "HOST DDR", "方案 2：每步搬溢出比例 × 5.16 MB。\n160 GB/s，每卡 96 GB。不搬权重和索引。", HOST, INK, 16, 13)

    card(slide, 9.15, 1.48, 3.78, 1.55, NAVY, "方案 1 · 不出卡", "两条向下的箭头都不走。\n卡内读，26.4 TB/s。", WHITE, WHITE, 15, 14)
    card(slide, 9.15, 3.18, 3.78, 1.40, HOST, "方案 2 · 只搬溢出", "走下面那条箭头。\n搬的是 GPU 放不下的主 KV。", WHITE, WHITE, 15, 14)
    card(slide, 9.15, 4.72, 3.78, 1.43, TEAL, "方案 3 · 热冷分开", "2048 块走上面的箭头。\n主 KV 走左边，放进 DDR 池。", WHITE, WHITE, 15, 14)


def slide_question(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "每步只热 5.16 MB，问题是它放哪", "把 deepseek-v41-20t-n2-slo 的分析收成三句话")
    ui.banner(slide, 0.92, "模型是 V4.1-Flash 外扩到 20T。Decode 一份 256 卡。三种放法只改 CSA2 候选池和主 KV 的位置。")
    r64 = v41.by_len(data, 65536)
    r4 = v41.by_len(data, 4194304)
    items = [
        (NAVY, "全放 HBM", "索引、主 KV、2048 块都在 GPU。\n不换入。房间满了就停批。"),
        (HOST, "走 HOST DDR", "2048 块里装不下的部分放主机。\n每步按溢出比例搬，160 GB/s。"),
        (TEAL, "交换 HBM + DDR 池", "2048 块常驻 30 颗交换芯片。\n主 KV 整份放进容量不限的 DDR 池。"),
    ]
    for i, (color, title, body) in enumerate(items):
        card(slide, 0.42 + i * 4.25, 1.55, 4.05, 2.15, color, title, body, body_size=14)
    ui.gold(
        slide,
        4.00,
        2.85,
        f"短的先说：64K、30 毫秒，全放 HBM 的批是 {v41.fmt_bs(r64['hbm30'])}，交换方案被 30×64 GB 卡住，批只有 {v41.fmt_bs(r64['sw30'])}，系统 TPS {v41.signed_pct(v41.tps_d(r64, 'sw', '30'), v41.tps_d(r64, 'hbm', '30'))}。\n"
        f"长的再说：4M、30 毫秒，全放 HBM 的批是 {v41.fmt_bs(r4['hbm30'])}。走主机把批抬到 {v41.fmt_bs(r4['host30'])}，但步时变长，TPS {v41.signed_pct(v41.tps_d(r4, 'host', '30'), v41.tps_d(r4, 'hbm', '30'))}。"
        f"交换方案批 {v41.fmt_bs(r4['sw30'])}，TPS {v41.signed_pct(v41.tps_d(r4, 'sw', '30'), v41.tps_d(r4, 'hbm', '30'))}。\n"
        "所以在网 cache 不是用来装短上下文的。它装的是 CSA2 每步要重读的那 2048 块，收益出现在 4M 这种主 KV 已经远远大于 GPU 房间的时候。",
        14,
    )


def slide_csa2(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "CSA2：先缩成 2048 块，后面只在块里挑", "40 层    ·    编码器 20 层    ·    解码器 20 层")
    ui.banner(slide, 0.92, "Full 负责从全文里挑块。Reindex 不再扫全文。Reuse 连挑块都不做，沿用上一层的结果。")
    stages = [
        (SOFT, NAVY, INK, "1  全文", "每个 token 存 890 字节。\n这是冷数据。\nDecode 不整段重读。"),
        (NAVY, WHITE, WHITE, "2  四个 Full", "层 2、8、14、20。\n压缩比 2。\n从全文里选出块。"),
        (TEAL, WHITE, WHITE, "3  候选池", "2048 块 × 8 位置\n= 16384 条主 KV。\n一共 4.72 MB。"),
        (HOST, WHITE, WHITE, "4  四个 Reindex", "层 24、28、32、36。\n只在这 16384 条里\n再挑 512。"),
    ]
    for i, (fill, tc, bc, title, body) in enumerate(stages):
        x = 0.42 + i * 3.22
        card(slide, x, 1.52, 2.90, 2.55, fill, title, body, tc, bc, 16, 14)
        if i < 3:
            arrow_right(slide, x + 2.94, 2.62, 0.24, 0.20, NAVY)
    ui.gold(
        slide,
        4.28,
        2.60,
        "其余层是 Reuse：不再扫全文，也不再挑块，沿用已经选出的 512。滑窗 40×128 条留在 GPU，不进卸载。\n"
        "编码器还有三组 Top-512，每步再读 0.44 MB。加上候选池 4.72 MB，一步的热数据是 5.16 MB / 序列。\n"
        "在网 cache 缓存的就是这 5.16 MB，不是 4M 上下文那 3.74 GB。主 KV 可以放得很远，只要这 2048 块离 GPU 近。",
        15,
    )


def slide_three(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "同一份数据，三条路", "左：全放 HBM    ·    中：走 HOST DDR    ·    右：交换 HBM + DDR 池")
    ui.banner(slide, 0.90, "箭头是 Decode 每一步的热路径。索引和滑窗三种方案都留在 GPU。")
    cols = [
        (0.36, NAVY, "全放 HBM"),
        (4.56, HOST, "走 HOST DDR"),
        (8.76, TEAL, "交换 HBM + DDR 池"),
    ]
    for x, color, title in cols:
        bar = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.42), Inches(4.05), Inches(0.40))
        ui.solid(bar, color)
        ui.textbox(slide, x, 1.42, 4.05, 0.40, title, 16, True, WHITE, PP_ALIGN.CENTER)

    card(slide, 0.36, 1.98, 4.05, 3.55, SOFT, "GPU HBM", "索引 + 滑窗\n主 KV 全量\n2048 块候选池\n\n每步就在这张卡里读\n带宽 26.4 TB/s\n不经过主机，也不经过交换机", NAVY, INK, 15, 14)
    ui.textbox(slide, 0.36, 5.65, 4.05, 1.20, "批量停在 GPU 房间被占满的地方。短上下文这是最快的，因为热数据本来就在卡上。", 13, False, INK, anchor=MSO_ANCHOR.TOP)

    card(slide, 4.56, 1.98, 4.05, 1.45, SOFT, "GPU HBM", "索引、滑窗，以及装得下的主 KV。", NAVY, INK, 14, 13)
    arrow_down(slide, 6.48, 3.50, 0.22, 0.24, HOST)
    ui.textbox(slide, 6.76, 3.46, 1.70, 0.32, "160 GB/s", 12, True, HOST, anchor=MSO_ANCHOR.MIDDLE)
    card(slide, 4.56, 3.82, 4.05, 1.70, "F8E6D4", "主机 DDR", "装不下的主 KV。\n每步只搬溢出比例 × 5.16 MB。\n每卡容量 96 GB。", HOST, INK, 14, 13)
    ui.textbox(slide, 4.56, 5.65, 4.05, 1.20, "不是把权重和索引也搬到主机。主机只接 GPU 放不下的那一段，而且链路窄。", 13, False, INK, anchor=MSO_ANCHOR.TOP)

    card(slide, 8.76, 1.98, 4.05, 0.95, SOFT, "GPU HBM", "只留索引和滑窗。", NAVY, INK, 14, 13)
    arrow_down(slide, 10.68, 2.98, 0.22, 0.22, TEAL)
    ui.textbox(slide, 10.96, 2.94, 1.70, 0.28, "4.80 TB/s", 12, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)
    card(slide, 8.76, 3.26, 4.05, 1.15, "D5EBE3", "交换芯片 HBM", "2048 块常驻。30 颗 × 64 GB。", TEAL, INK, 14, 13)
    arrow_down(slide, 10.68, 4.46, 0.22, 0.20, DDR)
    card(slide, 8.76, 4.72, 4.05, 0.85, "F6E4D4", "DDR 池", "主 KV 全量。容量不限。不在每步热路径上。", DDR, INK, 13, 12)
    ui.textbox(slide, 8.76, 5.68, 4.05, 1.15, "每步的热路径停在交换芯片。DDR 池只保管装不下的主 KV，GPU 不直接去扫它。", 13, False, INK, anchor=MSO_ANCHOR.TOP)


def slide_compare(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "差别只在热数据走哪条带宽", "容量墙和每步带宽一起决定批量")
    ui.banner(slide, 0.92, "系统 TPS = 全局批 / 实际 TPOT。批量变大但步时更长时，TPS 可以下降。")
    r64 = v41.by_len(data, 65536)
    r4 = v41.by_len(data, 4194304)
    head = ["", "全放 HBM", "走 HOST DDR", "交换 HBM + DDR 池"]
    body = [
        ["热的 5.16 MB", "GPU 自己读", "溢出部分走主机", "常驻交换芯片"],
        ["冷的主 KV", "也在 GPU", "装不下才进主机", "整份在 DDR 池"],
        ["每步带宽", "HBM 26.4 TB/s", "160 GB/s", "D2D 4.80 TB/s"],
        ["先碰到的墙", "GPU 房间", "每卡主机 96 GB", "30×64 GB 装候选池"],
        ["64K · 30 毫秒 TPS", v41.fmt_rate(v41.tps_d(r64, "hbm", "30")), v41.fmt_rate(v41.tps_d(r64, "host", "30")), v41.fmt_rate(v41.tps_d(r64, "sw", "30"))],
        ["4M · 30 毫秒 TPS", v41.fmt_rate(v41.tps_d(r4, "hbm", "30")), v41.fmt_rate(v41.tps_d(r4, "host", "30")), v41.fmt_rate(v41.tps_d(r4, "sw", "30"))],
    ]
    kinds = ["head", "body", "body", "body", "body", "key", "key"]
    ui.add_table(slide, 0.42, 1.50, [2.40, 3.20, 3.40, 3.50], [head] + body, [0.40] + [0.52] * 6, kinds, size=14)
    ui.gold(
        slide,
        5.30,
        1.55,
        "64K 一行里，主机和 HBM 是同一个数：KV 还没溢出，主机根本没被用到。交换方案每步都要读交换芯片，而且 2048 块 × 批量要先放进 30×64 GB，所以更早停批。\n"
        "4M 一行里，主机的批量比 HBM 大，TPS 却低 7.2%：160 GB/s 把步时拉长了。交换方案换入不到 1 毫秒，步时用满 30 毫秒，TPS 高 27.4%。",
        14,
    )


def slide_process(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 7, "分析就按这五步走", "数字来自 deepseek-v41-20t-n2-slo，这里不另算一套")
    ui.banner(slide, 0.92, "前三步三种方案完全一样。从第四步起，只改 KV 放哪、每步从哪读。")
    steps = [
        ("1", "定模型", "V4.1-Flash 的 40 层、隐藏 5120、CSA2 不动。路由专家从 384 加到 14123，凑到 20T。Engram 196B 留在主机，不占 GPU。"),
        ("2", "定集群", "N+2。Decode 一份副本 256 卡，Prefill 缩到 24 卡。算力 48P×70%，HBM 640 GB。拉历史 KV 只用参数面的 25%，每卡 25 GB/s。"),
        ("3", "定热数据", "按 CSA2 数：每步不是重读整段上下文，只读 2048 块再加编码器三组 Top-512，一共 5.16 MB。索引和滑窗留在 GPU。"),
        ("4", "摸批量", "输入从 64K 到 4M。TTFT 不超过 10 秒，TPOT 不超过 10 毫秒和 30 毫秒。每种放法各自把批量加到约束刚好用满。"),
        ("5", "比 TPS", "Prefill 的系统 TPS = 批 × 输入长度 / 实际 TTFT。Decode 的系统 TPS = 批 / 实际 TPOT。用实际耗时，不用 10 毫秒或 30 毫秒去除。"),
    ]
    for i, (n, title, body) in enumerate(steps):
        y = 1.48 + i * 1.05
        bubble = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.46), Inches(y + 0.12), Inches(0.46), Inches(0.46))
        ui.solid(bubble, NAVY)
        ui.textbox(slide, 0.46, y + 0.12, 0.46, 0.46, n, 16, True, WHITE, PP_ALIGN.CENTER)
        ui.textbox(slide, 1.10, y, 2.10, 0.85, title, 16, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
        ui.textbox(slide, 3.20, y, 9.60, 0.90, body, 14, False, INK, anchor=MSO_ANCHOR.MIDDLE)


def slide_takeaway(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 8, "在网 cache 只值当主 KV 已经放不下", "记住短上下文和 4M 这两头")
    ui.banner(slide, 0.92, "缓存对象是 CSA2 的 2048 块，不是整段 KV。整段主 KV 在第三种方案里放 DDR 池。")
    r64 = v41.by_len(data, 65536)
    r4 = v41.by_len(data, 4194304)
    card(
        slide, 0.42, 1.55, 6.15, 3.35, SOFT, "64K，缓存用不上",
        f"全放 HBM 的 30 毫秒批 {v41.fmt_bs(r64['hbm30'])}，房间还没满。\n"
        f"主机没被读到，TPS 和 HBM 一样。\n"
        f"交换芯片要为每条序列留 5.16 MB，30×64 GB 先满，批只有 {v41.fmt_bs(r64['sw30'])}。\n"
        f"系统 TPS {v41.signed_pct(v41.tps_d(r64, 'sw', '30'), v41.tps_d(r64, 'hbm', '30'))}。",
        NAVY, INK, 16, 15,
    )
    card(
        slide, 6.75, 1.55, 6.15, 3.35, "D5EBE3", "4M，缓存才划算",
        f"全放 HBM 的 30 毫秒批 {v41.fmt_bs(r4['hbm30'])}。\n"
        f"主机把批抬到 {v41.fmt_bs(r4['host30'])}，160 GB/s 把步时拉长，TPS {v41.signed_pct(v41.tps_d(r4, 'host', '30'), v41.tps_d(r4, 'hbm', '30'))}。\n"
        f"2048 块放交换 HBM、主 KV 放 DDR 池，批 {v41.fmt_bs(r4['sw30'])}。\n"
        f"换入走 4.80 TB/s，系统 TPS {v41.signed_pct(v41.tps_d(r4, 'sw', '30'), v41.tps_d(r4, 'hbm', '30'))}。",
        TEAL, INK, 16, 15,
    )
    ui.gold(
        slide,
        5.15,
        1.70,
        "一句话：CSA2 把每步要读的历史收成 2048 块。这 2048 块放 GPU，短上下文就够了。放到交换芯片的 HBM 上，等于在网上做一层 cache，只有上下文长到主 KV 必须离开 GPU 时，这层 cache 才比主机 DDR 划算。",
        15,
    )


def audit(prs):
    wide, low = Inches(13.333), Inches(7.50)
    bad = []
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.left is None:
                continue
            if shape.left + shape.width > wide + Emu(40000) or shape.top + shape.height > low + Emu(40000):
                bad.append((i, int(shape.left), int(shape.top), int(shape.width), int(shape.height)))
    return bad


def main():
    data = v41.collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "DS 4.1在网cache"
    blank = prs.slide_layouts[6]
    slide_question(prs, blank, data)
    slide_csa2_map(prs, blank)
    slide_placement(prs, blank)
    slide_csa2(prs, blank)
    slide_three(prs, blank)
    slide_compare(prs, blank, data)
    slide_process(prs, blank)
    slide_takeaway(prs, blank, data)
    prs.save(PPT)
    print("overflow", audit(prs))


if __name__ == "__main__":
    main()
