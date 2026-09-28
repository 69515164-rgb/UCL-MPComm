#!/usr/bin/env python3
"""Scale-out parameter-plane briefing.

Visual system: a single-accent specification sheet (white ground, hairline
tables, framed figures). Chinese is set in Noto Sans SC.

Scope is the east-west RDMA fabric only. Scale-up, north-south, and
commercial terms are out of scope.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Emu, Inches

W, H = 1920, 1080
OUT = Path("/workspace/docs/nvidia-param-plane")
FIGS = OUT / "src-figs"
FONT_PATH = "/workspace/docs/fonts/NotoSansSC.ttf"

BG = (255, 255, 255)
INK = (28, 32, 38)
MUTED = (88, 96, 106)
LINE = (218, 222, 228)
HAIR = (232, 235, 239)
ACCENT = (14, 74, 138)
SOFT = (244, 246, 249)
WHITE = (255, 255, 255)

ML = 64


def font(size: int, weight: int = 450) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_axes([weight])
    return f


def tw(d, t, f):
    return int(d.textlength(t, font=f))


def wrap(d, text, fnt, max_w):
    lines = []
    for para in str(text).split("\n"):
        if para == "":
            lines.append("")
            continue
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
    ImageDraw.Draw(img).rectangle((0, 0, W, 6), fill=ACCENT)
    return img


def block(d, x, y, text, fnt, fill, max_w, lh, max_lines=20):
    lines = wrap(d, text, fnt, max_w)[:max_lines]
    for i, ln in enumerate(lines):
        d.text((x, y + i * lh), ln, font=fnt, fill=fill)
    return y + max(1, len(lines)) * lh


def header(img, kicker, title, sub=None):
    d = ImageDraw.Draw(img)
    d.text((ML, 28), kicker, font=font(13, 600), fill=ACCENT)
    d.text((ML, 50), title, font=font(30, 620), fill=INK)
    rule = 100
    if sub:
        block(d, ML, 96, sub, font(15, 450), MUTED, 1792, 22, max_lines=2)
        rule = 146
    d.line((ML, rule, W - ML, rule), fill=LINE, width=1)
    return rule + 20


def footer(img, page, n, source):
    d = ImageDraw.Draw(img)
    d.line((ML, 1036, W - ML, 1036), fill=LINE, width=1)
    d.text((ML, 1048), source, font=font(12, 450), fill=MUTED)
    label = f"{page:02d}  /  {n:02d}"
    f = font(12, 600)
    d.text((W - ML - tw(d, label, f), 1048), label, font=f, fill=INK)


def note(img, y, text, h=78):
    d = ImageDraw.Draw(img)
    d.rectangle((ML, y, W - ML, y + h), fill=SOFT)
    d.rectangle((ML, y, ML + 4, y + h), fill=ACCENT)
    block(d, ML + 20, y + 14, text, font(15, 500), INK, 1740, 22, max_lines=3)
    return y + h


def trim_white(im, thr=248, pad=8):
    g = im.convert("L")
    bw = g.point(lambda p: 0 if p > thr else 255)
    box = bw.getbbox()
    if not box:
        return im
    x0, y0, x1, y1 = box
    return im.crop((max(0, x0 - pad), max(0, y0 - pad),
                    min(im.width, x1 + pad), min(im.height, y1 + pad)))


def contain(im, mw, mh):
    s = min(mw / im.width, mh / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                     Image.Resampling.LANCZOS)


def figure(img, box, path, caption):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    d.rectangle(box, outline=LINE, width=1)
    im = trim_white(Image.open(path).convert("RGB"))
    cap_h = 28
    fitted = contain(im, x1 - x0 - 16, y1 - y0 - cap_h - 12)
    px = x0 + (x1 - x0 - fitted.width) // 2
    py = y0 + 6 + (y1 - y0 - cap_h - 12 - fitted.height) // 2
    img.paste(fitted, (px, py))
    d = ImageDraw.Draw(img)
    d.text((x0 + 12, y1 - 24), caption, font=font(12, 450), fill=MUTED)


def bullets(d, x, y, items, max_w, size=15, lh=23, gap=10, color=INK):
    fnt = font(size, 450)
    for text in items:
        d.rectangle((x, y + 8, x + 5, y + 13), fill=ACCENT)
        y = block(d, x + 16, y, text, fnt, color, max_w - 16, lh)
        y += gap
    return y


def spec_table(img, box, headers, rows, col_w, size=14):
    x0, y0, x1, _y1 = box
    d = ImageDraw.Draw(img)
    hf = font(13, 600)
    bf = font(size, 450)
    lh = size + 6
    head_h = 34
    d.rectangle((x0, y0, x1, y0 + head_h), fill=ACCENT)
    x = x0
    for i, h in enumerate(headers):
        d.text((x + 10, y0 + 8), h, font=hf, fill=WHITE)
        x += col_w[i]
    y = y0 + head_h
    for r, row in enumerate(rows):
        heights = []
        for i, cell in enumerate(row):
            heights.append(len(wrap(d, cell, bf, col_w[i] - 20)) * lh + 14)
        rh = max(heights)
        if r % 2 == 1:
            d.rectangle((x0, y, x1, y + rh), fill=SOFT)
        d.line((x0, y + rh, x1, y + rh), fill=HAIR, width=1)
        x = x0
        for i, cell in enumerate(row):
            block(d, x + 10, y + 7, cell, bf, INK, col_w[i] - 20, lh, max_lines=6)
            x += col_w[i]
        y += rh
    d.rectangle((x0, y0, x1, y), outline=LINE, width=1)
    return y


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def slide_cover(n):
    img = canvas()
    d = ImageDraw.Draw(img)
    d.text((ML, 78), "DATA CENTER NETWORK    ·    SCALE-OUT", font=font(14, 600), fill=ACCENT)
    d.text((ML, 150), "NVIDIA 参数面", font=font(64, 620), fill=INK)
    d.text((ML, 236), "Scale-out 网络的完整方案、标准与定制", font=font(28, 500), fill=INK)
    d.rectangle((ML, 300, 220, 304), fill=ACCENT)
    block(
        d, ML, 332,
        "只讨论东西向 RDMA 织物。NVIDIA 自有方案是 Spectrum-X 以太和 Quantum InfiniBand。\n"
        "同一颗 ConnectX-8、同一代 Spectrum 交换机，也可以跑客户自己的传输。OpenAI 与微软的 MRC 就是这一层。",
        font(18, 450), MUTED, 1500, 30, max_lines=3,
    )
    rows = [
        ("01  —  07", "自有方案", "多平面、三条硬件控制环、故障收敛、论文实测、代际物料。"),
        ("08  —  11", "标准", "UEC、SUE、ESUN、IBTA、IEEE 802.3。席位、主推技术、策略。"),
        ("12  —  16", "定制", "MRC 的公开架构，以及 Meta、Oracle、AWS、Google、xAI 各自换掉的那一层。"),
    ]
    y = 470
    for num, name, desc in rows:
        d.line((ML, y, W - ML, y), fill=HAIR, width=1)
        d.text((ML, y + 18), num, font=font(16, 600), fill=ACCENT)
        d.text((280, y + 16), name, font=font(20, 620), fill=INK)
        d.text((520, y + 20), desc, font=font(16, 450), fill=MUTED)
        y += 72
    d.line((ML, y, W - ML, y), fill=HAIR, width=1)
    d.text((ML, 980), "研究截止  2026-09-28", font=font(14, 450), fill=MUTED)
    d.text((ML, 1008), "架构图来自 NVIDIA arXiv:2605.21187，以及 OpenAI / Microsoft 的 MRC 论文", font=font(14, 450), fill=MUTED)
    label = f"01  /  {n:02d}"
    f = font(14, 600)
    d.text((W - ML - tw(d, label, f), 980), label, font=f, fill=INK)
    return img


def slide_map(n):
    img = canvas()
    y0 = header(img, "02    总图", "参数面只有一条数据路径，上面有四层可以换",
                "从 GPU 网卡出去，到对端 GPU 网卡。Scale-up 的 NVLink、南北向的 BlueField 不在这条路径上。")
    stages = [
        ("1", "端点", "ConnectX / BlueField\n或客户网卡", "速率、verbs 接口"),
        ("2", "传输", "Spectrum-X 控制环\n或 MRC / SRD / RoCE", "谁做逐包均衡"),
        ("3", "路由", "交换机 AR\n或静态 SRv6 / BGP", "路径怎么选"),
        ("4", "转发面", "Spectrum / Quantum\n或 Tomahawk、自研 NOS", "芯片还是整机"),
    ]
    cw = 430
    for i, (num, name, tech, q) in enumerate(stages):
        x = ML + i * (cw + 24)
        d = ImageDraw.Draw(img)
        d.rectangle((x, y0, x + cw, y0 + 210), outline=LINE, width=1)
        d.rectangle((x, y0, x + cw, y0 + 4), fill=ACCENT)
        d.text((x + 20, y0 + 20), num, font=font(13, 600), fill=ACCENT)
        d.text((x + 48, y0 + 16), name, font=font(22, 620), fill=INK)
        block(d, x + 20, y0 + 64, tech, font(16, 450), INK, cw - 40, 24)
        d.text((x + 20, y0 + 160), q, font=font(14, 500), fill=MUTED)
        if i < 3:
            d.text((x + cw + 4, y0 + 88), "→", font=font(20, 500), fill=LINE)
    # two columns under
    d = ImageDraw.Draw(img)
    y = y0 + 240
    d.rectangle((ML, y, 940, y + 300), outline=LINE, width=1)
    d.rectangle((960, y, W - ML, y + 300), outline=LINE, width=1)
    d.text((ML + 20, y + 16), "NVIDIA 自有方案锁住的", font=font(16, 620), fill=ACCENT)
    bullets(d, ML + 20, y + 56, [
        "Spectrum-X：交换机逐包自适应路由，网卡按平面选路，链路层无损。性能依赖交换机和 SuperNIC 配对。",
        "Quantum InfiniBand：同一件 scale-out 工作，另加 SHARP 网内归约和 UFM。以太交换机的公开特性清单里没有 SHARP。",
        "对应用透明。几个平面都只暴露一个 RoCE 设备，NCCL 不用改。",
    ], 840, size=15, lh=22, gap=8)
    d.text((980, y + 16), "客户可以换掉的", font=font(16, 620), fill=ACCENT)
    bullets(d, 980, y + 56, [
        "传输。MRC 把逐包喷洒、选择性重传和静态源路由做进 CX-8，并关掉交换机动态路由。",
        "整机与 NOS。Meta 买 Spectrum-4 芯片，机箱、FBOSS 和拥塞策略是自己的。",
        "网卡。Oracle 用自研 Acceleron 做多平面，交换仍可以是 NVIDIA。AWS 的 SRD 连交换一起换掉。",
    ], 840, size=15, lh=22, gap=8)
    note(img, 900,
         "云伙伴规范 NET-2 把东西向织物写成必须是 InfiniBand 或 Spectrum-X。这是托管 DGX Cloud 的合同条款。MRC 说明硅片本身还能跑第三种传输。")
    footer(img, 2, n, "NET-2：docs.nvidia.com DGX Cloud 伙伴规范。MRC 的实现范围见第 13–14 页。")
    return img


def slide_fabrics(n):
    img = canvas()
    y0 = header(img, "03    自有方案", "两条 scale-out：以太靠配对控制环，InfiniBand 多一个 SHARP",
                "Huang，2025 年 8 月财报电话：对头部模型厂商，Quantum InfiniBand 是明确选择。Spectrum Ethernet is not off the shelf。")
    headers = ["", "Spectrum-X 以太", "Quantum InfiniBand"]
    rows = [
        ["交换", "Spectrum-4 起，到 Spectrum-6\n102.4 Tb/s / 芯片，200G SerDes", "Quantum-2，再到 Quantum-X800\n144×800 Gb/s"],
        ["端点", "BlueField-3、ConnectX-7/8/9\n与交换机配对", "ConnectX-8 / ConnectX-9\n官方平台包含这两代 SuperNIC"],
        ["逐包均衡", "交换机自适应路由\n网卡平面负载均衡", "自适应路由"],
        ["拥塞", "RTT 探针。ECN 只在负载均衡\n容量用尽之后标记", "基于遥测的拥塞控制"],
        ["可靠性", "无损 PFC。论文称两年生产\n未见 PFC 风暴", "InfiniBand 链路层"],
        ["网内归约", "公开特性清单没有交换机侧 SHARP", "SHARP v4。NVLink 交换机上的\nSHARP 属于 scale-up，不在这里"],
        ["管理与开放栈", "SONiC、SAI", "UFM"],
        ["公开落点", "xAI 10 万 Hopper：SN5600 + BF-3\nDSX 参考设计的默认织物", "Azure NDv6 GB300 集群内\nCoreWeave GB300"],
    ]
    spec_table(img, (ML, y0, W - ML, 900), headers, rows, [220, 786, 786], size=15)
    footer(img, 3, n, "Quantum-X800 产品页；Spectrum-X FAQ；Vera Rubin 技术博客；xAI 新闻稿 2024-10-28；Azure GB300 博文。")
    return img


def slide_topo(n):
    img = canvas()
    y0 = header(img, "04    拓扑", "用平面并行代替再加一层脊",
                "Spectrum-X 论文第 3 节，范围停在 Blackwell Ultra。作者把南北向、scale-across 和 NVLink 标成超出本文。")
    figure(img, (ML, y0, 1040, 900), FIGS / "fig02.png",
           "Figure 2    四平面、两层胖树、rail-optimized。Khashab et al., arXiv:2605.21187")
    d = ImageDraw.Draw(img)
    d.text((1080, y0), "架构师要记住的五点", font=font(16, 620), fill=INK)
    bullets(d, 1080, y0 + 40, [
        "平面在交换机侧断开。网卡经无源光 shuffle box 接入全部平面，网卡到网卡仍然全可达。",
        "论文给出的容量上界：两层多平面 12.8 万端点，三层 1600 万。这是拓扑上界，不是已交付规模。",
        "一个 800 Gb/s 网卡拆成 4×200 Gb/s，每平面一张胖树。测试床 Blackwell Ultra 是 1152 GPU、4 平面、CX-8。",
        "对应用只暴露一个 RoCE 设备。乱序由网卡直接写入目的内存，完成队列在网卡里重排。",
        "非满配用并行链路填端口。论文把 100 台 10% 占用的脊收成 10 台满配脊加 10 条并行链路，对等带宽还在。",
    ], 760, size=15, lh=22, gap=12)
    footer(img, 4, n, "arXiv:2605.21187，§2.2 与 §3.1，Figure 2，Table 2。")
    return img


def slide_loops(n):
    img = canvas()
    y0 = header(img, "05    控制环", "三条环分开，是因为它们会互相误读",
                "作者的原话：把三条环关进各自的带宽时延积，软件路径做不到。硬件加速是结构要求。")
    headers = ["", "自适应路由", "平面负载均衡", "拥塞控制"]
    rows = [
        ["位置", "交换机 fabric 口", "网卡平面口", "发送端"],
        ["状态", "无状态，逐包", "每个目的地一份，按平面拆开", "每个目的地，有状态"],
        ["时间", "数百纳秒\n队列亚微秒采样", "逐包选择\n故障在数个 RTT 内掩掉", "RTT"],
        ["信号", "出口队列深度\n量化的最短队列", "该平面的速率额度\n再加本地队列", "RTT 探针\nECN 仅在均衡容量用尽后"],
        ["不做的事", "不看端到端 incast", "不在平面内部选路径", "不追自适应路由能吸收的微突发"],
    ]
    y = spec_table(img, (ML, y0, W - ML, 700), headers, rows, [160, 544, 544, 544], size=15)
    figure(img, (ML, y + 16, 980, 990), FIGS / "fig04.png",
           "Figure 4    先掩掉限速面和故障面，再在剩下的平面里选最浅队列")
    d = ImageDraw.Draw(img)
    bullets(d, 1020, y + 24, [
        "fabric 口上的微突发会抬高 RTT。拥塞控制若把它读成 incast，会在所有平面上一起限速。",
        "平面内断一条上联，其余链路负载增加不到 1%。四平面断一平面，剩下的会被不成比例地打满。所以平面内无状态，平面间有状态。",
        "逐包喷洒让乱序和丢包分不清，所以这条方案选择无损。超过 97% 的流量容忍乱序。要保序的控制流量走普通以太和 BGP。",
    ], 820, size=15, lh=22, gap=12)
    footer(img, 5, n, "arXiv:2605.21187，§3.2、§4.1–§4.3，Figure 3 与 Figure 4。")
    return img


def slide_fail(n):
    img = canvas()
    y0 = header(img, "06    故障", "瞬时故障走硬件，永久不对称走权重",
                "本地链路约 100 纳秒排除。远端永久故障的权重由 BGP 计算，算完之后硬件仍按包平衡。")
    stats = [
        ("< 3 ms", "四平面断一平面\n硬件回到 75% 线速"),
        ("1.08 s", "NCCL 之上的软件均衡\n论文称大约慢 400 倍"),
        ("−11%", "永久少 10% 链路\n378 → 335 Gb/s"),
        ("+1 µs", "同一实验的 p99\n14.97 → 15.96 µs"),
    ]
    cw = 430
    for i, (num, text) in enumerate(stats):
        x = ML + i * (cw + 24)
        d = ImageDraw.Draw(img)
        d.text((x, y0), num, font=font(32, 620), fill=ACCENT)
        block(d, x, y0 + 46, text, font(15, 450), INK, cw - 8, 22)
    figure(img, (ML, y0 + 120, 1000, 900), FIGS / "fig05.png",
           "Figure 5    远端 D 容量下降后，去 D 的权重转向仍有容量的脊")
    d = ImageDraw.Draw(img)
    bullets(d, 1040, y0 + 130, [
        "Nemotron 3 Ultra，64 节点，四平面。主机到叶的链路闪断，一个迭代内退到三条平面，恢复后回到基线步时 2.95 秒。叶到脊的闪断几乎不动步时。",
        "单平面配置下，主机链路一断，RDMA 连接直接崩溃。",
        "NSX 仿真，25.6 万 GPU：收敛停在 10 毫秒以内，P99 集合完成时间大约 +20%。拖到 100 毫秒约 +53%，300 毫秒约 +260%。",
        "仿真用的闪断率，作者称为偏保守的最坏估计，而且只在集群生命周期的一部分里见过。",
        "Figure 12 的曲线：硬件平面切换在 3 毫秒内回到三条平面的线速。",
    ], 800, size=15, lh=22, gap=10)
    footer(img, 6, n, "arXiv:2605.21187，§4.4、§6.4–§6.6，Figure 5、12、13、14。")
    return img


def slide_eval(n):
    img = canvas()
    y0 = header(img, "07    实测", "论文对照的是 DCQCN 加 ECMP，不是 UEC，也不是 MRC",
                "部署陈述未经第三方审计：数十个客户集群，合计超过 100 万 GPU，生产超过两年。")
    kpis = [
        ("98%", "p01 带宽 / 线速", "64 节点，流量全部过脊"),
        ("8–9 µs", "75% 负载下 p99", "以太中位约 13 µs，散到 22"),
        ("668 ms", "有背景流的步时", "DeepSeek 代理，单独跑 667 ms"),
        ("49.3", "GB/s，安静 All2All", "硬件能力 49.5，约 99.5%"),
    ]
    for i, (a, b, c) in enumerate(kpis):
        x = ML + i * 456
        d = ImageDraw.Draw(img)
        d.text((x, y0), a, font=font(26, 620), fill=ACCENT)
        d.text((x, y0 + 36), b, font=font(14, 600), fill=INK)
        d.text((x, y0 + 58), c, font=font(13, 450), fill=MUTED)
    figure(img, (ML, y0 + 100, 940, 760), FIGS / "fig08.png",
           "Figure 8    左：高负载带宽分布。右：300 Gb/s 下的 p99 时延")
    figure(img, (964, y0 + 100, W - ML, 760), FIGS / "fig13.png",
           "Figure 13    训练步时。灰为主机链路闪断，绿为叶到脊闪断")
    note(img, 784,
         "两份 All2All 并行时，以太受害带宽掉到 10.9 GB/s 以下。Spectrum-X 近乎不掉。不对称实验里，全局一份拥塞上下文会把一对多带宽从 94.5 打到 47.3 GB/s；按平面拆开的上下文维持 93.7。4 MB 以下报文还没攒够每平面信号。",
         h=96)
    footer(img, 7, n, "arXiv:2605.21187，§5–§6，Table 1，Figure 8、9、10、13、15。DeepSeek 是 16 节点代理，不是全量预训练。")
    return img


def slide_bom(n):
    img = canvas()
    y0 = header(img, "08    物料与边界", "三代端点，以及三件容易写错层的技术",
                "ConnectX-9 的端口拆分，官网 FAQ 与技术博客表格不一致。这里只写两边相同的每 GPU 1.6 Tb/s。")
    headers = ["", "Hopper", "Blackwell", "Vera Rubin"]
    rows = [
        ["以太交换", "Spectrum-4，51.2 Tb/s\nSN5600，64×800GbE", "SN5000 系列\n同一代芯片", "Spectrum-6，102.4 Tb/s/芯片\nSN6600 128×800G\nSN6800 512×800G，5U"],
        ["端点", "测试床 CX-7\nxAI 部署 BF-3，400 GbE", "ConnectX-8\n800 Gb/s，2×400G", "ConnectX-9\n1.6 Tb/s / GPU"],
        ["论文测试床", "1024 GPU，1 平面\n三层胖树，CX-7", "1152 GPU，4 平面\n两层，CX-8", "架构讨论停在\nBlackwell Ultra"],
        ["InfiniBand", "Quantum-2", "Quantum-X800\n144×800G，SHARP v4", "仍与 Spectrum-X 并列\n为 Rubin 的 scale-out"],
    ]
    y = spec_table(img, (ML, y0, W - ML, 640), headers, rows, [200, 530, 530, 532], size=15)
    headers2 = ["", "它是什么", "在不在这条以太参数面上"]
    rows2 = [
        ["SHARP", "交换机里做集合归约", "在 Quantum 上。以太特性清单没有对等项。NET-2 写 SHARP where supported"],
        ["Spectrum-XGS", "跨园区。距离自适应拥塞控制", "是这条以太织物向外的一跳。厂商口径：10 公里大消息 AllReduce 1.9 倍，内部实验。具名客户 CoreWeave"],
        ["共封装光", "Spectrum-6 的光版本", "同一台交换机的光形态。厂商口径相对可插拔：能效 5 倍、故障间隔 10 倍。不改变三条控制环"],
    ]
    spec_table(img, (ML, y + 20, W - ML, 980), headers2, rows2, [220, 520, 1052], size=15)
    footer(img, 8, n, "Spectrum-X FAQ；Vera Rubin 技术博客；Quantum-X800 产品页；XGS 新闻稿 2025-08-22。SN6800 的 409.6 Tb/s 是推算，不写。")
    return img


def slide_std_map(n):
    img = canvas()
    y0 = header(img, "09    标准地图", "和 scale-out 有关的组织，NVIDIA 的席位不一样",
                "会员身份截至 2026-09-28。组织不公布工作组名册的，写成查无，不写成零贡献。")
    headers = ["层", "组织", "NVIDIA 的公开位置"]
    rows = [
        ["物理层", "IEEE 802.3dj\nOIF", "深。2026-03 的 802.3dj 出席至少 6 名工程师并署名评论决议。Karl Bois 任 OIF 技术委员会副主席。"],
        ["Scale-out 传输", "UEC", "2024-06 向媒体确认，2024-09 列入一般会员。无指导委员会席位。查无工作组主席或编辑。没有产品符合性声明。"],
        ["RoCE 血统", "IBTA", "Shainer：RoCE 在 IBTA 标准化，NVIDIA 在其中继续改规范。MRC 选择延伸这条血统，而不是换一套新传输。"],
        ["Scale-up 以太织物", "OCP ESUN\nSUE-T", "ESUN 12 家创始之一，名单里同时有 OpenAI。Broadcom 把 NVIDIA 列入 SUE-T 支持者。参与深度超出名单，公开材料不够。"],
        ["Scale-up 端点", "SUE / SUE-Lite", "文本作者是 Broadcom，不是 NVIDIA。它规定的是加速器之间的以太事务，不是 scale-out 交换。"],
        ["另一套 scale-up", "UALink", "公开名册上没有 NVIDIA。和参数面没有直接接口，这里只标明缺席。"],
    ]
    spec_table(img, (ML, y0, W - ML, 980), headers, rows, [240, 280, 1272], size=15)
    footer(img, 9, n, "UEC 会员帖与 The Next Platform 2024-06-26；802.3dj 会议纪要；OIF 2026-01-14；OCP ESUN；UALink 发起新闻。")
    return img


def slide_uec(n):
    img = canvas()
    y0 = header(img, "10    UEC", "1.0 在标准化 Spectrum-X 已经用专有配对做成的那些功能",
                "1.0 于 2025-06-11 发布。1.1 截至 2026-09-28 未发布。联盟曾写 CSIG 计划在 2026 年一季度随 1.1 公布。")
    headers = ["功能", "UEC 1.0，1.1 为计划", "Spectrum-X 现在的做法"]
    rows = [
        ["多路径", "Packet spray，端与交换机协同", "交换机逐包自适应路由，SuperNIC 重排"],
        ["拥塞", "NSCC / RCCC。1.1 计划 PCM，算法可跨网卡", "SuperNIC 可编程拥塞控制，线格式不公开"],
        ["遥测", "CSIG，4 或 8 字节，沿途比较替换", "端到端高频遥测"],
        ["链路", "LLR + 基于信用的流控，LLDP 协商", "无损 PFC。单链路故障收在该链路里，无公开互操作规范"],
        ["丢包信号", "可选包修剪", "无损前提下少丢。MRC 才把修剪用在有损以太上"],
        ["网内集合", "INC，可选", "SHARP 在 InfiniBand，不在以太交换机"],
        ["传输", "新的 UET，无握手短连接", "RoCEv2 加 NVIDIA 扩展"],
        ["Scale-up", "1.1 计划：统一转发头、单向时延 <1 µs", "不是这条参数面的范围"],
    ]
    y = spec_table(img, (ML, y0, W - ML, 860), headers, rows, [180, 800, 812], size=14)
    note(img, y + 16,
         "对照是分析，不是 NVIDIA 的官方表。ConnectX-8 手册的符合性清单是 IEEE 802.3 和 IBTA 1.7。Broadcom Thor Ultra 宣称完全符合 UEC。OFC 2026 首次公开的 LLR 互通是 Keysight 加 Broadcom。",
         h=88)
    footer(img, 10, n, "UEC 规范史；1.0.3 发布说明 2026-07-16；Congdon ITU-T 2026-07-11；ConnectX-8 手册；Thor Ultra 新闻稿 2025-10-14。")
    return img


def slide_sue(n):
    img = canvas()
    y0 = header(img, "11    SUE 与 ESUN", "SUE 是端点事务，ESUN 是织物需求，两者都不是 UEC 传输",
                "一个 scale-out 架构师要知道它们卡在哪一层，才不会把三份文本当成同一个标准。")
    headers = ["", "SUE", "SUE-Lite", "ESUN 1.0"]
    rows = [
        ["谁写的", "Broadcom\n2025-04 交到 OCP\n修订史唯一作者", "Broadcom\n2025-07 随 Tomahawk Ultra", "OCP。12 家创始含 NVIDIA、OpenAI、Meta、微软、Oracle"],
        ["哪一层", "加速器侧以太接口\n含端到端可靠传输\n和固定窗口拥塞控制", "同一接口的裁剪档", "L2/L3 织物的运营商需求基线，不是线协议"],
        ["相对完整档\n砍掉什么", "—", "端到端可靠、拥塞控制、分区。只留逐跳 LLR 与基于信用的流控。规范写 IP 面积最多少 50%", "大部分需求直接引用 UEC 1.0。压缩头用自写的 ESUN Header"],
        ["和参数面", "不规定 scale-out 交换机", "用面积论证机柜内可以不要端到端传输", "2026-02-12 批准。参与公司超过 175 家。NVIDIA 在创始名单"],
    ]
    y = spec_table(img, (ML, y0, W - ML, 780), headers, rows, [200, 500, 546, 546], size=14)
    note(img, y + 18,
         "Shainer，2026-07-16：我们在 UEC，在 ESUN，并且有贡献。同一段话用年度换代解释为什么不能等共识流程。ESUN 创始身份是公开的；具体写了哪一节，公开材料不够。",
         h=88)
    footer(img, 11, n, "OCP SUE 规范修订史；Broadcom 2025-07-15；OCP ESUN 1.0 博客；theCUBE 2026-07-16。")
    return img


def slide_std_strategy(n):
    img = canvas()
    y0 = header(img, "12    标准策略", "物理层做成标准，传输层保留一套自有方案，同时把开放传输做进同一颗网卡",
                "这是从席位和产品声明归纳的判断，不是 NVIDIA 的自我描述。自我描述在下面三句原话里。")
    headers = ["层", "公开行为", "对 scale-out 采购的含义"]
    rows = [
        ["200G SerDes、1.6T 光", "802.3dj 点名工程师，OIF 技术委员会副主席", "端口速率是公共品。谁的交换机都得用。"],
        ["UEC 传输", "一般会员。无符合性声明。缺席首次 LLR 互通", "Spectrum-X 不按 UEC 交货。UEC 符合性目前是 Broadcom 的说法。"],
        ["RoCE / IBTA", "继续改自己参与的传输", "MRC 选择延伸 RC，而不是等待 UET 换代。"],
        ["ESUN / SUE-T", "创始成员，支持者名单", "以太如果往 scale-up 长，NVIDIA 的交换机仍可能卖进去。"],
        ["Spectrum-X 本身", "Huang：不是现成以太。要交换机和 SuperNIC 一起", "自有方案的性能层不开放线格式。"],
    ]
    y = spec_table(img, (ML, y0, W - ML, 720), headers, rows, [280, 760, 752], size=15)
    quotes = [
        ("2024-06-26", "加入 UEC，是为了支持对客户有用的规范。未来也许会在 Spectrum-X 之外，再提供一个 UEC 版本的以太。"),
        ("Huang", "Spectrum Ethernet is not off the shelf。"),
        ("Shainer，2026-07", "我们在 UEC，在 ESUN，并且有贡献。同时必须非常快，因为每年都有新的一代。"),
    ]
    yy = y + 18
    cw = 576
    for i, (who, text) in enumerate(quotes):
        x = ML + i * (cw + 16)
        d = ImageDraw.Draw(img)
        d.rectangle((x, yy, x + cw, 1008), outline=LINE, width=1)
        d.rectangle((x, yy, x + 4, 1008), fill=ACCENT)
        d.text((x + 16, yy + 12), who, font=font(13, 600), fill=ACCENT)
        block(d, x + 16, yy + 38, text, font(14, 450), INK, cw - 32, 20, max_lines=5)
    footer(img, 12, n, "原话分别来自 The Next Platform、Q2 FY2026 财报电话、theCUBE。")
    return img


def slide_mrc(n):
    img = canvas()
    y0 = header(img, "13    定制    MRC", "OpenAI 与微软把传输换成开放的 MRC，交换机路由改成静态源路由",
                "论文作者单位含 OpenAI、Microsoft、NVIDIA、AMD、Broadcom。NVIDIA 通讯作者是 Sayantan Sur。规范交到 OCP。")
    figure(img, (ML, y0, 980, y0 + 430), FIGS / "mrc-fig1.png",
           "Figure 1    左：800G 单平面三层到 64K。右：8×100G 两层到 131,072 网卡")
    d = ImageDraw.Draw(img)
    bullets(d, 1010, y0, [
        "三件事一起做：端点逐包喷洒，多平面把十万以上 GPU 收进两层，静态 SRv6 让端点自己绕故障。",
        "关掉 PFC。每个包带 32 位熵，典型 128–256 条路径，均匀分到各平面。",
        "动态路由关掉。理由是端点已经在自适应，两套自适应会互相打扰。",
        "SRv6 用 uN 微段，转发表装机时写好。Spectrum-4、Spectrum-5 和 Tomahawk 5 都能线速转发。",
        "网卡：ConnectX-8、AMD Pollara / Vulcano、Thor Ultra。仍是 verbs，数据面只做 Write 和 WriteImm。",
        "坏路径数十微秒停用。CX-8 上网卡口故障，要数秒才把全部 QP 重映射完。",
    ], 840, size=14, lh=20, gap=6)
    spec_table(
        img, (ML, y0 + 450, W - ML, 1000),
        ["生产集群", "网卡", "交换", "拓扑"],
        [
            ["A", "GB200 + CX-8，800 Gb/s", "Spectrum-4 与 Tomahawk 5 混布", "两层，4×200 Gb/s"],
            ["B", "GB200 + CX-8，800 Gb/s", "论文写 Spectrum-5", "两层，8×100 Gb/s"],
            ["C", "MI355 + Pollara，400 Gb/s", "Tomahawk 5", "两层，4×100 Gb/s"],
            ["D", "RTX 6000 + Thor Ultra", "Tomahawk 5", "两层，400 Gb/s 单平面"],
        ],
        [180, 480, 620, 512],
        size=14,
    )
    footer(img, 13, n, "OpenAI / Microsoft 等，Resilient AI Supercomputer Networking using MRC and SRv6。配套传输论文 arXiv:2606.18170。")
    return img


def slide_mrc_vs(n):
    img = canvas()
    y0 = header(img, "14    两条以太", "Spectrum-X 与 MRC 都用多平面，均衡放在相反的一端",
                "不要把 MRC 写成 Spectrum-X 的一个功能，也不要写成广域网专有协议。论文写的是训练簇内部的后端。")
    headers = ["", "Spectrum-X，NVIDIA 自有", "MRC，客户方案，NVIDIA 参与实现"]
    rows = [
        ["逐包均衡", "交换机按队列深度选出口\n网卡再选平面", "端点按熵值喷洒\n交换机不做自适应"],
        ["路由", "永久不对称用 BGP 权重", "静态 SRv6。装机后转发表基本不改"],
        ["丢包", "无损。乱序与丢包不可分", "有损。SACK 选择性重传，可选包修剪"],
        ["ECN", "只在均衡容量用尽后标记", "当作选路信号。最后一跳关掉 ECN"],
        ["故障时延", "平面故障 < 3 ms 回到 75%", "坏路径数十微秒停用。网卡口重映射为数秒"],
        ["谁能互操作", "性能要 NVIDIA 交换机加 SuperNIC", "CX-8、Pollara、Thor Ultra\nSpectrum 与 Tomahawk 5"],
        ["生产规模", "论文测试床最大 1152 GPU\n另有超过 100 万 GPU 的部署陈述", "75K GPU 作业的启动丢包曲线\n50K GPU 作业扛过光模块闪断"],
    ]
    y = spec_table(img, (ML, y0, W - ML, 860), headers, rows, [200, 760, 832], size=14)
    note(img, y + 12,
         "50K GPU 作业里，一个光模块连闪四条网卡链路，吞吐大约掉 25% 并持续约一分钟，随后回到全速。作业没有崩溃，也没有把节点踢出作业。75K GPU 启动时不预填坏路径，第一分钟每个 QP 丢包少于 5 个。",
         h=78)
    footer(img, 14, n, "MRC 论文 §2、§5，Table 1，Figure 4 与 Figure 6。Spectrum-X 数字来自 arXiv:2605.21187。两边都是作者自己的测量。")
    return img


def slide_customers(n):
    img = canvas()
    y0 = header(img, "15    客户", "大客户改的是 scale-out 的哪一层",
                "有自研网络团队的客户留下交换或传输。没有的，拿走 NVIDIA 整套。")
    headers = ["客户", "交换", "网卡", "传输与路由"]
    rows = [
        ["xAI Colossus", "SN5600，Spectrum-4", "BlueField-3\n400 GbE / GPU", "整套 Spectrum-X。10 万 Hopper，122 天。参考部署"],
        ["CoreWeave GB300", "Quantum-X800", "ConnectX-8\n800 Gb/s", "InfiniBand 加 SHARP。跨园用 Spectrum-XGS"],
        ["Azure NDv6", "Quantum-X800", "NVIDIA", "集群内走自有 IB。与 Fairwater 上的 MRC 不是同一张网"],
        ["OpenAI / 微软训练簇", "Spectrum-4/5\n与 Tomahawk 5 混布", "CX-8，也有\nPollara、Thor Ultra", "MRC，静态 SRv6，有损。用于训练前沿模型"],
        ["Meta", "Spectrum-4 芯片\n自研机箱，FBOSS", "多厂商", "2024 年已选 RoCE。拥塞控制在集合库的接收端准入"],
        ["Oracle", "IB 与 Spectrum-X\n都可以", "Acceleron 自研\n也有 ConnectX", "网卡里做硬件多平面。交换芯片与端点拆开"],
        ["AWS", "自研", "Nitro / EFA", "SRD。一次把一个块喷到最多 64 条路径。不买 NVIDIA scale-out"],
        ["Google GPU 虚机", "Jupiter + 光电路交换", "ConnectX-7", "买网卡和 NVL72，不买参数面交换机"],
    ]
    spec_table(img, (ML, y0, W - ML, 1000), headers, rows, [280, 340, 300, 872], size=14)
    footer(img, 15, n, "xAI 新闻稿；CoreWeave、Azure 公开博文；MRC 论文 Table 1；Meta SIGCOMM 2024 与 Minipack3N；Oracle Acceleron；AWS HPC 博客；Google NSDI 2024 与 A3 Ultra。")
    return img


def slide_strategy(n):
    img = canvas()
    y0 = header(img, "16    定制策略", "三档。硅片可以进别人的设计，自有控制环不会因此停卖",
                "MRC 是第三档的公开证据：NVIDIA 工程师署名，把客户的开放传输做进自己的网卡和交换机，并接受关掉自己的自适应路由。")
    tiers = [
        ("01", "整套拿走", "客户没有自己的网络团队，或者合同要求 NET-2。",
         "xAI 的 Spectrum-X，CoreWeave 和 Azure NDv6 的 Quantum-X800。织物、网卡、拥塞控制都是 NVIDIA 的。"),
        ("02", "买芯片或网卡，控制面留下", "客户要换 NOS、拥塞策略或多厂商。",
         "Meta 的 Spectrum-4 进 FBOSS。Oracle 的 Acceleron 网卡配 NVIDIA 交换。Google 只买 ConnectX-7。AWS 这一档也不进，交换和传输都是自己的。"),
        ("03", "在 NVIDIA 硅片上跑客户的传输", "客户要多厂商互操作，并且不要两套自适应路由叠在一起。",
         "MRC。CX-8 与 Spectrum-4/5 实现它，Tomahawk 5 和 Thor Ultra 也实现它。Spectrum-X 继续作为另一条产品线销售。"),
    ]
    y = y0
    for num, title, when, how in tiers:
        d = ImageDraw.Draw(img)
        d.text((ML, y), num, font=font(14, 600), fill=ACCENT)
        d.text((ML + 48, y - 2), title, font=font(20, 620), fill=INK)
        d.text((ML + 420, y + 2), when, font=font(15, 450), fill=MUTED)
        block(d, ML + 48, y + 36, how, font(15, 450), INK, 1700, 22, max_lines=2)
        y += 100
        d.line((ML, y - 16, W - ML, y - 16), fill=HAIR, width=1)
    d = ImageDraw.Draw(img)
    d.text((ML, y + 8), "和标准策略如何是同一件事", font=font(18, 620), fill=INK)
    bullets(d, ML, y + 48, [
        "UEC 会员没有变成 Spectrum-X 的符合性标签。自有以太方案继续用专有的交换机与网卡配对。",
        "同一时期，NVIDIA 把一套借鉴 UET、但仍然延伸 RoCE 的开放传输做进 CX-8。这比发布一个 UEC 版本的 Spectrum-X 更靠近已投产的客户。",
        "SUE 不在这条定制路径上。它是 Broadcom 写的 scale-up 端点规范。NVIDIA 在 ESUN 里，是因为那一层仍然可能卖出以太网交换芯片。",
        "所以采购时要分开问两句：要的是 NVIDIA 的控制环，还是 NVIDIA 的硅片。MRC、Minipack3N 和 xAI 分别是这三档的样本。",
    ], 1760, size=15, lh=22, gap=8)
    footer(img, 16, n, "不写入本套材料：出口管制 SKU、股权与园区担保、NVLink Fusion 的投资金额、Kyber 延期、Colossus 2 的织物代际。那些不是 scale-out 架构。")
    return img


def build():
    slides = [
        slide_cover, slide_map, slide_fabrics, slide_topo, slide_loops,
        slide_fail, slide_eval, slide_bom, slide_std_map, slide_uec,
        slide_sue, slide_std_strategy, slide_mrc, slide_mrc_vs,
        slide_customers, slide_strategy,
    ]
    n = len(slides)
    # cover and others take n
    pngs = []
    OUT.mkdir(parents=True, exist_ok=True)
    for i, fn in enumerate(slides, 1):
        img = fn(n)
        path = OUT / f"{i:02d}.png"
        img.save(path, "PNG")
        pngs.append(path)
        print(path.name)
    # drop stale pages from the previous 19-page deck
    for stale in OUT.glob("*.png"):
        if stale not in pngs:
            stale.unlink()
            print("removed", stale.name)
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for p in pngs:
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(str(p), Emu(0), Emu(0), width=prs.slide_width, height=prs.slide_height)
    out = Path("/workspace/docs/nvidia-param-plane.pptx")
    prs.save(out)
    print(out)


if __name__ == "__main__":
    build()
