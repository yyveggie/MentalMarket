#!/usr/bin/env python3
"""损失厌恶排序图（方案 A：筛选有效交易样本）。

数据重建流程：
 1. 从 trades.jsonl 重建每 agent 的已实现盈亏幅度列表
 2. 筛除交易退化样本：n_gain<3 或 avg_gain<1%
 3. 剩余 agent 计算 λ̂ = avg|loss|/avg|gain|
 4. 按 ToM 层级池化所有实验，计算均值 + 95% bootstrap CI
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).parent
DATA_JSON = OUT_DIR / "损失厌恶排序_数据.json"

EXPERIMENTS = [
    ("ToM1", "纯 ToM1"),
    ("ToM2", "纯 ToM2"),
    ("ToM00_ToM11_ToM21", "0:1:1"),
    ("ToM01_ToM10_ToM21", "1:0:1"),
    ("ToM01_ToM11_ToM20", "1:1:0"),
    ("ToM01_ToM11_ToM21", "1:1:1"),
    ("ToM02_ToM11_ToM21", "2:1:1"),
    ("ToM02_ToM13_ToM23", "2:3:3"),
    ("ToM06_ToM13_ToM21", "6:3:1"),
    ("ToM07_ToM12_ToM21", "7:2:1"),
]

TOM_LEVELS = [0, 1, 2]
COLORS = {0: "#2196F3", 1: "#FF9800", 2: "#E53935"}
LABELS = {0: "ToM 0", 1: "ToM 1", 2: "ToM 2"}


def bootstrap_ci(vals: np.ndarray, B: int = 2000, seed: int = 42,
                 alpha: float = 0.05) -> tuple[float, float]:
    if len(vals) < 2:
        m = float(vals.mean()) if len(vals) else float("nan")
        return (m, m)
    rng = np.random.default_rng(seed)
    est = np.empty(B)
    n = len(vals)
    for i in range(B):
        est[i] = float(vals[rng.integers(0, n, n)].mean())
    return (float(np.quantile(est, alpha / 2)),
            float(np.quantile(est, 1 - alpha / 2)))


def compute_from_trades() -> tuple[dict, dict]:
    """重新从 trades.jsonl 计算。返回 (pooled, summary)。"""
    from _trades_loader import collect_filtered_lambdas

    pooled = {t: [] for t in TOM_LEVELS}
    count_stats = {t: {'total': 0, 'valid': 0} for t in TOM_LEVELS}

    print("从 trades.jsonl 重建并筛选 ...")
    for run_name, _ in EXPERIMENTS:
        print(f"  解析 {run_name} ...", flush=True)
        by_tom = collect_filtered_lambdas(run_name)
        for t in TOM_LEVELS:
            d = by_tom.get(t)
            if not d:
                continue
            pooled[t].extend(d['valid'])
            count_stats[t]['total'] += d['n_total']
            count_stats[t]['valid'] += d['n_valid']

    summary = {}
    for t in TOM_LEVELS:
        arr = np.asarray(pooled[t], dtype=float)
        if len(arr) == 0:
            summary[t] = {"mean": float('nan'), "lo": float('nan'),
                          "hi": float('nan'), "n": 0, **count_stats[t]}
            continue
        m = float(arr.mean())
        lo, hi = bootstrap_ci(arr)
        summary[t] = {"mean": m, "lo": lo, "hi": hi, "n": len(arr),
                      **count_stats[t]}
    return pooled, summary


def save_json(pooled: dict, summary: dict) -> None:
    payload = {
        "schema": "loss_aversion_ranking",
        "description": "按 ToM 池化所有实验的 λ̂ 均值与 95% bootstrap CI",
        "filter": {"min_gain_count": 3, "min_avg_gain_pct": 0.01},
        "experiments": [name for name, _ in EXPERIMENTS],
        "tom_levels": [
            {
                "tom": t,
                "label": LABELS[t],
                "mean": summary[t]["mean"],
                "ci_low": summary[t]["lo"],
                "ci_high": summary[t]["hi"],
                "n_valid": summary[t]["valid"],
                "n_total": summary[t]["total"],
                "valid_rate": (summary[t]["valid"] / summary[t]["total"])
                if summary[t]["total"] else None,
                "lambdas": pooled[t],
            }
            for t in TOM_LEVELS
        ],
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"绘图数据已写入: {DATA_JSON}")


def load_json() -> tuple[dict, dict]:
    """从已生成的 JSON 恢复 (pooled, summary)。"""
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        payload = json.load(f)
    pooled, summary = {}, {}
    for item in payload["tom_levels"]:
        t = int(item["tom"])
        pooled[t] = list(item.get("lambdas") or [])
        summary[t] = {
            "mean": item["mean"], "lo": item["ci_low"], "hi": item["ci_high"],
            "n": item["n_valid"],
            "valid": item["n_valid"], "total": item["n_total"],
        }
    return pooled, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="忽略缓存 JSON，重新从 trades.jsonl 计算")
    args = ap.parse_args()

    if DATA_JSON.exists() and not args.rebuild:
        print(f"从缓存 JSON 读取: {DATA_JSON}")
        pooled, summary = load_json()
    else:
        pooled, summary = compute_from_trades()
        save_json(pooled, summary)

    print("\n筛选后的池化结果（方案 A: n_gain≥3 且 avg_gain≥1%）:")
    print(f"{'ToM':<8}{'n_valid':>10}{'n_total':>10}{'有效率':>10}"
          f"{'mean':>12}{'95% CI':>24}")
    for t in TOM_LEVELS:
        s = summary[t]
        ci_str = f"[{s['lo']:.3f}, {s['hi']:.3f}]" if s['n'] else '-'
        rate = (s['valid']/s['total']*100) if s['total'] else 0
        print(f"{LABELS[t]:<8}{s['n']:>10}{s['total']:>10}{rate:>9.1f}%"
              f"{s['mean']:>12.3f}{ci_str:>24}")

    # ── 绘图 ─────────────────────────────────────────────────
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    fig, ax = plt.subplots(figsize=(7, 5), dpi=150)

    x = np.arange(len(TOM_LEVELS))
    means = [summary[t]["mean"] for t in TOM_LEVELS]
    lo_err = [summary[t]["mean"] - summary[t]["lo"] for t in TOM_LEVELS]
    hi_err = [summary[t]["hi"] - summary[t]["mean"] for t in TOM_LEVELS]
    bar_colors = [COLORS[t] for t in TOM_LEVELS]

    # 主柱子
    ax.bar(x, means, width=0.55,
           yerr=np.array([lo_err, hi_err]),
           color=bar_colors, alpha=0.85,
           edgecolor="black", linewidth=0.8,
           capsize=6, error_kw={"linewidth": 1.2, "ecolor": "#222"},
           zorder=3)

    # λ=1 中性参考线
    ax.axhline(1.0, color="#888", linewidth=1.0, linestyle="--",
               zorder=2, alpha=0.6)

    # 柱顶数值
    for i, t in enumerate(TOM_LEVELS):
        s = summary[t]
        ax.text(i, s["hi"] + 0.08, f"{s['mean']:.2f}",
                ha="center", va="bottom", fontsize=12,
                fontweight="bold", color="#222")

    # 轴设置：x 轴标签附带 valid/total 样本率
    ymax = max(summary[t]["hi"] for t in TOM_LEVELS)
    ax.set_xticks(x)
    xlabels = [
        f"{LABELS[t]}\n({summary[t]['valid']}/{summary[t]['total']})"
        for t in TOM_LEVELS
    ]
    ax.set_xticklabels(xlabels, fontsize=11)
    ax.set_ylabel("损失厌恶代理指标 λ̂", fontsize=11)
    ax.set_xlim(-0.6, 2.6)
    ax.set_ylim(0, ymax * 1.15)

    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    out_png = OUT_DIR / "损失厌恶排序.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\n排序图: {out_png}")


if __name__ == "__main__":
    main()
