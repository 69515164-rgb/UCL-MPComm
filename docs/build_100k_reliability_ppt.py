#!/usr/bin/env python3
"""Editable deck: reliability from 10k to 100k GPU training."""

from __future__ import annotations

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

W = Inches(13.333)
H = Inches(7.5)
FONT = "Microsoft YaHei"

NAVY = (14, 42, 71)
INK = (28, 36, 46)
MUTED = (90, 99, 110)
LINE = (214, 220, 226)
WHITE = (255, 255, 255)
SOFT = (244, 247, 250)
ACCENT = (20, 90, 150)
RED = (140, 42, 36)
GREEN = (27, 110, 72)
AMBER = (148, 96, 28)
BAND = (232, 240, 248)

# Counts, not rounded percents. Pies are drawn from these.
LLAMA = [
    ("故障 GPU", 148, (166, 54, 46)),
    ("HBM3 显存", 72, (214, 122, 42)),
    ("其他 GPU", 48, (196, 160, 72)),
    ("软件与依赖", 56, (31, 106, 165)),
    ("网络与通信超时", 49, (18, 122, 110)),
    ("主机", 46, (96, 110, 126)),
]
META32 = [
    ("HBM3 显存", 155, (214, 122, 42)),
    ("PCIe 设备", 122, (166, 54, 46)),
    ("通信超时与网络", 97, (18, 122, 110)),
    ("维护、内核与重启", 119, (96, 110, 126)),
    ("GPU 计算", 59, (31, 106, 165)),
    ("软件、数值与其他", 126, (120, 96, 64)),
]
SYNC = [
    ("全体停顿", 10, (166, 54, 46)),
    ("全速训练", 8, (27, 110, 72)),
]
ASYNC = [
    ("完全停顿", 3, (166, 54, 46)),
    ("少一个副本", 7, (214, 122, 42)),
    ("全速训练", 8, (27, 110, 72)),
]


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


def add_text(slide, x, y, w, h, text, size, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
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
    lines = text.split("\n") if isinstance(text, str) else list(text)
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)
    return box


def rect(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(0.75)
    # no shadow
    sppr = shape._element.spPr
    effect = sppr.find(qn("a:effectLst"))
    if effect is not None:
        sppr.remove(effect)
    return shape


def chrome(slide, kicker, title, claim):
    rect(slide, 0, 0, 13.333, 0.08, ACCENT)
    add_text(slide, 0.42, 0.18, 12.4, 0.28, kicker, 12, True, ACCENT)
    add_text(slide, 0.42, 0.42, 12.4, 0.42, title, 26, True, NAVY)
    rect(slide, 0.42, 0.96, 0.08, 0.42, ACCENT)
    add_text(slide, 0.60, 0.94, 12.2, 0.46, claim, 14, True, INK, anchor=MSO_ANCHOR.MIDDLE)
    add_text(slide, 0.42, 7.18, 10.6, 0.22, "公开数据整理  ·  健康迭代 MFU 与有效训练时间分开计", 10, False, MUTED)
    add_text(slide, 10.4, 7.18, 2.5, 0.22, "", 10, False, MUTED, align=PP_ALIGN.RIGHT)


def style_table(table, header=True):
    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.04)
            cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            solid = OxmlElement("a:solidFill")
            srgb = OxmlElement("a:srgbClr")
            if r == 0 and header:
                srgb.set("val", "0E2A47")
                color = WHITE
                bold = True
                size = 11
            elif r % 2 == 0:
                srgb.set("val", "F4F7FA")
                color = INK
                bold = False
                size = 11
            else:
                srgb.set("val", "FFFFFF")
                color = INK
                bold = False
                size = 11
            solid.append(srgb)
            # replace existing solid fill
            for old in tcPr.findall(qn("a:solidFill")):
                tcPr.remove(old)
            tcPr.append(solid)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    set_run_font(run, size, bold, color)
            for edge in ("lnL", "lnR", "lnT", "lnB"):
                ln = OxmlElement(f"a:{edge}")
                ln.set("w", "6350")
                fill = OxmlElement("a:solidFill")
                col = OxmlElement("a:srgbClr")
                col.set("val", "D6DCE2")
                fill.append(col)
                ln.append(fill)
                tcPr.append(ln)


def write_cell(cell, text, size=11, bold=False, color=INK, align=PP_ALIGN.LEFT):
    cell.text_frame.clear()
    cell.text_frame.word_wrap = True
    p = cell.text_frame.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    set_run_font(run, size, bold, color)


def add_table(slide, x, y, w, h, rows, cols, data, col_widths=None, font=11):
    shape = slide.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w), Inches(h))
    table = shape.table
    if col_widths:
        for i, cw in enumerate(col_widths):
            table.columns[i].width = Inches(cw)
    for r in range(rows):
        for c in range(cols):
            header = r == 0
            write_cell(
                table.cell(r, c),
                data[r][c],
                size=font,
                bold=header or c == 0,
                color=WHITE if header else INK,
                align=PP_ALIGN.LEFT if c == 0 or header else PP_ALIGN.CENTER,
            )
    style_table(table)
    return shape


def _ensure_txpr(parent, size_pt):
    if parent is None:
        return
    txpr = parent.find(qn("c:txPr"))
    if txpr is None:
        txpr = OxmlElement("c:txPr")
        parent.append(txpr)
    body = txpr.find(qn("a:bodyPr"))
    if body is None:
        body = OxmlElement("a:bodyPr")
        txpr.append(body)
    lst = txpr.find(qn("a:lstStyle"))
    if lst is None:
        txpr.append(OxmlElement("a:lstStyle"))
    p = txpr.find(qn("a:p"))
    if p is None:
        p = OxmlElement("a:p")
        txpr.append(p)
    ppr = p.find(qn("a:pPr"))
    if ppr is None:
        ppr = OxmlElement("a:pPr")
        p.append(ppr)
    defr = ppr.find(qn("a:defRPr"))
    if defr is None:
        defr = OxmlElement("a:defRPr")
        ppr.append(defr)
    defr.set("sz", str(int(size_pt * 100)))
    for tag in ("latin", "ea", "cs"):
        el = defr.find(qn(f"a:{tag}"))
        if el is None:
            el = OxmlElement(f"a:{tag}")
            defr.append(el)
        el.set("typeface", FONT)


def color_pie(chart, colors):
    series = chart.series[0]
    for i, color in enumerate(colors):
        pt = series.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = rgb(color)
        pt.format.line.color.rgb = rgb(WHITE)
        pt.format.line.width = Pt(1.25)


def add_pie(slide, x, y, w, h, title, items, total_note):
    labels = []
    values = []
    colors = []
    total = sum(v for _, v, _ in items)
    for name, value, color in items:
        pct = value / total * 100
        labels.append(f"{name}  {pct:.1f}%")
        values.append(value)
        colors.append(color)
    data = CategoryChartData()
    data.categories = labels
    data.add_series("次数", values)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.PIE, Inches(x), Inches(y + 0.32), Inches(w), Inches(h - 0.88), data
    )
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    plot = chart.plots[0]
    plot.has_data_labels = False
    color_pie(chart, colors)
    legend = chart._element.find(".//" + qn("c:legend"))
    _ensure_txpr(legend, 11)
    # chart title off; we draw our own
    chart.has_title = False
    add_text(slide, x, y, w, 0.32, title, 14, True, NAVY)
    add_text(slide, x, y + h - 0.28, w, 0.28, total_note, 10, False, MUTED)
    return chart


def slide_conclusion(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        s,
        "训练可靠性  ·  1 万卡到 10 万卡",
        "10 万卡先被打穿的是有效训练时间",
        "健康迭代的 MFU 在 1.6 万卡仍有 38%–55%。10 万卡公开材料没有同等 MFU，同步恢复把有效时间打到 44%。",
    )
    cards = [
        ("1.2 万–1.6 万卡", ">90%", "有效训练时间", "Llama 3、MegaScale 的生产窗口", GREEN),
        ("10 万卡  ·  全体同步恢复", "44%", "每 18 分钟故障，停 10 分钟", "Meta 在 9.8 万卡上测到的恢复上限", RED),
        ("10 万卡  ·  按副本恢复", "80%", "完全停顿收到约 3 分钟", "12 个副本，少副本的 7 分钟仍在训练", GREEN),
    ]
    for i, (k, num, sub, note, color) in enumerate(cards):
        x = 0.42 + i * 4.25
        rect(s, x, 1.62, 4.05, 2.55, WHITE, LINE)
        rect(s, x, 1.62, 4.05, 0.08, color)
        add_text(s, x + 0.2, 1.82, 3.65, 0.36, k, 13, True, MUTED)
        add_text(s, x + 0.2, 2.18, 3.65, 0.85, num, 40, True, color)
        add_text(s, x + 0.2, 3.05, 3.65, 0.36, sub, 14, True, INK)
        add_text(s, x + 0.2, 3.46, 3.65, 0.5, note, 12, False, MUTED)
    add_text(
        s,
        0.42,
        4.38,
        12.5,
        0.7,
        "40% 的单步 MFU × 44% 的有效时间 ≈ 峰值算力的 18%。按副本异步恢复后，同一单步效率对应约 32%。\n"
        "故障原因饼图有 1.6 万卡和 3.2 万卡两份。10 万卡公开的是故障间隔和恢复时间，没有第二份原因饼。",
        14,
        False,
        INK,
    )
    headers = ["口径", "怎么读", "10 万卡上谁先变"]
    rows = [
        ["健康迭代 MFU", "故障之间，一步吞吐相对峰值算力", "固定 batch 和慢卡会再掉几个点，不是腰斩"],
        ["有效训练时间", "有进展的时间 / 墙钟，含重启", "同步恢复从 1.6 万卡的 >90% 降到 44%"],
    ]
    data = [headers] + rows
    add_table(s, 0.42, 5.2, 12.5, 1.7, 3, 3, data, [2.4, 5.3, 4.8], font=12)


def slide_scale(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        s,
        "对照  ·  已发表数字",
        "卡数上去之后，先变的是故障间隔和重启",
        "1.6 万卡大约 3 小时一次意外中断，有效时间仍高于 90%。10 万卡的生产估计是 18 分钟一次。",
    )
    headers = ["来源", "规模", "故障间隔", "有效训练时间", "健康迭代 MFU"]
    data = [
        headers,
        ["Llama 3\n405B 稠密", "16,384 H100", "54 天 419 次意外\n约 3 小时一次", ">90%", "BF16 38%–43%\n16K / DP=128 为 41%"],
        ["MegaScale\n175B 稠密", "12,288 卡", "数周自动恢复\n100 次以上", ">90%\n诊断 <10 分钟\n追上 <15 分钟", "55.2%\n3,072 卡时为 59.1%"],
        ["Meta 生产\n约 3.2 万卡", "约 32,000", "每千台服务器\n每天 2.3 次", "95%–97%", "未单列"],
        ["Meta FT-HSDP\n10 万卡估计", "约 100,000\n恢复实验 98,000", "每 18 分钟一次\n线性外推约 50 分钟", "同步恢复 44%\n按副本恢复 80%", "正常步长约 20 秒\n未给 MFU"],
    ]
    add_table(s, 0.35, 1.58, 12.65, 4.85, 5, 5, data, [2.15, 2.15, 2.7, 2.7, 2.95], font=13)
    add_text(
        s,
        0.42,
        6.55,
        12.5,
        0.55,
        "18 分钟比 3.2 万卡故障率线性外推的约 50 分钟更密，不能只按硬件故障率放大。\n"
        "Llama 3 论文：arxiv.org/abs/2407.21783    MegaScale：arxiv.org/abs/2402.15627    FT-HSDP：arxiv.org/abs/2602.00277",
        12,
        False,
        MUTED,
    )


def slide_pies(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        s,
        "故障原因占比  ·  意外中断",
        "从 1.6 万卡到 3.2 万卡，显存和 PCIe 上来，裸 GPU 计算下去",
        "两张饼都按论文表内次数绘制。10 万卡没有公开的原因分解，不能把右图直接当成 10 万卡。",
    )
    add_pie(
        s, 0.25, 1.58, 6.4, 5.35,
        "Llama 3  ·  16,384 卡  ·  419 次意外中断",
        LLAMA,
        "论文写 GPU 类 58.7%。表内 GPU 行加总 268/419 = 64%，含静默错误和散热。",
    )
    add_pie(
        s, 6.7, 1.58, 6.4, 5.35,
        "Meta  ·  约 32,000 卡  ·  678 次中断",
        META32,
        "硬件相关 78%。GPU 计算故障从首位降到 7.4%，靠隔离坏卡。",
    )


def slide_100k(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        s,
        "10 万卡  ·  每 18 分钟的墙钟",
        "同步恢复有 56% 的时间停着；按副本恢复后完全停顿只占 17%",
        "左图是全体一起重启。右图是 12 个副本里只重修坏掉的那一个，另外 7 分钟以 11/12 的速度继续跑。有效算力 80%。",
    )
    add_pie(
        s, 0.28, 1.58, 4.55, 5.35,
        "同步恢复  ·  有效算力 44%",
        SYNC,
        "10 分钟停顿 / 18 分钟。9.8 万卡恢复上限约 10 分钟。",
    )
    add_pie(
        s, 4.9, 1.58, 4.55, 5.35,
        "按副本恢复  ·  有效算力 80%",
        ASYNC,
        "完全停顿 3 分钟。少副本的 7 分钟仍有 11/12 吞吐。",
    )
    rect(s, 9.6, 1.9, 3.35, 4.55, SOFT, LINE)
    add_text(s, 9.78, 2.05, 3.05, 0.55, "9.8 万卡同步恢复拆开", 14, True, NAVY)
    steps = [
        ("5 分钟", "冷申请 GPU 的上限", True),
        ("200 秒", "NCCL 建连。1.6 万卡约 17 秒", True),
        ("数分钟", "恢复后第一步。正常步约 20 秒", True),
        ("60 秒", "检测目前靠超时", False),
        ("不随规模涨", "取 checkpoint 与健康检查", False),
    ]
    y = 2.7
    for num, label, hot in steps:
        add_text(s, 9.78, y, 3.05, 0.28, num, 16, True, RED if hot else ACCENT)
        add_text(s, 9.78, y + 0.28, 3.05, 0.32, label, 12, False, INK)
        y += 0.7


def slide_mfu(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    chrome(
        s,
        "这些损失进哪一个指标",
        "重启打有效时间，慢卡和跨楼打单步 MFU",
        "Checkpoint 写盘在异步之后不在这张 10 分钟账单里。写进共享存储追不上故障间隔，是另一件事。",
    )
    headers = ["顺序", "因素", "公开量级", "打在"]
    data = [
        headers,
        ["1", "全体同步重启", "10 分钟 / 18 分钟，有效时间 44%", "有效训练时间"],
        ["2", "慢卡、慢链路、软件抖动", "万卡作业完成时间平均拉长到 1.34 倍", "单步 MFU"],
        ["3", "固定 batch 与跨楼时延", "1.2 万卡 MFU 59%→55%；跨楼时延约 30 倍于柜内", "单步 MFU"],
        ["4", "静默数值错误", "占中断约 1%–6%，单次排查以小时到天计", "已完成步数作废"],
        ["5", "Checkpoint 写盘", "异步分片后 GPU 阻塞是亚秒", "不主导"],
    ]
    add_table(s, 0.35, 1.58, 12.65, 3.55, 6, 4, data, [1.1, 3.3, 5.55, 2.7], font=13)
    rect(s, 0.35, 5.35, 12.65, 1.55, SOFT, LINE)
    add_text(s, 0.55, 5.48, 12.2, 0.32, "收到第 1 项之后，限制回到第 2、3 项", 14, True, NAVY)
    add_text(
        s,
        0.55,
        5.88,
        12.2,
        0.85,
        "按副本恢复把有效时间收到约 80%。此后每一步仍等最慢的 rank。时延敏感的集合通信要留在同一栋楼，跨楼只跑副本间的梯度。\n"
        "Greyhound（ATC 2025）统计的是万卡集群里 512–1,024 卡的作业，不是 10 万卡全量。慢的主因是网络拥塞和 GPU 退化。",
        13,
        False,
        INK,
    )


def build():
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    prs.core_properties.title = "万卡到10万卡训练可靠性"
    prs.core_properties.subject = "故障占比与有效训练时间"
    slide_conclusion(prs)
    slide_scale(prs)
    slide_pies(prs)
    slide_100k(prs)
    slide_mfu(prs)
    out = "/workspace/docs/100k-train-reliability.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    build()
