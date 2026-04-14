#!/usr/bin/env python3
"""
有社交 vs 无社交：推理同质性对比（三层去模板 NCD）

自动发现配对实验（X 与 X_无社交），
对 decisions.jsonl 中的推理文本做三层去模板后计算 NCD 同质性，
以哑铃图对比有社交与无社交的差异。

用法：
  cd evaluation/sentiment_social_compare
  python plot_reasoning_homogeneity_social_compare.py [--runs-root ../../runs]
"""

from __future__ import annotations

import argparse
import bisect
import math
import re
import sys
import zlib
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

_EVAL_DIR = Path(__file__).resolve().parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from metrics_plot_common import configure_chinese_font, read_jsonl, safe_int

_MAX_PAIRS = 300
_DAILY_MIN_DOCS = 5


# ── sim_time → trading_day ───────────────────────────────────────────
def _build_time_to_day(run_dir: Path):
    centers = []
    bi_path = run_dir / "broad_index.jsonl"
    if not bi_path.exists():
        return None
    for r in read_jsonl(bi_path):
        st = r.get("sim_time")
        td = safe_int(r.get("trading_day"))
        if st is not None and td is not None:
            centers.append((float(st), td))
    centers.sort()
    times = [c[0] for c in centers]
    days = [c[1] for c in centers]

    def mapper(sim_time: float) -> int:
        idx = bisect.bisect_right(times, sim_time)
        if idx == 0:
            return days[0]
        if idx >= len(times):
            return days[-1]
        if abs(times[idx] - sim_time) < abs(times[idx - 1] - sim_time):
            return days[idx]
        return days[idx - 1]

    return mapper


# ── 推理文本提取 ─────────────────────────────────────────────────────
def _extract_reasoning_parts(llm_output: dict, tom_level: int) -> list[str]:
    """返回推理文本列表（ToM-2 拆分为两条独立文本，避免拼接膨胀相似度）。"""
    if tom_level == 2:
        parts = []
        for k in ("tom1_reasoning", "tom2_reasoning"):
            v = llm_output.get(k, "")
            if v and not v.startswith("(ToM"):
                parts.append(v)
        return parts
    elif tom_level == 1:
        v = llm_output.get("mental_reasoning", "")
        if v and not v.startswith("(ToM"):
            return [v]
    return []


# ── 加载推理文本 ─────────────────────────────────────────────────────
def load_reasoning_texts(run_dir: Path, max_chars: int = 512):
    """返回 { day: { tom_group: [text, ...] } }"""
    mapper = _build_time_to_day(run_dir)
    if mapper is None:
        return {}
    dec_path = run_dir / "decisions.jsonl"
    if not dec_path.exists():
        return {}

    result: dict[int, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list))
    for r in read_jsonl(dec_path):
        tl = r.get("tom_level", 0)
        if tl == 0:
            continue
        out = r.get("llm_output", {})
        parts = _extract_reasoning_parts(out, tl)
        if not parts:
            continue
        day = mapper(float(r["sim_time"]))
        tom_group = f"tom{tl}"
        for text in parts:
            result[day][tom_group].append(text[:max_chars])
    return dict(result)


# ── 分词与 n-gram ────────────────────────────────────────────────────
def _tokenize(text: str) -> list[str]:
    import jieba
    jieba.setLogLevel(20)
    return list(jieba.cut(text))


def _multi_ngrams(tokens: list[str], sizes: list[int]) -> set[tuple]:
    result = set()
    n = len(tokens)
    for size in sizes:
        for i in range(n - size + 1):
            result.add(tuple(tokens[i:i + size]))
    return result


def _remove_template_spans(tokens: list[str],
                           template_ngs: set[tuple],
                           ngram_sizes: list[int]) -> list[str]:
    n = len(tokens)
    is_tpl = [False] * n
    for size in ngram_sizes:
        for i in range(n - size + 1):
            if tuple(tokens[i:i + size]) in template_ngs:
                for j in range(i, i + size):
                    is_tpl[j] = True
    return [t for i, t in enumerate(tokens) if not is_tpl[i]]


def _sample_pairs(n: int) -> list[tuple[int, int]]:
    if n < 2:
        return []
    total = n * (n - 1) // 2
    if total <= _MAX_PAIRS:
        return list(combinations(range(n), 2))
    pairs: set[tuple[int, int]] = set()
    while len(pairs) < _MAX_PAIRS:
        i, j = sorted(np.random.choice(n, 2, replace=False))
        pairs.add((i, j))
    return list(pairs)


# ── 计算单实验同质性 ─────────────────────────────────────────────────
def compute_homogeneity(day_group_texts: dict,
                        ngram_n: int = 2,
                        global_thresh: float = 0.80,
                        group_thresh: float = 0.60,
                        daily_thresh: float = 0.50) -> float | None:
    """三层去模板 → NCD 同质性，返回全交易日均值或 None。"""
    import jieba
    jieba.setLogLevel(20)

    ngram_sizes = [ngram_n, ngram_n + 1]

    class _Doc:
        __slots__ = ("day", "gk", "tokens", "ngrams")

        def __init__(self, day, gk, tokens, ngrams):
            self.day = day
            self.gk = gk
            self.tokens = tokens
            self.ngrams = ngrams

    docs: list[_Doc] = []
    for day in sorted(day_group_texts.keys()):
        for gk in sorted(day_group_texts[day].keys()):
            for text in day_group_texts[day][gk]:
                tokens = _tokenize(text)
                ngrams = _multi_ngrams(tokens, ngram_sizes)
                docs.append(_Doc(day, gk, tokens, ngrams))

    total = len(docs)
    if total < 4:
        return None

    # L1: 全局
    global_df: Counter = Counter()
    for doc in docs:
        for ng in doc.ngrams:
            global_df[ng] += 1
    global_tpl = {ng for ng, c in global_df.items()
                  if c > total * global_thresh}

    # L2: 组级
    group_indices: dict[str, list[int]] = defaultdict(list)
    for i, doc in enumerate(docs):
        group_indices[doc.gk].append(i)

    group_tpl: dict[str, set] = {}
    for gk, indices in group_indices.items():
        gdf: Counter = Counter()
        for i in indices:
            for ng in docs[i].ngrams:
                gdf[ng] += 1
        n_g = len(indices)
        group_tpl[gk] = {ng for ng, c in gdf.items()
                         if c > n_g * group_thresh
                         and ng not in global_tpl}

    # L3: 逐日
    day_indices: dict[int, list[int]] = defaultdict(list)
    for i, doc in enumerate(docs):
        day_indices[doc.day].append(i)

    upper_tpl = set(global_tpl)
    for v in group_tpl.values():
        upper_tpl |= v

    daily_tpl: dict[int, set] = {}
    for day, indices in day_indices.items():
        if len(indices) < _DAILY_MIN_DOCS:
            daily_tpl[day] = set()
            continue
        ddf: Counter = Counter()
        for i in indices:
            for ng in docs[i].ngrams:
                ddf[ng] += 1
        n_d = len(indices)
        daily_tpl[day] = {ng for ng, c in ddf.items()
                          if c > n_d * daily_thresh
                          and ng not in upper_tpl}

    tpl_total = (len(global_tpl)
                 + sum(len(v) for v in group_tpl.values())
                 + sum(len(v) for v in daily_tpl.values()))
    print(f"    三层模板: L1={len(global_tpl)} L2={sum(len(v) for v in group_tpl.values())} "
          f"L3={sum(len(v) for v in daily_tpl.values())} (共{tpl_total})")

    # 去模板 NCD
    cleaned_bytes: list[bytes] = []
    for doc in docs:
        all_tpl = (global_tpl
                   | group_tpl.get(doc.gk, set())
                   | daily_tpl.get(doc.day, set()))
        remaining = _remove_template_spans(doc.tokens, all_tpl, ngram_sizes)
        cleaned_bytes.append("".join(remaining).encode("utf-8"))

    comp_sizes = [len(zlib.compress(b, level=6)) for b in cleaned_bytes]

    def _ncd_sim(gi: int, gj: int) -> float:
        ca, cb = comp_sizes[gi], comp_sizes[gj]
        if ca == 0 and cb == 0:
            return float("nan")
        cab = len(zlib.compress(
            cleaned_bytes[gi] + cleaned_bytes[gj], level=6))
        denom = max(ca, cb)
        if denom == 0:
            return float("nan")
        return 1.0 - (cab - min(ca, cb)) / denom

    day_ncds = []
    for day, indices in day_indices.items():
        n = len(indices)
        pairs = _sample_pairs(n)
        if not pairs:
            continue
        sims = [_ncd_sim(indices[i], indices[j]) for i, j in pairs]
        valid = [s for s in sims if not math.isnan(s)]
        if valid:
            day_ncds.append(float(np.mean(valid)))

    if not day_ncds:
        return None
    return round(float(np.mean(day_ncds)), 4)


# ── 配对实验发现 ─────────────────────────────────────────────────────
def find_social_pairs(runs_root: Path) -> list[tuple[str, Path, Path]]:
    dirs = {d.name: d for d in runs_root.iterdir() if d.is_dir()}
    pairs = []
    for name in sorted(dirs):
        if name.endswith("_无社交"):
            base = name[: -len("_无社交")]
            if base in dirs:
                pairs.append((base, dirs[base], dirs[name]))

    def _sort_key(item):
        m = re.fullmatch(r"ToM(\d+)", item[0])
        return (0, int(m.group(1))) if m else (1, item[0])

    pairs.sort(key=_sort_key)
    return pairs


# ── 哑铃图绘制 ───────────────────────────────────────────────────────
def plot_dumbbell(data: list[dict], output: str):
    configure_chinese_font()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(data)
    if n == 0:
        return

    labels = [d["label"] for d in data]
    social_vals = np.array([d["social"] for d in data])
    nosocial_vals = np.array([d["nosocial"] for d in data])

    x = np.arange(n)
    fig, ax = plt.subplots(figsize=(max(7, 1.8 * n), 5.5))

    for i in range(n):
        ax.plot([x[i], x[i]], [social_vals[i], nosocial_vals[i]],
                color="#bfbfbf", linewidth=2.8, zorder=1,
                solid_capstyle="round")

    ax.scatter(x, social_vals, s=140, color="#0969da", zorder=3,
               label="有社交")
    ax.scatter(x, nosocial_vals, s=140, color="#cf222e", zorder=3,
               marker="D", label="无社交")

    for i in range(n):
        sv, nv = social_vals[i], nosocial_vals[i]
        diff = sv - nv
        sign = "+" if diff > 0 else ""

        if sv >= nv:
            s_off, n_off = (0, 10), (0, -14)
            s_va, n_va = "bottom", "top"
        else:
            s_off, n_off = (0, -14), (0, 10)
            s_va, n_va = "top", "bottom"

        ax.annotate(f"{sv:.4f}", (x[i], sv), textcoords="offset points",
                    xytext=s_off, ha="center", va=s_va, fontsize=10,
                    color="#0969da", fontweight="bold")
        ax.annotate(f"{nv:.4f}", (x[i], nv), textcoords="offset points",
                    xytext=n_off, ha="center", va=n_va, fontsize=10,
                    color="#cf222e", fontweight="bold")

        mid_y = (sv + nv) / 2
        color = "#0969da" if diff > 0 else "#cf222e" if diff < 0 else "#656d76"
        ax.annotate(f"Δ={sign}{diff:.4f}", (x[i], mid_y),
                    textcoords="offset points", xytext=(30, 0),
                    ha="left", va="center", fontsize=9, color=color,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#f6f8fa",
                              edgecolor="#d0d7de", alpha=0.9))

    y_min = min(social_vals.min(), nosocial_vals.min())
    y_max = max(social_vals.max(), nosocial_vals.max())
    margin = (y_max - y_min) * 0.4 if y_max > y_min else 0.1
    ax.set_ylim(y_min - margin, y_max + margin)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("1 − NCD (去模板, 全交易日均值)", fontsize=11)
    ax.set_title("有社交 vs 无社交：推理同质性对比（三层去模板 NCD）",
                 fontsize=14, fontweight="bold", pad=12)
    ax.yaxis.grid(True, linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=11, framealpha=0.9, loc="upper center", ncol=2,
              bbox_to_anchor=(0.5, -0.08))

    plt.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] {output}")


# ── main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="有社交 vs 无社交 推理同质性对比（三层去模板 NCD）")
    parser.add_argument("--runs-root", default="../../runs",
                        help="runs 目录")
    parser.add_argument("--max-chars", type=int, default=512,
                        help="推理文本截断字符数")
    parser.add_argument("--ngram", type=int, default=2,
                        help="最小 n-gram 大小 (自动同时使用 n 和 n+1)")
    args = parser.parse_args()

    runs_root = Path(args.runs_root).resolve()
    pairs = find_social_pairs(runs_root)
    if not pairs:
        print("[ERROR] 未找到配对实验", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(pairs)} 组配对:")

    ncd_data = []
    for label, social_dir, nosocial_dir in pairs:
        print(f"\n--- {label} ---")

        print(f"  有社交: {social_dir.name}")
        s_texts = load_reasoning_texts(social_dir, args.max_chars)
        s_ncd = compute_homogeneity(s_texts, args.ngram,
                                    group_thresh=1.01, daily_thresh=1.01)

        print(f"  无社交: {nosocial_dir.name}")
        n_texts = load_reasoning_texts(nosocial_dir, args.max_chars)
        n_ncd = compute_homogeneity(n_texts, args.ngram,
                                    group_thresh=1.01, daily_thresh=1.01)

        if s_ncd is None or n_ncd is None:
            print(f"  [SKIP] {label}: 缺少有效推理文本")
            continue

        print(f"  NCD: 有社交={s_ncd:.4f}  无社交={n_ncd:.4f}  "
              f"Δ={s_ncd - n_ncd:+.4f}")
        ncd_data.append({"label": label, "social": s_ncd, "nosocial": n_ncd})

    out_dir = Path(__file__).resolve().parent
    if ncd_data:
        plot_dumbbell(
            ncd_data,
            str(out_dir / "reasoning_homogeneity_ncd_compare.png"))


if __name__ == "__main__":
    main()
