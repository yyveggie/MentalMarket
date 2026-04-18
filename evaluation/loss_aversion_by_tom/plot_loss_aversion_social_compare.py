#!/usr/bin/env python3
"""有社交 vs 无社交 · 损失厌恶 λ̂ 哑铃图对比（方案 A：筛选有效交易样本）。

数据流程：
 1. 从 trades.jsonl 重建每 agent 的已实现盈亏幅度列表
 2. 筛除交易退化样本（n_gain<3 或 avg_gain<1%）
 3. 剩余 agent 计算 λ̂，同组取均值

对比实验配对：
 - 纯 ToM0/1/2 有社交 vs 无社交
 - 1:1:1 混合中的 ToM0/1/2（有社交 vs 无社交）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).parent
DATA_JSON = OUT_DIR / "有无社交损失厌恶_数据.json"

# (tom_level, social_run_name, nosocial_run_name)
PURE_PAIRS = [
    (0, "ToM0", "ToM0_无社交"),
    (1, "ToM1", "ToM1_无社交"),
    (2, "ToM2", "ToM2_无社交"),
]
MIXED_PAIR = ("ToM01_ToM11_ToM21", "ToM01_ToM11_ToM21_无社交")

ALL_RUNS = [r for _, s, ns in PURE_PAIRS for r in (s, ns)] + list(MIXED_PAIR)

COLOR_NOSOCIAL = "#e0e0e0"  # 浅灰
COLOR_SOCIAL = "#424242"    # 深灰
COLOR_LINK = "#999999"


def mean_of(vals: list[float]) -> float:
    return float(np.mean(vals)) if vals else float("nan")


def compute_from_trades() -> tuple[list, dict]:
    """重新从 trades.jsonl 计算。返回 (rows, per_agent_lambdas)。"""
    from _trades_loader import collect_filtered_lambdas

    def _collect(run_name: str, tom: int) -> tuple[list[float], int]:
        by_tom = collect_filtered_lambdas(run_name)
        d = by_tom.get(tom, {'valid': [], 'n_total': 0})
        return d['valid'], d['n_total']

    print("从 trades.jsonl 重建并筛选 ...")
    for name in ALL_RUNS:
        print(f"  预缓存 {name}", flush=True)
        collect_filtered_lambdas(name)

    rows = []
    per_agent: dict[str, dict[str, list[float]]] = {}
    mixed_s, mixed_ns = MIXED_PAIR
    for tom, social_run, nosocial_run in PURE_PAIRS:
        s_vals, s_total = _collect(social_run, tom)
        ns_vals, ns_total = _collect(nosocial_run, tom)
        rows.append((f"纯 ToM{tom}", tom,
                     mean_of(ns_vals), mean_of(s_vals),
                     len(ns_vals), ns_total, len(s_vals), s_total))
        s_mix, s_mix_total = _collect(mixed_s, tom)
        ns_mix, ns_mix_total = _collect(mixed_ns, tom)
        rows.append(("1:1:1", tom,
                     mean_of(ns_mix), mean_of(s_mix),
                     len(ns_mix), ns_mix_total, len(s_mix), s_mix_total))
        per_agent.setdefault(social_run, {})[str(tom)] = s_vals
        per_agent.setdefault(nosocial_run, {})[str(tom)] = ns_vals
        per_agent.setdefault(mixed_s, {})[str(tom)] = s_mix
        per_agent.setdefault(mixed_ns, {})[str(tom)] = ns_mix

    return rows, per_agent


def save_json(rows: list, per_agent: dict) -> None:
    mixed_s, mixed_ns = MIXED_PAIR
    payload = {
        "schema": "loss_aversion_social_compare",
        "description": "有/无社交 × (纯 ToM / 1:1:1 混合) 的 λ̂ 均值对比",
        "filter": {"min_gain_count": 3, "min_avg_gain_pct": 0.01},
        "pure_pairs": [
            {"tom": t, "social_run": s, "nosocial_run": ns}
            for t, s, ns in PURE_PAIRS
        ],
        "mixed_pair": {"social_run": mixed_s, "nosocial_run": mixed_ns},
        "points": [
            {
                "group": label, "tom": tom,
                "nosocial_mean": None if np.isnan(ns) else ns,
                "social_mean": None if np.isnan(s) else s,
                "delta": (None if (np.isnan(ns) or np.isnan(s))
                          else float(s - ns)),
                "n_valid_nosocial": nv, "n_total_nosocial": nt,
                "n_valid_social": sv, "n_total_social": st,
            }
            for label, tom, ns, s, nv, nt, sv, st in rows
        ],
        "per_agent_lambdas": per_agent,
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"绘图数据已写入: {DATA_JSON}")


def load_json() -> list:
    """从缓存 JSON 恢复 rows。"""
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = []
    for p in payload["points"]:
        ns = p["nosocial_mean"]
        s = p["social_mean"]
        rows.append((
            p["group"], int(p["tom"]),
            float("nan") if ns is None else float(ns),
            float("nan") if s is None else float(s),
            int(p["n_valid_nosocial"]), int(p["n_total_nosocial"]),
            int(p["n_valid_social"]), int(p["n_total_social"]),
        ))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="忽略缓存 JSON，重新从 trades.jsonl 计算")
    args = ap.parse_args()

    if DATA_JSON.exists() and not args.rebuild:
        print(f"从缓存 JSON 读取: {DATA_JSON}")
        rows = load_json()
    else:
        rows, per_agent = compute_from_trades()
        save_json(rows, per_agent)

    # 打印
    print("\n筛选后结果（方案 A: n_gain≥3 且 avg_gain≥1%）:")
    hdr = f"{'分组':<10}{'ToM':>5}{'无社交 λ̂':>14}{'有社交 λ̂':>14}"
    hdr += f"{'ns valid/total':>18}{'s valid/total':>18}"
    print(hdr)
    print("-" * 90)
    for label, tom, ns, s, nv, nt, sv, st in rows:
        ns_str = f"{ns:.3f}" if not np.isnan(ns) else "-"
        s_str = f"{s:.3f}" if not np.isnan(s) else "-"
        print(f"{label:<10}{tom:>5}{ns_str:>14}{s_str:>14}"
              f"{nv:>9}/{nt:<8}{sv:>9}/{st:<8}")

    # ── 绘图 ─────────────────────────────────────────────────────
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    # x 位置：每个 ToM 层级占 2 个位置，层级间留空
    x_positions = []
    group_centers = []
    cursor = 0
    for gi in range(3):
        x_positions.append(cursor)
        x_positions.append(cursor + 1)
        group_centers.append(cursor + 0.5)
        cursor += 3

    labels = [label for label, _, _, _, _, _, _, _ in rows]
    nosocial = np.array([r[2] for r in rows])
    social = np.array([r[3] for r in rows])

    fig, ax = plt.subplots(figsize=(8.5, 5.0), dpi=150)

    # 连接线
    for i, x in enumerate(x_positions):
        ax.plot([x, x], [nosocial[i], social[i]],
                color=COLOR_LINK, linewidth=2, zorder=1)

    # 散点
    ax.scatter(x_positions, nosocial, s=140, color=COLOR_NOSOCIAL,
               edgecolors="black", linewidths=0.9, zorder=2,
               label="无社交")
    ax.scatter(x_positions, social, s=140, color=COLOR_SOCIAL,
               edgecolors="black", linewidths=0.9, zorder=2,
               label="有社交")

    # 数值标注：无社交标左，有社交标右
    for i, x in enumerate(x_positions):
        if not np.isnan(nosocial[i]):
            ax.annotate(f"{nosocial[i]:.2f}", (x, nosocial[i]), fontsize=9,
                        ha="right", va="center",
                        xytext=(-10, 0), textcoords="offset points",
                        color="#555555")
        if not np.isnan(social[i]):
            ax.annotate(f"{social[i]:.2f}", (x, social[i]), fontsize=9,
                        ha="left", va="center",
                        xytext=(10, 0), textcoords="offset points",
                        fontweight="bold")

    # λ̂=1 分界线
    ax.axhline(1.0, color="#888", linewidth=1.0,
               linestyle="--", zorder=0, alpha=0.6)

    # 顶部 ToM 分组标注
    valid_ns = nosocial[~np.isnan(nosocial)]
    valid_s = social[~np.isnan(social)]
    ymax_all = max(valid_ns.max() if len(valid_ns) else 0.01,
                   valid_s.max() if len(valid_s) else 0.01)
    for gi, center in enumerate(group_centers):
        ax.text(center, ymax_all * 1.15, f"ToM{gi}",
                ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#333333")

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, fontsize=9, rotation=0)
    ax.set_xlim(x_positions[0] - 0.7, x_positions[-1] + 0.7)
    ax.set_ylabel("损失厌恶代理指标 λ̂", fontsize=11)
    ax.set_ylim(0, ymax_all * 1.28)
    ax.set_title("有社交 vs 无社交 · 损失厌恶 λ̂ 对比",
                 fontsize=12, pad=12)

    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(fontsize=10, loc="upper right",
              bbox_to_anchor=(1.0, 0.88), framealpha=0.9)

    plt.tight_layout()
    out_png = OUT_DIR / "有无社交损失厌恶_哑铃对比.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\n对比图: {out_png}")


if __name__ == "__main__":
    main()
