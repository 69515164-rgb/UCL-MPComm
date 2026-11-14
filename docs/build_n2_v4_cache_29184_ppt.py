#!/usr/bin/env python3
"""N+2 20T V4, TP=1, throughput-optimal under the latency caps.

A node is 2 CPUs x 4 GPUs. Each GPU has a 1.6 Tb/s unidirectional H2D
link. Each CPU has 2 TB/s and 2 TB of DDR, shared by its 4 GPUs.
Usable H2D is 80% of the line rate, 160 GB/s, which is below the
500 GB/s DDR share, so host reads move at 160 GB/s. The per-GPU share
of the 2 TB is 500 GB.

The in-network cache is 29184 GB at 51.2 Tb/s and has no second tier.
Three decode placements are compared: HBM only, HBM plus host DDR, and
HBM plus the cache. The batch is the one with the highest throughput
that still meets TTFT or TPOT. The KV model is the 20T V4 deck.
"""

from __future__ import annotations

import importlib.util
import math

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Inches

spec = importlib.util.spec_from_file_location(
    "slo_ui", "/agent/repos/ucl-mpcomm/docs/build_deepseek_20t_slo_ppt.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

vspec = importlib.util.spec_from_file_location(
    "v4", "/agent/repos/ucl-mpcomm/docs/build_n2_20t_notp_ppt.py"
)
v4 = importlib.util.module_from_spec(vspec)
vspec.loader.exec_module(v4)

H2D = 1.6e12 / 8 * 0.80
CPU_DDR_BW = 2e12
CPU_DDR_CAP = 2e12
GPUS_PER_CPU = 4
DDR_SHARE_BW = CPU_DDR_BW / GPUS_PER_CPU
HOST = min(H2D, DDR_SHARE_BW)
DDR_CAP = CPU_DDR_CAP / GPUS_PER_CPU
POOL_TOTAL = 29184e9
POOL_CAP = POOL_TOTAL / v4.N
POOL_BW = v4.POOL_51
TIE = 1e-4

SLIDES = 8
FOOTER = "N+2    ·    20T V4    ·    Prefill 64 卡 TP=1    ·    Decode DP=256 EP=256    ·    在网 cache 29184 GB    ·    无二级池"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY, TEAL = ui.NAVY, ui.TEAL
PPT = "/agent/repos/ucl-mpcomm/docs/N+2-20T-V4-在网cache.pptx"


def fmt_len(s):
    return v4.fmt_len(s)


def fmt_bs(n):
    return v4.fmt_bs(n)


def fmt_rate(v):
    return v4.fmt_rate(v)


def signed_pct(new, old):
    return v4.signed_pct(new, old)


def ms2(v):
    return v4.ms2(v)


def tps_d(bs, row):
    return bs / row["t"]


def tps_p(bs, s, row):
    return bs * s / row["t"]


def _keep(best, v, n, row):
    if best is None or v > best[0] * (1.0 + 1e-12):
        return (v, n, row)
    if v >= best[0] * (1.0 - TIE) and n > best[1]:
        return (v, n, row)
    return best


def best_decode(s, bw, cap, limit):
    store = v4.store_seq(s)
    n_fit = int(v4.ROOM_GPU // store)
    n_ext = int(cap // store) if cap else 0
    best = None
    last = None
    for n in range(1, n_fit + n_ext + 1):
        row = v4.decode(n * v4.DP, s, bw, cap, False)
        if row is None or row["t"] > limit + 1e-12:
            break
        last = (n, row)
        best = _keep(best, tps_d(n * v4.DP, row), n, row)
    return {"best": best, "last": last, "n_fit": n_fit}


def best_prefill(s, bw):
    store = v4.store_seq(s)
    n_fit = int(v4.PF_ROOM // store)
    best = None
    last = None
    for n in range(1, n_fit + 1):
        row = v4.prefill(n * v4.PF_DP, s, bw)
        if row["kv"] > v4.PF_ROOM + 1.0 or row["t"] > 10.0 + 1e-12:
            break
        last = (n, row)
        best = _keep(best, tps_p(n * v4.PF_DP, s, row), n, row)
    return {"best": best, "last": last, "n_fit": n_fit}


def why(found, limit):
    _v, n, row = found["best"]
    last_n = found["last"][0]
    if row.get("spill", 0.0) >= 0.01:
        return "溢出"
    if n >= found["n_fit"]:
        return "房间"
    if n < last_n and row["t"] < limit * 0.98:
        return "吞吐"
    return "时限"


def collect():
    rows = []
    for s in v4.LENGTHS:
        item = {"S": s}
        for key, bw in (("p25", v4.PREFIX_25), ("p100", v4.PREFIX_100)):
            item[key] = best_prefill(s, bw)
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            for key, bw, cap in (
                ("hbm", HOST, 0.0),
                ("ddr", HOST, DDR_CAP),
                ("cache", POOL_BW, POOL_CAP),
            ):
                item[f"{key}{tag}"] = best_decode(s, bw, cap, limit)
        rows.append(item)
    return {"rows": rows}


def pack(found):
    _v, n, row = found["best"]
    return n * v4.DP, row


def pack_pf(found):
    _v, n, row = found["best"]
    return n * v4.PF_DP, row


def pack_last(found):
    n, row = found["last"]
    return n * v4.DP, row


def margins(shape):
    for cell in shape.table.iter_cells():
        cell.margin_top = Inches(0.02)
        cell.margin_bottom = Inches(0.02)
        cell.margin_left = Inches(0.05)
        cell.margin_right = Inches(0.04)


def slide_open(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "吞吐最优点停在 KV 还在 HBM 里", "TTFT ≤ 10 秒    ·    TPOT ≤ 10 / 30 毫秒    ·    取系统吞吐最大的批")
    ui.banner(slide, 0.92, "基线 1 只用 GPU HBM。基线 2 再加每卡 500 GB 的 CPU DDR。在网 cache 一共 29184 GB，没有二级池。")
    r64, r4 = data["rows"][0], data["rows"][-1]
    head = ["约束", "64K 最优批", "64K 吞吐", "4M 最优批", "4M 吞吐", "4M cache 加满"]
    body = []
    for tag, label in (("10", "TPOT ≤ 10 毫秒"), ("30", "TPOT ≤ 30 毫秒")):
        b64, row64 = pack(r64[f"hbm{tag}"])
        b4, row4 = pack(r4[f"hbm{tag}"])
        c4, crow = pack_last(r4[f"cache{tag}"])
        body.append([
            label,
            fmt_bs(b64),
            fmt_rate(tps_d(b64, row64)),
            fmt_bs(b4),
            fmt_rate(tps_d(b4, row4)),
            f"{fmt_bs(c4)}\n{fmt_rate(tps_d(c4, crow))}",
        ])
    p64, prow = pack_pf(r64["p25"])
    p4, p4row = pack_pf(r4["p25"])
    body.insert(0, [
        "TTFT ≤ 10 秒，基线",
        fmt_bs(p64),
        fmt_rate(tps_p(p64, r64["S"], prow)),
        fmt_bs(p4),
        fmt_rate(tps_p(p4, r4["S"], p4row)),
        "Prefill 不走这档池",
    ])
    ui.add_table(
        slide, 0.42, 1.50,
        [2.15, 1.70, 1.70, 1.70, 1.70, 2.55],
        [head] + body,
        [0.40, 0.62, 0.62, 0.62],
        ["head", "key", "body", "body"],
        size=14,
    )
    b30, row30 = pack(r64["hbm30"])
    c30, crow = pack_last(r64["cache30"])
    ui.gold(
        slide,
        4.05,
        2.85,
        f"64K 的 10 毫秒停在时限上，批 {fmt_bs(pack(r64['hbm10'])[0])}，TPOT {ms2(pack(r64['hbm10'])[1]['t'])} 毫秒，HBM 还没满。\n"
        f"64K 的 30 毫秒在批 {fmt_bs(b30)}、TPOT {ms2(row30['t'])} 毫秒处吞吐最高。再加到 cache 上限 {fmt_bs(c30)}，"
        f"吞吐从 {fmt_rate(tps_d(b30, row30))} 降到 {fmt_rate(tps_d(c30, crow))}。\n"
        "128K 和 256K 的 cache 比 HBM 多 256 条全局批，吞吐高不到 0.2%。其余档三路是同一批，TPOT 5.69 到 7.63 毫秒。\n"
        "再把溢出放进 CPU DDR 或在网 cache，稀疏读的换入把步时拉长，系统吞吐下降。七档在第 6、7、8 页。",
        15,
    )


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "只把路由专家从 384 加到 4951", "1.6T V4-Pro    ·    外推到 20T    ·    层和隐藏不动")
    ui.banner(slide, 0.92, "层数、隐藏、中间维、TopK 不动。KV 仍是 30 层 CSA 加 31 层 HCA，压缩比 4 和 128。")
    head = ["项目", "1.6T 论文", "20T 外推"]
    body = [
        ["总参数", "1.600×10^12", f"{v4.TOTAL/1e12:.4f}×10^12"],
        ["路由专家", "384", f"{v4.E}"],
        ["层 / 隐藏 / 中间维", "61 / 7168 / 3072", "保持不动"],
        ["TopK / 激活", "6 路由 + 1 共享，4.9×10^10", "仍是 4.9×10^10"],
        ["注意力", "30 CSA + 31 HCA", "压缩比 4 和 128 不动"],
        ["每 token KV", "4939.5 字节 + 滑窗", "同一条式子"],
        ["FP4 专家表", f"{384 * v4.W_ONE * 0.5 / 1e12:.3f} TB", f"{v4.ROUTED / 1e12:.3f} TB"],
        ["Decode 每卡 KV 房间", "640 GB 扣权重和预留", f"{v4.ROOM_GPU/1e9:.2f} GB"],
    ]
    kinds = ["head"] + ["key" if i in (1, 5) else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.48, [2.90, 4.50, 5.10], [head] + body, [0.32] + [0.46] * 8, kinds, size=14)
    ui.gold(
        slide,
        5.70,
        1.20,
        f"K(S) = 4939.5×S + 4,497,408。1M 一条 {v4.store_seq(1048576)/1e9:.3f} GB，4M 一条 {v4.store_seq(4194304)/1e9:.3f} GB。\n"
        "一条序列的 KV 整段落在一张卡上。房间装不下的部分才进 CPU DDR 或在网 cache。",
        14,
    )


def slide_cluster(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "一节点两个 CPU，各接四张 GPU", "H2D 单向 1.6 Tb/s    ·    在网 cache 29184 GB    ·    无二级池")
    ui.banner(slide, 0.92, "4 张卡同时读这颗 CPU 的 DDR。H2D 比 DDR 分到的带宽窄，换入按 H2D。")
    head = ["项目", "配置"]
    body = [
        ["节点", "2 个 CPU，各有 4 对 H2D，对接 4 张 GPU"],
        ["H2D", f"每卡单向 1.6 Tb/s，沿用全篇 80%，可用 {H2D/1e9:.0f} GB/s"],
        ["CPU DDR", f"每颗 CPU {CPU_DDR_BW/1e12:.0f} TB/s、{CPU_DDR_CAP/1e12:.0f} TB。4 卡分得 {DDR_SHARE_BW/1e9:.0f} GB/s、{DDR_CAP/1e9:.0f} GB"],
        ["基线 2 的换入", f"min({H2D/1e9:.0f}, {DDR_SHARE_BW/1e9:.0f}) = {HOST/1e9:.0f} GB/s。每卡最多再放 {DDR_CAP/1e9:.0f} GB"],
        ["基线 1", f"只用 GPU HBM。每卡 KV 房间 {v4.ROOM_GPU/1e9:.2f} GB，溢出的批不要"],
        ["在网 cache", f"合计 {POOL_TOTAL/1e9:.0f} GB，256 卡每卡 {POOL_CAP/1e9:.0f} GB。带宽 {POOL_BW/1e12:.2f} TB/s。没有二级 DDR 池"],
        ["寻优", "时限以内取系统吞吐最大的批。批更大但步时更长，吞吐可以更低"],
    ]
    kinds = ["head"] + ["key" if i in (3, 5) else "body" for i in range(7)]
    ui.add_table(slide, 0.42, 1.48, [2.40, 10.10], [head] + body, [0.34] + [0.58] * 7, kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "TTFT 与 TPOT", "没有 AllReduce    ·    n 是一张卡上的条数")
    ui.banner(slide, 0.92, "Prefill 的 n = ceil(全局批 / 64)。Decode 的 n = ceil(全局批 / 256)。注意力由这一张卡承担。")
    panels = (
        (
            0.36,
            "TTFT    ·    Prefill 64 卡",
            [
                ["n", "ceil(全局批 / 64)"],
                ["命中", "p = 0.995 S，q = 0.005 S"],
                ["拉 KV", "n × (p×4939.5 + 61×min(p,128)×576) / BW"],
                ["带宽", "基线 50 GB/s，NEW 200 GB/s"],
                ["房间", f"每卡 KV 不超过 {v4.PF_ROOM/1e9:.0f} GB"],
                ["TTFT", "拉 KV + max(HBM, 计算) + MoE + 尾部"],
                ["吞吐", "全局批 × S / TTFT，取最大"],
            ],
        ),
        (
            6.86,
            "TPOT    ·    Decode 256 卡",
            [
                ["n", "ceil(全局批 / 256)"],
                ["溢出", f"f = max(n×K(S) − {v4.ROOM_GPU/1e9:.2f} GB, 0) / (n×K(S))"],
                ["读出", "30×(S/4)×64 + 31×(S/128)×576\n+ 30×min(1024, S/4)×576 + 滑窗"],
                ["换入", "f × n × Read / BW"],
                ["带宽", f"基线 1 不换入\n基线 2 是 {HOST/1e9:.0f} GB/s，每卡 {DDR_CAP/1e9:.0f} GB\ncache {POOL_BW/1e12:.2f} TB/s，合计 {POOL_TOTAL/1e9:.0f} GB"],
                ["TPOT", "换入 + max(HBM, 计算) + MoE"],
                ["吞吐", "全局批 / TPOT，取最大"],
            ],
        ),
    )
    for x, title, rows in panels:
        ui.textbox(slide, x, 1.46, 6.10, 0.32, title, 16, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
        kinds = ["head"] + ["key" if i >= len(rows) - 2 else "body" for i in range(len(rows))]
        heights = [0.30]
        for label, _text in rows:
            if label in ("读出", "带宽"):
                heights.append(0.70)
            else:
                heights.append(0.42)
        ui.add_table(slide, x, 1.82, [1.05, 5.05], [["项", "公式"]] + rows, heights, kinds, size=12)


def slide_prefill(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "Prefill 按 10 秒里的吞吐摸高", "64 卡    ·    基线 50 GB/s    ·    NEW 200 GB/s")
    ui.banner(slide, 0.90, "每卡 KV 必须放进房间。吞吐相同时取更大的批。提升是 NEW 的系统 TPS 相对基线。", size=12)
    head = ["输入", "方案", "每卡批", "系统 TPS", "提升", "TTFT", "拉 KV", "停在"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        base_bs, base_row = pack_pf(row["p25"])
        base = tps_p(base_bs, row["S"], base_row)
        for key, name in (("p25", "基线"), ("p100", "NEW")):
            bs, r = pack_pf(row[key])
            rate = tps_p(bs, row["S"], r)
            kinds.append("key" if name == "NEW" else "body")
            stop = why(row[key], 10.0)
            body.append([
                fmt_len(row["S"]),
                name,
                fmt_bs(r["n"]),
                fmt_rate(rate),
                "—" if name == "基线" else signed_pct(rate, base),
                f"{r['t']:.2f} 秒",
                f"{r['pull']:.2f} 秒",
                stop,
            ])
    shape = ui.add_table(
        slide, 0.36, 1.46,
        [0.85, 0.85, 1.15, 1.45, 1.15, 1.35, 1.45, 1.05],
        [head] + body,
        [0.32] + [0.36] * len(body),
        kinds,
        size=12,
    )
    margins(shape)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    limit = 0.010 if tag == "10" else 0.030
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    三路各自取吞吐最大的批")
    ui.banner(slide, 0.90, "吞吐单位是每秒完成的 token。相对 HBM 用的是这一行的系统吞吐。停在写的是 HBM 这一列为什么不再加批。", size=12)
    head = ["输入", "HBM 批", "毫秒", "HBM 吞吐", "DDR 批", "DDR 吞吐", "cache 批", "cache 吞吐", "相对 HBM", "停在"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        hb, hr = pack(row[f"hbm{tag}"])
        db, dr = pack(row[f"ddr{tag}"])
        cb, cr = pack(row[f"cache{tag}"])
        kinds.append("key" if row["S"] in (65536, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(hb),
            ms2(hr["t"]),
            fmt_rate(tps_d(hb, hr)),
            fmt_bs(db),
            fmt_rate(tps_d(db, dr)),
            fmt_bs(cb),
            fmt_rate(tps_d(cb, cr)),
            signed_pct(tps_d(cb, cr), tps_d(hb, hr)),
            why(row[f"hbm{tag}"], limit),
        ])
    shape = ui.add_table(
        slide, 0.28, 1.48,
        [0.72, 1.28, 0.85, 1.20, 1.28, 1.25, 1.35, 1.40, 1.15, 0.85],
        [head] + body,
        [0.34] + [0.58] * len(body),
        kinds,
        size=12,
    )
    margins(shape)
    r64 = data["rows"][0]
    hb, hr = pack(r64[f"hbm{tag}"])
    ui.gold(
        slide,
        6.05,
        0.95,
        f"64K 的 HBM 批 {fmt_bs(hb)}，TPOT {ms2(hr['t'])} 毫秒，停在{why(r64[f'hbm{tag}'], limit)}。"
        f"4M 三路都是批 {fmt_bs(pack(data['rows'][-1][f'hbm{tag}'])[0])}，TPOT {ms2(pack(data['rows'][-1][f'hbm{tag}'])[1]['t'])} 毫秒。",
        13,
    )


def slide_fill(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 8, "把批加到容量或时限，吞吐下降", "30 毫秒    ·    上限是这一档还满足 TPOT 的最大批")
    ui.banner(slide, 0.90, "最优列是第 7 页的吞吐最大点。上限列继续加批，直到 30 毫秒或 500 GB / 114 GB 放不下。", size=12)
    head = ["输入", "最优批", "最优吞吐", "DDR 上限批", "DDR 毫秒", "DDR 吞吐", "cache 上限批", "cache 毫秒", "cache 吞吐"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        hb, hr = pack(row["hbm30"])
        db, dr = pack_last(row["ddr30"])
        cb, cr = pack_last(row["cache30"])
        kinds.append("key" if row["S"] in (65536, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(hb),
            fmt_rate(tps_d(hb, hr)),
            fmt_bs(db),
            ms2(dr["t"]),
            fmt_rate(tps_d(db, dr)),
            fmt_bs(cb),
            ms2(cr["t"]),
            fmt_rate(tps_d(cb, cr)),
        ])
    shape = ui.add_table(
        slide, 0.28, 1.48,
        [0.72, 1.28, 1.25, 1.40, 1.15, 1.30, 1.55, 1.25, 1.40],
        [head] + body,
        [0.34] + [0.52] * len(body),
        kinds,
        size=12,
    )
    margins(shape)
    r4 = data["rows"][-1]
    _, hr = pack(r4["hbm30"])
    _, cr = pack_last(r4["cache30"])
    _, dr = pack_last(r4["ddr30"])
    ui.gold(
        slide,
        5.70,
        1.25,
        f"4M 最优这一步换入 {ms2(hr['swap'])} 毫秒，HBM {ms2(hr['hbm'])}，MoE {ms2(hr['moe'])}。\n"
        f"cache 加到上限后换入 {ms2(cr['swap'])} 毫秒，TPOT {ms2(cr['t'])} 毫秒，吞吐 {signed_pct(tps_d(pack_last(r4['cache30'])[0], cr), tps_d(pack(r4['hbm30'])[0], hr))}。\n"
        f"DDR 加到上限后换入 {ms2(dr['swap'])} 毫秒，TPOT {ms2(dr['t'])} 毫秒。160 GB/s 把多出来的稀疏读放大了。",
        14,
    )


def audit(prs):
    wide, low = Inches(13.333), Inches(7.50)
    bad = []
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.left is None:
                continue
            if shape.left + shape.width > wide + Emu(40000) or shape.top + shape.height > low + Emu(40000):
                bad.append((i, int(shape.left), int(shape.top), int(shape.width), int(shape.height)))
    return bad


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2：20T V4，在网 cache 29184 GB"
    blank = prs.slide_layouts[6]
    slide_open(prs, blank, data)
    slide_model(prs, blank)
    slide_cluster(prs, blank)
    slide_formula(prs, blank)
    slide_prefill(prs, blank, data)
    slide_decode(prs, blank, data, 6, "10", "10 毫秒：三路的吞吐最优点")
    slide_decode(prs, blank, data, 7, "30", "30 毫秒：三路的吞吐最优点")
    slide_fill(prs, blank, data)
    prs.save(PPT)
    print("slides", len(prs.slides), "overflow", audit(prs))
    print("room", f"{v4.ROOM_GPU/1e9:.2f}", "host", HOST / 1e9, "ddr", DDR_CAP / 1e9, "cache", POOL_CAP / 1e9)
    for row in data["rows"]:
        parts = [fmt_len(row["S"])]
        for tag in ("10", "30"):
            for key in ("hbm", "ddr", "cache"):
                bs, r = pack(row[f"{key}{tag}"])
                last, lr = pack_last(row[f"{key}{tag}"])
                parts.append(
                    f"{key}{tag}:{bs}/{ms2(r['t'])}/{fmt_rate(tps_d(bs, r))}"
                    f" last {last}/{fmt_rate(tps_d(last, lr))}/{why(row[f'{key}{tag}'], 0.01 if tag=='10' else 0.03)}"
                )
        print(" | ".join(parts))


if __name__ == "__main__":
    main()
