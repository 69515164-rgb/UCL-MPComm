#!/usr/bin/env python3
"""Unlimited memory pool for CSA latent, four read bandwidths.

Full-read KV stays on HBM. Every latent byte is off HBM. The pool capacity
is unlimited. Read bandwidth is 3.6, 2.4, 1.2, or 0.6 TB/s. Search still
picks the batch with the highest system TPS inside the TPOT limit.
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
BWS = (3.6e12, 2.4e12, 1.2e12, 0.6e12)
LABELS = ("3.6", "2.4", "1.2", "0.6")
SLIDES = 9
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "CSA latent 全部进内存池    ·    容量不限    ·    3.6 / 2.4 / 1.2 / 0.6 TB/s    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-内存池不同带宽CSA LATENT-590A.pptx"


def bw_key(bw):
    return f"{bw / 1e12:.1f}"


def decode_pool(n, s, bw):
    """Full-read stays on HBM. Every CSA latent byte is read from the pool."""
    hot, cold, cold_read, t_hbm, t_ca = cui.attention_times(n, s)
    need_h = n * hot
    hbm_h = min(need_h, v4.ROOM_GPU)
    rest_h = need_h - hbm_h
    placed = {
        "hbm": t_hbm,
        "ca": t_ca,
        "n": n,
        "hbm_h": hbm_h,
        "hbm_c": 0.0,
        "rest_h": rest_h,
        "rest_c": n * cold,
        "b_hot": rest_h,
        "b_cold": n * cold_read,
    }
    return cui.finish(n, s, placed, (rest_h + n * cold_read) / bw, v4.N)


def collect():
    rows = []
    tps = lambda n, row: n * v4.N / row["t"]
    for s in v4.LENGTHS:
        item = {"S": s}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_hbm(n, s), tps)
            item[f"host{tag}"] = cui.search(limit, lambda n, s=s: cui.decode_host(n, s), tps)
            for bw in BWS:
                item[f"p{bw_key(bw)}{tag}"] = cui.search(
                    limit, lambda n, s=s, bw=bw: decode_pool(n, s, bw), tps
                )
        rows.append(item)
    return {"rows": rows}


def lift(new, old):
    if not new or not old or old[0] <= 0:
        return "—"
    return cui.signed_pct(new[0], old[0])


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "CSA latent 全部进内存池，读入带宽分四档", "N+2(cui)    ·    临时调整    ·    寻优仍是时限内取最大 TPS")
    ui.banner(slide, 0.92, "池的容量不限。四档只改读入带宽：3.6、2.4、1.2、0.6 TB/s。只放 HBM 和主机仍用原来的放法，用来对照。")
    head = ["项目", "这一版"]
    body = [
        ["集群", "Decode 256 NPU，32 台。每台 2 个 CPU，各接 4 个 NPU。TP=1，DP=256，EP=256"],
        ["算力 / HBM", f"每 NPU 27640 TFLOPS FP4。HBM 384 GB，38400 GB/s。KV 房间 {cui.gb1(v4.ROOM_GPU)}"],
        ["全读 KV", "CSA index、HCA、滑窗。先放 HBM。放不下的全读才从池里读"],
        ["CSA latent", "一字节都不留在 HBM。整段存在容量不限的内存池里"],
        ["读入", "四档：3.6、2.4、1.2、0.6 TB/s。换入 = (溢出的全读 + 全部 latent 抽读) / 这一档带宽"],
        ["对照", "只放 HBM：latent 能留在 HBM。主机：每卡 500 GB、200 GB/s，latent 先填 HBM 再进 CPU DDR"],
        ["时限", "TPOT ≤ 10 毫秒和 30 毫秒。时限内取系统 TPS 最大。TPS = 全局批 / TPOT"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.52] * len(body), kinds, size=14)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "时限内取吞吐最大，抽读整段按这一档带宽", "TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "进卡之后，这一步的 KV 仍按 HBM 38.4 TB/s 再读一次。换入只计池里的字节，和 MoE 取较大值。")
    head = ["", "式子"]
    body = [
        ["全读", "每条 (480 + 139.5)×S + 4,497,408。先占 HBM"],
        ["latent 存储", "每条 4320×S。四档都全部在池里，不占 HBM"],
        ["latent 抽读", "每条 30 层 × min(1024, S/4) × 576。这一段全部从池里读"],
        ["换入", "(溢出的全读 + 全部 latent 抽读) / 3.6、2.4、1.2 或 0.6 TB/s"],
        ["HBM", "(这一步要读的全部 KV + 19.35 GB) / 38.4 TB/s"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)"],
        ["选批", "在 TPOT ≤ 10 或 30 毫秒里，取全局批 / TPOT 最大的每卡条数"],
    ]
    kinds = ["head"] + ["key" if i in (3, 5) else "body" for i in range(len(body))]
    ui.add_table(slide, 0.42, 1.48, [2.15, 10.35], [head] + body, [0.32] + [0.48] * len(body), kinds, size=14)


def slide_tps(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    系统 TPS = 全局批 / TPOT    ·    全局批 = 每卡 × 256")
    ui.banner(slide, 0.92, "六列都是系统 TPS。只放 HBM 和主机是基线。四档内存池的差别只在读入带宽。")
    head = ["输入", "只放 HBM", "主机", "3.6 TB/s", "2.4 TB/s", "1.2 TB/s", "0.6 TB/s"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        cells = [cui.fmt_len(item["S"])]
        for key in ("hbm", "host"):
            got = cui.pack(item[f"{key}{tag}"])
            cells.append(cui.fmt_rate(got[0]) if got else "—")
        for label in LABELS:
            got = cui.pack(item[f"p{label}{tag}"])
            cells.append(cui.fmt_rate(got[0]) if got else "—")
        body.append(cells)
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    ui.add_table(slide, 0.42, 1.48, [1.35, 1.7, 1.7, 1.85, 1.85, 1.85, 1.85], [head] + body, [0.36] + [0.46] * len(body), kinds, size=13)
    one, four = data["rows"][4], data["rows"][-1]
    fast, slow = cui.pack(one[f"p3.6{tag}"]), cui.pack(one[f"p0.6{tag}"])
    host, hbm = cui.pack(one[f"host{tag}"]), cui.pack(one[f"hbm{tag}"])
    fast4, slow4 = cui.pack(four[f"p3.6{tag}"]), cui.pack(four[f"p0.6{tag}"])
    host4, hbm4 = cui.pack(four[f"host{tag}"]), cui.pack(four[f"hbm{tag}"])
    note = (
        f"1M：3.6 是 {cui.fmt_rate(fast[0])}，相对主机 {lift(fast, host)}，相对只放 HBM {lift(fast, hbm)}。"
        f"0.6 是 {cui.fmt_rate(slow[0])}，相对主机 {lift(slow, host)}，相对只放 HBM {lift(slow, hbm)}。\n"
        f"4M：3.6 是 {cui.fmt_rate(fast4[0])}，相对主机 {lift(fast4, host4)}，相对只放 HBM {lift(fast4, hbm4)}。"
        f"0.6 是 {cui.fmt_rate(slow4[0])}，相对主机 {lift(slow4, host4)}，相对只放 HBM {lift(slow4, hbm4)}。\n"
    )
    same = [
        cui.fmt_len(item["S"])
        for item in data["rows"]
        if all(cui.pack(item[f"p{label}10"])[1] == cui.pack(item[f"p{label}30"])[1] for label in LABELS)
    ]
    if len(same) == len(data["rows"]):
        note += "四档的七个长度，10 毫秒和 30 毫秒都是同一批。"
    elif same:
        note += f"{same[0]} 到 {same[-1]} 四档的 10 毫秒和 30 毫秒是同一批。更长的输入在 10 毫秒里要减批。"
    else:
        note += "四档在 10 毫秒和 30 毫秒都要分开选批。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_lift(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    提升 = 这一档系统 TPS / 基线系统 TPS − 1")
    ui.banner(slide, 0.92, "每一档分别对只放 HBM 和主机。正数是内存池更高，负数是基线更高。")
    head = ["输入", "3.6对HBM", "3.6对主机", "2.4对HBM", "2.4对主机", "1.2对HBM", "1.2对主机", "0.6对HBM", "0.6对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        hbm, host = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"])
        cells = [cui.fmt_len(item["S"])]
        for label in LABELS:
            got = cui.pack(item[f"p{label}{tag}"])
            cells.append(lift(got, hbm))
            cells.append(lift(got, host))
        body.append(cells)
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [1.15, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=13)
    one, four = data["rows"][4], data["rows"][-1]

    def pair(item):
        hbm, host = cui.pack(item[f"hbm{tag}"]), cui.pack(item[f"host{tag}"])
        bits = []
        for label in ("3.6", "0.6"):
            got = cui.pack(item[f"p{label}{tag}"])
            bits.append(f"{label} 对 HBM {lift(got, hbm)}、对主机 {lift(got, host)}")
        return "；".join(bits)

    k64 = data["rows"][0]
    h64, o64 = cui.pack(k64[f"hbm{tag}"]), cui.pack(k64[f"host{tag}"])
    a64, b64 = cui.pack(k64[f"p3.6{tag}"]), cui.pack(k64[f"p2.4{tag}"])
    ui.gold(
        slide,
        5.20,
        1.85,
        f"1M：{pair(one)}。\n4M：{pair(four)}。\n"
        f"64K：3.6 对 HBM {lift(a64, h64)}、对主机 {lift(a64, o64)}；"
        f"2.4 对 HBM {lift(b64, h64)}、对主机 {lift(b64, o64)}。",
        14,
    )


def slide_batch(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 7, "30 毫秒 TPS 最高的批，每卡条数和 TPOT", "毫秒    ·    四档带宽    ·    每卡")
    ui.banner(slide, 0.92, "带宽变低以后，换入变长，时限内装得下的批变小，或者同样的批因为换入更慢而 TPOT 变长。")
    head = ["输入", "3.6 每卡", "3.6 毫秒", "2.4 每卡", "2.4 毫秒", "1.2 每卡", "1.2 毫秒", "0.6 每卡", "0.6 毫秒"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        cells = [cui.fmt_len(item["S"])]
        for label in LABELS:
            got = cui.pack(item[f"p{label}30"])
            if got is None:
                cells.extend(("—", "—"))
            else:
                cells.extend((cui.fmt_bs(got[1]), cui.ms2(got[2]["t"])))
        body.append(cells)
        kinds.append("key" if item["S"] == 1048576 else "body")
    widths = [1.15, 1.35, 1.4, 1.35, 1.4, 1.35, 1.4, 1.35, 1.4]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=13)
    one = data["rows"][4]
    bits = []
    for label in LABELS:
        got = cui.pack(one[f"p{label}30"])
        bits.append(f"{label} 每卡 {cui.fmt_bs(got[1])} 条、{cui.ms2(got[2]['t'])} 毫秒、换入 {cui.ms2(got[2]['swap'])} 毫秒")
    ui.gold(slide, 5.20, 1.85, "1M：" + "。".join(bits[:2]) + "。\n" + "。".join(bits[2:]) + "。\n换入超过 MoE 之后，带宽直接加进 TPOT。", 14)


def slide_swap(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 8, "30 毫秒最优批，换入和 MoE 谁更长", "毫秒    ·    右 = max(换入, MoE)")
    ui.banner(slide, 0.92, "换入 = (溢出的全读 + 全部 latent 抽读) / 这一档带宽。右这一项和左边的 HBM、计算相加，得到 TPOT。")
    head = ["输入", "3.6 换入", "3.6 MoE", "3.6 TPOT", "1.2 换入", "1.2 MoE", "1.2 TPOT", "0.6 换入", "0.6 MoE", "0.6 TPOT"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        cells = [cui.fmt_len(item["S"])]
        for label in ("3.6", "1.2", "0.6"):
            got = cui.pack(item[f"p{label}30"])
            row = got[2]
            cells.extend((cui.ms2(row["swap"]), cui.ms2(row["moe"]), cui.ms2(row["t"])))
        body.append(cells)
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [1.05, 1.2, 1.15, 1.25, 1.2, 1.15, 1.25, 1.2, 1.15, 1.25]
    ui.add_table(slide, 0.32, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    row = cui.pack(data["rows"][4]["p3.630"])[2]
    slow = cui.pack(data["rows"][4]["p0.630"])[2]

    def side(got):
        return "换入" if got["swap"] >= got["moe"] else "MoE"

    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M、3.6：换入 {cui.ms2(row['swap'])} 毫秒，MoE {cui.ms2(row['moe'])} 毫秒，右取{side(row)}。"
        f"HBM {cui.ms2(row['hbm'])}，计算 {cui.ms2(row['ca'])}，TPOT {cui.ms2(row['t'])} 毫秒。\n"
        f"1M、0.6：换入 {cui.ms2(slow['swap'])} 毫秒，MoE {cui.ms2(slow['moe'])} 毫秒，右取{side(slow)}，"
        f"TPOT {cui.ms2(slow['t'])} 毫秒。\n"
        f"带宽从 3.6 降到 0.6，1M 的换入从 {cui.ms2(row['swap'])} 毫秒变成 {cui.ms2(slow['swap'])} 毫秒。",
        14,
    )


def pool_slices(row):
    slices = [("HBM 全读", row["hbm_h"], cui.C_HOT)]
    if row["rest_h"] > 1e6:
        slices.append(("池中全读", row["rest_h"], cui.C_DDR))
    slices.append(("池中 latent", row["rest_c"], cui.C_LAT))
    return slices


def slide_pie(prs, blank, data):
    columns = []
    for item in data["rows"]:
        tps, _n, row = cui.pack(item["p3.630"])
        slices = pool_slices(row)
        columns.append((f"{cui.fmt_len(item['S'])}\nTPS {cui.fmt_rate(tps)}\n合计 {cui.gb_pie(cui.share(slices)[0])}", slices))
    cui.slide_pies(
        prs, blank, 9,
        "3.6 TB/s 这一档：HBM 只留全读，latent 全在池里",
        "30 毫秒系统 TPS 最高的批    ·    每卡    ·    饼旁是占比",
        "饼按存储字节，画的是 3.6 TB/s 选中的批。另外三档的放法相同，每卡条数不同，所以每卡上的字节量不同。HBM 上没有 CSA latent。",
        columns,
        f"1M：{cui.occ_note(columns[4][1])}。\n4M：{cui.occ_note(columns[-1][1])}。\n"
        "换入只抽每层 1024 个位置，不读整段 latent。",
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4，内存池不同带宽放 CSA latent"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_tps(prs, blank, data, 3, "30", "30 毫秒内，四档内存池的系统 TPS 和两组基线")
    slide_lift(prs, blank, data, 4, "30", "30 毫秒，四档系统 TPS 相对只放 HBM 和主机的提升")
    slide_tps(prs, blank, data, 5, "10", "10 毫秒再收紧一次，仍取各档自己的最高系统 TPS")
    slide_lift(prs, blank, data, 6, "10", "10 毫秒，四档系统 TPS 相对只放 HBM 和主机的提升")
    slide_batch(prs, blank, data)
    slide_swap(prs, blank, data)
    slide_pie(prs, blank, data)
    prs.save(PPT)
    for item in data["rows"]:
        bits = [cui.fmt_len(item["S"])]
        for label in LABELS:
            got = cui.pack(item["p" + label + "30"])
            bits.append(f"{label} n={got[1]} t={got[2]['t']*1e3:.2f} swap={got[2]['swap']*1e3:.2f} tps={got[0]/1e4:.1f}")
        hbm, host = cui.pack(item["hbm30"]), cui.pack(item["host30"])
        bits.append(f"hbm {hbm[0]/1e4:.1f} host {host[0]/1e4:.1f}")
        print(" | ".join(bits))


if __name__ == "__main__":
    main()
