#!/usr/bin/env python3
"""Two-level pool with a sample-only double buffer.

One batch runs attention and MoE. The other batch runs the indexer, then
swaps in the sampled CSA latent. The buffer holds that sample, not the
stored latent. Full-read KV of both batches stays on HBM.
"""

from __future__ import annotations

import importlib.util

from pptx import Presentation
from pptx.util import Inches

spec = importlib.util.spec_from_file_location(
    "lat", "/agent/repos/ucl-mpcomm/docs/build_n2_cui_tier_latent_ppt.py"
)
lat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lat)

cui = lat.cui
ui = lat.ui
v4 = lat.v4
T1_BW = lat.T1_BW
T2_BW = lat.T2_BW
CACHE_CAP = lat.CACHE_CAP
CACHE_TOTAL = lat.CACHE_TOTAL
SLIDES = 6
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "抽读双缓冲    ·    cache 3.6 TB/s    ·    DDR 1.2 TB/s    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-两级池抽读双缓冲-590A.pptx"


def parts(s):
    sel = min(1024.0, s / 4.0)
    index_b = v4.N_CSA * (s / 4.0) * 64
    hca_b = v4.N_HCA * (s / 128.0) * 576
    sample = v4.N_CSA * sel * 576
    win = v4.FIXED
    hot, cold, cold_read = cui.hot_cold(s)
    return {
        "index": index_b,
        "hca": hca_b,
        "sample": sample,
        "win": win,
        "hot": hot,
        "cold": cold,
        "cold_read": cold_read,
        "idx_flops": v4.N_CSA * 4096 * s,
        "attn_flops": v4.N_HCA * 2048 * s + v4.N_CSA * 262144 * (sel + 128) + v4.PROJ,
    }


def decode_pipe(n, s):
    """One batch computes, the other indexes then swaps. n is one batch."""
    p = parts(s)
    # Both batches keep full-read KV. Each has one sample buffer.
    foot = 2 * n * (p["hot"] + p["sample"])
    if foot > v4.ROOM_GPU + 1.0:
        return None
    total_cold = 2 * n * p["cold"]
    in_cache = min(total_cold, CACHE_CAP)
    frac = in_cache / total_cold if total_cold else 0.0
    b_cache = n * p["cold_read"] * frac
    b_ddr = n * p["cold_read"] * (1.0 - frac)
    swap = b_cache / T1_BW + b_ddr / T2_BW
    al = v4.align(n)
    t_idx = max(n * p["index"] / v4.HBM_BW, n * p["idx_flops"] / (v4.PEAK * al))
    t_attn = max(
        (n * (p["hca"] + p["sample"] + p["win"]) + v4.ATTN) / v4.HBM_BW,
        n * p["attn_flops"] / (v4.PEAK * al),
    )
    moe = v4.expert(float(n * v4.N), v4.N)
    prep = t_idx + swap
    comp = t_attn + moe["t"]
    cycle = max(comp, prep)
    return {
        "n": n,
        "t": cycle,
        "idx": t_idx,
        "swap": swap,
        "attn": t_attn,
        "moe": moe["t"],
        "td": moe["td"],
        "tw": moe["tw"],
        "tg": moe["tg"],
        "tc": moe["tc"],
        "prep": prep,
        "comp": comp,
        "foot": foot,
        "hot_one": n * p["hot"],
        "index_one": n * p["index"],
        "sample_one": n * p["sample"],
        "cache_lat": in_cache,
        "ddr_lat": total_cold - in_cache,
        "b_cache": b_cache,
        "b_ddr": b_ddr,
    }


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"off{tag}"] = cui.search(limit, lambda n, s=s: lat.decode_off(n, s), tps)
            item[f"pipe{tag}"] = cui.search(limit, lambda n, s=s: decode_pipe(n, s), tps)
        rows.append(item)
    return {"rows": rows}


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "抽读放进双缓冲，一批算 attention+MoE，另一批换入", "N+2(cui)    ·    两级池不变    ·    寻优仍是时限内取最大 TPS")
    ui.banner(slide, 0.92, "缓冲里是这一步抽中的 1024 个 latent，不是整段 4.53 GB。换入批先做 indexer，再按选中的位置换入。")
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU。每卡 27640 TFLOPS FP4，HBM 384 GB、38400 GB/s。KV 房间 315.7 GB"],
        ["池", f"cache 合计 {CACHE_TOTAL / 1e9:.0f} GB，每卡 {CACHE_CAP / 1e9:.0f} GB，读入 3.6 TB/s。二级 DDR 不限，读入 1.2 TB/s"],
        ["常驻", "两批的全读 KV 都留在 HBM。CSA latent 整段仍在池里，不进双缓冲"],
        ["缓冲", "每批一份抽读。1M 每条 17.69 MB。两份一起算进 315.7 GB"],
        ["节拍", "节拍 = max(attention + MoE, indexer + 换入)。同一批里 indexer 先做完再换入"],
        ["吞吐", "稳态每拍完成一批。系统 TPS = 这一批条数 × 256 / 节拍。时限内取 TPS 最大的批"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.58] * len(body), kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "节拍取计算批和换入批的较大值", "indexer + 换入    ·    attention + MoE")
    ui.banner(slide, 0.92, "换入批还没做 attention。它只读 HBM 里的 CSA index，选出位置，再把抽读从池里写入另一块缓冲。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。两批都留在 HBM"],
        ["抽读", "每条 30 × min(1024, S/4) × 576。S ≥ 4K 时是 17.69 MB。缓冲只放这一段"],
        ["indexer", "max(本批 index 字节 / 38.4 TB/s, 30×4096×S 的计算)"],
        ["换入", "cache 中的抽读 / 3.6 TB/s + DDR 中的抽读 / 1.2 TB/s"],
        ["attention", "max(HCA、抽读、滑窗和 19.35 GB 权重的 HBM 读, 对应计算)"],
        ["节拍", "max(attention + MoE, indexer + 换入)"],
        ["容量", "2 × 每批条数 × (全读 + 抽读) ≤ 315.7 GB。放不下的批丢掉"],
    ]
    kinds = ["head"] + ["key" if i in (3, 5) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    系统 TPS = 这一批 × 256 / 节拍    ·    两级是不拆批的原结果")
    ui.banner(slide, 0.92, "两级列是一批自己做完 indexer、换入、attention、MoE。双缓冲列是两批错开，节拍取较慢的一边。")
    head = ["输入", "两级批", "两级毫秒", "两级 TPS", "双缓冲批", "双缓冲毫秒", "双缓冲 TPS", "相对两级"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        off, pipe = cui.pack(item[f"off{tag}"]), cui.pack(item[f"pipe{tag}"])

        def trip(got):
            if got is None:
                return "—", "—", "—"
            return cui.fmt_bs(got[1]), cui.ms2(got[2]["t"]), cui.fmt_rate(got[0])

        ob, ot, ors = trip(off)
        pb, pt, pr = trip(pipe)
        body.append([
            cui.fmt_len(item["S"]), ob, ot, ors, pb, pt, pr,
            cui.signed_pct(pipe[0], off[0]) if pipe and off else "—",
        ])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [1.15, 1.35, 1.45, 1.55, 1.55, 1.70, 1.70, 1.40]
    ui.add_table(slide, 0.42, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=13)
    one, four = data["rows"][4], data["rows"][-1]
    p1, o1 = cui.pack(one[f"pipe{tag}"]), cui.pack(one[f"off{tag}"])
    p4, o4 = cui.pack(four[f"pipe{tag}"]), cui.pack(four[f"off{tag}"])
    same = [cui.fmt_len(item["S"]) for item in data["rows"] if cui.pack(item["pipe10"])[1] == cui.pack(item["pipe30"])[1]]
    note = (
        f"1M：双缓冲每批 {cui.fmt_bs(p1[1])} 条、节拍 {cui.ms2(p1[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(p1[0])}。"
        f"不拆批是每卡 {cui.fmt_bs(o1[1])} 条、{cui.fmt_rate(o1[0])}，相对两级 {cui.signed_pct(p1[0], o1[0])}。\n"
        f"4M：双缓冲每批 {cui.fmt_bs(p4[1])} 条、节拍 {cui.ms2(p4[2]['t'])} 毫秒、系统 TPS {cui.fmt_rate(p4[0])}，"
        f"相对两级 {cui.signed_pct(p4[0], o4[0])}。\n"
    )
    p64, o64 = cui.pack(data["rows"][0][f"pipe{tag}"]), cui.pack(data["rows"][0][f"off{tag}"])
    if len(same) == len(data["rows"]):
        note += (
            f"七档 10 毫秒和 30 毫秒是同一批。节拍都在 3 毫秒上下，准备和计算刚打平，再加条数 TPS 下降。"
            f"64K 相对两级 {cui.signed_pct(p64[0], o64[0])}。"
        )
    elif same:
        note += f"{same[0]} 到 {same[-1]} 的 10 毫秒和 30 毫秒是同一批。"
    else:
        note += "七档的 10 毫秒和 30 毫秒都不是同一批。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_split(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "30 毫秒最优批，indexer 加换入和 attention 加 MoE 谁更长", "毫秒    ·    节拍 = max(两边)")
    ui.banner(slide, 0.92, "换入批：indexer 做完再换入，两边相加。计算批：attention 做完再做 MoE，两边相加。节拍取较大的那个。")
    head = ["输入", "每批", "indexer", "换入", "准备", "attention", "MoE", "计算", "节拍"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["pipe30"])
        body.append([
            cui.fmt_len(item["S"]), cui.fmt_bs(n),
            cui.ms2(row["idx"]), cui.ms2(row["swap"]), cui.ms2(row["prep"]),
            cui.ms2(row["attn"]), cui.ms2(row["moe"]), cui.ms2(row["comp"]),
            cui.ms2(row["t"]),
        ])
        kinds.append("key" if item["S"] == 1048576 else "body")
    ui.add_table(
        slide, 0.36, 1.48,
        [1.15, 1.05, 1.35, 1.20, 1.20, 1.50, 1.20, 1.20, 1.20],
        [head] + body, [0.36] + [0.46] * len(body), kinds, size=13,
    )
    row = cui.pack(data["rows"][4]["pipe30"])[2]
    side = "准备" if row["prep"] >= row["comp"] else "计算"
    ui.gold(
        slide,
        5.40,
        1.55,
        f"1M：indexer {cui.ms2(row['idx'])} 毫秒，换入 {cui.ms2(row['swap'])} 毫秒，准备 {cui.ms2(row['prep'])} 毫秒。"
        f"attention {cui.ms2(row['attn'])} 毫秒，MoE {cui.ms2(row['moe'])} 毫秒，计算 {cui.ms2(row['comp'])} 毫秒。\n"
        f"节拍取{side}这一边，{cui.ms2(row['t'])} 毫秒。"
        f"换入里 cache {cui.ms2(row['b_cache'] / T1_BW)} 毫秒，DDR {cui.ms2(row['b_ddr'] / T2_BW)} 毫秒。\n"
        "换入批的 index 有 503 MB/条，抽读只有 17.69 MB/条。准备时间长，主要是在读 index。",
        14,
    )


def slide_room(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "30 毫秒最优批，HBM 里是两份全读和两份抽读", "每卡    ·    房间 315.7 GB    ·    latent 整段在池里")
    ui.banner(slide, 0.92, "抽读缓冲是两批各一份。CSA latent 的整段不在这张表的 HBM 列里，只出现在 cache 和 DDR。")
    head = ["输入", "每批", "一份全读", "两份全读", "两份抽读", "HBM 合计", "cache latent", "DDR latent"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        _tps, n, row = cui.pack(item["pipe30"])
        body.append([
            cui.fmt_len(item["S"]),
            cui.fmt_bs(n),
            cui.gb1(row["hot_one"]),
            cui.gb1(2 * row["hot_one"]),
            cui.gb1(2 * row["sample_one"]),
            cui.gb1(row["foot"]),
            cui.gb1(row["cache_lat"]),
            cui.gb1(row["ddr_lat"]),
        ])
        kinds.append("body")
    ui.add_table(
        slide, 0.32, 1.48,
        [1.05, 1.00, 1.40, 1.45, 1.45, 1.45, 1.70, 1.55],
        [head] + body, [0.36] + [0.46] * len(body), kinds, size=12,
    )
    row = cui.pack(data["rows"][4]["pipe30"])[2]
    ui.gold(
        slide,
        5.40,
        1.55,
        f"1M 每批 {cui.fmt_bs(row['n'])} 条。一份全读 {cui.gb1(row['hot_one'])}，两份 {cui.gb1(2 * row['hot_one'])}。"
        f"两份抽读 {cui.gb1(2 * row['sample_one'])}。HBM 合计 {cui.gb1(row['foot'])}。\n"
        f"两批的整段 latent 共 {cui.gb1(row['cache_lat'] + row['ddr_lat'])}，"
        f"cache {cui.gb1(row['cache_lat'])}，DDR {cui.gb1(row['ddr_lat'])}。\n"
        f"HBM 还空着 {cui.gb1(v4.ROOM_GPU - row['foot'])}。条数停在这里是因为再加一条，系统 TPS 下降，不是房间先满。",
        14,
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，两级池抽读双缓冲"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_decode(prs, blank, data, 3, "30", "30 毫秒内，抽读双缓冲的系统 TPS 和不拆批的两级池比")
    slide_decode(prs, blank, data, 4, "10", "10 毫秒再收紧一次，仍取两条路径各自的最高系统 TPS")
    slide_split(prs, blank, data)
    slide_room(prs, blank, data)
    prs.save(PPT)
    for item in data["rows"]:
        def brief(found):
            got = cui.pack(found)
            if got is None:
                return "none"
            row = got[2]
            extra = ""
            if "prep" in row:
                extra = f" prep={row['prep']*1e3:.2f} comp={row['comp']*1e3:.2f} foot={row['foot']/1e9:.1f}"
            return f"n={got[1]} t={row['t']*1e3:.2f} tps={got[0]:.3e}{extra}"
        print(cui.fmt_len(item["S"]), "off30", brief(item["off30"]), "pipe30", brief(item["pipe30"]), "pipe10", brief(item["pipe10"]))


if __name__ == "__main__":
    main()
