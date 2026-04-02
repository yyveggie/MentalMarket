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
    build_weighted_close_by_day,
    build_per_symbol_fit_curves,
    compute_overall,
    compute_symbol_metrics,
)
from metrics_plot_common import configure_chinese_font, ensure_output_dir, read_jsonl

configure_chinese_font()


def plot_real_vs_sim_curves(
    symbols: list[str],
    real_close_by_symbol_day: dict[str, dict[int, float]],
    sim_close: dict[str, dict[int, float]],
    max_day: int,
    output_path: Path,
    run_label: str = "",
) -> None:
    """为每只指数画真实 vs 模拟的归一化价格曲线（2×5 子图布局）。"""
    n = len(symbols)
    if n == 0:
        return
    ncols = min(5, n)
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 3.5 * nrows), dpi=140)
    if nrows == 1 and ncols == 1:
        axes = [[axes]]
    elif nrows == 1:
        axes = [list(axes)]
    elif ncols == 1:
        axes = [[ax] for ax in axes]
    else:
        axes = [list(row) for row in axes]

    for idx, symbol in enumerate(sorted(symbols)):
        r, c = divmod(idx, ncols)
        ax = axes[r][c]

        aligned = aligned_real_sim_with_day(symbol, real_close_by_symbol_day, sim_close, max_day)
        if len(aligned) < 2:
            ax.set_title(symbol)
            ax.text(0.5, 0.5, "No Data", ha="center", va="center", transform=ax.transAxes)
            continue

        days = [a[0] for a in aligned]
        real_prices = [a[1] for a in aligned]
        sim_prices = [a[2] for a in aligned]

        # 归一化为首日=100
        base_r = real_prices[0] if abs(real_prices[0]) > 1e-9 else 1.0
        base_s = sim_prices[0] if abs(sim_prices[0]) > 1e-9 else 1.0
        norm_r = [100.0 * p / base_r for p in real_prices]
        norm_s = [100.0 * p / base_s for p in sim_prices]

        ax.plot(days, norm_r, color="#888888", linewidth=1.5, label="Real")
        ax.plot(days, norm_s, color="#e6550d", linewidth=1.5, label="Sim", alpha=0.85)
        ax.set_title(symbol, fontsize=10)
        ax.grid(alpha=0.15)
        if idx == 0:
            ax.legend(fontsize=7, loc="best")

    # 隐藏多余子图
    for r in range(nrows):
        for c in range(ncols):
            if r * ncols + c >= n:
                axes[r][c].set_visible(False)

    title = "真实 vs 模拟 归一化价格曲线（首日=100）"
    if run_label:
        title += f"\n{run_label}"
    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _load_profile_weights(profile_csv_path: Path) -> dict[str, float] | None:
    """从 stock_profile.csv 加载市值权重并归一化，与 index_board 同口径。"""
    import csv

    if not profile_csv_path.exists():
        return None
    weights: dict[str, float] = {}
    try:
        with open(profile_csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                symbol = str(row.get("stock_id", "")).strip()
                w = float(row.get("weight", 0))
                if symbol and w > 0:
                    weights[symbol] = w
    except Exception:
        return None
    if not weights:
        return None
    total = sum(weights.values())
    return {s: w / total for s, w in weights.items()}


def plot_symbol_bars(symbol_metrics: dict[str, dict[str, Any]], output_path: Path) -> None:
    labels = sorted(symbol_metrics.keys())
    if not labels:
        return

    same_vals = [symbol_metrics[s].get("same_day_acc") or 0.0 for s in labels]
    fwd_vals = [symbol_metrics[s].get("forward1_acc") or 0.0 for s in labels]
    fit_vals = [symbol_metrics[s].get("fit_pct") or 0.0 for s in labels]
    rmse_vals = [symbol_metrics[s].get("rmse") or 0.0 for s in labels]
    r2_vals = [symbol_metrics[s].get("r_squared") or 0.0 for s in labels]

    x = list(range(len(labels)))
    w = 0.26

    fig, axes = plt.subplots(2, 1, figsize=(12, 10), dpi=140, gridspec_kw={"height_ratios": [3, 2]})

    ax = axes[0]
    ax.bar([i - w for i in x], same_vals, width=w, label="同日方向准确率", color="#3182bd")
    ax.bar(x, fwd_vals, width=w, label="前瞻1日方向代理准确率", color="#31a354")
    ax.bar([i + w for i in x], fit_vals, width=w, label="拟合度 (Pearson×100)", color="#e6550d")
    ax.set_ylim(0, 100)
    ax.set_ylabel("百分比")
    ax.set_title("各指数拟合度与准确率（严格口径）")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.grid(alpha=0.2, axis="y")
    ax.legend()

    ax2 = axes[1]
    w2 = 0.35
    bars_rmse = ax2.bar([i - w2 / 2 for i in x], rmse_vals, width=w2, label="RMSE", color="#756bb1")
    ax2_r2 = ax2.twinx()
    bars_r2 = ax2_r2.bar([i + w2 / 2 for i in x], r2_vals, width=w2, label="R2", color="#e7969c", alpha=0.85)
    ax2.set_ylabel("RMSE")
    ax2_r2.set_ylabel("R2 (Pearson r2)")
    ax2.set_title("各指数 RMSE 与 R2")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=30, ha="right")
    ax2.grid(alpha=0.2, axis="y")
    ax2.legend(handles=[bars_rmse, bars_r2], labels=["RMSE", "R2"], loc="upper right")

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
            ax.plot(days, fit_vals, label="大盘（加权合成）", color="#111111", linewidth=2.7)
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
    parser.add_argument(
        "--profile-csv",
        type=str,
        default="data/stock_profile.csv",
        help="stock_profile.csv for market-cap weights (used in broad index)",
    )
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
    run_label = run_dir.name  # e.g. 20260329_005147_tom07_tom12_tom21_预测拟合
    report_path = out_dir / f"拟合度报告_{run_label}.json"
    chart_path = out_dir / f"拟合度与准确率_{run_label}.png"

    curve_real_close_by_symbol_day = dict(real_close_by_symbol_day)
    curve_sim_close = dict(sim_close)
    curve_symbols = list(symbols)
    broad_curve_enabled = False

    if len(symbols) >= 2:
        profile_weights: dict[str, float] | None = None
        try:
            profile_weights = _load_profile_weights(resolve_existing_path(args.profile_csv, run_dir))
        except FileNotFoundError:
            pass
        broad_real = build_weighted_close_by_day(real_close_by_symbol_day, symbols, max_day, weights=profile_weights)
        broad_sim = build_weighted_close_by_day(sim_close, symbols, max_day, weights=profile_weights)
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

    # curves 和 curves_by_symbol 图已不再生成，只保留 JSON 用于下游分析
    curves_by_symbol = build_per_symbol_fit_curves(
        symbols=curve_symbols,
        real_close_by_symbol_day=curve_real_close_by_symbol_day,
        sim_close=curve_sim_close,
        max_day=max_day,
        rolling_window=max(5, int(args.rolling_window)),
    )

    curves_json_path = out_dir / f"拟合度曲线数据_{run_label}.json"
    curves_by_symbol_json_path = out_dir / f"拟合度分指数曲线数据_{run_label}.json"
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
            "broad_curve_definition": "market-cap weighted composite from stock_profile.csv (fallback: equal-weight)",
        },
        "overall": overall,
        "per_symbol": symbol_metrics,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if len(symbol_metrics) > 1:
        plot_symbol_bars(symbol_metrics, chart_path)

    # 真实 vs 模拟价格曲线对比图
    price_curves_path = out_dir / f"真实vs模拟价格曲线_{run_label}.png"
    plot_real_vs_sim_curves(
        symbols=symbols,
        real_close_by_symbol_day=real_close_by_symbol_day,
        sim_close=sim_close,
        max_day=max_day,
        output_path=price_curves_path,
        run_label=run_label,
    )

    print(json.dumps({
        "overall": overall,
        "report": str(report_path),
        "chart": str(chart_path) if len(symbol_metrics) > 1 else None,
        "price_curves": str(price_curves_path),
        "curves_json": str(curves_json_path),
        "curves_by_symbol_json": str(curves_by_symbol_json_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
