#!/usr/bin/env python3
"""价格发现质量评估脚本（双语说明）。

中文：
- 从 price_discovery 日志读取价格发现质量指标并按交易日绘图。
- 包含自相关、方差比、Amihud 非流动性与波动率等指标。

English:
- Loads price-discovery quality metrics from price_discovery logs and plots
    daily trajectories.
- Includes autocorrelation, variance ratio, Amihud illiquidity, and volatility.

运行示例:
- 项目根目录执行:
    python evaluation/plot_price_discovery_metrics.py runs/20260329_150251
- evaluation 目录执行:
    python plot_price_discovery_metrics.py ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from metrics_plot_common import (
    collect_symbols,
    configure_chinese_font,
    ensure_output_dir,
    group_last_row_by_day,
    read_jsonl,
    safe_float,
)

configure_chinese_font()


def extract_series(rows: list[dict], symbol: str) -> tuple[list[int], dict[str, list[float]]]:
    points = group_last_row_by_day(rows, symbol=symbol, day_key="trading_day", time_key="sim_time")

    days: list[int] = []
    metrics = {
        "autocorrelation_1": [],
        "variance_ratio_5": [],
        "amihud_illiquidity": [],
        "volatility": [],
    }

    for day, row in points:
        vals = {
            "autocorrelation_1": safe_float(row.get("autocorrelation_1")),
            "variance_ratio_5": safe_float(row.get("variance_ratio_5")),
            "amihud_illiquidity": safe_float(row.get("amihud_illiquidity")),
            "volatility": safe_float(row.get("volatility")),
        }
        if all(v is None for v in vals.values()):
            continue

        days.append(day)
        for k in metrics.keys():
            metrics[k].append(vals[k] if vals[k] is not None else 0.0)

    return days, metrics


def plot_symbol(symbol: str, days: list[int], metrics: dict[str, list[float]], out_path: Path) -> None:
    if len(days) < 2:
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True, dpi=140)
    ax = axes.ravel()

    style = {
        "autocorrelation_1": ("一阶自相关", "#3182bd"),
        "variance_ratio_5": ("方差比（5）", "#31a354"),
        "amihud_illiquidity": ("Amihud 非流动性", "#756bb1"),
        "volatility": ("波动率", "#e6550d"),
    }

    for i, key in enumerate(["autocorrelation_1", "variance_ratio_5", "amihud_illiquidity", "volatility"]):
        title, color = style[key]
        ax[i].plot(days, metrics[key], color=color, linewidth=1.7)
        ax[i].set_title(f"{symbol} {title}")
        ax[i].grid(alpha=0.2)
        ax[i].set_ylabel(title)

    ax[2].set_xlabel("交易日")
    ax[3].set_xlabel("交易日")

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot price-discovery metrics from price_discovery.jsonl")
    parser.add_argument("run_dir", type=str, help="Run directory path, e.g., runs/20260329_005147")
    parser.add_argument("--symbol", type=str, default="", help="Optional symbol; if omitted, all symbols are plotted")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    rows = read_jsonl(run_dir / "price_discovery.jsonl")
    if not rows:
        raise SystemExit(f"No price_discovery.jsonl data found in {run_dir}")

    symbols = collect_symbols(rows)
    if args.symbol:
        symbols = [args.symbol]

    out_dir = ensure_output_dir(run_dir, args.output_dir or None)

    created = 0
    for symbol in symbols:
        days, metrics = extract_series(rows, symbol)
        if len(days) < 2:
            continue
        out_path = out_dir / f"{symbol}_price_discovery.png"
        plot_symbol(symbol, days, metrics, out_path)
        created += 1

    print(f"Generated {created} charts in {out_dir}")


if __name__ == "__main__":
    main()
