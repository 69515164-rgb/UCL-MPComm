#!/usr/bin/env python3
"""Write the step-by-step N+2 calculation and a Word file that downloads.

The short result sheet stays in deepseek-20t-n2-slo.md. This script
expands the same formulas, with the arithmetic filled in, and writes
both a Markdown source and a .docx. GitHub serves the docx as a file
download; a raw Markdown URL opens as text in the browser.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))
import build_deepseek_20t_slo_ppt as m  # noqa: E402

MD_PATH = ROOT / "docs" / "deepseek-20t-n2-slo-calc.md"
DOCX_PATH = ROOT / "docs" / "deepseek-20t-n2-slo-calc.docx"
ACTIVE = 4.9e10


def comma(x, nd=None):
    if nd is None:
        if abs(x - round(x)) < 1e-6:
            return f"{int(round(x)):,}"
        nd = 4 if abs(x) >= 1 else 6
    return f"{x:,.{nd}f}"


def sec(x):
    return f"{x:.6f} 秒 = {x * 1e3:.3f} 毫秒"


def gb(x):
    return f"{x / 1e9:,.4f} GB"


def tbps(x):
    return f"{x / 1e12:.4f} TB/s"


def num(x):
    ax = abs(float(x))
    if ax != 0 and (ax >= 1e7 or ax < 1e-3):
        return f"{x:.6e}"
    return comma(x)


def moe_detail(tokens):
    tokens = max(float(tokens), 0.0)
    mean = tokens * m.TOPK / m.N
    spread = math.sqrt(max(mean * (1 - 1 / m.N), 0.0))
    hot = min(tokens * m.TOPK, mean + 2 * spread)
    frac = 1 - math.exp(-m.TOPK * tokens / m.E) if tokens > 0 else 0.0
    experts = m.E / m.N
    std = math.sqrt(max(experts * frac * (1 - frac), 0.0))
    e_hot = min(experts, experts * frac + 2 * std) if frac > 0 else 0.0
    tpe = hot / e_hot if e_hot else 0.0
    routed_tile = math.ceil(tpe / 16) * 16 if e_hot else 0.0
    routed_rows = e_hot * routed_tile if e_hot else 0.0
    shared_local = max(1, math.ceil(tokens / m.N))
    shared_rows = math.ceil(shared_local / 16) * 16
    weight_bytes = e_hot * m.W_ONE * 0.5 + m.SHARED
    gemm_flops = (routed_rows + shared_rows) * 6 * m.H * m.DFF * m.L
    dispatch_bytes = hot * m.H * 1
    combine_bytes = hot * m.H * 2
    t_w = weight_bytes / m.HBM_BW
    t_g = gemm_flops / m.PEAK
    t_d = m.L * (m.COLL + dispatch_bytes / m.D2D)
    t_c = m.L * (m.COLL + combine_bytes / m.D2D)
    t = t_d + max(t_w, t_g) + t_c
    ref = m.expert(tokens)
    if abs(ref["t"] - t) > 1e-9:
        raise AssertionError((ref["t"], t))
    return {
        "tokens": tokens,
        "mean": mean,
        "spread": spread,
        "hot": hot,
        "frac": frac,
        "experts": experts,
        "std": std,
        "e_hot": e_hot,
        "tpe": tpe,
        "routed_rows": routed_rows,
        "shared_rows": shared_rows,
        "weight_bytes": weight_bytes,
        "gemm_flops": gemm_flops,
        "dispatch_bytes": dispatch_bytes,
        "combine_bytes": combine_bytes,
        "tw": t_w,
        "tg": t_g,
        "td": t_d,
        "tc": t_c,
        "t": t,
    }


def prefill_detail(bs, s, hit=m.HIT, prefix=m.PREFIX_25):
    n = math.ceil(bs / m.DP)
    p, q = hit * s, (1 - hit) * s
    rows = n * q
    context = q * p + q * (q + 1) / 2.0
    idx = m.N_CSA * 4096 * context
    hca = m.N_HCA * 2048 * context
    core = m.N_CSA * 262144 * (1024 + 128) * q
    proj = m.PROJ * q
    flops = idx + hca + core + proj
    tile = math.ceil(rows / 16.0) * 16 if rows > 0 else 16
    util = m.align(rows)
    t_compute = n * flops / (m.TP * m.PEAK * util)
    prefix_bytes = p * m.BPT + m.L * min(p, 128) * 576
    t_pull = n * prefix_bytes / (m.TP * prefix) if prefix else 0.0
    seq_bytes = m.store_seq(s)
    hbm_bytes = m.ATTN / m.TP + n * (seq_bytes + q * m.BPT) / m.TP
    t_hbm = hbm_bytes / m.HBM_BW
    ar_bytes = 2 * (m.TP - 1) / m.TP * rows * m.H * 2
    t_ar = m.L * (m.COLL + ar_bytes / m.P2P)
    moe = moe_detail(bs * q)
    body = t_pull + max(t_hbm, t_compute) + t_ar + moe["t"]
    t_pd = n * seq_bytes / (m.TP * m.PARAM)
    tail = max(0.0, t_pd - body * (m.L - 1) / m.L)
    total = body + tail
    ref = m.prefill(bs, s, hit=hit, prefix=prefix)
    if abs(ref["t"] - total) > 1e-6:
        raise AssertionError((ref["t"], total, s, bs))
    return {
        "bs": bs,
        "s": s,
        "hit": hit,
        "prefix": prefix,
        "n": n,
        "p": p,
        "q": q,
        "rows": rows,
        "tile": tile,
        "util": util,
        "context": context,
        "idx": idx,
        "hca": hca,
        "core": core,
        "proj": proj,
        "flops": flops,
        "prefix_bytes": prefix_bytes,
        "seq_bytes": seq_bytes,
        "hbm_bytes": hbm_bytes,
        "ar_bytes": ar_bytes,
        "pull": t_pull,
        "compute": t_compute,
        "hbm": t_hbm,
        "ar": t_ar,
        "moe": moe,
        "pd": t_pd,
        "tail": tail,
        "body": body,
        "t": total,
    }


def decode_detail(bs, s, pool):
    n = math.ceil(bs / m.DP)
    sel = min(1024.0, s / 4.0)
    indexer = m.N_CSA * (s / 4.0) * 64
    hca_b = m.N_HCA * (s / 128.0) * 576
    chosen = m.N_CSA * sel * 576
    read_seq = indexer + hca_b + chosen + m.FIXED
    read_gpu = n * read_seq / m.TP
    store = bs * m.store_seq(s)
    spill = max(store - m.ROOM, 0.0) / store if store else 0.0
    t_swap = read_gpu * spill / pool
    t_hbm = (read_gpu + m.ATTN / m.TP) / m.HBM_BW
    score = m.N_CSA * 4096 * s + m.N_HCA * 2048 * s + m.N_CSA * 262144 * (sel + 128)
    flops = score + m.PROJ
    util = m.align(n)
    tile = math.ceil(n / 16.0) * 16 if n > 0 else 16
    t_ca = n * flops / (m.TP * m.PEAK * util)
    ar_bytes = 2 * (m.TP - 1) / m.TP * n * m.H * 2
    t_ar = m.L * (m.COLL + ar_bytes / m.P2P)
    moe = moe_detail(bs)
    total = t_swap + max(t_ca, t_hbm) + t_ar + moe["t"]
    ref = m.decode(bs, s, pool)
    if abs(ref["t"] - total) > 1e-6:
        raise AssertionError((ref["t"], total, s, bs))
    per_gpu_ddr = spill * store / m.N
    return {
        "bs": bs,
        "s": s,
        "pool": pool,
        "n": n,
        "sel": sel,
        "indexer": indexer,
        "hca_b": hca_b,
        "chosen": chosen,
        "read_seq": read_seq,
        "read_gpu": read_gpu,
        "store": store,
        "spill": spill,
        "ddr": per_gpu_ddr,
        "swap": t_swap,
        "hbm": t_hbm,
        "score": score,
        "flops": flops,
        "util": util,
        "tile": tile,
        "ca": t_ca,
        "ar_bytes": ar_bytes,
        "ar": t_ar,
        "moe": moe,
        "t": total,
    }


def tps_prefill(bs, s, t):
    return bs * s / t


def tps_decode(bs, t):
    return bs / t


def md_table(headers, rows):
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


def prefill_block(title, d):
    z = d
    moe = z["moe"]
    lines = [
        f"### {title}",
        "",
        f"输入 S = {comma(z['s'])}，全局批 = {comma(z['bs'])}，拉 KV 带宽 = {gb(z['prefix'])}/s，命中 = {z['hit']}.",
        "",
        "本地批和 token 拆分：",
        "",
        "```text",
        f"n = ceil({comma(z['bs'])} / {m.DP}) = {comma(z['n'])}",
        f"p = {z['hit']} × {comma(z['s'])} = {comma(z['p'])}",
        f"q = {1 - z['hit']:.3f} × {comma(z['s'])} = {comma(z['q'])}",
        f"rows = n × q = {comma(z['rows'])}",
        f"16 行对齐后的行数 = {comma(z['tile'])}",
        f"align = rows / 对齐行数 = {z['util']:.6f}",
        "```",
        "",
        "一条序列要拉的 prefix KV：",
        "",
        "```text",
        f"p × 4939.5 = {comma(z['p'])} × 4939.5 = {comma(z['p'] * m.BPT)}",
        f"滑窗 = 61 × min(p, 128) × 576 = 61 × {comma(min(z['p'], 128))} × 576 = {comma(m.L * min(z['p'], 128) * 576)}",
        f"一条序列 = {comma(z['prefix_bytes'])} 字节 = {gb(z['prefix_bytes'])}",
        f"T_pull = {comma(z['n'])} × {comma(z['prefix_bytes'])} / (8 × {num(z['prefix'])})",
        f"       = {sec(z['pull'])}",
        "```",
        "",
        "未命中段的注意力计算。context 是未命中 token 要看的历史对：先看已命中的 p，再看未命中段内部的三角。",
        "",
        "```text",
        f"context = q×p + q×(q+1)/2 = {comma(z['context'])}",
        f"CSA 索引 = 30 × 4096 × context = {num(z['idx'])}",
        f"HCA      = 31 × 2048 × context = {num(z['hca'])}",
        f"CSA 核心 = 30 × 262144 × (1024+128) × q = {num(z['core'])}",
        f"投影     = 1.935e10 × 2 × q = {num(z['proj'])}",
        f"单条序列 FLOPs = {num(z['flops'])}",
        f"T_compute = n × FLOPs / (8 × 3.360e16 × align)",
        f"          = {comma(z['n'])} × {num(z['flops'])} / (8 × {num(m.PEAK)} × {z['util']:.6f})",
        f"          = {sec(z['compute'])}",
        "```",
        "",
        "HBM 上这一步要碰的字节是本卡注意力权重，加上本地 n 条序列的整段 KV 和未命中段新写的 KV，再除以 TP。",
        "",
        "```text",
        f"一条序列存量 = {comma(z['s'])} × 4939.5 + 4497408 = {comma(z['seq_bytes'])} 字节 = {gb(z['seq_bytes'])}",
        f"HBM 字节 = 1.935e10 / 8 + {comma(z['n'])} × ({comma(z['seq_bytes'])} + {comma(z['q'])} × 4939.5) / 8",
        f"        = {comma(z['hbm_bytes'])} 字节 = {gb(z['hbm_bytes'])}",
        f"T_HBM = {gb(z['hbm_bytes'])} / 26.40 TB/s = {sec(z['hbm'])}",
        f"max(T_HBM, T_compute) = {sec(max(z['hbm'], z['compute']))}",
        "```",
        "",
        "AllReduce 走机内 7 条 P2P。每层字节是环上两趟，乘 (TP-1)/TP，隐藏 7168，BF16 两字节。每层另加 5 微秒。",
        "",
        "```text",
        f"每层字节 = 2 × 7/8 × {comma(z['rows'])} × 7168 × 2 = {comma(z['ar_bytes'])}",
        f"T_AR = 61 × (5e-6 + {comma(z['ar_bytes'])} / 1.120e12) = {sec(z['ar'])}",
        "```",
        "",
        "MoE 的 token 数是全局批乘未命中长度。热 token 在均值上加两个标准差，并且不超过全部 token×6。热专家用 1−exp(−6×token/E) 估计有 token 落到的比例，再加两个标准差。GEMM 行数按 16 对齐。6×隐藏×中间维是 3 个矩阵各算 2 次乘加。",
        "",
        "```text",
        f"MoE token = {comma(z['bs'])} × {comma(z['q'])} = {comma(moe['tokens'])}",
        f"均值 = token × 6 / 256 = {comma(moe['mean'])}",
        f"热 token = min(token×6, 均值 + 2×标准差) = {comma(moe['hot'])}",
        f"有流量的专家比例 = 1 − exp(−6 × token / 4951) = {moe['frac']:.6f}",
        f"每卡专家槽 = 4951 / 256 = {comma(moe['experts'])}",
        f"热专家 = {comma(moe['e_hot'])}",
        f"权重字节 = 热专家 × 4,029,677,568 × 0.5 + 共享专家 = {comma(moe['weight_bytes'])}",
        f"T_weight = {sec(moe['tw'])}",
        f"GEMM FLOPs = (路由对齐行 + 共享对齐行) × 6 × 7168 × 3072 × 61 = {num(moe['gemm_flops'])}",
        f"T_gemm = {sec(moe['tg'])}",
        f"max(T_weight, T_gemm) = {sec(max(moe['tw'], moe['tg']))}",
        f"dispatch 字节/层 = 热 token × 7168 × 1 = {comma(moe['dispatch_bytes'])}",
        f"combine  字节/层 = 热 token × 7168 × 2 = {comma(moe['combine_bytes'])}",
        f"T_dispatch = 61 × (5e-6 + dispatch / 4.80 TB/s) = {sec(moe['td'])}",
        f"T_combine  = 61 × (5e-6 + combine  / 4.80 TB/s) = {sec(moe['tc'])}",
        f"T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine = {sec(moe['t'])}",
        "```",
        "",
        "P→D 把整段 KV 送到 Decode。它和前面 60/61 层的主体重叠，只把超出的部分留在尾上。",
        "",
        "```text",
        f"T_PD = {comma(z['n'])} × {comma(z['seq_bytes'])} / (8 × 80 GB/s) = {sec(z['pd'])}",
        f"主体 × 60/61 = {sec(z['body'] * 60 / 61)}",
        f"T_tail = max(0, T_PD − 主体×60/61) = {sec(z['tail'])}",
        "```",
        "",
        "加总：",
        "",
        "```text",
        f"TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail",
        f"     = {z['pull']:.6f} + {max(z['hbm'], z['compute']):.6f} + {z['ar']:.6f} + {moe['t']:.6f} + {z['tail']:.6f}",
        f"     = {sec(z['t'])}",
        f"系统 Prefill TPS = {comma(z['bs'])} × {comma(z['s'])} / {z['t']:.6f} = {num(tps_prefill(z['bs'], z['s'], z['t']))} token/s",
        "```",
        "",
    ]
    return lines


def decode_block(title, d):
    z = d
    moe = z["moe"]
    lines = [
        f"### {title}",
        "",
        f"输入 S = {comma(z['s'])}，全局批 = {comma(z['bs'])}，换入带宽 = {gb(z['pool'])}/s。",
        "",
        "一步 Decode 不读整段 KV。CSA 读压缩索引、最多 1024 条被选中的 latent，再加 128 token 的滑窗。HCA 按压缩比 128 读 latent。",
        "",
        "```text",
        f"选中条数 = min(1024, S/4) = {comma(z['sel'])}",
        f"CSA 索引字节 = 30 × (S/4) × 64 = {comma(z['indexer'])}",
        f"HCA latent   = 31 × (S/128) × 576 = {comma(z['hca_b'])}",
        f"CSA 选中     = 30 × {comma(z['sel'])} × 576 = {comma(z['chosen'])}",
        f"滑窗         = 4,497,408",
        f"一条序列稀疏读 = {comma(z['read_seq'])} 字节 = {gb(z['read_seq'])}",
        f"本卡稀疏读 = n × 一条 / 8 = {comma(z['n'])} × {comma(z['read_seq'])} / 8 = {comma(z['read_gpu'])} 字节",
        "```",
        "",
        "存量超过副本 KV 房间的比例记为溢出。换入只为这一比例付带宽。每卡落到主机 DDR 或 DDR 池的字节是溢出比例乘整段存量再除以 256。",
        "",
        "```text",
        f"整段存量 = {comma(z['bs'])} × {comma(m.store_seq(z['s']))} = {comma(z['store'])} 字节 = {tb_bytes(z['store'])}",
        f"副本 KV 房间 = {comma(m.ROOM)} 字节 = {tb_bytes(m.ROOM)}",
        f"溢出比例 = max(存量 − 房间, 0) / 存量 = {z['spill'] * 100:.4f}%",
        f"每卡溢出 = {gb(z['ddr'])}",
        f"T_SWAP = 本卡稀疏读 × 溢出比例 / 换入带宽",
        f"       = {comma(z['read_gpu'])} × {z['spill']:.6f} / {num(z['pool'])}",
        f"       = {sec(z['swap'])}",
        "```",
        "",
        "注意力 FLOPs 用整段 S，不再用 Prefill 的未命中 context。核心项用选中条数加滑窗。",
        "",
        "```text",
        f"score = 30×4096×S + 31×2048×S + 30×262144×(选中+128) = {num(z['score'])}",
        f"再加投影 1.935e10×2 = {num(z['flops'])}",
        f"align(n) = {z['n']} / {comma(z['tile'])} = {z['util']:.6f}",
        f"T_compute = n × FLOPs / (8 × 3.360e16 × align) = {sec(z['ca'])}",
        f"T_HBM = (本卡稀疏读 + 注意力权重/8) / 26.40 TB/s = {sec(z['hbm'])}",
        f"max(T_HBM, T_compute) = {sec(max(z['hbm'], z['ca']))}",
        "```",
        "",
        "HBM 时间按整段稀疏读计，不把已经算进 T_SWAP 的那一比例扣掉。换入加在 max 的外面。",
        "",
        "```text",
        f"每层 AllReduce 字节 = 2 × 7/8 × {comma(z['n'])} × 7168 × 2 = {comma(z['ar_bytes'])}",
        f"T_AR = {sec(z['ar'])}",
        f"MoE token = 全局批 = {comma(moe['tokens'])}",
        f"热 token = {comma(moe['hot'])}，热专家 = {comma(moe['e_hot'])}",
        f"T_weight = {sec(moe['tw'])}，T_gemm = {sec(moe['tg'])}",
        f"T_dispatch = {sec(moe['td'])}，T_combine = {sec(moe['tc'])}",
        f"T_MoE = {sec(moe['t'])}",
        "```",
        "",
        "```text",
        f"TPOT = T_SWAP + max(T_HBM, T_compute) + T_AR + T_MoE",
        f"     = {z['swap']:.6f} + {max(z['hbm'], z['ca']):.6f} + {z['ar']:.6f} + {moe['t']:.6f}",
        f"     = {sec(z['t'])}",
        f"系统 Decode TPS = {comma(z['bs'])} / {z['t']:.6f} = {num(tps_decode(z['bs'], z['t']))} token/s",
        "```",
        "",
    ]
    return lines


def tb_bytes(x):
    return f"{x / 1e12:.4f} TB"


def build_lines():
    data = m.collect()
    by = {row["S"]: row for row in data["rows"]}
    r64 = by[65536]
    r4 = by[4194304]
    d64 = prefill_detail(r64["b25"], 65536)
    d64_next = prefill_detail(r64["b25"] + 1, 65536)
    d4 = prefill_detail(r4["b25"], 4194304)
    d4_new = prefill_detail(r4["b100"], 4194304, prefix=m.PREFIX_100)
    d64_new = prefill_detail(r64["b100"], 65536, prefix=m.PREFIX_100)
    cold_s = data["cold_s"]
    cold = prefill_detail(1, cold_s, hit=0.0)
    cold_next = prefill_detail(1, cold_s + 1, hit=0.0)
    cold4 = prefill_detail(1, 4194304, hit=0.0)
    dec4 = decode_detail(r4["b30"], 4194304, m.HOST)
    dec4_next = decode_detail(r4["b30"] + 1, 4194304, m.HOST)
    dec4_pool = decode_detail(r4["p30"], 4194304, m.POOL)
    dec64_10 = decode_detail(r64["b10"], 65536, m.HOST)

    w_step1 = 3 * m.H
    w_step2 = w_step1 * m.DFF
    active_routed = 6 * m.W_ONE
    active_shared = m.W_ONE
    active_rest = ACTIVE - 7 * m.W_ONE
    exact = (2e13 - m.OTHER) / m.W_ONE
    routed_gpu = m.ROUTED / m.N
    shared_gpu = m.SHARED
    attn_gpu = m.ATTN / m.TP
    room_gpu = m.HBM_CAP - routed_gpu - shared_gpu - attn_gpu - m.RESERVE
    ep16 = m.ROUTED / 16
    ep16_room = m.HBM_CAP - ep16 - shared_gpu - attn_gpu - m.RESERVE

    lines = []
    a = lines.append
    a("# N+2：20T DeepSeek SLO 详细计算过程")
    a("")
    a("这份是演算稿。结果摘要在 `deepseek-20t-n2-slo.md`，幻灯片在 `deepseek-20t-n2-slo.pptx`。三份用的是同一套式子。")
    a("")
    a("单位按十进制：1 GB = 10^9 字节，1 TB = 10^12 字节。HBM、DDR5 的标称已经是字节每秒。H2D、D2D、参数面、机内 P2P、总线 DDR 池的标称是比特每秒，先除以 8 再乘效率。一份副本是 256 卡。单条请求不跨副本，所以副本个数不改变单条 TTFT 或 TPOT。")
    a("")
    a("要满足的三条是：命中 99.5% 时 TTFT ≤ 10 秒，TPOT ≤ 10 毫秒，TPOT ≤ 30 毫秒。输入取 64K、128K、256K、512K、1M、2M、4M，都是 1024 的幂。输出 512 token 只用来把 Prefill 和 Decode 的请求/秒对齐。")
    a("")
    a("## 1. 先看判定")
    a("")
    a(f"冷请求、批为 1、命中为 0 时，最大输入是 {comma(cold_s)}，TTFT = {sec(cold['t'])}。再加 1 个 token 变成 {sec(cold_next['t'])}。4M 冷请求是 {sec(cold4['t'])}，超过 10 秒。")
    a("")
    a("99.5% 命中下，下面每一档的摸高批都同时落在 10 秒、10 毫秒、30 毫秒里面。系统 Prefill TPS 用完整输入 token，系统 Decode TPS 用这一步新生成的 token。")
    a("")
    summary = []
    for s in m.LENGTHS:
        row = by[s]
        summary.append([
            m.fmt_len(s),
            comma(row["b25"]),
            f"{tps_prefill(row['b25'], s, row['p25']['t']):.6e}",
            comma(row["b10"]),
            f"{tps_decode(row['b10'], row['d10']['t']):.6e}",
            comma(row["b30"]),
            f"{tps_decode(row['b30'], row['d30']['t']):.6e}",
        ])
    lines += md_table(
        ["输入", "10秒批", "Prefill TPS", "10毫秒批", "10毫秒 TPS", "30毫秒批", "30毫秒 TPS"],
        summary,
    )
    a("")
    a("## 2. 从 1.6T 推到 20T")
    a("")
    a("V4-Pro 论文是 1.6×10^12 参数、384 个路由专家、61 层、隐藏 7168、专家中间维 3072、每 token 激活 6 个路由专家、激活参数 4.9×10^10。20T 没有发布。外推只改路由专家个数，其余骨架不动。")
    a("")
    a("一个路由专家是 gate、up、down 三个矩阵，61 层各一份。")
    a("")
    a("```text")
    a(f"3 × 7168 = {comma(w_step1)}")
    a(f"{comma(w_step1)} × 3072 = {comma(w_step2)}")
    a(f"{comma(w_step2)} × 61 = {comma(m.W_ONE)}")
    a("```")
    a("")
    a("1.6T 去掉 384 个路由专家，剩下共享专家、注意力、词表、mHC、MTP。")
    a("")
    a("```text")
    a(f"384 × {comma(m.W_ONE)} = {comma(384 * m.W_ONE)}")
    a(f"其余 = 1,600,000,000,000 − {comma(384 * m.W_ONE)} = {comma(m.OTHER)}")
    a("```")
    a("")
    a("把总参数对齐到 2×10^13，专家数向上取整。")
    a("")
    a("```text")
    a(f"(2e13 − {comma(m.OTHER)}) / {comma(m.W_ONE)} = {exact:.6f}")
    a(f"E = ceil(这个数) = {m.E}")
    a(f"总参数 = {m.E} × {comma(m.W_ONE)} + {comma(m.OTHER)} = {comma(m.TOTAL_PARAMS)}")
    a(f"比 2×10^13 多 {comma(m.TOTAL_PARAMS - 2e13)}")
    a("```")
    a("")
    a("激活参数不随专家个数增加。6 个路由专家加 1 个共享专家，剩下的差额是每 token 都要算的注意力等项，用来对上论文的 4.9×10^10。")
    a("")
    a("```text")
    a(f"6 × {comma(m.W_ONE)} = {comma(active_routed)}")
    a(f"共享专家 = {comma(active_shared)}")
    a(f"其余激活 = 4.9e10 − 7 × {comma(m.W_ONE)} = {comma(active_rest)}")
    a(f"激活参数 = {comma(active_routed)} + {comma(active_shared)} + {comma(active_rest)} = {comma(ACTIVE)}")
    a(f"1.6T 激活比 = 4.9e10 / 1.6e12 = {ACTIVE / 1.6e12 * 100:.2f}%")
    a(f"20T 激活比 = 4.9e10 / {comma(m.TOTAL_PARAMS)} = {ACTIVE / m.TOTAL_PARAMS * 100:.3f}%")
    a("```")
    a("")
    a("路由专家用 FP4，一个参数 0.5 字节。共享专家和注意力用 FP8，一个参数 1 字节。")
    a("")
    a("```text")
    a(f"FP4 专家表 = {m.E} × {comma(m.W_ONE)} × 0.5 = {comma(m.ROUTED)} 字节 = {m.ROUTED / 1e12:.6f} TB")
    a("```")
    a("")
    a("## 3. 一个 token 的 KV")
    a("")
    a("61 层里 30 层 CSA、31 层 HCA。CSA 压缩比 4，另有 64 字节索引。HCA 压缩比 128。K/V 已经合成 576 字节的 latent，不再乘 2。滑窗 128，输入不短于 128 时，滑窗字节是常数。")
    a("")
    a("```text")
    a("CSA 每 token = 576/4 + 64/4 = 144 + 16 = 160 字节")
    a("30 层 CSA = 30 × 160 = 4,800 字节")
    a("HCA 每 token = 576/128 = 4.5 字节")
    a("31 层 HCA = 31 × 4.5 = 139.5 字节")
    a("每 token = 4,800 + 139.5 = 4,939.5 字节")
    a("滑窗 = 61 × 128 × 576 = 4,497,408 字节")
    a("一条序列存量 K(S) = 4939.5 × S + 4,497,408")
    a("```")
    a("")
    kv_rows = []
    for s in m.LENGTHS:
        k = m.store_seq(s)
        kv_rows.append([m.fmt_len(s), comma(s), comma(k), gb(k)])
    lines += md_table(["输入", "token", "一条序列字节", "一条序列"], kv_rows)
    a("")
    a("Decode 一步的稀疏读比存量小。压缩历史全读索引或 HCA latent，CSA latent 只读选中的那部分。")
    a("")
    a("```text")
    a("选中条数 = min(1024, S/4)")
    a("稀疏读 = 30×(S/4)×64 + 31×(S/128)×576 + 30×选中×576 + 4,497,408")
    a("```")
    a("")
    read_rows = []
    for s in m.LENGTHS:
        sel = min(1024.0, s / 4.0)
        read = m.n_csa_read(s)
        read_rows.append([m.fmt_len(s), comma(sel), comma(read), gb(read), f"{read / m.store_seq(s) * 100:.2f}%"])
    lines += md_table(["输入", "选中条数", "一条稀疏读字节", "一条稀疏读", "占存量"], read_rows)
    a("")
    a("## 4. 带宽怎么换成计时用的数")
    a("")
    a("DDR5 的 2 TB/s 是每台 8 卡机器的字节带宽，用来替换原来的 1288.8 GB/s，容量仍是每机 768 GB。它已经是字节，不再除以 8。")
    a("")
    bw_rows = [
        ["FP4 算力", "48 P = 4.8×10^16 FLOP/s", "字节口径，不除 8", "×70%", f"{m.PEAK:.4e} FLOP/s = 33.60 P"],
        ["HBM", "33 TB/s，640 GB", "字节口径", "×80%", f"{m.HBM_BW:.4e} B/s = 26.40 TB/s"],
        ["H2D", "每卡单向 1.6 Tb/s", "1.6e12/8 = 2.00e11 B/s", "×80%", f"{m.H2D:.4e} B/s = 160 GB/s"],
        ["DDR5", "每机 2 TB/s，768 GB", "2e12 B/s 已是字节", "×80% 后 /8 卡", f"{m.DDR_SHARE:.4e} B/s = 200 GB/s，每卡 {m.DDR_CAP/1e9:.0f} GB"],
        ["H2D 换入", "H2D 与每卡 DDR 取更小", "min(160, 200) GB/s", "已含效率", f"{m.HOST:.4e} B/s = 160 GB/s"],
        ["D2D", "每卡单向 48 Tb/s", "48e12/8 = 6.00e12 B/s", "×80%", f"{m.D2D:.4e} B/s = 4.80 TB/s"],
        ["机内 P2P", "两卡之间 1.6 Tb/s", "1.6e12/8 = 200 GB/s 一条", "7 条 ×80%", f"{m.P2P:.4e} B/s = 1.12 TB/s"],
        ["参数面物理", "每卡 800 Gb/s", "800e9/8 = 1.00e11 B/s", "拉 KV 不再乘 80%", "100 GB/s"],
        ["P→D", "同一条参数面", "100 GB/s", "×80%", "80 GB/s"],
        ["拉 KV 基线", "物理的 25%", "100 × 0.25", "不叠乘 80%", "25 GB/s"],
        ["拉 KV NEW", "物理的 100%", "100 GB/s", "不叠乘 80%", "100 GB/s"],
        ["总线 DDR 池", "每卡 51.2 Tb/s，容量不限", "51.2e12/8 = 6.40e12 B/s", "×80%", f"{m.POOL:.4e} B/s = 5.12 TB/s"],
    ]
    lines += md_table(["项目", "标称", "换成字节", "效率", "计时值"], bw_rows)
    a("")
    a("AllReduce 用 1.12 TB/s，因为一卡到另外 7 卡的 P2P 可以同时用。7 × 200 GB/s = 1.40 TB/s，再乘 80% 得 1.12 TB/s。D2D 口是 6.00 TB/s，高于这 1.40 TB/s，所以不把 AllReduce 再截到交换平面上。")
    a("")
    a("集合通信每层另加 5 微秒，61 层一共 0.305 毫秒的固定启动。这项加在对应的 AllReduce、dispatch、combine 里面，不和传输重叠。")
    a("")
    a("## 5. 每卡放什么，KV 还剩多少")
    a("")
    a("注意力 TP=8，一组 8 卡放一份注意力。MoE EP=256，专家摊满整个超节点。DP = 256/8 = 32。")
    a("")
    a("```text")
    a(f"每卡路由专家 = {comma(m.ROUTED)} / 256 = {comma(routed_gpu)} 字节 = {gb(routed_gpu)}")
    a(f"每卡专家个数 = 4951 / 256 = {m.E / m.N:.4f}")
    a(f"每卡共享专家 = {comma(shared_gpu)} 字节 = {gb(shared_gpu)}")
    a(f"每卡注意力 = 1.935e10 / 8 = {comma(attn_gpu)} 字节 = {gb(attn_gpu)}")
    a(f"预留 = {comma(m.RESERVE)} 字节 = 6.0000 GB")
    a(f"四项合计 = {gb(routed_gpu + shared_gpu + attn_gpu + m.RESERVE)}")
    a(f"每卡 KV 房间 = 640 GB − 合计 = {gb(room_gpu)}")
    a(f"副本 KV 房间 = 256 × {gb(room_gpu)} = {tb_bytes(m.ROOM)}")
    a("```")
    a("")
    a("如果 EP 改成 16，路由专家只摊到 16 卡。")
    a("")
    a("```text")
    a(f"每卡路由专家 = {comma(m.ROUTED)} / 16 = {comma(ep16)} 字节 = {gb(ep16)}")
    a(f"再加共享、注意力、预留后，KV 房间 = {gb(ep16_room)}")
    a(f"4M 一条序列存量 = {gb(m.store_seq(4194304))}")
    a("```")
    a("")
    a(f"EP=16 时每卡 KV 房间是 {gb(ep16_room)}，一条 4M 序列要 {gb(m.store_seq(4194304))}。房间装不下这条序列，所以这份副本用 EP=256。EP 走 D2D 交换平面，不进参数面。")
    a("")
    a("## 6. Prefill 的式子")
    a("")
    a("全局批先按 DP=32 得到本地批 n。拉 KV 和注意力再按 TP=8 切开。n/8 = 全局批/256。")
    a("")
    a("```text")
    a("TTFT = T_pull + max(T_HBM, T_compute) + T_AR + T_MoE + T_tail")
    a("T_pull = n × (p×4939.5 + 61×min(p,128)×576) / (8 × 拉KV带宽)")
    a("T_compute = n × (CSA索引 + HCA + CSA核心 + 投影) / (8 × 33.60 P × align(rows))")
    a("rows = n × q")
    a("align(rows) = rows / (ceil(rows/16) × 16)")
    a("T_AR = 61 × (5e-6 + 2×7/8 × rows × 7168 × 2 / 1.12 TB/s)")
    a("T_MoE = T_dispatch + max(T_weight, T_gemm) + T_combine")
    a("T_tail = max(0, T_PD − 主体×60/61)")
    a("T_PD = n × K(S) / (8 × 80 GB/s)")
    a("```")
    a("")
    a("p = 0.995×S，q = 0.005×S。系统 Prefill TPS = 全局批 × S / 实际 TTFT。分子用完整输入，分母用摸高批的实际时间，这个时间可以略小于 10 秒。")
    a("")
    a("批量从 1 开始倍增，再二分。返回的批满足 TTFT ≤ 10 秒，批加 1 则超过 10 秒。")
    a("")
    lines += prefill_block("6.1 64K 基线，批 139,712", d64)
    a(f"批 139,713 的 TTFT = {sec(d64_next['t'])}，超过 10 秒。所以 139,712 是这个输入的最大批。")
    a("")
    a(f"拉 KV 占 TTFT 的 {d64['pull'] / d64['t'] * 100:.2f}%。max(HBM, 计算) 取的是计算，HBM 是 {sec(d64['hbm'])}，计算是 {sec(d64['compute'])}。尾部是 0，因为 P→D 的 {sec(d64['pd'])} 短于主体的 60/61。")
    a("")
    lines += prefill_block("6.2 4M 基线，批 1,536", d4)
    a("")
    a("## 7. 每个输入的 Prefill 拆解")
    a("")
    a("每一行都用第 6 节的式子。下一批 TTFT 是当前批加 1 之后的时间，用来确认搜索停在边界上。")
    a("")
    pref_rows = []
    for s in m.LENGTHS:
        row = by[s]
        z = prefill_detail(row["b25"], s)
        nxt = prefill_detail(row["b25"] + 1, s)
        pref_rows.append([
            m.fmt_len(s),
            comma(row["b25"]),
            f"{z['t']:.4f}",
            f"{nxt['t']:.4f}",
            f"{z['pull']:.4f}",
            f"{z['compute']:.4f}",
            f"{z['hbm']:.4f}",
            f"{z['ar']:.4f}",
            f"{z['moe']['t']:.4f}",
            f"{z['tail']:.4f}",
            f"{z['pull'] / z['t'] * 100:.1f}%",
            f"{tps_prefill(row['b25'], s, z['t']):.4e}",
        ])
    lines += md_table(
        ["输入", "批", "TTFT秒", "下一批秒", "拉KV秒", "计算秒", "HBM秒", "AR秒", "MoE秒", "尾秒", "拉KV占比", "系统TPS"],
        pref_rows,
    )
    a("")
    a("## 8. Decode 的式子")
    a("")
    a("```text")
    a("TPOT = T_SWAP + max(T_HBM, T_compute) + T_AR + T_MoE")
    a("稀疏读见第 3 节")
    a("本卡稀疏读 = n × 一条稀疏读 / 8")
    a("溢出比例 = max(全局批 × K(S) − 副本房间, 0) / (全局批 × K(S))")
    a("T_SWAP = 本卡稀疏读 × 溢出比例 / 换入带宽")
    a("T_HBM = (本卡稀疏读 + 注意力权重/8) / 26.40 TB/s")
    a("T_compute = n × (score + 投影) / (8 × 33.60 P × align(n))")
    a("```")
    a("")
    a("换入带宽在基线里是 160 GB/s。每卡主机 DDR 还要装得下溢出的 KV，上限 96 GB。搜索在时间和容量里取同时满足的最大批。系统 Decode TPS = 全局批 / 实际 TPOT。")
    a("")
    lines += decode_block("8.1 64K、10 毫秒，批 125,600，换入 160 GB/s", dec64_10)
    a("溢出比例是 0，所以换入时间是 0。这条批的上限来自计算、AllReduce 和 MoE，不来自 DDR。")
    a("")
    lines += decode_block("8.2 4M、30 毫秒，批 7,646，换入 160 GB/s", dec4)
    a(f"批 7,647 的 TPOT = {sec(dec4_next['t'])}，超过 30 毫秒。每卡溢出 {gb(dec4['ddr'])}，低于 96 GB，所以这条批是被 160 GB/s 卡住的，768 GB 的机器容量还有空余。")
    a("")
    a("## 9. 每个输入的 Decode 拆解")
    a("")
    for label, key_b, key_d, limit in (
        ("9.1 TPOT ≤ 10 毫秒，换入 160 GB/s", "b10", "d10", 0.010),
        ("9.2 TPOT ≤ 30 毫秒，换入 160 GB/s", "b30", "d30", 0.030),
    ):
        a(f"### {label}")
        a("")
        rows = []
        for s in m.LENGTHS:
            row = by[s]
            bs = row[key_b]
            z = decode_detail(bs, s, m.HOST)
            nxt = decode_detail(bs + 1, s, m.HOST)
            rows.append([
                m.fmt_len(s),
                comma(bs),
                f"{z['t'] * 1e3:.3f}",
                f"{nxt['t'] * 1e3:.3f}",
                f"{z['spill'] * 100:.2f}%",
                f"{z['ddr'] / 1e9:.2f}",
                f"{z['swap'] * 1e3:.3f}",
                f"{z['ca'] * 1e3:.3f}",
                f"{z['hbm'] * 1e3:.3f}",
                f"{z['ar'] * 1e3:.3f}",
                f"{z['moe']['t'] * 1e3:.3f}",
                f"{tps_decode(bs, z['t']):.4e}",
            ])
            if z["t"] > limit + 1e-9 or nxt["t"] <= limit + 1e-9:
                raise AssertionError((label, s, bs, z["t"], nxt["t"]))
        lines += md_table(
            ["输入", "批", "TPOT毫秒", "下一批毫秒", "溢出", "每卡DDR GB", "SWAP毫秒", "计算毫秒", "HBM毫秒", "AR毫秒", "MoE毫秒", "系统TPS"],
            rows,
        )
        a("")
    a("10 毫秒在 64K、128K、256K 的溢出是 0。512K 起才有换入。30 毫秒从 128K 起有换入。表里的每卡 DDR 都低于 96 GB。")
    a("")
    a("## 10. 冷请求")
    a("")
    a("冷请求命中为 0，批为 1，不拉 prefix。q = S，p = 0。最大输入用二分找到，再检查相邻 token。")
    a("")
    lines += prefill_block(f"10.1 冷请求，输入 {comma(cold_s)}，批 1", cold)
    a(f"输入 {comma(cold_s + 1)} 的 TTFT = {sec(cold_next['t'])}。4M 冷请求的 TTFT = {sec(cold4['t'])}，其中计算 {sec(cold4['compute'])}，AllReduce {sec(cold4['ar'])}，MoE {sec(cold4['moe']['t'])}，拉 KV {sec(cold4['pull'])}。")
    a("")
    a("## 11. Case 1：基线改到 NEW")
    a("")
    a("基线是参数面物理带宽的 25%，每卡 25 GB/s。NEW 是物理 100 GB/s，不乘 80%。两条路径只改 T_pull 的分母，其余式子不变。批变大以后，计算、AllReduce、MoE 一起变长，所以 TPS 的提升低于带宽的 4 倍。")
    a("")
    a("### 11.1 64K")
    a("")
    a("```text")
    a(f"基线批 {comma(d64['bs'])}：拉 KV {sec(d64['pull'])}，计算 {sec(d64['compute'])}，AR {sec(d64['ar'])}，MoE {sec(d64['moe']['t'])}，TTFT {sec(d64['t'])}")
    a(f"NEW 批 {comma(d64_new['bs'])}：拉 KV {sec(d64_new['pull'])}，计算 {sec(d64_new['compute'])}，AR {sec(d64_new['ar'])}，MoE {sec(d64_new['moe']['t'])}，TTFT {sec(d64_new['t'])}")
    a(f"同一条 64K 序列的 prefix 字节仍是 {comma(d64['prefix_bytes'])}。带宽从 25 GB/s 到 100 GB/s，单条拉 KV 时间按 4 倍缩短。")
    a(f"基线系统 TPS = {num(tps_prefill(d64['bs'], 65536, d64['t']))}")
    a(f"NEW  系统 TPS = {num(tps_prefill(d64_new['bs'], 65536, d64_new['t']))}")
    a(f"提升 = {(tps_prefill(d64_new['bs'], 65536, d64_new['t']) / tps_prefill(d64['bs'], 65536, d64['t']) - 1) * 100:.1f}%")
    a(f"拉 KV 占比 {d64['pull']/d64['t']*100:.1f}% → {d64_new['pull']/d64_new['t']*100:.1f}%")
    a("```")
    a("")
    a("### 11.2 4M")
    a("")
    a("```text")
    a(f"基线批 {comma(d4['bs'])}：拉 KV {sec(d4['pull'])}，计算 {sec(d4['compute'])}，AR {sec(d4['ar'])}，MoE {sec(d4['moe']['t'])}，TTFT {sec(d4['t'])}")
    a(f"NEW 批 {comma(d4_new['bs'])}：拉 KV {sec(d4_new['pull'])}，计算 {sec(d4_new['compute'])}，AR {sec(d4_new['ar'])}，MoE {sec(d4_new['moe']['t'])}，TTFT {sec(d4_new['t'])}")
    a(f"基线系统 TPS = {num(tps_prefill(d4['bs'], 4194304, d4['t']))}")
    a(f"NEW  系统 TPS = {num(tps_prefill(d4_new['bs'], 4194304, d4_new['t']))}")
    a(f"提升 = {(tps_prefill(d4_new['bs'], 4194304, d4_new['t']) / tps_prefill(d4['bs'], 4194304, d4['t']) - 1) * 100:.1f}%")
    a(f"拉 KV 占比 {d4['pull']/d4['t']*100:.1f}% → {d4_new['pull']/d4_new['t']*100:.1f}%")
    a("```")
    a("")
    case_rows = []
    for s in m.LENGTHS:
        row = by[s]
        base = prefill_detail(row["b25"], s, prefix=m.PREFIX_25)
        new = prefill_detail(row["b100"], s, prefix=m.PREFIX_100)
        tps0 = tps_prefill(row["b25"], s, base["t"])
        tps1 = tps_prefill(row["b100"], s, new["t"])
        case_rows.append([
            m.fmt_len(s),
            comma(row["b25"]),
            comma(row["b100"]),
            f"{(tps1 / tps0 - 1) * 100:.1f}%",
            f"{base['pull']:.3f}",
            f"{new['pull']:.3f}",
            f"{base['compute']:.3f}",
            f"{new['compute']:.3f}",
            f"{base['ar']:.3f}",
            f"{new['ar']:.3f}",
            f"{base['moe']['t']:.3f}",
            f"{new['moe']['t']:.3f}",
            f"{base['pull'] / base['t'] * 100:.1f}%",
            f"{new['pull'] / new['t'] * 100:.1f}%",
        ])
    lines += md_table(
        ["输入", "基线批", "NEW批", "TPS提升", "基线拉KV", "NEW拉KV", "基线计算", "NEW计算", "基线AR", "NEW AR", "基线MoE", "NEW MoE", "基线占比", "NEW占比"],
        case_rows,
    )
    a("")
    a("## 12. Case 2：160 GB/s 换入改成 5.12 TB/s 的池")
    a("")
    a("池的标称是每卡 51.2 Tb/s。51.2e12 / 8 × 80% = 5.12 TB/s。容量不设上限，不经过 H2D，也不被 48 Tb/s 的交换平面截断。对照列仍是第 9 节的 160 GB/s。")
    a("")
    lines += decode_block("12.1 4M、30 毫秒，池上的批 17,184", dec4_pool)
    a("```text")
    a(f"H2D 批 {comma(dec4['bs'])}，TPOT {sec(dec4['t'])}，系统 TPS {num(tps_decode(dec4['bs'], dec4['t']))}")
    a(f"池  批 {comma(dec4_pool['bs'])}，TPOT {sec(dec4_pool['t'])}，系统 TPS {num(tps_decode(dec4_pool['bs'], dec4_pool['t']))}")
    a(f"TPS 提升 = {(tps_decode(dec4_pool['bs'], dec4_pool['t']) / tps_decode(dec4['bs'], dec4['t']) - 1) * 100:.1f}%")
    a(f"池上每卡溢出 = {gb(dec4_pool['ddr'])}，溢出比例 {dec4_pool['spill'] * 100:.2f}%")
    a("```")
    a("")
    a("池能放下更大的批，所以溢出比例反而更高：多出来的 KV 已经超出 150.68 TB 的 HBM 房间。")
    a("")
    pool_rows = []
    for s in m.LENGTHS:
        row = by[s]
        h10 = decode_detail(row["b10"], s, m.HOST)
        p10 = decode_detail(row["p10"], s, m.POOL)
        h30 = decode_detail(row["b30"], s, m.HOST)
        p30 = decode_detail(row["p30"], s, m.POOL)
        t10h, t10p = tps_decode(row["b10"], h10["t"]), tps_decode(row["p10"], p10["t"])
        t30h, t30p = tps_decode(row["b30"], h30["t"]), tps_decode(row["p30"], p30["t"])
        pool_rows.append([
            m.fmt_len(s),
            comma(row["b10"]),
            comma(row["p10"]),
            f"{(t10p / t10h - 1) * 100:.1f}%",
            comma(row["b30"]),
            comma(row["p30"]),
            f"{(t30p / t30h - 1) * 100:.1f}%",
            f"{p30['spill'] * 100:.1f}%",
            f"{p30['ddr'] / 1e9:.1f}",
        ])
    lines += md_table(
        ["输入", "10毫秒 H2D批", "10毫秒池批", "10毫秒提升", "30毫秒 H2D批", "30毫秒池批", "30毫秒提升", "池溢出", "池每卡DDR GB"],
        pool_rows,
    )
    a("")
    a("64K 到 256K 的 10 毫秒批没有溢出，换入带宽不影响批量，提升是 0。30 毫秒从 128K 起，池的批大于 H2D 的批。")
    a("")
    a("## 13. 副本怎么配")
    a("")
    a("一条请求在一个 Prefill 副本里做完输入，再在一个 Decode 副本里生成输出。输出按 512 token 计。一个 Prefill 副本每秒完成的请求数是 全局批 / TTFT。一个 Decode 副本每秒完成的请求数是 (全局批 / TPOT) / 512。")
    a("")
    a("```text")
    pair_rows = []
    for s, bkey, dkey, label in (
        (65536, "b10", "d10", "64K，10 毫秒"),
        (65536, "b30", "d30", "64K，30 毫秒"),
        (4194304, "b10", "d10", "4M，10 毫秒"),
        (4194304, "b30", "d30", "4M，30 毫秒"),
    ):
        row = by[s]
        rp, rd, ratio = m.req_pair(row["b25"], row["p25"]["t"], row[bkey], row[dkey]["t"])
        a(f"{label}：Prefill {rp:.2f} 请求/秒，Decode {rd:.2f} 请求/秒，{ratio:.2f} 份 Prefill 配 1 份 Decode")
        pair_rows.append([label, f"{rp:.2f}", f"{rd:.2f}", f"{ratio:.2f}"])
    a("```")
    a("")
    lines += md_table(["场景", "Prefill 请求/秒", "Decode 请求/秒", "Prefill 副本 / 1 个 Decode"], pair_rows)
    a("")
    a("## 14. 和幻灯片对过的数")
    a("")
    a("64K 基线批 139,712，TTFT 9.999 秒这一档，系统 Prefill TPS 9.16 亿 token/s。4M 基线批 1,536，10 毫秒批 7,335，30 毫秒批 7,646。4M 的 30 毫秒池批 17,184，相对 H2D 的系统 TPS 提升 124.7%。冷请求最大输入 3,575,424。")
    a("")
    checks = [
        (r64["b25"], 139712, "64K prefill"),
        (r4["b25"], 1536, "4M prefill"),
        (r4["b10"], 7335, "4M 10ms"),
        (r4["b30"], 7646, "4M 30ms"),
        (r4["p30"], 17184, "4M pool 30ms"),
        (cold_s, 3575424, "cold"),
    ]
    for got, expect, name in checks:
        if got != expect:
            raise AssertionError((name, got, expect))
    if abs(d64["t"] - 9.999) > 0.01:
        raise AssertionError(d64["t"])
    return lines


def set_run_font(run, size, bold=False, color=None, name="Microsoft YaHei"):
    run.font.name = name
    run.bold = bold
    run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor(*color)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)


def add_text(paragraph, text, size, bold=False, color=None, name="Microsoft YaHei"):
    parts = text.split("**")
    for i, part in enumerate(parts):
        if part == "":
            continue
        run = paragraph.add_run(part)
        set_run_font(run, size, bold or i % 2 == 1, color, name)


def shade_cell(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)


def write_docx(lines, path):
    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Cm(29.7)
    section.page_height = Cm(21.0)
    section.left_margin = Cm(1.4)
    section.right_margin = Cm(1.4)
    section.top_margin = Cm(1.4)
    section.bottom_margin = Cm(1.4)
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.0
                add_text(p, lines[i], 9, name="Consolas")
                i += 1
            i += 1
            continue
        if line.startswith("| ") and i + 1 < len(lines) and lines[i + 1].startswith("| ---"):
            headers = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            body = []
            while i < len(lines) and lines[i].startswith("| "):
                body.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            table = doc.add_table(rows=1 + len(body), cols=len(headers))
            table.style = "Table Grid"
            for c, text in enumerate(headers):
                cell = table.rows[0].cells[c]
                cell.text = ""
                p = cell.paragraphs[0]
                add_text(p, text, 8, True, (255, 255, 255))
                shade_cell(cell, "0E2A47")
            for r, row in enumerate(body):
                for c, text in enumerate(row):
                    cell = table.rows[r + 1].cells[c]
                    cell.text = ""
                    p = cell.paragraphs[0]
                    add_text(p, text, 8, c == 0, (14, 42, 71) if c == 0 else None)
                    if r % 2 == 1:
                        shade_cell(cell, "F4F7FA")
            doc.add_paragraph()
            continue
        if line.startswith("# "):
            p = doc.add_heading(line[2:], level=1)
            for run in p.runs:
                set_run_font(run, 20, True, (14, 42, 71))
        elif line.startswith("## "):
            p = doc.add_heading(line[3:], level=2)
            for run in p.runs:
                set_run_font(run, 16, True, (20, 90, 150))
        elif line.startswith("### "):
            p = doc.add_heading(line[4:], level=3)
            for run in p.runs:
                set_run_font(run, 13, True, (14, 122, 118))
        elif line.strip() == "":
            pass
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            add_text(p, line, 11)
        i += 1
    doc.save(path)


def main():
    lines = build_lines()
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_docx(lines, DOCX_PATH)
    print(MD_PATH)
    print(DOCX_PATH)


if __name__ == "__main__":
    main()
