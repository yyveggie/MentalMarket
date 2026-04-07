#!/usr/bin/env python3
"""
字符级推理同质性分析 — TF-IDF 去模板 Jaccard + NCD 双指标

方案 A：去高频短语后的 n-gram Jaccard 相似度
方案 B：压缩距离 NCD（Normalized Compression Distance）

输出：
  1. 每实验单图（双 Y 轴：Jaccard + NCD）
  2. 多实验对比图
  3. JSON 汇总

用法：
  # 单个实验
  python plot_reasoning_homogeneity_char.py runs/20260329_005147_tom07_tom12_tom21_预测拟合

  # 多个实验对比（生成单图 + 对比图）
  python plot_reasoning_homogeneity_char.py \
    runs/20260329_005147_tom07_tom12_tom21_预测拟合 \
    runs/20260329_150251_tom01_tom11_tom21_预测拟合 \
    runs/20260330_211929_tom06_tom13_tom21_预测拟合 \
    --labels "tom07/12/21,tom01/11/21,tom06/13/21"

  # 自定义参数
  python plot_reasoning_homogeneity_char.py runs/xxx \
    --ngram 3                  # 使用 trigram（默认 bigram）
    --template-thresh 0.70     # 出现在 >70% 文本中的 n-gram 视为模板（默认 80%）
    --max-chars 256            # 每条推理截断到 256 字符（默认 512）
    --output-dir my_output

输出文件（在 --output-dir 下）：
  推理同质性_字符级_{label}.png        每个实验的 Jaccard + NCD 双指标时间序列
  推理同质性_字符级_多实验对比.png     多实验对比图（仅多实验时生成）
  推理同质性_字符级_汇总.json          所有实验汇总统计
"""

import argparse
import bisect
import json
import os
import random
import sys
import zlib
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

# 组内超过此数量时随机采样配对，不做全量 C(n,2)
_MAX_PAIRS = 300

# ── CLI ──────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="字符级推理同质性分析")
    p.add_argument("run_dirs", nargs="+", help="实验目录")
    p.add_argument("--labels", default="", help="逗号分隔的实验标签")
    p.add_argument("--ngram", type=int, default=2, help="n-gram 大小 (默认 bigram)")
    p.add_argument("--template-thresh", type=float, default=0.80,
                   help="出现在 >X%% agent 中的 n-gram 视为模板 (默认 0.80)")
    p.add_argument("--max-chars", type=int, default=512,
                   help="每条推理文本截断到前 N 个字符")
    p.add_argument("--output-dir", default="output")
    return p.parse_args()


# ── 推理文本提取 ─────────────────────────────────────────────────────
def _extract_reasoning_parts(llm_output: dict, tom_level: int) -> dict:
    """
    返回 { group_suffix: text } 字典。
    tom0/tom1: {"":  mental_reasoning}
    tom2 拆分: {"_r1": tom1_reasoning, "_r2": tom2_reasoning}
    这样 tom2 的一阶推理和二阶推理分开统计，不会因为拼接而膨胀公共部分。
    """
    if tom_level == 2:
        parts = {}
        r1 = llm_output.get("tom1_reasoning", "")
        r2 = llm_output.get("tom2_reasoning", "")
        if r1 and not r1.startswith("(ToM"):
            parts["_r1"] = r1
        if r2 and not r2.startswith("(ToM"):
            parts["_r2"] = r2
        return parts
    else:
        mr = llm_output.get("mental_reasoning", "")
        if mr and not mr.startswith("(ToM"):
            return {"": mr}
        return {}


# ── sim_time → trading_day ───────────────────────────────────────────
def _build_time_to_day(run_dir: str):
    centers = []
    with open(os.path.join(run_dir, "broad_index.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            centers.append((rec["sim_time"], rec["trading_day"]))
    centers.sort()
    times = [c[0] for c in centers]
    days  = [c[1] for c in centers]

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


def load_decisions(run_dir: str, max_chars: int):
    """
    返回 { day: { group_key: [text, ...] } }
    group_key 例如: "tom1", "tom2_r1", "tom2_r2"
    """
    mapper = _build_time_to_day(run_dir)
    result = defaultdict(lambda: defaultdict(list))
    with open(os.path.join(run_dir, "decisions.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            tl  = rec.get("tom_level", 0)
            out = rec.get("llm_output", {})
            parts = _extract_reasoning_parts(out, tl)
            day = mapper(rec["sim_time"])
            for suffix, text in parts.items():
                gk = f"tom{tl}{suffix}"
                result[day][gk].append(text[:max_chars])
    return dict(result)


# ── 方案 A：TF-IDF 去模板 + Jaccard ─────────────────────────────────
def _tokenize(text: str):
    """jieba 分词"""
    import jieba
    return list(jieba.cut(text))


def _ngrams(tokens: list, n: int):
    """生成 n-gram 集合"""
    return set(tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1))


def compute_jaccard_homogeneity(day_group_texts: dict, ngram_n: int, thresh: float):
    """
    返回:
      intra: { group_key: { day: float } }
      inter: { day: float }
    """
    import jieba
    jieba.setLogLevel(20)

    print("  分词中…")
    all_doc_ngrams = []   # [(day, gk, ngram_set), ...]
    for day in sorted(day_group_texts.keys()):
        for gk in sorted(day_group_texts[day].keys()):
            for text in day_group_texts[day][gk]:
                tokens = _tokenize(text)
                ngs = _ngrams(tokens, ngram_n)
                all_doc_ngrams.append((day, gk, ngs))

    total_docs = len(all_doc_ngrams)
    if total_docs == 0:
        return {}, {}

    # 计算全局 DF
    print(f"  计算 DF（共 {total_docs} 条文本）…")
    df = Counter()
    for _, _, ngs in all_doc_ngrams:
        for ng in ngs:
            df[ng] += 1

    # 标记模板 n-gram（出现在 >thresh 比例的文档中）
    template_ngs = set()
    cutoff = int(total_docs * thresh)
    for ng, count in df.items():
        if count > cutoff:
            template_ngs.add(ng)
    print(f"  模板 n-gram 数量: {len(template_ngs)} / {len(df)} (阈值: >{thresh*100:.0f}%)")

    cleaned = []
    for day, gk, ngs in all_doc_ngrams:
        cleaned_ngs = ngs - template_ngs
        cleaned.append((day, gk, cleaned_ngs))

    groups = defaultdict(list)      # (day, gk) -> [cleaned_ngs]
    day_all = defaultdict(list)
    for day, gk, ngs in cleaned:
        groups[(day, gk)].append(ngs)
        day_all[day].append(ngs)

    def _mean_pairwise_jaccard(ngram_list):
        n = len(ngram_list)
        if n < 2:
            return float("nan")
        total_pairs = n * (n - 1) // 2
        if total_pairs <= _MAX_PAIRS:
            pairs = list(combinations(range(n), 2))
        else:
            pairs = set()
            while len(pairs) < _MAX_PAIRS:
                i, j = random.sample(range(n), 2)
                pairs.add((min(i, j), max(i, j)))
            pairs = list(pairs)
        sims = []
        for i, j in pairs:
            a, b = ngram_list[i], ngram_list[j]
            union = len(a | b)
            if union == 0:
                sims.append(1.0)
            else:
                sims.append(len(a & b) / union)
        return float(np.mean(sims))

    print("  计算 Jaccard 相似度…")
    intra = defaultdict(dict)
    for (day, gk), ngs_list in groups.items():
        intra[gk][day] = _mean_pairwise_jaccard(ngs_list)

    inter = {}
    for day, ngs_list in day_all.items():
        inter[day] = _mean_pairwise_jaccard(ngs_list)

    return dict(intra), inter


# ── 方案 B：NCD ──────────────────────────────────────────────────────
def _compress_size(text_bytes: bytes) -> int:
    return len(zlib.compress(text_bytes, level=6))


def _ncd(a: bytes, b: bytes, ca: int = 0, cb: int = 0) -> float:
    """Normalized Compression Distance（可传入预计算的 ca/cb）"""
    if ca == 0:
        ca = _compress_size(a)
    if cb == 0:
        cb = _compress_size(b)
    cab = _compress_size(a + b)
    denom = max(ca, cb)
    if denom == 0:
        return 0.0
    return (cab - min(ca, cb)) / denom


def compute_ncd_homogeneity(day_group_texts: dict):
    """
    NCD 越小 = 越相似，转换为 similarity = 1 - NCD。
    返回: intra { group_key: { day: float } }, inter { day: float }
    """
    encoded = defaultdict(lambda: defaultdict(list))  # day -> gk -> [bytes]
    comp_sz  = defaultdict(lambda: defaultdict(list))
    day_all  = defaultdict(list)
    day_all_sz = defaultdict(list)
    for day in sorted(day_group_texts.keys()):
        for gk in sorted(day_group_texts[day].keys()):
            for text in day_group_texts[day][gk]:
                b = text.encode("utf-8")
                sz = _compress_size(b)
                encoded[day][gk].append(b)
                comp_sz[day][gk].append(sz)
                day_all[day].append(b)
                day_all_sz[day].append(sz)

    def _mean_pairwise_ncd_sim(byte_list, comp_sizes):
        n = len(byte_list)
        if n < 2:
            return float("nan")
        total_pairs = n * (n - 1) // 2
        if total_pairs <= _MAX_PAIRS:
            pairs = list(combinations(range(n), 2))
        else:
            pairs = set()
            while len(pairs) < _MAX_PAIRS:
                i, j = random.sample(range(n), 2)
                pairs.add((min(i, j), max(i, j)))
            pairs = list(pairs)
        sims = []
        for i, j in pairs:
            sims.append(1.0 - _ncd(byte_list[i], byte_list[j],
                                   comp_sizes[i], comp_sizes[j]))
        return float(np.mean(sims))

    print("  计算 NCD 相似度…")
    intra = defaultdict(dict)
    for day in sorted(encoded.keys()):
        for gk in sorted(encoded[day].keys()):
            intra[gk][day] = _mean_pairwise_ncd_sim(
                encoded[day][gk], comp_sz[day][gk])

    inter = {}
    for day in sorted(day_all.keys()):
        inter[day] = _mean_pairwise_ncd_sim(day_all[day], day_all_sz[day])

    return dict(intra), inter


# ── 绘图 ──────────────────────────────────────────────────────────────
def plot_single_run(jaccard_intra, jaccard_inter, ncd_intra, ncd_inter,
                    label, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    tom_levels = sorted(set(list(jaccard_intra.keys()) + list(ncd_intra.keys())))
    _DISPLAY = {"tom1": "ToM-1", "tom2_r1": "ToM-2 一阶推理", "tom2_r2": "ToM-2 二阶推理"}
    n_plots = len(tom_levels) + 1  # +1 全体
    fig, axes = plt.subplots(1, n_plots, figsize=(6 * n_plots, 5), sharey=True)
    if n_plots == 1:
        axes = [axes]

    def _plot_pair(ax, jaccard_dict, ncd_dict, title):
        """在同一子图画 Jaccard (实线) 和 NCD-sim (虚线)"""
        days_j = sorted(jaccard_dict.keys())
        vals_j = [jaccard_dict[d] for d in days_j]
        valid_j = [(d, v) for d, v in zip(days_j, vals_j) if not np.isnan(v)]

        days_n = sorted(ncd_dict.keys())
        vals_n = [ncd_dict[d] for d in days_n]
        valid_n = [(d, v) for d, v in zip(days_n, vals_n) if not np.isnan(v)]

        if valid_j:
            ds, vs = zip(*valid_j)
            ax.plot(ds, vs, label="Jaccard (去模板)", color="#E91E63",
                    linewidth=1.5, alpha=0.85)
        if valid_n:
            ds, vs = zip(*valid_n)
            ax.plot(ds, vs, label="1−NCD", color="#2196F3",
                    linewidth=1.5, alpha=0.85, linestyle="--")
        ax.set_title(title, fontsize=11)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(-0.05, 1.05)
        ax.set_xlabel("交易日", fontsize=10)

    for ti, tl in enumerate(tom_levels):
        j_data = jaccard_intra.get(tl, {})
        n_data = ncd_intra.get(tl, {})
        _plot_pair(axes[ti], j_data, n_data,
                   f"{_DISPLAY.get(tl, tl)} 组内")

    _plot_pair(axes[-1], jaccard_inter, ncd_inter, "全体")
    axes[0].set_ylabel("相似度", fontsize=10)

    fig.suptitle(f"字符级推理同质性 — {label}", fontsize=13, y=1.02)
    os.makedirs(output_dir, exist_ok=True)
    safe = label.replace("/", "_").replace(" ", "_")
    png_path = os.path.join(output_dir, f"推理同质性_字符级_{safe}.png")
    fig.tight_layout()
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表: {png_path}")
    return png_path


def plot_multi_compare(all_jaccard, all_ncd, labels, output_dir):
    """多实验对比：Jaccard 一行，NCD 一行"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    tom_levels = sorted(set(
        tl for ji, _ in all_jaccard for tl in ji.keys()
    ))
    _DISPLAY = {"tom1": "ToM-1", "tom2_r1": "ToM-2 一阶", "tom2_r2": "ToM-2 二阶"}
    n_cols = len(tom_levels) + 1
    fig, axes = plt.subplots(2, n_cols, figsize=(6 * n_cols, 9), sharey=True)

    linestyles = ["-", "--", "-.", ":"]
    colors_run = ["#2196F3", "#FF9800", "#E91E63", "#4CAF50", "#9C27B0"]

    def _plot_line(ax, data_dict, lbl, ri):
        days = sorted(data_dict.keys())
        vals = [data_dict[d] for d in days]
        valid = [(d, v) for d, v in zip(days, vals) if not np.isnan(v)]
        if not valid:
            return
        ds, vs = zip(*valid)
        ax.plot(ds, vs, label=lbl,
                color=colors_run[ri % len(colors_run)],
                linestyle=linestyles[ri % len(linestyles)],
                linewidth=1.5, alpha=0.85)

    # Row 0 = Jaccard
    for ti, tl in enumerate(tom_levels):
        ax = axes[0][ti]
        for ri, ((ji, jinter), lbl) in enumerate(zip(all_jaccard, labels)):
            if tl in ji:
                _plot_line(ax, ji[tl], lbl, ri)
        ax.set_title(f"{_DISPLAY.get(tl, tl)} Jaccard", fontsize=10)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(-0.05, 1.05)

    ax = axes[0][-1]
    for ri, ((ji, jinter), lbl) in enumerate(zip(all_jaccard, labels)):
        _plot_line(ax, jinter, lbl, ri)
    ax.set_title("全体 Jaccard", fontsize=10)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)

    # Row 1 = NCD
    for ti, tl in enumerate(tom_levels):
        ax = axes[1][ti]
        for ri, ((ni, ninter), lbl) in enumerate(zip(all_ncd, labels)):
            if tl in ni:
                _plot_line(ax, ni[tl], lbl, ri)
        ax.set_title(f"{_DISPLAY.get(tl, tl)} 1−NCD", fontsize=10)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(-0.05, 1.05)
        ax.set_xlabel("交易日", fontsize=9)

    ax = axes[1][-1]
    for ri, ((ni, ninter), lbl) in enumerate(zip(all_ncd, labels)):
        _plot_line(ax, ninter, lbl, ri)
    ax.set_title("全体 1−NCD", fontsize=10)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("交易日", fontsize=9)

    axes[0][0].set_ylabel("Jaccard 相似度", fontsize=10)
    axes[1][0].set_ylabel("1 − NCD 相似度", fontsize=10)

    fig.suptitle("字符级推理同质性对比", fontsize=13)
    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, "推理同质性_字符级_多实验对比.png")
    fig.tight_layout()
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  对比图: {png_path}")
    return png_path


# ── 主入口 ─────────────────────────────────────────────────────────
def main():
    args = parse_args()
    labels = [l.strip() for l in args.labels.split(",")] if args.labels else []
    while len(labels) < len(args.run_dirs):
        labels.append(Path(args.run_dirs[len(labels)]).name)

    all_jaccard = []  # [(intra, inter), ...]
    all_ncd     = []
    all_json    = []

    for rd, lbl in zip(args.run_dirs, labels):
        print(f"\n{'='*60}")
        print(f"处理: {lbl}  ({rd})")
        print(f"{'='*60}")

        day_tom_texts = load_decisions(rd, args.max_chars)

        # 方案 A
        ji, jinter = compute_jaccard_homogeneity(
            day_tom_texts, args.ngram, args.template_thresh)
        all_jaccard.append((ji, jinter))

        # 方案 B
        ni, ninter = compute_ncd_homogeneity(day_tom_texts)
        all_ncd.append((ni, ninter))

        # 单实验图
        plot_single_run(ji, jinter, ni, ninter, lbl, args.output_dir)

        # 汇总
        summary = {"label": lbl}
        for gk in sorted(set(list(ji.keys()) + list(ni.keys()))):
            j_vals = [v for v in ji.get(gk, {}).values() if not np.isnan(v)]
            n_vals = [v for v in ni.get(gk, {}).values() if not np.isnan(v)]
            if j_vals:
                summary[f"{gk}_jaccard_mean"] = round(np.mean(j_vals), 4)
                summary[f"{gk}_jaccard_std"]  = round(np.std(j_vals), 4)
            if n_vals:
                summary[f"{gk}_ncd_sim_mean"] = round(np.mean(n_vals), 4)
                summary[f"{gk}_ncd_sim_std"]  = round(np.std(n_vals), 4)

        j_all = [v for v in jinter.values() if not np.isnan(v)]
        n_all = [v for v in ninter.values() if not np.isnan(v)]
        if j_all:
            summary["all_jaccard_mean"] = round(np.mean(j_all), 4)
        if n_all:
            summary["all_ncd_sim_mean"] = round(np.mean(n_all), 4)
        all_json.append(summary)

        print(f"\n  汇总:")
        for k, v in summary.items():
            if k != "label":
                print(f"    {k}: {v}")

    # 多实验对比图
    if len(args.run_dirs) > 1:
        plot_multi_compare(all_jaccard, all_ncd, labels, args.output_dir)

    # JSON
    json_path = os.path.join(args.output_dir, "推理同质性_字符级_汇总.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_json, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 汇总: {json_path}")


if __name__ == "__main__":
    main()
