#!/usr/bin/env python3
"""各实验 · 按心智层级的平均换手率对比柱状图。

数据源：runs/<exp>/behavioral_biases.jsonl 中的 turnover_rate 字段。
 - turnover_rate = daily_trade_notional / total_asset（日内累积、跨日重置）
 - 对每个 (agent_id, trading_day) 取最大值 ≈ 当日终盘换手率
 - 按 tom_level 聚合，计算每层级的平均日换手率与 95% bootstrap CI

图表样式对齐 evaluation/reasoning_homogeneity/plot_reasoning_post_consistency.py 的 plot_compare：
 - 分组柱状图，实验为 x 轴，ToM 层级用颜色区分
 - 误差条 = 95% bootstrap CI
 - 脚注说明数据来源与显著性符号
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RUNS_DIR = Path("/Users/mushroom/Desktop/MentalMarket/runs")
OUT_DIR = Path(__file__).parent
CACHE_FILE = OUT_DIR / "_turnover_cache.json"

# 实验目录与标签（与 reasoning_homogeneity 保持一致）
EXPERIMENTS = [
    ("ToM1", "ToM1"),
    ("ToM2", "ToM2"),
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


def compute_run(run_dir: Path) -> dict:
    """返回 {tom_level: [per (agent,day) daily_turnover_rate, ...]}"""
    fp = run_dir / "behavioral_biases.jsonl"
    if not fp.exists():
        return {}

    # (aid, day) -> (max_turnover, tom_level)
    daily_max: dict[tuple[int, int], tuple[float, int]] = {}
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            tr = r.get("turnover_rate")
            aid = r.get("agent_id")
            day = r.get("trading_day")
            tom = r.get("tom_level")
            if tr is None or aid is None or day is None or tom is None:
                continue
            key = (int(aid), int(day))
            prev = daily_max.get(key)
            if prev is None or tr > prev[0]:
                daily_max[key] = (float(tr), int(tom))

    by_tom: dict[int, list[float]] = defaultdict(list)
    for (aid, day), (tr, tom) in daily_max.items():
        by_tom[tom].append(tr)
    return {str(t): vs for t, vs in by_tom.items()}


def bootstrap_ci(vals: list[float], B: int = 500, seed: int = 42,
                 alpha: float = 0.05) -> tuple[float, float]:
    if not vals:
        return (float("nan"), float("nan"))
    if len(vals) < 2:
        m = float(np.mean(vals))
        return (m, m)
    rng = np.random.default_rng(seed)
    arr = np.asarray(vals, dtype=float)
    n = len(arr)
    estimates = np.empty(B)
    for i in range(B):
        idx = rng.integers(0, n, size=n)
        estimates[i] = float(arr[idx].mean())
    lo = float(np.quantile(estimates, alpha / 2))
    hi = float(np.quantile(estimates, 1 - alpha / 2))
    return (lo, hi)


def load_or_compute(force: bool = False) -> dict:
    """返回 {run_name: {tom_str: [turnover_rates]}}。缓存避免重复解析。"""
    if CACHE_FILE.exists() and not force:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if all(name in cached for name, _ in EXPERIMENTS):
                return cached
        except Exception:
            pass

    result = {}
    for name, label in EXPERIMENTS:
        print(f"  解析 {name} ...", flush=True)
        result[name] = compute_run(RUNS_DIR / name)

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"  缓存已写入: {CACHE_FILE}")
    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/2] 计算每个实验的 per-ToM 日均换手率（首次运行较慢）...")
    raw = load_or_compute()

    # 汇总统计
    summary = {}  # exp_name -> tom -> (mean, lo, hi, n)
    for name, _ in EXPERIMENTS:
        by_tom = raw.get(name, {})
        per_tom = {}
        for t in TOM_LEVELS:
            vals = by_tom.get(str(t), [])
            if vals:
                m = float(np.mean(vals))
                lo, hi = bootstrap_ci(vals)
                per_tom[t] = (m, lo, hi, len(vals))
        summary[name] = per_tom

    # 打印结果
    print("\n[2/2] 结果:")
    print(f"{'实验':<26} {'ToM0':>20} {'ToM1':>20} {'ToM2':>20}")
    print("-" * 90)
    for name, label in EXPERIMENTS:
        row = [f"{label:<26}"]
        for t in TOM_LEVELS:
            if t in summary[name]:
                m, lo, hi, n = summary[name][t]
                row.append(f"{m:.4f}[{lo:.4f},{hi:.4f}]")
            else:
                row.append("—")
        print(f"{row[0]} {row[1]:>20} {row[2]:>20} {row[3]:>20}")

    # ── 绘图 ────────────────────────────────────────────────
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    n_exp = len(EXPERIMENTS)
    n_groups = len(TOM_LEVELS)
    x_base = np.arange(n_exp)
    width = 0.75 / n_groups

    fig, ax = plt.subplots(figsize=(13, 6))

    for gi, t in enumerate(TOM_LEVELS):
        means, ci_lo, ci_hi = [], [], []
        for name, _ in EXPERIMENTS:
            s = summary[name].get(t)
            if s is None:
                means.append(0.0); ci_lo.append(0.0); ci_hi.append(0.0)
            else:
                m, lo, hi, _ = s
                means.append(m)
                ci_lo.append(max(0.0, m - lo))
                ci_hi.append(max(0.0, hi - m))

        offset = (gi - (n_groups - 1) / 2) * width
        bar_x = x_base + offset
        c = COLORS[t]

        ax.bar(bar_x, means, width * 0.92,
               yerr=np.array([ci_lo, ci_hi]),
               color=c, alpha=0.85,
               edgecolor="black", linewidth=0.4,
               capsize=3, error_kw={"linewidth": 0.9, "ecolor": "#333"},
               label=LABELS[t], zorder=3)

    ax.set_xticks(x_base)
    ax.set_xticklabels([lb for _, lb in EXPERIMENTS],
                       fontsize=10, rotation=0)
    ax.set_xlabel("实验（ToM0 : ToM1 : ToM2 比例）", fontsize=11)
    ax.set_ylabel("日均换手率（daily_trade_notional / total_asset）", fontsize=11)
    ax.set_title("各实验 · 按心智层级的平均日换手率",
                 fontsize=13, pad=12)
    ax.grid(True, alpha=0.25, axis="y")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(bottom=0)

    ax.legend(fontsize=10, loc="upper right", framealpha=0.92)

    fig.text(0.5, 0.01,
             "柱高 = (agent, day) 日终换手率的均值；"
             "误差条 = 95% bootstrap CI；"
             "数据源 behavioral_biases.jsonl",
             ha="center", fontsize=8, color="#555")

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    out_png = OUT_DIR / "日均换手率_多实验对比.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n对比图: {out_png}")

    # 汇总 JSON
    out_json = OUT_DIR / "日均换手率_汇总.json"
    json_summary = {}
    for name, label in EXPERIMENTS:
        json_summary[label] = {}
        for t, (m, lo, hi, n) in summary[name].items():
            json_summary[label][f"ToM{t}"] = {
                "mean": round(m, 6),
                "ci_95": [round(lo, 6), round(hi, 6)],
                "n_agent_days": n,
            }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(json_summary, f, ensure_ascii=False, indent=2)
    print(f"汇总 JSON: {out_json}")


if __name__ == "__main__":
    main()
