#!/usr/bin/env python3
"""Temporary deck: every CSA latent byte is off HBM, into the two-level pool.

Full-read KV stays on HBM. Latent fills the in-network cache first, then the
unlimited DDR pool. Cache total is 96 x 144 x 3 = 41472 GB, 162 GB per card.
Both tiers are read at the original pool rate, 6.4 Tb/s per card.
Search still maximizes TPS inside the TPOT limit.
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
T1_BW = cui.T1_BW
T2_BW = cui.T2_BW
CACHE_TOTAL = 96 * 144 * 3 * 1e9
CACHE_CAP = CACHE_TOTAL / v4.N
SLIDES = 9
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "CSA latent 全部进两级池    ·    cache 41472 GB    ·    两级每卡 6.4 Tb/s    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-两级池放CSA LATENT-590A.pptx"


def decode_off(n, s):
    """All latent is off HBM. Cache fills first, then the unlimited DDR pool."""
    hot, cold, cold_read, t_hbm, t_ca = cui.attention_times(n, s)
    need_h = n * hot
    need_c = n * cold
    hbm_h = min(need_h, v4.ROOM_GPU)
    rest_h = need_h - hbm_h
    t1_h = min(rest_h, CACHE_CAP)
    t1_c = min(need_c, CACHE_CAP - t1_h)
    t2_h = rest_h - t1_h
    t2_c = need_c - t1_c
    b1 = b2 = 0.0
    if need_h:
        b1 += need_h * (t1_h / need_h)
        b2 += need_h * (t2_h / need_h)
    if need_c:
        b1 += n * cold_read * (t1_c / need_c)
        b2 += n * cold_read * (t2_c / need_c)
    placed = {
        "hbm": t_hbm,
        "ca": t_ca,
        "n": n,
        "hbm_h": hbm_h,
        "hbm_c": 0.0,
        "rest_h": rest_h,
        "rest_c": need_c,
        "t1_h": t1_h,
        "t1_c": t1_c,
        "t2_h": t2_h,
        "t2_c": t2_c,
        "b1": b1,
        "b2": b2,
    }
    return cui.finish(n, s, placed, b1 / T1_BW + b2 / T2_BW, v4.N)


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_hbm(n, s), tps)
            item[f"host{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_host(n, s), tps)
            item[f"off{tag}"] = cui.search(limit, lambda n, s=s: decode_off(n, s), tps)
        rows.append(item)
    return {"rows": rows}


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "CSA latent 全部进两级池，读入用回 6.4 Tb/s", "N+2(cui)    ·    临时调整    ·    寻优仍是时限内取最大 TPS")
    ui.banner(
        slide,
        0.92,
        f"在网 cache 合计 96×144×3 = {CACHE_TOTAL / 1e9:.0f} GB，每卡 {CACHE_CAP / 1e9:.0f} GB。二级 DDR 不限。两级读入都是每卡 6.4 Tb/s，也就是 0.80 TB/s。",
    )
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU，32 台。每台 2 个 CPU，各接 4 个 NPU。TP=1，DP=256，EP=256"],
        ["算力 / HBM", f"每 NPU 27640 TFLOPS FP4。HBM 384 GB，38400 GB/s。KV 房间 {cui.gb1(v4.ROOM_GPU)}"],
        ["全读 KV", "CSA index、HCA、滑窗。先放 HBM。放不下的全读先占 cache，再进二级 DDR"],
        ["CSA latent", f"一字节都不留在 HBM。先填每卡 {CACHE_CAP / 1e9:.0f} GB 在网 cache，剩下的进二级 DDR"],
        ["读入", "两级都是 6.4 Tb/s（0.80 TB/s）。换入 = cache 抽读 / 0.80 + DDR 抽读 / 0.80"],
        ["对照", "只放 HBM：latent 能留在 HBM。主机：每卡 500 GB、200 GB/s，latent 先填 HBM 再进 CPU DDR"],
        ["时限", "TPOT ≤ 10 毫秒和 30 毫秒。时限内取系统 TPS 最大。TPS = 全局批 / TPOT"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "时限内取吞吐最大，latent 的抽读整段走两级池", "TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "两级同速。换入只看卸载的抽读有多少字节，不看它落在 cache 还是 DDR。进卡之后，这一步的 KV 仍按 HBM 38.4 TB/s 再读一次。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。先占 HBM"],
        ["latent 存储", f"每条 4320×S。全部不在 HBM。先填每卡 {CACHE_CAP / 1e9:.0f} GB cache，再进二级 DDR"],
        ["latent 抽读", "每条 30 层 × min(1024, S/4) × 576。这一段全部算卸载"],
        ["换入", "cache 中的抽读 / 0.80 TB/s + DDR 中的抽读 / 0.80 TB/s"],
        ["HBM", "(这一步要读的全部 KV + 19.35 GB) / 38.4 TB/s"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)"],
        ["选批", "在 TPOT ≤ 10 或 30 毫秒里，取全局批 / TPOT 最大的每卡条数"],
    ]
    kinds = ["head"] + ["key" if i in (1, 3, 5) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.48] * len(body), kinds, size=14)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    系统吞吐 TPS = 全局批 / TPOT    ·    全局批 = 每卡 × 256")
    ui.banner(slide, 0.92, "CSA latent 全部卸载。cache 和二级 DDR 都按每卡 0.80 TB/s 读入。对照仍让 latent 先填 HBM。三列都是系统 TPS。")
    head = ["输入", "HBM 批", "HBM TPS", "主机批", "主机毫秒", "主机 TPS", "两级批", "两级毫秒", "两级 TPS", "相对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        hbm, host, off = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"]), cui.pack(item[f"off{tag}"])

        def trip(got):
            if got is None:
                return "—", "—", "—"
            return cui.fmt_bs(got[1] * v4.N), cui.ms2(got[2]["t"]), cui.fmt_rate(got[0])

        hb, _ht, hr = trip(hbm)
        ob, ot, ors = trip(host)
        pb, pt, pr = trip(off)
        body.append([
            cui.fmt_len(item["S"]), hb, hr, ob, ot, ors, pb, pt, pr,
            cui.signed_pct(off[0], host[0]) if off and host else "—",
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.95, 1.15, 1.25, 1.15, 1.20, 1.25, 1.20, 1.35, 1.40, 1.30]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    one, four = data["rows"][4], data["rows"][-1]
    o1, h1 = cui.pack(one[f"off{tag}"]), cui.pack(one[f"host{tag}"])
    o4, h4 = cui.pack(four[f"off{tag}"]), cui.pack(four[f"host{tag}"])
    note = (
        f"1M：两级每卡 {cui.fmt_bs(o1[1])} 条、TPOT {cui.ms2(o1[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(o1[0])}。"
        f"主机每卡 {cui.fmt_bs(h1[1])} 条、TPS {cui.fmt_rate(h1[0])}，相对主机 {cui.signed_pct(o1[0], h1[0])}。\n"
        f"4M：两级每卡 {cui.fmt_bs(o4[1])} 条、TPOT {cui.ms2(o4[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(o4[0])}。"
        f"主机 TPS {cui.fmt_rate(h4[0])}，相对主机 {cui.signed_pct(o4[0], h4[0])}。\n"
    )
    if tag == "30":
        note += "64K 到 512K 顶在 30 毫秒。1M 起全读先把 HBM 占满。两级同速，162 GB 只改落点。"
    else:
        note += "七个长度都顶在 10 毫秒附近，条数都少于 30 毫秒。两级同速，162 GB 只改落点。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒 TPS 最高的批，latent 先填 cache，超出的进 DDR", "系统吞吐 TPS = 全局批 / TPOT    ·    每卡")
    ui.banner(slide, 0.92, "HBM 的 latent 一列是 0。cache 上限每卡 162 GB。换入毫秒按抽读，两级都是 0.80 TB/s。")
    head = ["输入", "每卡", "HBM 全读", "HBM latent", "cache latent", "DDR latent", "换入毫秒", "TPS"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        tps, n, row = cui.pack(item["off30"])
        body.append([
            cui.fmt_len(item["S"]),
            cui.fmt_bs(n),
            cui.gb1(row["hbm_h"]),
            cui.gb1(row["hbm_c"]),
            cui.gb1(row["t1_c"]),
            cui.gb1(row["t2_c"]),
            cui.ms2(row["swap"]),
            cui.fmt_rate(tps),
        ])
        kinds.append("body")
    ui.add_table(
        slide, 0.42, 1.48,
        [1.15, 1.10, 1.50, 1.55, 1.70, 1.70, 1.45, 1.35],
        [head] + body, [0.36] + [0.46] * len(body), kinds, size=13,
    )
    row = cui.pack(data["rows"][4]["off30"])[2]
    row4 = cui.pack(data["rows"][-1]["off30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：HBM latent 是 0，cache {cui.gb1(row['t1_c'])}，DDR {cui.gb1(row['t2_c'])}。"
        f"换入 {cui.ms2(row['swap'])} 毫秒，MoE {cui.ms2(row['moe'])} 毫秒。\n"
        f"4M：cache {cui.gb1(row4['t1_c'])}，DDR {cui.gb1(row4['t2_c'])}，换入 {cui.ms2(row4['swap'])} 毫秒。\n"
        "两级都是 0.80 TB/s。字节从 cache 挪到 DDR，换入时间不变。162 GB 只决定饼怎么分。",
        14,
    )


def slide_tpot(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "30 毫秒两级池的最优批，TPOT 按项打开", "毫秒    ·    TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "换入是全部 latent 抽读，加上溢出的全读，按 0.80 TB/s。派发和合并仍用总线 3.6 TB/s，权重用 HBM，GEMM 用 27.64 PFLOPS。")
    head = ["输入", "每卡", "HBM", "计算", "左", "换入", "派发", "权重", "GEMM", "合并", "MoE", "右", "TPOT"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["off30"])
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
    row = cui.pack(data["rows"][4]["off30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：HBM {cui.ms2(row['hbm'])}，计算 {cui.ms2(row['ca'])}，换入 {cui.ms2(row['swap'])}，"
        f"MoE {cui.ms2(row['moe'])}。左 {cui.ms2(max(row['hbm'], row['ca']))}，右 {cui.ms2(max(row['swap'], row['moe']))}，"
        f"TPOT {cui.ms2(row['t'])} 毫秒。\n"
        "左是这一层自己的读和注意力，右是换入和专家。两边相加。",
        14,
    )


def off_slices(row):
    slices = [("HBM 全读", row["hbm_h"], cui.C_HOT)]
    if row["t1_h"] > 1e6:
        slices.append(("cache 全读", row["t1_h"], cui.C_WIN))
    if row["t1_c"] > 1e6:
        slices.append(("cache latent", row["t1_c"], cui.C_CACHE))
    if row["t2_h"] > 1e6:
        slices.append(("DDR 全读", row["t2_h"], cui.C_HCA))
    if row["t2_c"] > 1e6:
        slices.append(("DDR latent", row["t2_c"], cui.C_LAT))
    return slices


def slide_pie(prs, blank, data):
    columns = []
    for item in data["rows"]:
        tps, _n, row = cui.pack(item["off30"])
        slices = off_slices(row)
        columns.append((f"{cui.fmt_len(item['S'])}\nTPS {cui.fmt_rate(tps)}\n合计 {cui.gb_pie(cui.share(slices)[0])}", slices))
    cui.slide_pies(
        prs, blank, 7,
        "两级池：HBM 只留全读，latent 分在 cache 和 DDR",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    饼旁是占比",
        f"饼按存储字节。HBM 上没有 CSA latent。cache 每卡最多 {CACHE_CAP / 1e9:.0f} GB，超出的整段 latent 进二级 DDR。换入两级同速。",
        columns,
        f"1M：{cui.occ_note(columns[4][1])}。\n4M：{cui.occ_note(columns[-1][1])}。\n"
        "两级都是 0.80 TB/s，落在哪一级不改变换入时间。",
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，两级池放 CSA latent"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_decode(prs, blank, data, 3, "30", "30 毫秒内，两级池的系统 TPS 和主机、只放 HBM 比")
    slide_decode(prs, blank, data, 4, "10", "10 毫秒再收紧一次，仍取三条路径各自的最高系统 TPS")
    slide_place(prs, blank, data)
    slide_tpot(prs, blank, data)
    slide_pie(prs, blank, data)
    host_cols = cui.pie_columns(data, "host30", lambda item, n, row: cui.parts_host(row))
    cui.slide_pies(
        prs, blank, 8,
        "对照：主机 CPU 卸载，latent 仍先填 HBM",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    这是原来的放法",
        "这一页不是两级池。全读先放 HBM，空位再放 CSA latent，放不下的进 CPU DDR。",
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
        "这一页没有两级池。CSA latent 和全读都在 HBM 里，放不下就减批。",
        hbm_cols,
        f"64K 合计 {cui.gb_pie(tot64)}，CSA latent {pct64[3]:.1f}%。\n"
        f"4M 合计 {cui.gb_pie(tot4)}，CSA latent {pct4[3]:.1f}%。比例几乎不随长度变。",
    )
    prs.save(PPT)
    print("CACHE_CAP_GB", CACHE_CAP / 1e9, "T1_BW", T1_BW, "T2_BW", T2_BW)
    for item in data["rows"]:
        def brief(found):
            got = cui.pack(found)
            if got is None:
                return "none"
            row = got[2]
            return (
                f"n={got[1]} t={row['t']*1e3:.2f} swap={row['swap']*1e3:.2f} moe={row['moe']*1e3:.2f} "
                f"c={row['t1_c']/1e9:.1f} d={row['t2_c']/1e9:.1f} tps={got[0]:.3e}"
            )
        print(cui.fmt_len(item["S"]), "off30", brief(item["off30"]), "off10", brief(item["off10"]))


if __name__ == "__main__":
    main()
