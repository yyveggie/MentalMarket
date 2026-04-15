#!/usr/bin/env python3
"""
统计各实验中、各 ToM 层级的正 / 负 / 中性情绪占比，并画图。

用法:
    python evaluation/sentiment_by_tom/plot_sentiment_by_tom.py [--runs-dir runs]
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# 让 evaluation/ 下的公共模块可被导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metrics_plot_common import configure_chinese_font

# ── 常量 ──────────────────────────────────────────────
NEUTRAL_THRESHOLD = 0.2          # 与 reputation.py 一致
SENTIMENT_FILE = "sentiment_series.jsonl"
OUT_DIR = Path(__file__).parent

# ── 数据读取 ──────────────────────────────────────────

def _load_sentiment_records(run_dir: Path) -> list[dict]:
    """读取某个实验的 sentiment_series.jsonl。"""
    fp = run_dir / SENTIMENT_FILE
    if not fp.exists():
        return []
    rows: list[dict] = []
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _classify(sentiment: float) -> str:
    """将 sentiment 值分类为正/负/中性。"""
    if sentiment > NEUTRAL_THRESHOLD:
        return "positive"
    elif sentiment < -NEUTRAL_THRESHOLD:
        return "negative"
    else:
        return "neutral"


# ── 统计 ─────────────────────────────────────────────

def compute_stats(runs_dir: Path) -> dict:
    """
    返回:
        {
            experiment_name: {
                tom_level: {"positive": n, "negative": n, "neutral": n, "total": n},
                ...
            },
            ...
        }
    """
    results: dict = {}
    for exp_name in sorted(os.listdir(runs_dir)):
        exp_dir = runs_dir / exp_name
        if not exp_dir.is_dir():
            continue
        rows = _load_sentiment_records(exp_dir)
        if not rows:
            continue

        tom_counts: dict[int, dict[str, int]] = defaultdict(
            lambda: {"positive": 0, "negative": 0, "neutral": 0, "total": 0}
        )
        for r in rows:
            tom = int(r.get("tom_level", -1))
            sval = float(r.get("sentiment", 0.0))
            cat = _classify(sval)
            tom_counts[tom][cat] += 1
            tom_counts[tom]["total"] += 1

        results[exp_name] = dict(tom_counts)
    return results


# ── Console 输出 ──────────────────────────────────────

def print_report(stats: dict) -> None:
    sep = "=" * 70
    print(f"\n{sep}")
    print("各实验 · 各 ToM 层级的正/负/中性情绪统计")
    print(f"{sep}\n")

    for exp, tom_map in stats.items():
        print(f"  {exp}")
        for tom in sorted(tom_map):
            c = tom_map[tom]
            total = c["total"]
            pos_pct = c["positive"] / total * 100 if total else 0
            neg_pct = c["negative"] / total * 100 if total else 0
            neu_pct = c["neutral"] / total * 100 if total else 0
            print(
                f"    ToM{tom}: 总{total}条  "
                f"正={c['positive']}({pos_pct:.1f}%)  "
                f"负={c['negative']}({neg_pct:.1f}%)  "
                f"中性={c['neutral']}({neu_pct:.1f}%)"
            )
        print()


# ── 画图 ─────────────────────────────────────────────

def plot_sentiment_composition(stats: dict, out_path: Path) -> None:
    """
    水平分组柱状图：
    - X 轴: 实验名（按 exp 排列，每个 exp 下按 ToM 分组）
    - Y 轴: 百分比
    - 颜色: 正(绿) / 负(红) / 中性(灰)
    """
    # 收集数据
    experiments = list(stats.keys())
    # 获取所有 ToM levels
    all_toms = sorted({tom for m in stats.values() for tom in m})

    n_exp = len(experiments)
    n_tom = len(all_toms)
    if n_exp == 0:
        print("无有效数据，跳过画图。")
        return

    fig, ax = plt.subplots(figsize=(max(14, n_exp * 1.2), 7))

    group_width = 0.8
    bar_width = group_width / max(n_tom, 1)
    x_base = np.arange(n_exp)

    colors_pos = {0: "#66bb6a", 1: "#2e7d32", 2: "#1b5e20"}     # 绿色系
    colors_neg = {0: "#ef5350", 1: "#c62828", 2: "#8e0000"}     # 红色系
    colors_neu = {0: "#bdbdbd", 1: "#9e9e9e", 2: "#757575"}     # 灰色系
    # fallback for any tom level
    def _c(tom, palette):
        return palette.get(tom, palette.get(0, "#888888"))

    for j, tom in enumerate(all_toms):
        pos_pcts = []
        neg_pcts = []
        neu_pcts = []
        for exp in experiments:
            c = stats[exp].get(tom)
            if c and c["total"] > 0:
                t = c["total"]
                pos_pcts.append(c["positive"] / t * 100)
                neg_pcts.append(c["negative"] / t * 100)
                neu_pcts.append(c["neutral"] / t * 100)
            else:
                pos_pcts.append(0)
                neg_pcts.append(0)
                neu_pcts.append(0)

        offsets = x_base + (j - n_tom / 2 + 0.5) * bar_width
        bars_neg = ax.bar(offsets, neg_pcts, bar_width * 0.9,
                          color=_c(tom, colors_neg), label=f"ToM{tom} 负" if j == 0 or True else "")
        bars_neu = ax.bar(offsets, neu_pcts, bar_width * 0.9, bottom=neg_pcts,
                          color=_c(tom, colors_neu), label=f"ToM{tom} 中性" if j == 0 or True else "")
        bot_pos = [n + ne for n, ne in zip(neg_pcts, neu_pcts)]
        bars_pos = ax.bar(offsets, pos_pcts, bar_width * 0.9, bottom=bot_pos,
                          color=_c(tom, colors_pos), label=f"ToM{tom} 正" if j == 0 or True else "")

    ax.set_xticks(x_base)
    ax.set_xticklabels(experiments, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("百分比 (%)")
    ax.set_title("各实验 · 各 ToM 层级的情绪正/负/中性占比")
    ax.set_ylim(0, 105)

    # 整理图例：去重
    handles, labels = ax.get_legend_handles_labels()
    seen = {}
    unique_handles, unique_labels = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen[l] = True
            unique_handles.append(h)
            unique_labels.append(l)
    ax.legend(unique_handles, unique_labels, fontsize=7, ncol=3,
              loc="upper right", bbox_to_anchor=(1.0, 1.0))

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"图表已保存: {out_path}")


def plot_sentiment_heatmap(stats: dict, out_path: Path) -> None:
    """
    热力图：行=实验，列=ToM层级，格值=正情绪占比(%)。
    额外在格子中标注 正%/负%/中性%。
    """
    experiments = list(stats.keys())
    all_toms = sorted({tom for m in stats.values() for tom in m})
    if not experiments:
        return

    n_exp = len(experiments)
    n_tom = len(all_toms)

    pos_matrix = np.full((n_exp, n_tom), np.nan)
    annotations = [['' for _ in range(n_tom)] for _ in range(n_exp)]

    for i, exp in enumerate(experiments):
        for j, tom in enumerate(all_toms):
            c = stats[exp].get(tom)
            if c and c["total"] > 0:
                t = c["total"]
                p = c["positive"] / t * 100
                n = c["negative"] / t * 100
                ne = c["neutral"] / t * 100
                pos_matrix[i, j] = p
                annotations[i][j] = f"+{p:.0f}%\n-{n:.0f}%\n○{ne:.0f}%"

    fig, ax = plt.subplots(figsize=(max(6, n_tom * 2.5), max(8, n_exp * 0.45)))
    cmap = plt.cm.RdYlGn  # 红(负)→黄(中)→绿(正)
    im = ax.imshow(pos_matrix, cmap=cmap, aspect="auto", vmin=0, vmax=100)

    ax.set_xticks(range(n_tom))
    ax.set_xticklabels([f"ToM {t}" for t in all_toms], fontsize=10)
    ax.set_yticks(range(n_exp))
    ax.set_yticklabels(experiments, fontsize=8)
    ax.set_xlabel("ToM 层级")
    ax.set_title("各实验 · 各 ToM 正情绪占比 (%) 热力图\n格内: +正% / -负% / ○中性%", fontsize=11)

    for i in range(n_exp):
        for j in range(n_tom):
            txt = annotations[i][j]
            if txt:
                ax.text(j, i, txt, ha="center", va="center", fontsize=7,
                        color="black" if 30 < pos_matrix[i, j] < 70 else "white")

    fig.colorbar(im, ax=ax, label="正情绪占比 (%)", shrink=0.6)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"热力图已保存: {out_path}")


# ── 主入口 ────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="各实验 ToM 情绪正负统计")
    parser.add_argument("--runs-dir", default="runs", help="实验根目录")
    parser.add_argument("--social-compare", action="store_true",
                        help="仅保留社交有/无对比实验对")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.exists():
        # 尝试相对于仓库根
        repo_root = Path(__file__).resolve().parents[2]
        runs_dir = repo_root / args.runs_dir
    if not runs_dir.exists():
        print(f"找不到实验目录: {args.runs_dir}", file=sys.stderr)
        sys.exit(1)

    plt.rcParams["axes.unicode_minus"] = False
    configure_chinese_font()

    stats = compute_stats(runs_dir)
    if not stats:
        print("未找到有效的 sentiment_series.jsonl 数据。")
        sys.exit(1)

    # ── 社交有无对比过滤 ──
    if args.social_compare:
        all_names = set(stats.keys())
        # 找出 X 与 X_无社交 配对
        pairs: list[tuple[str, str]] = []
        for name in sorted(all_names):
            if name.endswith("_无社交"):
                base = name[: -len("_无社交")]
                if base in all_names:
                    pairs.append((base, name))
        if not pairs:
            print("未找到社交有/无对比实验对。")
            sys.exit(1)
        keep = {}
        for base, nosoc in pairs:
            keep[base] = stats[base]
            keep[nosoc] = stats[nosoc]
        stats = keep

    print_report(stats)

    suffix = "_social_compare" if args.social_compare else ""
    plot_sentiment_composition(stats, OUT_DIR / f"sentiment_composition_by_tom{suffix}.png")
    plot_sentiment_heatmap(stats, OUT_DIR / f"sentiment_heatmap_by_tom{suffix}.png")


if __name__ == "__main__":
    main()
