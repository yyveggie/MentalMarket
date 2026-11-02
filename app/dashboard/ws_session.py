"""看板 WebSocket 会话：按工作区订阅主题，并对大数组做差量推送。

协议（客户端 → 服务端）：
  {"type": "subscribe", "topics": ["market", "agents"], "reset": false}
  {"type": "resync"}                      # 客户端发现差量锚点对不上时请求全量

协议（服务端 → 客户端，每个推送周期一条）：
  {"type": "state", "data": {...}}
  data 始终含核心字段（sim_time / trading_day / metrics / index_snapshot / topics），
  首条附带静态字段（trading_day_seconds / sim_start_date / real_* 等），
  其余按订阅主题给出；追加型序列用 `<key>_delta`，持仓用 `holdings` 全量或 `holdings_delta`。

序列差量格式：
  {"full": rows, "limit": n}                                  # 全量（首次或锚点丢失）
  {"anchor": id, "rows": rows, "limit": n}                    # 在锚点之后追加
  {"anchor": id, "replace_last": true, "rows": rows, "limit": n}  # 用 rows 替换锚点行及其后（末根 bar 可变）
"""
from __future__ import annotations

import json
from typing import Any

TOPICS: tuple[str, ...] = ("market", "agents", "social", "research")

CORE_KEYS: tuple[str, ...] = ("server_time", "sim_time", "trading_day", "metrics", "index_snapshot", "session")
STATIC_KEYS: tuple[str, ...] = (
    "trading_day_seconds", "intraday_bar_seconds", "sim_start_date", "real_index_series", "real_curve_calendar",
)
TOPIC_KEYS: dict[str, tuple[str, ...]] = {
    "market": (
        "index_series", "broad_index_series", "daily_bars", "intraday_bars", "technical_indicators",
        "price_trend", "deviation_trend", "cda_by_symbol", "market_micro", "leaderboard",
    ),
    "agents": ("active", "holdings", "tom_summary", "mm_subsidy"),
    "social": ("social_hot", "social_latest", "social_news", "social_graph"),
    "research": (
        "sentiment_trend", "confidence_trend", "deviation_trend", "bias_stats", "bias_trends",
        "cascade_stats", "liquidity_stats", "plan_stats", "tom_summary", "mm_subsidy",
    ),
}

# 追加型序列：键 → 行标识字段
SERIES_IDENT: dict[str, str] = {
    "index_series": "date",
    "broad_index_series": "date",
    "daily_bars": "time",
    "intraday_bars": "t",
    "price_trend": "t",
    "sentiment_trend": "t",
    "confidence_trend": "t",
    "deviation_trend": "t",
    "bias_trends": "day",
}
SERIES_DICT_KEYS: frozenset[str] = frozenset({"index_series", "daily_bars", "intraday_bars", "price_trend"})
# 末行可变（进行中的 bar）：差量时把锚点行一起重发
SERIES_RESEND_LAST: frozenset[str] = frozenset({"daily_bars", "intraday_bars", "index_series", "broad_index_series"})
SERIES_LIMIT: dict[str, int] = {
    "intraday_bars": 600, "price_trend": 600, "sentiment_trend": 600, "confidence_trend": 600,
    "deviation_trend": 600, "bias_trends": 200,
}
# 只随重量级缓存（约 5 秒一次）变化的字段：版本不变就不重发
HEAVY_KEYS: frozenset[str] = frozenset({"tom_summary", "social_hot", "social_latest", "social_news", "social_graph", "leaderboard"})
ACTIVE_FULL_INTERVAL = 30.0
CDA_TAPE_ROWS = 12


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class WsSession:
    def __init__(self) -> None:
        self.topics: set[str] = set(TOPICS)
        self.static_sent = False
        # 序列键（或 "键|标的"）→ (上次发送的末行标识, 上次发送的末行 JSON)
        self.series_state: dict[str, tuple[Any, str]] = {}
        self.holdings_fp: dict[int, str] | None = None
        self.heavy_version: float | None = None
        self.active_full_at: float = 0.0

    def reset(self) -> None:
        self.static_sent = False
        self.series_state.clear()
        self.holdings_fp = None
        self.heavy_version = None
        self.active_full_at = 0.0

    def set_topics(self, topics: list[str] | None, reset: bool = False) -> None:
        new = {str(t) for t in (topics or []) if str(t) in TOPICS}
        if not new:
            new = set(TOPICS)
        added = new - self.topics
        self.topics = new
        if reset:
            self.reset()
            return
        # 新订阅的主题没有基线，清掉相关差量状态，下一次推送发全量
        for topic in added:
            for key in TOPIC_KEYS[topic]:
                for skey in [k for k in self.series_state if k == key or k.startswith(key + "|")]:
                    self.series_state.pop(skey, None)
            if topic == "agents":
                self.holdings_fp = None
                self.active_full_at = 0.0
        if added & {"agents", "social", "market", "research"}:
            self.heavy_version = None


def series_delta(session: WsSession, skey: str, rows: list[dict], ident: str, resend_last: bool, limit: int | None) -> dict | None:
    prev = session.series_state.get(skey)
    if not rows:
        if prev is None or prev[0] is None:
            return None
        session.series_state[skey] = (None, "")
        return {"full": [], "limit": limit}
    last_row = rows[-1]
    last_id = last_row.get(ident)
    last_json = _dumps(last_row)
    if prev is None or prev[0] is None:
        session.series_state[skey] = (last_id, last_json)
        return {"full": rows, "limit": limit}
    prev_id, prev_json = prev
    j = -1
    for i in range(len(rows) - 1, -1, -1):
        if rows[i].get(ident) == prev_id:
            j = i
            break
    if j < 0:
        session.series_state[skey] = (last_id, last_json)
        return {"full": rows, "limit": limit}
    new_rows = rows[j + 1:]
    if resend_last:
        anchor_changed = _dumps(rows[j]) != prev_json
        if not new_rows and not anchor_changed:
            return None
        session.series_state[skey] = (last_id, last_json)
        return {"anchor": prev_id, "replace_last": True, "rows": rows[j:], "limit": limit}
    if not new_rows:
        return None
    session.series_state[skey] = (last_id, last_json)
    return {"anchor": prev_id, "rows": new_rows, "limit": limit}


def holdings_fingerprints(holdings: list[dict]) -> dict[int, str]:
    return {int(h["agent_id"]): _dumps(h) for h in holdings}


def _holdings_payload(session: WsSession, holdings: list[dict], fps: dict[int, str], heavy_changed: bool) -> tuple[str, Any] | None:
    if session.holdings_fp is None:
        session.holdings_fp = fps
        return "holdings", holdings
    if not heavy_changed:
        return None
    prev = session.holdings_fp
    upsert = [h for h in holdings if prev.get(int(h["agent_id"])) != fps[int(h["agent_id"])]]
    remove = [aid for aid in prev if aid not in fps]
    session.holdings_fp = fps
    if not upsert and not remove:
        return None
    return "holdings_delta", {"upsert": upsert, "remove": remove}


def build_payload(session: WsSession, state: dict, heavy_version: float, now_ts: float) -> dict:
    """从一份全量 state 派生某个客户端的推送内容。"""
    out: dict[str, Any] = {k: state[k] for k in CORE_KEYS if k in state}
    out["topics"] = sorted(session.topics)
    if not session.static_sent:
        for k in STATIC_KEYS:
            if k in state:
                out[k] = state[k]
        session.static_sent = True

    keys: set[str] = set()
    for topic in session.topics:
        keys.update(TOPIC_KEYS.get(topic, ()))
    heavy_changed = session.heavy_version != heavy_version

    for key in sorted(keys):
        if key not in state:
            continue
        val = state[key]
        if key == "holdings":
            fps = state.get("_holdings_fp") or holdings_fingerprints(val)
            item = _holdings_payload(session, val, fps, heavy_changed)
            if item is not None:
                out[item[0]] = item[1]
        elif key == "active":
            active = dict(val)
            if now_ts - session.active_full_at >= ACTIVE_FULL_INTERVAL:
                session.active_full_at = now_ts
            else:
                active.pop("recent_decisions", None)
                active.pop("recent_tools", None)
            out["active"] = active
        elif key == "cda_by_symbol":
            # 逐单归属看板不用；成交明细只显示最近几笔（逐笔成交另有事件流实时更新）
            slim: dict[str, dict] = {}
            for symbol, cda in (val or {}).items():
                slim[symbol] = {
                    "last_price": cda.get("last_price"),
                    "spread": cda.get("spread"),
                    "phase": cda.get("phase"),
                    "call_auction": cda.get("call_auction"),
                    "last_auction": cda.get("last_auction"),
                    "limit_up": cda.get("limit_up"),
                    "limit_down": cda.get("limit_down"),
                    "bids": cda.get("bids", []),
                    "asks": cda.get("asks", []),
                    "bids_attribution": [],
                    "asks_attribution": [],
                    "recent_trades": list(cda.get("recent_trades", []))[-CDA_TAPE_ROWS:],
                }
            out[key] = slim
        elif key in HEAVY_KEYS:
            if heavy_changed or session.heavy_version is None:
                out[key] = val
        elif key in SERIES_IDENT:
            ident = SERIES_IDENT[key]
            resend = key in SERIES_RESEND_LAST
            limit = SERIES_LIMIT.get(key)
            if key in SERIES_DICT_KEYS:
                deltas: dict[str, dict] = {}
                for symbol, rows in (val or {}).items():
                    d = series_delta(session, f"{key}|{symbol}", list(rows), ident, resend, limit)
                    if d is not None:
                        deltas[symbol] = d
                if deltas:
                    out[f"{key}_delta"] = deltas
            else:
                d = series_delta(session, key, list(val or []), ident, resend, limit)
                if d is not None:
                    out[f"{key}_delta"] = d
        else:
            out[key] = val

    session.heavy_version = heavy_version
    return out
