#!/usr/bin/env python3
"""Kyle lambda 指标评估脚本（双语说明）。

中文：
- 按交易日估计并绘制价格冲击系数 Kyle lambda 及其回归质量指标。
- 使用模型 Delta p = lambda * q + epsilon 评估成交冲击强度。

English:
- Estimates and plots daily Kyle lambda and regression quality diagnostics.
- Uses the model Delta p = lambda * q + epsilon to measure price impact.

运行示例:
- 项目根目录执行:
    python evaluation/plot_kyle_lambda_metrics.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_kyle_lambda_metrics.py --run-dir ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from academic_metrics_common import latest_non_nan, resolve_run_dir
from metric_kyle_lambda import build_daily_kyle_lambda
from metrics_plot_common import configure_chinese_font, ensure_output_dir

configure_chinese_font()

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot Kyle lambda metrics (Kyle 1985)")
    parser.add_argument("run_dir", nargs="?", default="", help="Run directory path")
    parser.add_argument("--run-dir", dest="run_dir_opt", default="", help="Run directory path (optional named arg)")
    parser.add_argument("--min-kyle-points", type=int, default=8, help="Min OLS points per symbol/day")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    args = parser.parse_args()

    run_dir = resolve_run_dir(args, parser)
    out_dir = ensure_output_dir(run_dir, args.output_dir or None)

    min_points = max(6, args.min_kyle_points)
    days, kyle_lambda, kyle_r2, kyle_n = build_daily_kyle_lambda(run_dir, min_points=min_points)
    if not days:
        raise SystemExit("No valid Kyle lambda points found in trades.jsonl")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), dpi=140, sharex=True)

    ax1.plot(days, kyle_lambda, color="#9467bd", linewidth=2.0, label="Kyle lambda")
    ax1.axhline(0.0, color="#999999", linewidth=1.0, alpha=0.6)
    ax1.set_ylabel("lambda")
    ax1.set_title("价格冲击指标（Kyle 1985）")
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper left")

    ax2.plot(days, kyle_r2, color="#17becf", linewidth=1.8, label="OLS R2")
    ax2.plot(days, kyle_n, color="#7f7f7f", linewidth=1.6, label="样本点 n")
    ax2.set_xlabel("交易日")
    ax2.set_ylabel("R2 / n")
    ax2.grid(alpha=0.2)
    ax2.legend(loc="upper left")

    fig.tight_layout()

    chart_path = out_dir / "kyle_lambda_metrics.png"
    summary_path = out_dir / "kyle_lambda_summary.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "min_kyle_points": min_points,
        "definition": {
            "model": "Delta p_t = lambda * q_t + epsilon_t",
            "reference": "Kyle (1985)",
            "aggregation": "sample-size weighted across symbols",
        },
        "latest_metrics": {
            "kyle_lambda": latest_non_nan(kyle_lambda),
            "kyle_r2": latest_non_nan(kyle_r2),
            "kyle_n": kyle_n[-1] if kyle_n else None,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"chart": str(chart_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
