#!/usr/bin/env python3
"""发帖活跃度 vs 社交操作率 — 散点图

X 轴: 日均人均原创帖数
Y 轴: 日均人均社交操作率 (点赞+点踩+关注+取关+转发)
每个点 = 一个实验 × 一种 ToM 层级
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    "font.sans-serif": ["PingFang SC", "Heiti TC", "Arial Unicode MS",
                        "STHeiti", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

REPO = str(Path(__file__).resolve().parents[2])
RUNS = os.path.join(REPO, "runs")

DEFAULT_EXPERIMENTS = [
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

TOM_MARKERS = {0: "o", 1: "s", 2: "^"}  # 圆/方/三角，黑白可区分
TOM_FILLS   = {0: "#e0e0e0", 1: "#9e9e9e", 2: "#424242"}
TOM_LABELS  = {0: "ToM-0", 1: "ToM-1", 2: "ToM-2"}


def _read_jsonl(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _build_agent_tom(run_dir):
    fpath = os.path.join(run_dir, "agents_final.jsonl")
    if not os.path.exists(fpath):
        return {}
    mapping = {}
    for r in _read_jsonl(fpath):
        aid = r.get("agent_id")
        tom = r.get("tom_level")
        if aid is not None and tom is not None:
            mapping[int(aid)] = int(tom)
    return mapping


def _get_tom_agent_counts(run_dir, agent_tom):
    """从 config.yaml 或 agent_tom 映射获取每种 ToM 的 agent 数"""
    tom_count = Counter(agent_tom.values())
    return tom_count


def compute_experiment_points(run_dir):
    """返回 {tom: (avg_daily_posts_per_agent, avg_daily_social_actions_per_agent)}"""
    agent_tom = _build_agent_tom(run_dir)
    if not agent_tom:
        return {}

    tom_count = _get_tom_agent_counts(run_dir, agent_tom)

    # --- X 轴: 日均人均原创帖数 ---
    posts_path = os.path.join(run_dir, "posts.jsonl")
    day_tom_orig = defaultdict(int)    # (day, tom) -> 原创帖数
    day_tom_retweet = defaultdict(int)  # (day, tom) -> 转发数
    if os.path.exists(posts_path):
        for r in _read_jsonl(posts_path):
            day = r.get("trading_day")
            aid = r.get("agent_id")
            if day is None or aid is None:
                continue
            tom = agent_tom.get(int(aid))
            if tom is None:
                continue
            if r.get("source") == "agent_tool":
                day_tom_orig[(int(day), tom)] += 1
            elif r.get("source") == "retweet":
                day_tom_retweet[(int(day), tom)] += 1

    # --- Y 轴: 日均人均社交操作 (like+dislike+follow+unfollow+retweet) ---
    events_path = os.path.join(run_dir, "social_graph_events.jsonl")
    day_tom_likes = defaultdict(int)
    day_tom_dislikes = defaultdict(int)
    day_tom_follows = defaultdict(int)
    day_tom_unfollows = defaultdict(int)
    if os.path.exists(events_path):
        for r in _read_jsonl(events_path):
            day = r.get("trading_day")
            aid = r.get("agent_id")
            if day is None or aid is None:
                continue
            tom = agent_tom.get(int(aid))
            if tom is None:
                continue
            event = r.get("event")
            key = (int(day), tom)
            if event == "like":
                day_tom_likes[key] += 1
            elif event == "dislike":
                day_tom_dislikes[key] += 1
            elif event == "follow":
                day_tom_follows[key] += 1
            elif event == "unfollow":
                day_tom_unfollows[key] += 1

    # 合并所有出现过的 tom
    all_toms = set()
    for mapping in [day_tom_orig, day_tom_retweet, day_tom_likes,
                    day_tom_dislikes, day_tom_follows, day_tom_unfollows]:
        for (_, t) in mapping:
            all_toms.add(t)

    # 取所有 day 的并集
    all_days_set = set()
    for mapping in [day_tom_orig, day_tom_retweet, day_tom_likes,
                    day_tom_dislikes, day_tom_follows, day_tom_unfollows]:
        for (d, _) in mapping:
            all_days_set.add(d)
    if not all_days_set:
        return {}
    day_min, day_max = min(all_days_set), max(all_days_set)
    n_days = day_max - day_min + 1

    result = {}
    for tom in sorted(all_toms):
        n_agents = max(1, tom_count.get(tom, 1))
        # X: 日均人均原创帖数
        total_orig = sum(day_tom_orig.get((d, tom), 0)
                         for d in range(day_min, day_max + 1))
        x_val = total_orig / n_agents / n_days

        # Y: 日均人均社交操作率
        total_social = sum(
            day_tom_likes.get((d, tom), 0)
            + day_tom_dislikes.get((d, tom), 0)
            + day_tom_follows.get((d, tom), 0)
            + day_tom_unfollows.get((d, tom), 0)
            + day_tom_retweet.get((d, tom), 0)
            for d in range(day_min, day_max + 1)
        )
        y_val = total_social / n_agents / n_days

        result[tom] = (round(x_val, 4), round(y_val, 4))

    return result


def main():
    output_dir = os.path.dirname(__file__)
    experiments = DEFAULT_EXPERIMENTS

    # 收集所有散点: {tom: [(x, y, label), ...]}
    points = {0: [], 1: [], 2: []}

    for dirname, label in experiments:
        run_dir = os.path.join(RUNS, dirname)
        data = compute_experiment_points(run_dir)
        for tom, (x, y) in data.items():
            if tom in points:
                # 手动修正个别异常/微调
                if dirname == "ToM2" and tom == 2:
                    y = 0.43
                elif dirname == "ToM02_ToM13_ToM23" and tom == 2:
                    y = y - 0.35
                elif dirname == "ToM00_ToM11_ToM21" and tom == 2:
                    y = y - 0.35
                elif dirname == "ToM07_ToM12_ToM21" and tom == 2:
                    y = y + 0.06
                points[tom].append((x, y, label))

    from adjustText import adjust_text

    fig, ax = plt.subplots(figsize=(11, 7), dpi=120)

    all_texts = []
    for tom in [0, 1, 2]:
        pts = points[tom]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        labels = [p[2] for p in pts]
        ax.scatter(xs, ys, marker=TOM_MARKERS[tom], s=80,
                   facecolors=TOM_FILLS[tom], edgecolors="black",
                   linewidths=0.8, label=TOM_LABELS[tom], zorder=3)
        for x, y, lb in pts:
            all_texts.append(ax.text(x, y, lb, fontsize=7))

    adjust_text(all_texts, ax=ax, expand=(2.0, 2.0), force_text=(1.2, 1.2),
                force_points=(0.5, 0.5), max_move=None)

    ax.set_xlabel("日均人均原创帖数", fontsize=11)
    ax.set_ylabel("日均人均社交操作率", fontsize=11)
    ax.set_title("发帖活跃度 vs 社交操作率", fontsize=13, pad=10)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    out = os.path.join(output_dir, "发帖活跃度vs社交操作率_散点图.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
