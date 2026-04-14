#!/usr/bin/env python3
"""
推理-发帖一致性分析（Reasoning vs. Post Consistency）

检测智能体"想的"（心智推理）和"说的"（社交帖子）之间的一致程度。
低一致性意味着潜在的策略性操纵：思考一套，发帖另一套。

指标：
  - Jaccard 相似度（jieba bigram，去模板后）
  - NCD 相似度（zlib 压缩距离）

输出：
  1. 每实验单图：按 ToM 层级的 reasoning-post 一致性时间序列
  2. 多实验对比箱线图
  3. JSON 汇总

用法：
  python plot_reasoning_post_consistency.py \
    runs/20260329_005147_tom07_tom12_tom21_预测拟合 \
    runs/20260329_150251_tom01_tom11_tom21_预测拟合 \
    runs/20260330_211929_tom06_tom13_tom21_预测拟合 \
    --labels "tom07/12/21,tom01/11/21,tom06/13/21" \
    --output-dir output/reasoning_homogeneity
"""

import argparse
import bisect
import json
import os
import re
import sys
import zlib
from collections import defaultdict
from pathlib import Path

import numpy as np

# ── CLI ──────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="推理-发帖一致性分析")
    p.add_argument("run_dirs", nargs="+", help="实验目录")
    p.add_argument("--labels", default="", help="逗号分隔的实验标签")
    p.add_argument("--ngram", type=int, default=2, help="n-gram 大小")
    p.add_argument("--template-thresh", type=float, default=0.80,
                   help="出现在 >X%% 文本中的 n-gram 视为模板")
    p.add_argument("--max-chars", type=int, default=512,
                   help="每条文本截断字符数")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--prefix", default="推理发帖一致性",
                   help="输出文件名前缀 (默认: 推理发帖一致性)")
    return p.parse_args()


# ── sim_time → trading_day ───────────────────────────────────────────
def _build_time_to_day(run_dir: str):
    centers = []
    with open(os.path.join(run_dir, "broad_index.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            centers.append((rec["sim_time"], rec["trading_day"]))
    centers.sort()
    times = [c[0] for c in centers]
    days  = [c[1] for c in centers]

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


# ── 推理文本提取 ─────────────────────────────────────────────────────
def _extract_reasoning_parts(llm_output: dict, tom_level: int) -> dict:
    """
    返回 { group_suffix: text } 字典。
    tom1: {"": mental_reasoning}
    tom2: {"_r1": tom1_reasoning, "_r2": tom2_reasoning}（独立拆分）
    tom0: {} （跳过）
    """
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


# ── 帖子清洗 ────────────────────────────────────────────────────────
_RETWEET_RE = re.compile(r"\[转发\s*@[A-Za-z0-9_]+\]\s*")

def _clean_post(content: str) -> str:
    """去掉 [转发 @Axx] 前缀，保留原创内容。"""
    return _RETWEET_RE.sub("", content).strip()


# ── 加载数据 ────────────────────────────────────────────────────────
def load_data(run_dir: str, max_chars: int):
    """
    返回 { agent_id: { day: { 'reasoning_parts': {suffix: text}, 'posts': [str, ...], 'tom': int } } }
    跳过 tom0（无有效推理）。
    """
    mapper = _build_time_to_day(run_dir)
    data = defaultdict(lambda: defaultdict(lambda: {"reasoning_parts": {}, "posts": [], "tom": 0}))

    # 1) decisions
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
                data[aid][day]["reasoning_parts"] = {k: v[:max_chars] for k, v in parts.items()}
                data[aid][day]["tom"] = tl

    # 2) posts
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


# ── jieba 分词 + n-gram ─────────────────────────────────────────────
def _tokenize(text: str):
    import jieba
    return list(jieba.cut(text))


def _ngrams(tokens: list, n: int):
    return set(tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1))


# ── 模板检测（全局 DF 阈值）──────────────────────────────────────────
def _find_template_ngrams(all_texts: list, ngram_n: int, thresh: float):
    """返回出现在 >thresh 比例文本中的 n-gram 集合。"""
    import jieba
    jieba.setLogLevel(20)
    from collections import Counter
    doc_count = Counter()
    for text in all_texts:
        tokens = _tokenize(text)
        ng = _ngrams(tokens, ngram_n)
        for g in ng:
            doc_count[g] += 1
    n_docs = len(all_texts)
    templates = {g for g, c in doc_count.items() if c / n_docs > thresh}
    return templates


# ── Jaccard ─────────────────────────────────────────────────────────
def jaccard(set_a, set_b):
    if not set_a and not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


# ── NCD 相似度 ──────────────────────────────────────────────────────
def ncd_similarity(a: str, b: str) -> float:
    ca = len(zlib.compress(a.encode("utf-8")))
    cb = len(zlib.compress(b.encode("utf-8")))
    cab = len(zlib.compress((a + b).encode("utf-8")))
    ncd = (cab - min(ca, cb)) / max(ca, cb) if max(ca, cb) > 0 else 0.0
    return 1.0 - ncd  # 转为相似度


# ── 单实验处理 ──────────────────────────────────────────────────────
GROUP_DISPLAY = {
    "tom1": "ToM-1",
    "tom2_r1": "ToM-2 一阶推理",
    "tom2_r2": "ToM-2 二阶推理",
}

def analyze_experiment(run_dir: str, label: str, args):
    """
    返回 {
      'label': str,
      'per_day': { group: { day: {'jaccard': float, 'ncd': float, 'n': int} } },
      'summary': { group: { 'jaccard_mean', 'jaccard_std', 'ncd_mean', 'ncd_std', 'n_pairs' } },
      'agent_scores': { group: [ (agent_id, jaccard_mean, ncd_mean, n_days) ] }
    }
    """
    print(f"\n{'='*60}")
    print(f"处理: {label}  ({run_dir})")
    print(f"{'='*60}")

    data = load_data(run_dir, args.max_chars)

    # 收集所有文本用于模板检测
    all_texts = []
    for aid_data in data.values():
        for day_data in aid_data.values():
            for txt in day_data["reasoning_parts"].values():
                if txt:
                    all_texts.append(txt)
            all_texts.extend(day_data["posts"])

    print(f"  文本总数: {len(all_texts)}（推理+帖子）")

    # 模板检测
    templates = _find_template_ngrams(all_texts, args.ngram, args.template_thresh)
    total_ngrams = set()
    for t in all_texts[:200]:
        tokens = _tokenize(t)
        total_ngrams |= _ngrams(tokens, args.ngram)
    print(f"  模板 n-gram: {len(templates)} / {len(total_ngrams)} (阈值: >{args.template_thresh*100:.0f}%)")

    # 按 ToM 层级和天分组计算
    # 对每个 agent 每天：每段推理 vs concat(posts) 的相似度
    per_day = defaultdict(lambda: defaultdict(list))   # group -> day -> [scores]
    agent_scores = defaultdict(lambda: defaultdict(list))  # group -> agent_id -> [scores]

    for aid, days_data in data.items():
        for day, dd in days_data.items():
            reasoning_parts = dd["reasoning_parts"]
            posts = dd["posts"]
            tom = dd["tom"]
            if not reasoning_parts or not posts:
                continue

            # 合并帖子文本
            post_text = "\n".join(posts)
            p_tokens = _tokenize(post_text)
            p_ngrams = _ngrams(p_tokens, args.ngram) - templates

            # 对每个推理分量独立比较
            for suffix, reasoning in reasoning_parts.items():
                group = f"tom{tom}{suffix}"

                r_tokens = _tokenize(reasoning)
                r_ngrams = _ngrams(r_tokens, args.ngram) - templates

                j = jaccard(r_ngrams, p_ngrams)
                ncd_sim = ncd_similarity(reasoning, post_text)

                per_day[group][day].append({"jaccard": j, "ncd": ncd_sim})
                agent_scores[group][aid].append({"jaccard": j, "ncd": ncd_sim})

    # 聚合
    result_per_day = {}
    result_summary = {}
    result_agents = {}

    for group in sorted(per_day.keys()):
        day_agg = {}
        all_j, all_n = [], []
        for day in sorted(per_day[group].keys()):
            scores = per_day[group][day]
            j_vals = [s["jaccard"] for s in scores]
            n_vals = [s["ncd"] for s in scores]
            day_agg[day] = {
                "jaccard": float(np.mean(j_vals)),
                "ncd": float(np.mean(n_vals)),
                "n": len(scores),
            }
            all_j.extend(j_vals)
            all_n.extend(n_vals)

        result_per_day[group] = day_agg
        result_summary[group] = {
            "jaccard_mean": round(float(np.mean(all_j)), 4),
            "jaccard_std": round(float(np.std(all_j)), 4),
            "ncd_mean": round(float(np.mean(all_n)), 4),
            "ncd_std": round(float(np.std(all_n)), 4),
            "n_pairs": len(all_j),
        }
        disp = GROUP_DISPLAY.get(group, group)
        print(f"  {disp}: Jaccard={result_summary[group]['jaccard_mean']:.4f}±{result_summary[group]['jaccard_std']:.4f}  "
              f"NCD_sim={result_summary[group]['ncd_mean']:.4f}±{result_summary[group]['ncd_std']:.4f}  "
              f"(n={result_summary[group]['n_pairs']})")

    # agent 级排序（按一致性从低到高 → 最可能操纵）
    for group in sorted(agent_scores.keys()):
        agents = []
        for aid, scores in agent_scores[group].items():
            j_mean = float(np.mean([s["jaccard"] for s in scores]))
            n_mean = float(np.mean([s["ncd"] for s in scores]))
            agents.append((aid, round(j_mean, 4), round(n_mean, 4), len(scores)))
        agents.sort(key=lambda x: x[1])  # 按 Jaccard 升序 → 最不一致的在前
        result_agents[group] = agents

        disp = GROUP_DISPLAY.get(group, group)
        print(f"\n  {disp} 最不一致 Top-5 agents（Jaccard↑）:")
        for aid, jm, nm, nd in agents[:5]:
            print(f"    Agent {aid:3d}: Jaccard={jm:.4f}  NCD_sim={nm:.4f}  ({nd} days)")

    return {
        "label": label,
        "per_day": result_per_day,
        "summary": result_summary,
        "agent_scores": result_agents,
    }


# ── 绘图 ────────────────────────────────────────────────────────────
def plot_single(exp_result, output_dir, safe_label, prefix="推理发帖一致性"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.sans-serif": ["Heiti TC", "Arial Unicode MS", "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    per_day = exp_result["per_day"]
    groups = sorted(per_day.keys())
    if not groups:
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    colors = {"tom1": "#2196F3", "tom2_r1": "#FF9800", "tom2_r2": "#FF5722"}
    labels = {"tom1": "ToM-1", "tom2_r1": "ToM-2 一阶", "tom2_r2": "ToM-2 二阶"}

    for gk in groups:
        dd = per_day[gk]
        days = sorted(dd.keys())
        j_vals = [dd[d]["jaccard"] for d in days]
        n_vals = [dd[d]["ncd"] for d in days]
        c = colors.get(gk, "#666")
        lb = labels.get(gk, gk)

        axes[0].plot(days, j_vals, color=c, alpha=0.8, label=lb, linewidth=1.2)
        axes[0].fill_between(days, j_vals, alpha=0.15, color=c)
        axes[1].plot(days, n_vals, color=c, alpha=0.8, label=lb, linewidth=1.2)
        axes[1].fill_between(days, n_vals, alpha=0.15, color=c)

    axes[0].set_ylabel("Jaccard (推理↔帖子)")
    axes[0].set_title(f"{prefix} — {exp_result['label']}")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim(bottom=0)

    axes[1].set_ylabel("NCD 相似度 (推理↔帖子)")
    axes[1].set_xlabel("Trading Day")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    axes[1].set_ylim(bottom=0)

    plt.tight_layout()
    out = os.path.join(output_dir, f"{prefix}_{safe_label}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表: {out}")


def plot_compare(all_results, output_dir, prefix="推理发帖一致性"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.sans-serif": ["Heiti TC", "Arial Unicode MS", "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    # 收集所有组
    all_groups = set()
    for r in all_results:
        all_groups |= set(r["summary"].keys())
    groups = sorted(all_groups)
    n_groups = len(groups)

    if n_groups == 0:
        return

    # === 图1: 分组柱状图 ===
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    x = np.arange(len(all_results))
    width = 0.8 / max(n_groups, 1)
    colors = {"tom1": "#2196F3", "tom2_r1": "#FF9800", "tom2_r2": "#FF5722"}
    labels_map = {"tom1": "ToM-1", "tom2_r1": "ToM-2 一阶", "tom2_r2": "ToM-2 二阶"}

    for gi, gk in enumerate(groups):
        j_means = []
        j_stds = []
        n_means = []
        n_stds = []
        for r in all_results:
            s = r["summary"].get(gk, {})
            j_means.append(s.get("jaccard_mean", 0))
            j_stds.append(s.get("jaccard_std", 0))
            n_means.append(s.get("ncd_mean", 0))
            n_stds.append(s.get("ncd_std", 0))

        offset = (gi - (n_groups - 1) / 2) * width
        c = colors.get(gk, "#666")
        lb = labels_map.get(gk, gk)
        axes[0].bar(x + offset, j_means, width * 0.9, yerr=j_stds,
                    label=lb, color=c, alpha=0.8, capsize=3)
        axes[1].bar(x + offset, n_means, width * 0.9, yerr=n_stds,
                    label=lb, color=c, alpha=0.8, capsize=3)

    exp_labels = [r["label"] for r in all_results]
    for ax, title in zip(axes, ["Jaccard 一致性", "NCD 一致性"]):
        ax.set_xticks(x)
        ax.set_xticklabels(exp_labels, fontsize=9)
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        ax.set_ylim(bottom=0)

    fig.suptitle(f"{prefix} — 多实验对比", fontsize=13, fontweight="bold")
    plt.tight_layout()
    out = os.path.join(output_dir, f"{prefix}_多实验对比.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  对比图: {out}")

    # === 图2: Agent 散点图 ===
    fig, axes = plt.subplots(1, len(all_results), figsize=(5 * len(all_results), 5),
                              squeeze=False)
    for ri, r in enumerate(all_results):
        ax = axes[0][ri]
        for gk in groups:
            agents = r["agent_scores"].get(gk, [])
            if not agents:
                continue
            c = colors.get(gk, "#666")
            lb = labels_map.get(gk, gk)
            aids = [a[0] for a in agents]
            j_vals = [a[1] for a in agents]
            n_vals = [a[2] for a in agents]
            ax.scatter(j_vals, n_vals, c=c, alpha=0.6, s=30, label=lb)
            # 标注最不一致的 3 个
            for a in agents[:3]:
                ax.annotate(f"A{a[0]}", (a[1], a[2]), fontsize=7, alpha=0.7)
        ax.set_xlabel("Jaccard")
        ax.set_ylabel("NCD sim")
        ax.set_title(r["label"])
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle(f"{prefix} — Agent分布", fontsize=13, fontweight="bold")
    plt.tight_layout()
    out = os.path.join(output_dir, f"{prefix}_Agent分布.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  散点图: {out}")


# ── main ─────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    labels = [l.strip() for l in args.labels.split(",") if l.strip()] \
             if args.labels else [Path(d).name for d in args.run_dirs]
    if len(labels) < len(args.run_dirs):
        labels += [Path(d).name for d in args.run_dirs[len(labels):]]

    all_results = []
    for rd, lb in zip(args.run_dirs, labels):
        safe = lb.replace("/", "_").replace(" ", "_")
        result = analyze_experiment(rd, lb, args)
        plot_single(result, args.output_dir, safe, prefix=args.prefix)
        all_results.append(result)

    if len(all_results) > 1:
        plot_compare(all_results, args.output_dir, prefix=args.prefix)

    # JSON 汇总
    summary = {}
    for r in all_results:
        summary[r["label"]] = {
            "summary": r["summary"],
            "least_consistent_agents": {
                gk: [(a[0], a[1], a[2]) for a in agents[:10]]
                for gk, agents in r["agent_scores"].items()
            },
        }
    out = os.path.join(args.output_dir, f"{args.prefix}_汇总.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 汇总: {out}")


if __name__ == "__main__":
    main()
