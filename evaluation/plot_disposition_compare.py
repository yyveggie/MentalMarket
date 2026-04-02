#!/usr/bin/env python3
"""三实验处置效应对比曲线。

从各实验的 behavioral_biases.jsonl 中按交易日聚合 PGR/PLR/DE，
绘制三个实验的处置效应对比曲线（DE = PGR - PLR）。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics_plot_common import configure_chinese_font, ensure_output_dir, read_jsonl, safe_int, safe_float

configure_chinese_font()

runs = {
    "tom0": "runs/20260322_132820_tom0",
    "tom1": "runs/20260322_231352_tom1",
    "tom2": "runs/20260323_213251_tom2",
}

out_dir = ensure_output_dir(Path("."), None)
colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]


def load_disposition_curves(run_path: str):
    """按交易日聚合 PGR/PLR/DE + 处置效应占比。

    优先使用 gains_available/realized_gain 等预计算字段；
    若字段缺失则从 sell_gain_pct / market_price / avg_buy_price
    + holdings_count / unrealized_loss_count 推算。
    返回滚动 5 天窗口的 PGR/PLR/DE 以及每日处置效应占比。
    """
    WINDOW = 5
    rows = read_jsonl(Path(run_path) / "behavioral_biases.jsonl")
    by_day = defaultdict(lambda: {
        "gains_avail": 0, "losses_avail": 0,
        "realized_gain": 0, "realized_loss": 0,
        "disposition_count": 0, "sell_count": 0,
    })

    for r in rows:
        day = safe_int(r.get("trading_day"))
        if day is None or day <= 0:
            continue
        d = by_day[day]
        action = r.get("action", "")
        status = r.get("status", "")

        # 使用已回填的预计算字段（口径统一）
        d["gains_avail"] += r.get("gains_available", 0)
        d["losses_avail"] += r.get("losses_available", 0)
        d["realized_gain"] += r.get("realized_gain", 0)
        d["realized_loss"] += r.get("realized_loss", 0)

        if action == "sell" and status == "ok":
            d["sell_count"] += 1
            if r.get("disposition_effect_flag"):
                d["disposition_count"] += 1

    days = sorted(by_day.keys())
    pgr_curve, plr_curve, de_curve, disp_pct_curve = [], [], [], []

    for idx, day in enumerate(days):
        # 滚动窗口：取最近 WINDOW 天
        start = max(0, idx - WINDOW + 1)
        win_days = days[start:idx + 1]

        win_ga = win_la = win_rg = win_rl = 0
        for wd in win_days:
            dd = by_day[wd]
            win_ga += dd["gains_avail"]
            win_la += dd["losses_avail"]
            win_rg += dd["realized_gain"]
            win_rl += dd["realized_loss"]

        pgr = win_rg / win_ga if win_ga > 0 else None
        plr = win_rl / win_la if win_la > 0 else None
        de = (pgr - plr) if pgr is not None and plr is not None else None

        pgr_curve.append(pgr)
        plr_curve.append(plr)
        de_curve.append(de)

        d = by_day[day]
        disp_pct = d["disposition_count"] / d["sell_count"] * 100 if d["sell_count"] > 0 else 0
        disp_pct_curve.append(disp_pct)

    return days, pgr_curve, plr_curve, de_curve, disp_pct_curve


# ── 加载数据 ──
all_data = {}
for label, path in runs.items():
    all_data[label] = load_disposition_curves(path)

# ── 画图：4 子图 ──
fig, axes = plt.subplots(4, 1, figsize=(12, 14), sharex=True, dpi=140)

# 1) DE (PGR - PLR)
ax = axes[0]
for i, (label, (days, pgr, plr, de, dp)) in enumerate(all_data.items()):
    valid = [(d, v) for d, v in zip(days, de) if v is not None]
    if valid:
        ax.plot([x[0] for x in valid], [x[1] for x in valid],
                color=colors[i], linewidth=1.8, label=label, alpha=0.9)
ax.axhline(0, color="#999", linestyle="--", linewidth=0.8, alpha=0.5)
ax.set_ylabel("DE (PGR - PLR)")
ax.set_title("处置效应指数（Odean DE）对比")
ax.grid(alpha=0.2)
ax.legend(loc="upper right")
ax.text(0.01, 0.05,
        "DE = PGR - PLR（滚动5天窗口）\n"
        "越接近0 = 处置效应越弱（理性）\n"
        "越负 = 亏损卖得多、盈利不舍得卖（反处置效应）",
        transform=ax.transAxes, fontsize=8, va="bottom",
        bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", alpha=0.85))

# 2) PGR
ax = axes[1]
for i, (label, (days, pgr, plr, de, dp)) in enumerate(all_data.items()):
    valid = [(d, v) for d, v in zip(days, pgr) if v is not None]
    if valid:
        ax.plot([x[0] for x in valid], [x[1] for x in valid],
                color=colors[i], linewidth=1.8, label=label, alpha=0.9)
ax.set_ylabel("PGR")
ax.set_title("盈利实现率（PGR）对比")
ax.grid(alpha=0.2)
ax.legend(loc="upper right")
ax.text(0.01, 0.95,
        "PGR = 已实现盈利次数 / 所有盈利机会次数（滚动5天）\n"
        "越高 = 越倾向\"赚了就跑\"",
        transform=ax.transAxes, fontsize=8, va="top",
        bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", alpha=0.85))

# 3) PLR
ax = axes[2]
for i, (label, (days, pgr, plr, de, dp)) in enumerate(all_data.items()):
    valid = [(d, v) for d, v in zip(days, plr) if v is not None]
    if valid:
        ax.plot([x[0] for x in valid], [x[1] for x in valid],
                color=colors[i], linewidth=1.8, label=label, alpha=0.9)
ax.set_ylabel("PLR")
ax.set_title("亏损实现率（PLR）对比")
ax.grid(alpha=0.2)
ax.legend(loc="upper right")
ax.text(0.01, 0.05,
        "PLR = 已实现亏损次数 / 所有亏损机会次数（滚动5天）\n"
        "越高 = 越倾向\"亏了就割\"（止损果断）\n"
        "越低 = 越倾向\"死扛不卖\"（套牢不割）",
        transform=ax.transAxes, fontsize=8, va="bottom",
        bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", alpha=0.85))

# 4) 处置效应占比（每日）
ax = axes[3]
for i, (label, (days, pgr, plr, de, dp)) in enumerate(all_data.items()):
    # 5日移动平均平滑
    if len(dp) >= 5:
        smooth = np.convolve(dp, np.ones(5) / 5, mode="valid")
        smooth_days = days[2:2 + len(smooth)]
        ax.plot(smooth_days, smooth, color=colors[i], linewidth=1.8, label=label, alpha=0.9)
    else:
        ax.plot(days, dp, color=colors[i], linewidth=1.8, label=label, alpha=0.9)
ax.set_xlabel("交易日")
ax.set_ylabel("占比 (%)")
ax.set_title("处置效应发生占比（5日均线）")
ax.grid(alpha=0.2)
ax.legend(loc="upper right")
ax.text(0.01, 0.95,
        "每天的卖出交易中，有多少比例是\n"
        "\"卖掉赚钱的、留着亏钱的\"（处置效应行为）\n"
        "用5天滑动平均平滑了波动",
        transform=ax.transAxes, fontsize=8, va="top",
        bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", alpha=0.85))

fig.suptitle("三实验处置效应对比", fontsize=14, y=1.01)
fig.tight_layout()
p = out_dir / "三实验处置效应对比.png"
fig.savefig(str(p), bbox_inches="tight")
fig.savefig(str(p.with_suffix(".pdf")), bbox_inches="tight")
plt.close(fig)
print(f"保存: {p}")
