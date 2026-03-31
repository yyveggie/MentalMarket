#!/usr/bin/env python3
"""行为偏差曲线评估脚本（双语说明）。

中文：
- 从 behavioral_biases 日志按交易日聚合并绘制行为偏差相关曲线。
- 覆盖处置效应、过度自信、从众、动量/反转、LSV 等指标。

English:
- Aggregates behavioral_biases logs by trading day and plots behavioral bias
    curves.
- Covers disposition effect, overconfidence, herding, momentum/contrarian, and
    advanced indicators such as LSV.

运行示例:
- 项目根目录执行:
    python evaluation/plot_behavioral_bias_curves.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_behavioral_bias_curves.py --run-dir ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from academic_metrics_common import resolve_run_dir
from metrics_plot_common import configure_chinese_font, ensure_output_dir, read_jsonl, safe_float, safe_int

configure_chinese_font()


def is_true(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v) != 0.0
    if isinstance(v, str):
        s = v.strip().lower()
        return s in {"1", "true", "yes", "y", "t"}
    return False

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot behavioral bias curves by trading day")
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

    by_day: dict[int, dict[str, Any]] = {}
    for row in rows:
        day = safe_int(row.get("trading_day"))
        if day is None or day <= 0:
            continue
        tom_level = safe_int(row.get("tom_level"))
        if args.tom_level >= 0 and tom_level != args.tom_level:
            continue

        slot = by_day.setdefault(
            day,
            {
                "n": 0,
                "herding_n": 0,
                "momentum_n": 0,
                "positive_skew_n": 0,
                "disposition": 0,
                "overconf": 0,
                "underdiv": 0,
                "avgdown": 0,
                "loss_aversion": 0,
                "herding": 0,
                "loss_trading": 0,
                "positive_skew": 0,
                "momentum": 0,
                "contrarian": 0,
                "turnover_sum": 0.0,
                "turnover_n": 0,
                "hhi_sum": 0.0,
                "hhi_n": 0,
                "max_loss_sum": 0.0,
                "max_loss_n": 0,
                "lsv_sum": 0.0,
                "lsv_n": 0,
                "skew_sum": 0.0,
                "skew_n": 0,
                "lambda_sum": 0.0,
                "lambda_n": 0,
            },
        )

        slot["n"] += 1
        if is_true(row.get("disposition_effect_flag")):
            slot["disposition"] += 1
        if is_true(row.get("overconfidence_flag")):
            slot["overconf"] += 1
        if is_true(row.get("underdiversification_flag")):
            slot["underdiv"] += 1
        if is_true(row.get("averaging_down_flag")):
            slot["avgdown"] += 1
        if is_true(row.get("loss_aversion_flag")):
            slot["loss_aversion"] += 1
        herding_raw = row.get("herding_flag")
        if herding_raw is not None:
            slot["herding_n"] += 1
            if is_true(herding_raw):
                slot["herding"] += 1
        if is_true(row.get("loss_trading_flag")):
            slot["loss_trading"] += 1

        # 主系统中 positive_skew 仅在 buy 且 status=ok 时产生。
        action = str(row.get("action", "")).strip().lower()
        status = str(row.get("status", "")).strip().lower()
        if action == "buy" and status == "ok":
            slot["positive_skew_n"] += 1
            if is_true(row.get("positive_skew_flag")):
                slot["positive_skew"] += 1

        moc = str(row.get("momentum_or_contrarian", "")).strip().lower()
        if moc == "momentum":
            slot["momentum_n"] += 1
            slot["momentum"] += 1
        elif moc == "contrarian":
            slot["momentum_n"] += 1
            slot["contrarian"] += 1

        turnover = safe_float(row.get("turnover_rate"))
        if turnover is not None:
            slot["turnover_sum"] += turnover
            slot["turnover_n"] += 1

        hhi = safe_float(row.get("portfolio_hhi"))
        if hhi is not None:
            slot["hhi_sum"] += hhi
            slot["hhi_n"] += 1

        max_loss = safe_float(row.get("max_unrealized_loss_pct"))
        if max_loss is not None:
            slot["max_loss_sum"] += max_loss
            slot["max_loss_n"] += 1

        lsv = safe_float(row.get("lsv_herding"))
        if lsv is not None:
            slot["lsv_sum"] += lsv
            slot["lsv_n"] += 1

        skew = safe_float(row.get("recent_skewness"))
        if skew is not None:
            slot["skew_sum"] += skew
            slot["skew_n"] += 1

        lam = safe_float(row.get("lambda_estimate"))
        if lam is not None:
            slot["lambda_sum"] += lam
            slot["lambda_n"] += 1

    if not by_day:
        raise SystemExit("No valid behavioral records after filtering")

    days = sorted(by_day.keys())

    def pct(key: str, denom_key: str = "n") -> list[float]:
        out: list[float] = []
        for d in days:
            n = max(1, int(by_day[d][denom_key]))
            out.append(100.0 * float(by_day[d][key]) / n)
        return out

    disposition = pct("disposition")
    overconf = pct("overconf")
    underdiv = pct("underdiv")
    avgdown = pct("avgdown")
    loss_aversion = pct("loss_aversion")
    herding = pct("herding", "herding_n")
    loss_trading = pct("loss_trading")
    positive_skew = pct("positive_skew", "positive_skew_n")
    momentum = pct("momentum", "momentum_n")
    contrarian = pct("contrarian", "momentum_n")

    turnover_avg = [
        by_day[d]["turnover_sum"] / by_day[d]["turnover_n"] if by_day[d]["turnover_n"] > 0 else 0.0
        for d in days
    ]
    hhi_avg = [
        by_day[d]["hhi_sum"] / by_day[d]["hhi_n"] if by_day[d]["hhi_n"] > 0 else 0.0
        for d in days
    ]
    max_loss_avg = [
        by_day[d]["max_loss_sum"] / by_day[d]["max_loss_n"] if by_day[d]["max_loss_n"] > 0 else 0.0
        for d in days
    ]
    lsv_avg = [
        by_day[d]["lsv_sum"] / by_day[d]["lsv_n"] if by_day[d]["lsv_n"] > 0 else 0.0
        for d in days
    ]
    skew_avg = [
        by_day[d]["skew_sum"] / by_day[d]["skew_n"] if by_day[d]["skew_n"] > 0 else 0.0
        for d in days
    ]
    lambda_avg = [
        by_day[d]["lambda_sum"] / by_day[d]["lambda_n"] if by_day[d]["lambda_n"] > 0 else 0.0
        for d in days
    ]

    out_dir = ensure_output_dir(run_dir, args.output_dir or None)
    chart_path = out_dir / (
        f"behavioral_bias_curves_tom{args.tom_level}.png" if args.tom_level >= 0 else "behavioral_bias_curves.png"
    )
    summary_path = out_dir / (
        f"behavioral_bias_summary_tom{args.tom_level}.json" if args.tom_level >= 0 else "behavioral_bias_summary.json"
    )

    fig, axes = plt.subplots(4, 1, figsize=(12, 12.5), sharex=True, dpi=140)

    ax1, ax2, ax3, ax4 = axes
    ax1.plot(days, disposition, label="处置效应", color="#1f77b4", linewidth=1.8)
    ax1.plot(days, overconf, label="过度自信", color="#d62728", linewidth=1.8)
    ax1.plot(days, underdiv, label="欠分散", color="#2ca02c", linewidth=1.8)
    ax1.plot(days, avgdown, label="亏损加仓", color="#9467bd", linewidth=1.6)
    ax1.plot(days, loss_aversion, label="损失厌恶", color="#8c564b", linewidth=1.6)
    ax1.plot(days, herding, label="从众", color="#e377c2", linewidth=1.6)
    ax1.plot(days, loss_trading, label="亏损后高频交易", color="#bcbd22", linewidth=1.5)
    ax1.set_ylabel("比例（%）")
    ax1.set_title("行为偏差占比曲线")
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper left", ncol=3, fontsize=8)

    ax2.plot(days, momentum, label="动量交易", color="#17becf", linewidth=1.8)
    ax2.plot(days, contrarian, label="反转交易", color="#ff7f0e", linewidth=1.8)
    ax2.plot(days, positive_skew, label="正偏好（彩票偏好）", color="#7f7f7f", linewidth=1.6)
    ax2.set_ylabel("比例（%）")
    ax2.set_title("交易风格偏好")
    ax2.grid(alpha=0.2)
    ax2.legend(loc="upper left")

    ax3.plot(days, turnover_avg, label="平均换手率", color="#1f77b4", linewidth=1.8)
    ax3.plot(days, hhi_avg, label="平均组合 HHI", color="#2ca02c", linewidth=1.8)
    ax3.plot(days, max_loss_avg, label="平均最大浮亏（%）", color="#d62728", linewidth=1.6)
    ax3.set_xlabel("交易日")
    ax3.set_ylabel("数值")
    ax3.set_title("风险与集中度曲线")
    ax3.grid(alpha=0.2)
    ax3.legend(loc="upper left")

    ax4.plot(days, lsv_avg, label="LSV 羊群强度", color="#1f77b4", linewidth=1.8)
    ax4.plot(days, skew_avg, label="平均近期偏度", color="#ff7f0e", linewidth=1.7)
    ax4.plot(days, lambda_avg, label="平均 λ（损失厌恶系数）", color="#2ca02c", linewidth=1.7)
    ax4.set_xlabel("交易日")
    ax4.set_ylabel("数值")
    ax4.set_title("高级行为指标曲线")
    ax4.grid(alpha=0.2)
    ax4.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "tom_level_filter": args.tom_level,
        "days": len(days),
        "latest_day": days[-1],
        "latest_metrics": {
            "disposition_rate_pct": disposition[-1],
            "overconfidence_rate_pct": overconf[-1],
            "underdiv_rate_pct": underdiv[-1],
            "loss_trading_rate_pct": loss_trading[-1],
            "positive_skew_rate_pct": positive_skew[-1],
            "herding_applicable_n": int(by_day[days[-1]]["herding_n"]),
            "momentum_applicable_n": int(by_day[days[-1]]["momentum_n"]),
            "positive_skew_applicable_n": int(by_day[days[-1]]["positive_skew_n"]),
            "avg_turnover": turnover_avg[-1],
            "avg_hhi": hhi_avg[-1],
            "avg_max_unrealized_loss_pct": max_loss_avg[-1],
            "avg_lsv_herding": lsv_avg[-1],
            "avg_recent_skewness": skew_avg[-1],
            "avg_lambda_estimate": lambda_avg[-1],
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"chart": str(chart_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
