#!/usr/bin/env python3
"""V4.1-Flash skeleton extrapolated to 20T on the N+2 256-GPU supernode.

The published model is DeepSeek-V4.1-Flash: 40 layers, hidden 5120,
40-layer causal encoder-decoder, CSA2, 552B backbone. The 20T deck
keeps that skeleton and only increases the routed-expert count, the
same way the V4-Pro deck went from 384 experts to 4951.

Decode KV offload is three placements of the CSA2 candidate pool:

1. Local HBM only. The batch stops when the whole KV fills the room.
2. The candidate pool's overflow is read from host DDR at 160 GB/s.
   Host capacity is 96 GB per GPU.
3. Main KV lives in the unlimited DDR pool. The candidate pool is
   resident in the 30 switches' 64 GB HBM and returns at the 4.80 TB/s
   D2D rate. Indexer K and the sliding window stay in GPU HBM.

Global KV is 890 bytes per token: three encoder Full layers at
compression 2 and one decoder Full layer at compression 1, each entry
288 bytes of FP4 main KV plus 68 bytes of MXFP4 indexer K.
The hierarchical pool is 2048 blocks of 8 positions, 16384 positions.
"""

from __future__ import annotations

import importlib.util
import math

spec = importlib.util.spec_from_file_location(
    "slo_ui", "/agent/repos/ucl-mpcomm/docs/build_deepseek_20t_slo_ppt.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

N, NODE = 256, 8
TP = 8
DP = N // TP
PF_N = 24
PF_DP = PF_N // TP
L, L_ENC = 40, 20
H, DFF, TOPK = 5120, 2304, 6
W_LAYER = 3 * H * DFF
W_ONE = W_LAYER * L
BACKBONE = 552e9
PUB_EXPERTS = 384
OTHER = BACKBONE - PUB_EXPERTS * W_ONE
E = math.ceil((2e13 - OTHER) / W_ONE)
TOTAL = E * W_ONE + OTHER
SHARED = W_ONE
EMBED = 2 * 129280 * H
ATTN = OTHER - SHARED - EMBED
ACT_DEC = 7 * W_ONE + ATTN + 129280 * H
ACT_PF = 7 * W_LAYER * L_ENC + ATTN * (L_ENC / L) + 129280 * H

HBM_CAP = 640e9
HBM_BW = 33e12 * 0.80
PEAK = 48e15 * 0.70
D2D = 48e12 / 8 * 0.80
P2P = (NODE - 1) * (1.6e12 / 8) * 0.80
HOST = min(1.6e12 / 8 * 0.80, 2e12 * 0.80 / NODE)
DDR_CAP = 768e9 / NODE
PREFIX = (800e9 / 8) * 0.25
POOL = 51.2e12 / 8 * 0.80
COLL = 5e-6
RESERVE = 6e9
ROUTED = E * W_ONE * 0.5
ROOM = N * (HBM_CAP - ROUTED / N - SHARED - ATTN / TP - RESERVE)

MAIN, INDEX = 288, 68
BPT = 890
WIN, SWA_B = 128, 512
FIXED = L * WIN * SWA_B
INDEX_FLOP = 2 * 32 * 128
CORE_FLOP = 2 * 2 * 64 * 512
POOL_POS = 2048 * 8
SWITCH_HBM = 64e9
N_SWITCH = 30
HIT = 0.995
OUT_LEN = 512
LENGTHS = (65536, 131072, 262144, 524288, 1048576, 2097152, 4194304)
MODES = ("hbm", "host", "sw")
MODE_NAME = {"hbm": "本地 HBM", "host": "主机 DDR", "sw": "交换 HBM"}

SLIDES = 13
FOOTER = "V4.1 外扩 20T    ·    N+2    ·    640 GB / 48P FP4    ·    Decode 256 卡    ·    拉 KV 25%    ·    CSA2 2048 块"
ui.SLIDES = SLIDES
ui.FOOTER = FOOTER

NAVY, ACCENT, TEAL = ui.NAVY, ui.ACCENT, ui.TEAL
INK, MUTED, WHITE = ui.INK, ui.MUTED, ui.WHITE
GOLD, DDR_COLOR = ui.GOLD, ui.DDR_COLOR


def room_bytes(ngpu):
    per = HBM_CAP - ROUTED / ngpu - SHARED - ATTN / TP - RESERVE
    return per, ngpu * per


def align(m):
    if m <= 0:
        return 1.0
    return m / (math.ceil(m / 16.0) * 16)


def pool_pos(s):
    return min(float(s), POOL_POS)


def index_seq(s):
    return 2.5 * s * INDEX + FIXED


def main_seq(s):
    return 2.5 * s * MAIN


def store_seq(s):
    return s * BPT + FIXED


def offload_bytes(s):
    """Decoder candidate pool plus one fetch of each encoder group's top-512."""
    enc = 3 * min(512.0, s / 2.0) * MAIN
    return enc + pool_pos(s) * MAIN


def index_read(s):
    return index_seq(s) + 4 * pool_pos(s) * INDEX


def expert(tokens, ngpu, layers):
    tokens = max(float(tokens), 0.0)
    mean = tokens * TOPK / ngpu
    hot = min(tokens * TOPK, mean + 2 * math.sqrt(max(mean * (1 - 1 / ngpu), 0.0)))
    frac = 1 - math.exp(-TOPK * tokens / E) if tokens > 0 else 0.0
    experts = E / ngpu
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_rows = e_hot * math.ceil(tpe / 16) * 16 if e_hot else 0.0
    shared_rows = math.ceil(max(1, math.ceil(tokens / ngpu)) / 16) * 16
    t_w = (e_hot * W_LAYER * layers * 0.5 + W_LAYER * layers) / HBM_BW
    t_g = (routed_rows + shared_rows) * 6 * H * DFF * layers / PEAK
    t_d = layers * (COLL + hot * H * 1 / D2D)
    t_c = layers * (COLL + hot * H * 2 / D2D)
    return {"t": t_d + max(t_w, t_g) + t_c, "tw": t_w, "tg": t_g, "td": t_d, "tc": t_c}


def allreduce(rows, layers):
    per = 2 * (TP - 1) / TP * rows * H * 2
    return layers * (COLL + per / P2P)


def score_flops(s):
    sel_e = min(512.0, s / 2.0)
    sel_d = min(512.0, float(s))
    idx = 3 * (s / 2.0) * INDEX_FLOP + s * INDEX_FLOP + 4 * pool_pos(s) * INDEX_FLOP
    core = (18 * (sel_e + WIN) + 20 * (sel_d + WIN) + 2 * WIN) * CORE_FLOP
    return idx + core


def prefill(bs, s, ngpu, hit=HIT):
    n = math.ceil(bs / (ngpu // TP))
    p, q = hit * s, (1 - hit) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    idx = 3 * INDEX_FLOP * (context / 2.0)
    sel = min(512.0, s / 2.0)
    core = 18 * CORE_FLOP * (sel + WIN) * q + 2 * CORE_FLOP * WIN * q
    proj = 2 * ATTN * (L_ENC / L) * q
    t_compute = n * (idx + core + proj) / (TP * PEAK * align(rows))
    t_pull = n * (p * BPT) / (TP * PREFIX) if PREFIX else 0.0
    hbm_bytes = ATTN / TP + n * (store_seq(s) + q * BPT) / TP
    t_hbm = hbm_bytes / HBM_BW
    t_ar = allreduce(rows, L_ENC)
    moe = expert(bs * q, ngpu, L_ENC)
    return {
        "t": t_pull + max(t_hbm, t_compute) + t_ar + moe["t"],
        "pull": t_pull,
        "hbm": t_hbm,
        "compute": t_compute,
        "ar": t_ar,
        "moe": moe["t"],
        "n": n,
        "q": q,
    }


def decode(bs, s, mode):
    """Return None when the placement cannot hold this batch."""
    n = math.ceil(bs / DP)
    idx_b = bs * index_seq(s)
    main_b = bs * main_seq(s)
    if idx_b > ROOM:
        return None
    moved = offload_bytes(s)
    if mode == "hbm":
        if idx_b + main_b > ROOM:
            return None
        spill = 0.0
        swap_b = 0.0
        resident = moved
        bw = None
    elif mode == "host":
        spill_b = max(main_b - (ROOM - idx_b), 0.0)
        if spill_b / N > DDR_CAP:
            return None
        spill = spill_b / main_b if main_b else 0.0
        swap_b = spill * moved
        resident = (1.0 - spill) * moved
        bw = HOST
    elif mode == "sw":
        if bs * moved / N_SWITCH > SWITCH_HBM:
            return None
        spill = 1.0
        swap_b = moved
        resident = 0.0
        bw = D2D
    else:
        raise ValueError(mode)
    read = n * swap_b / TP
    t_swap = read / bw if bw else 0.0
    t_hbm = (n * (index_read(s) + resident) / TP + ATTN / TP) / HBM_BW
    t_ca = n * (score_flops(s) + 2 * ATTN) / (TP * PEAK * align(n))
    t_ar = allreduce(n, L)
    moe = expert(bs, N, L)
    kernel = max(t_ca, t_hbm)
    return {
        "t": t_swap + kernel + t_ar + moe["t"],
        "swap": t_swap,
        "hbm": t_hbm,
        "ca": t_ca,
        "kernel": kernel,
        "ar": t_ar,
        "moe": moe["t"],
        "spill": spill,
        "n": n,
        "idx_b": idx_b,
        "main_b": main_b,
    }


def search_prefill(s, ngpu, limit=10.0):
    per, _ = room_bytes(ngpu)
    cap = int(per * ngpu // store_seq(s)) if per > 0 else 0

    def ok(bs):
        return 1 <= bs <= cap and prefill(bs, s, ngpu)["t"] <= limit + 1e-9

    if cap < 1 or not ok(1):
        return 0, prefill(1, s, ngpu), cap
    lo, hi = 1, 2
    while ok(hi) and hi < cap:
        lo, hi = hi, min(cap, hi * 2)
    if ok(hi):
        lo = hi
    else:
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if ok(mid):
                lo = mid
            else:
                hi = mid
    return lo, prefill(lo, s, ngpu), cap


def search_decode(s, limit, mode):
    def ok(bs):
        row = decode(bs, s, mode)
        return row is not None and row["t"] <= limit + 1e-9

    if not ok(1):
        row = decode(1, s, mode)
        return 0, row if row is not None else decode(1, s, "hbm")
    lo, hi = 1, 2
    while ok(hi) and hi < 8_000_000:
        lo, hi = hi, hi * 2
    if ok(hi):
        lo = hi
    else:
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if ok(mid):
                lo = mid
            else:
                hi = mid
    return lo, decode(lo, s, mode)


def max_cold():
    lo, hi = 1.0, 64e6
    for _ in range(48):
        mid = (lo + hi) / 2
        if prefill(1, mid, N, hit=0.0)["t"] > 10.0:
            hi = mid
        else:
            lo = mid
    s = int(math.floor(lo))
    while s > 1 and prefill(1, s, N, hit=0.0)["t"] > 10.0:
        s -= 1
    while prefill(1, s + 1, N, hit=0.0)["t"] <= 10.0:
        s += 1
    return s, prefill(1, s, N, hit=0.0)


def mem_slice(bs, s, mode):
    """Per-GPU bytes. Case sw puts main KV in the DDR pool."""
    weight = (ROUTED / N + SHARED + ATTN / TP + RESERVE) / 1e9
    room = (HBM_CAP - ROUTED / N - SHARED - ATTN / TP - RESERVE) / 1e9
    idx = bs * index_seq(s) / N / 1e9
    main = bs * main_seq(s) / N / 1e9
    if mode == "sw":
        hbm_kv = idx
        ddr = main
    elif mode == "host":
        hbm_kv = min(idx + main, room)
        ddr = max(idx + main - room, 0.0)
    else:
        hbm_kv = idx + main
        ddr = 0.0
    free = max(room - hbm_kv, 0.0)
    return {"weight": weight, "hbm": hbm_kv, "free": free, "ddr": ddr, "room": room}


def fmt_len(s):
    if s >= 1048576 and s % 1048576 == 0:
        return f"{s // 1048576}M"
    if s % 1024 == 0:
        return f"{s // 1024}K"
    return f"{s:,}"


def fmt_bs(n):
    return f"{int(n):,}"


def fmt_rate(v):
    if v >= 1e8:
        return f"{v / 1e8:.2f} 亿"
    x = v / 1e4
    if x >= 100:
        return f"{x:.0f} 万"
    if x >= 10:
        return f"{x:.1f} 万"
    return f"{x:.2f} 万"


def signed_pct(new, old):
    if not old:
        return "—"
    return f"{(new - old) / old * 100:+.1f}%"


def sec(v):
    if v >= 0.1:
        return f"{v:.2f} 秒"
    return f"{v * 1e3:.1f} 毫秒"


def ms(v):
    return f"{v * 1e3:.2f} 毫秒"


def collect():
    cold_s, cold = max_cold()
    rows = []
    for s in LENGTHS:
        b256, p256, cap256 = search_prefill(s, N)
        b24, p24, cap24 = search_prefill(s, PF_N)
        b16, p16, cap16 = search_prefill(s, 16)
        dec = {}
        for mode in MODES:
            for limit, tag in ((0.010, "10"), (0.030, "30")):
                bs, row = search_decode(s, limit, mode)
                dec[f"{mode}{tag}"] = bs
                dec[f"d{mode}{tag}"] = row
                dec[f"m{mode}{tag}"] = mem_slice(bs, s, mode)
        rows.append({
            "S": s,
            "b256": b256, "p256": p256, "cap256": cap256,
            "b24": b24, "p24": p24, "cap24": cap24,
            "b16": b16, "p16": p16, "cap16": cap16,
            **dec,
        })
    return {"cold_s": cold_s, "cold": cold, "cold4": prefill(1, 4194304, N, hit=0.0), "rows": rows}


def by_len(data, s):
    return next(row for row in data["rows"] if row["S"] == s)


def tps_d(row, mode, tag):
    return row[f"{mode}{tag}"] / row[f"d{mode}{tag}"]["t"]


def slide_conclusion(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 1, "4M 冷请求进了 10 秒，卸载差在长上下文", "V4.1 → 20T    ·    本页 Decode 先看本地 HBM    ·    三种卸载在第 11 页")
    ui.banner(slide, 0.92, "99.5% 命中。Prefill 只跑编码器 20 层。Decode 跑满 40 层。拉 KV 每卡 25 GB/s。本地 HBM 不换入。")
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    head = ["约束", "64K 全局批", "64K 系统 TPS", "4M 全局批", "4M 系统 TPS", "4M 实际耗时"]
    body = [
        ["TTFT ≤ 10 秒", fmt_bs(r64["b256"]), fmt_rate(r64["b256"] * r64["S"] / r64["p256"]["t"]), fmt_bs(r4["b256"]), fmt_rate(r4["b256"] * r4["S"] / r4["p256"]["t"]), sec(r4["p256"]["t"])],
        ["TPOT ≤ 10 毫秒", fmt_bs(r64["hbm10"]), fmt_rate(tps_d(r64, "hbm", "10")), fmt_bs(r4["hbm10"]), fmt_rate(tps_d(r4, "hbm", "10")), ms(r4["dhbm10"]["t"])],
        ["TPOT ≤ 30 毫秒", fmt_bs(r64["hbm30"]), fmt_rate(tps_d(r64, "hbm", "30")), fmt_bs(r4["hbm30"]), fmt_rate(tps_d(r4, "hbm", "30")), ms(r4["dhbm30"]["t"])],
    ]
    ui.add_table(slide, 0.42, 1.48, [2.15, 1.85, 2.15, 1.85, 2.15, 2.35], [head] + body, [0.40, 0.46, 0.46, 0.46], ["head", "key", "body", "body"], size=14)
    rp = r64["b24"] / r64["p24"]["t"]
    rd = (r64["hbm10"] / r64["dhbm10"]["t"]) / OUT_LEN
    ui.gold(
        slide,
        3.50,
        2.55,
        f"冷请求不拉 prefix。4M 冷请求 TTFT {sec(data['cold4']['t'])}，落在 10 秒内。冷请求摸到 10 秒的输入是 {data['cold_s']:,}。\n"
        f"64K、30 毫秒的本地 HBM 批 {fmt_bs(r64['hbm30'])}，KV 还没占满 {ROOM/1e12:.1f} TB。交换 HBM 把候选池放进 30×64 GB，批量停在 {fmt_bs(r64['sw30'])}。\n"
        f"4M、30 毫秒：本地 HBM {fmt_bs(r4['hbm30'])}，主机 DDR {fmt_bs(r4['host30'])}，交换 HBM {fmt_bs(r4['sw30'])}。"
        f"TPS 相对本地 HBM 是 {signed_pct(tps_d(r4, 'host', '30'), tps_d(r4, 'hbm', '30'))} 和 {signed_pct(tps_d(r4, 'sw', '30'), tps_d(r4, 'hbm', '30'))}。\n"
        f"64K、输出 {OUT_LEN}、10 毫秒：24 卡 Prefill {rp:.0f} 请求/秒，Decode {rd:.0f} 请求/秒，{rd / rp:.1f} 份 Prefill 配 1 份 Decode。",
        14,
    )
    slide.notes_slide.notes_text_frame.text = (
        f"cold {data['cold_s']} t={data['cold']['t']:.4f} cold4={data['cold4']['t']:.4f} "
        f"64k hbm30={r64['hbm30']} sw30={r64['sw30']} 4m hbm30={r4['hbm30']} host30={r4['host30']} sw30={r4['sw30']}"
    )


def slide_model(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 2, "层数和隐藏不动，路由专家加到 14123", "V4.1-Flash 552B    ·    外推到 20T    ·    Engram 不进这 20T")
    ui.banner(slide, 0.92, "CED：Prefill 走编码器，激活约一半。CSA2 四层 Full、四层 Reindex，其余 Reuse。TopK 仍是 6。")
    head = ["项目", "V4.1-Flash 论文", "20T 外推"]
    body = [
        ["骨干参数", "5.52×10^11", f"{TOTAL/1e12:.4f}×10^12"],
        ["路由专家", "384，中间维 2304", f"{E}，中间维仍 2304"],
        ["层 / 隐藏", "40 层，d = 5120", "保持 40 / 5120"],
        ["编码器 / 解码器", "20 + 20，解码 KV 由编码器投影", "切分不动"],
        ["每 token 激活", "Prefill 8B，Decode 16B", f"{ACT_PF/1e9:.2f}B / {ACT_DEC/1e9:.2f}B"],
        ["CSA2", "Full 4，Reindex 4，Reuse 其余", "模式和压缩比不动"],
        ["注意力 Top-K / 滑窗", "512 / 128", "保持 512 / 128"],
        ["Engram", "196B，放在主机", "不计入 20T，不占 GPU HBM"],
    ]
    kinds = ["head"] + ["key" if i in (1, 4, 5) else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.46, [2.55, 4.85, 5.10], [head] + body, [0.30] + [0.36] * 8, kinds, size=13)
    ui.gold(
        slide,
        5.15,
        1.90,
        f"E = ceil((2×10^13 − {OTHER/1e9:.3f}×10^9) / {W_ONE/1e9:.3f}×10^9) = {E}。\n"
        f"总参数 {TOTAL/1e12:.4f}×10^12，比 2×10^13 多 {(TOTAL - 2e13)/1e9:.2f}×10^9。单个专家 = 3 × 5120 × 2304 × 40 = {W_ONE/1e9:.3f}×10^9。\n"
        f"激活是 6 个路由专家加 1 个共享专家，再加上注意力和词表。论文写 8B / 16B，这里加总是 {ACT_PF/1e9:.2f}B / {ACT_DEC/1e9:.2f}B。\n"
        "Full 层是 2、8、14、20。Reindex 层是 24、28、32、36，只在第 20 层的候选池里打分。",
        14,
    )


def slide_kv(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 3, "全局 KV 是 890 字节，每步搬 2048 块", "CSA2    ·    FP4 主 KV    ·    候选池 2048 块 × 8 位置")
    ui.banner(slide, 0.92, "2048 是块。每块 8 个位置，解码器候选池是 16384 条主 KV。后面的 Reindex 只在这 16384 条里再挑 512。")
    head = ["一项", "怎么数", "结果"]
    body = [
        ["主 KV 一条", "512 路 E2M1 + 每 16 路一个 E4M3", "288 字节"],
        ["Indexer K 一条", "128 路 MXFP4 + 每 32 路一个 scale", "68 字节"],
        ["每 token 全局 KV", "编码器 3 层 ÷2，解码器 1 层 ×1", "2.5 × 356 = 890 字节"],
        ["一条 4M 序列", "890 × 4,194,304 + 滑窗", "3.74 GB"],
        ["候选池", "2048 × 8 × 288", "4.72 MB"],
        ["编码器三组 Top-512", "3 × 512 × 288，每步再取一次", "0.44 MB"],
        ["每步搬走的字节", "候选池 + 编码器三组", "5.16 MB / 序列"],
        ["滑窗", "40 层 × 128 × 512，FP8", "2.62 MB，留在 GPU"],
    ]
    kinds = ["head"] + ["key" if i in (2, 6) else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.46, [2.70, 5.35, 4.45], [head] + body, [0.32] + [0.36] * 8, kinds, size=13)
    ui.gold(
        slide,
        5.40,
        1.65,
        "索引和滑窗留在 GPU，Full 层的全量打分不走卸载链路。卸载链路每步只搬上面这 5.16 MB。\n"
        "本地 HBM 和主机 DDR：主 KV 先占 GPU 房间，装不下的部分才按溢出比例搬这 5.16 MB。\n"
        "交换 HBM：主 KV 整份放 DDR 池，16384 条候选池放在 30 颗交换芯片的 64 GB 里，每步按 D2D 4.80 TB/s 读回。30 × 64 GB 大约装 37.2 万条序列的候选池。",
        13,
    )


def slide_hardware(prs, blank):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 4, "三条卸载路径共用这一套带宽", "N+2    ·    参数面 800 Gb/s    ·    D2D 48 Tb/s    ·    拉 KV 25%")
    head = ["项目", "标称", "这一档怎么用"]
    body = [
        ["FP4 算力", "每卡 48 P", "×70% = 33.60 P。注意力和专家 GEMM 共用"],
        ["GPU HBM", "640 GB，33 TB/s", f"带宽 ×80% = 26.40 TB/s。KV 房间每卡 {ROOM/N/1e9:.0f} GB，副本 {ROOM/1e12:.1f} TB"],
        ["本地 HBM", "不换入", "主 KV 和索引都在 GPU。批量停在房间被占满的地方"],
        ["主机 DDR", "每机 2 TB/s，768 GB", f"换入 {HOST/1e9:.0f} GB/s，每卡容量 {DDR_CAP/1e9:.0f} GB。只搬溢出的候选池"],
        ["交换 HBM", "每颗 64 GB，30 颗", "候选池按 30 个平面切开。GPU 侧按 D2D 4.80 TB/s 读"],
        ["DDR 池", "每卡 51.2 Tb/s，容量不限", f"×80% = {POOL/1e12:.2f} TB/s。交换方案的主 KV 放这里"],
        ["D2D", "每卡单向 48 Tb/s", f"×80% = {D2D/1e12:.2f} TB/s。MoE 和交换 HBM 读候选池都走它"],
        ["参数面 / AllReduce", "800 Gb/s，机内 1.6 Tb/s", f"拉 KV {PREFIX/1e9:.0f} GB/s。AllReduce {P2P/1e9:.0f} GB/s"],
    ]
    kinds = ["head"] + ["key" if i in (2, 3, 4) else "body" for i in range(8)]
    ui.add_table(slide, 0.42, 1.42, [2.15, 3.55, 6.80], [head] + body, [0.30] + [0.42] * 8, kinds, size=13)
    ui.gold(
        slide,
        5.90,
        1.15,
        f"路由专家 FP4 表 {ROUTED/1e12:.2f} TB，256 卡每卡 {ROUTED/N/1e9:.1f} GB。共享专家 FP8 每卡 {SHARED/1e9:.2f} GB，注意力每卡 {ATTN/TP/1e9:.2f} GB，预留 6 GB。\n"
        "AllReduce 用机内 7 条 1.6 Tb/s ×80% = 1.12 TB/s，不走到 4.80 TB/s 的交换平面。",
        13,
    )


def slide_parallel(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 5, "Prefill 收到 24 卡，Decode 仍用 256", "Prefill TP=8 EP=24 DP=3    ·    Decode TP=8 EP=256 DP=32")
    ui.banner(slide, 0.92, "16 卡的专家表把 HBM 几乎占满。24 卡是 8 卡对齐下，10 秒批量仍由时间决定的最小副本。")
    head = ["", "Prefill", "Decode"]
    pf_room, pf_cluster = room_bytes(PF_N)
    dc_room, dc_cluster = room_bytes(N)
    r16 = by_len(data, 4194304)
    body = [
        ["切分", "TP=8，EP=24，DP=3\n一份副本 3 个机内组", "TP=8，EP=256，DP=32\n一份副本铺满超节点"],
        ["理由", "拉 KV 是每卡 25 GB/s\n加大 EP 不提高每卡 token/s", "长上下文的 KV 要吃房间\nMoE 也要把专家铺开"],
        ["每卡权重", f"路由 {ROUTED/PF_N/1e9:.0f} GB FP4\n注意力 {ATTN/TP/1e9:.2f} GB", f"路由 {ROUTED/N/1e9:.1f} GB FP4\n注意力 {ATTN/TP/1e9:.2f} GB"],
        ["KV 房间", f"每卡 {pf_room/1e9:.0f} GB\n副本 {pf_cluster/1e12:.2f} TB", f"每卡 {dc_room/1e9:.0f} GB\n副本 {dc_cluster/1e12:.1f} TB"],
    ]
    ui.add_table(slide, 0.42, 1.46, [1.70, 5.40, 5.40], [head] + body, [0.34, 0.62, 0.62, 0.62, 0.62], ["head", "key", "body", "body", "key"], size=13)
    r64 = by_len(data, 65536)
    per24 = r64["b24"] * r64["S"] / r64["p24"]["t"] / PF_N
    per256 = r64["b256"] * r64["S"] / r64["p256"]["t"] / N
    ui.gold(
        slide,
        5.15,
        1.90,
        f"64K 每卡 Prefill TPS：24 卡 {fmt_rate(per24)}，256 卡 {fmt_rate(per256)}。\n"
        f"16 卡每卡 KV 房间只有 {room_bytes(16)[0]/1e9:.1f} GB。4M 摸高批停在 {fmt_bs(r16['b16'])} 条，TTFT {sec(r16['p16']['t'])}，房间先满。\n"
        f"24 卡 4M 的时间批是 {fmt_bs(r16['b24'])}，显存上限 {fmt_bs(r16['cap24'])}，仍由 10 秒卡住。Decode 不跟着缩小。",
        13,
    )


def slide_tps(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 6, "本地 HBM 下，系统 TPS 随输入下降", "256 卡    ·    TTFT ≤ 10 秒    ·    TPOT ≤ 10 / 30 毫秒    ·    不换入")
    ui.banner(slide, 0.92, "这一页的 Decode 是本地 HBM。主机 DDR 和交换 HBM 的对比在第 11 页。Prefill TPS 用完整输入 token。")
    head = ["输入", "10 秒批", "Prefill TPS", "10 毫秒批", "10 毫秒 TPS", "30 毫秒批", "30 毫秒 TPS"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_bs(row["b256"]),
            fmt_rate(row["b256"] * row["S"] / row["p256"]["t"]),
            fmt_bs(row["hbm10"]),
            fmt_rate(tps_d(row, "hbm", "10")),
            fmt_bs(row["hbm30"]),
            fmt_rate(tps_d(row, "hbm", "30")),
        ])
    ui.add_table(slide, 0.42, 1.48, [1.15, 1.70, 2.05, 1.85, 2.05, 1.85, 1.85], [head] + body, [0.36] + [0.38] * len(body), kinds, size=14)
    r4 = by_len(data, 4194304)
    r64 = by_len(data, 65536)
    ui.gold(
        slide,
        5.05,
        1.95,
        f"64K 的 30 毫秒批 {fmt_bs(r64['hbm30'])}，实际 TPOT {ms(r64['dhbm30']['t'])}，KV 占用 {r64['mhbm30']['hbm']:.0f} GB/卡，房间还有空。\n"
        f"4M 的本地 HBM 在 10 毫秒和 30 毫秒是同一批 {fmt_bs(r4['hbm10'])}，实际 TPOT {ms(r4['dhbm10']['t'])}。房间先满，30 毫秒的余量用不上。\n"
        f"Prefill 从 64K 的 {fmt_rate(r64['b256'] * r64['S'] / r64['p256']['t'])} 降到 4M 的 {fmt_rate(r4['b256'] * r4['S'] / r4['p256']['t'])}，拉 KV 仍是大头。",
        14,
    )


def slide_prefill(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 7, "拉 KV 仍占掉 10 秒里的大部分", "256 卡 Prefill    ·    只跑编码器 20 层    ·    DP=32")
    ui.banner(slide, 0.92, "HBM 只有几毫秒到十几毫秒。计算列是编码器的 indexer 和 512 条稀疏注意力。四段相加等于 TTFT。")
    head = ["输入", "全局批", "拉 KV", "计算", "AR", "MoE", "HBM", "TTFT", "拉KV占比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        p = row["p256"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]), fmt_bs(row["b256"]), sec(p["pull"]), sec(p["compute"]),
            sec(p["ar"]), sec(p["moe"]), ms(p["hbm"]), sec(p["t"]), f"{p['pull'] / p['t'] * 100:.1f}%",
        ])
    ui.add_table(slide, 0.42, 1.46, [0.85, 1.35, 1.30, 1.25, 1.25, 1.25, 1.30, 1.30, 1.65], [head] + body, [0.34] + [0.36] * len(body), kinds, size=13)
    ui.gold(
        slide,
        4.55,
        2.45,
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE。\n"
        f"T_pull = n × (0.995×S×890) / (8 × {PREFIX/1e9:.0f} GB/s)。滑窗不进 prefix，Bounded Replay 在本地补。\n"
        "T_compute 只含编码器：3 个 Full 层的 indexer 按压缩比 2 计，18 层 CSA 各读 512+128，前两层只有滑窗。\n"
        f"T_AR 和 T_MoE 都是 20 层，不是 40 层。AllReduce {P2P/1e12:.2f} TB/s，MoE 的 dispatch / combine 走 {D2D/1e12:.2f} TB/s。\n"
        "n = ceil(全局批 / 32)。q = 0.005×S。",
        13,
    )


def slide_pf_tps(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 8, "24 卡系统 TPS 按卡数缩小，每卡持平", "Prefill EP=24    ·    对照 256 卡    ·    TTFT ≤ 10 秒")
    ui.banner(slide, 0.92, "系统 TPS 是一份副本的吞吐。24 卡约为 256 卡的 24/256，每卡 token/s 相同。")
    head = ["输入", "24卡批", "24卡 TPS", "24卡每卡", "256卡 TPS", "256卡每卡", "每卡比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        t24 = row["b24"] * row["S"] / row["p24"]["t"]
        t256 = row["b256"] * row["S"] / row["p256"]["t"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]), fmt_bs(row["b24"]), fmt_rate(t24), fmt_rate(t24 / PF_N),
            fmt_rate(t256), fmt_rate(t256 / N), f"{(t24 / PF_N) / (t256 / N) * 100:.1f}%",
        ])
    ui.add_table(slide, 0.42, 1.48, [1.05, 1.45, 1.90, 1.80, 2.05, 2.10, 2.15], [head] + body, [0.36] + [0.38] * len(body), kinds, size=14)
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    ui.gold(
        slide,
        5.05,
        1.95,
        f"64K：24 卡批 {fmt_bs(r64['b24'])}，TTFT {sec(r64['p24']['t'])}，显存上限 {fmt_bs(r64['cap24'])}。时间批更小，10 秒先到。\n"
        f"4M：24 卡批 {fmt_bs(r4['b24'])}，显存上限 {fmt_bs(r4['cap24'])}。256 卡批 {fmt_bs(r4['b256'])}，显存上限 {fmt_bs(r4['cap256'])}。\n"
        f"每卡比都在 100% 附近。拉 KV、AllReduce、MoE 都按卡摊开，副本放大不改变单卡耗时。",
        14,
    )


def slide_pf_time(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 9, "24 卡的 10 秒拆解和 256 卡同构", "24 卡 Prefill    ·    DP=3    ·    编码器 20 层")
    ui.banner(slide, 0.92, "版式同第 7 页。拉 KV 占比不变，批量约为 256 卡的 24/256。")
    head = ["输入", "全局批", "拉 KV", "计算", "AR", "MoE", "HBM", "TTFT", "拉KV占比"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        p = row["p24"]
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]), fmt_bs(row["b24"]), sec(p["pull"]), sec(p["compute"]),
            sec(p["ar"]), sec(p["moe"]), ms(p["hbm"]), sec(p["t"]), f"{p['pull'] / p['t'] * 100:.1f}%",
        ])
    ui.add_table(slide, 0.42, 1.46, [0.85, 1.25, 1.30, 1.25, 1.25, 1.25, 1.30, 1.30, 1.75], [head] + body, [0.34] + [0.36] * len(body), kinds, size=13)
    r64 = by_len(data, 65536)
    ui.gold(
        slide,
        4.55,
        2.45,
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE。\n"
        f"T_pull = n × (0.995×S×890) / (8 × {PREFIX/1e9:.0f} GB/s)。n = ceil(全局批 / {PF_DP})。\n"
        f"T_AR = 20 × (5 微秒 + 2×7/8 × n×q × 5120 × 2 / {P2P/1e12:.2f} TB/s)。\n"
        f"64K 拉 KV 占 {r64['p24']['pull'] / r64['p24']['t'] * 100:.1f}%，256 卡同一输入是 {r64['p256']['pull'] / r64['p256']['t'] * 100:.1f}%。",
        14,
    )


def slide_pf_hbm(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 10, "四档输入看 24 卡和 256 卡的 HBM", "每卡    ·    10 秒摸高批    ·    上排 256 卡，下排 24 卡")
    ui.banner(slide, 0.92, "三块是权重加预留、HBM 里的 KV、HBM 空闲。KV 按 890 字节/token 的整份序列。")
    lengths = (65536, 262144, 1048576, 4194304)
    colors = (NAVY, TEAL, "D5DDE6")
    names = ("权重+预留", "HBM KV", "空闲")
    for i, s in enumerate(lengths):
        row = by_len(data, s)
        x0 = 0.38 + i * 3.24
        ui.textbox(slide, x0, 1.40, 3.10, 0.26, fmt_len(s), 16, True, NAVY, PP_ALIGN.CENTER)
        for j, (ngpu, bs, tag) in enumerate(((N, row["b256"], "256 卡"), (PF_N, row["b24"], "24 卡"))):
            per, _ = room_bytes(ngpu)
            weight = ROUTED / ngpu + SHARED + ATTN / TP + RESERVE
            kv = row_bs_store(bs, s) / ngpu
            free = HBM_CAP - weight - kv
            values = (weight / 1e9, kv / 1e9, max(free, 0.0) / 1e9)
            cy = 2.22 if j == 0 else 4.42
            ui.add_pie(slide, x0 + 1.55, cy, 0.48, list(zip(values, colors)))
            ui.textbox(slide, x0, cy + 0.52, 3.10, 0.20, f"{tag} · 批 {fmt_bs(bs)}", 12, True, NAVY, PP_ALIGN.CENTER)
            ui.add_key(
                slide, x0 + 0.35, cy + 0.74, 2.55,
                [(color, f"{name}  {val:.0f} GB") for color, name, val in zip(colors, names, values)],
                size=11, row=0.18,
            )


def row_bs_store(bs, s):
    return bs * store_seq(s)


def slide_cases(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 11, "短上下文被 64 GB 拦住，4M 才拉开", "Decode    ·    本地 HBM / 主机 DDR / 交换 HBM    ·    格内是系统 TPS")
    ui.banner(slide, 0.88, "本地和主机在 KV 还没溢出时是同一批。交换方案每步都从交换 HBM 读候选池，并且整池要放进 30×64 GB。")
    head = ["输入", "HBM·10ms", "主机·10ms", "交换·10ms", "HBM·30ms", "主机·30ms", "交换·30ms"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            fmt_rate(tps_d(row, "hbm", "10")),
            fmt_rate(tps_d(row, "host", "10")),
            fmt_rate(tps_d(row, "sw", "10")),
            fmt_rate(tps_d(row, "hbm", "30")),
            fmt_rate(tps_d(row, "host", "30")),
            fmt_rate(tps_d(row, "sw", "30")),
        ])
    ui.add_table(slide, 0.42, 1.40, [1.05, 1.85, 1.90, 1.90, 1.90, 1.95, 1.95], [head] + body, [0.28] + [0.26] * len(body), kinds, size=12)
    head2 = ["输入", "HBM 10ms批", "主机 10ms批", "交换 10ms批", "HBM 30ms批", "主机 30ms批", "交换 30ms批"]
    body2, kinds2 = [], ["head"]
    for row in data["rows"]:
        kinds2.append("key" if row["S"] in (65536, 4194304) else "body")
        body2.append([
            fmt_len(row["S"]),
            fmt_bs(row["hbm10"]), fmt_bs(row["host10"]), fmt_bs(row["sw10"]),
            fmt_bs(row["hbm30"]), fmt_bs(row["host30"]), fmt_bs(row["sw30"]),
        ])
    ui.add_table(slide, 0.42, 3.70, [1.05, 1.85, 1.90, 1.90, 1.90, 1.95, 1.95], [head2] + body2, [0.26] + [0.24] * len(body2), kinds2, size=11)
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    ui.gold(
        slide,
        5.82,
        1.25,
        f"64K、30 毫秒：本地 {fmt_bs(r64['hbm30'])}，交换 {fmt_bs(r64['sw30'])}，TPS {signed_pct(tps_d(r64, 'sw', '30'), tps_d(r64, 'hbm', '30'))}。候选池 5.16 MB × 批量 / 30 颗，64 GB 先满。\n"
        f"4M、30 毫秒：主机批量 {fmt_bs(r4['host30'])}，步时 {ms(r4['dhost30']['t'])}，TPS {signed_pct(tps_d(r4, 'host', '30'), tps_d(r4, 'hbm', '30'))}。批量大了，步时更长。\n"
        f"交换批量 {fmt_bs(r4['sw30'])}，步时用满 30 毫秒，TPS {signed_pct(tps_d(r4, 'sw', '30'), tps_d(r4, 'hbm', '30'))}。",
        13,
    )


def slide_split(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 12, "4M 的 30 毫秒里，交换读候选池不到 1 毫秒", "TPOT 拆解    ·    64K 与 4M    ·    10 毫秒和 30 毫秒")
    head = ["场景", "批", "SWAP", "计算", "AR", "MoE", "TPOT"]
    body, kinds = [], ["head"]
    for s, tag, label in (
        (65536, "10", "64K · 10 毫秒"),
        (65536, "30", "64K · 30 毫秒"),
        (4194304, "10", "4M · 10 毫秒"),
        (4194304, "30", "4M · 30 毫秒"),
    ):
        row = by_len(data, s)
        for mode in MODES:
            d = row[f"d{mode}{tag}"]
            kinds.append("key" if s == 4194304 and tag == "30" else "body")
            body.append([
                f"{label} · {MODE_NAME[mode]}",
                fmt_bs(row[f"{mode}{tag}"]),
                ms(d["swap"]), ms(d["kernel"]), ms(d["ar"]), ms(d["moe"]), ms(d["t"]),
            ])
    ui.add_table(slide, 0.42, 1.36, [3.15, 1.55, 1.45, 1.45, 1.45, 1.45, 1.50], [head] + body, [0.28] + [0.32] * len(body), kinds, size=12)
    r4 = by_len(data, 4194304)
    ui.gold(
        slide,
        5.70,
        1.35,
        "TPOT = T_SWAP + max(T_HBM, T_compute) + T_AR + T_MoE。计算列是这两项里更大的一个。\n"
        f"4M、30 毫秒、交换 HBM：SWAP {ms(r4['dsw30']['swap'])}，计算 {ms(r4['dsw30']['kernel'])}，AR {ms(r4['dsw30']['ar'])}，MoE {ms(r4['dsw30']['moe'])}。\n"
        "计算列主要是索引打分的 HBM 读。候选池 5.16 MB 走 4.80 TB/s，换入不再是大头。64K 的大头是 AllReduce。",
        13,
    )


def slide_pies(prs, blank, data):
    slide = prs.slides.add_slide(blank)
    ui.chrome(slide, 13, "交换方案把主 KV 放进 DDR 池，索引留在 HBM", "30 毫秒批    ·    每卡    ·    上表含三种方案的 DDR")
    head = ["输入", "本地 HBM KV", "主机 DDR", "交换 HBM 索引", "交换 DDR 池", "交换批"]
    body, kinds = [], ["head"]
    for row in data["rows"]:
        kinds.append("key" if row["S"] in (65536, 1048576, 4194304) else "body")
        body.append([
            fmt_len(row["S"]),
            f"{row['mhbm30']['hbm']:.0f} GB",
            f"{row['mhost30']['ddr']:.0f} GB",
            f"{row['msw30']['hbm']:.0f} GB",
            f"{row['msw30']['ddr']:.0f} GB",
            fmt_bs(row["sw30"]),
        ])
    ui.add_table(slide, 0.42, 1.36, [1.15, 2.15, 1.90, 2.35, 2.15, 2.30], [head] + body, [0.28] + [0.24] * len(body), kinds, size=12)
    shown = [by_len(data, s) for s in (65536, 262144, 1048576, 4194304)]
    colors = (NAVY, TEAL, "D5DDE6", DDR_COLOR)
    labels = ("权重+预留", "HBM 索引", "HBM 空闲", "DDR 池")
    for i, row in enumerate(shown):
        x0 = 0.38 + i * 3.24
        mem = row["msw30"]
        values = (mem["weight"], mem["hbm"], mem["free"], mem["ddr"])
        ui.add_pie(slide, x0 + 0.72, 4.55, 0.55, list(zip(values, colors)))
        ui.textbox(slide, x0, 5.15, 3.10, 0.22, f"{fmt_len(row['S'])} · 交换 · 批 {fmt_bs(row['sw30'])}", 12, True, NAVY, PP_ALIGN.CENTER)
        ui.add_key(
            slide, x0 + 0.15, 5.38, 2.95,
            [(c, f"{n}  {v:.0f} GB") for c, n, v in zip(colors, labels, values)],
            size=11, row=0.20,
        )


def write_md(path, data):
    r64, r4 = by_len(data, 65536), by_len(data, 4194304)
    lines = [
        "# V4.1 外扩 20T：N+2 上的三种 KV 卸载",
        "",
        "骨架是 DeepSeek-V4.1-Flash。外推只增加路由专家。Engram 196B 留在主机，不进 20T，不占 GPU HBM。",
        "一份 Decode 副本是 256 卡。Prefill 用 24 卡。逐步数字和 PPT 由 `docs/build_deepseek_v41_20t_slo_ppt.py` 生成。",
        "",
        "## 1. 模型",
        "",
        "```",
        f"W_ONE = 3 × 5120 × 2304 × 40 = {W_ONE:.0f}",
        f"其余 = 5.52e11 − 384 × W_ONE = {OTHER:.0f}",
        f"E = ceil((2e13 − 其余) / W_ONE) = {E}",
        f"总参数 = {TOTAL:.0f}",
        f"激活 Prefill / Decode = {ACT_PF:.0f} / {ACT_DEC:.0f}",
        f"FP4 专家表 = {ROUTED:.0f} 字节 = {ROUTED/1e12:.3f} TB",
        "```",
        "",
        "论文给出的激活是 Prefill 8B、Decode 16B。这里按 6 路由 + 1 共享、注意力和词表加总，差在四舍五入。",
        "",
        "## 2. KV",
        "",
        "主 KV 一条 = 512×0.5 + 512/16 = 288 字节。Indexer K 一条 = 128×0.5 + 128/32 = 68 字节。",
        "每 token = (3/2 + 1) × 356 = 890 字节。滑窗 40×128×512 = 2.62 MB，留在 GPU。",
        "候选池 = 2048×8×288 = 4.72 MB。编码器三组 Top-512 = 0.44 MB。每步卸载 5.16 MB/序列。",
        "",
        "## 3. 三种放置",
        "",
        "本地 HBM：主 KV 和索引都在 GPU。`store > 房间` 的批量不要。",
        f"主机 DDR：溢出的主 KV 每卡不超过 {DDR_CAP/1e9:.0f} GB。每步 SWAP = 溢出比例 × 5.16 MB × n / 8 / {HOST/1e9:.0f} GB/s。",
        f"交换 HBM：主 KV 整份进 DDR 池。候选池放 30×{SWITCH_HBM/1e9:.0f} GB，每步按 {D2D/1e12:.2f} TB/s 读回。索引仍要放进 GPU 房间。",
        "",
        "```",
        "TPOT = T_SWAP + max(T_HBM, T_compute) + T_AR + T_MoE",
        "TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE",
        f"T_pull = n × (0.995×S×890) / (8 × {PREFIX:.3e})",
        "Prefill 的 AR 和 MoE 是 20 层。Decode 是 40 层。",
        "```",
        "",
        "## 4. 本地 HBM",
        "",
        f"冷请求最大输入 {data['cold_s']:,}，TTFT {data['cold']['t']:.4f} 秒。4M 冷请求 {data['cold4']['t']:.4f} 秒。",
        "",
        "| 输入 | 10秒批 | Prefill TPS | 10毫秒批 | 10毫秒 TPS | 30毫秒批 | 30毫秒 TPS |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        lines.append(
            f"| {fmt_len(row['S'])} | {row['b256']} | {row['b256']*row['S']/row['p256']['t']:.3e} | "
            f"{row['hbm10']} | {tps_d(row, 'hbm', '10'):.3e} | {row['hbm30']} | {tps_d(row, 'hbm', '30'):.3e} |"
        )
    lines += [
        "",
        "## 5. 三种 Decode",
        "",
        "| 输入 | HBM 10 | 主机 10 | 交换 10 | HBM 30 | 主机 30 | 交换 30 | 主机30提升 | 交换30提升 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        lines.append(
            f"| {fmt_len(row['S'])} | {row['hbm10']} | {row['host10']} | {row['sw10']} | "
            f"{row['hbm30']} | {row['host30']} | {row['sw30']} | "
            f"{signed_pct(tps_d(row, 'host', '30'), tps_d(row, 'hbm', '30'))} | "
            f"{signed_pct(tps_d(row, 'sw', '30'), tps_d(row, 'hbm', '30'))} |"
        )
    lines += [
        "",
        f"64K、30 毫秒：本地 {r64['hbm30']}，交换 {r64['sw30']}。4M、30 毫秒：本地 {r4['hbm30']}，主机 {r4['host30']}，交换 {r4['sw30']}。",
        "",
        "## 6. Prefill 24 卡",
        "",
        "| 输入 | 24卡批 | 24卡TPS | 256卡TPS | 拉KV占比 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        t24 = row["b24"] * row["S"] / row["p24"]["t"]
        t256 = row["b256"] * row["S"] / row["p256"]["t"]
        lines.append(
            f"| {fmt_len(row['S'])} | {row['b24']} | {t24:.6e} | {t256:.6e} | "
            f"{row['p24']['pull'] / row['p24']['t'] * 100:.1f}% |"
        )
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def audit(prs):
    wide, low = Inches(13.333), Inches(7.50)
    bad = []
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.left + shape.width > wide + Emu(20000) or shape.top + shape.height > low + Emu(20000):
                bad.append((i, shape.shape_type, shape.left, shape.top, shape.width, shape.height))
            if shape.top < 0 or shape.left < 0:
                bad.append((i, "neg", shape.left, shape.top, shape.width, shape.height))
    return bad


def main():
    data = collect()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "V4.1 外扩 20T：三种 KV 卸载"
    blank = prs.slide_layouts[6]
    slide_conclusion(prs, blank, data)
    slide_model(prs, blank)
    slide_kv(prs, blank)
    slide_hardware(prs, blank)
    slide_parallel(prs, blank, data)
    slide_tps(prs, blank, data)
    slide_prefill(prs, blank, data)
    slide_pf_tps(prs, blank, data)
    slide_pf_time(prs, blank, data)
    slide_pf_hbm(prs, blank, data)
    slide_cases(prs, blank, data)
    slide_split(prs, blank, data)
    slide_pies(prs, blank, data)
    out = "/agent/repos/ucl-mpcomm/docs/deepseek-v41-20t-n2-slo.pptx"
    prs.save(out)
    write_md("/agent/repos/ucl-mpcomm/docs/deepseek-v41-20t-n2-slo.md", data)
    bad = audit(prs)
    print(out)
    print("slides", len(prs.slides), "overflow", len(bad))
    for item in bad[:20]:
        print(item)
    r4, r64 = by_len(data, 4194304), by_len(data, 65536)
    print("cold", data["cold_s"], round(data["cold"]["t"], 3), "cold4", round(data["cold4"]["t"], 3))
    print("64k hbm/host/sw 30", r64["hbm30"], r64["host30"], r64["sw30"])
    print("4m hbm/host/sw 10", r4["hbm10"], r4["host10"], r4["sw10"])
    print("4m hbm/host/sw 30", r4["hbm30"], r4["host30"], r4["sw30"])
    print("4m 30 t", ms(r4["dhbm30"]["t"]), ms(r4["dhost30"]["t"]), ms(r4["dsw30"]["t"]))


if __name__ == "__main__":
    main()
