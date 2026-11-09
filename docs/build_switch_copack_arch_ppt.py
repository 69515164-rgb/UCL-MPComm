#!/usr/bin/env python3
"""One editable slide: feasible switch-local KV placement for 256-GPU decode."""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

FONT = "Microsoft YaHei"
NAVY = "0E2A47"
TEAL = "0E7A76"
INK = "1C242E"
MUTED = "5A636E"
WHITE = "FFFFFF"
LINE = "D6DCE2"
SOFT = "F4F7FA"
PALE = "E7F3F2"
GOLD_BG = "F8F1E4"
GOLD = "7A541C"
CHIP = "E8EEF5"

OUT = "/agent/repos/ucl-mpcomm/docs/switch-copack-kv-arch.pptx"


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


def arrow(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    solid(shape, fill)
    return shape


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "交换机本地内存上的 Decode KV"
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    textbox(slide, 0.40, 0.22, 10.6, 0.40, "扫描留在 GPU，冷 CSA 放在交换机本地内存", 26, True, NAVY)
    textbox(
        slide,
        0.40,
        0.64,
        10.2,
        0.28,
        "256 卡 Decode    ·    30 个平面    ·    每平面对外 400T，256×1.6T 只接 GPU",
        13,
        False,
        MUTED,
    )
    textbox(slide, 10.6, 0.28, 2.3, 0.28, "架构  /  1", 12, False, MUTED, PP_ALIGN.RIGHT)

    # Three columns
    cards = [
        (0.36, "GPU", "256 卡  ·  TP=8  ·  DP=32", NAVY),
        (4.72, "交换芯片", "每颗一平面  ·  ×30", TEAL),
        (9.08, "本地 DRAM", "挂在芯片自己的内存总线  ·  ×30", GOLD),
    ]
    for x, title, sub, color in cards:
        rect(slide, x, 1.08, 3.88, 4.28, WHITE, LINE, 1.25, rounded=False)
        rect(slide, x, 1.08, 3.88, 0.62, color, rounded=False)
        textbox(slide, x + 0.16, 1.10, 3.56, 0.32, title, 16, True, WHITE)
        textbox(slide, x + 0.16, 1.38, 3.56, 0.26, sub, 11, False, WHITE)

    # GPU body
    gx = 0.36
    textbox(slide, gx + 0.16, 1.82, 3.56, 0.36, "每条序列只在一组 8 卡上。\nKV 按字节切开，组播扇出是 1。", 12, False, INK, anchor=MSO_ANCHOR.TOP)
    rect(slide, gx + 0.16, 2.28, 3.56, 1.92, SOFT, LINE, 1.0)
    textbox(slide, gx + 0.30, 2.34, 3.28, 0.26, "HBM 里本步留下", 13, True, NAVY)
    rows = (
        ("索引", "2.01 GB / 条"),
        ("HCA latent", "0.59 GB / 条"),
        ("滑窗", "4.5 MB"),
    )
    for i, (name, val) in enumerate(rows):
        y = 2.66 + i * 0.42
        rect(slide, gx + 0.30, y, 0.14, 0.26, TEAL if i < 2 else "8AA8A6", rounded=False)
        textbox(slide, gx + 0.52, y, 1.50, 0.26, name, 13, True, INK)
        textbox(slide, gx + 1.90, y, 1.66, 0.26, val, 13, False, NAVY, PP_ALIGN.RIGHT)
    rect(slide, gx + 0.16, 4.32, 3.56, 0.86, PALE, "B7D9D7", 1.0)
    textbox(
        slide,
        gx + 0.30,
        4.38,
        3.28,
        0.74,
        "4M · 30 毫秒批的扫描集是 43 TB。\nGPU 上 151 TB 的 KV 房间装得下。\n扫完索引，发出一次 gather。",
        12,
        False,
        TEAL,
        anchor=MSO_ANCHOR.TOP,
    )

    # Switch body
    sx = 4.72
    textbox(slide, sx + 0.16, 1.82, 3.56, 0.36, "256 个 1.6T 端口全部接 GPU。\n访存按线速，对外容量 400T。", 12, False, INK, anchor=MSO_ANCHOR.TOP)
    rect(slide, sx + 0.16, 2.28, 3.56, 1.92, CHIP, "C5D2E4", 1.0)
    textbox(slide, sx + 0.30, 2.34, 2.20, 0.26, "合封 HBM", 13, True, NAVY)
    textbox(slide, sx + 2.20, 2.34, 1.36, 0.26, "64 GB", 13, True, TEAL, PP_ALIGN.RIGHT)
    textbox(slide, sx + 0.30, 2.64, 3.28, 0.24, "线速缓存，只放当前选中的 CSA 页", 12, False, INK)
    rect(slide, sx + 0.30, 2.96, 3.28, 0.48, WHITE, LINE, 1.0)
    textbox(slide, sx + 0.42, 2.96, 1.70, 0.48, "30 毫秒 · 4M", 12, False, MUTED)
    textbox(slide, sx + 2.00, 2.96, 1.42, 0.48, "约 10 GB", 14, True, NAVY, PP_ALIGN.RIGHT)
    rect(slide, sx + 0.30, 3.52, 3.28, 0.48, WHITE, LINE, 1.0)
    textbox(slide, sx + 0.42, 3.52, 1.70, 0.48, "10 毫秒 · 4M", 12, False, MUTED)
    textbox(slide, sx + 2.00, 3.52, 1.42, 0.48, "约 5 GB", 14, True, NAVY, PP_ALIGN.RIGHT)
    rect(slide, sx + 0.16, 4.32, 3.56, 0.86, PALE, "B7D9D7", 1.0)
    textbox(
        slide,
        sx + 0.30,
        4.38,
        3.28,
        0.74,
        "64 GB 盖住这一平面的选中页。\n命中后从原来的 1.6T 端口送回。\n每卡约 1.15 GB，传输 0.24 毫秒。",
        12,
        False,
        TEAL,
        anchor=MSO_ANCHOR.TOP,
    )

    # DRAM body
    dx = 9.08
    textbox(slide, dx + 0.16, 1.82, 3.56, 0.36, "不占 256 个 GPU 端口。\n每颗芯片后面一块内存板。", 12, False, INK, anchor=MSO_ANCHOR.TOP)
    rect(slide, dx + 0.16, 2.28, 3.56, 1.92, GOLD_BG, "E4D3B0", 1.0)
    textbox(slide, dx + 0.30, 2.34, 3.28, 0.26, "冷 CSA latent", 13, True, GOLD)
    rect(slide, dx + 0.30, 2.70, 3.28, 0.58, WHITE, "E4D3B0", 1.0)
    textbox(slide, dx + 0.42, 2.70, 1.55, 0.58, "30 毫秒 · 4M", 12, False, MUTED)
    textbox(slide, dx + 1.90, 2.70, 1.52, 0.58, "6.5 TB", 16, True, GOLD, PP_ALIGN.RIGHT)
    rect(slide, dx + 0.30, 3.40, 3.28, 0.58, WHITE, "E4D3B0", 1.0)
    textbox(slide, dx + 0.42, 3.40, 1.55, 0.58, "10 毫秒 · 4M", 12, False, MUTED)
    textbox(slide, dx + 1.90, 3.40, 1.52, 0.58, "1.1 TB", 16, True, GOLD, PP_ALIGN.RIGHT)
    rect(slide, dx + 0.16, 4.32, 3.56, 0.86, GOLD_BG, "E4D3B0", 1.0)
    textbox(
        slide,
        dx + 0.30,
        4.38,
        3.28,
        0.74,
        "未选中的页才放这里。\n选中页换入时才读 DRAM。\n稳态读落在 64 GB 的 HBM 上。",
        12,
        False,
        GOLD,
        anchor=MSO_ANCHOR.TOP,
    )

    # Arrows sitting in the gaps, vertically centered on the cards
    arrow(slide, 4.28, 3.02, 0.40, 0.20, TEAL)
    arrow(slide, 8.64, 3.02, 0.40, 0.20, GOLD)

    # Step strip
    rect(slide, 0.36, 5.50, 12.60, 1.22, SOFT, LINE, 1.0)
    textbox(slide, 0.52, 5.56, 2.4, 0.26, "一步 Decode", 13, True, NAVY)
    steps = (
        ("1", "卡内扫索引", "下标在 GPU 上产生"),
        ("2", "一次批量 gather", "1024 个下标，一次报文"),
        ("3", "HBM 命中，DRAM 补页", "选中页约 5–10 GB / 平面"),
        ("4", "原端口送回", "每卡 1.15 GB · 0.24 毫秒"),
    )
    for i, (num, title, detail) in enumerate(steps):
        x = 0.52 + i * 3.10
        circ = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(5.92), Inches(0.32), Inches(0.32))
        solid(circ, TEAL if i < 3 else GOLD)
        textbox(slide, x, 5.92, 0.32, 0.32, num, 12, True, WHITE, PP_ALIGN.CENTER)
        textbox(slide, x + 0.40, 5.88, 2.50, 0.26, title, 13, True, NAVY)
        textbox(slide, x + 0.40, 6.14, 2.50, 0.40, detail, 12, False, MUTED, anchor=MSO_ANCHOR.TOP)

    textbox(
        slide,
        0.40,
        6.86,
        12.5,
        0.28,
        "合封保持 64 GB。容量按冷 CSA 配在本地 DRAM，带宽按选中页配在 HBM。不把 DDR 服务器挂进 256 端口的二层交换。",
        12,
        False,
        MUTED,
    )
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.36), Inches(7.22), Inches(12.60), Inches(0.015))
    solid(rule, LINE)
    textbox(
        slide,
        0.36,
        7.24,
        12.60,
        0.22,
        "N+2    ·    20T Decode    ·    30 × 1.6T = 48 Tb/s    ·    有效 4.80 TB/s    ·    组播扇出 1",
        11,
        False,
        MUTED,
    )

    slide.notes_slide.notes_text_frame.text = (
        "4M sequence: index 2.01 GB, HCA 0.59 GB, window 4.5 MB stay on GPU. "
        "Selected CSA is 17.7 MB per sequence. "
        "30 ms batch 16672 sequences: scan set 43 TB fits in 151 TB GPU KV room. "
        "Selected pages are about 10 GB per switch at 30 ms and 5 GB at 10 ms, inside 64 GB HBM. "
        "Cold CSA is 6.5 TB per switch at 30 ms and 1.1 TB at 10 ms, on a local DRAM board. "
        "Return path is 1.15 GB per GPU, 0.24 ms at 4.80 TB/s."
    )
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
