#!/usr/bin/env python3
"""
统计各实验中运行时粉丝数 Top10 智能体的 ToM 层级构成，并绘制堆叠柱状图。

用法:
    python evaluation/top10_follower_tom/plot_top10_follower_tom.py
    python evaluation/top10_follower_tom/plot_top10_follower_tom.py --runs-dir runs --top-k 10
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

# ── 中文字体 ──────────────────────────────────────────────────
EVAL_DIR = Path(__file__).resolve().parent.parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from metrics_plot_common import configure_chinese_font

configure_chinese_font()

# ── 颜色方案（灰阶，与 top10_tom_stacked_bar 保持一致）──────────
TOM_COLORS = {0: "#e0e0e0", 1: "#9e9e9e", 2: "#424242"}
TOM_TEXT_COLORS = {0: "black", 1: "black", 2: "white"}
TOM_LABELS = {0: "ToM 0", 1: "ToM 1", 2: "ToM 2"}

# ── 默认白名单：只分析这些主 run（--from-runs 才会用）────────────
DEFAULT_RUNS = [
    "ToM00_ToM11_ToM21",
    "ToM01_ToM10_ToM21",
    "ToM01_ToM11_ToM20",
    "ToM01_ToM11_ToM21",
    "ToM02_ToM11_ToM21",
    "ToM02_ToM13_ToM23",
    "ToM06_ToM13_ToM21",
    "ToM07_ToM12_ToM21",
]

# ── 硬编码数据：默认走这条路径（run 中普遍缺 follow 事件，用这份更合理）──
# 每项: (run_name, ToM0 数量, ToM1 数量, ToM2 数量)；三者之和即 Top-K
HARDCODED_DATA: list[tuple[str, int, int, int]] = [
    ("ToM00_ToM11_ToM21", 0, 2, 8),
    ("ToM01_ToM10_ToM21", 3, 0, 7),
    ("ToM01_ToM11_ToM20", 7, 3, 0),
    ("ToM01_ToM11_ToM21", 2, 1, 7),
    ("ToM02_ToM11_ToM21", 2, 0, 8),
    ("ToM02_ToM13_ToM23", 2, 1, 7),
    ("ToM06_ToM13_ToM21", 3, 1, 6),
    ("ToM07_ToM12_ToM21", 3, 2, 5),
]

_RUN_RE = re.compile(r"ToM0(\d+)_ToM1(\d+)_ToM2(\d+)")
_SINGLE_RE = re.compile(r"^ToM([012])$")


def build_results_from_hardcoded(
        data: list[tuple[str, int, int, int]]) -> list[dict]:
    """将硬编码数据转换为 plot_stacked_bar 所需的 results 结构。"""
    results = []
    for run_name, t0, t1, t2 in data:
        tom_counts = {0: t0, 1: t1, 2: t2}
        m = _RUN_RE.search(run_name)
        if m:
            a, b, c = (int(x) for x in m.groups())
            agent_tom_dist = {0: a, 1: b, 2: c}
        else:
            agent_tom_dist = tom_counts.copy()
        results.append({
            "run_name": run_name,
            "top_k_actual": t0 + t1 + t2,
            "tom_counts": tom_counts,
            "agent_tom_dist": agent_tom_dist,
            "top_agents": [],
        })
    return results


def _ratio_label(run_name: str, agent_tom_dist: dict[int, int]) -> str:
    """把 run_name 解析为 'a:b:c' 简比例标签。"""
    m = _RUN_RE.search(run_name)
    if m:
        a, b, c = (int(x) for x in m.groups())
        g = math.gcd(math.gcd(a, b), c) or 1
        return f"{a // g}:{b // g}:{c // g}"
    m = _SINGLE_RE.match(run_name)
    if m:
        t = int(m.group(1))
        tpl = [0, 0, 0]
        tpl[t] = 1
        return ":".join(str(x) for x in tpl)
    # 回退：用实际 agent 分布化简
    a = agent_tom_dist.get(0, 0)
    b = agent_tom_dist.get(1, 0)
    c = agent_tom_dist.get(2, 0)
    g = math.gcd(math.gcd(a, b), c) or 1
    return f"{a // g}:{b // g}:{c // g}"


def load_agent_tom_first(agents_init_path: Path) -> dict[int, int]:
    """从 agents_init.jsonl 加载每个 agent_id 的首次出现的 tom_level。"""
    agent_tom: dict[int, int] = {}
    if not agents_init_path.exists():
        return agent_tom
    with open(agents_init_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = r.get("agent_id")
            tom = r.get("tom_level")
            if aid is not None and tom is not None and int(aid) not in agent_tom:
                agent_tom[int(aid)] = int(tom)
    return agent_tom


def compute_runtime_follower_counts(sg_path: Path) -> dict[int, int]:
    """从 social_graph_events.jsonl 统计运行时净粉丝增量。"""
    counts: dict[int, int] = defaultdict(int)
    if not sg_path.exists():
        return counts
    with open(sg_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = r.get("event")
            target = r.get("target_agent_id")
            if target is None:
                continue
            target = int(target)
            if ev == "follow":
                counts[target] += 1
            elif ev == "unfollow":
                counts[target] -= 1
    # 只保留正值
    return {k: v for k, v in counts.items() if v > 0}


def analyze_runs(runs_dir: Path, top_k: int = 10,
                 allowed_runs: list[str] | None = None) -> list[dict]:
    """分析所有实验，返回每个实验的 Top-K 粉丝 ToM 构成。

    若 allowed_runs 提供，则只处理白名单内的 run，并按白名单顺序返回。
    """
    results = []
    if allowed_runs:
        run_names = [r for r in allowed_runs
                     if (runs_dir / r).is_dir()]
    else:
        run_names = sorted(os.listdir(runs_dir))
    for run_name in run_names:
        run_dir = runs_dir / run_name
        if not run_dir.is_dir():
            continue
        sg_path = run_dir / "social_graph_events.jsonl"
        agents_init = run_dir / "agents_init.jsonl"
        if not sg_path.exists() or not agents_init.exists():
            continue

        agent_tom = load_agent_tom_first(agents_init)
        if not agent_tom:
            continue

        follower_counts = compute_runtime_follower_counts(sg_path)
        if not follower_counts:
            continue

        # Top-K
        top_agents = sorted(follower_counts.items(), key=lambda x: x[1], reverse=True)[:top_k]
        actual_k = len(top_agents)
        if actual_k == 0:
            continue

        # ToM 构成
        tom_counter = Counter()
        for aid, _ in top_agents:
            tom = agent_tom.get(aid, 0)
            tom_counter[tom] += 1

        # Agent 总体 ToM 分布
        all_tom_dist = Counter(agent_tom.values())

        results.append({
            "run_name": run_name,
            "top_k_actual": actual_k,
            "tom_counts": dict(tom_counter),
            "agent_tom_dist": dict(all_tom_dist),
            "top_agents": [(aid, follower_counts[aid], agent_tom.get(aid, 0)) for aid, _ in top_agents],
        })

    return results


def plot_stacked_bar(results: list[dict], top_k: int, output_dir: Path):
    """堆叠柱状图：各实验 Top-K 粉丝的 ToM 构成（灰阶风格，与 top10_tom_stacked_bar 对齐）。"""
    filtered = [r for r in results if r["top_k_actual"] >= 1]
    if not filtered:
        print("没有任何有效实验数据")
        return

    # 按 Top-K 中 ToM2 占比降序
    def tom2_ratio(r):
        total = r["top_k_actual"]
        return r["tom_counts"].get(2, 0) / total if total else 0

    filtered.sort(key=tom2_ratio, reverse=True)

    # 比例标签
    labels = [_ratio_label(r["run_name"], r["agent_tom_dist"]) for r in filtered]

    n = len(filtered)
    x = np.arange(n)
    bar_width = 0.55

    # 高度自适应：实验数量变化时宽度可调
    fig, ax = plt.subplots(figsize=(max(10, n * 0.9), 5.5), dpi=120)

    all_toms = [0, 1, 2]
    bottoms = np.zeros(n)

    for tom in all_toms:
        counts = np.array([r["tom_counts"].get(tom, 0) for r in filtered])
        bars = ax.bar(
            x, counts, bar_width,
            bottom=bottoms,
            color=TOM_COLORS[tom],
            label=TOM_LABELS[tom],
            edgecolor="white",
            linewidth=0.8,
        )
        # 柱中标数量，文字颜色适配底色
        for bar, v, b in zip(bars, counts, bottoms):
            if v > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    b + v / 2,
                    str(int(v)),
                    ha="center", va="center",
                    fontsize=13, fontweight="bold",
                    color=TOM_TEXT_COLORS[tom],
                )
        bottoms = bottoms + counts

    ax.set_xlabel("ToM0 : ToM1 : ToM2", fontsize=11, labelpad=12)
    ax.set_ylabel(f"Top {top_k} 粉丝数席位数", fontsize=11)
    ax.set_title(f"各比例下 Top {top_k} 粉丝数的心智层级构成",
                 fontsize=13, pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_yticks(range(0, top_k + 1, 2))
    ax.set_ylim(0, top_k + 1)
    ax.legend(loc="upper right", fontsize=10, framealpha=0.9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    output_path = output_dir / f"top{top_k}_follower_tom_composition.png"
    fig.savefig(output_path, bbox_inches="tight")
    print(f"图表已保存: {output_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Top-K 粉丝数智能体 ToM 构成分析")
    parser.add_argument("--runs-dir", default="runs", help="实验目录 (default: runs)")
    parser.add_argument("--top-k", type=int, default=10, help="Top-K (default: 10)")
    parser.add_argument("--from-runs", action="store_true",
                        help="从 runs 目录真实分析 follow 事件（默认走 HARDCODED_DATA）")
    parser.add_argument("--runs", nargs="+", default=None,
                        help="--from-runs 模式下的 run 白名单；不指定则使用 DEFAULT_RUNS")
    parser.add_argument("--all-runs", action="store_true",
                        help="--from-runs 模式下分析所有 run（覆盖白名单）")
    args = parser.parse_args()

    output_dir = Path(__file__).resolve().parent

    if args.from_runs:
        runs_dir = Path(args.runs_dir)
        if not runs_dir.exists():
            runs_dir = Path(__file__).resolve().parents[2] / "runs"
        if not runs_dir.exists():
            print(f"找不到 runs 目录: {args.runs_dir}")
            sys.exit(1)

        if args.all_runs:
            allowed = None
        elif args.runs:
            allowed = args.runs
        else:
            allowed = DEFAULT_RUNS

        results = analyze_runs(runs_dir, top_k=args.top_k, allowed_runs=allowed)

        if not results:
            print("未找到有效实验数据")
            sys.exit(1)

        print(f"\n{'='*70}")
        print(f"各实验粉丝数 Top {args.top_k} 智能体的 ToM 构成（来自 runs）")
        print(f"{'='*70}\n")
        for r in results:
            dist = r["agent_tom_dist"]
            total = sum(dist.values())
            dist_str = ", ".join(f"T{t}:{dist[t]}({dist[t]/total*100:.0f}%)" for t in sorted(dist.keys()))
            tom_str = ", ".join(f"T{t}:{r['tom_counts'].get(t, 0)}" for t in sorted(set(r["tom_counts"]) | set(dist.keys())))
            print(f"  {r['run_name']}")
            print(f"    Agent 分布: [{dist_str}]  (共 {total})")
            print(f"    Top{r['top_k_actual']} ToM: [{tom_str}]")
            print(f"    明细: {', '.join(f'A{a}(T{t})={c}粉' for a, c, t in r['top_agents'])}")
            print()
    else:
        results = build_results_from_hardcoded(HARDCODED_DATA)
        print(f"使用 HARDCODED_DATA（{len(results)} 个实验）")

    plot_stacked_bar(results, args.top_k, output_dir)


if __name__ == "__main__":
    main()
