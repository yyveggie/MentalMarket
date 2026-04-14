#!/usr/bin/env python3
"""有社交 vs 无社交：情绪标准差均值 哑铃图对比。

用法:
    cd evaluation
    python plot_sentiment_std_social_compare.py [--runs-root ../runs] [-o sentiment_social_compare.png]

自动检测 runs 下的配对实验（X 与 X_无社交），计算每个实验全部交易日
sentiment_std 的均值，以哑铃图(dumbbell chart)展示两两差异。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from metrics_plot_common import configure_chinese_font, read_jsonl, safe_int

# ── 配对发现 ──────────────────────────────────────────────────

def find_social_pairs(runs_root: Path) -> list[tuple[str, Path, Path]]:
    """返回 [(label, social_dir, nosocial_dir), ...] 按名称排序。"""
    dirs = {d.name: d for d in runs_root.iterdir() if d.is_dir() and d.name != "__pycache__"}
    pairs = []
    seen = set()
    for name, d in sorted(dirs.items()):
        if name.endswith("_无社交"):
            base = name[: -len("_无社交")]
            if base in dirs:
                pairs.append((base, dirs[base], d))
                seen.add(base)
                seen.add(name)
    # 排序: 纯 ToM 单层级在前(按数字)，混合层级在后
    def _sort_key(item):
        name = item[0]
        import re
        m = re.fullmatch(r"ToM(\d+)", name)
        if m:
            return (0, int(m.group(1)))
        return (1, name)
    pairs.sort(key=_sort_key)
    return pairs


# ── 计算 sentiment_std 均值 ──────────────────────────────────

def compute_mean_sentiment_std(run_dir: Path) -> float | None:
    """从 sentiment_series.jsonl 计算每日 sentiment_std 的全局均值。"""
    from collections import defaultdict

    sent_path = run_dir / "sentiment_series.jsonl"
    if not sent_path.exists():
        return None

    rows = read_jsonl(sent_path)
    day_sentiments: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        day = safe_int(r.get("trading_day"))
        s = r.get("sentiment")
        if day is None or s is None:
            continue
        day_sentiments[day].append(float(s))

    if not day_sentiments:
        return None

    daily_stds = []
    for day in sorted(day_sentiments):
        vals = day_sentiments[day]
        n = len(vals)
        if n < 2:
            continue
        mean = sum(vals) / n
        std = (sum((v - mean) ** 2 for v in vals) / (n - 1)) ** 0.5
        daily_stds.append(std)

    if not daily_stds:
        return None
    return round(sum(daily_stds) / len(daily_stds), 2)


def compute_mean_sentiment_std_by_tom(run_dir: Path) -> dict[int, float]:
    """按 ToM 层级分别计算每日 sentiment_std 的均值。
    返回 { tom_level: mean_std } 。"""
    from collections import defaultdict

    sent_path = run_dir / "sentiment_series.jsonl"
    if not sent_path.exists():
        return {}

    rows = read_jsonl(sent_path)
    tom_day_sentiments: dict[int, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for r in rows:
        day = safe_int(r.get("trading_day"))
        s = r.get("sentiment")
        tl = safe_int(r.get("tom_level"))
        if day is None or s is None or tl is None:
            continue
        tom_day_sentiments[tl][day].append(float(s))

    result = {}
    for tl in sorted(tom_day_sentiments):
        daily_stds = []
        for day in sorted(tom_day_sentiments[tl]):
            vals = tom_day_sentiments[tl][day]
            n = len(vals)
            if n < 2:
                continue
            mean = sum(vals) / n
            std = (sum((v - mean) ** 2 for v in vals) / (n - 1)) ** 0.5
            daily_stds.append(std)
        if daily_stds:
            result[tl] = round(sum(daily_stds) / len(daily_stds), 4)
    return result


# ── 垂直哑铃图绘制 ────────────────────────────────────────────

def plot_grouped_bar(pairs_data: list[tuple[str, float, float]], output: str,
                     title: str = "有社交 vs 无社交：情绪标准差对比"):
    """
    pairs_data: [(label, social_val, nosocial_val), ...]
    垂直哑铃图：X 轴为实验名，Y 轴为情绪标准差，
    每组一根竖线连接有社交/无社交两个圆点。
    """
    configure_chinese_font()

    n = len(pairs_data)
    labels = [p[0] for p in pairs_data]
    social_vals = np.array([p[1] for p in pairs_data])
    nosocial_vals = np.array([p[2] for p in pairs_data])

    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(max(6, 2.2 * n), 5.5))

    # 连接线（竖线）
    for i in range(n):
        ax.plot(
            [x[i], x[i]], [social_vals[i], nosocial_vals[i]],
            color="#bfbfbf", linewidth=2.8, zorder=1, solid_capstyle="round",
        )

    # 有社交圆点
    ax.scatter(x, social_vals, s=140, color="#0969da", zorder=3, label="有社交")
    # 无社交菱形
    ax.scatter(x, nosocial_vals, s=140, color="#cf222e", zorder=3, marker="D", label="无社交")

    # 数值标注 —— 始终让有社交标注在点上方、无社交标注在点下方
    for i in range(n):
        sv, nv = social_vals[i], nosocial_vals[i]
        diff = sv - nv
        sign = "+" if diff > 0 else ""

        # 确定谁在上面谁在下面
        if sv >= nv:
            s_offset, n_offset = (0, 10), (0, -14)
            s_va, n_va = "bottom", "top"
        else:
            s_offset, n_offset = (0, -14), (0, 10)
            s_va, n_va = "top", "bottom"

        ax.annotate(
            f"{sv:.2f}", (x[i], sv),
            textcoords="offset points", xytext=s_offset,
            ha="center", va=s_va, fontsize=10, color="#0969da", fontweight="bold",
        )
        ax.annotate(
            f"{nv:.2f}", (x[i], nv),
            textcoords="offset points", xytext=n_offset,
            ha="center", va=n_va, fontsize=10, color="#cf222e", fontweight="bold",
        )

        # Δ 标注 —— 放在连线中点旁侧
        mid_y = (sv + nv) / 2
        color = "#0969da" if diff > 0 else "#cf222e" if diff < 0 else "#656d76"
        ax.annotate(
            f"Δ={sign}{diff:.2f}", (x[i], mid_y),
            textcoords="offset points", xytext=(30, 0),
            ha="left", va="center", fontsize=9, color=color,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#f6f8fa",
                      edgecolor="#d0d7de", alpha=0.9),
        )

    y_min = min(social_vals.min(), nosocial_vals.min())
    y_max = max(social_vals.max(), nosocial_vals.max())
    margin = (y_max - y_min) * 0.35
    ax.set_ylim(y_min - margin, y_max + margin)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("情绪标准差（全交易日均值）", fontsize=11)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)

    ax.yaxis.grid(True, linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(fontsize=11, framealpha=0.9, loc="upper center", ncol=2,
              bbox_to_anchor=(0.5, -0.08))

    plt.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] 已保存: {output}")


def plot_tom_subplots(tom_pairs_data: dict[int, list[tuple[str, float, float]]],
                      output: str):
    """所有 ToM 层级合并为一张图的子图，紧凑布局。"""
    configure_chinese_font()

    toms = sorted(tom_pairs_data.keys())
    n_toms = len(toms)
    if n_toms == 0:
        return

    fig, axes = plt.subplots(1, n_toms, figsize=(3.8 * n_toms, 5),
                             sharey=True, squeeze=False)

    for ti, tl in enumerate(toms):
        ax = axes[0][ti]
        tdata = tom_pairs_data[tl]
        n = len(tdata)
        labels = [p[0] for p in tdata]
        social_vals = np.array([p[1] for p in tdata])
        nosocial_vals = np.array([p[2] for p in tdata])
        x = np.arange(n)

        for i in range(n):
            ax.plot([x[i], x[i]], [social_vals[i], nosocial_vals[i]],
                    color="#bfbfbf", linewidth=2.8, zorder=1,
                    solid_capstyle="round")

        ax.scatter(x, social_vals, s=100, color="#0969da", zorder=3)
        ax.scatter(x, nosocial_vals, s=100, color="#cf222e", zorder=3,
                   marker="D")

        for i in range(n):
            sv, nv = social_vals[i], nosocial_vals[i]
            diff = sv - nv
            sign = "+" if diff > 0 else ""
            gap = abs(sv - nv)

            if sv >= nv:
                s_off = (0, max(8, 4 if gap > 0.03 else 12))
                n_off = (0, -max(10, 4 if gap > 0.03 else 14))
                s_va, n_va = "bottom", "top"
            else:
                s_off = (0, -max(10, 4 if gap > 0.03 else 14))
                n_off = (0, max(8, 4 if gap > 0.03 else 12))
                s_va, n_va = "top", "bottom"

            ax.annotate(f"{sv:.2f}", (x[i], sv), textcoords="offset points",
                        xytext=s_off, ha="center", va=s_va, fontsize=8,
                        color="#0969da", fontweight="bold")
            ax.annotate(f"{nv:.2f}", (x[i], nv), textcoords="offset points",
                        xytext=n_off, ha="center", va=n_va, fontsize=8,
                        color="#cf222e", fontweight="bold")

            mid_y = (sv + nv) / 2
            color = "#0969da" if diff > 0 else "#cf222e" if diff < 0 else "#656d76"
            ax.annotate(f"Δ={sign}{diff:.2f}", (x[i], mid_y),
                        textcoords="offset points", xytext=(22, 0),
                        ha="left", va="center", fontsize=7.5, color=color,
                        bbox=dict(boxstyle="round,pad=0.15", facecolor="#f6f8fa",
                                  edgecolor="#d0d7de", alpha=0.9))

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8, rotation=15, ha="right")
        ax.set_title(f"ToM-{tl}", fontsize=11, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", alpha=0.35)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlim(-0.6, n - 0.4)

    axes[0][0].set_ylabel("情绪标准差", fontsize=10)

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#0969da",
                   markersize=8, label="有社交"),
        plt.Line2D([0], [0], marker="D", color="w", markerfacecolor="#cf222e",
                   markersize=8, label="无社交"),
    ]
    fig.legend(handles=handles, fontsize=10, framealpha=0.9,
               loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.01))

    fig.suptitle("有社交 vs 无社交：按 ToM 层级情绪标准差对比",
                 fontsize=13, fontweight="bold")
    fig.subplots_adjust(wspace=0.08)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] 已保存: {output}")


# ── main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="有社交 vs 无社交 情绪标准差哑铃图")
    parser.add_argument("--runs-root", default="../runs", help="runs 目录路径")
    parser.add_argument("-o", "--output", default="sentiment_social_compare.png", help="输出图片路径")
    args = parser.parse_args()

    runs_root = Path(args.runs_root).resolve()
    if not runs_root.exists():
        print(f"[ERROR] runs 目录不存在: {runs_root}", file=sys.stderr)
        sys.exit(1)

    pairs = find_social_pairs(runs_root)
    if not pairs:
        print("[WARN] 未找到任何 (X, X_无社交) 配对实验。", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(pairs)} 组对比:")
    pairs_data = []
    tom_pairs_data: dict[int, list[tuple[str, float, float]]] = {}
    for label, social_dir, nosocial_dir in pairs:
        sv = compute_mean_sentiment_std(social_dir)
        nv = compute_mean_sentiment_std(nosocial_dir)
        if sv is None or nv is None:
            print(f"  [SKIP] {label}: 缺少 sentiment_series.jsonl")
            continue
        print(f"  {label}: 有社交={sv:.2f}  无社交={nv:.2f}  Δ={sv - nv:+.2f}")
        pairs_data.append((label, sv, nv))

        sv_by_tom = compute_mean_sentiment_std_by_tom(social_dir)
        nv_by_tom = compute_mean_sentiment_std_by_tom(nosocial_dir)
        common_toms = sorted(set(sv_by_tom) & set(nv_by_tom))
        if common_toms:
            print(f"    按 ToM 分层:")
            for tl in common_toms:
                s, n = sv_by_tom[tl], nv_by_tom[tl]
                print(f"      ToM-{tl}: 有社交={s:.4f}  无社交={n:.4f}  Δ={s - n:+.4f}")
                tom_pairs_data.setdefault(tl, []).append((label, s, n))

    if not pairs_data:
        print("[ERROR] 无有效数据可绘图。", file=sys.stderr)
        sys.exit(1)

    plot_grouped_bar(pairs_data, args.output)

    if tom_pairs_data:
        out_dir = Path(args.output).parent
        tom_out = str(out_dir / "sentiment_social_compare_by_tom.png")
        plot_tom_subplots(tom_pairs_data, tom_out)


if __name__ == "__main__":
    main()
