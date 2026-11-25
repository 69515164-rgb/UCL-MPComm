#!/usr/bin/env python3
"""N+2(cui) 20T V4, two-level KV pool, same method as the 590A deck.

Rates below are the numbers used in the timing. They are not multiplied
by another 70% or 80%.

Per CPU: DDR 2 TB/s and 2 TB, attached to 4 NPUs.
Per NPU host path: min(H2D 1.6 Tb/s, DDR/4) = 200 GB/s, 500 GB.
Both pool tiers move at 6.4 Tb/s per NPU. The cache only adds a 27 GB
capacity window in front of the unlimited DDR pool.
"""

from __future__ import annotations

import importlib.util

from pptx import Presentation
from pptx.util import Inches

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

# Given simulation rates. Byte rates are decimal (TB/s = 1e12 B/s).
v4.HBM_CAP = 384e9
v4.HBM_BW = 38400e9
v4.PEAK = 27640e12
v4.D2D = 3.6e12
v4.ROOM_GPU = v4.HBM_CAP - v4.ROUTED / v4.EP - v4.SHARED - v4.ATTN / v4.TP - v4.RESERVE
v4.PF_ROOM = v4.HBM_CAP - v4.ROUTED / v4.PF_EP - v4.SHARED - v4.ATTN / v4.PF_TP - v4.RESERVE

H2D_BW = 1.6e12 / 8
DDR_NODE_BW = 2e12
DDR_NODE_CAP = 2e12
GPU_PER_CPU = 4
DDR_BW = DDR_NODE_BW / GPU_PER_CPU
DDR_CAP = DDR_NODE_CAP / GPU_PER_CPU
HOST_BW = min(H2D_BW, DDR_BW)
POOL_BW = 6.4e12 / 8
T1_TOTAL = 6912e9
T1_CAP = T1_TOTAL / v4.N
T1_BW = POOL_BW
T2_BW = POOL_BW
BW_25 = 1.6e12 / 8 * 0.25
BW_100 = 1.6e12 / 8
HIT = 0.995
TTFT_LIMIT = 10.0
TIE = 1e-4
NPU_PER_SERVER = 8

SLIDES = 8
FOOTER = (
    "N+2(cui)    ·    20T V4    ·    Decode 256 卡 TP=1    ·    "
    "cache 6912 GB    ·    池带宽每卡 6.4 Tb/s    ·    TTFT 10 秒    ·    TPOT 10/30 毫秒"
)
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
PPT = "/agent/repos/ucl-mpcomm/docs/N+2(cui)-20T-V4-两级池-590A.pptx"


def hot_cold(s):
    hot = (480.0 + 139.5) * s + v4.FIXED
    cold = 4320.0 * s
    cold_read = v4.N_CSA * min(1024.0, s / 4.0) * 576
    return hot, cold, cold_read


def attention_times(n, s):
    hot, cold, cold_read = hot_cold(s)
    sel = min(1024.0, s / 4.0)
    score = v4.N_CSA * 4096 * s + v4.N_HCA * 2048 * s + v4.N_CSA * 262144 * (sel + 128)
    read = n * v4.n_read(s)
    t_hbm = (read + v4.ATTN) / v4.HBM_BW
    t_ca = n * (score + v4.PROJ) / (v4.PEAK * v4.align(n))
    return hot, cold, cold_read, t_hbm, t_ca


def place(n, s, cap):
    """Hot stays on HBM. Cold fills the rest, then `cap` bytes of the next tier."""
    hot, cold, cold_read, t_hbm, t_ca = attention_times(n, s)
    need_h = n * hot
    need_c = n * cold
    hbm_h = min(need_h, v4.ROOM_GPU)
    hbm_c = min(need_c, v4.ROOM_GPU - hbm_h)
    rest_h = need_h - hbm_h
    rest_c = need_c - hbm_c
    off = rest_h + rest_c
    if cap is not None and off > cap + 1.0:
        return None
    b_hot = n * hot * (rest_h / need_h) if need_h else 0.0
    b_cold = n * cold_read * (rest_c / need_c) if need_c else 0.0
    return {
        "hbm": t_hbm,
        "ca": t_ca,
        "n": n,
        "hbm_h": hbm_h,
        "hbm_c": hbm_c,
        "rest_h": rest_h,
        "rest_c": rest_c,
        "b_hot": b_hot,
        "b_cold": b_cold,
        "off": off,
    }


def finish(n, s, placed, swap, ng):
    moe = v4.expert(float(n * ng), ng)
    other = max(placed["hbm"], placed["ca"])
    placed.update(
        {
            "t": other + max(swap, moe["t"]),
            "swap": swap,
            "moe": moe["t"],
            "td": moe["td"],
            "tw": moe["tw"],
            "tg": moe["tg"],
            "tc": moe["tc"],
        }
    )
    return placed


def decode_tier(n, s):
    placed = place(n, s, None)
    rest_h, rest_c = placed["rest_h"], placed["rest_c"]
    t1_h = min(rest_h, T1_CAP)
    t1_c = min(rest_c, T1_CAP - t1_h)
    t2_h = rest_h - t1_h
    t2_c = rest_c - t1_c
    need_h = n * hot_cold(s)[0]
    need_c = n * hot_cold(s)[1]
    cold_read = hot_cold(s)[2]
    b1 = b2 = 0.0
    if need_h:
        b1 += n * hot_cold(s)[0] * (t1_h / need_h)
        b2 += n * hot_cold(s)[0] * (t2_h / need_h)
    if need_c:
        b1 += n * cold_read * (t1_c / need_c)
        b2 += n * cold_read * (t2_c / need_c)
    placed["t1_h"] = t1_h
    placed["t1_c"] = t1_c
    placed["t2_h"] = t2_h
    placed["t2_c"] = t2_c
    placed["b1"] = b1
    placed["b2"] = b2
    return finish(n, s, placed, b1 / T1_BW + b2 / T2_BW, v4.N)


def decode_host(n, s):
    placed = place(n, s, DDR_CAP)
    if placed is None:
        return None
    swap = (placed["b_hot"] + placed["b_cold"]) / HOST_BW
    return finish(n, s, placed, swap, v4.N)


def decode_hbm(n, s):
    placed = place(n, s, 0.0)
    if placed is None:
        return None
    return finish(n, s, placed, 0.0, v4.N)


def prefill(n, s, bw):
    if n * v4.store_seq(s) > v4.PF_ROOM + 1.0:
        return None
    bs = n * v4.PF_DP
    p, q = HIT * s, (1.0 - HIT) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    flops = (
        v4.N_CSA * 4096 * context
        + v4.N_HCA * 2048 * context
        + v4.N_CSA * 262144 * (1024 + 128) * q
        + v4.PROJ * q
    )
    t_compute = n * flops / (v4.PEAK * v4.align(rows))
    prefix_bytes = p * v4.BPT + v4.L * min(p, 128) * 576
    t_pull = n * prefix_bytes / bw
    t_hbm = (v4.ATTN + n * (v4.store_seq(s) + q * v4.BPT)) / v4.HBM_BW
    moe = v4.expert(bs * q, v4.PF_N)
    body = t_pull + max(t_hbm, t_compute) + moe["t"]
    tail = max(0.0, n * v4.store_seq(s) / bw - body * (v4.L - 1) / v4.L)
    return {
        "t": body + tail,
        "pull": t_pull,
        "hbm": t_hbm,
        "compute": t_compute,
        "moe": moe["t"],
        "tail": tail,
        "n": n,
        "bs": bs,
        "kv": n * v4.store_seq(s),
    }


def _keep(best, tps, n, row):
    if best is None or tps > best[3] * (1.0 + 1e-12):
        return (tps, n, row, tps)
    if tps >= best[3] * (1.0 - TIE) and n > best[1]:
        return (tps, n, row, best[3])
    return best


def search(limit, fn, tps_of):
    best = None
    n = 1
    while n < 200000:
        row = fn(n)
        if row is None or row["t"] > limit + 1e-12:
            break
        best = _keep(best, tps_of(n, row), n, row)
        n += 1
    return best


def collect():
    rows = []
    for s in v4.LENGTHS:
        item = {"S": s}
        for key, bw in (("p25", BW_25), ("p100", BW_100)):
            item[key] = search(TTFT_LIMIT, lambda n, s=s, bw=bw: prefill(n, s, bw), lambda n, row: row["bs"] * s / row["t"])
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = search(limit, lambda n, s=s: decode_hbm(n, s), lambda n, row: n * v4.N / row["t"])
            item[f"host{tag}"] = search(limit, lambda n, s=s: decode_host(n, s), lambda n, row: n * v4.N / row["t"])
            item[f"tier{tag}"] = search(limit, lambda n, s=s: decode_tier(n, s), lambda n, row: n * v4.N / row["t"])
        rows.append(item)
    return {"rows": rows}


def fmt_len(s):
    return v4.fmt_len(s)


def fmt_bs(n):
    return v4.fmt_bs(n)


def fmt_rate(v):
    return v4.fmt_rate(v)


def signed_pct(new, old):
    return v4.signed_pct(new, old)


def ms2(v):
    return f"{v * 1e3:.2f}"


def gb1(n):
    if n >= 1e12:
        return f"{n / 1e12:.2f} TB"
    return f"{n / 1e9:.1f} GB"


def pack(found):
    if found is None:
        return None
    tps, n, row, _peak = found
    return tps, n, row


def cell_batch(found, scale):
    got = pack(found)
    if got is None:
        return "—", "—", "—"
    tps, n, row = got
    return fmt_bs(n * scale), ms2(row["t"]), fmt_rate(tps)


def slide_config(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "一份 Decode 超节点，256 卡，每台服务器 8 卡", "N+2(cui)    ·    仿真集群    ·    给出的速率直接计时")
    ui.banner(
        slide,
        0.92,
        "每个 CPU 的 DDR 是 2 TB/s、2 TB，接 4 个 NPU。主机路径取 H2D 和这份 DDR 里更小的一个。池的两级都是每卡 6.4 Tb/s。",
    )
    head = ["项目", "配置"]
    gpus = f"Decode {v4.N} NPU，{v4.N // NPU_PER_SERVER} 台。Prefill {v4.PF_N} NPU，{v4.PF_N // NPU_PER_SERVER} 台"
    body = [
        ["服务器", "2 个 CPU。每个 CPU 用 4 对 H2D 接 4 个 NPU。一台 8 个 NPU"],
        ["规模", gpus],
        ["切分", "两边都是 TP=1。Decode DP=256、EP=256。Prefill DP=64、EP=64"],
        ["算力", "每 NPU 27640 TFLOPS FP4，即 27.64 PFLOPS"],
        ["HBM", f"每 NPU 384 GB，38400 GB/s。KV 房间 Decode {gb1(v4.ROOM_GPU)}，Prefill {gb1(v4.PF_ROOM)}"],
        ["H2D", "每 NPU 单向 1.6 Tb/s，即 200 GB/s"],
        ["CPU DDR", "每个 CPU 2 TB/s、2 TB。每 NPU 分到 500 GB/s、500 GB"],
        ["主机路径", "min(200, 500) = 200 GB/s，容量每 NPU 500 GB。这是基线 2"],
        ["总线平面", "每 NPU 3.6 TB/s。派发和合并走这里，机内不再做 fullmesh"],
        ["参数面", "1.6 Tb/s。25% 是 50 GB/s，100% 是 200 GB/s。prefix 命中 99.5%"],
        ["一级 cache", f"合计 6912 GB，每 NPU {gb1(T1_CAP)}，访问 6.4 Tb/s（0.80 TB/s）"],
        ["二级 DDR 池", "容量不限，每 NPU 同样 6.4 Tb/s。一级只多 27 GB 的容量"],
        ["时限", "TTFT ≤ 10 秒，TPOT ≤ 10 毫秒和 30 毫秒。时限内取吞吐最大的批"],
    ]
    kinds = ["head"] + ["body"] * len(body)
    heights = [0.28] + [0.36] * len(body)
    ui.add_table(slide, 0.42, 1.42, [2.15, 10.35], [head] + body, heights, kinds, size=12)


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "时限内取吞吐最大，不取刚好踩线的那一批", "20T V4    ·    4951 个路由专家    ·    全读 KV 留在 HBM")
    ui.banner(slide, 0.92, "模型仍是 61 层、隐藏 7168、中间维 3072、TopK 6。20T 只把路由专家加到 4951。一条序列不跨卡。")
    head = ["", "式子"]
    body = [
        ["每 token KV", "4939.5×S + 4,497,408。全读是 index、HCA、滑窗；CSA latent 按每层 1024 个位置抽读"],
        ["Prefill", "n = 每卡条数，全局批 = n×64。TTFT = 拉 KV + max(HBM, 计算) + MoE + 尾部"],
        ["拉 KV / 尾部", "带宽用这一组的参数面：50 GB/s 或 200 GB/s。尾部只计没被前 60 层盖住的那段"],
        ["Prefill 房间", f"每卡 KV 超过 {gb1(v4.PF_ROOM)} 就停。这一阶段不把 KV 换进池"],
        ["Decode 放置", "全读 KV 先放 HBM。HBM 空位再放 CSA latent。剩下的先填每卡 27 GB cache，再进二级池"],
        ["基线 1", "全部留在 HBM。放不下就停。换入 = 0"],
        ["基线 2", "放不下的进这张卡的 CPU DDR，最多 500 GB，换入带宽 200 GB/s"],
        ["两级池", "换入 = 池中字节 / 0.80 TB/s。一级和二级同速，27 GB 只改变落点"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)。下一层换入叠在这一层 MoE 上"],
        ["吞吐", "Prefill 是全局批 × 输入 / TTFT，单位 token/秒。Decode 是全局批 / TPOT，单位条/秒"],
    ]
    kinds = ["head"] + ["key" if i in (4, 8) else "body" for i in range(len(body))]
    heights = [0.26] + [0.42] * len(body)
    ui.add_table(slide, 0.42, 1.42, [2.15, 10.35], [head] + body, heights, kinds, size=12)


def slide_prefill(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "参数面 25% 和 100%，10 秒内 token 吞吐最高的批", "Prefill 64 卡    ·    prefix 命中 99.5%    ·    KV 放在本卡 HBM")
    ui.banner(slide, 0.92, "25% 是 50 GB/s，100% 是 200 GB/s。拉 prefix 和交给 Decode 的 KV 都走这一档。批越大越先碰到 10 秒或本卡房间。")
    head = ["输入", "25% 每卡", "25% 全局", "25% 秒", "25% token/秒", "100% 每卡", "100% 全局", "100% 秒", "100% token/秒", "相对 25%"]
    body = []
    kinds = ["head"]
    for item in data["rows"]:
        a, b = pack(item["p25"]), pack(item["p100"])
        if a is None or b is None:
            body.append([fmt_len(item["S"])] + ["—"] * 9)
            kinds.append("body")
            continue
        body.append(
            [
                fmt_len(item["S"]),
                fmt_bs(a[1]),
                fmt_bs(a[2]["bs"]),
                f"{a[2]['t']:.2f}",
                fmt_rate(a[0]),
                fmt_bs(b[1]),
                fmt_bs(b[2]["bs"]),
                f"{b[2]['t']:.2f}",
                fmt_rate(b[0]),
                signed_pct(b[0], a[0]),
            ]
        )
        kinds.append("body")
    widths = [1.05, 1.15, 1.25, 1.05, 1.45, 1.2, 1.3, 1.1, 1.55, 1.4]
    heights = [0.40] + [0.42] * len(body)
    ui.add_table(slide, 0.42, 1.48, widths, [head] + body, heights, kinds, size=12)
    r64, r4 = data["rows"][0], data["rows"][-1]
    a64, b64 = pack(r64["p25"]), pack(r64["p100"])
    a4, b4 = pack(r4["p25"]), pack(r4["p100"])
    ui.gold(
        slide,
        5.05,
        1.95,
        f"64K 两组都是每卡 {fmt_bs(a64[1])} 条，房间先满。25% TTFT {a64[2]['t']:.2f} 秒、{fmt_rate(a64[0])} token/秒；"
        f"100% TTFT {b64[2]['t']:.2f} 秒、{fmt_rate(b64[0])}，{signed_pct(b64[0], a64[0])}。\n"
        f"4M 一条约 {gb1(v4.store_seq(4 * 1048576))}，房间 {gb1(v4.PF_ROOM)} 大约放 9 条。"
        f"25% 先碰到 10 秒，停在每卡 {fmt_bs(a4[1])} 条、{a4[2]['t']:.2f} 秒、{fmt_rate(a4[0])}。\n"
        f"100% 放到每卡 {fmt_bs(b4[1])} 条、{b4[2]['t']:.2f} 秒、{fmt_rate(b4[0])}，{signed_pct(b4[0], a4[0])}。",
        14,
    )


def slide_ttft(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "最优批上，TTFT 拆成拉 KV、计算、HBM、MoE 和尾部", "单位毫秒    ·    TTFT = 拉 KV + max(计算, HBM) + MoE + 尾部")
    ui.banner(slide, 0.90, "上表是参数面 25%，下表是 100%。取大是计算和 HBM 里更长的一个。尾部是交给 Decode 时没被前 60 层盖住的时间。", size=12)
    head = ["输入", "每卡", "拉 KV", "计算", "HBM", "取大", "MoE", "尾部", "TTFT"]

    def rows_for(key):
        body, kinds = [], ["head"]
        for item in data["rows"]:
            got = pack(item[key])
            if got is None:
                body.append([fmt_len(item["S"])] + ["—"] * 8)
            else:
                _tps, n, row = got
                body.append(
                    [
                        fmt_len(item["S"]),
                        fmt_bs(n),
                        ms2(row["pull"]),
                        ms2(row["compute"]),
                        ms2(row["hbm"]),
                        ms2(max(row["compute"], row["hbm"])),
                        ms2(row["moe"]),
                        ms2(row["tail"]),
                        ms2(row["t"]),
                    ]
                )
            kinds.append("body")
        return body, kinds

    widths = [1.15, 1.15, 1.35, 1.45, 1.35, 1.35, 1.35, 1.35, 1.50]
    b25, k25 = rows_for("p25")
    b100, k100 = rows_for("p100")
    ui.add_table(slide, 0.42, 1.40, widths, [head] + b25, [0.28] + [0.30] * len(b25), k25, size=11)
    ui.add_table(slide, 0.42, 4.05, widths, [head] + b100, [0.28] + [0.30] * len(b100), k100, size=11)


def slide_decode(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    三条路径各自取条/秒最大的批    ·    全局批 = 每卡 × 256")
    ui.banner(slide, 0.92, "基线 1 只放 HBM。基线 2 是 HBM 加每卡 500 GB CPU DDR。两级池是 27 GB cache 再加不限容量的二级，换入都按 0.80 TB/s。")
    head = ["输入", "HBM 批", "HBM 条/秒", "主机批", "主机毫秒", "主机条/秒", "两级批", "两级毫秒", "两级条/秒", "相对主机"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        h, host, tier = pack(item[f"hbm{tag}"]), pack(item[f"host{tag}"]), pack(item[f"tier{tag}"])
        def trip(got):
            if got is None:
                return "—", "—", "—"
            return fmt_bs(got[1] * v4.N), ms2(got[2]["t"]), fmt_rate(got[0])

        hb, _ht, hr = trip(h)
        ob, ot, orate = trip(host)
        tb, tt, tr = trip(tier)
        body.append([fmt_len(item["S"]), hb, hr, ob, ot, orate, tb, tt, tr, signed_pct(tier[0], host[0]) if tier and host else "—"])
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.95, 1.15, 1.35, 1.15, 1.15, 1.35, 1.15, 1.15, 1.40, 1.20]
    ui.add_table(slide, 0.42, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=12)
    one = data["rows"][4]
    four = data["rows"][-1]
    t1, h1 = pack(one[f"tier{tag}"]), pack(one[f"host{tag}"])
    t4, h4 = pack(four[f"tier{tag}"]), pack(four[f"host{tag}"])
    note = (
        f"1M：两级每卡 {fmt_bs(t1[1])} 条、TPOT {ms2(t1[2]['t'])} 毫秒、{fmt_rate(t1[0])} 条/秒。"
        f"主机每卡 {fmt_bs(h1[1]) if h1 else '—'} 条、{fmt_rate(h1[0]) if h1 else '—'}。"
        f"相对主机 {signed_pct(t1[0], h1[0]) if h1 else '—'}。\n"
        f"4M：两级每卡 {fmt_bs(t4[1])} 条、TPOT {ms2(t4[2]['t'])} 毫秒、{fmt_rate(t4[0])}。"
        f"主机 {fmt_rate(h4[0]) if h4 else '—'}，相对主机 {signed_pct(t4[0], h4[0]) if h4 else '—'}。\n"
    )
    if tag == "10":
        t30 = pack(four["tier30"])
        note += (
            f"64K 到 2M 的最高点已经低于 10 毫秒，和 30 毫秒是同一批。"
            f"4M 两级从每卡 {fmt_bs(t30[1])} 条收到 {fmt_bs(t4[1])} 条，吞吐 {signed_pct(t4[0], t30[0])}。"
        )
    else:
        note += "短输入的换入还短于 MoE。1M 起两项打平，4M 换入长过 MoE，多出来的时间直接进 TPOT。池更快，是因为 0.80 TB/s 高于主机 200 GB/s，而且容量不限。"
    ui.gold(slide, 5.20, 1.85, note, 14)


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 7, "30 毫秒最优点上，全读留在 HBM，latent 再填两级", "每卡    ·    集群二级 = 每卡二级 × 256")
    ui.banner(slide, 0.92, "一级每卡只有 27 GB。两级同速，所以换入时间不看字节落在一级还是二级，只看有多少字节离开了 HBM。")
    head = ["输入", "每卡", "全读 HBM", "latent HBM", "一级", "二级", "集群二级", "换入毫秒"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        got = pack(item["tier30"])
        if got is None:
            body.append([fmt_len(item["S"])] + ["—"] * 7)
        else:
            _tps, n, row = got
            lvl1 = row["t1_h"] + row["t1_c"]
            lvl2 = row["t2_h"] + row["t2_c"]
            body.append(
                [
                    fmt_len(item["S"]),
                    fmt_bs(n),
                    gb1(row["hbm_h"]),
                    gb1(row["hbm_c"]),
                    gb1(lvl1),
                    gb1(lvl2),
                    gb1(lvl2 * v4.N),
                    ms2(row["swap"]),
                ]
            )
        kinds.append("body")
    widths = [1.15, 1.15, 1.55, 1.7, 1.4, 1.45, 1.7, 1.4]
    ui.add_table(slide, 0.42, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=13)
    ui.gold(
        slide,
        5.40,
        1.60,
        "全读一列是 CSA index、HCA 和滑窗，按这一步整段都要读，所以不换出 HBM。\n"
        "一级先接 HBM 放不下的 latent，最多 27 GB。超过的进二级。\n"
        "换入字节按抽读算：全读不进换入，latent 只按落在池里的比例乘每层抽中的 1024 个位置。",
        14,
    )


def slide_tpot(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 8, "30 毫秒两级池的最优批，TPOT 按项打开", "毫秒    ·    TPOT = max(HBM, 计算) + max(换入, MoE)")
    ui.banner(slide, 0.92, "MoE = 派发 + max(权重, GEMM) + 合并。派发和合并用每卡 3.6 TB/s 的总线。权重用 HBM 带宽，GEMM 用 27.64 PFLOPS。")
    head = ["输入", "每卡", "HBM", "计算", "左", "换入", "派发", "权重", "GEMM", "合并", "MoE", "右", "TPOT"]
    body, kinds = [], ["head"]
    for item in data["rows"]:
        got = pack(item["tier30"])
        _tps, n, row = got
        left = max(row["hbm"], row["ca"])
        right = max(row["swap"], row["moe"])
        body.append(
            [
                fmt_len(item["S"]),
                fmt_bs(n),
                ms2(row["hbm"]),
                ms2(row["ca"]),
                ms2(left),
                ms2(row["swap"]),
                ms2(row["td"]),
                ms2(row["tw"]),
                ms2(row["tg"]),
                ms2(row["tc"]),
                ms2(row["moe"]),
                ms2(right),
                ms2(row["t"]),
            ]
        )
        kinds.append("key" if item["S"] in (1048576, 4194304) else "body")
    widths = [0.85, 0.8, 0.9, 0.9, 0.85, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.85, 0.95]
    ui.add_table(slide, 0.36, 1.48, widths, [head] + body, [0.36] + [0.46] * len(body), kinds, size=11)
    row = pack(data["rows"][4]["tier30"])[2]
    ui.gold(
        slide,
        5.40,
        1.60,
        f"1M 这一批：HBM {ms2(row['hbm'])}，计算 {ms2(row['ca'])}，换入 {ms2(row['swap'])}，"
        f"MoE {ms2(row['moe'])}（派发 {ms2(row['td'])}，权重 {ms2(row['tw'])}，GEMM {ms2(row['tg'])}，合并 {ms2(row['tc'])}）。\n"
        f"左 = max(HBM, 计算) = {ms2(max(row['hbm'], row['ca']))}。"
        f"右 = max(换入, MoE) = {ms2(max(row['swap'], row['moe']))}。TPOT {ms2(row['t'])} 毫秒。\n"
        "左是这一层自己的读和注意力，右是换入和专家。两边相加，不是四项相加。",
        14,
    )


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2(cui)：20T V4 两级池"
    blank = prs.slide_layouts[6]
    slide_config(prs, blank)
    slide_formula(prs, blank)
    slide_prefill(prs, blank, data)
    slide_ttft(prs, blank, data)
    slide_decode(prs, blank, data, 5, "30", "30 毫秒内，两级池的条/秒高于只放 HBM，也高于主机 DDR")
    slide_decode(prs, blank, data, 6, "10", "10 毫秒再收紧一次，仍取三条路径各自的最高吞吐")
    slide_place(prs, blank, data)
    slide_tpot(prs, blank, data)
    prs.save(PPT)
    print("ROOM_GPU_GB", round(v4.ROOM_GPU / 1e9, 2))
    print("PF_ROOM_GB", round(v4.PF_ROOM / 1e9, 2))
    print("T1_CAP_GB", round(T1_CAP / 1e9, 2))
    for item in data["rows"]:
        def brief(found):
            got = pack(found)
            if got is None:
                return "none"
            return f"n={got[1]} t={got[2]['t']*1e3:.2f}ms tps={got[0]:.3e}"

        print(
            fmt_len(item["S"]),
            "p25", brief(item["p25"]),
            "p100", brief(item["p100"]),
            "hbm30", brief(item["hbm30"]),
            "host30", brief(item["host30"]),
            "tier30", brief(item["tier30"]),
        )


if __name__ == "__main__":
    main()
