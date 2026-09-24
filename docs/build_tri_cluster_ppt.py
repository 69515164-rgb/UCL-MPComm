#!/usr/bin/env python3
"""One-page 3-column slide: ByteDance / Alibaba / Tencent AI clusters, prev / now / next."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Inches, Emu

W, H = 1920, 1080
OUT = Path("/workspace/docs")
DIR = OUT / "tri-ai-cluster-gens"
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"

BG = (246, 244, 239)
INK = (27, 36, 48)
MUTED = (92, 102, 112)
PAST = (138, 146, 152)
TEAL = (15, 110, 107)
CORAL = (196, 73, 58)
NAVY = (28, 49, 68)
GOLD = (176, 128, 40)
CARD = (255, 255, 255)
LINE = (220, 214, 204)
SOFT = (237, 233, 224)
PAST_BG = (240, 239, 236)
NEXT_BG = (252, 247, 234)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def tw(d, t, f):
    return int(d.textlength(t, font=f))


def wrap(d, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        buf = ""
        for ch in para:
            if d.textlength(buf + ch, font=fnt) <= max_w:
                buf += ch
            else:
                if buf:
                    lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines


def canvas():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for i in range(0, W, 48):
        d.line([(i, 0), (i, H)], fill=(236, 232, 224), width=1)
    for j in range(0, H, 48):
        d.line([(0, j), (W, j)], fill=(236, 232, 224), width=1)
    return img


def shadow(base, box, r=14):
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0 + 3, y0 + 4, x1 + 3, y1 + 6), radius=r, fill=(20, 24, 30, 22)
    )
    blur = layer.filter(ImageFilter.GaussianBlur(6))
    tmp = base.convert("RGBA")
    tmp.alpha_composite(blur)
    base.paste(tmp.convert("RGB"))


def card(img, box, fill=CARD, r=14, outline=LINE, w=1, drop=True):
    if drop:
        shadow(img, box, r)
    ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)


def pill(d, xy, text, bg, fg=(255, 255, 255), fnt=None, pad_x=9, pad_y=3):
    fnt = fnt or font(12)
    x, y = xy
    box = (x, y, x + tw(d, text, fnt) + pad_x * 2, y + 17 + pad_y * 2)
    d.rounded_rectangle(box, radius=10, fill=bg)
    d.text((x + pad_x, y + pad_y), text, font=fnt, fill=fg)
    return box


def dashed_rect(d, box, color, dash=6, gap=4, width=2, r=6):
    x0, y0, x1, y1 = box
    x = x0
    while x < x1:
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
        x += dash + gap
    y = y0
    while y < y1:
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)
        y += dash + gap


def node(d, xy, color, w=9, h=5):
    x, y = xy
    d.rounded_rectangle((x - w, y - h, x + w, y + h), radius=2, fill=color)


def gpu(d, xy, color, w=7, h=11):
    x, y = xy
    d.rounded_rectangle((x - w, y - h, x + w, y + h), radius=2, fill=color)


def rack(d, box, color, filled=True):
    x0, y0, x1, y1 = box
    if filled:
        d.rounded_rectangle(box, radius=3, fill=color)
    else:
        d.rounded_rectangle(box, radius=3, outline=color, width=2)


def header(img):
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 7), fill=TEAL)
    d.text((26, 14), "字节 / 阿里 / 腾讯  ·  AI 集群三代际：上一代 — 当前在网 — 下一代规划", font=font(15), fill=TEAL)
    d.text((26, 36), "训练专网 → 训推一体 → 按推理阶段分核：网络的考核对象正在从「作业不掉速」换成「Token 成本」", font=font(28), fill=INK)
    d.line([(26, 78), (W - 26, 78)], fill=LINE, width=1)


def trend_band(img):
    """Cross-vendor pattern: the actual 'what changed' summary."""
    d = ImageDraw.Draw(img)
    y0, y1 = 86, 190
    card(img, (26, y0, W - 26, y1), fill=CARD, r=12, drop=False)
    d.rectangle((26, y0, 33, y1), fill=TEAL)

    d.text((46, y0 + 8), "三家共同的代际规律", font=font(15), fill=TEAL)

    heads = [("上一代  2023–24", PAST), ("当前在网  2025–26", INK), ("下一代规划  2027+", GOLD)]
    cx = [300, 830, 1360]
    for (t, c), x in zip(heads, cx):
        d.text((x, y0 + 8), t, font=font(14), fill=c)

    rows = [
        ("场景", "训练专网，KPI 是 AllReduce 不掉速", "训推一体 + PD 进入网络设计目标，潮汐复用", "按 Prefill / Decode 分核，算每 Token 成本"),
        ("组网", "三层 Clos + 多轨，机内 8 卡即 Scale-up", "百卡级超节点 + 十万卡 Scale-out 并行", "超节点上千卡，层级压平，全光 NPO / OCS"),
        ("协议", "RoCEv2 + 交换机侧被动拥塞控制", "拥塞控制上移网卡，以太 Scale-up 内存语义", "Scale-up 与 Scale-out 融合，GPU 直控通信"),
    ]
    y = y0 + 32
    for lab, a, b, c in rows:
        d.text((46, y), lab, font=font(13), fill=MUTED)
        for x, t, col in ((cx[0], a, PAST), (cx[1], b, INK), (cx[2], c, GOLD)):
            d.ellipse((x - 14, y + 4, x - 6, y + 12), fill=col)
            d.text((x, y), t, font=font(13), fill=col)
        y += 24


def footer(img):
    d = ImageDraw.Draw(img)
    d.line([(26, 1036), (W - 26, 1036)], fill=LINE, width=1)
    d.text(
        (26, 1042),
        "判断：三家把「训推一体」都做在了当前一代，差异在下一代——字节押整机柜与铜/光双路线，阿里押 Scale-up 与 Scale-out 融合成一张以太网，腾讯押光 Shuffle 压平层级 + OCS 做超节点故障隔离。",
        font=font(13),
        fill=INK,
    )
    d.text(
        (26, 1060),
        "仅公开论文 / 官网 / 大会口径。下一代列为厂商目标值，未经实测验证；阿里 50万卡·1GW·200Pbps·6μs 与真武 V900（2027Q1 量产）、字节 Rack 3.0（概念设计）、腾讯星脉 3.0（研发中）均属规划。",
        font=font(12),
        fill=MUTED,
    )


# ---------------- roadmap glyphs ----------------

def glyph_byte_prev(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for i, x in enumerate((cx - 40, cx, cx + 40)):
        node(d, (x, y0 + 14), PAST, 8, 5)
    for x in (cx - 56, cx - 18, cx + 18, cx + 56):
        node(d, (x, y0 + 44), PAST, 8, 5)
        d.line([(x, y0 + 39), (cx, y0 + 19)], fill=(190, 194, 196), width=1)
    for i, x in enumerate((cx - 60, cx - 30, cx, cx + 30, cx + 60)):
        node(d, (x, y0 + 72), PAST, 7, 4)
        d.line([(x, y0 + 68), (cx - 18 + (i % 2) * 36, y0 + 49)], fill=(198, 202, 204), width=1)
    for x in (cx - 60, cx, cx + 60):
        gpu(d, (x, y0 + 96), (170, 176, 180), 6, 9)
    d.text((cx, y1 - 4), "三层 Clos · 8×200G 多轨", font=font(11), fill=PAST, anchor="mm")


def glyph_byte_now(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for x in (cx - 30, cx + 30):
        node(d, (x, y0 + 12), NAVY, 9, 5)
    for x in (cx - 60, cx - 20, cx + 20, cx + 60):
        node(d, (x, y0 + 38), TEAL, 8, 5)
        d.line([(x, y0 + 33), (cx - 30 if x < cx else cx + 30, y0 + 17)], fill=(170, 200, 198), width=1)
    # supernode: two racks
    for i in range(2):
        rack(d, (cx - 42 + i * 44, y0 + 58, cx - 2 + i * 44, y0 + 102), TEAL)
    d.line([(cx - 2, y0 + 80), (cx + 2, y0 + 80)], fill=CARD, width=3)
    d.text((cx, y0 + 80), "256 XPU", font=font(11), fill=(255, 255, 255), anchor="mm")
    for x in (cx - 22, cx + 22):
        d.line([(x, y0 + 58), (x, y0 + 44)], fill=TEAL, width=2)
    d.text((cx, y1 - 4), "超节点 + 三层 Clos · POD 65k", font=font(11), fill=INK, anchor="mm")


def glyph_byte_next(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for i in range(2):
        dashed_rect(d, (cx - 52 + i * 62, y0 + 8, cx - 12 + i * 62, y0 + 40), GOLD)
        d.text((cx - 32 + i * 62, y0 + 24), "交换柜", font=font(10), fill=GOLD, anchor="mm")
    for i in range(4):
        x = cx - 76 + i * 40
        dashed_rect(d, (x, y0 + 56, x + 30, y0 + 104), GOLD)
        d.line([(x + 15, y0 + 56), (cx - 32 + (i % 2) * 62, y0 + 42)], fill=(214, 178, 96), width=1)
    d.text((cx, y0 + 80), "8 计算柜", font=font(11), fill=GOLD, anchor="mm")
    d.text((cx, y1 - 4), "NPO 光互连 · 1024 XPU 超节点", font=font(11), fill=GOLD, anchor="mm")


def glyph_ali_prev(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for x in (cx - 50, cx - 16, cx + 16, cx + 50):
        node(d, (x, y0 + 16), PAST, 8, 5)
    d.text((x1 - 4, y0 + 14), "双平面", font=font(10), fill=PAST, anchor="rm")
    for i, x in enumerate((cx - 62, cx - 22, cx + 22, cx + 62)):
        node(d, (x, y0 + 52), PAST, 9, 5)
        d.line([(x, y0 + 47), (x - 12, y0 + 21)], fill=(190, 194, 196), width=1)
        d.line([(x, y0 + 47), (x + 12, y0 + 21)], fill=(205, 208, 210), width=1)
    d.text((x1 - 4, y0 + 52), "双上联", font=font(10), fill=PAST, anchor="rm")
    for x in (cx - 62, cx - 22, cx + 22, cx + 62):
        gpu(d, (x, y0 + 82), (170, 176, 180), 7, 11)
        d.line([(x, y0 + 71), (x, y0 + 58)], fill=(190, 194, 196), width=2)
    d.text((cx, y1 - 4), "单层千卡 / 两层万卡 · 存算分离", font=font(11), fill=PAST, anchor="mm")


def glyph_ali_now(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    d.text((x0 + 2, y0 + 2), "多平面", font=font(10), fill=CORAL)
    for p in range(2):
        yy = y0 + 14 + p * 18
        for x in (cx - 40, cx, cx + 40):
            node(d, (x, yy), CORAL if p == 0 else (222, 140, 128), 8, 4)
        d.line([(cx - 48, yy), (cx + 48, yy)], fill=(236, 200, 194), width=1)
    for x in (cx - 62, cx - 20, cx + 22, cx + 64):
        node(d, (x, y0 + 52), NAVY, 8, 5)
        d.line([(x, y0 + 47), (cx, y0 + 30)], fill=(200, 190, 196), width=1)
    # supernode box
    d.rounded_rectangle((cx - 66, y0 + 70, cx + 66, y0 + 102), radius=5, fill=CORAL)
    d.text((cx, y0 + 86), "超节点 64 卡实例", font=font(11), fill=(255, 255, 255), anchor="mm")
    d.text((cx, y1 - 4), "多平面 CLOS · 单集群 13万卡混布", font=font(11), fill=INK, anchor="mm")


def glyph_ali_next(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    dashed_rect(d, (cx - 74, y0 + 6, cx + 74, y0 + 38), GOLD)
    d.text((cx, y0 + 22), "单层全光 CLOS  512 xPU", font=font(10), fill=GOLD, anchor="mm")
    for i in range(6):
        x = cx - 62 + i * 25
        gpu(d, (x, y0 + 60), (230, 196, 130), 7, 11)
        d.line([(x, y0 + 49), (x, y0 + 40)], fill=GOLD, width=2)
    dashed_rect(d, (cx - 74, y0 + 78, cx + 74, y0 + 106), GOLD)
    d.text((cx, y0 + 92), "Scale-up / out 融合一张网", font=font(10), fill=GOLD, anchor="mm")
    d.text((cx, y1 - 4), "千卡超节点 · 50万卡广域集群", font=font(11), fill=GOLD, anchor="mm")


def glyph_tx_prev(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for x in (cx - 34, cx + 34):
        node(d, (x, y0 + 14), PAST, 9, 5)
    rails = (cx - 66, cx - 22, cx + 22, cx + 66)
    for x in rails:
        node(d, (x, y0 + 48), PAST, 8, 5)
        d.line([(x, y0 + 43), (cx - 34 if x < cx else cx + 34, y0 + 19)], fill=(192, 196, 198), width=1)
    for i, x in enumerate(rails):
        gpu(d, (x, y0 + 80), (170, 176, 180), 7, 11)
        d.line([(x, y0 + 69), (x, y0 + 54)], fill=(190, 194, 196), width=2)
        d.text((x, y0 + 98), f"轨{i+1}", font=font(9), fill=PAST, anchor="mm")
    d.text((cx, y1 - 4), "Fat-Tree 多轨道 · 首创多轨组网", font=font(11), fill=PAST, anchor="mm")


def glyph_tx_now(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for x in (cx - 34, cx + 34):
        node(d, (x, y0 + 12), NAVY, 9, 5)
    # same-rail aggregation: agg groups by rail
    for g in range(2):
        gx = cx - 40 + g * 80
        d.rounded_rectangle((gx - 32, y0 + 30, gx + 32, y0 + 52), radius=4, fill=(226, 232, 238))
        for k in range(2):
            node(d, (gx - 14 + k * 28, y0 + 41), NAVY, 8, 5)
        d.text((gx, y0 + 62), f"同轨 Agg{g+1}", font=font(9), fill=NAVY, anchor="mm")
        d.line([(gx, y0 + 30), (cx - 34 if g == 0 else cx + 34, y0 + 17)], fill=(180, 190, 202), width=2)
    for x in (cx - 62, cx - 20, cx + 20, cx + 62):
        gpu(d, (x, y0 + 92), NAVY, 7, 11)
        d.line([(x, y0 + 81), (x, y0 + 74)], fill=(160, 172, 188), width=2)
    d.text((cx, y1 - 4), "同轨聚合三层等带宽 · Pod 64K", font=font(11), fill=INK, anchor="mm")


def glyph_tx_next(d, box):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    for x in (cx - 44, cx, cx + 44):
        node(d, (x, y0 + 14), GOLD, 9, 5)
    d.text((x1 - 4, y0 + 12), "二层", font=font(10), fill=GOLD, anchor="rm")
    leafs = (cx - 66, cx - 22, cx + 22, cx + 66)
    for i, x in enumerate(leafs):
        node(d, (x, y0 + 50), GOLD, 8, 5)
        d.line([(x, y0 + 45), ((cx - 44, cx, cx + 44)[i % 3], y0 + 19)], fill=(220, 186, 110), width=2)
    d.rounded_rectangle((cx - 78, y0 + 62, cx + 78, y0 + 84), radius=4, fill=(250, 240, 214))
    d.text((cx, y0 + 73), "光 Shuffle", font=font(10), fill=GOLD, anchor="mm")
    for i, x in enumerate(leafs):
        d.line([(x, y0 + 55), (leafs[(i + 2) % 4], y0 + 62)], fill=GOLD, width=1)
        gpu(d, (x, y0 + 96), (230, 196, 130), 7, 10)
        d.line([(x, y0 + 86), (x, y0 + 84)], fill=GOLD, width=2)
    d.text((cx, y1 - 4), "扁平二级单轨 · 数十万卡", font=font(11), fill=GOLD, anchor="mm")


# ---------------- column assembly ----------------

def roadmap(img, box, items):
    """items: list of (stage_label, name, meta, color, bg, glyph_fn)."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    n = len(items)
    gap = 8
    cw = (x1 - x0 - gap * (n - 1)) / n
    for i, (stage, name, meta, color, bg, glyph) in enumerate(items):
        gx0 = x0 + i * (cw + gap)
        gbox = (gx0, y0, gx0 + cw, y1)
        d.rounded_rectangle(gbox, radius=8, fill=bg)
        d.text((gx0 + cw / 2, y0 + 12), stage, font=font(11), fill=color, anchor="mm")
        d.text((gx0 + cw / 2, y0 + 30), name, font=font(14), fill=color, anchor="mm")
        d.text((gx0 + cw / 2, y0 + 48), meta, font=font(10), fill=MUTED, anchor="mm")
        glyph(d, (gx0 + 6, y0 + 58, gx0 + cw - 6, y1 - 4))
        if i < n - 1:
            ax = gx0 + cw + gap / 2
            d.polygon(
                [(ax - 3, y0 + 26), (ax + 4, y0 + 31), (ax - 3, y0 + 36)],
                fill=(190, 186, 176),
            )


def verdict_strip(img, box, color, notes):
    """One judgement per generation, aligned to the table columns below."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    lab_w = 54
    cw = (x1 - x0 - lab_w) / 3
    d.text((x0 + lab_w / 2, (y0 + y1) / 2), "这代\n解决", font=font(11), fill=MUTED, anchor="mm")
    for j, text in enumerate(notes):
        col = (PAST, color, GOLD)[j]
        bg = (PAST_BG, (250, 249, 246), NEXT_BG)[j]
        cx0 = x0 + lab_w + cw * j
        d.rounded_rectangle((cx0 + 4, y0, cx0 + cw - 4, y1), radius=6, fill=bg)
        lines = wrap(d, text, font(12), cw - 24)
        ty = (y0 + y1) / 2 - len(lines) * 8
        for line in lines:
            d.text((cx0 + cw / 2, ty), line, font=font(12), fill=col, anchor="ma")
            ty += 16


def table(img, box, rows):
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    lab_w = 54
    cw = (x1 - x0 - lab_w) / 3
    d.rectangle((x0, y0, x1, y0 + 20), fill=SOFT)
    for i, (t, c) in enumerate((("上一代", PAST), ("当前在网", INK), ("下一代规划", GOLD))):
        d.text((x0 + lab_w + cw * i + cw / 2, y0 + 10), t, font=font(11), fill=c, anchor="mm")
    rh = (y1 - y0 - 20) / len(rows)
    y = y0 + 20
    for i, (lab, cells) in enumerate(rows):
        base = CARD if i % 2 == 0 else (250, 249, 246)
        d.rectangle((x0, y, x1, y + rh), fill=base)
        d.rectangle((x0, y, x0 + lab_w, y + rh), fill=SOFT)
        d.line([(x0, y), (x1, y)], fill=LINE, width=1)
        for ln, lt in enumerate(lab.split("\n")):
            d.text((x0 + lab_w / 2, y + rh / 2 - 8 + ln * 16), lt, font=font(12), fill=MUTED, anchor="mm")
        for j, text in enumerate(cells):
            col = (PAST, INK, GOLD)[j]
            cx0 = x0 + lab_w + cw * j
            if j == 2:
                d.rectangle((cx0, y, cx0 + cw, y + rh), fill=NEXT_BG)
            elif j == 0:
                d.rectangle((cx0, y, cx0 + cw, y + rh), fill=PAST_BG)
            fnt = font(12)
            lines = []
            for para in text.split("\n"):
                lines.extend(wrap(d, para, fnt, cw - 14))
            ty = y + (rh - len(lines) * 17) / 2
            for line in lines:
                d.text((cx0 + cw / 2, ty), line, font=fnt, fill=col, anchor="ma")
                ty += 17
        y += rh
    d.rectangle((x0, y0, x1, y1), outline=LINE, width=1)
    for i in range(1, 3):
        xx = x0 + lab_w + cw * i
        d.line([(xx, y0), (xx, y1)], fill=LINE, width=1)
    d.line([(x0 + lab_w, y0), (x0 + lab_w, y1)], fill=LINE, width=1)


def column(img, box, color, name, verdict, items, notes, rows):
    x0, y0, x1, y1 = box
    card(img, box, r=14, outline=color, w=2)
    d = ImageDraw.Draw(img)
    d.rectangle((x0, y0, x1, y0 + 7), fill=color)
    d.text((x0 + 16, y0 + 18), name, font=font(21), fill=INK)
    d.text((x0 + 128, y0 + 25), verdict, font=font(13), fill=color)
    roadmap(img, (x0 + 12, y0 + 54, x1 - 12, y0 + 232), items)
    verdict_strip(img, (x0 + 12, y0 + 242, x1 - 12, y0 + 300), color, notes)
    table(img, (x0 + 12, y0 + 308, x1 - 12, y1 - 12), rows)


def slide():
    img = canvas()
    header(img)
    trend_band(img)

    byte_items = [
        ("上一代", "MegaScale 集群", "NSDI'24 披露", PAST, PAST_BG, glyph_byte_prev),
        ("当前在网", "Rack 2.0 + HPN 6.0", "量产 / 已上线", TEAL, (240, 246, 245), glyph_byte_now),
        ("下一代规划", "AI Rack 3.0", "OCP 概念设计", GOLD, NEXT_BG, glyph_byte_next),
    ]
    byte_rows = [
        ("场景", (
            "大模型预训练为主\n12288 卡训 175B\nMFU 55.2%",
            "训推一体融合网\nPD 由 xLLM 承接\n强化学习沙箱",
            "兆瓦级超节点承载\n更大 TP / EP\n多代异构长期共存",
        )),
        ("组网", (
            "三层 Clos 1:1\n8×200G 多轨\nScale-up 仅机内 8 卡",
            "双柜 256 XPU 超节点\n三层 Clos POD 65k\n可线性扩至百万",
            "双柜 576 XPU\n224G SerDes / 460TB/s\nNPO 8+2 柜 = 1024",
        )),
        ("协议", (
            "早期 IB Fat-Tree\n后转 RoCEv2\nveCCL + BCC",
            "EthLink 以太 Scale-up\nLoad/Store + RDMA\n200/400/800G 混速",
            "800G → 1.6T\n单层大 Radix 光互连\n以太 Scale-up 标准化",
        )),
        ("关键\n技术", (
            "Tomahawk4 25.6T\n多轨亲和调度",
            "SGLB 带宽利用 +40%\n算子级 + 任务级 QoS\nSyncMesh 微秒收敛",
            "500kW / 800V HVDC\n整机柜全液冷\n铜光双路线并行",
        )),
    ]

    ali_items = [
        ("上一代", "HPN 7.0", "2023.9 规模上线", PAST, PAST_BG, glyph_ali_prev),
        ("当前在网", "EPOD → HPN 8.0", "训推一体 / PD", CORAL, (252, 243, 241), glyph_ali_now),
        ("下一代规划", "V900 + UPN + TPN", "2027Q1 量产", GOLD, NEXT_BG, glyph_ali_next),
    ]
    ali_rows = [
        ("场景", (
            "训练专网\n存算分离\n端到端 +14.9%",
            "训推一体 EPOD 已部署\n推理通信 +100%\n潮汐复用 + PD 分离",
            "十万亿参数 MoE\nAgent 高并发\nTPN 盯每 Token 成本",
        )),
        ("组网", (
            "双上联 + 多轨 + 双平面\n单层千卡 / 两层万卡\n51.2T + 400G",
            "多平面 CLOS + IPv6\n单集群最高 13万卡混布\n跨 AZ / Region RDMA",
            "UPN512 单层全光\nV900 + ICN 千卡超节点\nScale-up/out 融合",
        )),
        ("协议", (
            "RoCEv2 + 自研 HPCC\nACCL 通信库",
            "Solar-RDMA（UEC 多路径）\n拥塞下 +18%\nACCL + C4D 端到端 QoS",
            "原生内存语义 + 统一编址\nNPO 光模块\nTPN Token 面",
        )),
        ("关键\n技术", (
            "消除哈希极化\n队列 −91.8%",
            "分钟级自愈 / 可用 99.7%\nCPFS 百 PiB · 百 TB/s",
            "光互连成本 −30% 可靠 +3×\nTPN +2.5× / +10× / −1/3\n50万卡 1GW 200Pbps 6μs",
        )),
    ]

    tx_items = [
        ("上一代", "星脉 1.0", "多轨道首创", PAST, PAST_BG, glyph_tx_prev),
        ("当前在网", "星脉 2.0 / Astral", "生产 18 个月+", NAVY, (238, 241, 245), glyph_tx_now),
        ("下一代规划", "星脉 3.0", "研发设计中", GOLD, NEXT_BG, glyph_tx_next),
    ]
    tx_rows = [
        ("场景", (
            "混元训练\nGPU 利用 +40%\n时延 −40%",
            "工程支持 10 万卡\n训练推理一体化\n后训练带推理特征",
            "MoE 训推一体\nPrefill / Decode 分核\n降 TP/EP/CP 占比",
        )),
        ("组网", (
            "Fat-Tree 多轨道\n单机 1.6T → 3.2T 接入\n典型 2K / 最大 32K",
            "同轨聚合三层等带宽\nBlock 1K / Pod 64K\n集群约 512K",
            "二层撑数十万卡\n光 Shuffle 扁平单轨\n超节点 + OCS 隔离",
        )),
        ("协议", (
            "RoCEv2 + PFC/DCQCN\nTiTa 1.0 交换机被动 CC\nTCCL 路径预规划",
            "TiTa 2.0 网卡主动 CC\nTCCL 2.0 NVLink+NET\nGOR 全局路由",
            "TRMT GPU 直控 RDMA\n3.2T NPO 联合阿里云\n在 ODCC 立项",
        )),
        ("关键\n技术", (
            "多轨流量亲和\n通信效率 80%+",
            "通信 +60% / 训练 +20%\n灵境仿真：慢节点\n定位天级 → 分钟级",
            "DeepEP RoCE +100% / IB +30%\nLPO 时延 −99% 成本 −25%\nNPO 密度 +10×",
        )),
    ]

    byte_notes = (
        "把万卡训练跑稳：多轨 + 无收敛，先保 MFU",
        "把训练和推理装进同一张网，并把 Scale-up 以太化",
        "算力密度撞上供电散热，用整机柜和光互连换规模",
    )
    ali_notes = (
        "先把哈希极化和单 ToR 故障消掉，规模换效率",
        "同一张网做潮汐复用：训练让位推理，PD 拆开跑",
        "不再区分两张网，Scale-up 和 Scale-out 合并",
    )
    tx_notes = (
        "首创多轨道，把大流量按网卡序号分面并行",
        "端网协同：拥塞在发生前治，慢节点分钟级揪出",
        "层级压平，把 MoE 的 All-to-All 当一等公民设计",
    )

    gap = 14
    x = 26
    cw = (W - 52 - gap * 2) / 3
    for color, name, verdict, items, notes, rows in (
        (TEAL, "字节跳动", "整机柜 + 铜光双路线", byte_items, byte_notes, byte_rows),
        (CORAL, "阿里云", "训推一体最早落地", ali_items, ali_notes, ali_rows),
        (NAVY, "腾讯云", "端网协同 + 压平层级", tx_items, tx_notes, tx_rows),
    ):
        column(img, (x, 198, x + cw, 1030), color, name, verdict, items, notes, rows)
        x += cw + gap

    footer(img)
    return img


def pack(path):
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_picture(str(path), Emu(0), Emu(0), prs.slide_width, prs.slide_height)
    out = OUT / "tri-ai-cluster-gens.pptx"
    prs.save(out)
    return out


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    img = slide()
    png = DIR / "01-tri-cluster.png"
    img.save(png, "PNG", optimize=True)
    print("wrote", png)
    print("pptx", pack(png))


if __name__ == "__main__":
    main()
