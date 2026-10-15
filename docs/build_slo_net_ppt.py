#!/usr/bin/env python3
"""Executive planning deck: SLO-gated inference network vs TPN."""

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


def shadow_rect(base, box, radius=18):
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(layer)
    sd.rounded_rectangle((x0 + 4, y0 + 6, x1 + 4, y1 + 8), radius=radius, fill=(20, 24, 30, 28))
    blur = layer.filter(ImageFilter.GaussianBlur(8))
    tmp = base.convert("RGBA")
    tmp.alpha_composite(blur)
    base.paste(tmp.convert("RGB"))


def card(img, box, fill=CARD, radius=18, outline=LINE, width=1, drop=True):
    if drop:
        shadow_rect(img, box, radius=radius)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw, xy, text, bg, fg=(255, 255, 255), fnt=None, pad_x=16, pad_y=7):
    fnt = fnt or font(16)
    tw = text_w(draw, text, fnt)
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + 22 + pad_y * 2)
    draw.rounded_rectangle(box, radius=16, fill=bg)
    draw.text((x + pad_x, y + pad_y + 1), text, font=fnt, fill=fg)
    return box


def header(img, kicker, title, claim=None):
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 8), fill=TEAL)
    draw_text(draw, (56, 26), kicker, font(18), TEAL)
    # title may wrap once
    tfont = font(36) if len(title) > 22 else font(40)
    draw_text(draw, (56, 56), title, tfont, INK)
    if claim:
        draw_text(draw, (56, 114), claim, font(20), MUTED)
    draw.line([(56, 152), (W - 56, 152)], fill=LINE, width=1)


def footer(img, text):
    draw = ImageDraw.Draw(img)
    draw.line([(56, 1036), (W - 56, 1036)], fill=LINE, width=1)
    draw_text(draw, (56, 1050), text, font(15), MUTED)
    draw_text(draw, (W - 56, 1050), "投资汇报  ·  推理网络规划", font(15), TEAL, anchor="rt")


def so_bar(img, box, label, text, color=TEAL):
    card(img, box, fill=SOFT, drop=False, outline=LINE)
    d = ImageDraw.Draw(img)
    pill(d, (box[0] + 24, box[1] + 18), label, color)
    lines = wrap(d, text, font(22), box[2] - box[0] - 200)
    y = box[1] + 22
    for line in lines:
        draw_text(d, (box[0] + 160, y), line, font(22), INK)
        y += 34


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


# ---------------------------------------------------------------------------
# Slides — one viewpoint each
# ---------------------------------------------------------------------------

def slide_01():
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 18, H), fill=TEAL)
    draw_text(draw, (72, 70), "给决策层的一页判断", font(20), TEAL)
    draw_text(draw, (72, 118), "让网络对推理体验负责", font(64), INK)
    draw_text(draw, (72, 214), "先评估，再接单；达不到指标，禁止调度。", font(30), TEAL_D)
    draw_text(
        draw,
        (72, 274),
        "投资买的不是更大的带宽数字，而是：谁有权决定这单接还是不接。",
        font(22),
        MUTED,
    )

    items = [
        (TEAL, "判断", "体验已经按 Token 计价", "用户为快和稳付钱。\n网络若只报带宽，就是错配。"),
        (NAVY, "主张", "达不成的单，不准进门", "有卡也不滥接。\n先保正在服务的用户。"),
        (CORAL, "回报", "买决策权，不是买口号", "合格产能上升，\n空等和返工下降。"),
    ]
    x = 72
    for color, tag, title, body in items:
        card(img, (x, 370, x + 560, 720), radius=22)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x, 370, x + 14, 720), radius=8, fill=color)
        pill(d, (x + 40, 400), tag, color)
        draw_text(d, (x + 40, 470), title, font(28), INK)
        y = 540
        for line in body.split("\n"):
            draw_text(d, (x + 40, y), line, font(20), MUTED)
            y += 40
        x += 590

    card(img, (72, 760, 1848, 990), fill=SOFT, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (104, 792), "汇报逻辑", font(18), TEAL)
    draw_text(d, (104, 836), "错配 → 对手只换了名字 → 我们的主张（禁调）→ 两根轴怎么支撑 → 四笔价值账 → 投什么、怎么验收", font(22), INK)
    pills = ["主场景：AI推理", "指标：TTFT / TPS", "对标：阿里云TPN"]
    px = 104
    for p in pills:
        box = pill(d, (px, 910), p, TEAL)
        px = box[2] + 14
    footer(img, "01  /  开场判断")
    return img


def slide_02():
    img = new_canvas()
    header(
        img,
        "观点 1  ·  为什么现在投",
        "推理已经按 Token 赚钱，网络还按带宽汇报",
        "这是错配。错配的投资，用户无感，利润讲不清。",
    )
    left = [
        ("业务真正问的", TEAL, [
            "快不快：用户多久看到第一个字",
            "稳不稳：会不会越说越卡",
            "贵不贵：每个合格结果花多少钱",
        ]),
    ]
    right = [
        ("网络常常答的", CORAL, [
            "带宽又翻了一倍",
            "集群又能多接多少卡",
            "空载时延又降了一截",
        ]),
    ]
    card(img, (56, 180, 920, 780), radius=20)
    d = ImageDraw.Draw(img)
    pill(d, (92, 212), "业务真正问的", TEAL)
    qs = [
        ("快不快", "用户多久看到第一个字（TTFT）"),
        ("稳不稳", "会不会越说越卡（TPS/流畅）"),
        ("贵不贵", "每个合格结果花多少钱"),
    ]
    y = 300
    for t, b in qs:
        d.rounded_rectangle((92, y, 880, y + 120), radius=14, fill=SOFT)
        draw_text(d, (120, y + 24), t, font(26), TEAL)
        draw_text(d, (120, y + 68), b, font(20), INK)
        y += 140

    card(img, (980, 180, 1864, 780), radius=20)
    d = ImageDraw.Draw(img)
    pill(d, (1016, 212), "网络常常答的", CORAL)
    qs = [
        ("带宽", "链路更粗了，账单更大了"),
        ("规模", "能堆更多卡，不代表单更稳"),
        ("空载时延", "没人的时候很快，忙起来另说"),
    ]
    y = 300
    for t, b in qs:
        d.rounded_rectangle((1016, y, 1828, y + 120), radius=14, fill=SOFT)
        draw_text(d, (1044, y + 24), t, font(26), CORAL)
        draw_text(d, (1044, y + 68), b, font(20), INK)
        y += 140

    so_bar(
        img,
        (56, 812, 1864, 1008),
        "所以",
        "谁掌握 Token 体验，谁掌握推理利润。网络若不改汇报口径，投资就会买错东西。",
    )
    footer(img, "02  /  观点一")
    return img


def slide_03():
    img = new_canvas()
    header(
        img,
        "观点 2  ·  对手证明了什么",
        "TPN 说对了方向，还没有交出合同",
        "尊重对手的命名。投资要问：名字换了之后，谁对体验负责？",
    )
    cols = [
        (OK, "他们做对的", [
            "承认第一目标不再是训练不掉速",
            "把叙事改成每 Token 的性能和成本",
            "证明行业共识已经转向推理",
        ], "方向对，值得对标"),
        (GOLD, "他们公开交出的", [
            "两层网络",
            "带宽 +2.5 倍、规模 +10 倍",
            "时延降低约 1/3",
        ], "织物相对数，没有业务合同"),
        (CORAL, "他们没交出的", [
            "体验不达标时，能不能拒单",
            "多租互抢时，谁的体验优先",
            "这组数字对应哪一档用户体感",
        ], "决策权还在调度，网络仍是配角"),
    ]
    x = 56
    for color, title, bullets, foot in cols:
        card(img, (x, 180, x + 580, 780), radius=20)
        d = ImageDraw.Draw(img)
        d.rectangle((x, 180, x + 580, 188), fill=color)
        draw_text(d, (x + 36, 220), title, font(28), INK)
        y = 300
        for b in bullets:
            d.ellipse((x + 44, y + 10, x + 56, y + 22), fill=color)
            lines = wrap(d, b, font(20), 480)
            for i, line in enumerate(lines):
                draw_text(d, (x + 72, y + i * 32), line, font(20), INK)
            y += 32 * len(lines) + 28
        d.rounded_rectangle((x + 28, 660, x + 552, 748), radius=12, fill=SOFT)
        lines = wrap(d, foot, font(18), 500)
        ly = 684 if len(lines) == 1 else 672
        for line in lines:
            draw_text(d, (x + 48, ly), line, font(18), MUTED)
            ly += 28
        x += 604
    so_bar(
        img,
        (56, 812, 1864, 1008),
        "判断",
        "TPN 是正确的行业信号，不是可签的体验合同。领先点必须落在“有权不接单”，而不是再报一版相对数。",
    )
    footer(img, "03  /  观点二")
    return img


def slide_04():
    img = new_canvas()
    header(
        img,
        "观点 3  ·  为什么带宽故事不够",
        "带宽翻倍，用户仍可能觉得慢",
        "一次推理不是一条空管子。投资如果只买管子，买不到体验。",
    )
    stages = [
        (NAVY, "1  排队", "前面的人没走完\n再快的路也等"),
        (TEAL, "2  计算", "模型在算\n网络再强也替不了"),
        (GOLD, "3  搬运", "缓存要从别处搬来\n这才是网络的责任"),
    ]
    x = 56
    d = ImageDraw.Draw(img)
    for i, (color, title, body) in enumerate(stages):
        card(img, (x, 184, x + 520, 520), radius=20)
        dd = ImageDraw.Draw(img)
        dd.rectangle((x, 184, x + 520, 192), fill=color)
        draw_text(dd, (x + 36, 220), title, font(30), INK)
        y = 320
        for line in body.split("\n"):
            draw_text(dd, (x + 36, y), line, font(22), MUTED)
            y += 44
        if i < 2:
            arrow(dd, (x + 528, 350), (x + 568, 350), TEAL, 5, 16)
        x += 604

    card(img, (56, 556, 1864, 780), radius=18)
    d = ImageDraw.Draw(img)
    draw_text(d, (92, 588), "给投资人的分解", font(20), TEAL)
    draw_text(d, (92, 640), "用户体验  =  排队  +  计算  +  搬运", font(28), INK)
    draw_text(d, (92, 700), "缓存经常命中，网络不该是瓶颈；一旦没命中，搬运快慢就是体验本身。不拆开，就会把计算的问题误投成网络。", font(20), MUTED)

    so_bar(
        img,
        (56, 812, 1864, 1008),
        "所以",
        "我们不投“全网再快一截”。我们投：能事先判断这单会不会在搬运上翻车，翻车就不接。",
    )
    footer(img, "04  /  观点三")
    return img


def slide_05():
    img = new_canvas()
    header(
        img,
        "主张  ·  核心机制只讲这一件",
        "达不成的单，不准进门",
        "兜底不是保证每一次都快。兜底是：预测达不到，就禁止调度。",
    )
    # restaurant analogy strip
    card(img, (56, 176, 1864, 300), fill=SOFT, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (88, 198), "一个能听懂的类比", font(18), TEAL)
    draw_text(d, (88, 238), "餐厅座位空着，也不该再接做不完的菜。滥接的结果是：所有客人一起变慢，口碑和翻台一起坏。", font(22), INK)

    decisions = [
        (OK, "接", "这单在红线内", "放进正在服务的队列\n网络给它让路"),
        (GOLD, "换", "这里不行，旁边行", "换到更近的位置再评\n能近就不要远搬"),
        (CORAL, "拒", "哪里都达不到", "禁止调度\n保住已经在吃的客人"),
    ]
    x = 56
    for color, title, sub, body in decisions:
        card(img, (x, 328, x + 580, 780), radius=20, outline=color, width=2)
        d = ImageDraw.Draw(img)
        d.rectangle((x, 328, x + 580, 336), fill=color)
        draw_text(d, (x + 36, 368), title, font(40), color)
        draw_text(d, (x + 36, 440), sub, font(22), MUTED)
        y = 520
        for line in body.split("\n"):
            draw_text(d, (x + 36, y), line, font(22), INK)
            y += 44
        x += 604

    so_bar(
        img,
        (56, 812, 1864, 1008),
        "投资含义",
        "我们买的是拒单权。没有这把刀，带宽投得再多，忙的时候仍然大家一起慢。",
    )
    footer(img, "05  /  主张")
    return img


def slide_06():
    img = new_canvas()
    header(
        img,
        "支撑 1  ·  横向端网协同",
        "端和网必须对同一条用户路径负责",
        "不是两拨人各报各的数。用户慢了，两端要能一起说清楚、一起收口。",
    )
    feats = [
        (TEAL, "分清谁优先", "正在对话的人，优先于后台搬运和占便宜的流量。", "价值：忙的时候体验不塌"),
        (NAVY, "路上不互抢", "多租共用集群，但不能互相拖慢已经接进来的单。", "价值：提高复用，不牺牲口碑"),
        (GOLD, "堵了先限新的", "路一开始堵，先停新单，不去挤正在服务的人。", "价值：故障时亏小、不亏口碑"),
        (CORAL, "两边看同一张表", "入口和路上报的是同一套体验红线，不是各说各话。", "价值：出问题能问责，能停投"),
    ]
    x, y0 = 56, 180
    for i, (color, title, body, val) in enumerate(feats):
        if i == 2:
            x, y0 = 56, 560
        card(img, (x, y0, x + 876, y0 + 340), radius=20)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x + 28, y0 + 28, x + 16 + 28, y0 + 312), radius=8, fill=color)
        draw_text(d, (x + 72, y0 + 36), title, font(28), INK)
        lines = wrap(d, body, font(22), 740)
        ly = y0 + 110
        for line in lines:
            draw_text(d, (x + 72, ly), line, font(22), MUTED)
            ly += 36
        d.rounded_rectangle((x + 72, y0 + 240, x + 840, y0 + 308), radius=12, fill=SOFT)
        draw_text(d, (x + 96, y0 + 260), val, font(20), color)
        x += 904
    footer(img, "06  /  横向")
    return img


def slide_07():
    img = new_canvas()
    header(
        img,
        "支撑 2  ·  纵向算网协同",
        "有卡，不等于能接单",
        "算力空着也在烧钱。调度先问：这单会不会把体验红线打穿。",
    )
    chain = ["看档位", "看卡", "看数据在不在旁边", "看路还堵不堵", "才接单"]
    x = 56
    for i, name in enumerate(chain):
        fill = TEAL if i == 4 else CARD
        fg = (255, 255, 255) if i == 4 else INK
        card(img, (x, 184, x + 300, 300), fill=fill, outline=TEAL if i == 4 else LINE)
        d = ImageDraw.Draw(img)
        draw_text(d, (x + 150, 242), name, font(22), fg, anchor="mm")
        if i < 4:
            arrow(d, (x + 308, 242), (x + 348, 242), TEAL, 4, 12)
        x += 372

    cards = [
        ("调度先问网络", "卡有空位，只是必要条件。问不清会不会超时，就不能下发。"),
        ("数据靠近计算", "能在旁边取到缓存，就不要跨很远去搬。搬得动，才叫能接。"),
        ("扩容也要过门", "多加几张卡，路不够，照样拒。避免越扩越慢。"),
    ]
    x = 56
    for title, body in cards:
        card(img, (x, 340, x + 580, 760), radius=20)
        d = ImageDraw.Draw(img)
        draw_text(d, (x + 36, 380), title, font(28), TEAL)
        lines = wrap(d, body, font(22), 500)
        ly = 470
        for line in lines:
            draw_text(d, (x + 36, ly), line, font(22), INK)
            ly += 40
        x += 604

    so_bar(
        img,
        (56, 792, 1864, 1008),
        "价值",
        "少做“卡在空转、人在等待”的无效产能。投资从买卡，变成买接得住的单。",
    )
    footer(img, "07  /  纵向")
    return img


def slide_08():
    img = new_canvas()
    header(
        img,
        "价值  ·  投资买到什么",
        "四笔账，比再快一截带宽更好讲",
        "说服投资，靠的是体验、合格产能、成本和风险，不是协议名词。",
    )
    vals = [
        (TEAL, "体验", "接进来的用户，不被挤慢", "首字和流畅有红线。\n达不到的单不进门。"),
        (NAVY, "产能", "数合格的 Token，不数虚高吞吐", "只统计红线内的产出。\n忙时宁少接，不少合格。"),
        (GOLD, "成本", "少买空等的卡", "卡在等数据，电表照走。\n拒单比空等便宜。"),
        (CORAL, "风险", "验收失败可以停", "三条测法事先写死。\n讲不清价值，就不要加码。"),
    ]
    x = 56
    for color, title, sub, body in vals:
        card(img, (x, 180, x + 440, 760), radius=20)
        d = ImageDraw.Draw(img)
        d.rectangle((x, 180, x + 440, 188), fill=color)
        draw_text(d, (x + 28, 220), title, font(32), color)
        lines = wrap(d, sub, font(22), 380)
        ly = 300
        for line in lines:
            draw_text(d, (x + 28, ly), line, font(22), INK)
            ly += 36
        d.rounded_rectangle((x + 24, 500, x + 416, 720), radius=14, fill=SOFT)
        ly = 530
        for line in body.split("\n"):
            draw_text(d, (x + 44, ly), line, font(20), MUTED)
            ly += 44
        x += 464

    so_bar(
        img,
        (56, 792, 1864, 1008),
        "一句话",
        "这轮投资的回报，是少接烂单、多出合格结果、少养空转的卡。",
    )
    footer(img, "08  /  价值账")
    return img


def slide_09():
    img = new_canvas()
    header(
        img,
        "对标  ·  给投资人看的差",
        "他们增强路，我们决定谁可以上路",
        "不发明对手的承诺。只对比：公开材料里有什么，我们必须交出什么。",
    )
    rows = [
        ("目标", "把故事改成 Token", "把 Token 体验写成可执行红线"),
        ("数字", "路更宽、更大、空载更快", "忙的时候，达标单能不能保住"),
        ("权力", "调度自己决定接不接", "网络有权说：这单不准进"),
        ("忙时", "大家一起挤", "新单让路，老单受保护"),
        ("失败", "事后解释为什么慢", "事先拒单，验收可以停投"),
        ("问责", "数字对不上体验，难追责", "红线、拒单、测法三条对齐"),
    ]
    card(img, (56, 176, 1864, 248), fill=TEAL, outline=TEAL, drop=False)
    d = ImageDraw.Draw(img)
    draw_text(d, (90, 212), "看什么", font(20), (255, 255, 255), anchor="lm")
    draw_text(d, (420, 212), "TPN 公开材料", font(20), (255, 255, 255), anchor="lm")
    draw_text(d, (1120, 212), "本方案必须交给投资人", font(20), (255, 255, 255), anchor="lm")
    y = 256
    for i, (a, b, c) in enumerate(rows):
        fill = CARD if i % 2 == 0 else SOFT
        card(img, (56, y, 1864, y + 78), fill=fill, outline=LINE, drop=False)
        d = ImageDraw.Draw(img)
        draw_text(d, (90, y + 39), a, font(20), TEAL, anchor="lm")
        draw_text(d, (420, y + 39), b, font(20), INK, anchor="lm")
        draw_text(d, (1120, y + 39), c, font(20), INK, anchor="lm")
        y += 78

    so_bar(
        img,
        (56, 812, 1864, 1008),
        "结论",
        "相对 TPN 的领先，不在再报一版 +2.5 倍。在于：忙的时候我们有权不接，并且接进来的体验讲得清。",
    )
    footer(img, "09  /  对标")
    return img


def slide_10():
    img = new_canvas()
    header(
        img,
        "收口  ·  请投资人拍的三件事",
        "先买决策权，再买规模",
        "规模可以后加。没有拒单权和验收，先扩就是先买风险。",
    )
    asks = [
        (TEAL, "拍 1", "立红线", "为交互推理写下：首字多慢算失败、每秒多少合格结果算达标。", "没有红线，后面都是口号。"),
        (NAVY, "拍 2", "把门禁嵌进调度", "调度上线前必须经过评估：接 / 换 / 拒。没有令牌，不准接单。", "这是相对 TPN 的真正差别。"),
        (CORAL, "拍 3", "用三条测法卡投资", "忙时老用户会不会被挤慢；该拒的拒了没有；合格产能有没有比乱接更高。", "测不过，停加码。"),
    ]
    x = 56
    for color, n, title, body, foot in asks:
        card(img, (x, 180, x + 580, 780), radius=20)
        d = ImageDraw.Draw(img)
        pill(d, (x + 32, 212), n, color)
        draw_text(d, (x + 32, 290), title, font(32), INK)
        lines = wrap(d, body, font(22), 500)
        ly = 380
        for line in lines:
            draw_text(d, (x + 32, ly), line, font(22), MUTED)
            ly += 38
        d.rounded_rectangle((x + 28, 640, x + 552, 744), radius=12, fill=SOFT)
        lines = wrap(d, foot, font(20), 500)
        ly = 668 if len(lines) == 1 else 656
        for line in lines:
            draw_text(d, (x + 48, ly), line, font(20), color)
            ly += 30
        x += 604

    so_bar(
        img,
        (56, 812, 1864, 1008),
        "请决策",
        "批准的是一条原则：达不到体验红线的推理单，禁止调度。原则过了，再谈扩多少。",
    )
    footer(img, "10  /  决策")
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
