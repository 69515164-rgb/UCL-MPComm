#!/usr/bin/env python3
"""One slide: hot-expert challenges of the three Ascend MoE fusion paths."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Emu, Inches

W, H = 1920, 1080
OUT = Path("/workspace/docs")
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"

BG = (246, 244, 239)
INK = (27, 36, 48)
MUTED = (92, 102, 112)
TEAL = (15, 110, 107)
CORAL = (196, 73, 58)
NAVY = (28, 49, 68)
GOLD = (146, 104, 28)
CARD = (255, 255, 255)
LINE = (220, 214, 204)
SOFT = (237, 233, 224)
WAIT = (232, 226, 216)
PALE_TEAL = (230, 242, 241)
PALE_CORAL = (250, 236, 232)
PALE_NAVY = (232, 237, 242)
PALE_GOLD = (248, 241, 226)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def tw(d, text, fnt) -> int:
    return int(d.textlength(text, font=fnt))


def tokens(para):
    buf = ""
    for ch in para:
        latin = ch.isascii() and not ch.isspace() and ch not in ",.;:"
        if latin:
            buf += ch
        else:
            if buf:
                yield buf
                buf = ""
            yield ch
    if buf:
        yield buf


def wrap(d, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        buf = ""
        for tok in tokens(para):
            if d.textlength(buf + tok, font=fnt) <= max_w:
                buf += tok
            else:
                if buf:
                    lines.append(buf)
                buf = tok.lstrip() if lines else tok
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


def shadow(base, box, r=16):
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0 + 2, y0 + 3, x1 + 2, y1 + 5), radius=r, fill=(20, 24, 30, 28)
    )
    blur = layer.filter(ImageFilter.GaussianBlur(6))
    tmp = base.convert("RGBA")
    tmp.alpha_composite(blur)
    base.paste(tmp.convert("RGB"))


def card(img, box, fill=CARD, r=16, outline=LINE, w=1, drop=True):
    if drop:
        shadow(img, box, r)
    ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)


def text(d, xy, s, size, fill=INK, bold=False):
    # wqy-microhei has one weight; bold is expressed by the caller via color and size.
    d.text(xy, s, font=font(size), fill=fill)


def draw_hist(d, x, y, w, h):
    text(d, (x, y), "专家收到的 token", 18, INK)
    text(d, (x + 168, y + 2), "一根柱子同时决定字节和 GEMM", 14, MUTED)
    heights = [28, 36, 188, 22, 40, 18, 32, 24]
    base = y + h - 28
    gap = 14
    bw = (w - gap * (len(heights) - 1)) // len(heights)
    plot_h = h - 78
    peak = max(heights)
    for i, val in enumerate(heights):
        bh = max(8, int(plot_h * val / peak))
        bx = x + i * (bw + gap)
        hot = i == 2
        color = CORAL if hot else NAVY
        d.rounded_rectangle((bx, base - bh, bx + bw, base), radius=5, fill=color)
        if hot:
            label = "热点"
            lf = font(14)
            d.text((bx + (bw - tw(d, label, lf)) // 2, base - bh - 22), label, font=lf, fill=CORAL)
    text(d, (x, base + 8), "专家", 13, MUTED)


def hatch(img, box, color=(186, 178, 164)):
    x0, y0, x1, y1 = [int(v) for v in box]
    tile = Image.new("RGBA", (max(1, x1 - x0), max(1, y1 - y0)), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    tw_, th = tile.size
    td.rounded_rectangle((0, 0, tw_ - 1, th - 1), radius=5, fill=WAIT + (255,))
    step = 9
    acc = -tw_
    while acc < th:
        td.line([(0, acc), (tw_, acc + tw_)], fill=color + (255,), width=1)
        acc += step
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw_ - 1, th - 1), radius=5, fill=255)
    painted = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    painted.paste(tile, (0, 0))
    painted.putalpha(mask)
    base = img.convert("RGBA")
    base.alpha_composite(painted, (x0, y0))
    img.paste(base.convert("RGB"))


def draw_gantt(img, d, x, y, w, h):
    text(d, (x, y), "四张卡的同一步", 18, INK)
    text(d, (x + 150, y + 2), "冷卡提前算完，整步仍停在热卡", 14, MUTED)
    rows = [
        ("热卡", 0.46, 0.54, True),
        ("冷卡", 0.16, 0.12, False),
        ("冷卡", 0.11, 0.08, False),
        ("冷卡", 0.07, 0.05, False),
    ]
    top = y + 46
    label_w = 52
    bar_x = x + label_w
    bar_w = w - label_w - 8
    row_h = 46
    gap = 14
    finish = bar_x + bar_w
    for i, (name, comm, gemm, hot) in enumerate(rows):
        ry = top + i * (row_h + gap)
        name_color = CORAL if hot else MUTED
        text(d, (x, ry + 12), name, 16, name_color)
        c0 = bar_x
        c1 = bar_x + int(bar_w * comm)
        g1 = c1 + int(bar_w * gemm)
        d.rounded_rectangle((c0, ry, c1, ry + row_h), radius=5, fill=CORAL if hot else (214, 120, 108))
        d.rounded_rectangle((c1, ry, g1, ry + row_h), radius=5, fill=TEAL if hot else (92, 158, 156))
        if g1 < finish - 6:
            hatch(img, (g1 + 4, ry, finish, ry + row_h))
            d = ImageDraw.Draw(img)
            if finish - g1 > 70:
                text(d, (g1 + 16, ry + 12), "空等", 15, MUTED)
        if hot:
            text(d, (c0 + 12, ry + 12), "通信", 15, (255, 255, 255))
            text(d, (c1 + 12, ry + 12), "计算", 15, (255, 255, 255))
    d.line([(finish, top - 4), (finish, top + 4 * row_h + 3 * gap - 8)], fill=CORAL, width=2)
    label = "步结束"
    text(d, (finish - tw(d, label, font(14)) - 8, y + 2), label, 14, CORAL)


def legend(d, x, y):
    items = [
        (CORAL, "通信  随热点专家变长"),
        (TEAL, "计算  随热点专家变长"),
        (WAIT, "空等  冷卡已做完"),
    ]
    cx = x
    for color, label in items:
        d.rounded_rectangle((cx, y, cx + 18, y + 14), radius=3, fill=color, outline=LINE)
        text(d, (cx + 26, y - 3), label, 14, MUTED)
        cx += tw(d, label, font(14)) + 56


def section_label(d, x, y, title, color):
    d.rounded_rectangle((x, y, x + 8, y + 22), radius=2, fill=color)
    text(d, (x + 16, y - 1), title, 20, INK)


def body_lines(d, x, y, lines, size, fill, leading):
    for i, line in enumerate(lines):
        text(d, (x, y + i * leading), line, size, fill)
    return y + len(lines) * leading


def draw_path(img, box, accent, pale, kicker, title, frozen, challenge):
    card(img, box)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    d.rounded_rectangle((x0, y0, x1, y0 + 8), radius=4, fill=accent)
    d.rectangle((x0, y0 + 4, x1, y0 + 8), fill=accent)
    section_label(d, x0 + 22, y0 + 24, kicker, accent)
    sub_lines = title.split("\n")
    for i, line in enumerate(sub_lines):
        text(d, (x0 + 22, y0 + 54 + i * 20), line, 15, MUTED)

    fx, fy = x0 + 22, y0 + 112
    fw, fh = x1 - x0 - 44, 78
    d.rounded_rectangle((fx, fy, fx + fw, fy + fh), radius=10, fill=pale)
    text(d, (fx + 14, fy + 10), "进核前已经定死", 14, accent)
    lines = wrap(d, frozen, font(16), fw - 28)
    body_lines(d, fx + 14, fy + 34, lines, 16, INK, 22)

    cy = fy + fh + 16
    text(d, (x0 + 22, cy), "热点专家出现之后", 14, CORAL)
    clines = wrap(d, challenge, font(17), x1 - x0 - 44)
    body_lines(d, x0 + 22, cy + 26, clines, 17, INK, 26)


def draw():
    img = canvas()
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 8), fill=TEAL)
    text(d, (48, 28), "热点专家下，三条融合路径各自卡在哪", 34, INK)
    text(
        d,
        (48, 78),
        "热度把通信字节和 GEMM 堆到同一张卡。布局、通信算法和核分工在进核前定死，一步的时间由这张卡决定。",
        18,
        MUTED,
    )

    fig = (40, 122, 1880, 500)
    card(img, fig, r=18)
    d = ImageDraw.Draw(img)
    draw_hist(d, 68, 144, 620, 300)
    d.line([(720, 160), (720, 470)], fill=LINE, width=1)
    draw_gantt(img, d, 752, 144, 1088, 300)
    legend(d, 68, 456)

    paths = [
        (
            NAVY,
            PALE_NAVY,
            "通信融合",
            "商发  DispatchV4 + CombineV4",
            "commAlg 全卡全层只有一个值。\nhierarchy 假定专家扎在少数机器。",
            "热卡入站最长，集合通信等到它收完。\n专家打散，机内带宽用不上；堆在单机，中转更挤。",
        ),
        (
            TEAL,
            PALE_TEAL,
            "半融合",
            "商发  AlltoAllvGroupedMatMulV2\n+ GroupedMatMulAlltoAllvV2",
            "共享专家 MatMul 与路由通信重叠。\n共享计算跟全部 token 走，各卡差不多长。",
            "路由长尾只在热卡，重叠只盖住各卡相同的那段。\n热卡多出来的通信仍然露出。",
        ),
        (
            CORAL,
            PALE_CORAL,
            "整段融合",
            "MegaMoE  开源有实现，商发目录未列",
            "combineCommMode 与 tile 按总 token 数定。\n全卡、全层共用同一套。",
            "去重要同卡或同机重复命中，和均衡对着干。\n热专家上，量化和 FP32 累加留在关键路径。",
        ),
    ]
    gap = 16
    cw = (1840 - 2 * gap) // 3
    y0, y1 = 520, 900
    for i, item in enumerate(paths):
        x = 40 + i * (cw + gap)
        draw_path(img, (x, y0, x + cw, y1), *item)

    foot = (40, 918, 1880, 1048)
    card(img, foot, fill=NAVY, outline=NAVY, r=16)
    d = ImageDraw.Draw(img)
    text(d, (64, 936), "三条路径共同的天花板", 18, (255, 255, 255))
    notes = [
        ("缓冲", "按峰值预留。越过上限直接报错，\n不按这一步的直方图重切。"),
        ("门控", "只看总 BS。一专家独占和均匀平分，\n总 M 相同就走同一条代码。"),
        ("目标", "均衡在核外改专家表，亲和在核参数里。\n两边要的热度形状相反。"),
    ]
    nw = 560
    for i, (head, body) in enumerate(notes):
        nx = 64 + i * (nw + 24)
        d.rounded_rectangle((nx, 974, nx + 64, 1002), radius=8, fill=GOLD)
        hf = font(15)
        d.text((nx + (64 - tw(d, head, hf)) // 2, 978), head, font=hf, fill=(255, 255, 255))
        lines = wrap(d, body, font(15), nw - 80)
        body_lines(d, nx + 76, 974, lines, 15, (232, 236, 240), 22)
    return img


def pack(png: Path) -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_picture(str(png), Emu(0), Emu(0), prs.slide_width, prs.slide_height)
    out = OUT / "hot-expert-fuse.pptx"
    prs.save(out)
    return out


def main():
    img = draw()
    png = OUT / "hot-expert-fuse.png"
    img.save(png, "PNG")
    pptx = pack(png)
    print(png)
    print(pptx)


if __name__ == "__main__":
    main()
