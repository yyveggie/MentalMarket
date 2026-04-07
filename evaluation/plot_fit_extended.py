#!/usr/bin/env python3
"""绘制扩展拟合指标对比图（多实验柱状图 + 雷达图）。

用法:
    python evaluation/plot_fit_extended.py \
        runs/20260329_005147_tom07_tom12_tom21_预测拟合 \
        runs/20260329_150251_tom01_tom11_tom21_预测拟合 \
        runs/20260330_211929_tom06_tom13_tom21_预测拟合 \
        --labels "tom07/12/21,tom01/11/21,tom06/13/21" \
        --real-curves data/index_volatility_curves.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metric_fit_extended import (
    compute_extended_for_symbol,
    compute_overall_extended,
    _load_profile_weights,
    BROAD_EQW_SYMBOL,
)
from data_loader import (
    load_real_curves,
    build_sim_close_by_day,
    remap_sim_close_to_trading_days,
    resolve_existing_path,
    resolve_calendar_news_file,
    load_closed_dates_from_calendar_news,
    resolve_include_closed_days,
    aligned_real_sim_with_day,
    _build_nonseed_close_map,
)
from metrics_plot_common import read_jsonl
from metric_fit_accuracy import build_weighted_close_by_day


def _compute_for_run(run_dir: Path, real_curves: str, profile_csv: str) -> dict:
    include_closed = resolve_include_closed_days(run_dir, "auto")
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed else load_closed_dates_from_calendar_news(calendar_news_file)
    real_path = resolve_existing_path(real_curves, run_dir)
    _, real_close, _, open_day_of_all_day = load_real_curves(real_path, include_closed_days=include_closed, closed_dates_hint=closed_dates_hint)
    snapshot_rows = read_jsonl(run_dir / "market_snapshots.jsonl")
    sim_close_all = build_sim_close_by_day(snapshot_rows, nonseed_map=_build_nonseed_close_map(run_dir))
    sim_close = remap_sim_close_to_trading_days(sim_close_all, open_day_of_all_day)
    max_day = 0
    for dmap in sim_close.values():
        if dmap:
            max_day = max(max_day, max(dmap.keys()))

    symbols = sorted(set(real_close) & set(sim_close))
    profile_weights = None
    try:
        profile_weights = _load_profile_weights(resolve_existing_path(profile_csv, run_dir))
    except FileNotFoundError:
        pass

    per_symbol = {}
    for sym in symbols:
        aligned = aligned_real_sim_with_day(sym, real_close, sim_close, max_day)
        m = compute_extended_for_symbol(aligned)
        if m:
            per_symbol[sym] = m

    broad = {}
    if len(symbols) >= 2:
        br = build_weighted_close_by_day(real_close, symbols, max_day, weights=profile_weights)
        bs = build_weighted_close_by_day(sim_close, symbols, max_day, weights=profile_weights)
        if br and bs:
            ba = [(d, br[d], bs[d]) for d in sorted(set(br) & set(bs))]
            broad = compute_extended_for_symbol(ba)

    overall = compute_overall_extended(
        {s: v for s, v in per_symbol.items() if s != BROAD_EQW_SYMBOL},
        profile_weights,
    )
    return {"overall": overall, "broad_index": broad, "per_symbol": per_symbol}


# 指标分组与展示名
METRIC_GROUPS = [
    ("分布拟合", [
        ("ks_stat", "KS 统计量", True),     # lower is better
        ("wasserstein", "Wasserstein", True),
        ("skew_diff", "偏度差", True),
        ("kurt_diff", "峰度差", True),
    ]),
    ("曲线拟合", [
        ("dtw_normalized", "DTW(归一化)", True),
        ("mape", "MAPE(%)", True),
        ("theil_u1", "Theil U1", True),
        ("theil_u2", "Theil U2", True),
    ]),
    ("波动结构", [
        ("qlike", "QLIKE", True),
        ("lb_q_ratio", "LB-Q比率", False),  # closer to 1 is better
    ]),
]


def plot_bars(all_results: list[dict], labels: list[str], output: Path):
    """柱状图：每个指标分组一行，实验并排对比。"""
    flat_metrics = []
    for gname, items in METRIC_GROUPS:
        for mkey, mname, _ in items:
            flat_metrics.append((gname, mkey, mname))

    n_metrics = len(flat_metrics)
    n_runs = len(all_results)

    fig, axes = plt.subplots(n_metrics, 1, figsize=(10, 2.2 * n_metrics), dpi=140)
    if n_metrics == 1:
        axes = [axes]

    colors = ["#e6550d", "#3182bd", "#31a354", "#756bb1", "#e7298a"]
    x = np.arange(n_runs)
    width = 0.6

    for idx, (gname, mkey, mname) in enumerate(flat_metrics):
        ax = axes[idx]
        vals = []
        for r in all_results:
            v = r.get("overall", {}).get(mkey)
            vals.append(v if v is not None else 0)
        bars = ax.bar(x, vals, width, color=[colors[i % len(colors)] for i in range(n_runs)])
        ax.set_ylabel(mname, fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(f"{gname}: {mname}", fontsize=10)
        ax.grid(alpha=0.15, axis="y")
        for b, v in zip(bars, vals):
            if v != 0:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
                        f"{v:.4f}", ha="center", va="bottom", fontsize=7)

    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def plot_radar(all_results: list[dict], labels: list[str], output: Path):
    """雷达图：综合对比。"""
    # 选取关键指标
    radar_keys = ["ks_stat", "wasserstein", "dtw_normalized", "mape", "theil_u1", "qlike", "skew_diff", "kurt_diff"]
    radar_names = ["KS", "Wass.", "DTW", "MAPE", "Theil U1", "QLIKE", "偏度差", "峰度差"]

    n = len(radar_keys)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), dpi=140, subplot_kw=dict(polar=True))
    colors = ["#e6550d", "#3182bd", "#31a354", "#756bb1"]

    for i, r in enumerate(all_results):
        vals = []
        for k in radar_keys:
            v = r.get("overall", {}).get(k)
            vals.append(v if v is not None else 0)
        # 归一化到 [0, 1] 跨实验
        vals_arr = np.array(vals)
        vals_plot = vals_arr.tolist() + [vals_arr[0]]
        ax.plot(angles, vals_plot, color=colors[i % len(colors)], linewidth=1.8, label=labels[i])
        ax.fill(angles, vals_plot, color=colors[i % len(colors)], alpha=0.1)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(radar_names, fontsize=9)
    ax.set_title("扩展拟合指标雷达图", fontsize=13, y=1.08)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def plot_per_symbol_heatmap(all_results: list[dict], labels: list[str], output: Path):
    """热力图：每个实验各指数的关键指标。"""
    hm_keys = ["ks_stat", "wasserstein", "dtw_normalized", "theil_u1", "qlike"]
    hm_names = ["KS", "Wass.", "DTW", "Theil U1", "QLIKE"]

    symbols = set()
    for r in all_results:
        symbols.update(r.get("per_symbol", {}).keys())
    symbols = sorted(symbols)
    if not symbols:
        return

    n_runs = len(all_results)
    n_metrics = len(hm_keys)

    fig, axes = plt.subplots(1, n_runs, figsize=(5 * n_runs, 0.4 * len(symbols) + 2), dpi=140)
    if n_runs == 1:
        axes = [axes]

    for ri, (r, label) in enumerate(zip(all_results, labels)):
        ax = axes[ri]
        data = np.zeros((len(symbols), n_metrics))
        for si, sym in enumerate(symbols):
            for mi, mk in enumerate(hm_keys):
                v = r.get("per_symbol", {}).get(sym, {}).get(mk)
                data[si, mi] = v if v is not None else np.nan

        im = ax.imshow(data, aspect="auto", cmap="YlOrRd")
        ax.set_xticks(range(n_metrics))
        ax.set_xticklabels(hm_names, fontsize=8, rotation=45, ha="right")
        ax.set_yticks(range(len(symbols)))
        ax.set_yticklabels(symbols, fontsize=8)
        ax.set_title(label, fontsize=10)

        for si in range(len(symbols)):
            for mi in range(n_metrics):
                v = data[si, mi]
                if not np.isnan(v):
                    ax.text(mi, si, f"{v:.3f}", ha="center", va="center", fontsize=6,
                            color="white" if v > np.nanmedian(data) else "black")

    fig.suptitle("各指数扩展拟合指标热力图", fontsize=13)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="扩展拟合指标对比图")
    parser.add_argument("run_dirs", nargs="+")
    parser.add_argument("--labels", default="")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json")
    parser.add_argument("--profile-csv", default="data/stock_profile.csv")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    labels = [l.strip() for l in args.labels.split(",") if l.strip()] if args.labels else []
    if len(labels) < len(args.run_dirs):
        labels += [Path(d).name for d in args.run_dirs[len(labels):]]

    print("计算扩展拟合指标…")
    all_results = []
    for rd in args.run_dirs:
        print(f"  → {Path(rd).name}")
        r = _compute_for_run(Path(rd), args.real_curves, args.profile_csv)
        all_results.append(r)

    out = Path(args.output_dir)
    out.mkdir(exist_ok=True)

    # 1) 柱状图
    bar_path = out / "扩展拟合指标_柱状图.png"
    plot_bars(all_results, labels, bar_path)
    print(f"柱状图: {bar_path}")

    # 2) 雷达图
    radar_path = out / "扩展拟合指标_雷达图.png"
    plot_radar(all_results, labels, radar_path)
    print(f"雷达图: {radar_path}")

    # 3) 热力图
    hm_path = out / "扩展拟合指标_热力图.png"
    plot_per_symbol_heatmap(all_results, labels, hm_path)
    print(f"热力图: {hm_path}")

    # 4) JSON 汇总
    summary = []
    for label, r in zip(labels, all_results):
        summary.append({"label": label, "overall": r["overall"], "broad_index": r["broad_index"]})
    json_path = out / "扩展拟合指标_汇总.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 汇总: {json_path}")

    # 打印总览
    print("\n=== 总览 (overall) ===")
    for label, r in zip(labels, all_results):
        print(f"\n{label}:")
        for k, v in r.get("overall", {}).items():
            print(f"  {k}: {v:.6f}" if isinstance(v, float) else f"  {k}: {v}")


if __name__ == "__main__":
    main()
