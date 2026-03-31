#!/usr/bin/env python3
"""波动聚集评估脚本（双语说明）。

中文：
- 按 Cont (2001) 常用定义计算并绘制波动聚集相关指标。
- 主要输出 ACF(|r|,1) 与 ACF(r^2,1) 的日度变化。

English:
- Computes and plots volatility-clustering metrics using Cont (2001)
    definitions.
- Main outputs are daily ACF(|r|,1) and ACF(r^2,1) trajectories.

运行示例:
- 项目根目录执行:
    python evaluation/plot_volatility_clustering_metrics.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_volatility_clustering_metrics.py --run-dir ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from academic_metrics_common import (
    compute_log_returns,
    latest_non_nan,
    load_reference_close_series,
    resolve_run_dir,
)
from metric_volatility_clustering import rolling_acf
from metrics_plot_common import configure_chinese_font, ensure_output_dir

configure_chinese_font()

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot volatility clustering metrics (Cont 2001)")
    parser.add_argument("run_dir", nargs="?", default="", help="Run directory path")
    parser.add_argument("--run-dir", dest="run_dir_opt", default="", help="Run directory path (optional named arg)")
    parser.add_argument(
        "--symbol",
        type=str,
        default="",
        help="Return reference symbol from market_snapshots (default: broad_index value)",
    )
    parser.add_argument("--rolling-window", type=int, default=40, help="Rolling window (days)")
    parser.add_argument("--exclude-seed", action="store_true", help="Exclude market-maker (seed) trades from close prices")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    args = parser.parse_args()

    run_dir = resolve_run_dir(args, parser)
    out_dir = ensure_output_dir(run_dir, args.output_dir or None)

    days_close, closes = load_reference_close_series(run_dir, args.symbol, exclude_seed=args.exclude_seed)
    window = max(20, args.rolling_window)
    if len(closes) < window + 2:
        raise SystemExit("Not enough close series points for volatility clustering")

    returns = compute_log_returns(closes)
    days, ac_abs_1, ac_sq_1 = rolling_acf(days_close, returns, window)

    fig, ax = plt.subplots(1, 1, figsize=(12, 4.5), dpi=140)
    ax.plot(days, ac_abs_1, label="ACF(|r|,1)", color="#1f77b4", linewidth=1.8)
    ax.plot(days, ac_sq_1, label="ACF(r^2,1)", color="#d62728", linewidth=1.8)
    ax.axhline(0.0, color="#999999", linewidth=1.0, alpha=0.6)
    ax.set_xlabel("交易日")
    ax.set_ylabel("相关系数")
    ax.set_title("波动聚集指标（Cont 2001）")
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left")
    fig.tight_layout()

    chart_path = out_dir / "volatility_clustering_metrics.png"
    summary_path = out_dir / "volatility_clustering_summary.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "symbol_for_returns": args.symbol if args.symbol else "__broad_index__",
        "rolling_window_days": window,
        "definition": {
            "acf_abs_lag1": "ACF(|r_t|,1)",
            "acf_sq_lag1": "ACF(r_t^2,1)",
            "reference": "Cont (2001)",
        },
        "latest_metrics": {
            "acf_abs_lag1": latest_non_nan(ac_abs_1),
            "acf_sq_lag1": latest_non_nan(ac_sq_1),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"chart": str(chart_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
