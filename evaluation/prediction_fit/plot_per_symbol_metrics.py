#!/usr/bin/env python3
"""逐指数预测准确率与拟合度可视化。

自动读取 prediction_fit/ 下所有拟合度报告 JSON，
为每个指标生成热力图（行=指数，列=实验），以及分组柱状图。

运行：
    cd evaluation/prediction_fit
    python plot_per_symbol_metrics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from metrics_plot_common import configure_chinese_font

configure_chinese_font()

HERE = Path(__file__).resolve().parent

# ──────── 指标定义 ────────
METRICS = [
    ("same_day_acc", "同日方向准确率 (%)"),
    ("forward1_acc", "前一日预测准确率 (%)"),
    ("fit_pct", "Pearson 拟合度 (%)"),
    ("rmse", "RMSE"),
    ("r_squared", "R-squared"),
]


def _short_label(name: str) -> str:
    """缩短实验名：去掉 _预测拟合 后缀。"""
    return name.replace("_预测拟合", "")


def load_reports() -> list[tuple[str, dict]]:
    """加载当前目录下所有拟合度报告 JSON。"""
    reports = []
    for f in sorted(HERE.glob("拟合度报告_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        label = f.stem.replace("拟合度报告_", "")
        reports.append((label, data))
    if not reports:
        raise SystemExit("未找到拟合度报告 JSON 文件")
    return reports


def plot_heatmaps(reports: list[tuple[str, dict]]) -> Path:
    """为每个指标生成热力图（行=指数，列=实验），拼成一张大图。"""
    labels = [_short_label(r[0]) for r in reports]
    # 收集所有指数（排除 __BROAD_EQW__）
    all_symbols: set[str] = set()
    for _, data in reports:
        all_symbols.update(s for s in data.get("per_symbol", {}) if not s.startswith("__"))
    symbols = sorted(all_symbols)
    if not symbols:
        raise SystemExit("没有逐指数数据")

    n_metrics = len(METRICS)
    fig, axes = plt.subplots(1, n_metrics, figsize=(4.8 * n_metrics, 0.5 * len(symbols) + 2.5), dpi=140)
    if n_metrics == 1:
        axes = [axes]

    for ax, (key, title) in zip(axes, METRICS):
        matrix = np.full((len(symbols), len(reports)), np.nan)
        for j, (_, data) in enumerate(reports):
            ps = data.get("per_symbol", {})
            for i, sym in enumerate(symbols):
                val = ps.get(sym, {}).get(key)
                if val is not None:
                    matrix[i, j] = val

        vmin = np.nanmin(matrix) if not np.all(np.isnan(matrix)) else 0
        vmax = np.nanmax(matrix) if not np.all(np.isnan(matrix)) else 1
        im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn", vmin=vmin, vmax=vmax)

        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        ax.set_yticks(range(len(symbols)))
        ax.set_yticklabels(symbols, fontsize=9)
        ax.set_title(title, fontsize=11, pad=8)

        # 标注数值
        for i in range(len(symbols)):
            for j in range(len(reports)):
                v = matrix[i, j]
                if np.isnan(v):
                    continue
                fmt = f"{v:.1f}" if abs(v) >= 1 else f"{v:.3f}"
                ax.text(j, i, fmt, ha="center", va="center", fontsize=7,
                        color="white" if (v - vmin) / max(vmax - vmin, 1e-9) < 0.35 else "black")

        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    fig.suptitle("逐指数预测准确率与拟合度热力图", fontsize=14, y=1.02)
    fig.tight_layout()
    out = HERE / "逐指数拟合热力图.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_grouped_bars(reports: list[tuple[str, dict]]) -> Path:
    """分组柱状图：每个指数一组柱子，不同实验不同颜色。"""
    labels = [_short_label(r[0]) for r in reports]
    all_symbols: set[str] = set()
    for _, data in reports:
        all_symbols.update(s for s in data.get("per_symbol", {}) if not s.startswith("__"))
    symbols = sorted(all_symbols)

    # 选 3 个关键指标画柱状图
    bar_metrics = [
        ("same_day_acc", "同日方向准确率 (%)"),
        ("fit_pct", "Pearson 拟合度 (%)"),
        ("r_squared", "R-squared"),
    ]

    n_metrics = len(bar_metrics)
    fig, axes = plt.subplots(n_metrics, 1, figsize=(max(10, len(symbols) * 1.2), 3.5 * n_metrics), dpi=140)
    if n_metrics == 1:
        axes = [axes]

    colors = plt.cm.Set2(np.linspace(0, 1, max(len(reports), 3)))
    x = np.arange(len(symbols))
    width = 0.8 / len(reports)

    for ax, (key, title) in zip(axes, bar_metrics):
        for j, (_, data) in enumerate(reports):
            vals = []
            ps = data.get("per_symbol", {})
            for sym in symbols:
                v = ps.get(sym, {}).get(key)
                vals.append(v if v is not None else 0)
            offset = (j - len(reports) / 2 + 0.5) * width
            ax.bar(x + offset, vals, width, label=labels[j], color=colors[j])

        ax.set_xticks(x)
        ax.set_xticklabels(symbols, fontsize=9)
        ax.set_ylabel(title, fontsize=10)
        ax.set_title(title, fontsize=11)
        ax.legend(fontsize=8, loc="best")
        ax.grid(axis="y", alpha=0.2)

        # 50% 参考线（方向准确率）
        if "acc" in key:
            ax.axhline(50, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    fig.suptitle("逐指数关键指标分组柱状图", fontsize=14, y=1.01)
    fig.tight_layout()
    out = HERE / "逐指数拟合柱状图.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    reports = load_reports()
    print(f"读取到 {len(reports)} 个实验报告")

    hm = plot_heatmaps(reports)
    print(f"热力图: {hm}")

    bar = plot_grouped_bars(reports)
    print(f"柱状图: {bar}")


if __name__ == "__main__":
    main()
