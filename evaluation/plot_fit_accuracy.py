#!/usr/bin/env python3
"""拟合与预测准确率可视化与CLI入口（双语说明）。

中文：
- 用于评估单次实验结果与真实市场曲线之间的拟合程度与方向预测准确率。
- 输出总体指标、按标的对比图，以及按交易日变化的准确率/拟合度曲线。

English:
- Evaluates how well one simulation run fits real market curves and predicts
    return direction.
- Produces overall metrics, per-symbol comparison chart, and daily changing
    curves for accuracy and fit.

运行示例:
- 项目根目录执行:
    python evaluation/plot_fit_accuracy.py runs/20260329_150251
- evaluation 目录执行:
    python plot_fit_accuracy.py ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data_loader import (
    _build_nonseed_close_map,
    build_sim_close_by_day,
    load_closed_dates_from_calendar_news,
    load_real_curves,
    remap_sim_close_to_trading_days,
    resolve_calendar_news_file,
    resolve_existing_path,
    resolve_include_closed_days,
)
from metric_fit_accuracy import (
    BROAD_EQW_SYMBOL,
    DailyCurves,
    aligned_real_sim_with_day,
    build_daily_metric_curves,
    build_equal_weight_close_by_day,
    build_per_symbol_fit_curves,
    compute_overall,
    compute_symbol_metrics,
)
from metrics_plot_common import configure_chinese_font, ensure_output_dir, read_jsonl

configure_chinese_font()


def plot_symbol_bars(symbol_metrics: dict[str, dict[str, Any]], output_path: Path) -> None:
    labels = sorted(symbol_metrics.keys())
    if not labels:
        return

    same_vals = [symbol_metrics[s].get("same_day_acc") or 0.0 for s in labels]
    fwd_vals = [symbol_metrics[s].get("forward1_acc") or 0.0 for s in labels]
    fit_vals = [symbol_metrics[s].get("fit_pct") or 0.0 for s in labels]

    x = list(range(len(labels)))
    w = 0.26

    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=140)
    ax.bar([i - w for i in x], same_vals, width=w, label="同日方向准确率", color="#3182bd")
    ax.bar(x, fwd_vals, width=w, label="前瞻1日方向代理准确率", color="#31a354")
    ax.bar([i + w for i in x], fit_vals, width=w, label="拟合度", color="#e6550d")

    ax.set_ylim(0, 100)
    ax.set_ylabel("百分比")
    ax.set_title("各指数拟合度与准确率（严格口径）")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.grid(alpha=0.2, axis="y")
    ax.legend()

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_fit_curves_by_symbol(
    curves_by_symbol: dict[str, dict[str, list[int] | list[float | None]]],
    output_path: Path,
    overall_curve: DailyCurves | None = None,
) -> None:
    if not curves_by_symbol:
        return

    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=140)

    for symbol in sorted(curves_by_symbol.keys()):
        curve = curves_by_symbol[symbol]
        days_raw = curve.get("days", [])
        fit_raw = curve.get("fit_pct", [])
        if not isinstance(days_raw, list) or not isinstance(fit_raw, list):
            continue

        days = [int(x) for x in days_raw if isinstance(x, (int, float))]
        fit_vals = [float("nan") if x is None else float(x) for x in fit_raw]

        if symbol == BROAD_EQW_SYMBOL:
            ax.plot(days, fit_vals, label="大盘（等权合成）", color="#111111", linewidth=2.7)
        else:
            ax.plot(days, fit_vals, label=symbol, linewidth=1.15, alpha=0.82)

    if overall_curve is not None:
        odays = overall_curve["days"]
        ofit = [float("nan") if x is None else float(x) for x in overall_curve["fit_pct"]]
        ax.plot(odays, ofit, label="十指数聚合", color="#e6550d", linewidth=2.2, linestyle="--")

    ax.set_ylim(0, 100)
    ax.set_xlabel("交易日")
    ax.set_ylabel("拟合度（%）")
    ax.set_title("各指数与大盘拟合度变化曲线（严格口径）")
    ax.grid(alpha=0.2)
    ax.legend(loc="best", ncol=2, fontsize=9)

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_metric_curves(curves: DailyCurves, output_path: Path) -> None:
    days = curves["days"]
    same_day_acc = [float("nan") if x is None else float(x) for x in curves["same_day_acc"]]
    forward1_acc = [float("nan") if x is None else float(x) for x in curves["forward1_acc"]]
    fit_pct = [float("nan") if x is None else float(x) for x in curves["fit_pct"]]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8.4), sharex=True, dpi=140)

    ax1.plot(days, same_day_acc, label="同日方向准确率", color="#3182bd", linewidth=1.8)
    ax1.plot(days, forward1_acc, label="前瞻1日方向代理准确率", color="#31a354", linewidth=1.8)
    ax1.set_ylim(0, 100)
    ax1.set_ylabel("准确率（%）")
    ax1.set_title("十指数聚合准确率变化曲线（严格口径）")
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper left")

    ax2.plot(days, fit_pct, label="十指数聚合拟合度", color="#e6550d", linewidth=1.9)
    ax2.set_ylim(0, 100)
    ax2.set_xlabel("交易日")
    ax2.set_ylabel("拟合度（%）")
    ax2.set_title("十指数聚合拟合度变化曲线（严格口径）")
    ax2.grid(alpha=0.2)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate fit and prediction accuracy for a run directory")
    parser.add_argument("run_dir", type=str, help="Run directory path, e.g., runs/20260329_005147")
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json", help="Real curve file path")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory, default <run_dir>/figures")
    parser.add_argument("--symbol", type=str, default="", help="Optional single symbol evaluation")
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=20,
        help="Rolling window (days) for fit_pct curve",
    )
    parser.add_argument(
        "--include-closed-days",
        type=str,
        default="auto",
        choices=["auto", "true", "false"],
        help="Whether closed days participate in metrics; auto reads run_dir/config.yaml news_events_config.reopen_include_closed_days",
    )
    parser.add_argument("--exclude-seed", action="store_true", help="Exclude market-maker (seed) trades from close prices")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise SystemExit(f"Run directory not found: {run_dir}")

    snapshot_rows = read_jsonl(run_dir / "market_snapshots.jsonl")
    if not snapshot_rows:
        raise SystemExit(f"No market_snapshots.jsonl in {run_dir}")

    include_closed_days = resolve_include_closed_days(run_dir, args.include_closed_days)
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed_days else load_closed_dates_from_calendar_news(calendar_news_file)
    real_curve_path = resolve_existing_path(args.real_curves, run_dir)

    real_indices, real_close_by_symbol_day, calendar_dates, open_day_of_all_day = load_real_curves(
        real_curve_path,
        include_closed_days=include_closed_days,
        closed_dates_hint=closed_dates_hint,
    )
    sim_close_all = build_sim_close_by_day(
        snapshot_rows,
        nonseed_map=_build_nonseed_close_map(run_dir) if args.exclude_seed else None,
    )
    sim_close = remap_sim_close_to_trading_days(sim_close_all, open_day_of_all_day)

    max_sim_day = 0
    for dmap in sim_close.values():
        if dmap:
            max_sim_day = max(max_sim_day, max(dmap.keys()))
    max_day = min(len(calendar_dates), max_sim_day)
    if max_day < 3:
        raise SystemExit("Not enough aligned days to evaluate")

    symbols = sorted(set(real_close_by_symbol_day.keys()) & set(sim_close.keys()))
    if args.symbol:
        if args.symbol not in symbols:
            raise SystemExit(
                f"Symbol {args.symbol} not available in aligned real/sim data; available: {', '.join(symbols)}"
            )
        symbols = [args.symbol]

    if not symbols:
        raise SystemExit("No overlapping symbols between real curves and simulation snapshots")

    symbol_metrics: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        aligned = aligned_real_sim_with_day(symbol, real_close_by_symbol_day, sim_close, max_day)
        metric = compute_symbol_metrics(aligned)
        symbol_metrics[symbol] = metric

    overall = compute_overall(symbol_metrics)

    out_dir = ensure_output_dir(run_dir, args.output_dir or None)
    report_path = out_dir / "fit_accuracy_report.json"
    chart_path = out_dir / "fit_accuracy_by_symbol.png"
    curves_path = out_dir / "fit_accuracy_curves.png"
    curves_json_path = out_dir / "fit_accuracy_curves.json"
    curves_by_symbol_path = out_dir / "fit_accuracy_curves_by_symbol.png"
    curves_by_symbol_json_path = out_dir / "fit_accuracy_curves_by_symbol.json"

    curve_real_close_by_symbol_day = dict(real_close_by_symbol_day)
    curve_sim_close = dict(sim_close)
    curve_symbols = list(symbols)
    broad_curve_enabled = False

    if len(symbols) >= 2:
        broad_real = build_equal_weight_close_by_day(real_close_by_symbol_day, symbols, max_day)
        broad_sim = build_equal_weight_close_by_day(sim_close, symbols, max_day)
        if broad_real and broad_sim:
            curve_real_close_by_symbol_day[BROAD_EQW_SYMBOL] = broad_real
            curve_sim_close[BROAD_EQW_SYMBOL] = broad_sim
            curve_symbols.append(BROAD_EQW_SYMBOL)
            broad_curve_enabled = True

    curves = build_daily_metric_curves(
        symbols=symbols,
        real_close_by_symbol_day=real_close_by_symbol_day,
        sim_close=sim_close,
        max_day=max_day,
        rolling_window=max(5, int(args.rolling_window)),
    )

    curves_by_symbol = build_per_symbol_fit_curves(
        symbols=curve_symbols,
        real_close_by_symbol_day=curve_real_close_by_symbol_day,
        sim_close=curve_sim_close,
        max_day=max_day,
        rolling_window=max(5, int(args.rolling_window)),
    )

    plot_metric_curves(curves, curves_path)
    plot_fit_curves_by_symbol(curves_by_symbol, curves_by_symbol_path, overall_curve=curves)
    curves_json_path.write_text(json.dumps(curves, ensure_ascii=False, indent=2), encoding="utf-8")
    curves_by_symbol_json_path.write_text(json.dumps(curves_by_symbol, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "run_dir": str(run_dir),
        "real_curve_file": str(real_curve_path),
        "max_day_used": max_day,
        "alignment_policy": {
            "calendar_source": (
                "union of all real-index dates (include closed days)"
                if include_closed_days
                else "union of all real-index dates -> trading-day calendar (closed days removed)"
            ),
            "pairing": (
                "strict real/sim intersection on all-day index"
                if include_closed_days
                else "strict real/sim intersection on trading-day index"
            ),
            "closed_day_excluded": not include_closed_days,
            "include_closed_days": include_closed_days,
            "closed_dates_hint_count": len(closed_dates_hint),
            "calendar_news_file": str(calendar_news_file) if calendar_news_file else None,
            "forward_fill_sim_on_missing_day": False,
            "return_pair_rule": "only consecutive day pairs (d and d-1)",
            "forward1_rule": "proxy sign(sim_return_{t-1}) vs sign(real_return_t) on consecutive d-2,d-1,d",
        },
        "curve_scope": {
            "fit_accuracy_curves_png": "aggregated over selected symbols",
            "fit_accuracy_curves_by_symbol_png": "per symbol fit curves + synthetic broad index curve",
            "broad_curve_enabled": broad_curve_enabled,
            "broad_curve_definition": "equal-weight composite from selected symbols in real and simulation",
        },
        "overall": overall,
        "per_symbol": symbol_metrics,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if len(symbol_metrics) > 1:
        plot_symbol_bars(symbol_metrics, chart_path)

    print(json.dumps({
        "overall": overall,
        "report": str(report_path),
        "chart": str(chart_path) if len(symbol_metrics) > 1 else None,
        "curves_chart": str(curves_path),
        "curves_json": str(curves_json_path),
        "curves_by_symbol_chart": str(curves_by_symbol_path),
        "curves_by_symbol_json": str(curves_by_symbol_json_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
