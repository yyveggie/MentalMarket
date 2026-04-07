#!/usr/bin/env python3
"""
推理同质性分析（Reasoning Homogeneity via Embedding Similarity）

对指定实验目录的 decisions.jsonl，按交易日、按 ToM 层级分组，
计算同组所有智能体推理文本的 embedding pairwise cosine similarity，
生成「同质性指数」随交易日变化的时间序列图。

用法：
  # 单个实验
  python plot_reasoning_homogeneity.py runs/20260329_005147_tom07_tom12_tom21_预测拟合

  # 多个实验对比（生成单图 + 对比图）
  python plot_reasoning_homogeneity.py \
    runs/20260329_005147_tom07_tom12_tom21_预测拟合 \
    runs/20260329_150251_tom01_tom11_tom21_预测拟合 \
    runs/20260330_211929_tom06_tom13_tom21_预测拟合 \
    --labels "tom07/12/21,tom01/11/21,tom06/13/21"

  # 自定义 embedding 模型
  python plot_reasoning_homogeneity.py runs/xxx --model BAAI/bge-base-zh-v1.5

  # 自定义输出目录和批大小
  python plot_reasoning_homogeneity.py runs/xxx --output-dir my_output --batch-size 128

输出文件（在 --output-dir 下）：
  推理同质性_{label}.png          每个实验的 ToM 层级同质性时间序列
  推理同质性_多实验对比.png       多实验对比图（仅多实验时生成）
  推理同质性_汇总.json            所有实验汇总统计
"""

import argparse
import bisect
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# ── CLI ──────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="推理同质性分析")
    p.add_argument("run_dirs", nargs="+", help="实验目录")
    p.add_argument("--labels", default="", help="逗号分隔的实验标签")
    p.add_argument("--model", default="shibing624/text2vec-base-chinese",
                   help="sentence-transformers 模型名")
    p.add_argument("--batch-size", type=int, default=256, help="embedding 批大小")
    p.add_argument("--output-dir", default="output", help="输出目录")
    p.add_argument("--max-tokens", type=int, default=256,
                   help="每条推理文本截断到前 N 个字符（降低显存/内存）")
    return p.parse_args()


# ── 提取推理文本 ─────────────────────────────────────────────────────
def _extract_reasoning(llm_output: dict, tom_level: int) -> str:
    """
    根据 ToM 层级提取推理文本:
      - tom0: mental_reasoning（通常为占位符"(ToM0无需一阶心智推理)"）
      - tom1: mental_reasoning
      - tom2: tom1_reasoning + tom2_reasoning
    """
    if tom_level == 2:
        parts = []
        r1 = llm_output.get("tom1_reasoning", "")
        r2 = llm_output.get("tom2_reasoning", "")
        if r1: parts.append(r1)
        if r2: parts.append(r2)
        return "\n".join(parts) if parts else ""
    else:
        return llm_output.get("mental_reasoning", "")


# ── sim_time → trading_day 映射 ─────────────────────────────────────
def _build_time_to_day(run_dir: str) -> callable:
    """从 broad_index.jsonl 构建 sim_time → trading_day 的映射函数"""
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
        # 选更近的
        if abs(times[idx] - sim_time) < abs(times[idx - 1] - sim_time):
            return days[idx]
        return days[idx - 1]

    return mapper


# ── 加载 decisions ────────────────────────────────────────────────────
def load_decisions(run_dir: str, max_tokens: int):
    """
    返回:  { trading_day: { tom_level: [ text, ... ] } }
    """
    mapper = _build_time_to_day(run_dir)
    result = defaultdict(lambda: defaultdict(list))
    dec_path = os.path.join(run_dir, "decisions.jsonl")
    with open(dec_path) as f:
        for line in f:
            rec = json.loads(line)
            tl  = rec.get("tom_level", 0)
            out = rec.get("llm_output", {})
            text = _extract_reasoning(out, tl)
            if not text or text.startswith("(ToM0"):
                # tom0 的占位文本不做 embedding
                if tl == 0:
                    continue
                if not text:
                    continue
            text = text[:max_tokens]
            day  = mapper(rec["sim_time"])
            result[day][tl].append(text)
    return dict(result)


# ── Embedding + 同质性计算 ────────────────────────────────────────────
def compute_homogeneity(day_tom_texts: dict, model, batch_size: int):
    """
    对每天每 ToM 层级计算组内平均 pairwise cosine similarity（同质性指数）。
    同时计算跨 ToM 层级的相似度。

    返回:
      intra: { tom_level: { day: float } }   组内同质性
      inter: { day: float }                  全体同质性
    """
    # 收集所有文本和元数据
    all_texts = []
    meta = []  # (day, tom_level, idx_in_texts)
    for day in sorted(day_tom_texts.keys()):
        for tl in sorted(day_tom_texts[day].keys()):
            for txt in day_tom_texts[day][tl]:
                meta.append((day, tl, len(all_texts)))
                all_texts.append(txt)

    if not all_texts:
        return {}, {}

    print(f"  共 {len(all_texts)} 条推理文本，开始 embedding…")
    embeddings = model.encode(all_texts, batch_size=batch_size,
                              show_progress_bar=True, normalize_embeddings=True)
    # embeddings: (N, D), 已归一化 → cosine sim = dot product

    # 按 (day, tom_level) 分组
    from collections import defaultdict as dd
    groups = dd(list)      # (day, tl) -> [idx]
    day_all = dd(list)     # day -> [idx]
    for day, tl, idx in meta:
        groups[(day, tl)].append(idx)
        day_all[day].append(idx)

    def _mean_pairwise_sim(indices):
        if len(indices) < 2:
            return float("nan")
        vecs = embeddings[indices]  # (n, D)
        sim_mat = vecs @ vecs.T     # (n, n), 已归一化
        n = len(indices)
        # 取上三角（不含对角线）
        triu_sum = (sim_mat.sum() - n) / 2.0
        count = n * (n - 1) / 2.0
        return float(triu_sum / count)

    intra = defaultdict(dict)  # tom_level -> {day: sim}
    for (day, tl), indices in groups.items():
        intra[tl][day] = _mean_pairwise_sim(indices)

    inter = {}
    for day, indices in day_all.items():
        inter[day] = _mean_pairwise_sim(indices)

    return dict(intra), inter


# ── 绘图 ──────────────────────────────────────────────────────────────
def plot_single_run(intra, inter, label, output_dir):
    """为单个实验画同质性时间序列"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = {0: "#2196F3", 1: "#FF9800", 2: "#E91E63"}
    tom_labels = {0: "ToM-0", 1: "ToM-1", 2: "ToM-2"}

    for tl in sorted(intra.keys()):
        days = sorted(intra[tl].keys())
        vals = [intra[tl][d] for d in days]
        # 去掉 nan
        valid = [(d, v) for d, v in zip(days, vals) if not np.isnan(v)]
        if not valid:
            continue
        ds, vs = zip(*valid)
        ax.plot(ds, vs, label=tom_labels.get(tl, f"ToM-{tl}"),
                color=colors.get(tl, None), linewidth=1.5, alpha=0.85)

    # 全体
    days_all = sorted(inter.keys())
    vals_all = [inter[d] for d in days_all]
    valid_all = [(d, v) for d, v in zip(days_all, vals_all) if not np.isnan(v)]
    if valid_all:
        ds, vs = zip(*valid_all)
        ax.plot(ds, vs, label="全体", color="black", linewidth=2, linestyle="--", alpha=0.7)

    ax.set_xlabel("交易日", fontsize=12)
    ax.set_ylabel("平均 Pairwise 余弦相似度", fontsize=12)
    ax.set_title(f"推理同质性指数 — {label}", fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 1.05)

    os.makedirs(output_dir, exist_ok=True)
    safe = label.replace("/", "_").replace(" ", "_")
    png_path = os.path.join(output_dir, f"推理同质性_{safe}.png")
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    print(f"  图表: {png_path}")
    return png_path


def plot_multi_run_compare(all_results, labels, output_dir):
    """
    多实验对比图：每个 ToM 层级一个子图，各实验为不同线型。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    tom_levels = sorted(set(
        tl for intra, _ in all_results for tl in intra.keys()
    ))
    n_toms = len(tom_levels) + 1  # +1 for "全体"

    fig, axes = plt.subplots(1, n_toms, figsize=(6 * n_toms, 5), sharey=True)
    if n_toms == 1:
        axes = [axes]
    linestyles = ["-", "--", "-.", ":"]
    colors_run = ["#2196F3", "#FF9800", "#E91E63", "#4CAF50", "#9C27B0"]

    for ti, tl in enumerate(tom_levels):
        ax = axes[ti]
        for ri, ((intra, inter), lbl) in enumerate(zip(all_results, labels)):
            if tl not in intra:
                continue
            days = sorted(intra[tl].keys())
            vals = [intra[tl][d] for d in days]
            valid = [(d, v) for d, v in zip(days, vals) if not np.isnan(v)]
            if not valid:
                continue
            ds, vs = zip(*valid)
            ax.plot(ds, vs, label=lbl,
                    color=colors_run[ri % len(colors_run)],
                    linestyle=linestyles[ri % len(linestyles)],
                    linewidth=1.5, alpha=0.85)
        ax.set_title(f"ToM-{tl} 组内同质性", fontsize=12)
        ax.set_xlabel("交易日", fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 1.05)

    # 全体同质性
    ax = axes[-1]
    for ri, ((intra, inter), lbl) in enumerate(zip(all_results, labels)):
        days = sorted(inter.keys())
        vals = [inter[d] for d in days]
        valid = [(d, v) for d, v in zip(days, vals) if not np.isnan(v)]
        if not valid:
            continue
        ds, vs = zip(*valid)
        ax.plot(ds, vs, label=lbl,
                color=colors_run[ri % len(colors_run)],
                linestyle=linestyles[ri % len(linestyles)],
                linewidth=1.5, alpha=0.85)
    ax.set_title("全体同质性", fontsize=12)
    ax.set_xlabel("交易日", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 1.05)

    axes[0].set_ylabel("平均 Pairwise 余弦相似度", fontsize=10)

    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, "推理同质性_多实验对比.png")
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    print(f"  对比图: {png_path}")
    return png_path


# ── 主程序 ─────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    labels = [l.strip() for l in args.labels.split(",")] if args.labels else []
    while len(labels) < len(args.run_dirs):
        labels.append(Path(args.run_dirs[len(labels)]).name)

    # 加载模型
    print(f"加载模型: {args.model}")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.model)
    print(f"  模型维度: {model.get_sentence_embedding_dimension()}")

    all_results = []
    all_json = []
    for rd, lbl in zip(args.run_dirs, labels):
        print(f"\n{'='*60}")
        print(f"处理: {lbl}  ({rd})")
        print(f"{'='*60}")

        day_tom_texts = load_decisions(rd, args.max_tokens)
        intra, inter = compute_homogeneity(day_tom_texts, model, args.batch_size)
        all_results.append((intra, inter))

        # 单实验图
        plot_single_run(intra, inter, lbl, args.output_dir)

        # 汇总统计
        run_summary = {"label": lbl}
        for tl in sorted(intra.keys()):
            vals = [v for v in intra[tl].values() if not np.isnan(v)]
            if vals:
                run_summary[f"tom{tl}_mean"] = round(float(np.mean(vals)), 4)
                run_summary[f"tom{tl}_std"] = round(float(np.std(vals)), 4)
                run_summary[f"tom{tl}_min"] = round(float(np.min(vals)), 4)
                run_summary[f"tom{tl}_max"] = round(float(np.max(vals)), 4)
        inter_vals = [v for v in inter.values() if not np.isnan(v)]
        if inter_vals:
            run_summary["all_mean"] = round(float(np.mean(inter_vals)), 4)
            run_summary["all_std"]  = round(float(np.std(inter_vals)), 4)
        all_json.append(run_summary)

        print(f"\n  汇总:")
        for k, v in run_summary.items():
            if k != "label":
                print(f"    {k}: {v}")

    # 多实验对比图
    if len(args.run_dirs) > 1:
        plot_multi_run_compare(all_results, labels, args.output_dir)

    # JSON 结果
    json_path = os.path.join(args.output_dir, "推理同质性_汇总.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_json, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 汇总: {json_path}")


if __name__ == "__main__":
    main()
