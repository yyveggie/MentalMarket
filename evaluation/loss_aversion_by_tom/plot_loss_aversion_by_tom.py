#!/usr/bin/env python3
"""各实验 · 按心智层级的损失厌恶系数 λ 均值对比柱状图。

数据源：runs/<exp>/behavioral_biases.jsonl 中的 lambda_estimate 字段。

Kahneman & Tversky 损失厌恶系数（简化版）：
 - λ ≈ avg(|realized_loss_pct|) / avg(|realized_gain_pct|)
 - λ > 1 表示厌恶损失（亏损时持有更久、要求更大的涨幅才卖出）
 - λ < 1 表示相反趋势

聚合口径：对每个 Agent 取其最后一条 non-null lambda_estimate（= 仿真结束时的稳定估计），
按 tom_level 分组计算均值与 95% bootstrap CI。

图表样式对齐 evaluation/turnover_by_tom/plot_turnover_by_tom.py。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RUNS_DIR = Path("/Users/mushroom/Desktop/MentalMarket/runs")
OUT_DIR = Path(__file__).parent
CACHE_FILE = OUT_DIR / "_loss_aversion_cache.json"

EXPERIMENTS = [
    ("ToM1", "ToM1"),
    ("ToM2", "ToM2"),
    ("ToM00_ToM11_ToM21", "0:1:1"),
    ("ToM01_ToM10_ToM21", "1:0:1"),
    ("ToM01_ToM11_ToM20", "1:1:0"),
    ("ToM01_ToM11_ToM21", "1:1:1"),
    ("ToM02_ToM11_ToM21", "2:1:1"),
    ("ToM02_ToM13_ToM23", "2:3:3"),
    ("ToM06_ToM13_ToM21", "6:3:1"),
    ("ToM07_ToM12_ToM21", "7:2:1"),
]

TOM_LEVELS = [0, 1, 2]
COLORS = {0: "#2196F3", 1: "#FF9800", 2: "#E53935"}
LABELS = {0: "ToM 0", 1: "ToM 1", 2: "ToM 2"}


def compute_run(run_dir: Path) -> dict[str, list[float]]:
    """{tom_str: [per-agent final lambda, ...]}

    对每个 agent 取其最后一条 non-null lambda_estimate（按 sim_time 升序）。
    """
    fp = run_dir / "behavioral_biases.jsonl"
    if not fp.exists():
        return {}
    # aid -> (latest_sim_time, lambda, tom)
    latest: dict[int, tuple[float, float, int]] = {}
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lam = r.get("lambda_estimate")
            aid = r.get("agent_id")
            tom = r.get("tom_level")
            st = r.get("sim_time")
            if lam is None or aid is None or tom is None:
                continue
            aid = int(aid); tom = int(tom)
            st_f = float(st) if st is not None else 0.0
            prev = latest.get(aid)
            if prev is None or st_f > prev[0]:
                latest[aid] = (st_f, float(lam), tom)

    by_tom: dict[int, list[float]] = defaultdict(list)
    for aid, (_, lam, tom) in latest.items():
        by_tom[tom].append(lam)
    return {str(t): vs for t, vs in by_tom.items()}


def bootstrap_ci(vals: list[float], B: int = 500, seed: int = 42,
                 alpha: float = 0.05) -> tuple[float, float]:
    if not vals:
        return (float("nan"), float("nan"))
    if len(vals) < 2:
        m = float(np.mean(vals))
        return (m, m)
    rng = np.random.default_rng(seed)
    arr = np.asarray(vals, dtype=float)
    n = len(arr)
    est = np.empty(B)
    for i in range(B):
        est[i] = float(arr[rng.integers(0, n, n)].mean())
    return (float(np.quantile(est, alpha / 2)),
            float(np.quantile(est, 1 - alpha / 2)))


def load_or_compute(force: bool = False) -> dict:
    if CACHE_FILE.exists() and not force:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if all(n in cached for n, _ in EXPERIMENTS):
                return cached
        except Exception:
            pass

    result = {}
    for name, _ in EXPERIMENTS:
        print(f"  解析 {name} ...", flush=True)
        result[name] = compute_run(RUNS_DIR / name)

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"  缓存已写入: {CACHE_FILE}")
    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/2] 计算每个实验的 per-ToM 损失厌恶系数（首次运行较慢）...")
    raw = load_or_compute()

    # 汇总
    summary = {}  # exp_name -> tom -> (mean, lo, hi, n_agent)
    for name, _ in EXPERIMENTS:
        by_tom = raw.get(name, {})
        per_tom = {}
        for t in TOM_LEVELS:
            vals = by_tom.get(str(t), [])
            if vals:
                m = float(np.mean(vals))
                lo, hi = bootstrap_ci(vals)
                per_tom[t] = (m, lo, hi, len(vals))
        summary[name] = per_tom

    # 打印
    print("\n[2/2] 结果:")
    print(f"{'实验':<24} {'ToM0':>22} {'ToM1':>22} {'ToM2':>22}")
    print("-" * 96)
    for name, label in EXPERIMENTS:
        parts = [f"{label:<24}"]
        for t in TOM_LEVELS:
            if t in summary[name]:
                m, lo, hi, n = summary[name][t]
                parts.append(f"{m:.4f}[{lo:.4f},{hi:.4f}](n={n})")
            else:
                parts.append("—")
        print(f"{parts[0]} {parts[1]:>22} {parts[2]:>22} {parts[3]:>22}")

    # ── 绘图 ──────────────────────────────────────────────────────
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    n_exp = len(EXPERIMENTS)
    n_groups = len(TOM_LEVELS)
    x_base = np.arange(n_exp)
    width = 0.75 / n_groups

    fig, ax = plt.subplots(figsize=(13, 6))

    for gi, t in enumerate(TOM_LEVELS):
        means, ci_lo, ci_hi = [], [], []
        for name, _ in EXPERIMENTS:
            s = summary[name].get(t)
            if s is None:
                means.append(0.0); ci_lo.append(0.0); ci_hi.append(0.0)
            else:
                m, lo, hi, _ = s
                means.append(m)
                ci_lo.append(max(0.0, m - lo))
                ci_hi.append(max(0.0, hi - m))

        offset = (gi - (n_groups - 1) / 2) * width
        bar_x = x_base + offset
        c = COLORS[t]

        ax.bar(bar_x, means, width * 0.92,
               yerr=np.array([ci_lo, ci_hi]),
               color=c, alpha=0.85,
               edgecolor="black", linewidth=0.4,
               capsize=3, error_kw={"linewidth": 0.9, "ecolor": "#333"},
               label=LABELS[t], zorder=3)

    # λ=1 参考线（厌恶/偏好分界）
    ax.axhline(1.0, color="#888888", linewidth=1.0,
               linestyle="--", zorder=2, alpha=0.8)
    ax.text(n_exp - 0.4, 1.02, "λ=1（分界）",
            ha="right", va="bottom", fontsize=9, color="#666")

    ax.set_xticks(x_base)
    ax.set_xticklabels([lb for _, lb in EXPERIMENTS],
                       fontsize=10, rotation=0)
    ax.set_xlabel("实验（ToM0 : ToM1 : ToM2 比例）", fontsize=11)
    ax.set_ylabel("损失厌恶系数 λ", fontsize=11)
    ax.set_title("各实验 · 按心智层级的损失厌恶系数均值",
                 fontsize=13, pad=12)
    ax.grid(True, alpha=0.25, axis="y")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(bottom=0)

    ax.legend(fontsize=10, loc="upper right", framealpha=0.92)

    fig.text(0.5, 0.01,
             "柱高 = 每 Agent 末期 λ 估计的均值；"
             "误差条 = 95% bootstrap CI；"
             "λ = avg(|realized_loss_pct|) / avg(|realized_gain_pct|)",
             ha="center", fontsize=8, color="#555")

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    out_png = OUT_DIR / "损失厌恶系数_多实验对比.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n对比图: {out_png}")

    # JSON
    out_json = OUT_DIR / "损失厌恶系数_汇总.json"
    json_summary = {}
    for name, label in EXPERIMENTS:
        json_summary[label] = {}
        for t, (m, lo, hi, n) in summary[name].items():
            json_summary[label][f"ToM{t}"] = {
                "lambda_mean": round(m, 6),
                "ci_95": [round(lo, 6), round(hi, 6)],
                "n_agents": n,
            }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(json_summary, f, ensure_ascii=False, indent=2)
    print(f"汇总 JSON: {out_json}")


if __name__ == "__main__":
    main()
