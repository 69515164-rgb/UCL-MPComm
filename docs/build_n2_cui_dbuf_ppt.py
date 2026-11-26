#!/usr/bin/env python3
"""Two-level pool deck in the latent-pool slide format, with an HBM double buffer.

The buffer holds one step of sampled CSA latent, not the stored latent.
One batch runs attention and MoE. The other runs the indexer, then swaps.
Full-read KV of both batches stays on HBM. Latent fills the 162 GB cache,
then the unlimited DDR pool.
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
T1_BW = 3.6e12
T2_BW = 1.2e12
CACHE_TOTAL = 96 * 144 * 3 * 1e9
CACHE_CAP = CACHE_TOTAL / v4.N
SLIDES = 10
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "CSA latent 进两级池    ·    HBM 双缓冲只放抽读    ·    cache 3.6 TB/s    ·    DDR 1.2 TB/s    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-两级池放CSA LATENT HBM DB抽读-590A.pptx"


def ms_pair(cycle):
    """Round the cycle first, then double it, so 3.03 ms pairs with 6.06 ms."""
    shown = round(cycle * 1e3, 2)
    return f"{shown:.2f}", f"{shown * 2:.2f}"


def parts(s):
    sel = min(1024.0, s / 4.0)
    index_b = v4.N_CSA * (s / 4.0) * 64
    hca_b = v4.N_HCA * (s / 128.0) * 576
    sample = v4.N_CSA * sel * 576
    hot, cold, cold_read = cui.hot_cold(s)
    return {
        "index": index_b,
        "hca": hca_b,
        "sample": sample,
        "win": v4.FIXED,
        "hot": hot,
        "cold": cold,
        "cold_read": cold_read,
        "idx_flops": v4.N_CSA * 4096 * s,
        "attn_flops": v4.N_HCA * 2048 * s + v4.N_CSA * 262144 * (sel + 128) + v4.PROJ,
    }


def decode_db(n, s):
    """n is one batch. The other batch is the same size and stays resident."""
    p = parts(s)
    hot_one = n * p["hot"]
    sample_one = n * p["sample"]
    foot = 2 * (hot_one + sample_one)
    if foot > v4.ROOM_GPU + 1.0:
        return None
    total_cold = 2 * n * p["cold"]
    in_cache = min(total_cold, CACHE_CAP)
    frac = in_cache / total_cold if total_cold else 0.0
    b_cache = n * p["cold_read"] * frac
    b_ddr = n * p["cold_read"] * (1.0 - frac)
    swap = b_cache / T1_BW + b_ddr / T2_BW
    al = v4.align(n)
    idx_hbm = n * p["index"] / v4.HBM_BW
    idx_cmp = n * p["idx_flops"] / (v4.PEAK * al)
    t_idx = max(idx_hbm, idx_cmp)
    t_hbm = (n * (p["hca"] + p["sample"] + p["win"]) + v4.ATTN) / v4.HBM_BW
    t_ca = n * p["attn_flops"] / (v4.PEAK * al)
    t_attn = max(t_hbm, t_ca)
    moe = v4.expert(float(n * v4.N), v4.N)
    # Indexer and attention share one HBM and one cube, so attention waits.
    # Swap uses the pool port and runs beside attention + MoE.
    comp = t_attn + moe["t"]
    tail = max(swap, comp)
    return {
        "n": n,
        "t": t_idx + tail,
        "idx": t_idx,
        "idx_hbm": idx_hbm,
        "idx_cmp": idx_cmp,
        "swap": swap,
        "attn": t_attn,
        "hbm": t_hbm,
        "ca": t_ca,
        "moe": moe["t"],
        "td": moe["td"],
        "tw": moe["tw"],
        "tg": moe["tg"],
        "tc": moe["tc"],
        "prep": t_idx + swap,
        "comp": comp,
        "tail": tail,
        "foot": foot,
        "hbm_h": 2 * hot_one,
        "hbm_c": 2 * sample_one,
        "t1_h": 0.0,
        "t1_c": in_cache,
        "t2_h": 0.0,
        "t2_c": total_cold - in_cache,
        "b1": b_cache,
        "b2": b_ddr,
    }


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_hbm(n, s), tps)
            item[f"host{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_host(n, s), tps)
            def db_ok(n, s=s, limit=limit):
                row = decode_db(n, s)
                if row is None or 2 * row["t"] > limit + 1e-12:
                    return None
                return row

            item[f"db{tag}"] = cui.search(limit, db_ok, tps)
        rows.append(item)
    return {"rows": rows}


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "CSA latent 进两级池，HBM 双缓冲只放抽读", "N+2(cui)    ·    临时调整    ·    寻优仍是时限内取最大 TPS")
    ui.banner(
        slide,
        0.92,
        f"在网 cache 合计 96×144×3 = {CACHE_TOTAL / 1e9:.0f} GB，每卡 {CACHE_CAP / 1e9:.0f} GB，读入 3.6 TB/s。二级 DDR 不限，读入 1.2 TB/s。",
    )
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU，32 台。每台 2 个 CPU，各接 4 个 NPU。TP=1，DP=256，EP=256"],
        ["算力 / HBM", f"每 NPU 27640 TFLOPS FP4。HBM 384 GB，38400 GB/s。KV 房间 {cui.gb1(v4.ROOM_GPU)}"],
        ["全读 KV", "CSA index、HCA、滑窗。两批都留在 HBM。放不下的批丢掉"],
        ["CSA latent", f"整段一字节都不留在 HBM。先填每卡 {CACHE_CAP / 1e9:.0f} GB 在网 cache，剩下的进二级 DDR"],
        ["双缓冲", "每批一份抽读，只放这一步抽中的 1024 个 latent。1M 每条 17.69 MB。两份一起算进房间"],
        ["节拍", "节拍 = indexer + max(换入, attention + MoE)。一条 TPOT 是连续两拍。系统 TPS = 这一批 × 256 / 节拍"],
        ["对照", "只放 HBM：latent 能留在 HBM。主机：每卡 500 GB、200 GB/s。时限内取系统 TPS 最大"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_formula(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "系统吞吐用节拍去除这一批，也等于用一条 TPOT 去除两批", "节拍 = indexer + max(换入, attention + MoE)    ·    一条 TPOT = 连续两拍")
    ui.banner(slide, 0.92, "indexer 和 attention 共用一条 HBM、一块算力，所以 indexer 先做完。换入走池，和后一批的 attention、MoE 同时。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。两批都留在 HBM"],
        ["latent 存储", f"每条 4320×S。整段不在 HBM。两批一起先填每卡 {CACHE_CAP / 1e9:.0f} GB cache，再进二级 DDR"],
        ["抽读", "每条 30 层 × min(1024, S/4) × 576。S ≥ 4K 时是 17.69 MB。缓冲只放这一段"],
        ["换入", "cache 中的抽读 / 3.6 TB/s + DDR 中的抽读 / 1.2 TB/s"],
        ["indexer", "max(本批 index 字节 / 38.4 TB/s, 30×4096×S 的计算)"],
        ["节拍", "indexer + max(换入, attention + MoE)。这一拍有一批吐出 token"],
        ["一条 TPOT", "连续两拍。同一条请求这一拍做 indexer 和换入，下一拍做 attention 和 MoE"],
        ["系统 TPS", "这一批 × 256 / 节拍 = 两批 × 256 / 一条 TPOT。分子和分母一起加倍，是同一个数"],
    ]
    kinds = ["head"] + ["key" if i in (5, 6, 7) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.46, [2.15, 10.35], [head] + body, [0.28] + [0.42] * len(body), kinds, size=13)
    _tps, n, row = cui.pack(data["rows"][4]["db30"])
    cycle, tpot = ms_pair(row["t"])
    ui.gold(
        slide,
        5.40,
        1.55,
        f"1M 每卡 {cui.fmt_bs(n)} 条。节拍 {cycle} 毫秒，一条 TPOT {tpot} 毫秒。\n"
        f"系统 TPS = {cui.fmt_bs(n)}×256 / {cycle} 毫秒"
        f" = 2×{cui.fmt_bs(n)}×256 / {tpot} 毫秒"
        f" = {cui.fmt_rate(_tps)}。\n"
        "只把分母换成一条 TPOT、分子仍用一批，会把常驻的另一批漏掉。",
        14,
    )


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"一条 TPOT ≤ {tag} 毫秒    ·    系统 TPS = 这一批 × 256 / 节拍 = 两批 × 256 / 一条 TPOT")
    ui.banner(slide, 0.92, "DB 列的毫秒是节拍。一条 TPOT 是连续两拍。系统 TPS 用节拍去除这一批，等于用一条 TPOT 去除两批。")
    head = ["输入", "HBM 批", "HBM TPS", "主机批", "主机毫秒", "主机 TPS", "DB 批", "节拍", "DB TPS", "相对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        hbm, host, db = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"]), cui.pack(item[f"db{tag}"])

        def trip(got):
            if got is None:
                return "—", "—", "—"
            return cui.fmt_bs(got[1] * v4.N), cui.ms2(got[2]["t"]), cui.fmt_rate(got[0])

        hb, _ht, hr = trip(hbm)
        ob, ot, ors = trip(host)
        pb, pt, pr = trip(db)
        body.append([
            cui.fmt_len(item["S"]), hb, hr, ob, ot, ors, pb, pt, pr,
            cui.signed_pct(db[0], host[0]) if db and host else "—",
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.95, 1.15, 1.25, 1.15, 1.20, 1.25, 1.20, 1.35, 1.40, 1.30]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    one, four = data["rows"][4], data["rows"][-1]
    o1, h1 = cui.pack(one[f"db{tag}"]), cui.pack(one[f"host{tag}"])
    o4, h4 = cui.pack(four[f"db{tag}"]), cui.pack(four[f"host{tag}"])
    c1, p1 = ms_pair(o1[2]["t"])
    c4, p4 = ms_pair(o4[2]["t"])
    note = (
        f"1M：节拍 {c1} 毫秒，一条 TPOT {p1} 毫秒。"
        f"系统 TPS = {cui.fmt_bs(o1[1])}×256 / {c1} 毫秒"
        f" = 2×{cui.fmt_bs(o1[1])}×256 / {p1} 毫秒"
        f" = {cui.fmt_rate(o1[0])}，相对主机 {cui.signed_pct(o1[0], h1[0])}。\n"
        f"4M：节拍 {c4} 毫秒，一条 TPOT {p4} 毫秒，"
        f"系统 TPS {cui.fmt_rate(o4[0])}，相对主机 {cui.signed_pct(o4[0], h4[0])}。\n"
    )
    same, diff = [], []
    for item in data["rows"]:
        name = cui.fmt_len(item["S"])
        if cui.pack(item["db10"])[1] == cui.pack(item["db30"])[1]:
            same.append(name)
        else:
            diff.append((name, cui.pack(item["db10"]), cui.pack(item["db30"])))
    if same and diff:
        note += f"{same[0]} 到 {same[-1]} 一条 TPOT 在 10 毫秒以内，两档是同一批。{diff[0][0]} 起 10 毫秒要把批减小。"
    elif not diff:
        longest = max(2 * cui.pack(item[f"db{tag}"])[2]["t"] for item in data["rows"])
        note += f"七档一条 TPOT 最长 {cui.ms2(longest)} 毫秒，10 毫秒和 30 毫秒是同一批。"
    else:
        note += "七档在 10 毫秒和 30 毫秒都要分开选批。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒 TPS 最高的批，抽读在 HBM，整段 latent 在池里", "系统 TPS = 这一批 × 256 / 节拍 = 两批 × 256 / 一条 TPOT    ·    每卡")
    ui.banner(slide, 0.92, "HBM 全读是两批加在一起。HBM 抽读是两份缓冲。cache 上限每卡 162 GB，读入 3.6 TB/s。DDR 不限，读入 1.2 TB/s。")
    head = ["输入", "每卡", "HBM 全读", "HBM 抽读", "cache latent", "DDR latent", "换入毫秒", "TPS"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        tps, n, row = cui.pack(item["db30"])
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
    row = cui.pack(data["rows"][4]["db30"])[2]
    row4 = cui.pack(data["rows"][-1]["db30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：HBM 全读 {cui.gb1(row['hbm_h'])}，HBM 抽读 {cui.gb1(row['hbm_c'])}，"
        f"cache {cui.gb1(row['t1_c'])}，DDR {cui.gb1(row['t2_c'])}。换入 {cui.ms2(row['swap'])} 毫秒。\n"
        f"4M：HBM 全读 {cui.gb1(row4['hbm_h'])}，抽读 {cui.gb1(row4['hbm_c'])}，"
        f"cache {cui.gb1(row4['t1_c'])}，DDR {cui.gb1(row4['t2_c'])}，换入 {cui.ms2(row4['swap'])} 毫秒。\n"
        f"1M 换入拆开是 cache {cui.ms2(row['b1'] / T1_BW)} 毫秒，DDR {cui.ms2(row['b2'] / T2_BW)} 毫秒。"
        f"4M 是 cache {cui.ms2(row4['b1'] / T1_BW)} 毫秒，DDR {cui.ms2(row4['b2'] / T2_BW)} 毫秒。",
        14,
    )


def slide_tpot(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "30 毫秒双缓冲的最优批，节拍按项打开", "毫秒    ·    节拍 = indexer + max(换入, attention + MoE)")
    ui.banner(slide, 0.92, "indexer 先占 HBM 和算力。随后换入走池，和 attention、MoE 同时。后段取这两边的较大值。")
    head = ["输入", "每卡", "indexer", "attention", "MoE", "换入", "后段", "节拍"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["db30"])
        body.append([
            cui.fmt_len(item["S"]), cui.fmt_bs(n),
            cui.ms2(row["idx"]), cui.ms2(row["attn"]), cui.ms2(row["moe"]), cui.ms2(row["swap"]),
            cui.ms2(row["tail"]), cui.ms2(row["t"]),
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    ui.add_table(
        slide, 0.42, 1.48,
        [1.25, 1.15, 1.45, 1.55, 1.35, 1.35, 1.55, 1.45],
        [head] + body, [0.36] + [0.46] * len(body), kinds, size=13,
    )
    _tps6, _n6, row = cui.pack(data["rows"][4]["db30"])
    c, p = ms_pair(row["t"])
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M：indexer {cui.ms2(row['idx'])} 毫秒，其中 HBM 读 {cui.ms2(row['idx_hbm'])}、算力 {cui.ms2(row['idx_cmp'])}。"
        f"attention {cui.ms2(row['attn'])}，MoE {cui.ms2(row['moe'])}，换入 {cui.ms2(row['swap'])}。\n"
        f"后段取 max(换入, attention + MoE) = {cui.ms2(row['tail'])}。节拍 {c} 毫秒，一条 TPOT {p} 毫秒。"
        f"系统 TPS = {cui.fmt_bs(row['n'])}×256 / {c} 毫秒"
        f" = 2×{cui.fmt_bs(row['n'])}×256 / {p} 毫秒 = {cui.fmt_rate(_tps6)}。",
        14,
    )


def db_slices(row):
    slices = [("HBM 全读", row["hbm_h"], cui.C_HOT)]
    if row["hbm_c"] > 1e6:
        slices.append(("HBM 抽读", row["hbm_c"], cui.C_COLD))
    if row["t1_c"] > 1e6:
        slices.append(("cache latent", row["t1_c"], cui.C_CACHE))
    if row["t2_c"] > 1e6:
        slices.append(("DDR latent", row["t2_c"], cui.C_LAT))
    return slices


def slide_pie(prs, blank, data):
    columns = []
    for item in data["rows"]:
        tps, _n, row = cui.pack(item["db30"])
        slices = db_slices(row)
        columns.append((f"{cui.fmt_len(item['S'])}\nTPS {cui.fmt_rate(tps)}\n合计 {cui.gb_pie(cui.share(slices)[0])}", slices))
    cui.slide_pies(
        prs, blank, 7,
        "双缓冲：HBM 留两份全读和两份抽读，latent 分在 cache 和 DDR",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    饼旁是占比",
        f"饼按存储字节，两批都算在内。HBM 上没有整段 CSA latent。cache 每卡最多 {CACHE_CAP / 1e9:.0f} GB，读入 3.6 TB/s。超出的整段 latent 进二级 DDR，读入 1.2 TB/s。",
        columns,
        f"1M：{cui.occ_note(columns[4][1])}。\n4M：{cui.occ_note(columns[-1][1])}。\n"
        "抽读是两份缓冲，相对整段 latent 很小。cache 按 3.6 TB/s 读，DDR 按 1.2 TB/s 读。",
    )


def _seg(slide, x, y, w, h, fill, label, color):
    if w < 0.04:
        return
    shape = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    ui.solid(shape, fill)
    if w >= 0.70 and label:
        ui.textbox(slide, x + 0.02, y, w - 0.04, h, label, 11 if w >= 1.05 else 9, True, color, ui.PP_ALIGN.CENTER)


def _bar(slide, x, y, w, h, parts, cycle):
    cursor = x
    for sec, fill, label, color in parts:
        sw = w * sec / cycle
        _seg(slide, cursor, y, sw, h, fill, label, color)
        cursor += sw


def _sides(row, compute):
    """compute=True means this row waits, then runs attention and MoE."""
    idx, attn, moe, swap = row["idx"], row["attn"], row["moe"], row["swap"]
    pad = abs(swap - (attn + moe))
    if compute:
        parts = [
            (idx, "E6EBEF", "等 HBM", ui.NAVY),
            (attn, "0E7A76", f"attention\n{cui.ms2(attn)}", ui.WHITE),
            (moe, "1B4F8A", f"MoE\n{cui.ms2(moe)}", ui.WHITE),
        ]
        if swap > attn + moe:
            parts.append((pad, "F4F7FA", "", ui.NAVY))
    else:
        parts = [
            (idx, "3D7CC9", f"indexer\n{cui.ms2(idx)}", ui.WHITE),
            (swap, "E07A3D", f"换入\n{cui.ms2(swap)}", ui.WHITE),
        ]
        if attn + moe > swap:
            parts.append((pad, "F4F7FA", "", ui.NAVY))
    return parts


def slide_timeline(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    _tps, n, row = cui.pack(data["rows"][4]["db30"])
    cycle_s = row["t"]
    cycle, tpot = ms_pair(cycle_s)
    ui.chrome(
        slide, 10,
        "indexer 先做完，换入再盖住 attention 和 MoE",
        f"1M 每卡 {cui.fmt_bs(n)} 条    ·    节拍 {cycle} 毫秒    ·    一条 TPOT {tpot} 毫秒",
    )
    ui.banner(slide, 0.92, "计算批在 indexer 期间等 HBM。indexer 结束后，换入走池的口，attention 和 MoE 同时开始。每一拍结束，计算批吐出一个 token。")
    x0, slot_w, gap = 1.85, 3.55, 0.12
    y_a, y_b, bar_h = 1.98, 3.12, 0.78
    slots = [("第 1 拍", True, "甲吐出 token"), ("第 2 拍", False, "乙吐出 token"), ("第 3 拍", True, "甲再吐出 token")]
    ui.textbox(slide, 0.28, y_a, 1.50, bar_h, "甲批", 14, True, ui.NAVY, ui.PP_ALIGN.RIGHT)
    ui.textbox(slide, 0.28, y_b, 1.50, bar_h, "乙批", 14, True, ui.NAVY, ui.PP_ALIGN.RIGHT)
    for i, (title, jia_computes, token) in enumerate(slots):
        x = x0 + i * (slot_w + gap)
        ui.textbox(slide, x, 1.48, slot_w, 0.26, f"{title}    {cycle} 毫秒", 13, True, ui.NAVY, ui.PP_ALIGN.CENTER)
        _bar(slide, x, y_a, slot_w, bar_h, _sides(row, jia_computes), cycle_s)
        tail_x = x + slot_w * row["idx"] / cycle_s
        tail_w = slot_w * row["tail"] / cycle_s
        ui.textbox(slide, tail_x, y_a + bar_h, tail_w, 0.24, "同时", 11, True, ui.TEAL, ui.PP_ALIGN.CENTER)
        _bar(slide, x, y_b, slot_w, bar_h, _sides(row, not jia_computes), cycle_s)
        ui.textbox(slide, x, y_b + bar_h + 0.02, slot_w, 0.26, token, 12, True, ui.GOLD, ui.PP_ALIGN.CENTER)
    ui.textbox(
        slide, x0 + slot_w, 4.28, 2 * slot_w + gap, 0.26,
        f"甲相邻两个 token 的间隔 = 一条 TPOT = {tpot} 毫秒",
        13, True, ui.GOLD, ui.PP_ALIGN.CENTER,
    )
    legend = [
        ("E6EBEF", "等 HBM"),
        ("3D7CC9", "indexer"),
        ("E07A3D", "换入"),
        ("0E7A76", "attention"),
        ("1B4F8A", "MoE"),
    ]
    for i, (color, name) in enumerate(legend):
        lx = 1.55 + i * 2.15
        sw = slide.shapes.add_shape(ui.MSO_SHAPE.RECTANGLE, Inches(lx), Inches(4.64), Inches(0.26), Inches(0.20))
        ui.solid(sw, color)
        ui.textbox(slide, lx + 0.32, 4.58, 1.7, 0.30, name, 12, False, ui.INK)
    ui.gold(
        slide,
        5.10,
        1.90,
        f"第 1 拍乙先做 indexer {cui.ms2(row['idx'])} 毫秒。这段 HBM 读是 {cui.ms2(row['idx_hbm'])} 毫秒，算力只有 {cui.ms2(row['idx_cmp'])} 毫秒，甲只能等。\n"
        f"随后乙换入 {cui.ms2(row['swap'])} 毫秒，甲同时做 attention {cui.ms2(row['attn'])} 毫秒和 MoE {cui.ms2(row['moe'])} 毫秒。换入走池，不占这 38.4 TB/s。\n"
        f"节拍 {cycle} 毫秒，一条 TPOT {tpot} 毫秒。系统 TPS = {cui.fmt_bs(n)}×256 / {cycle} 毫秒"
        f" = 2×{cui.fmt_bs(n)}×256 / {tpot} 毫秒 = {cui.fmt_rate(_tps)}。",
        14,
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，两级池放 CSA latent，HBM 双缓冲抽读"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank, data)
    slide_decode(prs, blank, data, 3, "30", "30 毫秒内，抽读双缓冲的系统 TPS 和主机、只放 HBM 比")
    slide_decode(prs, blank, data, 4, "10", "10 毫秒再收紧一次，仍取三条路径各自的最高系统 TPS")
    slide_place(prs, blank, data)
    slide_tpot(prs, blank, data)
    slide_pie(prs, blank, data)
    host_cols = cui.pie_columns(data, "host30", lambda item, n, row: cui.parts_host(row))
    cui.slide_pies(
        prs, blank, 8,
        "对照：主机 CPU 卸载，latent 仍先填 HBM",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    这是原来的放法",
        "这一页不是双缓冲。全读先放 HBM，空位再放 CSA latent，放不下的进 CPU DDR。",
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
        "这一页没有两级池，也没有双缓冲。CSA latent 和全读都在 HBM 里，放不下就减批。",
        hbm_cols,
        f"64K 合计 {cui.gb_pie(tot64)}，CSA latent {pct64[3]:.1f}%。\n"
        f"4M 合计 {cui.gb_pie(tot4)}，CSA latent {pct4[3]:.1f}%。比例几乎不随长度变。",
    )
    slide_timeline(prs, blank, data)
    prs.save(PPT)
    for item in data["rows"]:
        def brief(found):
            got = cui.pack(found)
            if got is None:
                return "none"
            row = got[2]
            extra = ""
            if "prep" in row:
                extra = f" prep={row['prep']*1e3:.2f} comp={row['comp']*1e3:.2f}"
            return f"n={got[1]} t={row['t']*1e3:.2f} tps={got[0]:.3e}{extra}"
        print(
            cui.fmt_len(item["S"]),
            "db30", brief(item["db30"]),
            "host30", brief(item["host30"]),
            "hbm30", brief(item["hbm30"]),
        )


if __name__ == "__main__":
    main()
