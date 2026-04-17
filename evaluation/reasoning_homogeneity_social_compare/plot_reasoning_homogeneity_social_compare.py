#!/usr/bin/env python3
"""
有社交 vs 无社交：推理同质性对比（TF-IDF 1-2gram 余弦相似度）

自动发现配对实验（X 与 X_无社交），对 decisions.jsonl 中的推理文本做
jieba 分词 + TF-IDF(1-2gram, sublinear_tf) 向量化，计算成对余弦相似度
作为推理同质性指标。IDF 权重天然降权高频词，无需显式三层去模板。

统计：按天采样成对 → 按天加权平均 → bootstrap 95% CI → permutation p 值。

用法：
  python plot_reasoning_homogeneity_social_compare.py [--runs-root ../../runs]
"""

from __future__ import annotations

import argparse
import bisect
import math
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

_EVAL_DIR = Path(__file__).resolve().parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from metrics_plot_common import configure_chinese_font, read_jsonl, safe_int

_MAX_PAIRS = 300


# ── sim_time → trading_day ───────────────────────────────────────────
def _build_time_to_day(run_dir: Path):
    centers = []
    bi_path = run_dir / "broad_index.jsonl"
    if not bi_path.exists():
        return None
    for r in read_jsonl(bi_path):
        st = r.get("sim_time")
        td = safe_int(r.get("trading_day"))
        if st is not None and td is not None:
            centers.append((float(st), td))
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


# ── 推理文本提取 ─────────────────────────────────────────────────────
def _extract_reasoning_parts(llm_output: dict, tom_level: int) -> list[str]:
    """返回推理文本列表（ToM-2 拆分为两条独立文本，避免拼接膨胀相似度）。"""
    if tom_level == 2:
        parts = []
        for k in ("tom1_reasoning", "tom2_reasoning"):
            v = llm_output.get(k, "")
            if v and not v.startswith("(ToM"):
                parts.append(v)
        return parts
    elif tom_level == 1:
        v = llm_output.get("mental_reasoning", "")
        if v and not v.startswith("(ToM"):
            return [v]
    return []


# ── 加载推理文本 ─────────────────────────────────────────────────────
def load_reasoning_texts(run_dir: Path, max_chars: int = 512):
    """返回 { day: { tom_group: [text, ...] } }"""
    mapper = _build_time_to_day(run_dir)
    if mapper is None:
        return {}
    dec_path = run_dir / "decisions.jsonl"
    if not dec_path.exists():
        return {}

    result: dict[int, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list))
    for r in read_jsonl(dec_path):
        tl = r.get("tom_level", 0)
        if tl == 0:
            continue
        out = r.get("llm_output", {})
        parts = _extract_reasoning_parts(out, tl)
        if not parts:
            continue
        day = mapper(float(r["sim_time"]))
        tom_group = f"tom{tl}"
        for text in parts:
            result[day][tom_group].append(text[:max_chars])
    return dict(result)


# ── 成对采样 ─────────────────────────────────────────────────────────
def _sample_pairs(n: int, rng: np.random.Generator | None = None
                  ) -> list[tuple[int, int]]:
    if n < 2:
        return []
    total = n * (n - 1) // 2
    if total <= _MAX_PAIRS:
        return list(combinations(range(n), 2))
    if rng is None:
        rng = np.random.default_rng()
    pairs: set[tuple[int, int]] = set()
    while len(pairs) < _MAX_PAIRS:
        i, j = sorted(rng.choice(n, 2, replace=False))
        pairs.add((int(i), int(j)))
    return list(pairs)


# ── 分词 ─────────────────────────────────────────────────────────────
def _jieba_tokenize(text: str) -> list[str]:
    import jieba
    jieba.setLogLevel(20)
    return [t for t in jieba.cut(text) if t.strip()]


# ── 统一指标：TF-IDF 1-2gram 余弦相似度 ──────────────────────────────
def compute_homogeneity(day_group_texts: dict,
                        seed: int = 42,
                        ) -> dict[int, list[float]] | None:
    """TF-IDF(1-2gram, sublinear_tf, L2-normalize) 余弦相似度。

    IDF 权重 log(N/df) 天然对高频模板词做对数级降权，
    起到"软去模板"作用，无需显式的硬去模板预处理。

    返回 {day: [cos_sim, ...]} 或 None（样本不足）。
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    rng = np.random.default_rng(seed)

    # 展平
    flat_texts: list[str] = []
    flat_day: list[int] = []
    for day in sorted(day_group_texts.keys()):
        for gk in sorted(day_group_texts[day].keys()):
            for text in day_group_texts[day][gk]:
                flat_texts.append(text)
                flat_day.append(day)

    if len(flat_texts) < 4:
        return None

    import time as _t
    _t0 = _t.time()
    vectorizer = TfidfVectorizer(
        tokenizer=_jieba_tokenize,
        token_pattern=None,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        norm="l2",
    )
    X = vectorizer.fit_transform(flat_texts)
    print(f"    TF-IDF: vocab={X.shape[1]}, docs={X.shape[0]}, "
          f"vectorize in {_t.time()-_t0:.1f}s")

    # 每日文档行号
    day_to_rows: dict[int, list[int]] = defaultdict(list)
    for row, d in enumerate(flat_day):
        day_to_rows[d].append(row)

    per_day_sims: dict[int, list[float]] = {}
    for day, rows in day_to_rows.items():
        n = len(rows)
        pairs = _sample_pairs(n, rng=rng)
        if not pairs:
            continue
        sims = [float((X[rows[i]] @ X[rows[j]].T).toarray()[0, 0])
                for i, j in pairs]
        if sims:
            per_day_sims[day] = sims

    return per_day_sims or None


# ── 聚合 / 统计 ──────────────────────────────────────────────────────
def weighted_day_mean(per_day_sims: dict[int, list[float]]) -> float:
    """按每日对数量加权，得全实验相似度均值。"""
    daily_means = []
    weights = []
    for day, sims in per_day_sims.items():
        if not sims:
            continue
        daily_means.append(float(np.mean(sims)))
        weights.append(len(sims))
    if not daily_means:
        return float("nan")
    return float(np.average(daily_means, weights=weights))


def bootstrap_ci(per_day_sims: dict[int, list[float]],
                 B: int = 500, seed: int = 42,
                 alpha: float = 0.05) -> tuple[float, float]:
    """按"天"为重采样单位的 bootstrap 95% CI。"""
    rng = np.random.default_rng(seed)
    days = [d for d, s in per_day_sims.items() if s]
    if len(days) < 2:
        m = weighted_day_mean(per_day_sims)
        return (m, m)
    daily_means_all = np.array([float(np.mean(per_day_sims[d])) for d in days])
    weights_all = np.array([len(per_day_sims[d]) for d in days])
    n_days = len(days)
    estimates = []
    for _ in range(B):
        idx = rng.integers(0, n_days, size=n_days)  # 有放回
        estimates.append(float(
            np.average(daily_means_all[idx], weights=weights_all[idx])))
    lo = float(np.quantile(estimates, alpha / 2))
    hi = float(np.quantile(estimates, 1 - alpha / 2))
    return (lo, hi)


def permutation_pvalue(social_sims: dict[int, list[float]],
                       nosocial_sims: dict[int, list[float]],
                       B: int = 1000, seed: int = 42) -> float:
    """以"天"为单元的非配对 permutation test，检验 Δ = social − nosocial ≠ 0。"""
    rng = np.random.default_rng(seed)
    s_days = [(float(np.mean(v)), len(v))
              for v in social_sims.values() if v]
    n_days = [(float(np.mean(v)), len(v))
              for v in nosocial_sims.values() if v]
    if not s_days or not n_days:
        return float("nan")

    def _wmean(items):
        vals, ws = zip(*items)
        return float(np.average(vals, weights=ws))

    obs = _wmean(s_days) - _wmean(n_days)
    pooled = s_days + n_days
    n_s = len(s_days)
    idx = np.arange(len(pooled))
    extreme = 0
    for _ in range(B):
        rng.shuffle(idx)
        perm_s = [pooled[i] for i in idx[:n_s]]
        perm_n = [pooled[i] for i in idx[n_s:]]
        diff = _wmean(perm_s) - _wmean(perm_n)
        if abs(diff) >= abs(obs):
            extreme += 1
    return (extreme + 1) / (B + 1)


# ── 配对实验发现 ─────────────────────────────────────────────────────
def find_social_pairs(runs_root: Path) -> list[tuple[str, Path, Path]]:
    dirs = {d.name: d for d in runs_root.iterdir() if d.is_dir()}
    pairs = []
    for name in sorted(dirs):
        if name.endswith("_无社交"):
            base = name[: -len("_无社交")]
            if base in dirs:
                pairs.append((base, dirs[base], dirs[name]))

    def _sort_key(item):
        m = re.fullmatch(r"ToM(\d+)", item[0])
        return (0, int(m.group(1))) if m else (1, item[0])

    pairs.sort(key=_sort_key)
    return pairs


# ── 哑铃图绘制 ───────────────────────────────────────────────────────
_LABEL_ALIAS = {
    "ToM01_ToM11_ToM21": "1:1:1",
}


def _pretty_label(raw: str) -> str:
    return _LABEL_ALIAS.get(raw, raw)


def _pval_star(p: float) -> str:
    if math.isnan(p):
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "n.s."


def plot_dumbbell(data: list[dict], output: str,
                  ylabel: str = "平均余弦相似度（TF-IDF 1-2gram）",
                  suptitle: str = "有社交 vs 无社交：推理同质性对比"):
    """灰度哑铃图 + CI 误差条 + p 值显著性标注。"""
    configure_chinese_font()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(data)
    if n == 0:
        return

    labels = [_pretty_label(d["label"]) for d in data]
    social_vals = np.array([d["social"] for d in data])
    nosocial_vals = np.array([d["nosocial"] for d in data])

    # CI（缺省时退化为 0 宽度误差条）
    s_ci = [d.get("social_ci") for d in data]
    n_ci = [d.get("nosocial_ci") for d in data]

    def _err(vals, cis):
        lo = np.array([v - c[0] if c else 0 for v, c in zip(vals, cis)])
        hi = np.array([c[1] - v if c else 0 for v, c in zip(vals, cis)])
        return np.vstack([lo, hi])

    s_err = _err(social_vals, s_ci)
    n_err = _err(nosocial_vals, n_ci)

    x = np.arange(n)
    fig, ax = plt.subplots(figsize=(max(5, 1.6 * n + 2), 4.6), dpi=120)

    for i in range(n):
        ax.plot([x[i], x[i]], [social_vals[i], nosocial_vals[i]],
                color="#999999", linewidth=2, zorder=1)

    ax.errorbar(x, nosocial_vals, yerr=n_err, fmt="none",
                ecolor="#888888", elinewidth=1.0, capsize=4, zorder=1.5)
    ax.errorbar(x, social_vals, yerr=s_err, fmt="none",
                ecolor="#333333", elinewidth=1.0, capsize=4, zorder=1.5)

    ax.scatter(x, nosocial_vals, s=100, color="#e0e0e0",
               edgecolors="black", linewidths=0.8, zorder=2, label="无社交")
    ax.scatter(x, social_vals, s=100, color="#424242",
               edgecolors="black", linewidths=0.8, zorder=2, label="有社交")

    for i in range(n):
        for val in (nosocial_vals[i], social_vals[i]):
            ax.annotate(f"{val:.4f}", (x[i], val), fontsize=8,
                        ha="left", va="center",
                        xytext=(12, 0), textcoords="offset points")

    # Δ + p 值标注（顶部）
    y_max_obs = float(max(np.max(social_vals + s_err[1]),
                          np.max(nosocial_vals + n_err[1])))
    y_min_obs = float(min(np.min(social_vals - s_err[0]),
                          np.min(nosocial_vals - n_err[0])))
    y_span = y_max_obs - y_min_obs if y_max_obs > y_min_obs else 0.01
    has_pval = any("pvalue" in d for d in data)
    if has_pval:
        for i, d in enumerate(data):
            diff = social_vals[i] - nosocial_vals[i]
            p = d.get("pvalue", float("nan"))
            star = _pval_star(p)
            p_txt = f"p={p:.3f}" if not math.isnan(p) else ""
            txt = f"Δ={diff:+.4f}  {p_txt} {star}".strip()
            ax.text(x[i], y_max_obs + y_span * 0.12, txt,
                    ha="center", va="bottom", fontsize=8, color="#333333")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, alpha=0.15, axis="y")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.margins(x=0.2)

    if has_pval:
        cur_lo, cur_hi = ax.get_ylim()
        ax.set_ylim(cur_lo, cur_hi + y_span * 0.15)

    ax.legend(fontsize=10, loc="lower right")

    fig.suptitle(suptitle, fontsize=13)
    plt.tight_layout()
    fig.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] {output}")


# ── main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="有社交 vs 无社交 推理同质性对比")
    parser.add_argument("--runs-root", default="../../runs",
                        help="runs 目录")
    parser.add_argument("--max-chars", type=int, default=512,
                        help="推理文本截断字符数")
    parser.add_argument("--bootstrap", type=int, default=500,
                        help="bootstrap 重采样次数")
    parser.add_argument("--permutation", type=int, default=1000,
                        help="permutation test 次数")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    runs_root = Path(args.runs_root).resolve()
    # 若当前 CWD 下找不到，则回退到仓库根（脚本位置向上两级）
    if not runs_root.exists():
        repo_root = Path(__file__).resolve().parents[2]
        fallback = (repo_root / args.runs_root).resolve()
        if not fallback.exists():
            fallback = repo_root / "runs"
        runs_root = fallback
    if not runs_root.exists():
        print(f"[ERROR] runs 目录不存在: {runs_root}", file=sys.stderr)
        sys.exit(1)

    pairs = find_social_pairs(runs_root)
    if not pairs:
        print("[ERROR] 未找到配对实验", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(pairs)} 组配对:")

    data = []
    for label, social_dir, nosocial_dir in pairs:
        print(f"\n--- {label} ---")

        print(f"  有社交: {social_dir.name}")
        s_texts = load_reasoning_texts(social_dir, args.max_chars)
        s_sims = compute_homogeneity(s_texts, seed=args.seed)

        print(f"  无社交: {nosocial_dir.name}")
        n_texts = load_reasoning_texts(nosocial_dir, args.max_chars)
        n_sims = compute_homogeneity(n_texts, seed=args.seed)

        if s_sims is None or n_sims is None:
            print(f"  [SKIP] {label}: 缺少有效推理文本")
            continue

        s_mean = weighted_day_mean(s_sims)
        n_mean = weighted_day_mean(n_sims)
        s_lo, s_hi = bootstrap_ci(s_sims, B=args.bootstrap, seed=args.seed)
        n_lo, n_hi = bootstrap_ci(n_sims, B=args.bootstrap, seed=args.seed)
        pval = permutation_pvalue(s_sims, n_sims,
                                  B=args.permutation, seed=args.seed)

        print(f"  cos: 有社交={s_mean:.4f} [95%CI {s_lo:.4f},{s_hi:.4f}]  "
              f"无社交={n_mean:.4f} [95%CI {n_lo:.4f},{n_hi:.4f}]")
        print(f"       Δ={s_mean - n_mean:+.4f}  "
              f"permutation p={pval:.4f}  (B={args.permutation})")

        data.append({
            "label": label,
            "social": s_mean, "nosocial": n_mean,
            "social_ci": (s_lo, s_hi), "nosocial_ci": (n_lo, n_hi),
            "pvalue": pval,
        })

    out_dir = Path(__file__).resolve().parent
    if data:
        plot_dumbbell(
            data,
            str(out_dir / "reasoning_homogeneity_compare.png"),
            ylabel="平均余弦相似度（TF-IDF 1-2gram）",
            suptitle="有社交 vs 无社交：推理同质性对比")


if __name__ == "__main__":
    main()
