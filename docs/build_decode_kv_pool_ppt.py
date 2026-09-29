#!/usr/bin/env python3
"""Editable deck: when decode may use an SSD KV pool, and when it must use DDR.

Slides are native text boxes, shapes, and a table. Do not flatten pages to images.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

OUT = Path("/workspace/docs/decode-kv-pool.pptx")
FONT = "Microsoft YaHei"

SW, SH = 13.333333, 7.5
ML = 0.48

INK = (22, 27, 34)
MUTED = (88, 98, 110)
ACCENT = (14, 74, 138)
MUST = (140, 42, 36)
WHITE = (255, 255, 255)
SOFT = (244, 247, 250)
LINE = (214, 221, 229)
NEUTRAL = (96, 106, 118)
SSD_BG = (236, 243, 250)
DDR_BG = (250, 242, 241)
NEU_BG = (246, 247, 249)


def rgb(c: tuple[int, int, int]) -> RGBColor:
    return RGBColor(*c)


def _anchor(tf, anchor: str) -> None:
    body = tf._txBody.find(qn("a:bodyPr"))
    body.set("anchor", {"top": "t", "middle": "ctr", "bottom": "b"}[anchor])


def set_run_font(run, size: float, bold: bool, color: tuple[int, int, int], name: str = FONT) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    run.font.name = name
    r_pr = run._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        el = r_pr.find(qn(f"a:{tag}"))
        if el is None:
            el = r_pr.makeelement(qn(f"a:{tag}"), {})
            r_pr.append(el)
        el.set("typeface", name)


def add_rect(slide, x, y, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(1)
    sp_pr = shape._element.spPr
    effect = sp_pr.find(qn("a:effectLst"))
    if effect is not None:
        sp_pr.remove(effect)
    return shape


def add_text(slide, x, y, w, h, content, *, size=16, bold=False, color=INK, align="left", anchor="top", spacing=1.05):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Inches(0.02)
    tf.margin_right = Inches(0.02)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    _anchor(tf, anchor)
    align_map = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
    if isinstance(content, str):
        blocks = [(content, size, bold, color)]
    else:
        blocks = content
    for i, block in enumerate(blocks):
        text, sz, is_bold, col = block
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align_map[align]
        p.line_spacing = spacing
        p.space_before = Pt(0)
        p.space_after = Pt(2)
        run = p.add_run()
        run.text = text
        set_run_font(run, sz, is_bold, col)
    return shape


def footer(slide, page: int, total: int = 4) -> None:
    add_rect(slide, ML, 7.16, SW - ML * 2, 0.01, LINE)
    add_text(slide, ML, 7.2, 8, 0.26, "Decode KV 池", size=12, color=MUTED, anchor="middle")
    add_text(slide, SW - ML - 1.6, 7.2, 1.6, 0.26, f"{page}  /  {total}", size=12, bold=True, color=ACCENT, align="right", anchor="middle")


def chrome(slide, kicker: str, title: str, conclusion: str, page: int) -> float:
    add_rect(slide, 0, 0, SW, 0.08, ACCENT)
    add_text(slide, ML, 0.16, 12, 0.28, kicker, size=13, bold=True, color=ACCENT, anchor="middle")
    add_text(slide, ML, 0.42, SW - ML * 2, 0.46, title, size=26, bold=True, color=INK, anchor="middle")
    y = 0.96
    h = 0.72
    add_rect(slide, ML, y, SW - ML * 2, h, SOFT)
    add_rect(slide, ML, y, 0.08, h, ACCENT)
    add_text(slide, ML + 0.24, y, SW - ML * 2 - 0.4, h, conclusion, size=15, color=INK, anchor="middle", spacing=1.15)
    footer(slide, page)
    return y + h + 0.16


def slide_decision(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    top = chrome(
        slide,
        "结论",
        "Decode 什么条件下用 SSD 池，什么时候必须用 DDR 池",
        "历史 KV 的数值不变，每步用新的 Q 重读一遍。池子只承接 HBM 放不下的缺页，从第二个 token 起计入 TPOT。",
        1,
    )
    rows = [
        (NEUTRAL, NEU_BG, "不进池", "HBM 装得下", [
            ("历史 KV 能整段留在 decode 侧 HBM。冷前缀若在第一个 token 之前装进 HBM，装载记在 TTFT。", 16, False, INK),
            ("每步只读 HBM，并把新 token 的 KV 写回 HBM。这一步不访问池子。", 16, True, NEUTRAL),
        ]),
        (ACCENT, SSD_BG, "可以用 SSD", "大页把接口喂满", [
            ("缺页在 TPOT 上，同一层连续存放并按层大读，接口被喂满。合同看平均 TPOT，或没有 TPOT 合同。", 16, False, INK),
            ("平均传输时间由接口带宽决定，与 DDR 相同。", 16, True, ACCENT),
        ]),
        (MUST, DDR_BG, "必须用 DDR", "喂不满，或要保 p99", [
            ("缺页在 TPOT 上，而且是小页随机读，或合同写 p99，或单次 IO 的时延已经大于剩余预算。", 16, False, INK),
            ("这时 SSD 喂不满接口，或长尾直接进每一个 token。", 16, True, MUST),
        ]),
    ]
    gap = 0.12
    height = (7.05 - top - gap * 2) / 3
    for i, (rail, bg, label, sub, lines) in enumerate(rows):
        y = top + i * (height + gap)
        add_rect(slide, ML, y, SW - ML * 2, height, bg)
        add_rect(slide, ML, y, 0.08, height, rail)
        add_text(slide, ML + 0.24, y, 2.35, height, [(label, 22, True, rail), (sub, 14, False, MUTED)], anchor="middle", spacing=1.15)
        add_rect(slide, ML + 2.7, y + 0.28, 0.012, height - 0.56, LINE)
        add_text(slide, ML + 2.95, y, SW - ML - (ML + 2.95) - 0.16, height, lines, anchor="middle", spacing=1.2)


def slide_timing(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    top = chrome(
        slide,
        "计时",
        "只有缺页的重读进入 TPOT",
        "交接和第一个 token 的取数记在 TTFT。第二个 token 起，不在 HBM 里的历史 KV 每步重读，才计入 TPOT。",
        2,
    )
    steps = [
        ("1", "交接", "TTFT", "Prefill 把 prompt 的历史 KV 交给 decode。这些 K、V 的数值到这里已经定稿。"),
        ("2", "第一个 token", "TTFT", "读 HBM 里的历史 KV，算出这个 token，把增量 KV 写回 HBM。这时若还要从池里取缺页，仍记在 TTFT。"),
        ("3", "后续每个 token", "TPOT", "用新的 Q 重读全部历史 KV。留在 HBM 的读 HBM，不在的读池。被驱逐的页下一步还要再读。"),
        ("4", "逐层重叠", "TPOT", "下一层的取数可以盖在当前层计算下面。不超过计算，池子只占带宽；超出的部分加进这一步。"),
    ]
    gap = 0.1
    height = (7.05 - top - gap * 3) / 4
    for i, (num, title, clock, body) in enumerate(steps):
        y = top + i * (height + gap)
        add_rect(slide, ML, y, SW - ML * 2, height, WHITE, LINE)
        add_rect(slide, ML, y, 0.08, height, ACCENT if clock == "TPOT" else NEUTRAL)
        add_rect(slide, ML + 0.28, y + (height - 0.46) / 2, 0.46, 0.46, ACCENT)
        add_text(slide, ML + 0.28, y + (height - 0.46) / 2, 0.46, 0.46, num, size=18, bold=True, color=WHITE, align="center", anchor="middle")
        add_text(
            slide,
            ML + 0.9,
            y,
            2.7,
            height,
            [(title, 18, True, INK), (clock, 13, True, ACCENT if clock == "TPOT" else MUTED)],
            anchor="middle",
            spacing=1.05,
        )
        add_text(slide, ML + 3.7, y, SW - ML - (ML + 3.7) - 0.2, height, body, size=16, color=INK, anchor="middle", spacing=1.15)


def slide_criterion(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    top = chrome(
        slide,
        "判据",
        "接口带宽相同，差别只在单次 IO 有多大",
        "长上下文只提供字节数。单次 IO 够大，SSD 与 DDR 的平均时间相同；读变成小页，就必须改用 DDR。",
        3,
    )
    bottom = 7.05
    gap = 0.14
    left_w = 6.15
    add_rect(slide, ML, top, left_w, bottom - top, SOFT)
    add_text(slide, ML + 0.24, top + 0.14, left_w - 0.4, 0.36, "每步访问多少字节", size=16, bold=True, color=ACCENT, anchor="middle")
    formulas = [
        "每 token KV = 2 × 层数 × KV 头数 × 头维 × 字节",
        "单步读取 = 缓存长度 × 每 token KV",
        "单步写入 = 每 token KV",
        "本步池读取 = 不在 HBM 中的历史 KV",
        "单次读取时间 = IO 字节 / 接口带宽 + 介质时延",
    ]
    fy = top + 0.58
    fh = 0.48
    for line in formulas:
        add_rect(slide, ML + 0.24, fy, left_w - 0.48, fh - 0.08, WHITE)
        add_text(slide, ML + 0.36, fy, left_w - 0.72, fh - 0.08, line, size=14, bold=True, color=INK, anchor="middle")
        fy += fh
    add_text(
        slide,
        ML + 0.24,
        fy + 0.06,
        left_w - 0.48,
        bottom - fy - 0.12,
        "70B、GQA、BF16：80 层、8 个 KV 头、头维 128。每 token 320KB。缓存 32768 时单步读取 10GB，每层 128MB。历史内容与上一步相同，只多一个 token。",
        size=13,
        color=MUTED,
        anchor="top",
        spacing=1.2,
    )

    rx = ML + left_w + gap
    rw = SW - ML - rx
    right_h = (bottom - top - gap) / 2
    cards = [
        (top, ACCENT, SSD_BG, "按层大读，可以用 SSD", [
            ("写按一个 token 的小页追加，读按层收成一次区间读。已在 HBM 的部分从区间去掉，长度不超过逐层缓冲，再拆成数 MB 条带。", 14, False, INK),
            ("50GB/s、时延差 100 微秒时，大约 5MB 以上时延就可忽略。一层 128MB 的大读里，时延只占百分之几。", 14, True, ACCENT),
        ]),
        (top + right_h + gap, MUST, DDR_BG, "小页或 p99，必须用 DDR", [
            ("每层每个 token 约 4KB。32K 上下文一步约 260 万次读，要喂满 50GB/s 需要约每秒 1200 万次。SSD 的随机 IOPS 先到顶。", 14, False, INK),
            ("合同若写 p99，垃圾回收的停顿也不随大流量摊薄。", 14, True, MUST),
        ]),
    ]
    for y, rail, bg, title, lines in cards:
        add_rect(slide, rx, y, rw, right_h, bg)
        add_rect(slide, rx, y, 0.08, right_h, rail)
        add_text(slide, rx + 0.24, y + 0.12, rw - 0.4, 0.4, title, size=18, bold=True, color=rail, anchor="middle")
        add_text(slide, rx + 0.24, y + 0.54, rw - 0.4, right_h - 0.68, lines, anchor="top", spacing=1.2)


def _set_cell_border(cell, color: str = "D6DCE2") -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        existing = tc_pr.find(qn(f"a:{edge}"))
        if existing is not None:
            tc_pr.remove(existing)
        ln = etree.SubElement(tc_pr, qn(f"a:{edge}"))
        ln.set("w", "6350")
        solid = etree.SubElement(ln, qn("a:solidFill"))
        srgb = etree.SubElement(solid, qn("a:srgbClr"))
        srgb.set("val", color)


def _set_cell_margins(cell) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    mar = tc_pr.find(qn("a:tcMar"))
    if mar is not None:
        tc_pr.remove(mar)
    mar = etree.SubElement(tc_pr, qn("a:tcMar"))
    for edge, val in (("left", "100000"), ("right", "100000"), ("top", "60000"), ("bottom", "60000")):
        node = etree.SubElement(mar, qn(f"a:{edge}"))
        node.set("mar", val)


def write_cell(cell, text, size, bold, color, fill, align="left") -> None:
    cell.text = ""
    cell.fill.solid()
    cell.fill.fore_color.rgb = rgb(fill)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    _set_cell_border(cell)
    _set_cell_margins(cell)
    tf = cell.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER}[align]
    run = p.add_run()
    run.text = text
    set_run_font(run, size, bold, color)


def slide_table(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    top = chrome(
        slide,
        "总表",
        "先看缺页在不在 TPOT 上，再看这次读能不能喂满接口",
        "HBM 装得下就不进池。装不下时，大页连续读且合同看平均，可以用 SSD；小页随机读或要保 p99，必须用 DDR。",
        4,
    )
    rows = [
        ("历史 KV 能整段留在 decode 侧 HBM", "不进池", "每步只读 HBM，池子不在 TPOT 上", NEUTRAL),
        ("冷前缀在第一个 token 之前装入 HBM", "SSD 可以", "只搬一次，时间记在 TTFT", ACCENT),
        ("长上下文按层连续大读，合同看平均", "SSD 可以", "接口被喂满，平均时间与 DDR 相同", ACCENT),
        ("离线吞吐，没有 TPOT 合同", "SSD 可以", "时延和垃圾回收长尾不进预算", ACCENT),
        ("小页随机读，上下文变长则 IO 次数上升", "必须 DDR", "SSD 喂不满同一条接口", MUST),
        ("合同写的是 p99 TPOT", "必须 DDR", "垃圾回收的停顿不随大流量摊薄", MUST),
        ("单次 IO 太小，时延差大于剩余预算", "必须 DDR", "介质时延直接加进每一个 token", MUST),
    ]
    table_h = 7.05 - top
    shape = slide.shapes.add_table(1 + len(rows), 3, Inches(ML), Inches(top), Inches(SW - ML * 2), Inches(table_h))
    table = shape.table
    table.columns[0].width = Inches(6.15)
    table.columns[1].width = Inches(1.9)
    table.columns[2].width = Inches(SW - ML * 2 - 6.15 - 1.9)
    headers = ["场景", "选择", "原因"]
    for j, text in enumerate(headers):
        write_cell(table.cell(0, j), text, 14, True, WHITE, ACCENT, "left" if j == 0 else "center" if j == 1 else "left")
    for i, (scene, choice, reason, tone) in enumerate(rows, start=1):
        fill = WHITE if i % 2 else SOFT
        write_cell(table.cell(i, 0), scene, 14, False, INK, fill)
        write_cell(table.cell(i, 1), choice, 14, True, tone, fill, "center")
        write_cell(table.cell(i, 2), reason, 14, False, MUTED, fill)


def build() -> None:
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    prs.core_properties.title = "Decode KV 池：何时 SSD，何时必须 DDR"
    slide_decision(prs)
    slide_timing(prs)
    slide_criterion(prs)
    slide_table(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
