#!/usr/bin/env python3
"""跨日志 ToM 阶级分布波动对比脚本（双语说明）。

中文：
- 对比多个实验 run 的 ToM 阶级分布变化，重点展示分布占比与其波动率。
- 输入多个 runs/<run_id> 目录，读取各自 tom_stats.jsonl 后按交易日对齐。
- 输出跨日志对比图与摘要 JSON，便于观察不同实验设置下的群体结构稳定性。

English:
- Compares ToM-level distribution dynamics across multiple run logs.
- Reads tom_stats.jsonl from each run, aligns by trading day, and visualizes
  both level and volatility of class shares.
- Produces a cross-run comparison figure and JSON summary for stability
  analysis under different experiment settings.

运行示例:
- 项目根目录执行:
        python evaluation/plot_cross_run_tom_distribution_volatility.py --run-dirs runs/20260320_121528_tom0 runs/20260322_132820_tom0
- evaluation 目录执行:
        python plot_cross_run_tom_distribution_volatility.py --run-dirs ../runs/20260320_121528_tom0 ../runs/20260322_132820_tom0
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from metrics_plot_common import configure_chinese_font, ensure_output_dir, read_jsonl, safe_float, safe_int

configure_chinese_font()


def resolve_run_dir(path_str: str) -> Path:
    run_dir = Path(path_str)
    if not run_dir.exists() or not run_dir.is_dir():
        raise SystemExit(f"Run directory not found: {run_dir}")
    if not (run_dir / "tom_stats.jsonl").exists():
        raise SystemExit(f"Missing tom_stats.jsonl in run directory: {run_dir}")
    return run_dir


def rolling_std(values: list[float], window: int) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        j = max(0, i - window + 1)
        seg = values[j : i + 1]
        if len(seg) < 2:
            out.append(0.0)
            continue
        mean = sum(seg) / len(seg)
        var = sum((x - mean) ** 2 for x in seg) / len(seg)
        out.append(var**0.5)
    return out


def load_tom_daily_last(run_dir: Path) -> dict[int, dict[int, dict]]:
    rows = read_jsonl(run_dir / "tom_stats.jsonl")
    # day -> tom_level -> (sim_time, row)
    by_day_level: dict[int, dict[int, tuple[float, dict]]] = {}

    for r in rows:
        day = safe_int(r.get("trading_day"))
        level = safe_int(r.get("tom_level"))
        tm = safe_float(r.get("sim_time"))
        if day is None or day <= 0 or level is None:
            continue
        t = tm if tm is not None else -1.0
        dm = by_day_level.setdefault(day, {})
        old = dm.get(level)
        if old is None or t >= old[0]:
            dm[level] = (t, r)

    out: dict[int, dict[int, dict]] = {}
    for day, level_map in by_day_level.items():
        out[day] = {level: level_map[level][1] for level in level_map}
    return out


def build_run_series(
    day_level_rows: dict[int, dict[int, dict]],
    days: list[int],
    tom_levels: list[int],
    window: int,
) -> dict[int, dict[str, list[float]]]:
    # day -> total count
    day_total_count: dict[int, float] = {}
    for day in days:
        level_rows = day_level_rows.get(day, {})
        total = 0.0
        for level in tom_levels:
            c = safe_float(level_rows.get(level, {}).get("count")) if level in level_rows else None
            total += c if c is not None else 0.0
        day_total_count[day] = total

    per_level: dict[int, dict[str, list[float]]] = {}

    for level in tom_levels:
        share: list[float] = []
        avg_return_pct: list[float] = []
        avg_wealth: list[float] = []

        for day in days:
            row = day_level_rows.get(day, {}).get(level, {})
            total = day_total_count.get(day, 0.0)
            c = safe_float(row.get("count"))
            r = safe_float(row.get("avg_return_pct"))
            w = safe_float(row.get("avg_wealth"))

            if c is None or total <= 1e-12:
                share.append(0.0)
            else:
                share.append(c / total)

            avg_return_pct.append(r if r is not None else float("nan"))
            avg_wealth.append(w if w is not None else float("nan"))

        share_vol = rolling_std(share, window)

        per_level[level] = {
            "share": share,
            "share_vol": share_vol,
            "avg_return_pct": avg_return_pct,
            "avg_wealth": avg_wealth,
        }

    return per_level


def pick_levels(all_day_level_rows: list[dict[int, dict[int, dict]]], explicit_levels: list[int] | None) -> list[int]:
    if explicit_levels:
        return sorted(set(explicit_levels))

    levels: set[int] = set()
    for day_map in all_day_level_rows:
        for level_map in day_map.values():
            levels.update(level_map.keys())
    return sorted(levels)


def non_nan_mean(values: list[float]) -> float | None:
    xs = [x for x in values if not math.isnan(x)]
    if not xs:
        return None
    return sum(xs) / len(xs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot cross-run ToM distribution and volatility comparison")
    parser.add_argument(
        "run_dirs",
        nargs="+",
        help="Two or more run directories, e.g. runs/20260329_005147 runs/20260329_005147_tuned",
    )
    parser.add_argument("--tom-levels", type=int, nargs="*", default=None, help="Optional ToM levels to include")
    parser.add_argument("--rolling-window", type=int, default=10, help="Rolling window (days) for share volatility")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run1>/figures)")
    args = parser.parse_args()

    if len(args.run_dirs) < 2:
        raise SystemExit("Please provide at least two run directories for cross-run comparison")

    run_dirs = [resolve_run_dir(p) for p in args.run_dirs]
    run_labels = [p.name for p in run_dirs]

    day_level_rows_list = [load_tom_daily_last(p) for p in run_dirs]
    tom_levels = pick_levels(day_level_rows_list, args.tom_levels)
    if not tom_levels:
        raise SystemExit("No tom_level records found in provided runs")

    all_days: set[int] = set()
    for day_map in day_level_rows_list:
        all_days.update(day_map.keys())
    days = sorted(all_days)
    if not days:
        raise SystemExit("No trading_day data found in provided runs")

    window = max(2, args.rolling_window)

    run_series: dict[str, dict[int, dict[str, list[float]]]] = {}
    for i, label in enumerate(run_labels):
        run_series[label] = build_run_series(day_level_rows_list[i], days, tom_levels, window)

    out_dir = ensure_output_dir(run_dirs[0], args.output_dir or None)
    runs_join = "_vs_".join(run_labels)
    chart_path = out_dir / f"cross_run_tom_distribution_volatility_{runs_join}.png"
    summary_path = out_dir / f"cross_run_tom_distribution_volatility_{runs_join}.json"

    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#d62728", "#9467bd", "#8c564b"]
    styles = ["-", "--", ":", "-."]

    fig, axes = plt.subplots(3, 1, figsize=(14, 12.5), sharex=True, dpi=140)
    ax_share, ax_vol, ax_ret = axes

    for level_idx, level in enumerate(tom_levels):
        color = colors[level_idx % len(colors)]
        for run_idx, label in enumerate(run_labels):
            style = styles[run_idx % len(styles)]
            line_label = f"{label} | ToM{level}"
            series = run_series[label][level]

            ax_share.plot(days, [100.0 * x for x in series["share"]], linestyle=style, color=color, linewidth=1.8, label=line_label)
            ax_vol.plot(days, [100.0 * x for x in series["share_vol"]], linestyle=style, color=color, linewidth=1.8, label=line_label)
            ax_ret.plot(days, series["avg_return_pct"], linestyle=style, color=color, linewidth=1.6, label=line_label)

    ax_share.set_ylabel("阶级占比（%）")
    ax_share.set_title("跨日志 ToM 阶级分布占比")
    ax_share.grid(alpha=0.2)

    ax_vol.set_ylabel("占比波动率（%）")
    ax_vol.set_title(f"跨日志 ToM 阶级分布波动（滚动窗口={window}天）")
    ax_vol.grid(alpha=0.2)

    ax_ret.set_xlabel("交易日")
    ax_ret.set_ylabel("平均收益率（%）")
    ax_ret.set_title("跨日志 ToM 阶级平均收益率")
    ax_ret.grid(alpha=0.2)

    handles, labels = ax_share.get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=8, frameon=False)

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary: dict[str, object] = {
        "run_dirs": [str(p) for p in run_dirs],
        "run_labels": run_labels,
        "tom_levels": tom_levels,
        "rolling_window": window,
        "days": days,
        "per_run": {},
    }

    per_run_summary: dict[str, dict[str, object]] = {}
    for label in run_labels:
        per_level_summary: dict[str, object] = {}
        for level in tom_levels:
            series = run_series[label][level]
            per_level_summary[str(level)] = {
                "mean_share_pct": (non_nan_mean(series["share"]) or 0.0) * 100.0,
                "mean_share_vol_pct": (non_nan_mean(series["share_vol"]) or 0.0) * 100.0,
                "mean_avg_return_pct": non_nan_mean(series["avg_return_pct"]),
                "mean_avg_wealth": non_nan_mean(series["avg_wealth"]),
            }
        per_run_summary[label] = per_level_summary

    summary["per_run"] = per_run_summary
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "chart": str(chart_path),
                "summary": str(summary_path),
                "run_labels": run_labels,
                "tom_levels": tom_levels,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
