#!/usr/bin/env python3
"""对比多个实验的大盘（broad_index）曲线。

运行示例:
    cd /Users/mushroom/Desktop/MentalMarket
    python evaluation/plot_broad_index_compare.py \
        runs/20260322_132820_tom0 \
        runs/20260322_231352_tom1 \
        runs/20260323_213251_tom2 \
        --labels "ToM0,ToM1,ToM2" --normalize
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from metrics_plot_common import configure_chinese_font, read_jsonl, safe_float, safe_int

configure_chinese_font()


def build_broad_index_series(run_dir: Path) -> tuple[list[int], list[float]]:
    rows = read_jsonl(run_dir / "broad_index.jsonl")
    by_day: dict[int, tuple[float, float]] = {}
    for row in rows:
        day = safe_int(row.get("trading_day"))
        value = safe_float(row.get("value"))
        tm = safe_float(row.get("sim_time"))
        if day is None or day <= 0 or value is None:
            continue
        t = tm if tm is not None else -1.0
        old = by_day.get(day)
        if old is None or t >= old[0]:
            by_day[day] = (t, value)
    days = sorted(by_day.keys())
    closes = [by_day[d][1] for d in days]
    return days, closes


def main() -> None:
    parser = argparse.ArgumentParser(description="对比多个实验的大盘曲线")
    parser.add_argument("run_dirs", nargs="+", type=str, help="实验目录路径列表")
    parser.add_argument("--labels", type=str, default="", help="逗号分隔的自定义标签")
    parser.add_argument("--output", type=str, default="output/broad_index_compare.png", help="输出文件路径")
    parser.add_argument("--normalize", action="store_true", help="归一化为首日=100")
    args = parser.parse_args()

    labels = [l.strip() for l in args.labels.split(",")] if args.labels else []
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 6), dpi=140)

    for i, run_path in enumerate(args.run_dirs):
        run_dir = Path(run_path)
        days, closes = build_broad_index_series(run_dir)
        if len(days) < 2:
            print(f"跳过 {run_dir}: 数据不足")
            continue

        if args.normalize and closes[0] > 0:
            base = closes[0]
            closes = [c / base * 100 for c in closes]

        label = labels[i] if i < len(labels) else run_dir.name
        color = colors[i % len(colors)]
        ax.plot(days, closes, color=color, linewidth=1.8, label=label, alpha=0.9)

    ax.set_title("大盘曲线对比（Broad Market Index）", fontsize=14)
    ax.set_xlabel("交易日", fontsize=12)
    ax.set_ylabel("归一化指数 (首日=100)" if args.normalize else "指数值", fontsize=12)
    # 纵轴自动留出适当余量
    ax.margins(y=0.08)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=11)

    fig.tight_layout()
    fig.savefig(str(out_path), bbox_inches="tight")
    pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(str(pdf_path), bbox_inches="tight")
    plt.close(fig)
    print(f"图表已保存到: {out_path}")
    print(f"PDF已保存到: {pdf_path}")


if __name__ == "__main__":
    main()
