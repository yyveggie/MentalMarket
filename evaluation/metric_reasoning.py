"""Reasoning homogeneity & reasoning-post consistency metrics.

Lightweight implementation for eval_web:
- Uses character-level bigrams (no jieba dependency)
- NCD via zlib
- Samples pairs when group size > 30
"""

from __future__ import annotations

import zlib
import random
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from metrics_plot_common import read_jsonl, safe_int, safe_float

_MAX_PAIRS = 200


def _char_bigrams(text: str) -> set[str]:
    text = text.strip()
    if len(text) < 2:
        return set()
    return {text[i:i+2] for i in range(len(text) - 1)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


def _ncd_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ca = len(zlib.compress(a.encode("utf-8")))
    cb = len(zlib.compress(b.encode("utf-8")))
    cab = len(zlib.compress((a + b).encode("utf-8")))
    ncd = (cab - min(ca, cb)) / max(ca, cb) if max(ca, cb) > 0 else 0.0
    return max(0.0, 1.0 - ncd)


def _extract_reasoning(llm_output: dict, tom_level: int) -> dict[str, str]:
    if tom_level == 2:
        parts = {}
        r1 = llm_output.get("tom1_reasoning", "")
        r2 = llm_output.get("tom2_reasoning", "")
        if r1 and not r1.startswith("(ToM"):
            parts["r1"] = r1
        if r2 and not r2.startswith("(ToM"):
            parts["r2"] = r2
        return parts
    else:
        mr = llm_output.get("mental_reasoning", "")
        if mr and not mr.startswith("(ToM"):
            return {"": mr}
        return {}


def _build_time_to_day(run_dir: Path):
    import bisect
    bi_path = run_dir / "broad_index.jsonl"
    if not bi_path.exists():
        return lambda t: max(1, int(t / 3600) + 1)
    centers = []
    for r in read_jsonl(bi_path):
        st = r.get("sim_time")
        td = safe_int(r.get("trading_day"))
        if st is not None and td is not None:
            centers.append((float(st), td))
    if not centers:
        return lambda t: max(1, int(t / 3600) + 1)
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


def compute_reasoning_homogeneity(run_dir: Path, max_chars: int = 300) -> list[dict]:
    """Per-day per-ToM reasoning text similarity (Jaccard bigram + NCD)."""
    dec_path = run_dir / "decisions.jsonl"
    if not dec_path.exists():
        return []

    time_to_day = _build_time_to_day(run_dir)

    # group: (day, tom, suffix) -> list[str]
    groups: dict[tuple, list[str]] = defaultdict(list)
    for row in read_jsonl(dec_path):
        tom = safe_int(row.get("tom_level"))
        if tom is None or tom == 0:
            continue
        st = safe_float(row.get("sim_time"))
        if st is None:
            continue
        day = time_to_day(st)
        llm = row.get("llm_output") or row.get("action_executed") or {}
        if isinstance(llm, str):
            continue
        parts = _extract_reasoning(llm, tom)
        for suffix, text in parts.items():
            text = text[:max_chars].strip()
            if len(text) >= 10:
                groups[(day, tom, suffix)].append(text)

    result = []
    for (day, tom, suffix), texts in sorted(groups.items()):
        if len(texts) < 2:
            continue
        bigram_sets = [_char_bigrams(t) for t in texts]
        pairs = list(combinations(range(len(texts)), 2))
        if len(pairs) > _MAX_PAIRS:
            pairs = random.sample(pairs, _MAX_PAIRS)

        jac_vals = [_jaccard(bigram_sets[i], bigram_sets[j]) for i, j in pairs]
        ncd_vals = [_ncd_similarity(texts[i], texts[j]) for i, j in pairs]

        label = f"ToM{tom}" + (f"_{suffix}" if suffix else "")
        result.append({
            "trading_day": day,
            "tom_level": label,
            "jaccard_sim": round(sum(jac_vals) / len(jac_vals), 4),
            "ncd_sim": round(sum(ncd_vals) / len(ncd_vals), 4),
            "pair_count": len(pairs),
            "agent_count": len(texts),
        })

    return result


def compute_reasoning_post_consistency(run_dir: Path, max_chars: int = 300) -> list[dict]:
    """Per-day per-ToM consistency between reasoning and posted content."""
    dec_path = run_dir / "decisions.jsonl"
    posts_path = run_dir / "posts.jsonl"
    if not dec_path.exists() or not posts_path.exists():
        return []

    time_to_day = _build_time_to_day(run_dir)

    # agent reasoning per day
    agent_reasoning: dict[tuple[int, int], str] = {}  # (day, agent_id) -> reasoning
    agent_tom: dict[int, int] = {}
    for row in read_jsonl(dec_path):
        tom = safe_int(row.get("tom_level"))
        aid = safe_int(row.get("agent_id"))
        st = safe_float(row.get("sim_time"))
        if tom is None or tom == 0 or aid is None or st is None:
            continue
        day = time_to_day(st)
        agent_tom[aid] = tom
        llm = row.get("llm_output") or row.get("action_executed") or {}
        if isinstance(llm, str):
            continue
        parts = _extract_reasoning(llm, tom)
        combined = " ".join(parts.values())[:max_chars].strip()
        if len(combined) >= 10:
            key = (day, aid)
            agent_reasoning[key] = combined

    # agent posts per day
    agent_posts: dict[tuple[int, int], str] = defaultdict(str)
    for row in read_jsonl(posts_path):
        aid = safe_int(row.get("agent_id"))
        day = safe_int(row.get("trading_day"))
        if aid is None or day is None or aid < 0:
            continue
        if row.get("source") not in ("agent_tool",):
            continue
        content = str(row.get("content", ""))[:max_chars]
        agent_posts[(day, aid)] += " " + content

    # compute per (day, tom) consistency
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for (day, aid), reasoning in agent_reasoning.items():
        post_text = agent_posts.get((day, aid), "").strip()
        if len(post_text) < 5:
            continue
        tom = agent_tom.get(aid, 0)
        j = _jaccard(_char_bigrams(reasoning), _char_bigrams(post_text))
        n = _ncd_similarity(reasoning, post_text)
        buckets[(day, tom)].append((j, n))

    result = []
    for (day, tom), vals in sorted(buckets.items()):
        if not vals:
            continue
        jac_avg = sum(v[0] for v in vals) / len(vals)
        ncd_avg = sum(v[1] for v in vals) / len(vals)
        result.append({
            "trading_day": day,
            "tom_level": tom,
            "jaccard_consistency": round(jac_avg, 4),
            "ncd_consistency": round(ncd_avg, 4),
            "agent_count": len(vals),
        })

    return result
