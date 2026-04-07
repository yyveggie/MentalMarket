#!/usr/bin/env python3
"""真实大盘 vs 模拟大盘 对比图（支持多个实验叠加）。"""

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_real_broad(real_curves_path: str, profile_csv: str | None, news2_path: str) -> tuple[list[int], list[float]]:
    """从真实分指数曲线加权合成大盘，返回 (sim_days, normalized_values)。"""
    with open(real_curves_path, encoding="utf-8") as f:
        indices = json.load(f)["indices"]

    # 加载权重
    weights: dict[str, float] = {}
    if profile_csv and Path(profile_csv).exists():
        with open(profile_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = row.get("stock_id", "").strip()
                w = float(row.get("weight", 0))
                if sym and w > 0:
                    weights[sym] = w
    if not weights:
        weights = {s: 1.0 for s in indices}
    total_w = sum(weights.get(s, 0) for s in indices)
    norm_w = {s: weights.get(s, 0) / total_w for s in indices if weights.get(s, 0) > 0}

    # date -> real_close (per symbol)
    real_by_date: dict[str, dict[str, float]] = {}
    for sym, records in indices.items():
        if sym not in norm_w:
            continue
        for rec in records:
            d = rec["date"]
            real_by_date.setdefault(d, {})[sym] = rec["close"]

    # 加载 news2 做 date -> sim_day 映射
    with open(news2_path, encoding="utf-8") as f:
        news2 = json.load(f)
    date_to_day = {}
    for item in news2["news"]:
        if item.get("market_status") == "开市":
            date_to_day[item["date"]] = item["day"]

    # 合成加权大盘
    day_value: dict[int, float] = {}
    syms = sorted(norm_w.keys())
    for date_str, closes in real_by_date.items():
        sim_day = date_to_day.get(date_str)
        if sim_day is None:
            continue
        if all(s in closes for s in syms):
            val = sum(norm_w[s] * closes[s] for s in syms)
            day_value[sim_day] = val

    days = sorted(day_value.keys())
    if not days:
        return [], []
    base = day_value[days[0]]
    normed = [day_value[d] / base * 100 for d in days]
    return days, normed


def load_sim_broad(run_dir: str) -> tuple[list[int], list[float]]:
    """从 broad_index.jsonl 加载模拟大盘，归一化为首日=100。"""
    p = Path(run_dir) / "broad_index.jsonl"
    day_val: dict[int, float] = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            day_val[rec["trading_day"]] = rec["value"]
    days = sorted(day_val.keys())
    if not days:
        return [], []
    base = day_val[days[0]]
    normed = [day_val[d] / base * 100 for d in days]
    return days, normed


def main():
    parser = argparse.ArgumentParser(description="真实大盘 vs 模拟大盘对比图")
    parser.add_argument("run_dirs", nargs="+", help="实验目录")
    parser.add_argument("--labels", default="", help="逗号分隔的标签")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json")
    parser.add_argument("--profile-csv", default="data/stock_profile.csv")
    parser.add_argument("--news2", default="data/news2.json")
    parser.add_argument("--output", default="output/broad_real_vs_sim.png")
    args = parser.parse_args()

    labels = [l.strip() for l in args.labels.split(",") if l.strip()] if args.labels else []
    if len(labels) < len(args.run_dirs):
        labels += [Path(d).name for d in args.run_dirs[len(labels):]]

    # 真实大盘
    real_days, real_vals = load_real_broad(args.real_curves, args.profile_csv, args.news2)
    if not real_days:
        print("无法构建真实大盘数据", file=sys.stderr)
        sys.exit(1)

    # 模拟大盘
    sim_data = []
    for rd in args.run_dirs:
        sd, sv = load_sim_broad(rd)
        sim_data.append((sd, sv))

    # 画图
    colors = ["#e6550d", "#3182bd", "#31a354", "#756bb1", "#e7298a", "#66a61e"]
    fig, ax = plt.subplots(figsize=(14, 6.5), dpi=140)

    ax.plot(real_days, real_vals, color="#111111", linewidth=2.5, label="真实大盘（加权合成）", zorder=10)

    for i, (sd, sv) in enumerate(sim_data):
        c = colors[i % len(colors)]
        ax.plot(sd, sv, color=c, linewidth=1.8, alpha=0.85, label=f"模拟: {labels[i]}")

    ax.set_xlabel("交易日（sim_day）", fontsize=12)
    ax.set_ylabel("归一化指数（首日=100）", fontsize=12)
    ax.set_title("真实大盘 vs 模拟大盘 对比", fontsize=14)
    ax.legend(fontsize=9, loc="best")
    ax.grid(alpha=0.2)

    fig.tight_layout()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"图表已保存: {out}")

    # 同时存 PDF
    pdf_out = out.with_suffix(".pdf")
    fig2, ax2 = plt.subplots(figsize=(14, 6.5), dpi=140)
    ax2.plot(real_days, real_vals, color="#111111", linewidth=2.5, label="真实大盘（加权合成）", zorder=10)
    for i, (sd, sv) in enumerate(sim_data):
        c = colors[i % len(colors)]
        ax2.plot(sd, sv, color=c, linewidth=1.8, alpha=0.85, label=f"模拟: {labels[i]}")
    ax2.set_xlabel("交易日（sim_day）", fontsize=12)
    ax2.set_ylabel("归一化指数（首日=100）", fontsize=12)
    ax2.set_title("真实大盘 vs 模拟大盘 对比", fontsize=14)
    ax2.legend(fontsize=9, loc="best")
    ax2.grid(alpha=0.2)
    fig2.tight_layout()
    fig2.savefig(pdf_out, bbox_inches="tight")
    plt.close(fig2)
    print(f"PDF已保存: {pdf_out}")


if __name__ == "__main__":
    main()
