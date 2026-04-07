"""Social network activity, information diffusion, sentiment dynamics,
social-trading nexus, reputation system, and KOL market impact metrics."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from metrics_plot_common import read_jsonl, safe_int


# ──────────────────────────────────────────────────────────────
# 1. 社交网络活跃度 (per day, per tom_level)
# ──────────────────────────────────────────────────────────────

def compute_social_activity(run_dir: Path) -> list[dict]:
    """
    从 social_graph_events.jsonl 计算每日每 ToM 层级的社交活跃指标。

    返回行: {trading_day, tom_level, like_events, follow_events,
             unique_likers, avg_likes_given, like_targets_unique}
    """
    fpath = run_dir / "social_graph_events.jsonl"
    if not fpath.exists():
        return []

    rows = read_jsonl(fpath)

    # 按 (day, tom) 聚合
    # key = (trading_day, tom_level)
    day_tom_likes: dict[tuple[int, int], list[int]] = defaultdict(list)  # liker agent ids
    day_tom_follows: dict[tuple[int, int], int] = defaultdict(int)
    day_tom_like_targets: dict[tuple[int, int], set[int]] = defaultdict(set)

    for r in rows:
        day = safe_int(r.get("trading_day"))
        tom = r.get("tom_level")
        if day is None or tom is None:
            continue
        tom = int(tom)
        event = r.get("event", "")
        key = (day, tom)

        if event == "like":
            day_tom_likes[key].append(r.get("agent_id", -1))
            target = r.get("target_agent_id")
            if target is not None:
                day_tom_like_targets[key].add(target)
        elif event == "follow":
            day_tom_follows[key] += 1

    all_keys = set(day_tom_likes.keys()) | set(day_tom_follows.keys())
    if not all_keys:
        return []

    # 从 config.yaml 读取 agent 总数，读不到则默认 100
    total_agents = 100
    cfg_path = run_dir / "config.yaml"
    if cfg_path.exists():
        import yaml
        with open(cfg_path) as _f:
            _cfg = yaml.safe_load(_f) or {}
        total_agents = max(1, (_cfg.get("agent") or {}).get("n_agents", 100))

    # 补齐所有 day × tom 组合，确保无事件天也输出 0 而非缺失
    all_days = sorted({d for d, _ in all_keys})
    all_toms = sorted({t for _, t in all_keys})
    day_min, day_max = all_days[0], all_days[-1]

    result = []
    for day in range(day_min, day_max + 1):
        for tom in all_toms:
            key = (day, tom)
            likers = day_tom_likes.get(key, [])
            unique_likers = len(set(likers))
            like_count = len(likers)
            follow_count = day_tom_follows.get(key, 0)
            targets_unique = len(day_tom_like_targets.get(key, set()))

            result.append({
                "trading_day": day,
                "tom_level": tom,
                "like_events": like_count,
                "follow_events": follow_count,
                "unique_likers": unique_likers,
                "avg_likes_given": round(like_count / total_agents, 4),
                "like_targets_unique": targets_unique,
            })

    return result


# ──────────────────────────────────────────────────────────────
# 2. 信息传播与参与度 (per day, market-level)
# ──────────────────────────────────────────────────────────────

def compute_info_diffusion(run_dir: Path) -> list[dict]:
    """
    从 posts.jsonl + social_graph_events.jsonl 计算每日信息传播指标。

    返回行: {trading_day, total_posts, agent_posts, retweet_posts, news_posts,
             retweet_ratio, avg_likes_per_post, max_post_likes,
             unique_posters, posting_rate}
    """
    posts_path = run_dir / "posts.jsonl"
    events_path = run_dir / "social_graph_events.jsonl"

    # ── 读取帖子数据 ──
    posts_by_day: dict[int, list[dict]] = defaultdict(list)
    if posts_path.exists():
        for r in read_jsonl(posts_path):
            day = safe_int(r.get("trading_day"))
            if day is None:
                continue
            posts_by_day[day].append(r)

    # ── 每帖获赞数：优先读 posts.jsonl 自带的 likes 字段，回退到事件统计 ──
    post_likes: dict[int, int] = defaultdict(int)  # post_id -> like count
    # 先从帖子记录自带 likes 字段取
    _has_inline_likes = False
    for day_posts in posts_by_day.values():
        for p in day_posts:
            lk = p.get("likes")
            if lk is not None and lk > 0:
                _has_inline_likes = True
                post_likes[p.get("post_id", -999)] = int(lk)
    # 若帖子无内嵌 likes，从 social_graph_events 统计
    if not _has_inline_likes and events_path.exists():
        for r in read_jsonl(events_path):
            if r.get("event") == "like":
                pid = r.get("post_id")
                if pid is not None:
                    post_likes[pid] += 1

    # ── 估算总 agent 数量（从帖子中提取唯一 agent_id，排除系统 -1）──
    all_agent_ids: set[int] = set()
    for day_posts in posts_by_day.values():
        for p in day_posts:
            aid = p.get("agent_id")
            if aid is not None and aid >= 0:
                all_agent_ids.add(aid)
    total_agents = max(1, len(all_agent_ids))

    if not posts_by_day:
        return []

    result = []
    for day in sorted(posts_by_day.keys()):
        day_posts = posts_by_day[day]
        total = len(day_posts)

        agent_posts = sum(1 for p in day_posts if p.get("source") == "agent_tool")
        retweet_posts = sum(1 for p in day_posts if p.get("source") == "retweet")
        news_posts = sum(1 for p in day_posts if p.get("source") == "news")

        # 每帖获赞
        day_likes = [post_likes.get(p.get("post_id", -999), 0) for p in day_posts]
        avg_likes = round(sum(day_likes) / max(1, total), 2)
        max_likes = max(day_likes) if day_likes else 0

        # 独立发帖人（排除系统 agent_id=-1）
        posters = set()
        for p in day_posts:
            aid = p.get("agent_id")
            if aid is not None and aid >= 0:
                posters.add(aid)
        unique_posters = len(posters)

        result.append({
            "trading_day": day,
            "total_posts": total,
            "agent_posts": agent_posts,
            "retweet_posts": retweet_posts,
            "news_posts": news_posts,
            "retweet_ratio": round(retweet_posts / max(1, agent_posts), 3),
            "avg_likes_per_post": avg_likes,
            "max_post_likes": max_likes,
            "unique_posters": unique_posters,
            "posting_rate": round(unique_posters / total_agents * 100, 1),
        })

    return result


# ──────────────────────────────────────────────────────────────
# 2b. 信息传播与参与度（按 ToM 分组）
# ──────────────────────────────────────────────────────────────

def _build_agent_tom_map(run_dir: Path) -> dict[int, int]:
    """从 agents_final.jsonl 建立 agent_id → tom_level 映射。"""
    fpath = run_dir / "agents_final.jsonl"
    if not fpath.exists():
        return {}
    import json
    mapping: dict[int, int] = {}
    for line in open(fpath):
        try:
            r = json.loads(line)
            aid = r.get("agent_id")
            tom = r.get("tom_level")
            if aid is not None and tom is not None:
                mapping[int(aid)] = int(tom)
        except Exception:
            continue
    return mapping


def compute_info_diffusion_by_tom(run_dir: Path) -> list[dict]:
    """按 ToM 分组的每日信息传播指标。"""
    posts_path = run_dir / "posts.jsonl"
    if not posts_path.exists():
        return []

    agent_tom = _build_agent_tom_map(run_dir)
    if not agent_tom:
        return []

    # 读取帖子，按 (day, tom) 分组
    from metrics_plot_common import safe_int
    day_tom_posts: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in read_jsonl(posts_path):
        day = safe_int(r.get("trading_day"))
        aid = r.get("agent_id")
        if day is None or aid is None:
            continue
        tom = agent_tom.get(int(aid))
        if tom is None:
            continue
        day_tom_posts[(day, tom)].append(r)

    if not day_tom_posts:
        return []

    # 帖子获赞（复用 inline likes 逻辑）
    post_likes: dict[int, int] = defaultdict(int)
    for r in read_jsonl(posts_path):
        lk = r.get("likes")
        if lk is not None and lk > 0:
            post_likes[r.get("post_id", -999)] = int(lk)

    # 每个 tom 层级的 agent 数量
    from collections import Counter
    tom_agent_count = Counter(agent_tom.values())

    all_keys = sorted(day_tom_posts.keys())
    all_days = sorted({d for d, _ in all_keys})
    all_toms = sorted({t for _, t in all_keys})
    day_min, day_max = all_days[0], all_days[-1]

    result = []
    for day in range(day_min, day_max + 1):
        for tom in all_toms:
            posts = day_tom_posts.get((day, tom), [])
            total = len(posts)
            agent_posts = sum(1 for p in posts if p.get("source") == "agent_tool")
            retweet_posts = sum(1 for p in posts if p.get("source") == "retweet")

            day_likes = [post_likes.get(p.get("post_id", -999), 0) for p in posts]
            avg_likes = round(sum(day_likes) / max(1, total), 2) if day_likes else 0

            posters = set()
            for p in posts:
                a = p.get("agent_id")
                if a is not None and a >= 0:
                    posters.add(a)
            unique_posters = len(posters)
            n_agents_in_tom = max(1, tom_agent_count.get(tom, 1))

            result.append({
                "trading_day": day,
                "tom_level": tom,
                "total_posts": total,
                "agent_posts": agent_posts,
                "retweet_posts": retweet_posts,
                "avg_likes_per_post": avg_likes,
                "unique_posters": unique_posters,
                "posting_rate": round(unique_posters / n_agents_in_tom * 100, 1),
            })

    return result


# ──────────────────────────────────────────────────────────────
# 3. 情绪传导与共识 (per day, market-level)
# ──────────────────────────────────────────────────────────────

def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation between two same-length lists. Returns None if insufficient."""
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = sum((xs[i] - mx) ** 2 for i in range(n))
    vy = sum((ys[i] - my) ** 2 for i in range(n))
    denom = (vx * vy) ** 0.5
    if denom < 1e-15:
        return None
    return cov / denom


def compute_sentiment_dynamics(run_dir: Path, window: int = 30) -> list[dict]:
    """
    从 sentiment_series.jsonl + broad_index.jsonl 计算情绪传导指标。

    返回行: {trading_day, sentiment_mean, sentiment_std, sentiment_consensus,
             cross_tom_divergence, extreme_ratio, sentiment_acf1,
             sentiment_return_corr}
    """
    sent_path = run_dir / "sentiment_series.jsonl"
    index_path = run_dir / "broad_index.jsonl"
    if not sent_path.exists():
        return []

    sent_rows = read_jsonl(sent_path)

    # 按天聚合情绪
    day_sentiments: dict[int, list[float]] = defaultdict(list)
    day_tom_sentiments: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    for r in sent_rows:
        day = safe_int(r.get("trading_day"))
        s = r.get("sentiment")
        tom = r.get("tom_level")
        if day is None or s is None:
            continue
        s = float(s)
        day_sentiments[day].append(s)
        if tom is not None:
            day_tom_sentiments[day][int(tom)].append(s)

    # 读取指数收益率序列
    day_return: dict[int, float] = {}
    if index_path.exists():
        for r in read_jsonl(index_path):
            day = safe_int(r.get("trading_day"))
            ret = r.get("pct_chg")
            if day is not None and ret is not None:
                day_return[day] = float(ret)

    sorted_days = sorted(day_sentiments.keys())
    if not sorted_days:
        return []

    # 构建每日平均情绪序列（用于 ACF 和 correlation）
    daily_mean_sent: dict[int, float] = {}
    for d in sorted_days:
        vals = day_sentiments[d]
        daily_mean_sent[d] = sum(vals) / len(vals)

    result = []
    for idx, day in enumerate(sorted_days):
        vals = day_sentiments[day]
        n = len(vals)
        mean_s = sum(vals) / n
        std_s = (sum((v - mean_s) ** 2 for v in vals) / max(1, n - 1)) ** 0.5

        # 跨 ToM 分歧度
        tom_means = []
        for tom, tom_vals in day_tom_sentiments[day].items():
            if tom_vals:
                tom_means.append(sum(tom_vals) / len(tom_vals))
        cross_div = None
        if len(tom_means) >= 2:
            tm_mean = sum(tom_means) / len(tom_means)
            cross_div = round((sum((m - tm_mean) ** 2 for m in tom_means) / (len(tom_means) - 1)) ** 0.5, 4)

        # 极端化率
        n_extreme = sum(1 for v in vals if abs(v) > 0.7)
        extreme_r = round(n_extreme / n * 100, 1)

        # 滚动窗口 ACF(lag1) 和 sentiment-return correlation
        acf1 = None
        sr_corr = None
        if idx >= window - 1:
            win_days = sorted_days[idx - window + 1: idx + 1]
            win_sent = [daily_mean_sent[d] for d in win_days]

            # ACF(lag1)
            if len(win_sent) >= 5:
                wm = sum(win_sent) / len(win_sent)
                c0 = sum((v - wm) ** 2 for v in win_sent)
                if c0 > 1e-15:
                    c1 = sum((win_sent[i] - wm) * (win_sent[i - 1] - wm) for i in range(1, len(win_sent)))
                    acf1 = round(c1 / c0, 4)

            # Sentiment-return correlation
            win_ret = [day_return.get(d) for d in win_days]
            if all(v is not None for v in win_ret):
                sr_corr_val = _pearson(win_sent, [v for v in win_ret if v is not None])
                if sr_corr_val is not None:
                    sr_corr = round(sr_corr_val, 4)

        row: dict = {
            "trading_day": day,
            "sentiment_mean": round(mean_s, 4),
            "sentiment_std": round(std_s, 4),
            "sentiment_consensus": round(1.0 - std_s, 4),
            "extreme_ratio": extreme_r,
        }
        if cross_div is not None:
            row["cross_tom_divergence"] = cross_div
        if acf1 is not None:
            row["sentiment_acf1"] = acf1
        if sr_corr is not None:
            row["sentiment_return_corr"] = sr_corr
        result.append(row)

    return result


# ──────────────────────────────────────────────────────────────
# 4. 社交-交易因果 (per day, per tom_level)
# ──────────────────────────────────────────────────────────────

def compute_social_trading_nexus(run_dir: Path) -> list[dict]:
    """
    从 info_cascade.jsonl 计算社交驱动交易指标。

    返回行: {trading_day, tom_level, social_trade_ratio, feed_conversion_rate,
             avg_perceived_posts, avg_engagement}
    """
    fpath = run_dir / "info_cascade.jsonl"
    if not fpath.exists():
        return []

    rows = read_jsonl(fpath)

    # 按 (day, tom) 聚合
    day_tom_data: dict[tuple[int, int], list[dict]] = defaultdict(list)

    for r in rows:
        day = safe_int(r.get("trading_day"))
        tom = r.get("tom_level")
        if day is None or tom is None:
            continue
        day_tom_data[(day, int(tom))].append(r)

    if not day_tom_data:
        return []

    result = []
    for (day, tom), entries in sorted(day_tom_data.items()):
        n = len(entries)

        # 社交驱动交易率: 感知 ≥1 帖 且 action=buy/sell 的比例
        with_posts = [e for e in entries if (e.get("perceived_post_count") or 0) > 0]
        if with_posts:
            traded_after_post = sum(
                1 for e in with_posts if e.get("agent_action") in ("buy", "sell")
            )
            social_trade_ratio = round(traded_after_post / len(with_posts) * 100, 1)
        else:
            social_trade_ratio = 0.0

        # 信息流转化率: 关注者帖子 ≥1 且 action=buy/sell
        with_following = [e for e in entries if (e.get("following_authors_in_feed") or 0) > 0]
        if with_following:
            traded_after_following = sum(
                1 for e in with_following if e.get("agent_action") in ("buy", "sell")
            )
            feed_conv_rate = round(traded_after_following / len(with_following) * 100, 1)
        else:
            feed_conv_rate = 0.0

        # 平均感知帖数
        avg_pp = round(
            sum(e.get("perceived_post_count", 0) for e in entries) / n, 2
        )
        # 平均互动感知量
        avg_eng = round(
            sum(e.get("total_engagement", 0) for e in entries) / n, 2
        )

        result.append({
            "trading_day": day,
            "tom_level": tom,
            "social_trade_ratio": social_trade_ratio,
            "feed_conversion_rate": feed_conv_rate,
            "avg_perceived_posts": avg_pp,
            "avg_engagement": avg_eng,
        })

    return result


# ──────────────────────────────────────────────────────────────
# 5. 声誉系统 (per day, market-level)
# ──────────────────────────────────────────────────────────────

def compute_reputation_system(run_dir: Path) -> list[dict]:
    """
    从 reputation_history.jsonl 计算每日声誉分布指标。

    返回行: {trading_day, avg_reputation, reputation_std, reputation_gini,
             high_rep_ratio, avg_accuracy, update_count}
    """
    rep_path = run_dir / "reputation_history.jsonl"
    if not rep_path.exists():
        return []

    rep_rows = read_jsonl(rep_path)
    if not rep_rows:
        return []

    # 按天分组，追踪每个 agent 的最新声望
    day_updates: dict[int, list[dict]] = defaultdict(list)
    for r in rep_rows:
        day = safe_int(r.get("trading_day"))
        if day is not None:
            day_updates[day].append(r)

    sorted_days = sorted(day_updates.keys())
    if not sorted_days:
        return []

    # 初始化所有 agent 为默认声望 0.5（与引擎 ReputationManager 默认值一致）
    all_agents: set[int] = set()
    for updates in day_updates.values():
        for r in updates:
            aid = r.get("agent_id")
            if aid is not None:
                all_agents.add(aid)
    agent_rep: dict[int, float] = {a: 0.5 for a in all_agents}
    agent_acc: dict[int, float] = {}

    result = []
    for day in sorted_days:
        updates = day_updates[day]
        for r in updates:
            aid = r.get("agent_id")
            if aid is not None:
                agent_rep[aid] = r.get("new_score", 0.0)
                if "recent_accuracy" in r:
                    agent_acc[aid] = r["recent_accuracy"]

        scores = list(agent_rep.values())
        n = len(scores)
        if n == 0:
            continue

        mean_r = sum(scores) / n
        std_r = (sum((s - mean_r) ** 2 for s in scores) / max(1, n - 1)) ** 0.5

        # Gini coefficient
        sorted_s = sorted(scores)
        cum = 0.0
        for i, s in enumerate(sorted_s):
            cum += (2 * (i + 1) - n - 1) * s
        gini = cum / (n * sum(sorted_s)) if sum(sorted_s) > 1e-15 else 0.0

        high_ratio = round(sum(1 for s in scores if s >= 0.7) / n * 100, 1)

        acc_vals = list(agent_acc.values())
        avg_acc = round(sum(acc_vals) / len(acc_vals), 4) if acc_vals else None

        row: dict = {
            "trading_day": day,
            "avg_reputation": round(mean_r, 4),
            "reputation_std": round(std_r, 4),
            "reputation_gini": round(gini, 4),
            "high_rep_ratio": high_ratio,
            "update_count": len(updates),
        }
        if avg_acc is not None:
            row["avg_accuracy"] = avg_acc
        result.append(row)

    return result


# ──────────────────────────────────────────────────────────────
# 6. KOL 市场冲击 (per day, market-level)
# ──────────────────────────────────────────────────────────────

def compute_kol_market_impact(
    run_dir: Path, kol_top_pct: float = 0.2
) -> list[dict]:
    """
    基于引擎实时记录的 kol_emerge/kol_lost 事件重建每日 KOL 集合，
    按 ToM 层级分组输出。

    返回行: {trading_day, tom_level, kol_count, kol_pct, kol_post_count,
             kol_sentiment_mean, kol_like_share}
    """
    graph_path = run_dir / "social_graph_events.jsonl"
    posts_path = run_dir / "posts.jsonl"
    sent_path = run_dir / "sentiment_series.jsonl"
    if not graph_path.exists():
        return []

    agent_tom = _build_agent_tom_map(run_dir)
    all_toms = sorted(set(agent_tom.values())) if agent_tom else [0]

    # ── 从 social_graph_events 重建 KOL 时间线 ──
    # kol_emerge/kol_lost 没有 trading_day，需从上下文推断
    sg_lines = read_jsonl(graph_path)
    # 第一遍：收集所有行的 trading_day 以便做线性扫描推断
    sg_days: list[int | None] = []
    for r in sg_lines:
        d = safe_int(r.get("trading_day"))
        sg_days.append(d)

    def _infer_day(idx: int) -> int | None:
        # 向前/向后找最近的 trading_day
        for offset in range(1, 50):
            for j in (idx - offset, idx + offset):
                if 0 <= j < len(sg_days) and sg_days[j] is not None:
                    return sg_days[j]
        return None

    # 构建 KOL 事件时间线: list[(day, agent_id, 'emerge'|'lost')]
    kol_events: list[tuple[int, int, str]] = []
    for i, r in enumerate(sg_lines):
        ev = r.get("event")
        if ev in ("kol_emerge", "kol_lost"):
            day = safe_int(r.get("trading_day")) or _infer_day(i)
            aid = r.get("agent_id")
            if day is not None and aid is not None:
                kol_events.append((day, aid, "emerge" if ev == "kol_emerge" else "lost"))

    # 按天排序
    kol_events.sort(key=lambda x: x[0])

    # ── 逐日获赞 ──
    day_like_targets: dict[int, list[int]] = defaultdict(list)
    for r in sg_lines:
        if r.get("event") == "like":
            target = r.get("target_agent_id")
            day = safe_int(r.get("trading_day"))
            if target is not None and day is not None:
                day_like_targets[day].append(target)

    # ── 帖数 ──
    day_post_map: dict[int, list[dict]] = defaultdict(list)
    if posts_path.exists():
        for p in read_jsonl(posts_path):
            day = safe_int(p.get("trading_day"))
            if day is not None and p.get("source") != "news":
                day_post_map[day].append(p)

    # ── 情绪 ──
    day_sent: dict[int, dict[int, float]] = defaultdict(dict)
    if sent_path.exists():
        for r in read_jsonl(sent_path):
            day = safe_int(r.get("trading_day"))
            s = r.get("sentiment")
            aid = r.get("agent_id")
            if day is not None and s is not None and aid is not None:
                day_sent[day][aid] = float(s)

    all_days = sorted(
        set(sg_days_clean := [d for d in sg_days if d is not None])
        | set(day_post_map)
        | set(day_sent)
    )
    if not all_days:
        return []

    # ── 逐日滚动 KOL 集合 ──
    kol_set: set[int] = set()
    ev_idx = 0
    result = []

    for day in all_days:
        # 应用截止当日的所有 KOL 事件
        while ev_idx < len(kol_events) and kol_events[ev_idx][0] <= day:
            _, aid, action = kol_events[ev_idx]
            if action == "emerge":
                kol_set.add(aid)
            else:
                kol_set.discard(aid)
            ev_idx += 1

        n_kol_total = len(kol_set)

        # 按 tom 分组
        kol_by_tom: dict[int, set[int]] = defaultdict(set)
        for a in kol_set:
            t = agent_tom.get(a, 0)
            kol_by_tom[t].add(a)

        # 当日获赞分布
        day_likes_count: dict[int, int] = defaultdict(int)
        for target in day_like_targets.get(day, []):
            day_likes_count[target] += 1
        total_day_likes = sum(day_likes_count.values())

        for tom in all_toms:
            tom_kols = kol_by_tom.get(tom, set())
            tom_kol_posts = sum(
                1 for p in day_post_map.get(day, [])
                if p.get("agent_id") in tom_kols
            )
            tom_kol_sents = [day_sent.get(day, {}).get(a) for a in tom_kols]
            tom_kol_sents = [s for s in tom_kol_sents if s is not None]
            tom_kol_likes = sum(day_likes_count.get(a, 0) for a in tom_kols)

            row: dict = {
                "trading_day": day,
                "tom_level": tom,
                "kol_count": len(tom_kols),
                "kol_pct": round(len(tom_kols) / n_kol_total * 100, 1) if n_kol_total else 0,
                "kol_post_count": tom_kol_posts,
            }
            if tom_kol_sents:
                row["kol_sentiment_mean"] = round(sum(tom_kol_sents) / len(tom_kol_sents), 4)
            if total_day_likes > 0:
                row["kol_like_share"] = round(tom_kol_likes / total_day_likes * 100, 1)
            result.append(row)

    return result


def compute_tool_usage(run_dir: Path) -> list[dict]:
    """
    返回行: {trading_day, tom_level, total_decisions, total_tool_calls,
             avg_tools_per_decision, cancel_orders_pct, social_action_pct,
             set_trade_plan_pct, social_post_pct, social_retweet_pct,
             social_like_pct}
    """
    fpath = run_dir / "decisions.jsonl"
    if not fpath.exists():
        return []

    rows = read_jsonl(fpath)

    # 按 (day, tom) 聚合
    DT = tuple[int, int]
    agg_decisions: dict[tuple[int, int], int] = defaultdict(int)
    agg_tools: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for r in rows:
        day = safe_int(r.get("trading_day"))
        tom = r.get("tom_level")
        if day is None or tom is None:
            continue
        tom = int(tom)
        key = (day, tom)
        agg_decisions[key] += 1

        ae = r.get("action_executed") or {}
        for t in ae.get("tool_trace", []):
            name = t.get("name", "")
            agg_tools[key][name] += 1
            # social_action 细分
            if name == "social_action":
                sub = (t.get("args") or {}).get("action_type", "unknown")
                agg_tools[key][f"social_{sub}"] += 1

    if not agg_decisions:
        return []

    result = []
    for (day, tom) in sorted(agg_decisions.keys()):
        key = (day, tom)
        n_dec = agg_decisions[key]
        tools = agg_tools[key]
        total_tc = sum(v for k, v in tools.items() if not k.startswith("social_"))
        # social_action 本身已计入 total，social_xxx 子项不重复计

        def pct(name: str) -> float:
            return round(tools.get(name, 0) / max(1, total_tc) * 100, 1)

        result.append({
            "trading_day": day,
            "tom_level": tom,
            "total_decisions": n_dec,
            "total_tool_calls": total_tc,
            "avg_tools_per_decision": round(total_tc / max(1, n_dec), 2),
            "cancel_orders_pct": pct("cancel_orders"),
            "social_action_pct": pct("social_action"),
            "set_trade_plan_pct": pct("set_trade_plan"),
            "social_post_pct": pct("social_post"),
            "social_retweet_pct": pct("social_retweet"),
            "social_like_pct": pct("social_like"),
        })

    return result
