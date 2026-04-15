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
import os
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

# ── 颜色方案 ──────────────────────────────────────────────────
TOM_COLORS = {0: "#78909c", 1: "#0288d1", 2: "#7c4dff"}
TOM_LABELS = {0: "ToM 0", 1: "ToM 1", 2: "ToM 2"}


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


def analyze_runs(runs_dir: Path, top_k: int = 10) -> list[dict]:
    """分析所有实验，返回每个实验的 Top-K 粉丝 ToM 构成。"""
    results = []
    for run_name in sorted(os.listdir(runs_dir)):
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
    """绘制堆叠柱状图：各实验 Top-K 粉丝的 ToM 构成。"""
    # 过滤掉 top_k_actual < 3 的短跑实验
    filtered = [r for r in results if r["top_k_actual"] >= 3]
    if not filtered:
        print("没有足够数据的实验（Top-K >= 3）")
        return

    # 按 ToM2 占比降序排列
    def tom2_ratio(r):
        total = r["top_k_actual"]
        return r["tom_counts"].get(2, 0) / total if total else 0
    filtered.sort(key=tom2_ratio, reverse=True)

    labels = []
    for r in filtered:
        dist = r["agent_tom_dist"]
        total = sum(dist.values())
        pcts = []
        for t in sorted(dist.keys()):
            pcts.append(f"T{t}:{dist[t]}")
        label = r["run_name"].replace("_预测拟合", "\n预测拟合").replace("_认知能否翻盘", "\n翻盘").replace("_资金不均等幂律分布", "\n幂律").replace("_无社交", "\n无社交").replace("_欺骗工具", "\n欺骗")
        labels.append(label)

    n = len(filtered)
    x = np.arange(n)
    bar_width = 0.6

    fig, ax = plt.subplots(figsize=(max(12, n * 0.8), 6))

    all_toms = sorted({t for r in filtered for t in r["tom_counts"]})
    bottoms = np.zeros(n)

    for tom in all_toms:
        values = []
        for r in filtered:
            total = r["top_k_actual"]
            count = r["tom_counts"].get(tom, 0)
            values.append(count / total * 100)
        values = np.array(values)
        bars = ax.bar(
            x, values, bar_width,
            bottom=bottoms,
            color=TOM_COLORS.get(tom, "#999"),
            label=TOM_LABELS.get(tom, f"ToM {tom}"),
            edgecolor="white",
            linewidth=0.5,
        )
        # 在柱子上标数量
        for i, (v, cnt_r) in enumerate(zip(values, filtered)):
            cnt = cnt_r["tom_counts"].get(tom, 0)
            if cnt > 0:
                ax.text(
                    x[i], bottoms[i] + v / 2,
                    str(cnt),
                    ha="center", va="center",
                    fontsize=9, fontweight="bold", color="white",
                )
        bottoms += values

    ax.set_ylabel("Top-K 中各 ToM 层级占比 (%)", fontsize=12)
    ax.set_title(f"各实验粉丝数 Top {top_k} 智能体的心智阶层构成", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    # 在柱子下方标注实验的 Agent ToM 分布
    for i, r in enumerate(filtered):
        dist = r["agent_tom_dist"]
        total = sum(dist.values())
        parts = []
        for t in sorted(dist.keys()):
            pct = dist[t] / total * 100
            parts.append(f"T{t}:{pct:.0f}%")
        ax.text(
            x[i], -8,
            " ".join(parts),
            ha="center", va="top",
            fontsize=7, color="#555",
            rotation=0,
        )

    plt.tight_layout()
    output_path = output_dir / f"top{top_k}_follower_tom_composition.png"
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"图表已保存: {output_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Top-K 粉丝数智能体 ToM 构成分析")
    parser.add_argument("--runs-dir", default="runs", help="实验目录 (default: runs)")
    parser.add_argument("--top-k", type=int, default=10, help="Top-K (default: 10)")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.exists():
        # 尝试仓库根目录
        runs_dir = Path(__file__).resolve().parents[2] / "runs"
    if not runs_dir.exists():
        print(f"找不到 runs 目录: {args.runs_dir}")
        sys.exit(1)

    output_dir = Path(__file__).resolve().parent
    results = analyze_runs(runs_dir, top_k=args.top_k)

    if not results:
        print("未找到有效实验数据")
        sys.exit(1)

    # 打印文本报告
    print(f"\n{'='*70}")
    print(f"各实验粉丝数 Top {args.top_k} 智能体的 ToM 构成")
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

    # 绘图
    plot_stacked_bar(results, args.top_k, output_dir)


if __name__ == "__main__":
    main()
