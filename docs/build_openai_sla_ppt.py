#!/usr/bin/env python3
"""Editable one-slide deck: OpenAI API SLA, price, and credit remedy."""

from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
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
AMBER_BG = "FBF3EA"
GREEN_BG = "E8F5EE"
HEADER_BG = "0E2A47"
ZEBRA = "F4F7FA"
PLAIN = "FFFFFF"
LINE = "D6DCE2"


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
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)
    return box


def rect(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.fill.background()
    sppr = shape._element.spPr
    effect = sppr.find(qn("a:effectLst"))
    if effect is not None:
        sppr.remove(effect)
    return shape


def fill_cell(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("a:solidFill")):
        tcPr.remove(old)
    solid = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", hex_color)
    solid.append(srgb)
    tcPr.append(solid)


def border_cell(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        ln = OxmlElement(f"a:{edge}")
        ln.set("w", "6350")
        fill = OxmlElement("a:solidFill")
        col = OxmlElement("a:srgbClr")
        col.set("val", LINE)
        fill.append(col)
        ln.append(fill)
        tcPr.append(ln)


def write_cell(cell, text, size, bold, color, align):
    tf = cell.text_frame
    tf.clear()
    tf.word_wrap = True
    cell.margin_left = Inches(0.06)
    cell.margin_right = Inches(0.05)
    cell.margin_top = Inches(0.04)
    cell.margin_bottom = Inches(0.03)
    cell.vertical_anchor = MSO_ANCHOR.TOP
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(1)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "OpenAI API：SLA、售价与未达标补偿"
    prs.core_properties.subject = "公开价目整理"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    rect(slide, 0, 0, 13.333, 0.08, ACCENT)
    add_text(slide, 0.32, 0.14, 12.6, 0.24, "公开价目整理  ·  OpenAI API", 12, True, ACCENT)
    add_text(slide, 0.32, 0.36, 12.6, 0.36, "SLA 承诺、售价与未达标补偿", 24, True, NAVY)
    rect(slide, 0.32, 0.80, 0.07, 0.46, ACCENT)
    add_text(
        slide,
        0.48,
        0.76,
        12.5,
        0.52,
        "带赔付的只有企业 Scale Tier，以及 GPT-5.6 及更早的 Fast。赔的是服务抵扣额度，慢请求已生成的 token 仍按该档单价收取。GPT-6 速度档是加价，没有时延承诺。",
        13,
        True,
        INK,
        anchor=MSO_ANCHOR.MIDDLE,
    )

    headers = ["销售档", "SLA 承诺", "售价（美元 / 百万 token）", "未达成时的补偿"]
    rows = [
        [
            "Standard\n按量",
            "无可用性承诺，无时延承诺。",
            "GPT-6 Astra 短上下文：输入 10，缓存输入 1，输出 50。\n输入超过 272K 时，整单输入 2 倍、输出 1.5 倍。",
            "无赔付。\n已生成 token 按 Standard 单价收取。",
        ],
        [
            "Fast\nGPT-6 系列\nAstra、6.1 Sol、6 Sol、Luna",
            "价目表的可用性与时延为空。\nAstra 的 Fast mode 写明不含时延 SLA。",
            "对应 Standard 的 2 倍。\nAstra 短上下文：输入 20，缓存输入 2，输出 100。\n长上下文：输入 40，输出 150。",
            "无 service credit。\n性能变差且流量爬升过快时，部分请求降为 Standard，按 Standard 价计费，并不再计入 Fast 目标。经验线：已到每分钟 100 万 token，且 15 分钟内再增超过 50%。",
        ],
        [
            "Fast\nGPT-5.6 及更早",
            "企业协议与 Scale Tier 同一套处理。\n时延按每 5 分钟窗口的 p50 统计。\n公开页没有单独的 token/s 门槛表。",
            "GPT-5.6 Sol 为 Standard 的 2 倍。\n短上下文：输入 8，输出 40。\n长上下文：输入 16，输出 60。\n该促销价至少保持到 2026-11-21。",
            "企业客户获得 service credit，经客户经理办理。\n同一个月可用性与时延都未达标时，只赔较高的一笔，不叠加。\n额度不能兑现金、不能转让，发行后一年有效。",
        ],
        [
            "Ultrafast\nGPT-6 Astra",
            "无公开可用性或时延 SLA。\n速度宣传为最多比 Standard 快 8 倍。",
            "Standard 的 6 倍。\n短上下文：输入 60，缓存输入 6，缓存写入 75，输出 300。\n长上下文：输入 120，输出 450。",
            "无公开赔付条款。\n已生成 token 按 Ultrafast 单价收取。",
        ],
        [
            "Scale Tier\n企业预购\n最少 30 天",
            "可用性 99.9%。\n时延为每 5 分钟窗口的 p50，且 99% 的请求快于该模型门槛。\nGPT-5.5 为 50 token/s，GPT-5.4 mini 为 100 token/s，GPT-5 mini 为 80 token/s。\n部分型号不含长上下文。",
            "按 token unit 预购。\nGPT-5.5：输入 5 万 TPM，750 美元/unit/天，无输出包。\nGPT-5.4 mini：输入 5 万 TPM，100 美元/unit/天。\nGPT-5.2：输入 2.5 万 TPM 为 105 美元/unit/天，输出 2500 TPM 为 84 美元/unit/天。\n15 分钟窗口未超过额度不另收费，超出按 Fast 按量计。",
            "该月时延和可用性都未达标时，按该月这笔 token unit 采购赔 service credit，取两项中较高的一笔。\n赔付比例未公开。\n额度不能兑现金，发行后一年有效。",
        ],
    ]
    # Compensation column: 0 = no credit, 1 = service credit.
    credit = [0, 0, 1, 0, 1]
    heights = [0.32, 0.72, 1.05, 1.02, 0.82, 1.28]

    data = [headers] + rows
    shape = slide.shapes.add_table(len(data), 4, Inches(0.28), Inches(1.36), Inches(12.76), Inches(5.72))
    table = shape.table
    widths = [1.85, 3.45, 3.85, 3.61]
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    for r, h in enumerate(heights):
        table.rows[r].height = Inches(h)

    for r, row in enumerate(data):
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            header = r == 0
            if header:
                bg, color, bold, size = HEADER_BG, WHITE, True, 11
            elif c == 3:
                bg = GREEN_BG if credit[r - 1] else AMBER_BG
                color, bold, size = INK, False, 10
            elif r % 2 == 0:
                bg, color, bold, size = ZEBRA, INK, c == 0, 10
            else:
                bg, color, bold, size = PLAIN, INK, c == 0, 10
            if header:
                color = WHITE
            write_cell(cell, text, size, bold or header, color, PP_ALIGN.LEFT)
            if header:
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            fill_cell(cell, bg)
            border_cell(cell)

    add_text(
        slide,
        0.28,
        7.14,
        9.4,
        0.26,
        "时延门槛是生成速度（token/s），不是 TTFT 毫秒，也不是 TPOT 的 p99。绿色格为有赔付，米色格为无赔付。",
        10,
        False,
        MUTED,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    add_text(slide, 9.6, 7.14, 3.45, 0.26, "来源：OpenAI 公开价目与 SLA 页", 10, False, MUTED, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)

    notes = slide.notes_slide.notes_text_frame
    notes.text = (
        "来源：https://openai.com/api-scale-tier/ ；"
        "https://developers.openai.com/api/docs/guides/fast-mode ；"
        "https://developers.openai.com/api/docs/pricing ；"
        "https://developers.openai.com/api/docs/guides/ultrafast-mode ；"
        "https://openai.com/policies/service-credit-terms/ 。"
        "Scale Tier 与 Fast（GPT-5.6 及更早）的赔付比例不在公开页，写在企业协议里。"
        "价格为短上下文标价。长上下文按整单另计。"
    )

    out = "/workspace/docs/openai-sla-price-credit.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
