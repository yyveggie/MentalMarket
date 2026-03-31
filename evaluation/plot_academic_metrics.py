#!/usr/bin/env python3
"""学术指标可视化与CLI入口（双语说明）。

中文：
- 生成厚尾指数、波动聚集、价格冲击（Kyle lambda）、财富不平等度等学术指标图表。

English:
- Generates academic metric charts: tail index, volatility clustering, Kyle lambda, wealth inequality.

运行示例:
- 项目根目录执行:
    python evaluation/plot_academic_metrics.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_academic_metrics.py --run-dir ../runs/20260329_150251
- 仅生成单一指标（例如厚尾）:
    python evaluation/plot_academic_metrics.py --run-dir runs/20260329_150251 --metric tail
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from academic_metrics_common import (
    compute_log_returns,
    latest_non_nan,
    load_reference_close_series,
    resolve_run_dir,
)
from metric_kyle_lambda import build_daily_kyle_lambda
from metric_tail_index import rolling_hill
from metric_volatility_clustering import rolling_acf
from metric_wealth_inequality import build_daily_inequality
from metrics_plot_common import configure_chinese_font, ensure_output_dir


def _plot_tail_metric(
    run_dir: Path,
    out_dir: Path,
    symbol: str,
    window: int,
    chart_name: str,
    exclude_seed: bool = False,
):
    import matplotlib.pyplot as plt

    days_close, closes = load_reference_close_series(run_dir, symbol, exclude_seed=exclude_seed)
    if len(closes) < window + 2:
        return {"error": "Not enough close series points for tail-index estimation"}

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

    chart_path = out_dir / chart_name
    summary_path = out_dir / f"{Path(chart_name).stem}_summary.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "symbol_for_returns": symbol if symbol else "__broad_index__",
        "rolling_window_days": window,
        "definition": {
            "estimator": "Hill estimator",
            "reference": "Hill (1975)",
            "formula": "alpha_hat = [ (1/k) * sum ln(X_(i)/X_(k+1)) ]^-1",
            "min_tail_samples": 20,
        },
        "latest_metrics": {
            "hill_alpha_pos": latest_non_nan(alpha_pos),
            "hill_alpha_neg": latest_non_nan(alpha_neg),
            "k_pos": k_pos[-1] if k_pos else None,
            "k_neg": k_neg[-1] if k_neg else None,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"chart": str(chart_path), "summary": str(summary_path)}


def _plot_volatility_metric(
    run_dir: Path,
    out_dir: Path,
    symbol: str,
    window: int,
    chart_name: str,
    exclude_seed: bool = False,
):
    import matplotlib.pyplot as plt

    days_close, closes = load_reference_close_series(run_dir, symbol, exclude_seed=exclude_seed)
    if len(closes) < window + 2:
        return {"error": "Not enough close series points for volatility clustering"}

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

    chart_path = out_dir / chart_name
    summary_path = out_dir / f"{Path(chart_name).stem}_summary.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "symbol_for_returns": symbol if symbol else "__broad_index__",
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
    return {"chart": str(chart_path), "summary": str(summary_path)}


def _plot_kyle_metric(
    run_dir: Path,
    out_dir: Path,
    min_kyle_points: int,
    chart_name: str,
):
    import matplotlib.pyplot as plt

    min_points = max(6, int(min_kyle_points))
    days, kyle_lambda, kyle_r2, kyle_n = build_daily_kyle_lambda(run_dir, min_points=min_points)
    if not days:
        return {"error": "No valid Kyle lambda points found in trades.jsonl"}

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

    chart_path = out_dir / chart_name
    summary_path = out_dir / f"{Path(chart_name).stem}_summary.json"
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
    return {"chart": str(chart_path), "summary": str(summary_path)}


def _plot_inequality_metric(
    run_dir: Path,
    out_dir: Path,
    tom_level: int,
    chart_name: str,
):
    import matplotlib.pyplot as plt

    tom_filter = tom_level if tom_level >= 0 else None
    days, gini, theil_t, top1_share, agent_n = build_daily_inequality(run_dir, tom_level=tom_filter)
    if not days:
        return {"error": "No valid daily wealth snapshots in agent_wealth.jsonl"}

    fig, ax = plt.subplots(1, 1, figsize=(12, 4.8), dpi=140)
    ax.plot(days, gini, label="Gini", linewidth=1.9, color="#bcbd22")
    ax.plot(days, theil_t, label="Theil-T", linewidth=1.9, color="#8c564b")
    ax.plot(days, top1_share, label="Top-1 share", linewidth=1.9, color="#e377c2")
    ax.set_xlabel("交易日")
    ax.set_ylabel("不平等度")
    title = "财富不平等指标"
    if tom_filter is not None:
        title += f"（ToM={tom_filter}）"
    ax.set_title(title)
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left")
    fig.tight_layout()

    suffix = f"_tom{tom_filter}" if tom_filter is not None else ""
    stem = Path(chart_name).stem + suffix
    chart_path = out_dir / f"{stem}{Path(chart_name).suffix or '.png'}"
    summary_path = out_dir / f"{stem}_summary.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "tom_level": tom_filter,
        "definition": {
            "gini": "Gini coefficient",
            "theil_t": "Theil-T index",
            "top1_share": "share of top 1% wealth",
            "reference": "Gini / Theil standard definitions",
        },
        "latest_metrics": {
            "gini": latest_non_nan(gini),
            "theil_t": latest_non_nan(theil_t),
            "top1_share": latest_non_nan(top1_share),
            "agent_n": agent_n[-1] if agent_n else None,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"chart": str(chart_path), "summary": str(summary_path)}


def main() -> None:
    """Direct entrypoint: generate one or all academic metric charts."""
    parser = argparse.ArgumentParser(description="Generate academic metric plots")
    parser.add_argument("run_dir", nargs="?", default="", help="Run directory path")
    parser.add_argument("--run-dir", dest="run_dir_opt", default="", help="Run directory path (optional named arg)")
    parser.add_argument(
        "--metric",
        type=str,
        default="all",
        choices=["all", "tail", "volatility", "kyle", "inequality"],
        help="Metric to generate: all/tail/volatility/kyle/inequality",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="",
        help="Return reference symbol from market_snapshots (default: broad_index value)",
    )
    parser.add_argument("--rolling-window", type=int, default=40, help="Rolling window (days)")
    parser.add_argument("--min-kyle-points", type=int, default=8, help="Min OLS points per symbol/day for Kyle")
    parser.add_argument("--tom-level", type=int, default=-1, help="If >=0, inequality only uses this ToM level")
    parser.add_argument("--exclude-seed", action="store_true", help="Exclude market-maker (seed) trades from close prices")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    parser.add_argument(
        "--chart-name",
        type=str,
        default="tail_index_metrics_from_common.png",
        help="Output chart filename (used when --metric=tail)",
    )
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")

    configure_chinese_font()
    run_dir = resolve_run_dir(args, parser)
    out_dir = ensure_output_dir(run_dir, args.output_dir or None)

    window = max(20, args.rolling_window)
    outputs: dict[str, dict[str, str]] = {}

    if args.metric in ("all", "tail"):
        chart_name = args.chart_name if args.metric == "tail" else "tail_index_metrics_from_common.png"
        outputs["tail"] = _plot_tail_metric(run_dir, out_dir, args.symbol, window, chart_name, exclude_seed=args.exclude_seed)

    if args.metric in ("all", "volatility"):
        outputs["volatility"] = _plot_volatility_metric(
            run_dir,
            out_dir,
            args.symbol,
            window,
            "volatility_clustering_metrics_from_common.png",
            exclude_seed=args.exclude_seed,
        )

    if args.metric in ("all", "kyle"):
        outputs["kyle"] = _plot_kyle_metric(
            run_dir,
            out_dir,
            args.min_kyle_points,
            "kyle_lambda_metrics_from_common.png",
        )

    if args.metric in ("all", "inequality"):
        outputs["inequality"] = _plot_inequality_metric(
            run_dir,
            out_dir,
            args.tom_level,
            "wealth_inequality_metrics_from_common.png",
        )

    if args.metric != "all":
        single = outputs.get(args.metric, {})
        if "error" in single:
            raise SystemExit(single["error"])
        print(json.dumps(single, ensure_ascii=False, indent=2))
        return

    success = sum(1 for v in outputs.values() if "error" not in v)
    if success == 0:
        raise SystemExit("No metrics generated successfully")
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
