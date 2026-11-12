#!/usr/bin/env python3
"""Two slides: public measurements of repeated same-prefix KV hits.

Figures are copied from the papers, not redrawn.

Case 1. Ying He et al., Characterizing Predictability–Throughput
Trade-offs of KV-Cache SSD Offloading in LMCache, arXiv:2610.21249.
Figures 1(a), 1(b) and 3.

Case 2. Muhammad Ibrahim, When the KV Cache Is Slower Than the GPU,
arXiv:2610.21500. Figures 3 and 5.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

FONT = "Microsoft YaHei"
NAVY = "0E2A47"
ACCENT = "145A96"
TEAL = "0E7A76"
INK = "1C242E"
MUTED = "5A636E"
WHITE = "FFFFFF"
LINE = "D6DCE2"
SOFT = "F4F7FA"
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"

ROOT = Path(__file__).resolve().parent
FIG = ROOT / "figures" / "kv-hit"
OUT = ROOT / "相同prefix命中-存储吞吐.pptx"
FOOTER = "相同 prefix 命中    ·    原图摘自公开论文    ·    说明按正文数字写"


def rgb(value):
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def set_run_font(run, size, bold, color):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    rpr = run._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        el = rpr.find(qn(f"a:{tag}"))
        if el is None:
            el = OxmlElement(f"a:{tag}")
            rpr.append(el)
        el.set("typeface", FONT)


def strip_shadow(shape):
    effect = shape._element.spPr.find(qn("a:effectLst"))
    if effect is not None:
        shape._element.spPr.remove(effect)


def solid(shape, fill, line=None, line_pt=1.0):
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(line_pt)
    strip_shadow(shape)


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
        body_pr = body.find(qn("a:bodyPr"))
        if body_pr is not None:
            body_pr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = line
        set_run_font(run, size, bold, color)
    return shape


def rect(slide, x, y, w, h, fill, line=None, line_pt=1.0, rounded=True):
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill, line, line_pt)
    if rounded:
        shape.adjustments[0] = 0.08
    return shape


def chrome(slide, page, kicker, title, subtitle):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    solid(bar, ACCENT)
    textbox(slide, 0.40, 0.14, 10.6, 0.24, kicker, 12, True, ACCENT)
    textbox(slide, 11.15, 0.14, 1.78, 0.24, f"{page}  /  2", 12, False, MUTED, PP_ALIGN.RIGHT)
    textbox(slide, 0.40, 0.38, 12.5, 0.38, title, 24, True, NAVY)
    textbox(slide, 0.40, 0.78, 12.5, 0.26, subtitle, 13, False, MUTED)


def picture(slide, name, x, y, w):
    """Place a figure at width w, height from its own aspect, with a thin frame."""
    with Image.open(FIG / name) as im:
        aspect = im.size[0] / im.size[1]
    pad = 0.03
    inner_w = w - 2 * pad
    inner_h = inner_w / aspect
    h = inner_h + 2 * pad
    rect(slide, x, y, w, h, WHITE, LINE, 1.0, rounded=False)
    slide.shapes.add_picture(str(FIG / name), Inches(x + pad), Inches(y + pad), Inches(inner_w), Inches(inner_h))
    return h


def footer(slide, source):
    box = rect(slide, 0.40, 6.28, 12.52, 0.78, GOLD_BG)
    textbox(slide, 0.56, 6.34, 12.20, 0.66, source, 12, False, GOLD)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.40), Inches(7.16), Inches(12.52), Inches(0.012))
    solid(rule, LINE)
    textbox(slide, 0.40, 7.18, 12.52, 0.24, FOOTER, 11, False, MUTED)


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "相同 prefix 命中时的存储吞吐"
    blank = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank)
    slide.notes_slide.notes_text_frame.text = (
        "Ying He, Dingsen Shi, Yanbo Dai, Donger Chen, Harry Fu, Chris Tsu, "
        "Wang Feng, Song Fu. Characterizing Predictability–Throughput "
        "Trade-offs of KV-Cache SSD Offloading in LMCache for LLM Serving "
        "Systems. arXiv:2610.21249. Figures 1(a), 1(b), 3. "
        "https://arxiv.org/html/2610.21249"
    )
    chrome(
        slide,
        1,
        "案例 1    ·    LMCache 落 SSD    ·    arXiv:2610.21249",
        "同一段 prefix，命中一次就再读一遍 SSD",
        "100 次请求，上下文和提示完全相同。图是论文 Fig. 1 与 Fig. 3 的原图。",
    )
    textbox(slide, 0.40, 1.08, 6.20, 0.24, "Fig. 1(a)  页缓存还在，重复读没有落到 SSD", 12, True, TEAL)
    textbox(slide, 6.76, 1.08, 6.16, 0.24, "Fig. 1(b)  O_DIRECT，99 次命中每次重读同一 chunk", 12, True, ACCENT)
    picture(slide, "lmcache_set_a_pagecache.png", 0.40, 1.34, 6.20)
    picture(slide, "lmcache_set_a_odirect.png", 6.76, 1.34, 6.16)

    picture(slide, "lmcache_set_a_ttft.png", 0.40, 4.48, 4.36)
    rect(slide, 4.92, 4.48, 8.00, 1.70, SOFT, LINE, 1.0)
    textbox(
        slide,
        5.08,
        4.54,
        7.68,
        1.58,
        "Set A 约 94 token，100 次独立请求。\n"
        "去重之后 SSD 只写一次 11.75 MB。随后 99 次热命中产生 9,405 次读，合计 1.16 GB，每次约 12 MB。\n"
        "热 TTFT：页缓存 27 ms，直读 SSD 93.1 ms。\n"
        "GPU 前缀块是 16 token，盘上 chunk 是 256 token。尾部 14 token 没进 GPU 块，仍把整个 chunk 读回。",
        13,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )
    footer(
        slide,
        "He 等，arXiv:2610.21249，Fig. 1 与 Fig. 3。纵轴是块层提交速率，不是盘的物理带宽。\n"
        "这是同一内容被逐次重读。论文这组没有做多客户端并发扫描。",
    )

    slide = prs.slides.add_slide(blank)
    slide.notes_slide.notes_text_frame.text = (
        "Muhammad Ibrahim. When the KV Cache Is Slower Than the GPU: "
        "Scaling Remote KV Tiers for Context-Parallel Prefill. "
        "arXiv:2610.21500. Figures 3 and 5. "
        "https://arxiv.org/html/2610.21500"
    )
    chrome(
        slide,
        2,
        "案例 2    ·    LMCache + Valkey    ·    arXiv:2610.21500",
        "八个客户端打同一个存储实例，带宽几乎不涨",
        "GLM-5.3，8×B300。每个客户端一批 8 个 12.4 MB chunk，共 99 MB。图是论文 Fig. 3 与 Fig. 5 的原图。",
    )
    textbox(slide, 0.40, 1.08, 6.30, 0.24, "Fig. 3  聚合 GET 带宽", 12, True, TEAL)
    textbox(slide, 7.20, 1.08, 5.70, 0.24, "Fig. 5  预填充延迟。红线是单实例同步加载", 12, True, ACCENT)
    picture(slide, "valkey_get_bandwidth.png", 0.40, 1.34, 6.30)
    picture(slide, "valkey_latency_cdf.png", 7.20, 1.34, 5.73)

    rect(slide, 0.40, 4.62, 6.30, 1.56, PALE, TEAL, 1.25)
    textbox(
        slide,
        0.54,
        4.68,
        6.02,
        1.44,
        "1 个客户端、1 个实例：1.51 GB/s。8 个客户端打同一个实例：1.71 GB/s，只多 13%。\n"
        "一批 99 MB 的 p50 从 65 ms 变成 440 ms。拆成 8 个实例后是 10.76 GB/s，批次回到 70 ms。\n"
        "16k token 重算 0.31 秒，远程命中 0.88 秒。单实例回放的 p99 是 83.32 秒，GPU 只有 7% 在忙。",
        13,
        False,
        INK,
        anchor=MSO_ANCHOR.TOP,
    )
    footer(
        slide,
        "Ibrahim，arXiv:2610.21500，Fig. 3 与 Fig. 5。GET 排在 Valkey 的一条主线程上，I/O 线程只并行套接字读写。\n"
        "带宽不涨是服务线程排队。论文没有把它测成单个 DRAM bank 的冲突。",
    )

    prs.save(OUT)


if __name__ == "__main__":
    build()
