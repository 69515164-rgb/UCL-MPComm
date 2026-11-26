#!/usr/bin/env python3
"""Temporary deck: every CSA latent byte sits in the in-network cache.

No DDR pool. Cache total is 13824 GB, 54 GB per Decode NPU.
Read-in is the bus, 3.6 TB/s. Full-read KV stays on HBM.
Search is unchanged: highest throughput inside the TPOT limit,
among batches whose latent fits in that cache.
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
CACHE_TOTAL = 13824e9
CACHE_CAP = CACHE_TOTAL / v4.N
SLIDES = 9
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "CSA latent 全部进在网 cache 13824 GB    ·    读入 3.6 TB/s    ·    不用 DDR 池    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-在网cache放CSA LATENT-590A.pptx"


def decode_cache(n, s):
    """Full-read stays on HBM. All CSA latent must fit in the per-card cache."""
    hot, cold, cold_read, t_hbm, t_ca = cui.attention_times(n, s)
    need_h = n * hot
    need_c = n * cold
    if need_h > v4.ROOM_GPU + 1.0 or need_c > CACHE_CAP + 1.0:
        return None
    placed = {
        "hbm": t_hbm,
        "ca": t_ca,
        "n": n,
        "hbm_h": need_h,
        "hbm_c": 0.0,
        "rest_h": 0.0,
        "rest_c": need_c,
        "t1_h": 0.0,
        "t1_c": need_c,
        "t2_h": 0.0,
        "t2_c": 0.0,
        "b1": n * cold_read,
        "b2": 0.0,
    }
    return cui.finish(n, s, placed, (n * cold_read) / READ_BW, v4.N)


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_hbm(n, s), tps)
            item[f"host{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_host(n, s), tps)
            item[f"cache{tag}"] = cui.search(limit, lambda n, s=s: decode_cache(n, s), tps)
        rows.append(item)
    return {"rows": rows}


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "CSA latent 只放在网 cache，读入 3.6 TB/s", "N+2(cui)    ·    临时调整    ·    寻优仍是时限内取最大 TPS")
    ui.banner(
        slide,
        0.92,
        f"在网 cache 合计 {CACHE_TOTAL / 1e9:.0f} GB，Decode 256 卡平分，每卡 {CACHE_CAP / 1e9:.0f} GB。不用二级 DDR。放不下的批直接淘汰。",
    )
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU，32 台。每台 2 个 CPU，各接 4 个 NPU。TP=1，DP=256，EP=256"],
        ["算力 / HBM", "每 NPU 27640 TFLOPS FP4。HBM 384 GB，38400 GB/s。KV 房间 315.7 GB"],
        ["全读 KV", "CSA index、HCA、滑窗。只放 HBM。HBM 放不下这一批全读，这批不成立"],
        ["CSA latent", f"一字节都不留在 HBM。整段只进在网 cache，每卡上限 {CACHE_CAP / 1e9:.0f} GB"],
        ["读入", "3.6 TB/s。换入 = 全部 latent 抽读 / 3.6 TB/s。没有 DDR 这一级"],
        ["对照", "只放 HBM：latent 能留在 HBM。主机：每卡 500 GB、200 GB/s，latent 先填 HBM 再进 DDR"],
        ["时限", "TPOT ≤ 10 毫秒和 30 毫秒。装进 cache 的批里取系统 TPS 最大。TPS = 全局批 / TPOT"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "时限内取吞吐最大，latent 必须先装进每卡 54 GB", "TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "进到卡上之后，这一步要读的 KV 仍按 HBM 的 38.4 TB/s 再读一次。换入只计 cache 里的抽读，并叠在 MoE 上。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。只占 HBM，不进 cache"],
        ["latent 存储", f"每条 4320×S。全部在 cache，且每卡合计 ≤ {CACHE_CAP / 1e9:.0f} GB"],
        ["latent 抽读", "每条 30 层 × min(1024, S/4) × 576。换入按这一段的全部字节"],
        ["换入", "全部 latent 抽读 / 3.6 TB/s"],
        ["HBM", "(这一步要读的全部 KV + 19.35 GB) / 38.4 TB/s"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)"],
        ["选批", "先丢掉 latent 超过每卡 54 GB 的批，再在 TPOT ≤ 10 或 30 毫秒里取全局批 / TPOT 最大的每卡条数"],
    ]
    kinds = ["head"] + ["key" if i in (1, 3, 6) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.48] * len(body), kinds, size=14)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    系统吞吐 TPS = 全局批 / TPOT    ·    全局批 = 每卡 × 256")
    ui.banner(slide, 0.92, f"在网 cache 每卡 {CACHE_CAP / 1e9:.0f} GB，只放 CSA latent，读入 3.6 TB/s。只放 HBM 和主机仍让 latent 先填 HBM。三列 TPS 都是系统吞吐。")
    head = ["输入", "HBM 批", "HBM TPS", "主机批", "主机毫秒", "主机 TPS", "cache 批", "cache 毫秒", "cache TPS", "相对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        hbm, host, cache = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"]), cui.pack(item[f"cache{tag}"])

        def trip(got):
            if got is None:
                return "—", "—", "—"
            return cui.fmt_bs(got[1] * v4.N), cui.ms2(got[2]["t"]), cui.fmt_rate(got[0])

        hb, _ht, hr = trip(hbm)
        ob, ot, ors = trip(host)
        cb, ct, cr = trip(cache)
        body.append([
            cui.fmt_len(item["S"]), hb, hr, ob, ot, ors, cb, ct, cr,
            cui.signed_pct(cache[0], host[0]) if cache and host else "—",
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.95, 1.15, 1.25, 1.15, 1.20, 1.25, 1.25, 1.40, 1.40, 1.20]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    one, four = data["rows"][4], data["rows"][-1]
    c1, h1 = cui.pack(one[f"cache{tag}"]), cui.pack(one[f"host{tag}"])
    c4, h4 = cui.pack(four[f"cache{tag}"]), cui.pack(four[f"host{tag}"])
    same = all(cui.pack(item[f"cache{tag}"])[1] == cui.pack(item["cache30"])[1] for item in data["rows"])
    note = (
        f"1M：cache 每卡 {cui.fmt_bs(c1[1])} 条、TPOT {cui.ms2(c1[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(c1[0])}。"
        f"主机每卡 {cui.fmt_bs(h1[1])} 条、TPS {cui.fmt_rate(h1[0])}，相对主机 {cui.signed_pct(c1[0], h1[0])}。\n"
        f"4M：cache 每卡 {cui.fmt_bs(c4[1])} 条、TPOT {cui.ms2(c4[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(c4[0])}。"
        f"主机 TPS {cui.fmt_rate(h4[0])}，相对主机 {cui.signed_pct(c4[0], h4[0])}。\n"
    )
    if same:
        note += f"每卡 {CACHE_CAP / 1e9:.0f} GB 先被 latent 装满，TPOT 还没到 {tag} 毫秒。10 毫秒和 30 毫秒因此是同一批。"
    else:
        note += f"收到 {tag} 毫秒后，有的长度要减批。cache 里再加一条 latent 就超过每卡 {CACHE_CAP / 1e9:.0f} GB。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒 TPS 最高的批，latent 全在 cache，再加一条就超", "系统吞吐 TPS = 全局批 / TPOT    ·    每卡")
    ui.banner(slide, 0.92, "HBM 的 latent 一列是 0。cache 一列是整段存储，上限 54 GB。换入毫秒只按抽读。")
    head = ["输入", "每卡", "HBM 全读", "HBM latent", "cache latent", "占上限", "换入毫秒", "TPS"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        tps, n, row = cui.pack(item["cache30"])
        body.append([
            cui.fmt_len(item["S"]),
            cui.fmt_bs(n),
            cui.gb1(row["hbm_h"]),
            cui.gb1(row["hbm_c"]),
            cui.gb1(row["rest_c"]),
            f"{row['rest_c'] / CACHE_CAP * 100:.1f}%",
            cui.ms2(row["swap"]),
            cui.fmt_rate(tps),
        ])
        kinds.append("body")
    ui.add_table(
        slide, 0.42, 1.48,
        [1.15, 1.05, 1.55, 1.55, 1.85, 1.25, 1.45, 1.40],
        [head] + body, [0.36] + [0.46] * len(body), kinds, size=13,
    )
    row = cui.pack(data["rows"][4]["cache30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M 这一批 HBM 上的 latent 是 0，cache 里的 latent 是 {cui.gb1(row['rest_c'])}，"
        f"占每卡 {CACHE_CAP / 1e9:.0f} GB 的 {row['rest_c'] / CACHE_CAP * 100:.1f}%。"
        f"换入 {cui.ms2(row['swap'])} 毫秒，MoE {cui.ms2(row['moe'])} 毫秒。\n"
        "再加一条，latent 就超过 54 GB，这批被丢掉。全读都在 HBM 里，没有溢出。\n"
        "条数由 cache 容量决定。换入远短于 MoE，所以时限不是先碰到的那条约束。",
        14,
    )


def slide_tpot(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "30 毫秒在网 cache 的最优批，TPOT 按项打开", "毫秒    ·    TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "换入是全部 latent 抽读除以 3.6 TB/s。派发和合并仍用这条总线，权重用 HBM，GEMM 用 27.64 PFLOPS。")
    head = ["输入", "每卡", "HBM", "计算", "左", "换入", "派发", "权重", "GEMM", "合并", "MoE", "右", "TPOT"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["cache30"])
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
    row = cui.pack(data["rows"][4]["cache30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：HBM {cui.ms2(row['hbm'])}，计算 {cui.ms2(row['ca'])}，换入 {cui.ms2(row['swap'])}，"
        f"MoE {cui.ms2(row['moe'])}。左 {cui.ms2(max(row['hbm'], row['ca']))}，右 {cui.ms2(max(row['swap'], row['moe']))}，"
        f"TPOT {cui.ms2(row['t'])} 毫秒。\n"
        "左是这一层自己的读和注意力，右是换入和专家。两边相加。换入这一列远小于右。",
        14,
    )


def cache_slices(row):
    return [
        ("HBM 全读", row["hbm_h"], cui.C_HOT),
        ("cache latent", row["rest_c"], cui.C_CACHE),
    ]


def slide_pie_cache(prs, blank, data):
    columns = []
    for item in data["rows"]:
        tps, _n, row = cui.pack(item["cache30"])
        slices = cache_slices(row)
        columns.append((f"{cui.fmt_len(item['S'])}\nTPS {cui.fmt_rate(tps)}\n合计 {cui.gb_pie(cui.share(slices)[0])}", slices))
    cui.slide_pies(
        prs, blank, 7,
        "在网 cache：HBM 只留全读，CSA latent 全部在 cache",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    饼旁是占比",
        f"饼按存储字节。HBM 上没有 CSA latent。cache latent 是整段 4320×S，每卡不超过 {CACHE_CAP / 1e9:.0f} GB。换入只抽其中每层最多 1024 个位置。",
        columns,
        f"1M：{cui.occ_note(columns[4][1])}。\n4M：{cui.occ_note(columns[-1][1])}。\n"
        f"每卡 cache 上限 {CACHE_CAP / 1e9:.0f} GB。条数加到再放一条就超为止。",
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，在网 cache 放 CSA latent"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_decode(prs, blank, data, 3, "30", "30 毫秒内，在网 cache 的系统 TPS 和主机、只放 HBM 比")
    slide_decode(prs, blank, data, 4, "10", "10 毫秒再收紧一次，仍取三条路径各自的最高系统 TPS")
    slide_place(prs, blank, data)
    slide_tpot(prs, blank, data)
    slide_pie_cache(prs, blank, data)
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
        "这一页不是在网 cache。没有外置 cache，CSA latent 和全读都在 HBM 里。",
        hbm_cols,
        f"64K 合计 {cui.gb_pie(tot64)}，CSA latent {pct64[3]:.1f}%。\n"
        f"4M 合计 {cui.gb_pie(tot4)}，CSA latent {pct4[3]:.1f}%。比例几乎不随长度变。",
    )
    prs.save(PPT)
    print("CACHE_CAP_GB", CACHE_CAP / 1e9)
    for item in data["rows"]:
        def brief(found):
            got = cui.pack(found)
            if got is None:
                return "none"
            row = got[2]
            return (
                f"n={got[1]} t={row['t']*1e3:.2f}ms swap={row['swap']*1e3:.3f} "
                f"moe={row['moe']*1e3:.2f} cache={row['rest_c']/1e9:.2f}GB tps={got[0]:.3e}"
            )
        print(
            cui.fmt_len(item["S"]),
            "hbm30", brief(item["hbm30"]),
            "host30", brief(item["host30"]),
            "cache30", brief(item["cache30"]),
            "cache10", brief(item["cache10"]),
        )


if __name__ == "__main__":
    main()
