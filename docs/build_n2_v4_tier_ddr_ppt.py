#!/usr/bin/env python3
"""N+2 20T V4 with a two-level KV pool, TP=1.

Tier 1 is the in-network cache: 233472 GB at 51.2 Tb/s (6.40 TB/s),
shared as 912 GB per GPU. Tier 2 is
a bus DDR pool at 6.4 Tb/s (0.80 TB/s) with no capacity cap. Both rates
are line rate / 8, the same conversion as the cache, with no extra 80%.

Placement follows what each step actually reads. The CSA index, the HCA
KV and the sliding window are scanned in full, so they stay on GPU HBM.
The CSA latent body is touched only at 1024 positions per layer, so the
bytes that do not fit in HBM fill the cache and then the DDR pool.

Swap of the next layer overlaps the current layer's MoE. TPOT is
max(HBM, attention compute) + max(swap, MoE). The batch is the one with
the highest throughput that still meets TPOT. The baseline is HBM only.
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

T1_BW = v4.POOL_51
T1_TOTAL = 233472e9
T1_CAP = T1_TOTAL / v4.N
T2_BW = 6.4e12 / 8
HOST_BW = min(1.6e12 / 8 * 0.80, 2e12 / 4)
DDR_CAP = 2e12 / 4
TIE = 1e-4
SEL_BYTES = v4.N_CSA * 1024 * 576
C_HOT = "1B4F8A"
C_COLD = "8FCBB8"
C_CACHE = "3D7CC9"
C_DDR = "E07A3D"
C_INDEX = "1B4F8A"
C_HCA = "5B8FA8"
C_WIN = "C4A35A"
C_LAT = "E07A3D"

SLIDES = 18
FOOTER = "N+2    ·    20T V4    ·    Decode DP=256 EP=256    ·    一级 233472 GB · 51.2 Tb/s    ·    二级 6.4 Tb/s · 容量不限"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER
NAVY, TEAL = ui.NAVY, ui.TEAL
PPT = "/agent/repos/ucl-mpcomm/docs/N+2-20T-V4-两级池-590A.pptx"


def hot_cold(s):
    hot = (480.0 + 139.5) * s + v4.FIXED
    cold = 4320.0 * s
    cold_read = v4.N_CSA * min(1024.0, s / 4.0) * 576
    return hot, cold, cold_read


def decode_tier(n, s):
    hot, cold, cold_read = hot_cold(s)
    need_h = n * hot
    need_c = n * cold
    hbm_h = min(need_h, v4.ROOM_GPU)
    hbm_c = min(need_c, v4.ROOM_GPU - hbm_h)
    rest_h = need_h - hbm_h
    rest_c = need_c - hbm_c
    t1_h = min(rest_h, T1_CAP)
    t1_c = min(rest_c, T1_CAP - t1_h)
    t2_h = rest_h - t1_h
    t2_c = rest_c - t1_c
    b1 = b2 = 0.0
    if need_h:
        b1 += n * hot * (t1_h / need_h)
        b2 += n * hot * (t2_h / need_h)
    if need_c:
        b1 += n * cold_read * (t1_c / need_c)
        b2 += n * cold_read * (t2_c / need_c)
    sel = min(1024.0, s / 4.0)
    score = v4.N_CSA * 4096 * s + v4.N_HCA * 2048 * s + v4.N_CSA * 262144 * (sel + 128)
    read = n * v4.n_read(s)
    t_hbm = (read + v4.ATTN) / v4.HBM_BW
    t_ca = n * (score + v4.PROJ) / (v4.PEAK * v4.align(n))
    moe = v4.expert(float(n * v4.DP))
    swap = b1 / T1_BW + b2 / T2_BW
    other = max(t_hbm, t_ca)
    return {
        "t": other + max(swap, moe["t"]),
        "swap": swap,
        "hbm": t_hbm,
        "ca": t_ca,
        "moe": moe["t"],
        "td": moe["td"],
        "tw": moe["tw"],
        "tg": moe["tg"],
        "tc": moe["tc"],
        "n": n,
        "hbm_h": hbm_h,
        "hbm_c": hbm_c,
        "t1_h": t1_h,
        "t1_c": t1_c,
        "t2_h": t2_h,
        "t2_c": t2_c,
        "b1": b1,
        "b2": b2,
    }


def decode_host(n, s):
    """Hot stays on HBM. Cold fills the rest of HBM, then up to 500 GB of CPU DDR."""
    hot, cold, cold_read = hot_cold(s)
    need_h = n * hot
    need_c = n * cold
    hbm_h = min(need_h, v4.ROOM_GPU)
    hbm_c = min(need_c, v4.ROOM_GPU - hbm_h)
    rest_h = need_h - hbm_h
    rest_c = need_c - hbm_c
    if rest_h + rest_c > DDR_CAP + 1.0:
        return None
    b_hot = n * hot * (rest_h / need_h) if need_h else 0.0
    b_cold = n * cold_read * (rest_c / need_c) if need_c else 0.0
    base = decode_tier(n, s)
    swap = (b_hot + b_cold) / HOST_BW
    other = max(base["hbm"], base["ca"])
    return {
        "t": other + max(swap, base["moe"]),
        "swap": swap,
        "moe": base["moe"],
        "td": base["td"],
        "tw": base["tw"],
        "tg": base["tg"],
        "tc": base["tc"],
        "hbm": base["hbm"],
        "ca": base["ca"],
        "n": n,
        "hbm_h": hbm_h,
        "hbm_c": hbm_c,
        "ddr_h": rest_h,
        "ddr_c": rest_c,
    }


def decode_uniform(n, s):
    """Spill is a byte fraction of the whole KV, hot and cold together."""
    kept = n * v4.store_seq(s)
    overflow = max(kept - v4.ROOM_GPU, 0.0)
    t1 = min(overflow, T1_CAP)
    t2 = overflow - t1
    read = n * v4.n_read(s)
    swap = 0.0
    if kept:
        swap = read * (t1 / kept) / T1_BW + read * (t2 / kept) / T2_BW
    base = decode_tier(n, s)
    other = max(base["hbm"], base["ca"])
    base["swap"] = swap
    base["t"] = other + max(swap, base["moe"])
    return base


def _keep(best, tps, n, row):
    # best is (tps, n, row, peak). Ties stay within 0.01% of the peak itself,
    # so a long flat slope cannot walk the batch away from the maximum.
    if best is None or tps > best[3] * (1.0 + 1e-12):
        return (tps, n, row, tps)
    if tps >= best[3] * (1.0 - TIE) and n > best[1]:
        return (tps, n, row, best[3])
    return best


def search(s, limit, fn):
    best = None
    last = None
    n = 1
    while n < 200000:
        row = fn(n, s)
        if row is None or row["t"] > limit + 1e-12:
            break
        last = (n, row)
        best = _keep(best, n * v4.N / row["t"], n, row)
        n += 1
    return best, last


def hbm_search(s, limit):
    n_fit = int(v4.ROOM_GPU // v4.store_seq(s))
    best = None
    last = None
    for n in range(1, n_fit + 1):
        row = decode_tier(n, s)
        if row["swap"] > 1e-9:
            break
        if row["t"] > limit + 1e-12:
            break
        last = (n, row)
        best = _keep(best, n * v4.N / row["t"], n, row)
    return {"best": best, "last": last, "n_fit": n_fit}


def collect():
    rows = []
    for s in v4.LENGTHS:
        item = {"S": s, "n_fit": int(v4.ROOM_GPU // v4.store_seq(s))}
        for limit, tag in ((0.010, "10"), (0.030, "30")):
            item[f"hbm{tag}"] = hbm_search(s, limit)
            best, last = search(s, limit, decode_tier)
            item[f"tier{tag}"] = {"best": best, "last": last}
            best, last = search(s, limit, decode_host)
            item[f"host{tag}"] = {"best": best, "last": last}
        rows.append(item)
    return {"rows": rows}


def pack(found):
    _tps, n, row, _peak = found["best"]
    return n, row


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


def gb_pie(n):
    if n >= 1e12:
        return f"{n / 1e12:.2f} TB"
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return "0"


def share(slices):
    total = sum(v for _label, v, _color in slices)
    if total <= 0:
        return total, [0.0] * len(slices)
    raw = [v / total * 100 for _label, v, _color in slices]
    rounded = [round(x, 1) for x in raw]
    drift = round(100.0 - sum(rounded), 1)
    biggest = max(range(len(slices)), key=lambda i: slices[i][1])
    rounded[biggest] = round(rounded[biggest] + drift, 1)
    return total, rounded


def add_pie(slide, cx, cy, r, slices):
    alive = [(v, c) for _label, v, c in slices if v > 0]
    if not alive:
        return
    if len(alive) == 1:
        oval = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(cx - r), Inches(cy - r), Inches(2 * r), Inches(2 * r)
        )
        ui.solid(oval, alive[0][1])
        return
    total = sum(v for v, _c in alive)
    theta = 0.0
    for value, color in alive:
        sweep = 360.0 * value / total
        if sweep < 1.2:
            theta += sweep
            continue
        steps = max(2, int(math.ceil(sweep / 6)))
        pts = [(cx, cy)]
        for i in range(steps + 1):
            ang = math.radians(theta + sweep * i / steps)
            pts.append((cx + r * math.sin(ang), cy - r * math.cos(ang)))
        theta += sweep
        builder = slide.shapes.build_freeform(Inches(pts[0][0]), Inches(pts[0][1]))
        builder.add_line_segments([(Inches(x), Inches(y)) for x, y in pts[1:]], close=True)
        ui.solid(builder.convert_to_shape(), color)


def gb_seq(n):
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    return f"{n / 1e6:.1f} MB"


def gb1(n):
    if abs(n) < 1e6:
        return "0"
    if n >= 1e12:
        return f"{n / 1e12:.2f} TB"
    return f"{n / 1e9:.1f} GB"


def tps_of(n, row):
    return n * v4.N / row["t"]


def margins(shape):
    for cell in shape.table.iter_cells():
        cell.margin_top = Inches(0.02)
        cell.margin_bottom = Inches(0.02)
        cell.margin_left = Inches(0.05)
        cell.margin_right = Inches(0.04)


def slide_open(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "长上下文下，两级池的批大于只放 HBM", "TPOT ≤ 30 毫秒    ·    换入叠在其他层的 MoE 上    ·    取系统吞吐最大的批")
    ui.banner(slide, 0.92, f"一级是在网 cache，{T1_TOTAL / 1e9:.0f} GB、51.2 Tb/s，每卡 {T1_CAP / 1e9:.0f} GB。二级是总线 DDR，6.4 Tb/s，容量不限。对照只用 GPU HBM。")
    head = ["输入", "HBM 批", "HBM 吞吐", "两级批", "TPOT", "换入", "两级吞吐", "相对 HBM"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        hn, hr = pack(row["hbm30"])
        tn, tr = pack(row["tier30"])
        kinds.append("key" if row["S"] in (1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(hn * v4.N),
            fmt_rate(tps_of(hn, hr)),
            fmt_bs(tn * v4.N),
            f"{ms2(tr['t'])} 毫秒",
            f"{ms2(tr['swap'])} 毫秒",
            fmt_rate(tps_of(tn, tr)),
            signed_pct(tps_of(tn, tr), tps_of(hn, hr)),
        ])
    shape = ui.add_table(
        slide, 0.42, 1.48,
        [1.05, 1.70, 1.55, 1.70, 1.45, 1.40, 1.70, 1.45],
        [head] + body,
        [0.36] + [0.48] * len(body),
        kinds,
        size=13,
    )
    margins(shape)
    r1 = data["rows"][4]
    r4 = data["rows"][-1]
    r64 = data["rows"][0]
    hn, hr = pack(r1["hbm30"])
    tn, tr = pack(r1["tier30"])
    h4, a4 = pack(r4["hbm30"])
    t4, b4 = pack(r4["tier30"])
    h64, a64 = pack(r64["hbm30"])
    t64, b64 = pack(r64["tier30"])
    ui.gold(
        slide,
        5.55,
        1.45,
        f"1M 从批 {fmt_bs(hn * v4.N)}、{fmt_rate(tps_of(hn, hr))} 提到批 {fmt_bs(tn * v4.N)}、{fmt_rate(tps_of(tn, tr))}，"
        f"{signed_pct(tps_of(tn, tr), tps_of(hn, hr))}。换入 {ms2(tr['swap'])} 毫秒，MoE {ms2(tr['moe'])} 毫秒。\n"
        f"4M 从批 {fmt_bs(h4 * v4.N)} 提到 {fmt_bs(t4 * v4.N)}，吞吐 {signed_pct(tps_of(t4, b4), tps_of(h4, a4))}，TPOT {ms2(b4['t'])} 毫秒。\n"
        f"64K 从批 {fmt_bs(h64 * v4.N)} 到 {fmt_bs(t64 * v4.N)}，只高 {signed_pct(tps_of(t64, b64), tps_of(h64, a64))}。"
        f"这一档 MoE 有 {ms2(b64['moe'])} 毫秒，HBM 读先把吞吐拉下来，换入 {ms2(b64['swap'])} 毫秒短于 MoE，不另加时间。",
        14,
    )


def slide_bytes(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "CSA index 和 HCA 每步整段都读，CSA latent 只抽 1024 个", "30 层 CSA    ·    31 层 HCA    ·    S ≥ 4K 时每层抽满 1024")
    ui.banner(slide, 0.92, "全读 KV = CSA index + HCA + sliding window，每步整段都读。CSA latent 每 4 个 token 收成一个 576 字节的向量，每步只抽 1024 个。")
    head = ["输入", "一条 KV", "全读 KV", "CSA latent", "每步全读", "每步抽读"]
    body, kinds = [], ["head"]
    for s in v4.LENGTHS:
        hot, cold, cold_read = hot_cold(s)
        kinds.append("key" if s == 1048576 else "body")
        body.append([
            fmt_len(s),
            gb_seq(v4.store_seq(s)),
            gb_seq(hot),
            gb_seq(cold),
            gb_seq(hot),
            f"{cold_read / 1e6:.2f} MB",
        ])
    shape = ui.add_table(
        slide, 0.42, 1.48,
        [1.40, 2.10, 2.20, 2.20, 2.30, 2.30],
        [head] + body,
        [0.36] + [0.46] * len(body),
        kinds,
        size=14,
    )
    margins(shape)
    n1, r1 = pack(data["rows"][4]["tier30"])
    ui.gold(
        slide,
        5.45,
        1.55,
        f"1M 一条 {v4.store_seq(1048576) / 1e9:.3f} GB。全读 KV {hot_cold(1048576)[0] / 1e9:.3f} GB，CSA latent {hot_cold(1048576)[1] / 1e9:.3f} GB。\n"
        f"每步抽中的 latent 固定 {SEL_BYTES / 1e6:.2f} MB，和上下文长度无关。二级只有 {T2_BW / 1e12:.2f} TB/s。\n"
        f"1M 的吞吐最高点是每卡 {n1} 条，latent 换入 {ms2(r1['swap'])} 毫秒，短于 MoE {ms2(r1['moe'])} 毫秒，不另加时间。",
        14,
    )


def slide_place(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "全读 KV 先放 HBM，CSA latent 再填两级", "每张卡分开存放    ·    一条序列不跨卡")
    ui.banner(slide, 0.92, "同一类数据在各级之间按字节占比分摊这一步的读。抽中的 1024 个事先不确定，所以按 CSA latent 的占比取。")
    head = ["顺序", "介质", "容量", "带宽", "放什么"]
    room = v4.ROOM_GPU
    body = [
        ["1", "GPU HBM", f"每卡 {room / 1e9:.2f} GB", "26.40 TB/s", "先放每步全读的 KV。空出来的容量放 CSA latent"],
        ["2", "一级 在网 cache", f"合计 {T1_TOTAL / 1e9:.0f} GB\n每卡 {T1_CAP / 1e9:.0f} GB", f"{T1_BW / 1e12:.2f} TB/s\n51.2 Tb/s", "HBM 放不下的全读 KV 先放这里。然后放 CSA latent"],
        ["3", "二级 总线 DDR", "容量不限", f"{T2_BW / 1e12:.2f} TB/s\n6.4 Tb/s", "一级放不下的全读 KV，然后剩下的 CSA latent"],
    ]
    kinds = ["head", "key", "body", "body"]
    shape = ui.add_table(
        slide, 0.42, 1.48,
        [1.10, 2.30, 2.40, 2.20, 4.50],
        [head] + body,
        [0.36, 0.85, 0.95, 0.95],
        kinds,
        size=14,
    )
    margins(shape)
    bits = []
    for row in (data["rows"][0], data["rows"][4], data["rows"][-1]):
        _n, r = pack(row["tier30"])
        bits.append(f"{fmt_len(row['S'])} 每卡 {gb1(r['t2_c'])}")
    ui.gold(
        slide,
        5.00,
        1.95,
        "30 毫秒的七个最优点上，每步全读的 KV 全部留在 HBM，一级和二级没有这部分。\n"
        f"一级每卡 {T1_CAP / 1e9:.0f} GB 被 CSA latent 装满。二级只接一级放不下的 CSA latent：{'，'.join(bits)}。\n"
        "换入字节 = 抽读 × 该级 latent 占比。全读走 HBM 的 26.40 TB/s，不进换入。\n"
        "下一层要的那一份在上一层做 MoE 时换入。整步换入不长于整步 MoE，TPOT 里就只有 HBM 和 MoE。",
        14,
    )


def slide_formula(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "换入不长于 MoE 时，步时只剩 HBM 和 MoE", "n 是一张卡上的条数    ·    吞吐 = 全局批 / TPOT")
    ui.banner(slide, 0.92, "HBM 仍按这一步要读的全部 KV 计。换入只计放在池里的那一部分。进到卡上之后再读一次，已经含在 HBM 里。")
    head = ["项", "公式"]
    body = [
        ["全读 / latent", "全读 = 30×(S/4)×64 + 31×(S/128)×576 + sliding window\nCSA latent = 30×(S/4)×576"],
        ["每步抽读", f"30 × min(1024, S/4) × 576。S ≥ 4K 时是 {SEL_BYTES / 1e6:.2f} MB"],
        ["换入", "（全读 × 一级全读占比 + 抽读 × 一级 latent 占比）/ 6.40 TB/s\n+（全读 × 二级全读占比 + 抽读 × 二级 latent 占比）/ 0.80 TB/s"],
        ["HBM", "(n × Read + 19.35 GB) / 26.40 TB/s"],
        ["TPOT", "max(HBM, 计算) + max(换入, MoE)"],
        ["选批", "TPOT ≤ 10 或 30 毫秒里，取全局批 / TPOT 最大的 n。一样大时取更大的批"],
    ]
    kinds = ["head"] + ["key" if i in (2, 4) else "body" for i in range(6)]
    heights = [0.32, 0.62, 0.48, 0.70, 0.42, 0.42, 0.48]
    shape = ui.add_table(
        slide, 0.42, 1.46,
        [1.40, 11.10],
        [head] + body,
        heights,
        kinds,
        size=13,
    )
    margins(shape)
    ui.gold(
        slide,
        5.55,
        1.45,
        "最优点上，一级和二级里没有全读 KV，换入只剩抽中的 latent。\n"
        "换入短于 MoE 时，加一条序列只多付 HBM 和 MoE。批增加的吞吐抵得过这两项。\n"
        "换入长过 MoE 之后，多出来的换入直接加进 TPOT。1M 的最高点停在这两项相等的那一条。",
        14,
    )


def slide_where(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "最优点上一级装满 CSA latent，二级接剩下的", "30 毫秒的吞吐最大批    ·    每卡容量    ·    集群二级 = 每卡 × 256")
    ui.banner(slide, 0.90, "全读一列是 HBM 上的 CSA index、HCA 和 sliding window。一级和二级都是 CSA latent，没有全读 KV。", size=12)
    head = ["输入", "每卡条数", "全读", "latent", "一级 latent", "二级 latent", "集群二级"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        n, r = pack(row["tier30"])
        kinds.append("key" if row["S"] in (1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(n),
            gb1(r["hbm_h"]),
            gb1(r["hbm_c"]),
            gb1(r["t1_c"]),
            gb1(r["t2_c"]),
            gb1(r["t2_c"] * v4.N),
        ])
    shape = ui.add_table(
        slide, 0.36, 1.46,
        [1.00, 1.45, 1.25, 1.50, 2.20, 2.30, 2.80],
        [head] + body,
        [0.36] + [0.48] * len(body),
        kinds,
        size=13,
    )
    margins(shape)
    r1 = data["rows"][4]
    n, r = pack(r1["tier30"])
    ui.gold(
        slide,
        5.55,
        1.45,
        f"1M 每卡 {n} 条。全读 KV {gb1(r['hbm_h'])} 全在 HBM，HBM 还留着 {gb1(r['hbm_c'])} 的 CSA latent。\n"
        f"一级 {gb1(r['t1_c'])} 满。二级每卡 {gb1(r['t2_c'])}，256 卡合计 {gb1(r['t2_c'] * v4.N)}。\n"
        f"这一步从二级读出 {gb1(r['b2'])}，用 {T2_BW / 1e12:.2f} TB/s 走 {ms2(r['b2'] / T2_BW)} 毫秒；"
        f"从一级读出 {gb1(r['b1'])}，走 {ms2(r['b1'] / T1_BW)} 毫秒。换入合计 {ms2(r['swap'])} 毫秒。",
        14,
    )


def slide_walk(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    s = 1048576
    n_fit = int(v4.ROOM_GPU // v4.store_seq(s))
    n_full = n_fit
    while decode_tier(n_full + 1, s)["t2_c"] <= 1.0:
        n_full += 1
    best_n = pack(data["rows"][4]["tier30"])[0]
    ui.chrome(slide, 6, "1M：换入和 MoE 相等的那一条吞吐最高", "每卡从 HBM 装满，到换入开始算进 TPOT")
    ui.banner(
        slide,
        0.92,
        f"{n_fit} 条把 HBM 装满。{n_full} 条时一级还没溢出到二级。{best_n} 条换入和 MoE 相等，{best_n + 1} 条换入开始算进 TPOT。",
    )
    marks = sorted({n_fit, n_full, (n_fit + best_n) // 2, best_n, best_n + 1, best_n + 49})
    head = ["每卡", "全局批", "换入", "MoE", "HBM", "TPOT", "吞吐", "二级 latent"]
    body, kinds = [], ["head"]
    for n in marks:
        r = decode_tier(n, s)
        kinds.append("key" if n == best_n else "body")
        body.append([
            fmt_bs(n),
            fmt_bs(n * v4.N),
            f"{ms2(r['swap'])} 毫秒",
            f"{ms2(r['moe'])} 毫秒",
            f"{ms2(r['hbm'])} 毫秒",
            f"{ms2(r['t'])} 毫秒",
            fmt_rate(tps_of(n, r)),
            gb1(r["t2_c"]),
        ])
    shape = ui.add_table(
        slide, 0.32, 1.48,
        [1.15, 1.55, 1.45, 1.45, 1.45, 1.45, 1.55, 2.45],
        [head] + body,
        [0.36] + [0.46] * len(body),
        kinds,
        size=13,
    )
    margins(shape)
    uni, _last = search(s, 0.030, decode_uniform)
    un, ur = uni[1], uni[2]
    bn, br = pack(data["rows"][4]["tier30"])
    later = decode_tier(best_n + 49, s)
    ui.gold(
        slide,
        5.00,
        1.95,
        f"{bn} 条换入 {ms2(br['swap'])} 毫秒，MoE {ms2(br['moe'])} 毫秒，TPOT {ms2(br['t'])} 毫秒，吞吐 {fmt_rate(tps_of(bn, br))}。\n"
        f"{bn + 1} 条换入长过 MoE，多出来的换入算进 TPOT，吞吐开始下降。{best_n + 49} 条换入 {ms2(later['swap'])} 毫秒，吞吐回到 {fmt_rate(tps_of(best_n + 49, later))}。\n"
        f"全读 KV 和 CSA latent 按字节比例一起切到二级时，1M 最高到每卡 {un} 条、吞吐 {fmt_rate(tps_of(un, ur))}。"
        f"全读 KV 留在 HBM 时是每卡 {bn} 条、{fmt_rate(tps_of(bn, br))}。\n"
        f"这一步抽中的 latent 是 {gb1(bn * SEL_BYTES)}。HBM 上还有 {gb1(br['hbm_c'])} CSA latent，留出这块缓冲即可。",
        14,
    )


def slide_ten(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 7, "10 毫秒：128K 到 1M 和 30 毫秒是同一批", "TPOT ≤ 10 毫秒    ·    仍取系统吞吐最大的批")
    ui.banner(slide, 0.90, "128K、256K、512K、1M 的吞吐最高点已经低于 10 毫秒，收紧时限不改变这一批。64K 在 HBM 还没满时就碰到 10 毫秒。", size=12)
    head = ["输入", "HBM 批", "HBM 吞吐", "两级批", "TPOT", "两级吞吐", "相对 HBM", "和 30 毫秒"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        hn, hr = pack(row["hbm10"])
        tn, tr = pack(row["tier10"])
        n30, _r30 = pack(row["tier30"])
        if tn == n30:
            same = "同一批"
        elif tn < row["n_fit"]:
            same = "HBM 未满"
        else:
            same = f"30 毫秒是 {fmt_bs(n30)} 条"
        kinds.append("key" if row["S"] in (65536, 2097152, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(hn * v4.N),
            fmt_rate(tps_of(hn, hr)),
            fmt_bs(tn * v4.N),
            f"{ms2(tr['t'])} 毫秒",
            fmt_rate(tps_of(tn, tr)),
            signed_pct(tps_of(tn, tr), tps_of(hn, hr)),
            same,
        ])
    shape = ui.add_table(
        slide, 0.32, 1.46,
        [0.95, 1.55, 1.45, 1.55, 1.40, 1.55, 1.35, 2.20],
        [head] + body,
        [0.36] + [0.48] * len(body),
        kinds,
        size=13,
    )
    margins(shape)
    r2 = data["rows"][5]
    r4 = data["rows"][-1]
    n2, a2 = pack(r2["tier10"])
    m2, b2 = pack(r2["tier30"])
    n4, a4 = pack(r4["tier10"])
    m4, b4 = pack(r4["tier30"])
    ui.gold(
        slide,
        5.55,
        1.45,
        f"2M 的 10 毫秒停在每卡 {n2} 条、TPOT {ms2(a2['t'])} 毫秒、吞吐 {fmt_rate(tps_of(n2, a2))}。"
        f"30 毫秒放到每卡 {m2} 条、{fmt_rate(tps_of(m2, b2))}。\n"
        f"4M 的 10 毫秒停在每卡 {n4} 条、吞吐 {fmt_rate(tps_of(n4, a4))}。30 毫秒放到每卡 {m4} 条、{fmt_rate(tps_of(m4, b4))}。\n"
        "这两档的换入在 10 毫秒里还短于 MoE，是时限先把批截住。",
        14,
    )


def parts_tier(row):
    return [
        ("全读", row["hbm_h"], C_HOT),
        ("latent", row["hbm_c"], C_COLD),
        ("cache", row["t1_h"] + row["t1_c"], C_CACHE),
        ("二级 DDR", row["t2_h"] + row["t2_c"], C_DDR),
    ]


def parts_host(row):
    return [
        ("全读", row["hbm_h"], C_HOT),
        ("latent", row["hbm_c"], C_COLD),
        ("CPU DDR", row["ddr_h"] + row["ddr_c"], C_DDR),
    ]


def parts_hbm(s, n):
    return [
        ("CSA index", 480.0 * s * n, C_INDEX),
        ("HCA", 139.5 * s * n, C_HCA),
        ("window", v4.FIXED * n, C_WIN),
        ("CSA latent", 4320.0 * s * n, C_LAT),
    ]


def pie_label(title, batch, slices):
    total, _pct = share(slices)
    return f"{title}\n批 {fmt_bs(batch)}\n合计 {gb_pie(total)}", slices


def slide_h2d(prs, blank, data, page, tag, title):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, f"TPOT ≤ {tag} 毫秒    ·    H2D 每卡 {DDR_CAP / 1e9:.0f} GB、{HOST_BW / 1e9:.0f} GB/s    ·    换入叠在 MoE 上")
    ui.banner(
        slide, 0.90,
        "H2D 卸载是主机 DDR。全读 KV 先放 HBM，空位放 CSA latent，剩下的经 H2D 进主机 DDR。相对 H2D 是两级池的系统吞吐。",
        size=12,
    )
    head = ["输入", "HBM 批", "HBM 吞吐", "H2D 批", "H2D 毫秒", "H2D 吞吐", "两级批", "两级吞吐", "相对 H2D"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        hn, hr = pack(row[f"hbm{tag}"])
        dn, dr = pack(row[f"host{tag}"])
        tn, tr = pack(row[f"tier{tag}"])
        kinds.append("key" if row["S"] in (1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(hn * v4.N),
            fmt_rate(tps_of(hn, hr)),
            fmt_bs(dn * v4.N),
            ms2(dr["t"]),
            fmt_rate(tps_of(dn, dr)),
            fmt_bs(tn * v4.N),
            fmt_rate(tps_of(tn, tr)),
            signed_pct(tps_of(tn, tr), tps_of(dn, dr)),
        ])
    shape = ui.add_table(
        slide, 0.28, 1.46,
        [0.85, 1.40, 1.30, 1.40, 1.20, 1.35, 1.45, 1.40, 1.45],
        [head] + body,
        [0.34] + [0.46] * len(body),
        kinds,
        size=12,
    )
    margins(shape)
    one = data["rows"][4]
    four = data["rows"][-1]
    dn, dr = pack(one[f"host{tag}"])
    tn, tr = pack(one[f"tier{tag}"])
    d4, r4 = pack(four[f"host{tag}"])
    t4, b4 = pack(four[f"tier{tag}"])
    ui.gold(
        slide,
        5.40,
        1.55,
        f"1M：H2D 批 {fmt_bs(dn * v4.N)}，换入 {ms2(dr['swap'])} 毫秒，吞吐 {fmt_rate(tps_of(dn, dr))}。"
        f"两级批 {fmt_bs(tn * v4.N)}，换入 {ms2(tr['swap'])} 毫秒，吞吐 {fmt_rate(tps_of(tn, tr))}，"
        f"{signed_pct(tps_of(tn, tr), tps_of(dn, dr))}。\n"
        f"4M：H2D 批 {fmt_bs(d4 * v4.N)}，吞吐 {fmt_rate(tps_of(d4, r4))}。"
        f"两级批 {fmt_bs(t4 * v4.N)}，吞吐 {fmt_rate(tps_of(t4, b4))}，"
        f"{signed_pct(tps_of(t4, b4), tps_of(d4, r4))}。\n"
        f"H2D 是 {HOST_BW / 1e9:.0f} GB/s。两级池一级 {T1_BW / 1e12:.2f} TB/s，二级 {T2_BW / 1e12:.2f} TB/s。同样的 CSA latent，池上的换入更短，批可以更大。",
        13,
    )


def slide_pies(prs, blank, page, title, kicker, banner, columns, note):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, page, title, kicker)
    ui.banner(slide, 0.90, banner, size=12)
    gap = 12.90 / len(columns)
    for i, (label, slices) in enumerate(columns):
        x = 0.22 + i * gap
        ui.textbox(slide, x, 1.38, gap - 0.06, 0.62, label, 11, True, NAVY, anchor=MSO_ANCHOR.MIDDLE)
        add_pie(slide, x + gap / 2.0, 2.62, 0.46, slices)
        _total, pct = share(slices)
        items = []
        for (name, value, color), p in zip(slices, pct):
            shown = "<0.1%" if p == 0.0 and value > 0 else f"{p:.1f}%"
            items.append((color, f"{name}  {shown}\n{gb_pie(value)}"))
        ui.add_key(slide, x + 0.02, 3.18, gap - 0.10, items, size=10, row=0.44)
    ui.gold(slide, 5.50, 1.50, note, 13)


def occ_note(slices):
    _total, pct = share(slices)
    return "，".join(
        f"{name} {gb_pie(value)}（{p:.1f}%）"
        for (name, value, _color), p in zip(slices, pct)
        if value >= 1e6
    )


def slide_pie_tier(prs, blank, data):
    columns = []
    for row in data["rows"]:
        n, found = pack(row["tier30"])
        columns.append(pie_label(fmt_len(row["S"]), n * v4.N, parts_tier(found)))
    one = columns[4][1]
    four = columns[-1][1]
    slide_pies(
        prs, blank, 10,
        "二级池：HBM、在网 cache、二级 DDR 各放多少",
        "30 毫秒吞吐最高的批    ·    全读 = CSA index + HCA + sliding window    ·    latent = CSA latent",
        f"饼按这一批的 KV 字节。HBM 拆成全读和 CSA latent。cache 是一级，每卡 {T1_CAP / 1e9:.0f} GB。二级是总线 DDR。权重和预留不在饼里。",
        columns,
        f"1M：{occ_note(one)}。\n4M：{occ_note(four)}。\n七档每步全读的 KV 都在 HBM，cache 和二级里只有 CSA latent。",
    )


def slide_pie_host(prs, blank, data):
    columns = []
    for row in data["rows"]:
        n, found = pack(row["host30"])
        columns.append(pie_label(fmt_len(row["S"]), n * v4.N, parts_host(found)))
    one = columns[4][1]
    four = columns[-1][1]
    slide_pies(
        prs, blank, 11,
        "主机卸载：HBM 和 CPU DDR 各放多少",
        f"30 毫秒吞吐最高的批    ·    CPU DDR 每卡 {DDR_CAP / 1e9:.0f} GB、{HOST_BW / 1e9:.0f} GB/s",
        "每步全读的 KV 先放 HBM。HBM 空出来的容量放 CSA latent，放不下的进这张卡的 CPU DDR。DDR 里没有全读 KV。",
        columns,
        f"1M：{occ_note(one)}。\n4M：{occ_note(four)}。\n"
        f"每卡 DDR 上限 {DDR_CAP / 1e9:.0f} GB。4M 用了 {gb_pie(four[2][1])}。",
    )


PATHS = (
    ("hbm", "只放 HBM", "换入为 0，KV 全在 GPU HBM"),
    ("host", "H2D 卸载", f"换入 = 主机字节 / {HOST_BW / 1e9:.0f} GB/s"),
    ("tier", "两级池", f"换入 = 一级 / {T1_BW / 1e12:.2f} TB/s + 二级 / {T2_BW / 1e12:.2f} TB/s"),
)


def ms_leaf(v):
    return round(v * 1e3, 3)


def shown(found, tier):
    """Round the leaves first, then add, so the printed formula holds."""
    hbm = ms_leaf(found["hbm"])
    ca = ms_leaf(found["ca"])
    td = ms_leaf(found["td"])
    tw = ms_leaf(found["tw"])
    tg = ms_leaf(found["tg"])
    tc = ms_leaf(found["tc"])
    gate = tw if tw >= tg else tg
    moe = round(td + gate + tc, 3)
    if tier:
        t1 = ms_leaf(found["b1"] / T1_BW)
        t2 = ms_leaf(found["b2"] / T2_BW)
        swap = round(t1 + t2, 3)
    else:
        t1 = t2 = 0.0
        swap = ms_leaf(found["swap"])
    left = hbm if hbm >= ca else ca
    right = swap if swap >= moe else moe
    tpot = round(left + right, 3)
    return {
        "hbm": hbm, "ca": ca, "left": left, "t1": t1, "t2": t2, "swap": swap,
        "td": td, "tw": tw, "tg": tg, "gate": gate, "tc": tc, "moe": moe,
        "right": right, "t": tpot,
    }


def tpot_chrome(slide, page, path_name, tag, how):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    ui.solid(bar, ui.ACCENT)
    ui.textbox(
        slide, 0.42, 0.12, 10.6, 0.24,
        f"{tag} 毫秒 · {path_name} · {how} · 单位毫秒",
        12, True, ui.ACCENT, anchor=MSO_ANCHOR.MIDDLE,
    )
    ui.textbox(
        slide, 0.42, 0.36, 12.5, 0.70,
        "TPOT = max(HBM, 计算) + max(换入, MoE)\nMoE = 派发 + max(权重, GEMM) + 合并",
        20, True, ui.NAVY, anchor=MSO_ANCHOR.MIDDLE,
    )
    ui.textbox(
        slide, 11.4, 0.12, 1.5, 0.24,
        f"{page}  /  {ui.SLIDES}",
        12, False, ui.MUTED, align=ui.PP_ALIGN.RIGHT,
    )
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.42), Inches(7.18), Inches(12.5), Inches(0.01))
    ui.solid(rule, ui.LINE)
    ui.textbox(slide, 0.42, 7.20, 12.5, 0.24, ui.FOOTER, 11, False, ui.MUTED, anchor=MSO_ANCHOR.MIDDLE)


def slide_tpot(prs, blank, data, page, tag, kind, path_name, how):
    slide = prs.slides.add_slide(blank)
    tpot_chrome(slide, page, path_name, tag, how)
    tier = kind == "tier"
    if tier:
        head = ["输入", "每卡", "全局批", "HBM", "计算", "max(HBM,计算)", "一级", "二级", "换入", "MoE", "max(换入,MoE)", "TPOT"]
        widths = [0.72, 0.88, 1.12, 0.86, 0.86, 1.42, 0.78, 0.78, 0.82, 0.82, 1.42, 0.92]
    else:
        head = ["输入", "每卡", "全局批", "HBM", "计算", "max(HBM,计算)", "换入", "MoE", "max(换入,MoE)", "TPOT"]
        widths = [0.82, 1.00, 1.28, 1.02, 1.02, 1.58, 1.02, 1.02, 1.58, 1.12]
    body, kinds = [], ["head"]
    moe_body = []
    for row in data["rows"]:
        _n, found = pack(row[f"{kind}{tag}"])
        view = shown(found, tier)
        if abs((view["td"] + view["gate"] + view["tc"]) - view["moe"]) > 1e-9:
            raise RuntimeError((kind, tag, row["S"], view))
        if abs((view["left"] + view["right"]) - view["t"]) > 1e-9:
            raise RuntimeError((kind, tag, row["S"], view))
        kinds.append("key" if row["S"] in (1048576, 4194304) else "body")
        cells = [
            fmt_len(row["S"]),
            fmt_bs(found["n"]),
            fmt_bs(found["n"] * v4.N),
            f"{view['hbm']:.3f}",
            f"{view['ca']:.3f}",
            f"{view['left']:.3f}",
        ]
        if tier:
            cells.extend([f"{view['t1']:.3f}", f"{view['t2']:.3f}"])
        cells.extend([
            f"{view['swap']:.3f}",
            f"{view['moe']:.3f}",
            f"{view['right']:.3f}",
            f"{view['t']:.3f}",
        ])
        body.append(cells)
        moe_body.append([
            fmt_len(row["S"]),
            fmt_bs(found["n"]),
            fmt_bs(found["n"] * v4.N),
            f"{view['td']:.3f}",
            f"{view['tw']:.3f}",
            f"{view['tg']:.3f}",
            f"{view['gate']:.3f}",
            f"{view['tc']:.3f}",
            f"{view['moe']:.3f}",
        ])
    top = ui.add_table(
        slide, 0.36, 1.12,
        widths,
        [head] + body,
        [0.28] + [0.30] * len(body),
        kinds,
        size=12,
    )
    margins(top)
    ui.textbox(
        slide, 0.40, 3.56, 12.4, 0.24,
        "MoE 逐项：派发 + max(权重, GEMM) + 合并",
        13, True, ui.ACCENT, anchor=MSO_ANCHOR.MIDDLE,
    )
    moe_head = ["输入", "每卡", "全局批", "派发", "权重", "GEMM", "max(权重,GEMM)", "合并", "MoE"]
    moe_w = [0.90, 1.15, 1.48, 1.42, 1.42, 1.35, 2.00, 1.35, 1.43]
    bottom = ui.add_table(
        slide, 0.40, 3.84,
        moe_w,
        [moe_head] + moe_body,
        [0.36] + [0.40] * len(moe_body),
        kinds,
        size=14,
    )
    margins(bottom)


def slide_pie_hbm(prs, blank, data):
    columns = []
    for row in data["rows"]:
        n, _found = pack(row["hbm30"])
        columns.append(pie_label(fmt_len(row["S"]), n * v4.N, parts_hbm(row["S"], n)))
    win64 = columns[0][1][2][1]
    tot64, pct64 = share(columns[0][1])
    tot4, pct4 = share(columns[-1][1])
    slide_pies(
        prs, blank, 12,
        "不卸载：HBM 里这条 KV 怎么拆",
        "30 毫秒只放 HBM 的吞吐最高批    ·    每卡    ·    四块都在 GPU HBM",
        "没有 cache，也没有 DDR。饼是 HBM 上这一批 KV 的内部构成：CSA index、HCA、sliding window、CSA latent。",
        columns,
        f"64K 合计 {gb_pie(tot64)}，CSA latent {pct64[3]:.1f}%，CSA index {pct64[0]:.1f}%，HCA {pct64[1]:.1f}%，sliding window {pct64[2]:.1f}%（{gb_pie(win64)}）。\n"
        f"4M 合计 {gb_pie(tot4)}，CSA latent {pct4[3]:.1f}%，CSA index {pct4[0]:.1f}%，HCA {pct4[1]:.1f}%，sliding window {pct4[2]:.1f}%。window 不随长度涨，饼上不再画出这一小段。\n"
        "七档的比例几乎一样，变的是每卡条数和这四块的字节。",
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


def check():
    hot, cold, _read = hot_cold(1048576)
    assert abs(hot + cold - v4.store_seq(1048576)) < 1.0
    n_fit = int(v4.ROOM_GPU // v4.store_seq(1048576))
    assert decode_tier(n_fit, 1048576)["swap"] < 1e-9
    for s in v4.LENGTHS:
        _best, _last = search(s, 0.030, decode_tier)
        row = _best[2]
        assert row["t1_h"] < 1.0 and row["t2_h"] < 1.0, (s, row["t1_h"], row["t2_h"])


def main():
    check()
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "N+2：20T V4，一级在网 cache，二级 6.4 Tb/s"
    blank = prs.slide_layouts[6]
    slide_open(prs, blank, data)
    slide_bytes(prs, blank, data)
    slide_place(prs, blank, data)
    slide_formula(prs, blank)
    slide_where(prs, blank, data)
    slide_walk(prs, blank, data)
    slide_ten(prs, blank, data)
    slide_h2d(prs, blank, data, 8, "30", "30 毫秒：两级池相对 H2D 卸载的吞吐")
    slide_h2d(prs, blank, data, 9, "10", "10 毫秒：两级池相对 H2D 卸载的吞吐")
    slide_pie_tier(prs, blank, data)
    slide_pie_host(prs, blank, data)
    slide_pie_hbm(prs, blank, data)
    page = 13
    for tag in ("30", "10"):
        for kind, path_name, how in PATHS:
            slide_tpot(prs, blank, data, page, tag, kind, path_name, how)
            page += 1
    prs.save(PPT)
    print("slides", len(prs.slides), "overflow", audit(prs))
    for row in data["rows"]:
        parts = [fmt_len(row["S"])]
        for tag in ("10", "30"):
            hn, hr = pack(row[f"hbm{tag}"])
            tn, tr = pack(row[f"tier{tag}"])
            parts.append(
                f"{tag} hbm {hn}/{ms2(hr['t'])}/{fmt_rate(tps_of(hn, hr))}"
                f" tier {tn}/{ms2(tr['t'])}/{fmt_rate(tps_of(tn, tr))}"
                f" swap {ms2(tr['swap'])} moe {ms2(tr['moe'])}"
                f" T2 {tr['t2_c']/1e9:.1f}"
            )
        for tag in ("10", "30"):
            hn, hr = pack(row[f"host{tag}"])
            parts.append(
                f"h2d{tag} {hn}/{ms2(hr['t'])}/{fmt_rate(tps_of(hn, hr))}"
                f" DDR {(hr['ddr_h']+hr['ddr_c'])/1e9:.1f}"
            )
        print(" | ".join(parts))


if __name__ == "__main__":
    main()
