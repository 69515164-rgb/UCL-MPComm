#!/usr/bin/env python3
"""Memory-tier pyramid G0–G4 with public bandwidth/capacity labels."""

from PIL import Image, ImageDraw, ImageFont

W, H = 2200, 2480
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


LAYERS = [
    {
        "id": "G0",
        "name": "L1–L2  片上缓存",
        "media": "SRAM · SMEM/L1 + L2",
        "ext": False,
        "fill": (234, 88, 12),
        "fill2": (194, 65, 12),
        "cap": "L1 256 KB/SM（H100，SMEM 最大 228 KB）  ·  L2 50 MB",
        "bw": "SMEM ~20 TB/s 量级  ·  L2 实测 ~3.5–5.5 TB/s",
        "lat": "L1 ~15–20 ns  ·  L2 ~100–130 ns",
        "role": "算子热数据 / FlashAttention SRAM",
        "src": "Hopper 白皮书 · Chips and Cheese / CUDA microbench",
    },
    {
        "id": "G1",
        "name": "LOCAL HBM",
        "media": "HBM3 / HBM3e  本地高带宽显存",
        "ext": False,
        "fill": (194, 65, 12),
        "fill2": (154, 52, 18),
        "cap": "80 / 141 / 192 GB（H100 / H200 / B200）  ·  NVL72 合计 ~13.4 TB",
        "bw": "3.35 / 4.8 / 8.0 TB/s（H100 / H200 / B200）",
        "lat": "~100–300 ns",
        "role": "权重 + 热 KV + 激活  ·  训练/推理工作集",
        "src": "NVIDIA H100 / H200 / B200 / GB200 NVL72 公开规格",
    },
    {
        "id": "G1.5",
        "name": "DDR 成池 · 直挂 Scale-Up 总线",
        "media": "Grace LPDDR5X + NVLink-C2C  ·  CXL.mem  ·  UB load/store",
        "ext": True,
        "fill": (180, 83, 9),
        "fill2": (146, 64, 14),
        "cap": "Grace 240–480 GB/CPU  ·  NVL72 17 TB LPDDR  ·  CXL 扩展 TB 级/节点",
        "bw": "C2C 900 GB/s 双向（~7× PCIe Gen5 x16）  ·  Grace DRAM 512 GB/s  ·  CXL 3.0 x16 原始 256 GB/s 双向",
        "lat": "相干路径百 ns  ·  CXL.mem ~150–300+ ns",
        "role": "加速器可 load/store 的近端 DDR 池，不经主机 PCIe",
        "src": "GB200 NVL72 · CXL 3.0 白皮书 · CloudMatrix384 UB 全局地址空间",
    },
    {
        "id": "G2",
        "name": "HOST MEMORY",
        "media": "DDR5 DIMM  节点本地主机内存",
        "ext": False,
        "fill": (13, 148, 136),
        "fill2": (15, 118, 110),
        "cap": "DGX B200 标准 2 TB（可升 4 TB）  ·  双路服务器典型 1–4 TB",
        "bw": "插槽 DDR5 ~400–800+ GB/s  ·  GPU 路径 PCIe Gen5 x16 ~64 GB/s 单向 / 128 GB/s 双向",
        "lat": "DRAM ~80–140 ns  ·  H2D 拷贝 µs 级（常见瓶颈）",
        "role": "节点本地主机内存；对 GPU 的有效带宽受 PCIe/H2D 约束",
        "src": "DGX B200 User Guide · H200 PCIe 128 GB/s",
    },
    {
        "id": "G2.5",
        "name": "超节点内 DDR 池",
        "media": "SuperPod / NVL 域内远程主机 DDR（UB / NVLink 余量）",
        "ext": True,
        "fill": (109, 40, 217),
        "fill2": (91, 33, 182),
        "cap": "N × 主机 DRAM  ·  TaiShan SuperPoD 公开 48 TB  ·  CM384 超节点全局可寻址（CPU DRAM+NPU HBM）",
        "bw": "受 scale-up 余量约束，非 DDR 通道峰值  ·  CM384 UB ~392 GB/s 单向/NPU（与 NPU–NPU 共享）",
        "lat": "互连跳 ~1–2 µs  ·  华为 UB 2.0 公开 2.1 µs",
        "role": "把各节点 G2 收成超节点池；GB200 的 17 TB LPDDR 是 G1.5 在机柜内聚合，不是另一块独立 DDR",
        "src": "CloudMatrix384 arXiv:2506.12708 · Huawei UB 2.0 · GB200 NVL72",
    },
    {
        "id": "G3",
        "name": "LOCAL SSD",
        "media": "NVMe  节点本地闪存",
        "ext": False,
        "fill": (37, 99, 235),
        "fill2": (29, 78, 216),
        "cap": "DGX B200 数据盘 8×3.84 TB ≈ 30.7 TB  ·  单盘 3.84–30.72 TB 级",
        "bw": "PCIe 5 单盘 ~14–14.5 GB/s  ·  多盘 RAID0 可至数十 GB/s",
        "lat": "~10–100 µs",
        "role": "温 KV / 检查点；节点内，默认不可跨节点共享",
        "src": "DGX B200 · Solidigm D7-PS1010 14.5 GB/s",
    },
    {
        "id": "G3.5",
        "name": "ICMS / CMX",
        "media": "Ethernet-attached flash  ·  BlueField-4 + Spectrum-X（ICMS 后更名 CMX）",
        "ext": False,
        "fill": (30, 58, 138),
        "fill2": (30, 41, 89),
        "cap": "GPU Pod 级 PB 量级  ·  公开口径每 BF4 可支撑约 150 TB context",
        "bw": "BF4 800 Gb/s ≈ 100 GB/s/链路  ·  WEKA GDS 单主机读 ~308 GB/s / 写 ~163 GB/s  ·  相对传统存储最高 5× TPS",
        "lat": "数十–百 µs 量级（预热到 G2/G1，而非 G4 的毫秒）",
        "role": "Pod 级共享 KV / agentic 长期上下文  ·  NVIDIA 官方 G3.5 层",
        "src": "NVIDIA CMX/ICMS blog · WEKA Augmented Memory Grid",
    },
    {
        "id": "G4",
        "name": "云存储",
        "media": "对象存储 / 共享并行文件系统（S3、Scale 等）",
        "ext": False,
        "fill": (51, 65, 85),
        "fill2": (30, 41, 59),
        "cap": "实际无上限（PB–EB）",
        "bw": "客户端通常 1–数十 GB/s  ·  集群聚合数十–数百 GB/s",
        "lat": "毫秒–百毫秒  ·  S3 Express One Zone 约数 ms–十几 ms p99",
        "role": "冷 KV / 数据集 / 检查点归档",
        "src": "AWS S3 / 并行文件系统公开口径",
    },
]


def half_width(y, y0, y1, top_hw, bot_hw):
    t = (y - y0) / (y1 - y0)
    return top_hw + t * (bot_hw - top_hw)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    cx = W // 2

    # header
    rr(d, (0, 0, W, 148), 0, NAVY)
    d.text((48, 28), "内存分层架构金字塔", font=font(40), fill=WHITE)
    d.text(
        (48, 82),
        "G0 → G4（含 G1.5 / G2.5 扩展层）  ·  带宽 / 容量 / 延迟取自业界公开规格（典型区间，非单一 SKU）",
        font=font(18),
        fill=(186, 230, 253),
    )

    # legend chips
    y_leg = 168
    rr(d, (40, y_leg, W - 40, y_leg + 86), 14, CARD, LINE, 2)
    d.text((60, y_leg + 12), "分层口径", font=font(16), fill=MUTED)
    x = 60
    y = y_leg + 40
    items = [
        ("NVIDIA 官方", "G1 HBM · G2 DRAM · G3 Local SSD · G3.5 ICMS/CMX · G4 Shared Storage", (29, 78, 216), (219, 234, 254)),
        ("本图扩展", "G0 片上缓存  ·  G1.5 直挂 Scale-Up 的 DDR 池  ·  G2.5 超节点内 DDR 池", GOLD, GOLD_BG),
    ]
    for title, body, fg, bgc in items:
        pw, ph = pill(d, x, y, title, font(14), fg, bgc)
        d.text((x + pw + 10, y + 4), body, font=font(15), fill=INK)
        x += pw + 10 + tw(d, body, font(15))[0] + 36

    # axis hint
    d.text((48, 268), "快 / 小 / 近", font=font(14), fill=(234, 88, 12))
    d.text((W - 48 - tw(d, "慢 / 大 / 远", font(14))[0], 268), "慢 / 大 / 远", font=font(14), fill=MUTED)
    d.text((48, 268 + 22), "带宽高 · 容量小 · 延迟低", font=font(13), fill=MUTED)

    # pyramid geometry
    y0 = 310
    heights = [168, 188, 218, 198, 218, 188, 228, 198]
    gap = 8
    total_h = sum(heights) + gap * (len(heights) - 1)
    y1 = y0 + total_h
    top_hw, bot_hw = 310, 1040

    ys = []
    y = y0
    for hgt in heights:
        ys.append((y, y + hgt))
        y += hgt + gap

    # drop shadow
    for i, layer in enumerate(LAYERS):
        top, bot = ys[i]
        hw_t = half_width(top, y0, y1, top_hw, bot_hw)
        hw_b = half_width(bot, y0, y1, top_hw, bot_hw)
        poly = [
            (cx - hw_t + 8, top + 8),
            (cx + hw_t + 8, top + 8),
            (cx + hw_b + 8, bot + 8),
            (cx - hw_b + 8, bot + 8),
        ]
        d.polygon(poly, fill=(203, 213, 225))

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
        # inner highlight band
        mid = (top + bot) / 2
        hw_m = half_width(mid, y0, y1, top_hw, bot_hw)
        d.polygon(
            [
                (cx - hw_t + 3, top + 3),
                (cx + hw_t - 3, top + 3),
                (cx + hw_m - 3, mid),
                (cx - hw_m + 3, mid),
            ],
            fill=layer["fill2"],
        )
        outline = (253, 224, 71) if layer["ext"] else WHITE
        d.polygon(poly, outline=outline, width=3 if layer["ext"] else 2)

        pad = 28
        left = cx - hw_t + pad
        # conservative inner left using top width
        x0 = left
        yy = top + 12

        # badge
        badge_fg = GOLD if layer["ext"] else layer["fill"]
        badge_bg = GOLD_BG if layer["ext"] else WHITE
        bw, bh = pill(d, x0, yy, layer["id"], font(18), badge_fg, badge_bg, 12, 5)
        d.text((x0 + bw + 12, yy + 4), layer["name"], font=font(22), fill=WHITE)
        if layer["ext"]:
            ew, _ = tw(d, "扩展层", font(13))
            name_w, _ = tw(d, layer["name"], font(22))
            pill(d, x0 + bw + 12 + name_w + 12, yy + 6, "扩展层", font(13), GOLD, GOLD_BG, 8, 3)

        d.text((x0, yy + 36), layer["media"], font=font(15), fill=(255, 237, 213) if i < 3 else (226, 232, 240))

        # metric rows
        metrics = [
            ("容量", layer["cap"]),
            ("带宽", layer["bw"]),
            ("延迟", layer["lat"]),
        ]
        my = yy + 62
        for label, val in metrics:
            lw, lh = tw(d, label, font(14))
            rr(d, (x0, my, x0 + 52, my + lh + 8), 6, WHITE)
            d.text((x0 + (52 - lw) / 2, my + 3), label, font=font(14), fill=layer["fill2"])
            d.text((x0 + 62, my + 3), val, font=font(15), fill=WHITE)
            my += lh + 14

        d.text((x0, my + 2), "角色  " + layer["role"], font=font(14), fill=(254, 243, 199) if layer["ext"] else (226, 232, 240))

    # footer / sources
    fy = y1 + 28
    rr(d, (40, fy, W - 40, H - 28), 14, CARD, LINE, 2)
    d.text((60, fy + 16), "公开信息来源与读法", font=font(18), fill=NAVY)
    notes = [
        "数字为公开典型区间，跨代 SKU 并置（H100/H200/B200、DGX B200、GB200 NVL72、CXL 3.0、CloudMatrix384、CMX/ICMS），不是某一台机器的实测。",
        "G0：NVIDIA Hopper 白皮书（L1 256 KB/SM、L2 50 MB）；SMEM ~20 TB/s 为业界常用量级；L2 带宽取 Chips and Cheese / CUDA study 实测 ~3.5–5.5 TB/s。",
        "G1：NVIDIA 官方 H100 80 GB @ 3.35 TB/s、H200 141 GB @ 4.8 TB/s、B200 192 GB @ 8 TB/s；NVL72 GPU 内存合计 ~13.4 TB HBM3e。",
        "G1.5：GB200 的 Grace LPDDR 经 NVLink-C2C（900 GB/s 双向）直连 GPU，属 scale-up 相干路径；CXL 3.0 x16 原始 256 GB/s 双向；与 G2 的差异是「不经 PCIe H2D」。",
        "G2：DGX B200 主机内存 2 TB（可 4 TB）；H200 规格 PCIe Gen5 128 GB/s 双向。对 GPU 而言有效带宽是 H2D，不是 DDR 通道峰值。",
        "G2.5：超节点内把各节点主机 DDR 收成池。CloudMatrix384 UB ~392 GB/s 单向/NPU 且与计算通信共享；华为 UB 2.0 公开 2.1 µs。容量随节点数线性放大。GB200 的 17 TB LPDDR 计在 G1.5（C2C），不要与 G2.5 重复加总。",
        "G3：DGX B200 8×3.84 TB NVMe；企业级 PCIe 5 盘公开顺序读 ~14–14.5 GB/s（Solidigm D7-PS1010）。",
        "G3.5：NVIDIA CES/GTC 2026 的 ICMS，后更名 CMX，官方定位 G3.5（Local SSD 与云存储之间）。Pod 级 PB；BF4 800 Gb/s；WEKA GDS 公开单主机读 ~308 GB/s；相对通用存储最高 5× TPS。",
        "G4：对象存储 / 共享 FS。容量近乎无限，延迟进入毫秒；带宽取决于集群与客户端网卡，不能按单 GPU HBM 口径对比。",
        "G1.5 / G2.5 不是 NVIDIA 官方 G 阶梯的编号，是本图为区分「直挂 scale-up 的 DDR」与「超节点内远程 DDR 池」而插入的半层。",
    ]
    ny = fy + 48
    nf = font(14)
    for i, line in enumerate(notes):
        d.text((60, ny), f"{i + 1}.  {line}", font=nf, fill=INK if i == 0 else MUTED)
        ny += 22

    out = "/workspace/docs/memory-hierarchy-pyramid.png"
    img.save(out, "PNG", optimize=True)
    print("wrote", out, img.size)


if __name__ == "__main__":
    main()
