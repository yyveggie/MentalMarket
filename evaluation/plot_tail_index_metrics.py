#!/usr/bin/env python3
"""尾指数评估脚本（双语说明）。

中文：
- 基于 Hill 估计量计算并绘制收益率正尾与负尾的尾指数变化。
- 用于刻画收益分布厚尾特征与极端风险演化。

English:
- Computes and plots positive/negative return tail indices using the Hill
    estimator.
- Used to characterize heavy-tail behavior and the evolution of tail risk.

运行示例:
- 项目根目录执行:
    python evaluation/plot_tail_index_metrics.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_tail_index_metrics.py --run-dir ../runs/20260329_150251
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
from metric_tail_index import rolling_hill
from metrics_plot_common import configure_chinese_font, ensure_output_dir

configure_chinese_font()

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot Hill tail-index metrics (Hill 1975)")
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
        raise SystemExit("Not enough close series points for tail-index estimation")

    returns = compute_log_returns(closes)
    days, alpha_pos, alpha_neg, k_pos, k_neg = rolling_hill(days_close, returns, window)

    fig, ax = plt.subplots(1, 1, figsize=(12, 4.5), dpi=140)
    ax.plot(days, alpha_pos, label="Hill alpha (正尾)", color="#2ca02c", linewidth=1.8)
    ax.plot(days, alpha_neg, label="Hill alpha (负尾)", color="#ff7f0e", linewidth=1.8)
    ax.axhline(3.0, color="#999999", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_xlabel("交易日")
    ax.set_ylabel("尾指数 alpha")
    ax.set_title("厚尾指数（Hill 1975）")
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left")
    fig.tight_layout()

    chart_path = out_dir / "tail_index_metrics.png"
    summary_path = out_dir / "tail_index_summary.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "symbol_for_returns": args.symbol if args.symbol else "__broad_index__",
        "rolling_window_days": window,
        "definition": {
            "estimator": "Hill estimator",
            "reference": "Hill (1975)",
            "formula": "alpha_hat = [ (1/k) * sum ln(X_(i)/X_(k+1)) ]^-1",
        },
        "latest_metrics": {
            "hill_alpha_pos": latest_non_nan(alpha_pos),
            "hill_alpha_neg": latest_non_nan(alpha_neg),
            "k_pos": k_pos[-1] if k_pos else None,
            "k_neg": k_neg[-1] if k_neg else None,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"chart": str(chart_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
