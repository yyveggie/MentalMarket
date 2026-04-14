#!/usr/bin/env python3
"""
有社交 vs 无社交：推理同质性对比（Jaccard + NCD）

对配对实验的 decisions.jsonl，按 ToM 层级分组，
计算同组同日所有 agent 推理文本的 pairwise Jaccard / NCD 相似度，
取全交易日均值后以哑铃图对比有社交与无社交。

用法：
  cd evaluation/sentiment_social_compare
  python plot_reasoning_homogeneity_social_compare.py [--runs-root ../../runs]
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
import zlib
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

# ── 路径处理：确保能 import 上级 evaluation 公共模块 ──────────────

_EVAL_DIR = Path(__file__).resolve().parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from metrics_plot_common import configure_chinese_font, read_jsonl, safe_int


# ── sim_time → trading_day 映射 ──────────────────────────────────────

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

def _extract_reasoning(llm_output: dict, tom_level: int) -> str:
    if tom_level == 2:
        parts = []
        for k in ("tom1_reasoning", "tom2_reasoning"):
            v = llm_output.get(k, "")
            if v and not v.startswith("(ToM"):
                parts.append(v)
        return "\n".join(parts)
    elif tom_level == 1:
        v = llm_output.get("mental_reasoning", "")
        return "" if v.startswith("(ToM") else v
    return ""


# ── 加载推理文本 ─────────────────────────────────────────────────────

def load_reasoning_texts(run_dir: Path, max_chars: int = 512):
    """
    返回 { tom_level: { trading_day: [text, ...] } }
    跳过 tom0（占位推理无意义）。
    """
    mapper = _build_time_to_day(run_dir)
    if mapper is None:
        return {}
    dec_path = run_dir / "decisions.jsonl"
    if not dec_path.exists():
        return {}

    result: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in read_jsonl(dec_path):
        tl = r.get("tom_level", 0)
        if tl == 0:
            continue
        out = r.get("llm_output", {})
        text = _extract_reasoning(out, tl)
        if not text:
            continue
        text = text[:max_chars]
        day = mapper(float(r["sim_time"]))
        result[tl][day].append(text)
    return dict(result)


# ── jieba 分词 + n-gram ──────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    import jieba
    jieba.setLogLevel(20)
    return list(jieba.cut(text))


def _ngrams(tokens: list[str], n: int = 2) -> set[tuple]:
    return set(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


# ── Jaccard ──────────────────────────────────────────────────────────

def jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


# ── NCD 相似度 ───────────────────────────────────────────────────────

def ncd_similarity(a: str, b: str) -> float:
    ca = len(zlib.compress(a.encode("utf-8")))
    cb = len(zlib.compress(b.encode("utf-8")))
    cab = len(zlib.compress((a + b).encode("utf-8")))
    ncd = (cab - min(ca, cb)) / max(ca, cb) if max(ca, cb) > 0 else 0.0
    return 1.0 - ncd


# ── 计算单实验同质性 ─────────────────────────────────────────────────

def compute_homogeneity(tom_day_texts: dict[int, dict[int, list[str]]],
                        ngram_n: int = 2, max_pairs: int = 500,
                        template_thresh: float = 0.10):
    """
    合并所有 ToM 层级，按天计算全体 agent 推理文本的 pairwise 同质性。
    先做模板 n-gram 过滤（去掉出现在 >template_thresh 比例文档中的 n-gram），
    返回 { 'jaccard_mean': float, 'ncd_mean': float } 或 None。
    """
    # 合并所有 ToM 到 day -> [text]
    day_texts: dict[int, list[str]] = defaultdict(list)
    for tl_days in tom_day_texts.values():
        for day, texts in tl_days.items():
            day_texts[day].extend(texts)

    if not day_texts:
        return None

    # ── 模板 n-gram 检测：收集全部文本的 n-gram 文档频率 ──
    all_texts_flat = [t for texts in day_texts.values() for t in texts]
    from collections import Counter
    doc_count: Counter = Counter()
    for t in all_texts_flat:
        ng = _ngrams(_tokenize(t), ngram_n)
        for g in ng:
            doc_count[g] += 1
    n_docs = len(all_texts_flat)
    template_ngrams = {g for g, c in doc_count.items() if c / n_docs > template_thresh}
    print(f"    模板 n-gram: {len(template_ngrams)}/{len(doc_count)} (阈值>{template_thresh*100:.0f}%)")

    rng = np.random.default_rng(42)
    day_jaccards = []
    day_ncds = []

    for day in sorted(day_texts):
        texts = day_texts[day]
        n = len(texts)
        if n < 2:
            continue

        # 过滤掉模板 n-gram
        ngram_sets = [_ngrams(_tokenize(t), ngram_n) - template_ngrams for t in texts]

        all_pairs = list(combinations(range(n), 2))
        if len(all_pairs) > max_pairs:
            indices = rng.choice(len(all_pairs), max_pairs, replace=False)
            selected = [all_pairs[i] for i in indices]
        else:
            selected = all_pairs

        jaccards = []
        ncds = []
        for i, j in selected:
            jaccards.append(jaccard(ngram_sets[i], ngram_sets[j]))
            ncds.append(ncd_similarity(texts[i], texts[j]))

        day_jaccards.append(np.mean(jaccards))
        day_ncds.append(np.mean(ncds))

    if not day_jaccards:
        return None

    return {
        "jaccard_mean": round(float(np.mean(day_jaccards)), 2),
        "ncd_mean": round(float(np.mean(day_ncds)), 2),
    }


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

def plot_dumbbell(data: list[dict], metric_key: str, metric_label: str,
                  title: str, output: str):
    """
    data: [{'label': str, 'tom': int, 'social': float, 'nosocial': float}, ...]
    """
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

    # 竖线
    for i in range(n):
        ax.plot([x[i], x[i]], [social_vals[i], nosocial_vals[i]],
                color="#bfbfbf", linewidth=2.8, zorder=1, solid_capstyle="round")

    ax.scatter(x, social_vals, s=140, color="#0969da", zorder=3, label="有社交")
    ax.scatter(x, nosocial_vals, s=140, color="#cf222e", zorder=3, marker="D", label="无社交")

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

        ax.annotate(f"{sv:.2f}", (x[i], sv), textcoords="offset points",
                    xytext=s_off, ha="center", va=s_va, fontsize=10,
                    color="#0969da", fontweight="bold")
        ax.annotate(f"{nv:.2f}", (x[i], nv), textcoords="offset points",
                    xytext=n_off, ha="center", va=n_va, fontsize=10,
                    color="#cf222e", fontweight="bold")

        mid_y = (sv + nv) / 2
        color = "#0969da" if diff > 0 else "#cf222e" if diff < 0 else "#656d76"
        ax.annotate(f"Δ={sign}{diff:.2f}", (x[i], mid_y),
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
    ax.set_ylabel(metric_label, fontsize=11)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
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
    parser = argparse.ArgumentParser(description="有社交 vs 无社交 推理同质性对比")
    parser.add_argument("--runs-root", default="../../runs", help="runs 目录")
    parser.add_argument("--max-chars", type=int, default=512, help="推理文本截断字符数")
    parser.add_argument("--max-pairs", type=int, default=500, help="每日最大采样配对数")
    parser.add_argument("--ngram", type=int, default=2, help="n-gram 大小")
    args = parser.parse_args()

    runs_root = Path(args.runs_root).resolve()
    pairs = find_social_pairs(runs_root)
    if not pairs:
        print("[ERROR] 未找到配对实验", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(pairs)} 组配对:")

    jaccard_data = []
    ncd_data = []

    for label, social_dir, nosocial_dir in pairs:
        print(f"\n--- {label} ---")

        print(f"  有社交: {social_dir.name}")
        s_texts = load_reasoning_texts(social_dir, args.max_chars)
        s_homo = compute_homogeneity(s_texts, args.ngram, args.max_pairs)

        print(f"  无社交: {nosocial_dir.name}")
        n_texts = load_reasoning_texts(nosocial_dir, args.max_chars)
        n_homo = compute_homogeneity(n_texts, args.ngram, args.max_pairs)

        if s_homo is None or n_homo is None:
            print(f"  [SKIP] {label}: 缺少有效推理文本")
            continue

        sj, nj = s_homo["jaccard_mean"], n_homo["jaccard_mean"]
        sn, nn = s_homo["ncd_mean"], n_homo["ncd_mean"]
        print(f"  Jaccard: 有社交={sj:.2f}  无社交={nj:.2f}  Δ={sj - nj:+.2f}")
        print(f"  NCD:     有社交={sn:.2f}  无社交={nn:.2f}  Δ={sn - nn:+.2f}")
        jaccard_data.append({"label": label, "social": sj, "nosocial": nj})
        ncd_data.append({"label": label, "social": sn, "nosocial": nn})

    out_dir = Path(__file__).resolve().parent
    if jaccard_data:
        plot_dumbbell(jaccard_data, "jaccard", "Jaccard 同质性（全交易日均值）",
                      "有社交 vs 无社交：推理 Jaccard 同质性对比",
                      str(out_dir / "reasoning_homogeneity_jaccard_compare.png"))
    if ncd_data:
        plot_dumbbell(ncd_data, "ncd", "NCD 同质性（全交易日均值）",
                      "有社交 vs 无社交：推理 NCD 同质性对比",
                      str(out_dir / "reasoning_homogeneity_ncd_compare.png"))


if __name__ == "__main__":
    main()
