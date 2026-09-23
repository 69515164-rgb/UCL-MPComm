#!/usr/bin/env python3
"""Render SLO-gated inference network planning slides and pack a PPTX."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Inches, Emu

W, H = 1920, 1080
OUT = Path("/workspace/docs")
SLIDE_DIR = OUT / "slo-gated-inference-net"
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"

BG = (246, 244, 239)
INK = (27, 36, 48)
MUTED = (92, 102, 112)
TEAL = (15, 110, 107)
TEAL_D = (10, 78, 76)
CORAL = (196, 73, 58)
GOLD = (184, 138, 58)
OK = (42, 122, 75)
NAVY = (28, 49, 68)
CARD = (255, 255, 255)
LINE = (220, 214, 204)
SOFT = (237, 233, 224)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def new_canvas() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for i in range(0, W, 48):
        draw.line([(i, 0), (i, H)], fill=(236, 232, 224), width=1)
    for j in range(0, H, 48):
        draw.line([(0, j), (W, j)], fill=(236, 232, 224), width=1)
    return img


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    return int(draw.textlength(text, font=fnt))


def wrap(draw, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        buf = ""
        for ch in para:
            if draw.textlength(buf + ch, font=fnt) <= max_w:
                buf += ch
            else:
                if buf:
                    lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines


def draw_text(draw, xy, text, fnt, fill=INK, anchor="lt"):
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def shadow_rect(base, box, radius=18, pad=10):
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(layer)
    sd.rounded_rectangle((x0 + 4, y0 + 6, x1 + 4, y1 + 8), radius=radius, fill=(20, 24, 30, 28))
    blur = layer.filter(ImageFilter.GaussianBlur(8))
    base.alpha_composite(blur) if base.mode == "RGBA" else None
    # work on RGB: paste via mask
    if base.mode != "RGBA":
        tmp = base.convert("RGBA")
        tmp.alpha_composite(blur)
        base.paste(tmp.convert("RGB"))
        return
    base.alpha_composite(blur)


def card(img, box, fill=CARD, radius=18, outline=LINE, width=1, drop=True):
    if drop:
        shadow_rect(img, box, radius=radius)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw, xy, text, bg, fg=(255, 255, 255), fnt=None, pad_x=16, pad_y=7):
    fnt = fnt or font(16)
    tw = text_w(draw, text, fnt)
    th = 22
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    draw.rounded_rectangle(box, radius=16, fill=bg)
    draw.text((x + pad_x, y + pad_y + 1), text, font=fnt, fill=fg)
    return box


def header(img, kicker, title, claim=None):
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 8), fill=TEAL)
    draw_text(draw, (56, 28), kicker, font(18), TEAL)
    draw_text(draw, (56, 58), title, font(40), INK)
    if claim:
        draw_text(draw, (56, 114), claim, font(20), MUTED)
    draw.line([(56, 152), (W - 56, 152)], fill=LINE, width=1)


def footer(img, text):
    draw = ImageDraw.Draw(img)
    draw.line([(56, 1036), (W - 56, 1036)], fill=LINE, width=1)
    draw_text(draw, (56, 1050), text, font(15), MUTED)
    draw_text(draw, (W - 56, 1050), "推理SLO门禁网络  ·  对标TPN", font(15), TEAL, anchor="rt")


def arrow(draw, p1, p2, color=TEAL, width=3, head=12):
    draw.line([p1, p2], fill=color, width=width)
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    x, y = p2
    for da in (2.6, -2.6):
        draw.line(
            [(x, y), (x - head * math.cos(ang + da), y - head * math.sin(ang + da))],
            fill=color,
            width=width,
        )


def center_label(draw, box, lines, fnt, fill=INK):
    x0, y0, x1, y1 = box
    total = len(lines) * (fnt.size + 6)
    y = (y0 + y1 - total) / 2
    for line in lines:
        draw.text(((x0 + x1) / 2, y), line, font=fnt, fill=fill, anchor="mt")
        y += fnt.size + 6


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def slide_01():
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 18, H), fill=TEAL)
    draw_text(draw, (72, 86), "网络规划  ·  AI推理主场景", font(20), TEAL)
    draw_text(draw, (72, 140), "推理SLO门禁网络", font(72), INK)
    draw_text(draw, (72, 230), "横向端网协同  ×  纵向算网协同", font(32), TEAL_D)
    draw_text(
        draw,
        (72, 292),
        "业务调度之前结合SLO评估；判断达不成，则禁止调度。",
        font(24),
        MUTED,
    )

    items = [
        (TEAL, "横向", "端网协同", "主机网卡与织物共治\n流分类 / 遥测 / 硬隔离"),
        (NAVY, "纵向", "算网协同", "调度调用网络门禁\n放置 / 预算 / 亲和"),
        (CORAL, "兜底", "Fail-closed", "预测超预算即拒收\n保已准入请求的P99"),
    ]
    x = 72
    for color, tag, title, body in items:
        card(img, (x, 400, x + 560, 720), radius=22)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x, 400, x + 14, 720), radius=8, fill=color)
        pill(d, (x + 40, 430), tag, color)
        draw_text(d, (x + 40, 500), title, font(36), INK)
        y = 568
        for line in body.split("\n"):
            draw_text(d, (x + 40, y), line, font(20), MUTED)
            y += 36
        x += 590

    card(img, (72, 760, 1848, 980), fill=SOFT, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (104, 792), "对标TPN的领先点", font(20), TEAL)
    draw_text(
        d,
        (104, 836),
        "TPN公开的是织物相对数（2层 / 带宽+2.5x / 规模+10x / 时延-1/3）。本方案把TTFT、TPS等业务指标写成可执行合同，",
        font(20),
        INK,
    )
    draw_text(
        d,
        (104, 876),
        "把网络预算嵌进调度器：先评估，再放置；达不成就禁调。领先在闭环，不在口号。",
        font(20),
        INK,
    )
    pills = ["TTFT P99", "TPOT P99", "TPS", "Goodput"]
    px = 104
    for p in pills:
        box = pill(d, (px, 920), p, TEAL, fnt=font(16))
        px = box[2] + 16
    footer(img, "01  /  封面")
    return img


def slide_02():
    img = new_canvas()
    header(img, "01  对标判断", "领先点不在带宽数字，在调度闭环",
           "TPN把优化目标改成了Token，但公开材料停在L0织物；业务分位在PAI能看，还不能挡。")
    cols = [
        (TEAL, "TPN 公开能力", "L0  织物相对数", [
            "2层网络",
            "访问带宽 +2.5 倍",
            "规模 +10 倍",
            "时延降低 1/3",
            "命题：每Token性能与性价比",
        ], "无公开SLO、基线、测试方法"),
        (GOLD, "PAI 已落地", "L2  服务层观测", [
            "控制台 TTFT / TPOT / TPS",
            "压测报告可出分位",
            "Prometheus 可导出告警",
            "前缀路由间接降TTFT",
            "扩缩容仍看QPS/GPU",
        ], "能看，默认不禁调"),
        (CORAL, "公开缺口", "闭环还没接上", [
            "没有Token合同给网络",
            "没有 T_net 预算表",
            "调度不调用网络门禁",
            "多租隔离未与P99绑定",
            "无 Goodput=SLO内Token",
        ], "带宽翻倍，用户仍可能慢"),
    ]
    x = 56
    draw = ImageDraw.Draw(img)
    for color, title, sub, bullets, foot in cols:
        card(img, (x, 180, x + 580, 900), radius=20)
        d = ImageDraw.Draw(img)
        d.rectangle((x, 180, x + 580, 188), fill=color)
        draw_text(d, (x + 36, 214), title, font(28), INK)
        draw_text(d, (x + 36, 262), sub, font(18), color)
        y = 320
        for b in bullets:
            d.ellipse((x + 40, y + 8, x + 52, y + 20), fill=color)
            draw_text(d, (x + 68, y), b, font(20), INK)
            y += 52
        d.rounded_rectangle((x + 28, 800, x + 552, 872), radius=12, fill=SOFT)
        lines = wrap(d, foot, font(18), 500)
        ly = 818 if len(lines) == 1 else 808
        for line in lines:
            draw_text(d, (x + 48, ly), line, font(18), MUTED)
            ly += 28
        x += 604
    footer(img, "02  /  对标判断")
    return img


def slide_03():
    img = new_canvas()
    header(img, "02  总体架构", "一张网，两根轴",
           "横向把端和网收成一条控制面；纵向把算力调度和网络门禁收成一次决策。")

    # cross
    cx, cy = 960, 620
    draw = ImageDraw.Draw(img)
    draw.line([(220, cy), (1700, cy)], fill=TEAL, width=4)
    draw.line([(cx, 210), (cx, 980)], fill=NAVY, width=4)

    # axis labels
    draw_text(draw, (cx, 188), "纵向  ·  算网协同", font(22), NAVY, anchor="mm")
    draw_text(draw, (1720, cy), "横向  ·  端网协同", font(22), TEAL, anchor="lm")

    # center hub
    card(img, (cx - 170, cy - 70, cx + 170, cy + 70), fill=TEAL, outline=TEAL, drop=True)
    d = ImageDraw.Draw(img)
    draw_text(d, (cx, cy - 16), "SLO 门禁", font(28), (255, 255, 255), anchor="mm")
    draw_text(d, (cx, cy + 22), "评估 · 放置 · 禁调", font(16), (210, 232, 230), anchor="mm")

    quads = [
        (240, 210, 720, 520, NAVY, "上  业务与调度", [
            "SLO合同：TTFT / TPS / TPOT",
            "调度器先问门禁再放置",
            "超预算：换位或禁止调度",
        ]),
        (1200, 210, 1680, 520, NAVY, "上  网络控制面", [
            "切片带宽与队列水位",
            "路径/亲和/故障域视图",
            "预算剩余实时回传",
        ]),
        (240, 720, 720, 1000, TEAL, "下  端（主机/网卡）", [
            "KV / Decode / 存储 / BE 分流",
            "NIC QoS 保已准入流",
            "INT / ECN 上报预测器",
        ]),
        (1200, 720, 1680, 1000, TEAL, "下  网（交换机/织物）", [
            "出队列隔离，多租不互伤",
            "同ToR / 同平面优先",
            "故障时拒新保旧",
        ]),
    ]
    for x0, y0, x1, y1, color, title, bullets in quads:
        card(img, (x0, y0, x1, y1), radius=18)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x0, y0, x0 + 10, y1), radius=6, fill=color)
        draw_text(d, (x0 + 32, y0 + 22), title, font(20), color)
        y = y0 + 70
        for b in bullets:
            draw_text(d, (x0 + 32, y), b, font(18), INK)
            y += 36

    footer(img, "03  /  双轴架构")
    return img


def slide_04():
    img = new_canvas()
    header(img, "03  SLO合同", "先签合同，再把预算拆到网络",
           "网络只能兜 T_net。算力段、命中率、批大小买不回来，所以合同必须可分解。")

    metrics = [
        (TEAL, "TTFT P99", "体验", "首Token到达", "Queue + Prefill + KV搬运"),
        (NAVY, "TPOT P99", "流畅", "相邻Token间隔", "Decode + 批等待 + MoE"),
        (GOLD, "TPS", "产能", "每秒有效Token", "min(算力, 网络, KV槽)"),
        (OK, "Goodput", "合格产能", "SLO内Token/墙钟", "只计同时满足分位的量"),
    ]
    x = 56
    for color, name, kind, meaning, decomp in metrics:
        card(img, (x, 180, x + 440, 430), radius=18)
        d = ImageDraw.Draw(img)
        pill(d, (x + 24, 204), kind, color)
        draw_text(d, (x + 24, 268), name, font(28), INK)
        draw_text(d, (x + 24, 320), meaning, font(18), MUTED)
        draw_text(d, (x + 24, 364), decomp, font(17), INK)
        x += 464

    card(img, (56, 460, 1864, 1008), radius=20)
    d = ImageDraw.Draw(img)
    draw_text(d, (92, 492), "可执行分解（不用网络空载RTT代替业务分位）", font(22), TEAL)

    formulas = [
        "TTFT = T_queue + T_prefill(I, 1-H) + T_kv_load + T_kv_xfer",
        "TPS  = min(TPS_compute, TPS_net, TPS_kvslot)",
        "Budget_net_TTFT = SLO_ttft - T_queue_slo - T_prefill_est",
        "ADMIT  iff  TTFT_hat_P99 <= SLO  and  TPS_hat >= SLO  and  T_net <= Budget_net",
    ]
    y = 550
    for fml in formulas:
        d.rounded_rectangle((92, y, 1780, y + 70), radius=12, fill=SOFT)
        draw_text(d, (120, y + 18), fml, font(22), INK)
        y += 86

    draw_text(d, (92, 920), "H = 前缀命中率。命中足够高时，网络不应再是一阶项；未命中时，T_kv_xfer 必须有毫秒预算。", font(18), MUTED)
    footer(img, "04  /  SLO合同")
    return img


def slide_05():
    img = new_canvas()
    header(img, "04  核心机制", "调度之前先评估，达不成禁止调度",
           "门禁在业务调度之前，不在看板之后。Fail-closed：预测超预算就拒，不靠平均带宽掩盖尾部。")

    steps = [
        ("1", "到达", "请求 / 新副本 / 新租户"),
        ("2", "画像", "模型 · I/O · 并发 · 命中率"),
        ("3", "遥测", "队列 · 切片剩余 · 路径"),
        ("4", "预测", "TTFT / TPS / T_net P99"),
    ]
    x = 56
    draw = ImageDraw.Draw(img)
    for i, (n, title, body) in enumerate(steps):
        card(img, (x, 184, x + 390, 360), radius=16)
        d = ImageDraw.Draw(img)
        d.ellipse((x + 24, 208, x + 64, 248), fill=TEAL)
        draw_text(d, (x + 44, 228), n, font(20), (255, 255, 255), anchor="mm")
        draw_text(d, (x + 80, 214), title, font(26), INK)
        draw_text(d, (x + 28, 286), body, font(18), MUTED)
        if i < 3:
            arrow(d, (x + 398, 272), (x + 430, 272), TEAL, 4, 14)
        x += 464

    # three decisions
    decisions = [
        (OK, "ADMIT  放行", "T_net 与算力预算都够", [
            "按亲和位放置",
            "切片记账 +1",
            "进入硬隔离队列",
        ]),
        (GOLD, "REPLACE  换位", "本位置超预算，邻域够", [
            "优先同ToR / 同平面",
            "KV与Decode重亲和",
            "换完再评一次",
        ]),
        (CORAL, "REJECT  禁止调度", "任何位置都达不成SLO", [
            "不进入业务调度",
            "返回容量不足/换SLO档",
            "保已准入请求的P99",
        ]),
    ]
    x = 56
    for color, title, sub, bullets in decisions:
        card(img, (x, 400, x + 580, 860), radius=20, outline=color, width=2)
        d = ImageDraw.Draw(img)
        d.rectangle((x, 400, x + 580, 408), fill=color)
        draw_text(d, (x + 32, 432), title, font(28), color)
        draw_text(d, (x + 32, 486), sub, font(18), MUTED)
        y = 540
        for b in bullets:
            d.ellipse((x + 40, y + 8, x + 52, y + 20), fill=color)
            draw_text(d, (x + 68, y), b, font(20), INK)
            y += 56
        x += 604

    card(img, (56, 884, 1864, 1008), fill=SOFT, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (88, 910), "和TPN的本质差别", font(18), TEAL)
    draw_text(d, (88, 950), "TPN增强织物后，调度仍可把请求打上去；本方案调度器必须拿到 Admit 结果。没有放行令牌，业务层不得放置。", font(20), INK)
    footer(img, "05  /  调度前门禁")
    return img


def slide_06():
    img = new_canvas()
    header(img, "05  横向  ·  端网协同", "主机和织物共治同一条Token路径",
           "端负责分类与上报，网负责隔离与路径；预测器吃两端遥测，而不是只看空载RTT。")

    feats = [
        (TEAL, "01", "四类流硬分", "KV搬运  ·  Decode同步  ·  存储回源  ·  Best-effort",
         "不同队列、不同预算。训练AllReduce和BE打不满已准入的KV/Decode。",
         "端：DSCP/TC打标    网：PQ/切片入队"),
        (TEAL, "02", "端侧保已准入", "NIC QoS / 限速 / 喷洒窗口",
         "新流可降，已放行流的T_net P99优先。PCIe无GPU QoS时，在网卡做。",
         "端：已准入QP保速    网：超水位反压新流"),
        (NAVY, "03", "网侧硬隔离", "切片 + 出队列 + 同平面优先",
         "多租注入后，已准入TTFT P99漂移受合同约束，而不是“尽量公平”。",
         "端：按切片选路    网：出队列互不抢缓冲"),
        (NAVY, "04", "遥测回灌", "队列深度 / ECN / 重传 → 预测器",
         "门禁用的是实时水位，不是规划表。超水位先收口喷洒和KV并发。",
         "端：INT/ECN上报    网：队列水位进预测器"),
    ]
    positions = [(56, 180), (988, 180), (56, 590), (988, 590)]
    for (x, y), (color, n, title, sub, body, bar) in zip(positions, feats):
        card(img, (x, y, x + 876, y + 380), radius=20)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x + 28, y + 28, x + 88, y + 88), radius=14, fill=color)
        draw_text(d, (x + 58, y + 58), n, font(22), (255, 255, 255), anchor="mm")
        draw_text(d, (x + 112, y + 36), title, font(28), INK)
        draw_text(d, (x + 112, y + 84), sub, font(18), color)
        lines = wrap(d, body, font(20), 780)
        ly = y + 150
        for line in lines:
            draw_text(d, (x + 40, ly), line, font(20), MUTED)
            ly += 36
        d.rounded_rectangle((x + 28, y + 292, x + 848, y + 352), radius=12, fill=SOFT)
        draw_text(d, (x + 52, y + 310), bar, font(18), INK)
    footer(img, "06  /  横向端网协同")
    return img


def slide_07():
    img = new_canvas()
    header(img, "06  纵向  ·  算网协同", "调度器把网络门禁当成硬依赖",
           "GPU有空位不等于能调度。算力、缓存、网络预算三次都过，才放置。")

    # flow bar
    nodes = ["SLO档", "算力槽", "KV亲和", "网络预算", "放置"]
    x = 80
    draw = ImageDraw.Draw(img)
    for i, name in enumerate(nodes):
        box = (x, 184, x + 260, 280)
        fill = TEAL if i == 4 else CARD
        fg = (255, 255, 255) if i == 4 else INK
        card(img, box, fill=fill, outline=TEAL if i == 4 else LINE, drop=True)
        d = ImageDraw.Draw(img)
        draw_text(d, ((box[0] + box[2]) / 2, 232), name, font(24), fg, anchor="mm")
        if i < 4:
            arrow(d, (x + 268, 232), (x + 300, 232), TEAL, 4, 12)
        x += 360

    feats = [
        ("Admit API", "调度每次放置都调用。返回 ADMIT / REPLACE / REJECT，没有令牌不得下发。"),
        ("计算-KV亲和", "远端KV会撑爆TTFT预算时，禁止跨域放置，先同ToR，再同平面。"),
        ("PD配比受预算约束", "Prefill/Decode 扩容看 T_kv_xfer P99，不只看卡数配比。"),
        ("弹性也走门禁", "副本增加先问切片剩余。GPU利用率够、网络预算不够，仍禁扩。"),
        ("多档SLO", "交互档 / 批量档分合同。批量不得占交互切片。拒收优于混排降质。"),
        ("失败语义", "故障域收缩时拒新保旧，Goodput优先于平均TPS。"),
    ]
    x, y = 56, 330
    for i, (title, body) in enumerate(feats):
        if i == 3:
            x, y = 56, 680
        card(img, (x, y, x + 580, y + 300), radius=18)
        d = ImageDraw.Draw(img)
        draw_text(d, (x + 28, y + 28), title, font(24), TEAL)
        lines = wrap(d, body, font(18), 520)
        ly = y + 90
        for line in lines:
            draw_text(d, (x + 28, ly), line, font(18), INK)
            ly += 32
        x += 604
    footer(img, "07  /  纵向算网协同")
    return img


def slide_08():
    img = new_canvas()
    header(img, "07  业务指标兜底", "兜底=三道闸，不是事后解释",
           "网络不承诺替算力出Token；网络承诺：不把达不成的活放进去，放进去的活不被邻居打穿。")

    gates = [
        (CORAL, "闸1  准入", "预测失败 → 禁止调度", [
            "请求、扩容、新租户都过门禁",
            "输出拒绝原因：算力 / KV / 网络",
            "可改SLO档，不可 silently 降质",
            "验收：超预算请求不得进入运行队列",
        ], "挡在调度前"),
        (TEAL, "闸2  隔离", "已准入 P99 受保护", [
            "KV/Decode 与 BE/训练分队列",
            "多租注入后漂移写入合同",
            "超水位先限新流，不伤老流",
            "验收：打满BE后TTFT P99漂移可控",
        ], "挡在数据面"),
        (NAVY, "闸3  故障", "拒新保旧，Fail-closed", [
            "链路/ToR异常：收缩预算",
            "新请求REJECT，在途走完",
            "恢复后再开门，不做平均抹平",
            "验收：故障窗口Goodput优于平均TPS",
        ], "挡在控制面"),
    ]
    x = 56
    for color, title, sub, bullets, tag in gates:
        card(img, (x, 180, x + 580, 820), radius=20)
        d = ImageDraw.Draw(img)
        d.rectangle((x, 180, x + 580, 188), fill=color)
        pill(d, (x + 32, 220), tag, color)
        draw_text(d, (x + 32, 290), title, font(30), INK)
        draw_text(d, (x + 32, 350), sub, font(20), color)
        y = 430
        for b in bullets:
            d.ellipse((x + 40, y + 8, x + 52, y + 20), fill=color)
            lines = wrap(d, b, font(20), 480)
            for j, line in enumerate(lines):
                draw_text(d, (x + 68, y + j * 30), line, font(20), INK)
            y += 30 * len(lines) + 28
        x += 604

    card(img, (56, 848, 1864, 1008), fill=SOFT, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (88, 876), "一句话", font(18), TEAL)
    draw_text(d, (88, 920), "兜底不是“网络保证TPOT=20ms”。兜底是：达不成的不进门；进门的T_net P99有预算、有隔离、有故障语义。", font(22), INK)
    footer(img, "08  /  三道闸")
    return img


def slide_09():
    img = new_canvas()
    header(img, "08  对比与验收", "用可证伪的表，对标TPN公开能力",
           "不发明TPN的SLA。只对比它已经公开的东西，和本方案必须交出来的东西。")

    rows = [
        ("优化目标", "每Token性能与性价比（命题）", "可执行Token SLO合同"),
        ("量化形态", "2层 / +2.5x / +10x / 时延-1/3", "TTFT/TPS P99 + T_net预算"),
        ("与调度关系", "织物增强，调度自行放置", "调度前评估，可禁止调度"),
        ("测量闭环", "无公开归因到Token分位", "引擎stage对齐网络切片"),
        ("多租语义", "未与业务P99绑定", "隔离闸 + 漂移合同"),
        ("失败语义", "规模与自愈（HPN侧）", "拒新保旧，Goodput优先"),
    ]
    # table header
    card(img, (56, 176, 1864, 248), fill=TEAL, outline=TEAL, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (80, 212), "维度", font(20), (255, 255, 255), anchor="lm")
    draw_text(d, (420, 212), "TPN 公开材料", font(20), (255, 255, 255), anchor="lm")
    draw_text(d, (1120, 212), "本方案必须交付", font(20), (255, 255, 255), anchor="lm")

    y = 256
    for i, (a, b, c) in enumerate(rows):
        fill = CARD if i % 2 == 0 else SOFT
        card(img, (56, y, 1864, y + 72), fill=fill, outline=LINE, drop=False)
        d = ImageDraw.Draw(img)
        draw_text(d, (80, y + 36), a, font(18), TEAL, anchor="lm")
        draw_text(d, (420, y + 36), b, font(18), INK, anchor="lm")
        draw_text(d, (1120, y + 36), c, font(18), INK, anchor="lm")
        y += 72

    # acceptance
    acc = [
        ("验收1  隔离", "多租打满BE后，已准入TTFT P99漂移受合同约束。",
         "测法：固定画像，注入训练/BE流，看受害租户分位。"),
        ("验收2  门禁", "超预算请求必须拒绝；误伤率与漏放率可测。",
         "测法：构造临界负载，统计该拒未拒 / 该放未放。"),
        ("验收3  产能", "Goodput（SLO内Token）优于同规格best-effort。",
         "测法：同样卡数与流量，比合格Token/墙钟，不比平均TPS。"),
    ]
    x = 56
    for tag, text, how in acc:
        card(img, (x, 720, x + 580, 1008), radius=16)
        d = ImageDraw.Draw(img)
        pill(d, (x + 24, 748), tag, TEAL)
        lines = wrap(d, text, font(20), 500)
        ly = 812
        for line in lines:
            draw_text(d, (x + 28, ly), line, font(20), INK)
            ly += 32
        d.rounded_rectangle((x + 24, 912, x + 556, 980), radius=10, fill=SOFT)
        hlines = wrap(d, how, font(16), 500)
        hy = 926
        for line in hlines:
            draw_text(d, (x + 40, hy), line, font(16), MUTED)
            hy += 24
        x += 604
    footer(img, "09  /  对比与验收")
    return img


def slide_10():
    img = new_canvas()
    header(img, "09  关键特征一览", "规划要能落地，特征必须可检查",
           "评审时只问六件事：有没有合同、门禁、隔离、亲和、遥测、验收。")

    feats = [
        ("F1  SLO合同", "TTFT / TPOT / TPS / Goodput 分位可写进档位",
         "检查：有没有书面档位和基线画像"),
        ("F2  调度前门禁", "ADMIT / REPLACE / REJECT，无令牌不得放置",
         "检查：调度路径上有没有硬依赖API"),
        ("F3  预算分解", "T_net 从TTFT里拆出毫秒账，不拿空载RTT充数",
         "检查：引擎stage能否对上网络切片"),
        ("F4  端网共治", "四类流 + NIC QoS + 切片队列 + 遥测回灌",
         "检查：KV/Decode是否与BE分队列"),
        ("F5  算网共治", "Admit API、KV亲和、PD/弹性都受预算约束",
         "检查：GPU有空位但超预算时会不会禁扩"),
        ("F6  三道闸兜底", "准入挡调度，隔离挡数据面，故障拒新保旧",
         "检查：故障时是拒新，还是继续灌流"),
    ]
    x, y = 56, 180
    for i, (title, body, chk) in enumerate(feats):
        if i == 3:
            x, y = 56, 560
        card(img, (x, y, x + 580, y + 340), radius=18)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x + 24, y + 24, x + 88, y + 88), radius=14, fill=TEAL)
        draw_text(d, (x + 56, y + 56), f"{i+1:02d}", font(20), (255, 255, 255), anchor="mm")
        draw_text(d, (x + 108, y + 40), title, font(24), INK)
        lines = wrap(d, body, font(20), 500)
        ly = y + 120
        for line in lines:
            draw_text(d, (x + 32, ly), line, font(20), MUTED)
            ly += 36
        d.rounded_rectangle((x + 24, y + 250, x + 556, y + 312), radius=12, fill=SOFT)
        draw_text(d, (x + 40, y + 270), chk, font(17), INK)
        x += 604

    footer(img, "10  /  关键特征")
    return img


SLIDES = [
    ("01-cover", slide_01),
    ("02-gap", slide_02),
    ("03-architecture", slide_03),
    ("04-slo-contract", slide_04),
    ("05-admission-gate", slide_05),
    ("06-horizontal", slide_06),
    ("07-vertical", slide_07),
    ("08-safety-net", slide_08),
    ("09-vs-tpn", slide_09),
    ("10-features", slide_10),
]


def pack_pptx(paths):
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for p in paths:
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(str(p), Emu(0), Emu(0), prs.slide_width, prs.slide_height)
    out = OUT / "slo-gated-inference-network.pptx"
    prs.save(out)
    return out


def main():
    SLIDE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, fn in SLIDES:
        img = fn()
        path = SLIDE_DIR / f"{name}.png"
        img.save(path, "PNG", optimize=True)
        paths.append(path)
        print("wrote", path)
    pptx = pack_pptx(paths)
    print("pptx", pptx)


if __name__ == "__main__":
    main()
