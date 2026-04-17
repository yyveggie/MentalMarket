#!/usr/bin/env python3
"""
推理-发帖一致性分析（Reasoning vs. Post Consistency）

检测智能体"想的"（心智推理）和"说的"（社交帖子）之间的一致程度。
低一致性意味着潜在的策略性操纵：思考一套，发帖另一套。

度量：三层去模板 + NCD（Normalized Compression Distance）字符级压缩距离。
NCD 对跨语体文本（分析体 reasoning ↔ 口语体 post）比词袋余弦更鲁棒。

统计：按"天"bootstrap 95% CI；shuffle baseline（随机重配对）检验
真实一致性是否显著高于随机零假设。
"""

import argparse
import bisect
import json
import math
import os
import re
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

_DAILY_MIN_DOCS = 5


# ── CLI ──────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="推理-发帖一致性分析")
    p.add_argument("run_dirs", nargs="*", help="实验目录（留空则使用内置默认列表）")
    p.add_argument("--labels", default="", help="逗号分隔的实验标签")
    p.add_argument("--ngram", type=int, default=2,
                   help="最小 n-gram 大小 (默认 2)，自动同时使用 n 和 n+1")
    p.add_argument("--global-thresh", type=float, default=0.95,
                   help="Layer 1 全局去模板阈值 (默认 0.95，与同质性脚本对齐)")
    p.add_argument("--group-thresh", type=float, default=0.90,
                   help="Layer 2 组级去模板阈值 (默认 0.90)")
    p.add_argument("--daily-thresh", type=float, default=0.80,
                   help="Layer 3 逐日去模板阈值 (默认 0.80)")
    p.add_argument("--max-chars", type=int, default=512,
                   help="每条文本截断字符数")
    p.add_argument("--bootstrap", type=int, default=500,
                   help="bootstrap 重采样次数")
    p.add_argument("--shuffle", type=int, default=200,
                   help="shuffle baseline 随机重配对次数")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-dir", default=os.path.join(os.path.dirname(__file__), ""))
    p.add_argument("--prefix", default="推理发帖一致性",
                   help="输出文件名前缀")
    p.add_argument("--template-thresh", type=float, default=None,
                   help="[兼容旧版] 等同于 --global-thresh")
    return p.parse_args()


def _build_time_to_day(run_dir: str):
    centers = []
    with open(os.path.join(run_dir, "broad_index.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            centers.append((rec["sim_time"], rec["trading_day"]))
    centers.sort()
    times = [c[0] for c in centers]
    days = [c[1] for c in centers]

    def mapper(sim_time: float) -> int:
        idx = bisect.bisect_right(times, sim_time)
        if idx == 0:
            return days[0]
        if idx >= len(times):
            return days[-1]
        if abs(times[idx] - sim_time) < abs(times[idx - 1] - sim_time):
            return days[idx]
        return days[idx - 1]

    return mapper


def _extract_reasoning_parts(llm_output: dict, tom_level: int) -> dict:
    if tom_level == 2:
        parts = {}
        r1 = llm_output.get("tom1_reasoning", "")
        r2 = llm_output.get("tom2_reasoning", "")
        if r1 and not r1.startswith("(ToM"):
            parts["_r1"] = r1
        if r2 and not r2.startswith("(ToM"):
            parts["_r2"] = r2
        return parts
    elif tom_level == 1:
        mr = llm_output.get("mental_reasoning", "")
        if mr and not mr.startswith("(ToM"):
            return {"": mr}
    return {}


_RETWEET_RE = re.compile(r"\[转发\s*@[A-Za-z0-9_]+\]\s*")


def _clean_post(content: str) -> str:
    return _RETWEET_RE.sub("", content).strip()


def load_data(run_dir: str, max_chars: int):
    mapper = _build_time_to_day(run_dir)
    data = defaultdict(
        lambda: defaultdict(
            lambda: {"reasoning_parts": {}, "posts": [], "tom": 0}))

    with open(os.path.join(run_dir, "decisions.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            tl = rec.get("tom_level", 0)
            if tl == 0:
                continue
            aid = rec["agent_id"]
            day = mapper(rec["sim_time"])
            out = rec.get("llm_output", {})
            parts = _extract_reasoning_parts(out, tl)
            if parts:
                data[aid][day]["reasoning_parts"] = {
                    k: v[:max_chars] for k, v in parts.items()}
                data[aid][day]["tom"] = tl

    with open(os.path.join(run_dir, "posts.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            aid = rec["agent_id"]
            day = rec.get("trading_day")
            if day is None:
                day = mapper(rec["sim_time"])
            content = _clean_post(rec.get("content", ""))
            if content and aid in data:
                data[aid][day]["posts"].append(content[:max_chars])

    return dict(data)


def _tokenize(text: str) -> list[str]:
    import jieba
    return list(jieba.cut(text))


def _multi_ngrams(tokens: list[str], sizes: list[int]) -> set[tuple]:
    result = set()
    n = len(tokens)
    for size in sizes:
        for i in range(n - size + 1):
            result.add(tuple(tokens[i:i + size]))
    return result


def _remove_template_spans(tokens: list[str],
                           template_ngs: set[tuple],
                           ngram_sizes: list[int]) -> list[str]:
    n = len(tokens)
    is_tpl = [False] * n
    for size in ngram_sizes:
        for i in range(n - size + 1):
            if tuple(tokens[i:i + size]) in template_ngs:
                for j in range(i, i + size):
                    is_tpl[j] = True
    return [t for i, t in enumerate(tokens) if not is_tpl[i]]


GROUP_DISPLAY = {
    "tom1": "ToM-1",
    "tom2_r1": "ToM-2 一阶推理",
    "tom2_r2": "ToM-2 二阶推理",
}


# ── 统计辅助函数 ────────────────────────────────────────────────────
def _weighted_day_mean(per_day_sims: dict) -> float:
    """按每日样本数加权的日均相似度。"""
    means, weights = [], []
    for _, sims in per_day_sims.items():
        if not sims:
            continue
        means.append(float(np.mean(sims)))
        weights.append(len(sims))
    if not means:
        return float("nan")
    return float(np.average(means, weights=weights))


def _bootstrap_ci(per_day_sims: dict, B: int = 500,
                  seed: int = 42, alpha: float = 0.05) -> tuple[float, float]:
    """按"天"重采样的 95% bootstrap CI。"""
    days = [d for d, s in per_day_sims.items() if s]
    if len(days) < 2:
        m = _weighted_day_mean(per_day_sims)
        return (m, m)
    rng = np.random.default_rng(seed)
    daily_means = np.array([float(np.mean(per_day_sims[d])) for d in days])
    weights_all = np.array([len(per_day_sims[d]) for d in days])
    n = len(days)
    estimates = []
    for _ in range(B):
        idx = rng.integers(0, n, size=n)
        estimates.append(float(np.average(
            daily_means[idx], weights=weights_all[idx])))
    lo = float(np.quantile(estimates, alpha / 2))
    hi = float(np.quantile(estimates, 1 - alpha / 2))
    return (lo, hi)


def _sig_mark(p: float) -> str:
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "n.s."


def analyze_experiment(run_dir: str, label: str, args):
    print(f"\n{'=' * 60}")
    print(f"处理: {label}  ({run_dir})")
    print(f"{'=' * 60}")

    import jieba
    jieba.setLogLevel(20)

    data = load_data(run_dir, args.max_chars)
    ngram_sizes = [args.ngram, args.ngram + 1]

    # ── 收集全部文本用于三层模板检测 ─────────────────────────────────
    class _DocMeta:
        __slots__ = ("day", "group", "ngrams")

        def __init__(self, day, group, ngrams):
            self.day = day
            self.group = group
            self.ngrams = ngrams

    all_metas: list[_DocMeta] = []
    for aid, days_data in data.items():
        for day, dd in days_data.items():
            tom = dd["tom"]
            if tom == 0:
                continue
            tom_group = f"tom{tom}"
            for text in dd["reasoning_parts"].values():
                if text:
                    tokens = _tokenize(text)
                    all_metas.append(_DocMeta(
                        day, tom_group, _multi_ngrams(tokens, ngram_sizes)))
            for post in dd["posts"]:
                if post:
                    tokens = _tokenize(post)
                    all_metas.append(_DocMeta(
                        day, tom_group, _multi_ngrams(tokens, ngram_sizes)))

    total = len(all_metas)
    if total == 0:
        return _empty_result(label)

    print(f"  文本总数: {total}（推理+帖子），n-gram 粒度: {ngram_sizes}")

    # ── 三层模板检测 ─────────────────────────────────────────────────
    print("  Layer 1: 全局去模板…")
    global_df: Counter = Counter()
    for m in all_metas:
        for ng in m.ngrams:
            global_df[ng] += 1
    global_tpl = {ng for ng, c in global_df.items()
                  if c > total * args.global_thresh}
    print(f"    全局模板: {len(global_tpl)} 个")

    print("  Layer 2: 组级去模板…")
    group_indices: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(all_metas):
        group_indices[m.group].append(i)

    group_tpl: dict[str, set] = {}
    for gk, indices in group_indices.items():
        gdf: Counter = Counter()
        for i in indices:
            for ng in all_metas[i].ngrams:
                gdf[ng] += 1
        n_g = len(indices)
        group_tpl[gk] = {ng for ng, c in gdf.items()
                         if c > n_g * args.group_thresh
                         and ng not in global_tpl}
        print(f"    {gk}: +{len(group_tpl[gk])} 个")

    print("  Layer 3: 逐日去模板…")
    day_indices: dict[int, list[int]] = defaultdict(list)
    for i, m in enumerate(all_metas):
        day_indices[m.day].append(i)

    upper_tpl = set(global_tpl)
    for v in group_tpl.values():
        upper_tpl |= v

    daily_tpl: dict[int, set] = {}
    daily_total = 0
    for day, indices in day_indices.items():
        if len(indices) < _DAILY_MIN_DOCS:
            daily_tpl[day] = set()
            continue
        ddf: Counter = Counter()
        for i in indices:
            for ng in all_metas[i].ngrams:
                ddf[ng] += 1
        n_d = len(indices)
        new_tpl = {ng for ng, c in ddf.items()
                   if c > n_d * args.daily_thresh
                   and ng not in upper_tpl}
        daily_tpl[day] = new_tpl
        daily_total += len(new_tpl)
    print(f"    逐日模板: 共 +{daily_total} 个")

    # ── 逐 (agent, day, suffix) 收集清洗后的 (r_bytes, p_bytes) 对 ──
    print("  清洗 + 压缩尺寸预计算…")

    def _get_tpl(tom_group: str, day: int) -> set:
        return (global_tpl
                | group_tpl.get(tom_group, set())
                | daily_tpl.get(day, set()))

    # per_group_pairs[group] = list of dict(r_bytes, p_bytes, rc, pc, day, aid)
    # rc/pc 预先计算的压缩字节数
    per_group_pairs: dict = defaultdict(list)

    for aid, days_data in data.items():
        for day, dd in days_data.items():
            reasoning_parts = dd["reasoning_parts"]
            posts = dd["posts"]
            tom = dd["tom"]
            if not reasoning_parts or not posts:
                continue

            tom_group = f"tom{tom}"
            tpl = _get_tpl(tom_group, day)

            post_text = "\n".join(posts)
            p_tokens = _tokenize(post_text)
            p_cleaned_str = "".join(
                _remove_template_spans(p_tokens, tpl, ngram_sizes))
            p_bytes = p_cleaned_str.encode("utf-8")
            if not p_bytes:
                continue
            pc = len(zlib.compress(p_bytes))

            for suffix, reasoning in reasoning_parts.items():
                group = f"tom{tom}{suffix}"
                r_tokens = _tokenize(reasoning)
                r_cleaned_str = "".join(
                    _remove_template_spans(r_tokens, tpl, ngram_sizes))
                r_bytes = r_cleaned_str.encode("utf-8")
                if not r_bytes:
                    continue
                rc = len(zlib.compress(r_bytes))
                per_group_pairs[group].append({
                    "aid": aid, "day": day,
                    "r_bytes": r_bytes, "p_bytes": p_bytes,
                    "rc": rc, "pc": pc,
                })

    def _ncd_from_bytes(r_bytes: bytes, p_bytes: bytes,
                        rc: int, pc: int) -> float:
        denom = max(rc, pc)
        if denom == 0:
            return float("nan")
        cab = len(zlib.compress(r_bytes + p_bytes))
        return 1.0 - (cab - min(rc, pc)) / denom

    # ── 观测一致性：真配对 ──────────────────────────────────────────
    print("  计算观测一致性（真配对）…")
    per_day: dict = defaultdict(lambda: defaultdict(list))
    agent_scores: dict = defaultdict(lambda: defaultdict(list))

    for group, pairs in per_group_pairs.items():
        for pp in pairs:
            ncd = _ncd_from_bytes(pp["r_bytes"], pp["p_bytes"],
                                  pp["rc"], pp["pc"])
            if not math.isnan(ncd):
                per_day[group][pp["day"]].append(ncd)
                agent_scores[group][pp["aid"]].append(ncd)

    # ── Shuffle baseline：随机重配对 r ↔ p ─────────────────────────
    print(f"  计算 shuffle baseline (B={args.shuffle})…")
    rng = np.random.default_rng(args.seed)
    baseline_stats: dict = {}
    for group, pairs in per_group_pairs.items():
        if len(pairs) < 5:
            continue
        n = len(pairs)
        r_list = [pp["r_bytes"] for pp in pairs]
        rc_list = [pp["rc"] for pp in pairs]
        p_list = [pp["p_bytes"] for pp in pairs]
        pc_list = [pp["pc"] for pp in pairs]

        shuffled_means = []
        for _ in range(args.shuffle):
            perm = rng.permutation(n)
            # 避免自配对
            for k in range(n):
                if perm[k] == k:
                    swap = (k + 1) % n
                    perm[k], perm[swap] = perm[swap], perm[k]
            vals = []
            for k in range(n):
                j = int(perm[k])
                v = _ncd_from_bytes(
                    r_list[k], p_list[j], rc_list[k], pc_list[j])
                if not math.isnan(v):
                    vals.append(v)
            if vals:
                shuffled_means.append(float(np.mean(vals)))

        if shuffled_means:
            obs_mean = _weighted_day_mean(per_day[group])
            arr = np.array(shuffled_means)
            baseline_mean = float(arr.mean())
            baseline_lo = float(np.quantile(arr, 0.025))
            baseline_hi = float(np.quantile(arr, 0.975))
            # 单尾 p 值：观测均值 ≤ shuffle 分布中多少比例
            # （若观测 > baseline，则 p 小 = 一致性显著高于随机）
            p_high = (np.sum(arr >= obs_mean) + 1) / (len(arr) + 1)
            baseline_stats[group] = {
                "baseline_mean": baseline_mean,
                "baseline_ci": (baseline_lo, baseline_hi),
                "p_value": float(p_high),
            }

    # ── 聚合 ────────────────────────────────────────────────────────
    result_per_day = {}
    result_summary = {}
    result_agents = {}

    for group in sorted(per_day.keys()):
        day_agg = {}
        all_vals = []
        for day in sorted(per_day[group].keys()):
            vals = per_day[group][day]
            day_agg[day] = {
                "ncd_sim": float(np.mean(vals)),
                "n": len(vals),
            }
            all_vals.extend(vals)

        obs_mean = _weighted_day_mean(per_day[group])
        ci_lo, ci_hi = _bootstrap_ci(
            per_day[group], B=args.bootstrap, seed=args.seed)
        b_stats = baseline_stats.get(group, {})

        result_per_day[group] = day_agg
        result_summary[group] = {
            "ncd_mean": round(obs_mean, 4),
            "ncd_ci": (round(ci_lo, 4), round(ci_hi, 4)),
            "ncd_std": round(float(np.std(all_vals)), 4),
            "n_pairs": len(all_vals),
            "baseline_mean": round(b_stats.get("baseline_mean", float("nan")), 4),
            "baseline_ci": tuple(round(x, 4) for x in b_stats.get(
                "baseline_ci", (float("nan"), float("nan")))),
            "p_value": b_stats.get("p_value", float("nan")),
            "sig": _sig_mark(b_stats.get("p_value", 1.0)),
        }
        disp = GROUP_DISPLAY.get(group, group)
        s = result_summary[group]
        bl = s["baseline_mean"]
        delta = s["ncd_mean"] - bl if not math.isnan(bl) else float("nan")
        print(f"  {disp}: obs={s['ncd_mean']:.4f} "
              f"[95%CI {s['ncd_ci'][0]:.4f},{s['ncd_ci'][1]:.4f}]  "
              f"baseline={bl:.4f}  Δ={delta:+.4f}  "
              f"p={s['p_value']:.3f} {s['sig']}  (n={s['n_pairs']})")

    for group in sorted(agent_scores.keys()):
        agents = []
        for aid, scores in agent_scores[group].items():
            agents.append(
                (aid, round(float(np.mean(scores)), 4), len(scores)))
        agents.sort(key=lambda x: x[1])
        result_agents[group] = agents

        disp = GROUP_DISPLAY.get(group, group)
        print(f"\n  {disp} 最不一致 Top-5 agents（NCD↑）:")
        for a_id, nm, nd in agents[:5]:
            print(f"    Agent {a_id:3d}: NCD_sim={nm:.4f}  ({nd} days)")

    template_stats = {
        "ngram_sizes": ngram_sizes,
        "global_templates": len(global_tpl),
        "group_templates": {gk: len(v) for gk, v in group_tpl.items()},
        "daily_templates_total": daily_total,
        "total_docs": total,
    }

    return {
        "label": label,
        "per_day": result_per_day,
        "summary": result_summary,
        "agent_scores": result_agents,
        "template_stats": template_stats,
    }


def _empty_result(label: str) -> dict:
    return {"label": label, "per_day": {}, "summary": {},
            "agent_scores": {}, "template_stats": {}}


# ── 绘图 ────────────────────────────────────────────────────────────
def plot_single(exp_result, output_dir, safe_label,
                prefix="推理发帖一致性"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "Arial Unicode MS", "STHeiti",
            "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    per_day = exp_result["per_day"]
    groups = sorted(per_day.keys())
    if not groups:
        return

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = {"tom1": "#2196F3", "tom2_r1": "#FF9800", "tom2_r2": "#FF5722"}
    labels = {"tom1": "ToM-1", "tom2_r1": "ToM-2 一阶", "tom2_r2": "ToM-2 二阶"}

    for gk in groups:
        dd = per_day[gk]
        days = sorted(dd.keys())
        vals = [dd[d]["ncd_sim"] for d in days]
        c = colors.get(gk, "#666")
        lb = labels.get(gk, gk)
        ax.plot(days, vals, color=c, alpha=0.8, label=lb, linewidth=1.2)
        ax.fill_between(days, vals, alpha=0.1, color=c)

    ax.set_ylabel("1 − NCD (去模板, 推理↔帖子)", fontsize=11)
    ax.set_xlabel("交易日", fontsize=11)
    ax.set_title(f"{prefix}（三层去模板 NCD）— {exp_result['label']}",
                 fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    out = os.path.join(output_dir, f"{prefix}_{safe_label}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表: {out}")


def plot_compare(all_results, output_dir, prefix="推理发帖一致性"):
    """多实验对比柱状图（1 − NCD）：
    - 实心柱 = 观测真配对的 1 − NCD
    - 柱顶 CI 误差条 = 95% bootstrap CI
    - 柱顶星号 = 观测 vs shuffle baseline 的显著性
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "Arial Unicode MS", "STHeiti",
            "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    all_groups = set()
    for r in all_results:
        all_groups |= set(r["summary"].keys())
    groups = sorted(all_groups)
    n_groups = len(groups)
    if n_groups == 0:
        return

    colors = {"tom1": "#2196F3", "tom2_r1": "#FF9800", "tom2_r2": "#E53935"}
    labels_map = {"tom1": "ToM-1", "tom2_r1": "ToM-2 一阶", "tom2_r2": "ToM-2 二阶"}

    fig, ax = plt.subplots(figsize=(13, 6))
    n_exp = len(all_results)
    x_base = np.arange(n_exp)
    width = 0.75 / max(n_groups, 1)

    for gi, gk in enumerate(groups):
        means, ci_err_lo, ci_err_hi, sigs = [], [], [], []
        for r in all_results:
            s = r["summary"].get(gk, {})
            m = s.get("ncd_mean", float("nan"))
            lo, hi = s.get("ncd_ci", (m, m))
            means.append(m if not math.isnan(m) else 0)
            ci_err_lo.append(max(0, m - lo) if not math.isnan(m) else 0)
            ci_err_hi.append(max(0, hi - m) if not math.isnan(m) else 0)
            sigs.append(s.get("sig", ""))

        offset = (gi - (n_groups - 1) / 2) * width
        bar_x = x_base + offset
        c = colors.get(gk, "#666")

        # 柱 + CI 误差条
        ax.bar(bar_x, means, width * 0.92,
               yerr=np.array([ci_err_lo, ci_err_hi]),
               color=c, alpha=0.85,
               edgecolor="black", linewidth=0.4,
               capsize=3, error_kw={"linewidth": 0.9, "ecolor": "#333"},
               label=labels_map.get(gk, gk), zorder=3)

        # 柱顶星号
        for xi, m, hi_err, sig in zip(bar_x, means, ci_err_hi, sigs):
            if sig and sig != "n.s." and m > 0:
                ax.text(xi, m + hi_err + 0.005, sig,
                        ha="center", va="bottom",
                        fontsize=9, color=c, fontweight="bold")

    # X/Y 轴
    ax.set_xticks(x_base)
    ax.set_xticklabels([r["label"] for r in all_results],
                       fontsize=10, rotation=0)
    ax.set_xlabel("实验（ToM0 : ToM1 : ToM2 比例）", fontsize=11)
    ax.set_ylabel("推理 ↔ 发帖相似度（1 − NCD）", fontsize=11)
    ax.set_title("心智推理-发帖内容一致性",
                 fontsize=13, pad=12)
    ax.grid(True, alpha=0.25, axis="y")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(bottom=0)

    ax.legend(fontsize=9, loc="lower right", framealpha=0.92)

    # 脚注
    fig.text(0.5, 0.01,
             "柱高 = 观测真配对的 1−NCD（推理↔发帖）；"
             "误差条 = 95% bootstrap CI；"
             "*** p<0.001, ** p<0.01, * p<0.05",
             ha="center", fontsize=8, color="#555")

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    out = os.path.join(output_dir, f"{prefix}_多实验对比.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  对比图: {out}")


def main():
    args = parse_args()
    if args.template_thresh is not None:
        args.global_thresh = args.template_thresh

    # 硬编码实验目录与标签
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

    if not args.run_dirs:
        run_dirs = [os.path.join(RUNS, d) for d, _ in DEFAULT_EXPERIMENTS]
        labels = [lb for _, lb in DEFAULT_EXPERIMENTS]
    else:
        run_dirs = args.run_dirs
        labels = ([l.strip() for l in args.labels.split(",") if l.strip()]
                  if args.labels
                  else [Path(d).name for d in run_dirs])
        if len(labels) < len(run_dirs):
            labels += [Path(d).name for d in run_dirs[len(labels):]]

    os.makedirs(args.output_dir, exist_ok=True)

    all_results = []
    for rd, lb in zip(run_dirs, labels):
        result = analyze_experiment(rd, lb, args)
        all_results.append(result)

    if len(all_results) > 1:
        plot_compare(all_results, args.output_dir, prefix=args.prefix)

    summary = {}
    for r in all_results:
        summary[r["label"]] = {
            "summary": r["summary"],
            "template_stats": r.get("template_stats", {}),
            "least_consistent_agents": {
                gk: [(a[0], a[1]) for a in agents[:10]]
                for gk, agents in r["agent_scores"].items()
            },
        }
    out = os.path.join(args.output_dir, f"{args.prefix}_汇总.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 汇总: {out}")


if __name__ == "__main__":
    main()
