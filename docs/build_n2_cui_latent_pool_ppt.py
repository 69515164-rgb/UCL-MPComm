#!/usr/bin/env python3
"""Temporary deck: every CSA latent byte sits in an unlimited pool.

Full-read KV stays on HBM. The pool read-in rate is the bus, 3.6 TB/s.
Search is unchanged: highest throughput inside the TTFT and TPOT limits.
HBM-only and host DDR stay on the previous placement, as the comparison.
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
POOL_BW = 3.6e12
SLIDES = 9
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "CSA latent 全部进无限大池    ·    读入 3.6 TB/s    ·    TTFT 10 秒    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-无限大池放CSA LATENT-590A.pptx"


def decode_pool(n, s):
    """Full-read stays on HBM. Every CSA latent byte is read from the pool."""
    hot, cold, cold_read, t_hbm, t_ca = cui.attention_times(n, s)
    need_h = n * hot
    hbm_h = min(need_h, v4.ROOM_GPU)
    rest_h = need_h - hbm_h
    b_hot = rest_h
    b_cold = n * cold_read
    placed = {
        "hbm": t_hbm,
        "ca": t_ca,
        "n": n,
        "hbm_h": hbm_h,
        "hbm_c": 0.0,
        "rest_h": rest_h,
        "rest_c": n * cold,
        "t1_h": 0.0,
        "t1_c": 0.0,
        "t2_h": rest_h,
        "t2_c": n * cold,
        "b1": 0.0,
        "b2": b_hot + b_cold,
    }
    return cui.finish(n, s, placed, (b_hot + b_cold) / POOL_BW, v4.N)


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_hbm(n, s), tps)
            item[f"host{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_host(n, s), tps)
            item[f"pool{tag}"] = cui.search(limit, lambda n, s=s: decode_pool(n, s), tps)
        rows.append(item)
    return {"rows": rows}


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "CSA latent 全部不放 HBM，读入走 3.6 TB/s", "N+2(cui)    ·    临时调整    ·    寻优仍是时限内取最大 TPS")
    ui.banner(slide, 0.92, "全读 KV 仍留在 HBM。CSA latent 整段放进容量不限的池，读入带宽是总线平面的 3.6 TB/s。HBM 只放和主机卸载仍用原来的放法，用来对照。")
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU，32 台。每台 2 个 CPU，各接 4 个 NPU。TP=1，DP=256，EP=256"],
        ["算力 / HBM", "每 NPU 27640 TFLOPS FP4。HBM 384 GB，38400 GB/s。KV 房间 315.7 GB"],
        ["全读 KV", "CSA index、HCA、滑窗。先放 HBM，HBM 放不下的才进池"],
        ["CSA latent", "一字节都不留在 HBM。存储和抽读都从无限大池来"],
        ["读入", "3.6 TB/s。换入 = （溢出的全读 + 全部 latent 抽读）/ 3.6 TB/s"],
        ["对照", "只放 HBM：latent 能留在 HBM。主机：每卡 500 GB、200 GB/s，latent 先填 HBM 再进 DDR"],
        ["时限", "TPOT ≤ 10 毫秒和 30 毫秒。时限内取系统 TPS 最大的批。TPS = 全局批 / TPOT"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "时限内取吞吐最大，latent 的抽读整段按 3.6 TB/s", "TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "进到卡上之后，这一步要读的 KV 仍按 HBM 的 38.4 TB/s 再读一次。换入只计池里的那一部分，并叠在 MoE 上。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。先占 HBM"],
        ["latent 存储", "每条 4320×S。这一版全部在池里，不占 HBM"],
        ["latent 抽读", "每条 30 层 × min(1024, S/4) × 576。换入按这一段的全部字节"],
        ["换入", "(溢出的全读字节 + 全部 latent 抽读) / 3.6 TB/s"],
        ["HBM", "(这一步要读的全部 KV + 19.35 GB) / 38.4 TB/s"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)"],
        ["选批", "TPOT ≤ 10 或 30 毫秒里，取全局批 / TPOT 最大的每卡条数"],
    ]
    kinds = ["head"] + ["key" if i in (3, 5) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.48] * len(body), kinds, size=14)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    系统吞吐 TPS = 全局批 / TPOT    ·    全局批 = 每卡 × 256")
    ui.banner(slide, 0.92, "无限池把 CSA latent 全部卸载，读入 3.6 TB/s。只放 HBM 和主机仍让 latent 先填 HBM。三列 TPS 都是系统吞吐。")
    head = ["输入", "HBM 批", "HBM TPS", "主机批", "主机毫秒", "主机 TPS", "无限池批", "无限池毫秒", "无限池 TPS", "相对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        h, host, pool = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"]), cui.pack(item[f"pool{tag}"])

        def trip(got):
            if got is None:
                return "—", "—", "—"
            return cui.fmt_bs(got[1] * v4.N), cui.ms2(got[2]["t"]), cui.fmt_rate(got[0])

        hb, _ht, hr = trip(h)
        ob, ot, ors = trip(host)
        pb, pt, pr = trip(pool)
        body.append([
            cui.fmt_len(item["S"]), hb, hr, ob, ot, ors, pb, pt, pr,
            cui.signed_pct(pool[0], host[0]) if pool and host else "—",
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.95, 1.15, 1.25, 1.15, 1.20, 1.25, 1.25, 1.35, 1.45, 1.20]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    one, four = data["rows"][4], data["rows"][-1]
    p1, h1 = cui.pack(one[f"pool{tag}"]), cui.pack(one[f"host{tag}"])
    p4, h4 = cui.pack(four[f"pool{tag}"]), cui.pack(four[f"host{tag}"])
    note = (
        f"1M：无限池每卡 {cui.fmt_bs(p1[1])} 条、TPOT {cui.ms2(p1[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(p1[0])}。"
        f"主机每卡 {cui.fmt_bs(h1[1])} 条、TPS {cui.fmt_rate(h1[0])}，相对主机 {cui.signed_pct(p1[0], h1[0])}。\n"
        f"4M：无限池每卡 {cui.fmt_bs(p4[1])} 条、TPOT {cui.ms2(p4[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(p4[0])}。"
        f"主机 TPS {cui.fmt_rate(h4[0])}，相对主机 {cui.signed_pct(p4[0], h4[0])}。\n"
    )
    if tag == "10":
        p30 = cui.pack(four["pool30"])
        note += (
            f"4M 的 30 毫秒是每卡 {cui.fmt_bs(p30[1])} 条、TPS {cui.fmt_rate(p30[0])}。"
            f"收到 10 毫秒后是每卡 {cui.fmt_bs(p4[1])} 条，吞吐 {cui.signed_pct(p4[0], p30[0])}。"
        )
    else:
        note += "换入短于 MoE 时，TPOT 里只有 HBM 和 MoE。latent 全部从 3.6 TB/s 读入，不再占用 HBM 房间。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒 TPS 最高的批，HBM 只剩全读，latent 全在池里", "系统吞吐 TPS = 全局批 / TPOT    ·    每卡")
    ui.banner(slide, 0.92, "HBM 的 latent 一列是 0。池中 latent 是整段存储。换入毫秒只按抽读，不按整段存储。")
    head = ["输入", "每卡", "HBM 全读", "HBM latent", "池中全读", "池中 latent", "换入毫秒", "TPS"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        tps, n, row = cui.pack(item["pool30"])
        body.append([
            cui.fmt_len(item["S"]),
            cui.fmt_bs(n),
            cui.gb1(row["hbm_h"]),
            cui.gb1(row["hbm_c"]),
            cui.gb1(row["rest_h"]),
            cui.gb1(row["rest_c"]),
            cui.ms2(row["swap"]),
            cui.fmt_rate(tps),
        ])
        kinds.append("body")
    ui.add_table(slide, 0.42, 1.48, [1.15, 1.15, 1.55, 1.55, 1.55, 1.70, 1.45, 1.40], [head] + body, [0.36] + [0.46] * len(body), kinds, size=13)
    row = cui.pack(data["rows"][4]["pool30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M 这一批 HBM 上的 latent 是 0，池里的 latent 是 {cui.gb1(row['rest_c'])}。"
        f"换入 {cui.ms2(row['swap'])} 毫秒，MoE {cui.ms2(row['moe'])} 毫秒。\n"
        "全读还在 HBM 里。只有全读本身超过 315.7 GB 时，多出来的全读才进池。\n"
        "抽读字节远小于整段 latent，所以饼上的池很大，换入毫秒仍然可以短于 MoE。",
        14,
    )


def slide_tpot(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "30 毫秒无限池的最优批，TPOT 按项打开", "毫秒    ·    TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "换入是全部 latent 抽读加上溢出的全读，除以 3.6 TB/s。派发和合并仍用这条总线，权重用 HBM，GEMM 用 27.64 PFLOPS。")
    head = ["输入", "每卡", "HBM", "计算", "左", "换入", "派发", "权重", "GEMM", "合并", "MoE", "右", "TPOT"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["pool30"])
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
    row = cui.pack(data["rows"][4]["pool30"])[2]
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


def pool_slices(row):
    slices = [("HBM 全读", row["hbm_h"], cui.C_HOT)]
    if row["rest_h"] > 1e6:
        slices.append(("池中全读", row["rest_h"], cui.C_DDR))
    slices.append(("池中 latent", row["rest_c"], cui.C_LAT))
    return slices


def slide_pie_pool(prs, blank, data):
    columns = []
    for item in data["rows"]:
        tps, _n, row = cui.pack(item["pool30"])
        slices = pool_slices(row)
        columns.append((f"{cui.fmt_len(item['S'])}\nTPS {cui.fmt_rate(tps)}\n合计 {cui.gb_pie(cui.share(slices)[0])}", slices))
    cui.slide_pies(
        prs, blank, 7,
        "无限大池：HBM 只留全读，CSA latent 全在池里",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    饼旁是占比",
        "饼按存储字节。HBM 上没有 CSA latent。池中 latent 是整段 4320×S，换入只抽其中每层 1024 个位置。",
        columns,
        f"1M：{cui.occ_note(columns[4][1])}。\n4M：{cui.occ_note(columns[-1][1])}。\n"
        "全读留在 HBM。latent 的占比高，是因为它整段都在池里。",
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，无限大池放 CSA latent"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_decode(prs, blank, data, 3, "30", "30 毫秒内，无限池的系统 TPS 和主机、只放 HBM 比")
    slide_decode(prs, blank, data, 4, "10", "10 毫秒再收紧一次，仍取三条路径各自的最高系统 TPS")
    slide_place(prs, blank, data)
    slide_tpot(prs, blank, data)
    slide_pie_pool(prs, blank, data)
    host_cols = cui.pie_columns(data, "host30", lambda item, n, row: cui.parts_host(row))
    cui.slide_pies(
        prs, blank, 8,
        "对照：主机 CPU 卸载，latent 仍先填 HBM",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    这是原来的放法",
        "这一页不是无限池。全读先放 HBM，空位再放 CSA latent，放不下的进 CPU DDR。",
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
        "这一页不是无限池。没有外置池，CSA latent 和全读都在 HBM 里。",
        hbm_cols,
        f"64K 合计 {cui.gb_pie(tot64)}，CSA latent {pct64[3]:.1f}%。\n"
        f"4M 合计 {cui.gb_pie(tot4)}，CSA latent {pct4[3]:.1f}%。比例几乎不随长度变。",
    )
    prs.save(PPT)
    for item in data["rows"]:
        def brief(found):
            got = cui.pack(found)
            if got is None:
                return "none"
            return f"n={got[1]} t={got[2]['t']*1e3:.2f}ms tps={got[0]:.3e}"
        print(cui.fmt_len(item["S"]), "hbm30", brief(item["hbm30"]), "host30", brief(item["host30"]), "pool30", brief(item["pool30"]))


if __name__ == "__main__":
    main()
