#!/usr/bin/env python3
"""财富不平等评估脚本（双语说明）。

中文：
- 计算并绘制财富分布不平等指标：Gini、Theil-T、Top-1 占比。
- 支持按 ToM 层级过滤，观察群体结构差异。

English:
- Computes and plots inequality metrics for wealth distribution: Gini,
  Theil-T, and Top-1 share.
- Supports ToM-level filtering to inspect cross-group distributional patterns.

运行示例:
- 项目根目录执行:
    python evaluation/plot_wealth_inequality_metrics.py --run-dir runs/20260329_150251
- evaluation 目录执行:
    python plot_wealth_inequality_metrics.py --run-dir ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from academic_metrics_common import latest_non_nan, resolve_run_dir
from metric_wealth_inequality import build_daily_inequality
from metrics_plot_common import configure_chinese_font, ensure_output_dir

configure_chinese_font()

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot wealth inequality metrics")
    parser.add_argument("run_dir", nargs="?", default="", help="Run directory path")
    parser.add_argument("--run-dir", dest="run_dir_opt", default="", help="Run directory path (optional named arg)")
    parser.add_argument("--tom-level", type=int, default=-1, help="If >=0, only use this ToM level")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    args = parser.parse_args()

    run_dir = resolve_run_dir(args, parser)
    out_dir = ensure_output_dir(run_dir, args.output_dir or None)

    tom_level = args.tom_level if args.tom_level >= 0 else None
    days, gini, theil_t, top1_share, agent_n = build_daily_inequality(run_dir, tom_level=tom_level)
    if not days:
        raise SystemExit("No valid daily wealth snapshots in agent_wealth.jsonl")

    fig, ax = plt.subplots(1, 1, figsize=(12, 4.8), dpi=140)
    ax.plot(days, gini, label="Gini", linewidth=1.9, color="#bcbd22")
    ax.plot(days, theil_t, label="Theil-T", linewidth=1.9, color="#8c564b")
    ax.plot(days, top1_share, label="Top-1 share", linewidth=1.9, color="#e377c2")
    ax.set_xlabel("交易日")
    ax.set_ylabel("不平等度")
    title = "财富不平等指标"
    if tom_level is not None:
        title += f"（ToM={tom_level}）"
    ax.set_title(title)
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left")
    fig.tight_layout()

    suffix = f"_tom{tom_level}" if tom_level is not None else ""
    chart_path = out_dir / f"wealth_inequality_metrics{suffix}.png"
    summary_path = out_dir / f"wealth_inequality_summary{suffix}.json"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "tom_level": tom_level,
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

    print(json.dumps({"chart": str(chart_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
