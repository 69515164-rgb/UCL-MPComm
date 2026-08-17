#!/usr/bin/env python3
"""Memory-tier pyramid G0–G4 with public bandwidth/capacity labels."""

from PIL import Image, ImageDraw, ImageFont

W, H = 2000, 1980
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"

NAVY = (15, 39, 68)
INK = (30, 41, 59)
MUTED = (71, 85, 105)
WHITE = (255, 255, 255)
BG = (241, 244, 248)
CARD = (255, 255, 255)
LINE = (203, 213, 225)
GOLD = (161, 98, 7)
GOLD_BG = (254, 243, 199)


def font(sz):
    return ImageFont.truetype(FONT, sz)


def tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f)
    return b[2] - b[0], b[3] - b[1]


def rr(d, xy, r, fill, outline=None, w=2):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=w)


def pill(d, x, y, text, f, fg, bg, pad_x=10, pad_y=5):
    w, h = tw(d, text, f)
    rr(d, (x, y, x + w + 2 * pad_x, y + h + 2 * pad_y), 8, bg)
    d.text((x + pad_x, y + pad_y - 1), text, font=f, fill=fg)
    return w + 2 * pad_x, h + 2 * pad_y


# cap / bw / lat kept short so they stay readable inside the trapezoid
LAYERS = [
    {
        "id": "G0",
        "name": "L1–L2",
        "ext": False,
        "fill": (234, 88, 12),
        "cap": "256 KB/SM · 50 MB",
        "bw": "~20 TB/s",
        "lat": "15–130 ns",
    },
    {
        "id": "G1",
        "name": "LOCAL HBM",
        "ext": False,
        "fill": (194, 65, 12),
        "cap": "80–192 GB · 13.4 TB",
        "bw": "3.4–8.0 TB/s",
        "lat": "100–300 ns",
    },
    {
        "id": "G1.5",
        "name": "DDR 池 · 直挂 Scale-Up",
        "ext": True,
        "fill": (180, 83, 9),
        "cap": "240–480 GB · 17 TB",
        "bw": "C2C 900 GB/s",
        "lat": "百 ns",
    },
    {
        "id": "G2",
        "name": "HOST MEMORY",
        "ext": False,
        "fill": (13, 148, 136),
        "cap": "2–4 TB/节点",
        "bw": "H2D ~64 GB/s",
        "lat": "80–140 ns",
    },
    {
        "id": "G2.5",
        "name": "超节点 DDR 池",
        "ext": True,
        "fill": (109, 40, 217),
        "cap": "N×DRAM · 数十 TB",
        "bw": "UB ~392 GB/s/NPU",
        "lat": "1–2 µs",
    },
    {
        "id": "G3",
        "name": "LOCAL SSD",
        "ext": False,
        "fill": (37, 99, 235),
        "cap": "~30 TB/节点",
        "bw": "~14 GB/s/盘",
        "lat": "10–100 µs",
    },
    {
        "id": "G3.5",
        "name": "ICMS / CMX",
        "ext": False,
        "fill": (30, 58, 138),
        "cap": "Pod 级 PB",
        "bw": "~100–300 GB/s",
        "lat": "数十 µs",
    },
    {
        "id": "G4",
        "name": "云存储",
        "ext": False,
        "fill": (51, 65, 85),
        "cap": "PB–EB",
        "bw": "1–数十 GB/s",
        "lat": "ms 级",
    },
]


def half_width(y, y0, y1, top_hw, bot_hw):
    t = (y - y0) / (y1 - y0)
    return top_hw + t * (bot_hw - top_hw)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    cx = W // 2

    rr(d, (0, 0, W, 118), 0, NAVY)
    d.text((44, 22), "内存分层架构金字塔", font=font(36), fill=WHITE)
    d.text(
        (44, 72),
        "G0 → G4   ·   容量 / 带宽 / 延迟为公开典型值，非单一 SKU",
        font=font(18),
        fill=(186, 230, 253),
    )

    y_leg = 136
    rr(d, (36, y_leg, W - 36, y_leg + 58), 12, CARD, LINE, 2)
    x = 52
    y = y_leg + 14
    items = [
        ("NVIDIA", "G1 HBM · G2 DRAM · G3 SSD · G3.5 ICMS · G4 云存储", (29, 78, 216), (219, 234, 254)),
        ("扩展", "G0 片上缓存 · G1.5 直挂 Scale-Up DDR · G2.5 超节点 DDR 池", GOLD, GOLD_BG),
    ]
    for title, body, fg, bgc in items:
        pw, _ = pill(d, x, y, title, font(15), fg, bgc, 10, 5)
        d.text((x + pw + 10, y + 5), body, font=font(16), fill=INK)
        x += pw + 10 + tw(d, body, font(16))[0] + 28

    d.text((44, 208), "快 / 小 / 近", font=font(16), fill=(234, 88, 12))
    d.text((W - 44 - tw(d, "慢 / 大 / 远", font(16))[0], 208), "慢 / 大 / 远", font=font(16), fill=MUTED)

    y0 = 240
    hgt = 156
    gap = 7
    n = len(LAYERS)
    total_h = hgt * n + gap * (n - 1)
    y1 = y0 + total_h
    top_hw, bot_hw = 420, 960

    ys = [(y0 + i * (hgt + gap), y0 + i * (hgt + gap) + hgt) for i in range(n)]

    for i, layer in enumerate(LAYERS):
        top, bot = ys[i]
        hw_t = half_width(top, y0, y1, top_hw, bot_hw)
        hw_b = half_width(bot, y0, y1, top_hw, bot_hw)
        poly = [
            (cx - hw_t + 6, top + 6),
            (cx + hw_t + 6, top + 6),
            (cx + hw_b + 6, bot + 6),
            (cx - hw_b + 6, bot + 6),
        ]
        d.polygon(poly, fill=(203, 213, 225))

    f_title = font(28)
    f_lab = font(16)
    f_val = font(22)
    for i, layer in enumerate(LAYERS):
        top, bot = ys[i]
        hw_t = half_width(top, y0, y1, top_hw, bot_hw)
        hw_b = half_width(bot, y0, y1, top_hw, bot_hw)
        poly = [
            (cx - hw_t, top),
            (cx + hw_t, top),
            (cx + hw_b, bot),
            (cx - hw_b, bot),
        ]
        d.polygon(poly, fill=layer["fill"])
        outline = (253, 224, 71) if layer["ext"] else WHITE
        d.polygon(poly, outline=outline, width=3 if layer["ext"] else 2)

        x0 = cx - hw_t + 26
        yy = top + 14
        badge_fg = GOLD if layer["ext"] else layer["fill"]
        badge_bg = GOLD_BG if layer["ext"] else WHITE
        bw, _ = pill(d, x0, yy, layer["id"], font(18), badge_fg, badge_bg, 12, 4)
        d.text((x0 + bw + 12, yy + 3), layer["name"], font=f_title, fill=WHITE)
        if layer["ext"]:
            nw, _ = tw(d, layer["name"], f_title)
            pill(d, x0 + bw + 12 + nw + 12, yy + 6, "扩展", font(14), GOLD, GOLD_BG, 8, 3)

        # three metric columns
        inner_w = 2 * hw_t - 52
        col_w = inner_w / 3
        my = yy + 52
        cols = [("容量", layer["cap"]), ("带宽", layer["bw"]), ("延迟", layer["lat"])]
        for ci, (lab, val) in enumerate(cols):
            cx0 = x0 + ci * col_w
            d.text((cx0, my), lab, font=f_lab, fill=(254, 243, 199))
            d.text((cx0, my + 24), val, font=f_val, fill=WHITE)

    fy = y1 + 22
    rr(d, (36, fy, W - 36, H - 24), 12, CARD, LINE, 2)
    d.text((52, fy + 14), "口径说明", font=font(17), fill=NAVY)
    notes = [
        "公开典型区间：H100/H200/B200、DGX B200、GB200 NVL72、CXL 3.0、CloudMatrix384、CMX/ICMS、WEKA GDS。",
        "G1.5 = 直挂 Scale-Up 的 DDR（C2C 900 GB/s / CXL / UB load-store），不经 PCIe。G2 对 GPU 有效带宽是 H2D ~64 GB/s。",
        "G2.5 = 超节点内远程 DDR 池，带宽吃互联余量（CM384 UB ~392 GB/s/NPU）。NVL72 的 17 TB LPDDR 计在 G1.5。",
        "G3.5 ICMS 后更名 CMX：Pod 级 PB，µs 级；G4 为对象存储/共享 FS，ms 级。G1.5/G2.5 非 NVIDIA 官方编号。",
    ]
    ny = fy + 46
    for line in notes:
        d.text((52, ny), "·  " + line, font=font(15), fill=MUTED)
        ny += 24

    out = "/workspace/docs/memory-hierarchy-pyramid.png"
    img.save(out, "PNG", optimize=True)
    print("wrote", out, img.size)


if __name__ == "__main__":
    main()
