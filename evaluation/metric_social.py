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

    result = []
    for day, tom in sorted(all_keys):
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
            "avg_likes_given": round(like_count / max(1, unique_likers), 2),
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

    # ── 统计每帖获赞数 ──
    post_likes: dict[int, int] = defaultdict(int)  # post_id -> like count
    if events_path.exists():
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
    识别 KOL（按累计获赞 top 20%），计算 KOL vs 非KOL 每日指标。

    返回行: {trading_day, kol_post_count, non_kol_post_count,
             kol_sentiment_mean, non_kol_sentiment_mean,
             kol_sentiment_lead, kol_like_share}
    """
    posts_path = run_dir / "posts.jsonl"
    graph_path = run_dir / "social_graph_events.jsonl"
    sent_path = run_dir / "sentiment_series.jsonl"
    if not posts_path.exists():
        return []

    posts = read_jsonl(posts_path)
    # ── 识别 KOL: 按累计获赞 top kol_top_pct ──
    likes_received: dict[int, int] = defaultdict(int)
    day_likes: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    if graph_path.exists():
        for r in read_jsonl(graph_path):
            if r.get("event") == "like":
                target = r.get("target_agent_id")
                day = safe_int(r.get("trading_day"))
                if target is not None:
                    likes_received[target] += 1
                    if day is not None:
                        day_likes[day][target] += 1

    # 加上发帖量作为辅助排序（likes 优先）
    posts_count: dict[int, int] = defaultdict(int)
    for p in posts:
        aid = p.get("agent_id")
        if aid is not None and p.get("source") != "news":
            posts_count[aid] += 1

    all_agents = set(likes_received.keys()) | set(posts_count.keys())
    if not all_agents:
        return []

    # 综合分: likes*10 + posts (likes 权重更大)
    agent_score = {a: likes_received.get(a, 0) * 10 + posts_count.get(a, 0) for a in all_agents}
    sorted_agents = sorted(agent_score.items(), key=lambda x: -x[1])
    n_kol = max(1, int(len(sorted_agents) * kol_top_pct))
    kol_set = {a for a, _ in sorted_agents[:n_kol]}

    # ── 每日帖数 ──
    day_posts_kol: dict[int, int] = defaultdict(int)
    day_posts_non: dict[int, int] = defaultdict(int)
    for p in posts:
        day = safe_int(p.get("trading_day"))
        aid = p.get("agent_id")
        if day is None or aid is None or p.get("source") == "news":
            continue
        if aid in kol_set:
            day_posts_kol[day] += 1
        else:
            day_posts_non[day] += 1

    # ── 每日情绪 ──
    day_kol_sent: dict[int, list[float]] = defaultdict(list)
    day_non_sent: dict[int, list[float]] = defaultdict(list)
    if sent_path.exists():
        for r in read_jsonl(sent_path):
            day = safe_int(r.get("trading_day"))
            s = r.get("sentiment")
            aid = r.get("agent_id")
            if day is None or s is None or aid is None:
                continue
            s = float(s)
            if aid in kol_set:
                day_kol_sent[day].append(s)
            else:
                day_non_sent[day].append(s)

    all_days = sorted(
        set(day_posts_kol) | set(day_posts_non)
        | set(day_kol_sent) | set(day_non_sent)
    )
    if not all_days:
        return []

    result = []
    for day in all_days:
        kol_s = day_kol_sent.get(day, [])
        non_s = day_non_sent.get(day, [])
        kol_mean = round(sum(kol_s) / len(kol_s), 4) if kol_s else None
        non_mean = round(sum(non_s) / len(non_s), 4) if non_s else None

        # KOL 获赞占比
        total_day_likes = sum(day_likes.get(day, {}).values())
        kol_day_likes = sum(day_likes.get(day, {}).get(a, 0) for a in kol_set)
        kol_like_share = (
            round(kol_day_likes / total_day_likes * 100, 1)
            if total_day_likes > 0 else None
        )

        row: dict = {
            "trading_day": day,
            "kol_post_count": day_posts_kol.get(day, 0),
            "non_kol_post_count": day_posts_non.get(day, 0),
        }
        if kol_mean is not None:
            row["kol_sentiment_mean"] = kol_mean
        if non_mean is not None:
            row["non_kol_sentiment_mean"] = non_mean
        if kol_mean is not None and non_mean is not None:
            row["kol_sentiment_lead"] = round(kol_mean - non_mean, 4)
        if kol_like_share is not None:
            row["kol_like_share"] = kol_like_share
        result.append(row)

    return result


# ──────────────────────────────────────────────────────────────
# 7. 工具调用分布 (per day, per tom_level)
# ──────────────────────────────────────────────────────────────

def compute_tool_usage(run_dir: Path) -> list[dict]:
    """
    从 decisions.jsonl 的 action_executed.tool_trace 计算每日工具调用比例。

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
