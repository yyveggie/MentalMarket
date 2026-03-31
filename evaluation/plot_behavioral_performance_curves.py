#!/usr/bin/env python3
"""行为绩效曲线评估脚本（双语说明）。

中文：
- 基于 behavioral_biases 日志按交易日评估行为与绩效关系。
- 输出收益率、收益方差、夏普、最大回撤等绩效指标变化曲线。

English:
- Evaluates daily behavioral-performance relationships from behavioral_biases
    logs.
- Produces time-series curves for return, variance, Sharpe, max drawdown, and
    related performance indicators.

运行示例:
- 项目根目录执行:
    python evaluation/plot_behavioral_performance_curves.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_behavioral_performance_curves.py --run-dir ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
import json
from statistics import median
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from academic_metrics_common import resolve_run_dir
from metrics_plot_common import configure_chinese_font, ensure_output_dir, read_jsonl, safe_float, safe_int

configure_chinese_font()

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot behavioral performance curves by trading day")
    parser.add_argument("run_dir", nargs="?", default="", help="Run directory path")
    parser.add_argument("--run-dir", dest="run_dir_opt", default="", help="Run directory path (optional named arg)")
    parser.add_argument("--tom-level", type=int, default=-1, help="Filter by tom_level; -1 means all")
    parser.add_argument(
        "--bias-file",
        type=str,
        default="behavioral_biases.jsonl",
        help="Behavioral bias filename under run_dir (e.g., behavioral_biases_v2.jsonl)",
    )
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    args = parser.parse_args()

    run_dir = resolve_run_dir(args, parser)
    rows = read_jsonl(run_dir / args.bias_file)
    if not rows:
        raise SystemExit(f"No {args.bias_file} data found in {run_dir}")

    by_day_agent_last: dict[int, dict[int, tuple[float, dict[str, Any]]]] = {}
    by_day_realized: dict[int, dict[str, float]] = {}
    for row in rows:
        day = safe_int(row.get("trading_day"))
        if day is None or day <= 0:
            continue
        tom_level = safe_int(row.get("tom_level"))
        if args.tom_level >= 0 and tom_level != args.tom_level:
            continue

        aid = safe_int(row.get("agent_id"))
        sim_time = safe_float(row.get("sim_time"))
        if aid is not None:
            day_map = by_day_agent_last.setdefault(day, {})
            old = day_map.get(aid)
            t = sim_time if sim_time is not None else -1.0
            if old is None or t >= old[0]:
                day_map[aid] = (t, row)

        # 已实现盈亏幅度使用卖出事件口径聚合，避免把 0/1 事件计数误标为金额。
        slot_evt = by_day_realized.setdefault(day, {"gain_pct_sum": 0.0, "loss_pct_sum": 0.0})
        action = str(row.get("action", "")).strip().lower()
        status = str(row.get("status", "")).strip().lower()
        avg_buy = safe_float(row.get("avg_buy_price"))
        target = safe_float(row.get("target_price"))
        if action == "sell" and status == "ok" and avg_buy is not None and avg_buy > 0 and target is not None:
            pnl_pct = abs((target - avg_buy) / avg_buy * 100.0)
            if target > avg_buy:
                slot_evt["gain_pct_sum"] += pnl_pct
            elif target < avg_buy:
                slot_evt["loss_pct_sum"] += pnl_pct

    if not by_day_agent_last:
        raise SystemExit("No valid behavioral records after filtering")

    days = sorted(by_day_agent_last.keys())

    avg_ret: list[float] = []
    med_ret: list[float] = []
    win_rate: list[float] = []
    lose_rate: list[float] = []
    de_curve: list[float] = []
    pgr_curve: list[float] = []
    plr_curve: list[float] = []
    lambda_curve: list[float] = []
    gain_pct_curve: list[float] = []
    loss_pct_curve: list[float] = []
    agent_count_curve: list[int] = []

    for d in days:
        last_rows = [item[1] for item in by_day_agent_last[d].values()]
        agent_count_curve.append(len(last_rows))

        vals = [v for v in (safe_float(r.get("cumulative_return_pct")) for r in last_rows) if v is not None]
        if vals:
            avg_ret.append(sum(vals) / len(vals))
            med_ret.append(float(median(vals)))
        else:
            avg_ret.append(0.0)
            med_ret.append(0.0)

        n = max(1, len(vals))
        win_rate.append(100.0 * sum(1 for v in vals if v > 0) / n)
        lose_rate.append(100.0 * sum(1 for v in vals if v < 0) / n)

        de_vals = [v for v in (safe_float(r.get("de_odean")) for r in last_rows) if v is not None]
        pgr_vals = [v for v in (safe_float(r.get("pgr")) for r in last_rows) if v is not None]
        plr_vals = [v for v in (safe_float(r.get("plr")) for r in last_rows) if v is not None]
        lam_vals = [v for v in (safe_float(r.get("lambda_estimate")) for r in last_rows) if v is not None]

        de_curve.append(sum(de_vals) / len(de_vals) if de_vals else 0.0)
        pgr_curve.append(sum(pgr_vals) / len(pgr_vals) if pgr_vals else 0.0)
        plr_curve.append(sum(plr_vals) / len(plr_vals) if plr_vals else 0.0)
        lambda_curve.append(sum(lam_vals) / len(lam_vals) if lam_vals else 0.0)

        evt = by_day_realized.get(d, {"gain_pct_sum": 0.0, "loss_pct_sum": 0.0})
        gain_pct_curve.append(float(evt.get("gain_pct_sum", 0.0)))
        loss_pct_curve.append(float(evt.get("loss_pct_sum", 0.0)))

    out_dir = ensure_output_dir(run_dir, args.output_dir or None)
    chart_path = out_dir / (
        f"behavioral_performance_curves_tom{args.tom_level}.png"
        if args.tom_level >= 0
        else "behavioral_performance_curves.png"
    )
    summary_path = out_dir / (
        f"behavioral_performance_summary_tom{args.tom_level}.json"
        if args.tom_level >= 0
        else "behavioral_performance_summary.json"
    )

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, dpi=140)
    ax1, ax2, ax3 = axes

    ax1.plot(days, avg_ret, label="平均累计收益率（%）", color="#1f77b4", linewidth=1.8)
    ax1.plot(days, med_ret, label="中位数累计收益率（%）", color="#ff7f0e", linewidth=1.7)
    ax1.set_ylabel("收益率（%）")
    ax1.set_title("行为收益曲线")
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper left")

    ax2.plot(days, win_rate, label="盈利占比", color="#2ca02c", linewidth=1.8)
    ax2.plot(days, lose_rate, label="亏损占比", color="#d62728", linewidth=1.8)
    ax2.set_ylabel("比例（%）")
    ax2.set_title("盈亏占比曲线")
    ax2.grid(alpha=0.2)
    ax2.legend(loc="upper left")

    ax3.plot(days, de_curve, label="处置效应指数（de_odean）", color="#9467bd", linewidth=1.8)
    ax3.plot(days, pgr_curve, label="PGR", color="#17becf", linewidth=1.7)
    ax3.plot(days, plr_curve, label="PLR", color="#8c564b", linewidth=1.7)
    ax3.plot(days, lambda_curve, label="λ（损失厌恶系数）", color="#2ca02c", linewidth=1.7)
    ax3.plot(days, gain_pct_curve, label="已实现盈利幅度和（%）", color="#1f77b4", linewidth=1.3, alpha=0.7)
    ax3.plot(days, loss_pct_curve, label="已实现亏损幅度和（%）", color="#d62728", linewidth=1.3, alpha=0.7)
    ax3.set_xlabel("交易日")
    ax3.set_ylabel("数值")
    ax3.set_title("处置效应与已实现盈亏曲线")
    ax3.grid(alpha=0.2)
    ax3.legend(loc="upper left", ncol=2, fontsize=8)

    fig.tight_layout()
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "tom_level_filter": args.tom_level,
        "days": len(days),
        "latest_day": days[-1],
        "latest_metrics": {
            "agent_count": agent_count_curve[-1],
            "avg_cumulative_return_pct": avg_ret[-1],
            "median_cumulative_return_pct": med_ret[-1],
            "win_rate_pct": win_rate[-1],
            "loss_rate_pct": lose_rate[-1],
            "de_odean": de_curve[-1],
            "pgr": pgr_curve[-1],
            "plr": plr_curve[-1],
            "lambda_estimate": lambda_curve[-1],
            "realized_gain_pct_sum": gain_pct_curve[-1],
            "realized_loss_pct_sum": loss_pct_curve[-1],
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"chart": str(chart_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
