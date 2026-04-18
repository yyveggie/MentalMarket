#!/usr/bin/env python3
"""持仓分散度多实验对比图（主图：有效持仓数 / 副图：阈值敏感性）。

主图 `持仓分散度_多实验对比.png`:
 - X 轴: 10 个实验
 - 柱: 按 ToM 分组，高度 = 该层级 Agent 级 HHI 均值对应的有效持仓数 N_eff = 1/HHI
 - 误差条: 95% bootstrap CI（由 HHI 的 CI 反推到 N_eff）
 - 参考线: N_eff = 10（等权分散上限） / N_eff = 2（典型集中）

副图 `持仓分散度_阈值敏感性.png`:
 - X 轴: HHI 阈值 (0.2 ~ 0.6)
 - Y 轴: Agent 级触发率 %
 - 每条 ToM 一条线，按实验做小多图（grid）

数据来源: 持仓分散度_汇总.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).parent
DATA_JSON = OUT_DIR / "持仓分散度_汇总.json"
PNG_MAIN = OUT_DIR / "持仓分散度_多实验对比.png"
PNG_THR = OUT_DIR / "持仓分散度_阈值敏感性.png"

# 对齐 evaluation/reasoning_homogeneity 的配色
TOM_COLORS = {"0": "#2196F3", "1": "#FF9800", "2": "#E53935"}
TOM_LABELS = {"0": "ToM 0", "1": "ToM 1", "2": "ToM 2"}


def load_or_compute() -> dict:
    if not DATA_JSON.exists():
        subprocess.run(
            [sys.executable, str(OUT_DIR / "compute_underdiversification.py")],
            check=True,
        )
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def plot_main(data: dict) -> None:
    entries = data["experiments"]
    labels = [e["label"] for e in entries]

    toms_present: list[str] = []
    for e in entries:
        for t in e["by_tom"].keys():
            if t not in toms_present:
                toms_present.append(t)
    toms_present.sort()

    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "Arial Unicode MS", "STHeiti",
            "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    fig, ax = plt.subplots(figsize=(13, 6))

    n_exp = len(entries)
    n_tom = len(toms_present)
    width = 0.75 / max(n_tom, 1)
    x_base = np.arange(n_exp)

    for i, tom in enumerate(toms_present):
        heights, lower_err, upper_err = [], [], []
        for e in entries:
            slot = e["by_tom"].get(tom)
            if slot and slot["mean_hhi"] is not None:
                m = slot["mean_hhi"]
                lo, hi = slot["ci95"]
                # N_eff = 1/HHI；CI 翻转（HHI 越大 N_eff 越小）
                ne = 1.0 / m
                ne_hi = 1.0 / lo
                ne_lo = 1.0 / hi
                heights.append(ne)
                lower_err.append(ne - ne_lo)
                upper_err.append(ne_hi - ne)
            else:
                heights.append(np.nan)
                lower_err.append(0)
                upper_err.append(0)
        offset = (i - (n_tom - 1) / 2) * width
        bar_x = x_base + offset
        ax.bar(bar_x, heights, width * 0.92,
               yerr=np.array([lower_err, upper_err]),
               color=TOM_COLORS[tom], alpha=0.85,
               edgecolor="black", linewidth=0.4,
               capsize=3, error_kw={"linewidth": 0.9, "ecolor": "#333"},
               label=TOM_LABELS[tom], zorder=3)

    # 参考线：等权分散上限 N_eff = N
    n_tradable = entries[0].get("n_tradable", 10)
    ax.axhline(n_tradable, color="#999", linestyle="--", linewidth=0.9,
               zorder=0, alpha=0.7)
    ax.text(-0.5, n_tradable + 0.08, f"等权分散上限 N={n_tradable}",
            fontsize=9, color="#666", ha="left", va="bottom")

    ax.set_xticks(x_base)
    ax.set_xticklabels(labels, fontsize=10, rotation=0)
    ax.set_xlabel("实验（ToM0 : ToM1 : ToM2 比例）", fontsize=11)
    ax.set_ylabel("有效持仓数  $N_{eff}=1/HHI$", fontsize=11)
    ax.set_title("各实验 · 心智层级持仓分散度", fontsize=13, pad=12)

    ax.grid(True, alpha=0.25, axis="y")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(0, n_tradable * 1.08)
    ax.legend(fontsize=9, loc="upper right", framealpha=0.92)
    ax.set_xlim(-0.6, n_exp - 0.4)

    fig.text(0.5, 0.01,
             "柱高 = Agent 级 $N_{eff}=1/\\overline{HHI}$（每 Agent 时均 HHI → 跨 Agent 平均）；"
             "误差条 = 95% bootstrap CI；"
             "剔除预热期 day<3；空仓事件排除",
             ha="center", fontsize=8, color="#555")

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(PNG_MAIN, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"主图: {PNG_MAIN}")


def plot_threshold_sensitivity(data: dict) -> None:
    entries = data["experiments"]
    thresholds = sorted(
        float(t) for t in next(iter(entries[0]["by_tom_threshold_pct"].values())).keys()
    )

    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    n = len(entries)
    cols = 5
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.6 * rows),
                             dpi=150, sharey=True)
    axes = axes.flatten()

    for idx, entry in enumerate(entries):
        ax = axes[idx]
        for tom, d in entry["by_tom_threshold_pct"].items():
            ys = [d.get(str(t)) for t in thresholds]
            ys = [np.nan if v is None else v for v in ys]
            ax.plot(thresholds, ys, marker="o", markersize=4,
                    color=TOM_COLORS.get(tom, "#555"),
                    label=TOM_LABELS.get(tom, f"ToM{tom}"),
                    linewidth=1.5)
        ax.axvline(0.5, color="#aaa", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.set_title(entry["label"], fontsize=10)
        ax.set_xlim(min(thresholds) - 0.02, max(thresholds) + 0.02)
        ax.set_ylim(0, 100)
        ax.grid(True, linestyle="--", alpha=0.3)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if idx % cols == 0:
            ax.set_ylabel("触发率 %", fontsize=9)
        if idx // cols == rows - 1 or idx + cols >= n:
            ax.set_xlabel("HHI 阈值", fontsize=9)

    for k in range(n, len(axes)):
        axes[k].axis("off")

    axes[0].legend(fontsize=8, loc="upper right", framealpha=0.85)
    fig.suptitle(
        "持仓分散度 · 阈值敏感性（Agent 级触发率 vs HHI 阈值）"
        "\n虚线 = 当前默认阈值 0.5",
        fontsize=12.5, y=1.005,
    )
    plt.tight_layout()
    fig.savefig(PNG_THR, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"副图: {PNG_THR}")


def main():
    data = load_or_compute()
    plot_main(data)
    plot_threshold_sensitivity(data)


if __name__ == "__main__":
    main()
