#!/usr/bin/env python3
"""有社交 vs 无社交 · 持仓分散度哑铃图对比。

配对实验（纯 ToM 与 1:1:1 混合）：
  - ToM0           ↔ ToM0_无社交
  - ToM1           ↔ ToM1_无社交
  - ToM2           ↔ ToM2_无社交
  - ToM01_ToM11_ToM21 (1:1:1) ↔ ToM01_ToM11_ToM21_无社交

主量：每个 (run × ToM 切片) 的 Agent 级 N_eff = 1/mean_hhi。
数据口径与 compute_underdiversification.py 一致：
 - 剔除 trading_day < 3 预热期
 - 排除 holdings_count == 0 空仓事件
 - 每 Agent 先算自己的 HHI 时均，再跨 Agent 平均

图样式参考 evaluation/loss_aversion_by_tom/plot_loss_aversion_social_compare.py。
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO / "runs"
OUT_DIR = Path(__file__).parent
DATA_JSON = OUT_DIR / "有无社交持仓分散度_数据.json"
PNG = OUT_DIR / "有无社交持仓分散度_哑铃对比.png"

WARMUP_DAYS = 3

# (tom_level, social_run, nosocial_run)
PURE_PAIRS = [
    (0, "ToM0", "ToM0_无社交"),
    (1, "ToM1", "ToM1_无社交"),
    (2, "ToM2", "ToM2_无社交"),
]
MIXED_PAIR = ("ToM01_ToM11_ToM21", "ToM01_ToM11_ToM21_无社交")

COLOR_NOSOCIAL = "#e0e0e0"
COLOR_SOCIAL = "#424242"
COLOR_LINK = "#999999"


def per_agent_hhi(run_name: str) -> dict[int, dict[int, float]]:
    """读取一个 run，返回 {tom_level: {agent_id: hhi_time_mean}}。"""
    path = RUNS_DIR / run_name / "behavioral_biases.jsonl"
    per_agent: dict[int, list[float]] = defaultdict(list)
    agent_tom: dict[int, int] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            day = r.get("trading_day")
            if day is not None and day < WARMUP_DAYS:
                continue
            aid = r.get("agent_id")
            tom = r.get("tom_level")
            hc = r.get("holdings_count")
            hhi = r.get("portfolio_hhi")
            if aid is None or tom is None:
                continue
            agent_tom[aid] = int(tom)
            if hc == 0 or hhi is None or not isinstance(hhi, (int, float)):
                continue
            per_agent[aid].append(float(hhi))

    by_tom: dict[int, dict[int, float]] = defaultdict(dict)
    for aid, xs in per_agent.items():
        if not xs:
            continue
        by_tom[agent_tom[aid]][aid] = sum(xs) / len(xs)
    return by_tom


def group_neff(hhi_map: dict[int, float]) -> tuple[float, float, int]:
    """输入 {agent_id: hhi}，返回 (mean_hhi, n_eff, n_agents)。"""
    if not hhi_map:
        return float("nan"), float("nan"), 0
    xs = list(hhi_map.values())
    m = sum(xs) / len(xs)
    return m, 1.0 / m, len(xs)


def compute() -> tuple[list, dict]:
    rows = []
    per_agent_out: dict = {}

    mixed_s, mixed_ns = MIXED_PAIR
    mixed_s_data = per_agent_hhi(mixed_s)
    mixed_ns_data = per_agent_hhi(mixed_ns)

    for tom, social_run, nosocial_run in PURE_PAIRS:
        s_data = per_agent_hhi(social_run).get(tom, {})
        ns_data = per_agent_hhi(nosocial_run).get(tom, {})
        m_s, ne_s, n_s = group_neff(s_data)
        m_ns, ne_ns, n_ns = group_neff(ns_data)
        rows.append(("纯 ToM%d" % tom, tom, m_ns, m_s, ne_ns, ne_s, n_ns, n_s))

        # 1:1:1 对应 tom 切片
        s_mix = mixed_s_data.get(tom, {})
        ns_mix = mixed_ns_data.get(tom, {})
        m_s2, ne_s2, n_s2 = group_neff(s_mix)
        m_ns2, ne_ns2, n_ns2 = group_neff(ns_mix)
        rows.append(("1:1:1", tom, m_ns2, m_s2, ne_ns2, ne_s2, n_ns2, n_s2))

        per_agent_out.setdefault(social_run, {})[str(tom)] = list(s_data.values())
        per_agent_out.setdefault(nosocial_run, {})[str(tom)] = list(ns_data.values())
        per_agent_out.setdefault(mixed_s, {})[str(tom)] = list(s_mix.values())
        per_agent_out.setdefault(mixed_ns, {})[str(tom)] = list(ns_mix.values())

    return rows, per_agent_out


def save_json(rows: list, per_agent: dict) -> None:
    mixed_s, mixed_ns = MIXED_PAIR
    payload = {
        "schema": "diversification_social_compare",
        "description": "有/无社交 × (纯 ToM / 1:1:1 混合) 的 N_eff = 1/HHI 对比（Agent 级聚合）",
        "method": {
            "warmup_days_skipped": WARMUP_DAYS,
            "exclude_empty_portfolio": True,
            "aggregation": "per_agent_time_mean_then_group_mean",
            "metric": "n_eff = 1 / mean_hhi",
        },
        "pure_pairs": [
            {"tom": t, "social_run": s, "nosocial_run": ns}
            for t, s, ns in PURE_PAIRS
        ],
        "mixed_pair": {"social_run": mixed_s, "nosocial_run": mixed_ns},
        "points": [
            {
                "group": label, "tom": tom,
                "nosocial_mean_hhi": None if np.isnan(m_ns) else round(m_ns, 4),
                "social_mean_hhi": None if np.isnan(m_s) else round(m_s, 4),
                "nosocial_n_eff": None if np.isnan(ne_ns) else round(ne_ns, 3),
                "social_n_eff": None if np.isnan(ne_s) else round(ne_s, 3),
                "delta_n_eff": (None if (np.isnan(ne_ns) or np.isnan(ne_s))
                                else round(float(ne_s - ne_ns), 3)),
                "n_agents_nosocial": n_ns,
                "n_agents_social": n_s,
            }
            for label, tom, m_ns, m_s, ne_ns, ne_s, n_ns, n_s in rows
        ],
        "per_agent_hhi": per_agent,
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"数据写入: {DATA_JSON}")


def load_json() -> list:
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        p = json.load(f)
    rows = []
    for pt in p["points"]:
        ne_ns = pt["nosocial_n_eff"]
        ne_s = pt["social_n_eff"]
        m_ns = pt["nosocial_mean_hhi"]
        m_s = pt["social_mean_hhi"]
        rows.append((
            pt["group"], int(pt["tom"]),
            float("nan") if m_ns is None else float(m_ns),
            float("nan") if m_s is None else float(m_s),
            float("nan") if ne_ns is None else float(ne_ns),
            float("nan") if ne_s is None else float(ne_s),
            int(pt["n_agents_nosocial"]), int(pt["n_agents_social"]),
        ))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="忽略缓存 JSON，重新从 behavioral_biases.jsonl 计算")
    args = ap.parse_args()

    if DATA_JSON.exists() and not args.rebuild:
        print(f"从缓存 JSON 读取: {DATA_JSON}")
        rows = load_json()
    else:
        rows, per_agent = compute()
        save_json(rows, per_agent)

    # 打印
    print("\nAgent 级聚合结果 (N_eff = 1/mean_hhi):")
    hdr = (f"{'分组':<10}{'ToM':>4}{'无社交 N_eff':>15}{'有社交 N_eff':>15}"
           f"{'ΔN_eff':>10}{'ns n_agt':>10}{'s n_agt':>10}")
    print(hdr)
    print("-" * len(hdr))
    for label, tom, _m_ns, _m_s, ne_ns, ne_s, n_ns, n_s in rows:
        ns_str = f"{ne_ns:.3f}" if not np.isnan(ne_ns) else "-"
        s_str = f"{ne_s:.3f}" if not np.isnan(ne_s) else "-"
        d = ne_s - ne_ns if not (np.isnan(ne_ns) or np.isnan(ne_s)) else float("nan")
        d_str = f"{d:+.3f}" if not np.isnan(d) else "-"
        print(f"{label:<10}{tom:>4}{ns_str:>15}{s_str:>15}"
              f"{d_str:>10}{n_ns:>10}{n_s:>10}")

    # ── 绘图 ─────────────────────────────────────────────────────
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    # 每 ToM 占 2 个 x 位置（纯 + 1:1:1），层级间留空
    x_positions, group_centers = [], []
    cursor = 0
    for gi in range(3):
        x_positions.append(cursor)
        x_positions.append(cursor + 1)
        group_centers.append(cursor + 0.5)
        cursor += 3

    labels = [r[0] for r in rows]
    nosocial_ne = np.array([r[4] for r in rows])
    social_ne = np.array([r[5] for r in rows])

    fig, ax = plt.subplots(figsize=(8.5, 5.0), dpi=150)

    # 连接线
    for i, x in enumerate(x_positions):
        ax.plot([x, x], [nosocial_ne[i], social_ne[i]],
                color=COLOR_LINK, linewidth=2, zorder=1)

    # 散点
    ax.scatter(x_positions, nosocial_ne, s=140, color=COLOR_NOSOCIAL,
               edgecolors="black", linewidths=0.9, zorder=2, label="无社交")
    ax.scatter(x_positions, social_ne, s=140, color=COLOR_SOCIAL,
               edgecolors="black", linewidths=0.9, zorder=2, label="有社交")

    # 数值标注
    for i, x in enumerate(x_positions):
        if not np.isnan(nosocial_ne[i]):
            ax.annotate(f"{nosocial_ne[i]:.2f}", (x, nosocial_ne[i]),
                        fontsize=9, ha="right", va="center",
                        xytext=(-10, 0), textcoords="offset points",
                        color="#555555")
        if not np.isnan(social_ne[i]):
            ax.annotate(f"{social_ne[i]:.2f}", (x, social_ne[i]),
                        fontsize=9, ha="left", va="center",
                        xytext=(10, 0), textcoords="offset points",
                        fontweight="bold")

    # 等权分散上限 N=10
    ax.axhline(10, color="#aaa", linewidth=1.0, linestyle="--",
               zorder=0, alpha=0.7)
    ax.text(x_positions[0] - 0.6, 10 + 0.05, "等权分散上限 N=10",
            fontsize=9, color="#666", ha="left", va="bottom")

    # 顶部 ToM 分组标注
    valid = np.concatenate([nosocial_ne[~np.isnan(nosocial_ne)],
                            social_ne[~np.isnan(social_ne)]])
    ymax_all = max(float(valid.max()) if len(valid) else 1.0, 6.0)
    for gi, center in enumerate(group_centers):
        ax.text(center, ymax_all * 1.12, f"ToM{gi}",
                ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#333333")

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, fontsize=9, rotation=0)
    ax.set_xlim(x_positions[0] - 0.7, x_positions[-1] + 0.7)
    ax.set_ylabel("有效持仓数  $N_{eff}=1/HHI$", fontsize=11)
    ax.set_ylim(0, 10 * 1.10)
    ax.set_title("有社交 vs 无社交 · 持仓分散度 $N_{eff}$ 对比",
                 fontsize=12, pad=12)

    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(fontsize=10, loc="upper right",
              bbox_to_anchor=(1.0, 0.88), framealpha=0.9)

    plt.tight_layout()
    fig.savefig(PNG, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\n对比图: {PNG}")


if __name__ == "__main__":
    main()
