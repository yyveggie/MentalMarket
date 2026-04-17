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

_EVAL_DIR = Path(__file__).resolve().parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

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
    """情绪标准差均值（严格口径，真实"人际分歧度"）。

    计算步骤:
        1. 按 (trading_day, agent_id) 把同一 agent 一天内的多条 sentiment
           先求均值，压成"每日每人一条"
        2. 对每个交易日，计算跨 agent 的样本 std (除 n-1)
        3. 对所有交易日的 std 求算数平均

    这样能消除"同一 agent 日内多次决策的时序波动"污染，
    得到纯粹的"人际分歧"指标。
    """
    from collections import defaultdict

    sent_path = run_dir / "sentiment_series.jsonl"
    if not sent_path.exists():
        return None

    rows = read_jsonl(sent_path)
    # day -> agent_id -> [sentiment, ...]
    day_agent_sent: dict[int, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for r in rows:
        day = safe_int(r.get("trading_day"))
        aid = safe_int(r.get("agent_id"))
        s = r.get("sentiment")
        if day is None or aid is None or s is None:
            continue
        day_agent_sent[day][aid].append(float(s))

    if not day_agent_sent:
        return None

    daily_stds = []
    for day in sorted(day_agent_sent):
        # 先把每个 agent 日内均值压成一条
        agent_means = [sum(v) / len(v) for v in day_agent_sent[day].values() if v]
        n = len(agent_means)
        if n < 2:
            continue
        mean = sum(agent_means) / n
        std = (sum((v - mean) ** 2 for v in agent_means) / (n - 1)) ** 0.5
        daily_stds.append(std)

    if not daily_stds:
        return None
    return round(sum(daily_stds) / len(daily_stds), 2)


def compute_mean_sentiment_std_by_tom(run_dir: Path) -> dict[int, float]:
    """按 ToM 层级分别计算"人际分歧度"（严格口径，同 compute_mean_sentiment_std）。

    返回 { tom_level: mean_std }。

    步骤:
        1. 按 (tom_level, trading_day, agent_id) 先把同一 agent 日内多条 sentiment
           压成均值
        2. 对每个 (tom_level, trading_day)，算跨 agent 样本 std
        3. 对各日 std 求均值
    """
    from collections import defaultdict

    sent_path = run_dir / "sentiment_series.jsonl"
    if not sent_path.exists():
        return {}

    rows = read_jsonl(sent_path)
    # tom -> day -> agent_id -> [sentiment, ...]
    tom_day_agent: dict[int, dict[int, dict[int, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        day = safe_int(r.get("trading_day"))
        s = r.get("sentiment")
        tl = safe_int(r.get("tom_level"))
        aid = safe_int(r.get("agent_id"))
        if day is None or s is None or tl is None or aid is None:
            continue
        tom_day_agent[tl][day][aid].append(float(s))

    result = {}
    for tl in sorted(tom_day_agent):
        daily_stds = []
        for day in sorted(tom_day_agent[tl]):
            agent_means = [sum(v) / len(v) for v in tom_day_agent[tl][day].values() if v]
            n = len(agent_means)
            if n < 2:
                continue
            mean = sum(agent_means) / n
            std = (sum((v - mean) ** 2 for v in agent_means) / (n - 1)) ** 0.5
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


_LABEL_ALIAS = {
    "ToM01_ToM11_ToM21": "1:1:1",
}


def _pretty_label(raw: str) -> str:
    return _LABEL_ALIAS.get(raw, raw)


def plot_tom_subplots(tom_pairs_data: dict[int, list[tuple[str, float, float]]],
                      output: str):
    """所有 ToM 层级合并为一张图的子图，风格对齐大盘哑铃图。"""
    configure_chinese_font()

    toms = sorted(tom_pairs_data.keys())
    n_toms = len(toms)
    if n_toms == 0:
        return

    fig, axes = plt.subplots(1, n_toms, figsize=(3.2 * n_toms, 4),
                             sharey=True, squeeze=False, dpi=120)

    for ti, tl in enumerate(toms):
        ax = axes[0][ti]
        tdata = tom_pairs_data[tl]
        n = len(tdata)
        labels = [_pretty_label(p[0]) for p in tdata]
        social_vals = np.array([p[1] for p in tdata])
        nosocial_vals = np.array([p[2] for p in tdata])
        x = np.arange(n)

        # 连接线
        for i in range(n):
            ax.plot([x[i], x[i]], [social_vals[i], nosocial_vals[i]],
                    color="#999999", linewidth=2, zorder=1)

        # 无社交（浅灰） + 有社交（深灰），统一圆点 + 黑色细边
        ax.scatter(x, nosocial_vals, s=100, color="#e0e0e0",
                   edgecolors="black", linewidths=0.8, zorder=2,
                   label="无社交")
        ax.scatter(x, social_vals, s=100, color="#424242",
                   edgecolors="black", linewidths=0.8, zorder=2,
                   label="有社交")

        # 数值标注：统一放到散点右侧 12pt，避免与点重叠
        for i in range(n):
            for val in (nosocial_vals[i], social_vals[i]):
                ax.annotate(f"{val:.2f}", (x[i], val), fontsize=8,
                            ha="left", va="center",
                            xytext=(12, 0), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        ax.set_title(f"ToM{tl}", fontsize=11, pad=8)
        ax.grid(True, alpha=0.15, axis="y")
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.margins(x=0.2)

    axes[0][0].set_ylabel("情绪标准差", fontsize=11)

    # 图例放到最后一个子图右上角
    axes[0][-1].legend(fontsize=10, loc="upper right")

    fig.suptitle("有社交 vs 无社交：按 ToM 层级情绪标准差对比", fontsize=13)
    plt.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
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
