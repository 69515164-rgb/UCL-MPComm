#!/usr/bin/env python3
"""Temporary deck: CSA latent sits on HBM and the in-network cache.

Full-read KV takes HBM first. Leftover HBM is filled with latent.
The rest of the latent goes to the cache and nowhere else.
Cache total is 96 x 144 x 3 = 41472 GB, 162 GB per Decode NPU.
Cache read-in is 3.6 TB/s. Search still maximizes TPS inside the TPOT limit.
"""

from __future__ import annotations

import importlib.util

from pptx import Presentation
from pptx.util import Inches

spec = importlib.util.spec_from_file_location(
    "cui", "/agent/repos/ucl-mpcomm/docs/build_n2_cui_tier_ppt.py"
)
cui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cui)

ui = cui.ui
v4 = cui.v4
READ_BW = 3.6e12
CACHE_TOTAL = 96 * 144 * 3 * 1e9
CACHE_CAP = CACHE_TOTAL / v4.N
SLIDES = 9
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "CSA latent 同时用 HBM 和在网 cache 41472 GB    ·    读入 3.6 TB/s    ·    不用 DDR 池    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-在网cache+HBM放CSA LATENT-590A.pptx"


def decode_both(n, s):
    """Latent fills leftover HBM, then the per-card cache. No DDR tier."""
    placed = cui.place(n, s, CACHE_CAP)
    if placed is None:
        return None
    placed["t1_h"] = placed["rest_h"]
    placed["t1_c"] = placed["rest_c"]
    placed["t2_h"] = 0.0
    placed["t2_c"] = 0.0
    swap = (placed["b_hot"] + placed["b_cold"]) / READ_BW
    return cui.finish(n, s, placed, swap, v4.N)


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_hbm(n, s), tps)
            item[f"host{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_host(n, s), tps)
            item[f"both{tag}"] = cui.search(limit, lambda n, s=s: decode_both(n, s), tps)
        rows.append(item)
    return {"rows": rows}


def cap_note(row):
    return f"{row['rest_c'] / CACHE_CAP * 100:.1f}%"


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "CSA latent 同时放 HBM 和在网 cache，读入 3.6 TB/s", "N+2(cui)    ·    临时调整    ·    寻优仍是时限内取最大 TPS")
    ui.banner(
        slide,
        0.92,
        f"在网 cache 合计 96×144×3 = {CACHE_TOTAL / 1e9:.0f} GB，Decode 256 卡平分，每卡 {CACHE_CAP / 1e9:.0f} GB。不用二级 DDR。",
    )
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU，32 台。每台 2 个 CPU，各接 4 个 NPU。TP=1，DP=256，EP=256"],
        ["算力 / HBM", f"每 NPU 27640 TFLOPS FP4。HBM 384 GB，38400 GB/s。KV 房间 {cui.gb1(v4.ROOM_GPU)}"],
        ["全读 KV", "CSA index、HCA、滑窗。先放 HBM。放不下的全读也占 cache，并按 3.6 TB/s 换入"],
        ["CSA latent", f"先填 HBM 空位，剩下的进在网 cache。cache 每卡上限 {CACHE_CAP / 1e9:.0f} GB，没有 DDR"],
        ["读入", "3.6 TB/s。换入只算 cache 里的抽读。留在 HBM 上的 latent 不换入"],
        ["对照", "只放 HBM：放不下就停。主机：每卡 500 GB、200 GB/s，latent 先填 HBM 再进 DDR"],
        ["时限", "TPOT ≤ 10 毫秒和 30 毫秒。装得进 cache 的批里取系统 TPS 最大。TPS = 全局批 / TPOT"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "时限内取吞吐最大，HBM 空位先放 latent", "TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "进到卡上之后，这一步要读的 KV 仍按 HBM 的 38.4 TB/s 再读一次。换入只计 cache 里的那一部分，并叠在 MoE 上。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。先占 HBM"],
        ["latent 存储", f"每条 4320×S。先填 HBM 空位，剩下的进 cache，每卡溢出 ≤ {CACHE_CAP / 1e9:.0f} GB"],
        ["latent 抽读", "每条 30 层 × min(1024, S/4) × 576。换入只乘 cache 里的占比"],
        ["换入", "(溢出的全读 + cache 中的 latent 抽读) / 3.6 TB/s"],
        ["HBM", "(这一步要读的全部 KV + 19.35 GB) / 38.4 TB/s"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)"],
        ["选批", f"先丢掉溢出超过每卡 {CACHE_CAP / 1e9:.0f} GB 的批，再在 TPOT ≤ 10 或 30 毫秒里取全局批 / TPOT 最大的每卡条数"],
    ]
    kinds = ["head"] + ["key" if i in (1, 3, 6) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.48] * len(body), kinds, size=14)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    系统吞吐 TPS = 全局批 / TPOT    ·    全局批 = 每卡 × 256")
    ui.banner(slide, 0.92, f"合用是 latent 先填 HBM，剩下的进每卡 {CACHE_CAP / 1e9:.0f} GB cache，读入 3.6 TB/s。只放 HBM 和主机仍是原来的放法。三列 TPS 都是系统吞吐。")
    head = ["输入", "HBM 批", "HBM TPS", "主机批", "主机毫秒", "主机 TPS", "合用批", "合用毫秒", "合用 TPS", "相对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        hbm, host, both = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"]), cui.pack(item[f"both{tag}"])

        def trip(got):
            if got is None:
                return "—", "—", "—"
            return cui.fmt_bs(got[1] * v4.N), cui.ms2(got[2]["t"]), cui.fmt_rate(got[0])

        hb, _ht, hr = trip(hbm)
        ob, ot, ors = trip(host)
        bb, bt, br = trip(both)
        body.append([
            cui.fmt_len(item["S"]), hb, hr, ob, ot, ors, bb, bt, br,
            cui.signed_pct(both[0], host[0]) if both and host else "—",
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.95, 1.15, 1.25, 1.15, 1.20, 1.25, 1.20, 1.35, 1.40, 1.30]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    one, four = data["rows"][4], data["rows"][-1]
    b1, h1 = cui.pack(one[f"both{tag}"]), cui.pack(one[f"host{tag}"])
    b4, h4 = cui.pack(four[f"both{tag}"]), cui.pack(four[f"host{tag}"])
    splits = []
    for item in data["rows"]:
        lo, hi = cui.pack(item["both10"]), cui.pack(item["both30"])
        if lo[1] != hi[1]:
            splits.append(
                f"{cui.fmt_len(item['S'])} 在 30 毫秒是每卡 {cui.fmt_bs(hi[1])} 条、TPOT {cui.ms2(hi[2]['t'])} 毫秒，"
                f"收到 10 毫秒减到每卡 {cui.fmt_bs(lo[1])} 条、TPOT {cui.ms2(lo[2]['t'])} 毫秒"
            )
    note = (
        f"1M：合用每卡 {cui.fmt_bs(b1[1])} 条、TPOT {cui.ms2(b1[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(b1[0])}。"
        f"主机每卡 {cui.fmt_bs(h1[1])} 条、TPS {cui.fmt_rate(h1[0])}，相对主机 {cui.signed_pct(b1[0], h1[0])}。\n"
        f"4M：合用每卡 {cui.fmt_bs(b4[1])} 条、TPOT {cui.ms2(b4[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(b4[0])}。"
        f"主机 TPS {cui.fmt_rate(h4[0])}，相对主机 {cui.signed_pct(b4[0], h4[0])}。\n"
    )
    if splits:
        note += "。".join(splits) + "。其余长度 cache 先满，10 毫秒和 30 毫秒是同一批。"
    else:
        note += f"七档都是每卡 {CACHE_CAP / 1e9:.0f} GB 先满，TPOT 低于 10 毫秒，两档是同一批。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒 TPS 最高的批，latent 先填 HBM，剩下的进 cache", "系统吞吐 TPS = 全局批 / TPOT    ·    每卡")
    ui.banner(slide, 0.92, f"cache 一列是 HBM 放不下的整段 latent，上限每卡 {CACHE_CAP / 1e9:.0f} GB。换入毫秒只按这一段的抽读。")
    head = ["输入", "每卡", "HBM 全读", "HBM latent", "cache 全读", "cache latent", "占 cache", "换入毫秒", "TPS"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        tps, n, row = cui.pack(item["both30"])
        body.append([
            cui.fmt_len(item["S"]),
            cui.fmt_bs(n),
            cui.gb1(row["hbm_h"]),
            cui.gb1(row["hbm_c"]),
            cui.gb1(row["rest_h"]),
            cui.gb1(row["rest_c"]),
            cap_note(row),
            cui.ms2(row["swap"]),
            cui.fmt_rate(tps),
        ])
        kinds.append("body")
    ui.add_table(
        slide, 0.28, 1.48,
        [0.95, 0.95, 1.35, 1.50, 1.40, 1.60, 1.20, 1.30, 1.25],
        [head] + body, [0.36] + [0.46] * len(body), kinds, size=12,
    )
    row = cui.pack(data["rows"][4]["both30"])[2]
    row4 = cui.pack(data["rows"][-1]["both30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：HBM latent {cui.gb1(row['hbm_c'])}，cache latent {cui.gb1(row['rest_c'])}，"
        f"占每卡 {CACHE_CAP / 1e9:.0f} GB 的 {cap_note(row)}。"
        f"换入 {cui.ms2(row['swap'])} 毫秒，MoE {cui.ms2(row['moe'])} 毫秒。\n"
        f"4M：HBM latent {cui.gb1(row4['hbm_c'])}，cache latent {cui.gb1(row4['rest_c'])}（{cap_note(row4)}）。"
        f"换入 {cui.ms2(row4['swap'])} 毫秒。\n"
        "全读先占 HBM。HBM 空位放 latent，只有放不下的 latent 才进 cache，换入只算这一段。",
        14,
    )


def slide_tpot(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "30 毫秒合用的最优批，TPOT 按项打开", "毫秒    ·    TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "换入是 cache 里的 latent 抽读，加上溢出的全读，除以 3.6 TB/s。派发和合并仍用这条总线，权重用 HBM，GEMM 用 27.64 PFLOPS。")
    head = ["输入", "每卡", "HBM", "计算", "左", "换入", "派发", "权重", "GEMM", "合并", "MoE", "右", "TPOT"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["both30"])
        left = max(row["hbm"], row["ca"])
        right = max(row["swap"], row["moe"])
        body.append([
            cui.fmt_len(item["S"]), cui.fmt_bs(n),
            cui.ms2(row["hbm"]), cui.ms2(row["ca"]), cui.ms2(left), cui.ms2(row["swap"]),
            cui.ms2(row["td"]), cui.ms2(row["tw"]), cui.ms2(row["tg"]), cui.ms2(row["tc"]),
            cui.ms2(row["moe"]), cui.ms2(right), cui.ms2(row["t"]),
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.85, 0.8, 0.9, 0.9, 0.85, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.85, 0.95]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=11)
    row = cui.pack(data["rows"][4]["both30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：HBM {cui.ms2(row['hbm'])}，计算 {cui.ms2(row['ca'])}，换入 {cui.ms2(row['swap'])}，"
        f"MoE {cui.ms2(row['moe'])}。左 {cui.ms2(max(row['hbm'], row['ca']))}，右 {cui.ms2(max(row['swap'], row['moe']))}，"
        f"TPOT {cui.ms2(row['t'])} 毫秒。\n"
        "左是这一层自己的读和注意力，右是换入和专家。两边相加。留在 HBM 的 latent 不进换入。",
        14,
    )


def both_slices(row):
    slices = [
        ("HBM 全读", row["hbm_h"], cui.C_HOT),
        ("HBM latent", row["hbm_c"], cui.C_COLD),
    ]
    if row["rest_h"] > 1e6:
        slices.append(("cache 全读", row["rest_h"], cui.C_DDR))
    slices.append(("cache latent", row["rest_c"], cui.C_CACHE))
    return slices


def slide_pie(prs, blank, data):
    columns = []
    for item in data["rows"]:
        tps, _n, row = cui.pack(item["both30"])
        slices = both_slices(row)
        columns.append((f"{cui.fmt_len(item['S'])}\nTPS {cui.fmt_rate(tps)}\n合计 {cui.gb_pie(cui.share(slices)[0])}", slices))
    cui.slide_pies(
        prs, blank, 7,
        "HBM 加在网 cache：latent 两边各占多少",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    饼旁是占比",
        f"饼按存储字节。全读先放 HBM，空位放 CSA latent，剩下的 latent 进 cache，每卡不超过 {CACHE_CAP / 1e9:.0f} GB。换入只抽 cache 里的那一段。",
        columns,
        f"1M：{cui.occ_note(columns[4][1])}。\n4M：{cui.occ_note(columns[-1][1])}。\n"
        f"每卡 cache 上限 {CACHE_CAP / 1e9:.0f} GB。HBM 上的 latent 不换入。",
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，HBM 和在网 cache 放 CSA latent"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_decode(prs, blank, data, 3, "30", "30 毫秒内，HBM 加 cache 的系统 TPS 和主机、只放 HBM 比")
    slide_decode(prs, blank, data, 4, "10", "10 毫秒再收紧一次，仍取三条路径各自的最高系统 TPS")
    slide_place(prs, blank, data)
    slide_tpot(prs, blank, data)
    slide_pie(prs, blank, data)
    host_cols = cui.pie_columns(data, "host30", lambda item, n, row: cui.parts_host(row))
    cui.slide_pies(
        prs, blank, 8,
        "对照：主机 CPU 卸载，latent 仍先填 HBM",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    这是原来的放法",
        "这一页不是在网 cache。全读先放 HBM，空位再放 CSA latent，放不下的进 CPU DDR。",
        host_cols,
        f"1M：{cui.occ_note(host_cols[4][1])}。\n4M：{cui.occ_note(host_cols[-1][1])}。",
    )
    hbm_cols = cui.pie_columns(data, "hbm30", lambda item, n, row: cui.parts_hbm(item["S"], n))
    tot64, pct64 = cui.share(hbm_cols[0][1])
    tot4, pct4 = cui.share(hbm_cols[-1][1])
    cui.slide_pies(
        prs, blank, 9,
        "对照：不卸载，KV 全在 HBM",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    四块都在 HBM",
        "这一页没有在网 cache。CSA latent 和全读都在 HBM 里，放不下就减批。",
        hbm_cols,
        f"64K 合计 {cui.gb_pie(tot64)}，CSA latent {pct64[3]:.1f}%。\n"
        f"4M 合计 {cui.gb_pie(tot4)}，CSA latent {pct4[3]:.1f}%。比例几乎不随长度变。",
    )
    prs.save(PPT)
    print("CACHE_TOTAL_GB", CACHE_TOTAL / 1e9, "CACHE_CAP_GB", CACHE_CAP / 1e9, "ROOM_GB", v4.ROOM_GPU / 1e9)
    for item in data["rows"]:
        def brief(found):
            got = cui.pack(found)
            if got is None:
                return "none"
            row = got[2]
            return (
                f"n={got[1]} t={row['t']*1e3:.2f}ms swap={row['swap']*1e3:.3f} "
                f"hbm_c={row['hbm_c']/1e9:.1f} cache={row['rest_c']/1e9:.1f} tps={got[0]:.3e}"
            )
        print(
            cui.fmt_len(item["S"]),
            "both30", brief(item["both30"]),
            "both10", brief(item["both10"]),
            "host30", brief(item["host30"]),
        )


if __name__ == "__main__":
    main()
