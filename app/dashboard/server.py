from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from aiohttp import web

_logger = logging.getLogger(__name__)

from app.utils.indicators import ema as _ema, momentum as _momentum, rsi as _rsi, sma as _sma, volatility as _volatility, round_or_none as _round_or_none, compute_trading_day as _compute_td


def _extract_reasoning(llm_out: dict, tom_level: int) -> str:
    if tom_level <= 0:
        return ""
    if tom_level == 2:
        t1r = str(llm_out.get("tom1_reasoning", ""))
        t2r = str(llm_out.get("tom2_reasoning", ""))
        if t1r or t2r:
            parts = []
            if t1r:
                parts.append(f"[一阶]{t1r}")
            if t2r:
                parts.append(f"[二阶]{t2r}")
            return " ".join(parts)
    return str(llm_out.get("mental_reasoning", ""))


class RealtimeDashboard:
    """In-process realtime dashboard server for simulation observability."""

    def __init__(
        self,
        agent_manager,
        orderbook,
        index_board,
        data_logger,
        host: str = "127.0.0.1",
        port: int = 8765,
        l2_depth: int = 10,
        l2_quote_orders: int = 6,
        index_lookback: int = 300,
        trading_day_seconds: float = 60.0,
        max_recent_events: int = 200,
        dashboard_config: dict | None = None,
    ):
        self.agent_manager = agent_manager
        if isinstance(orderbook, dict):
            self.orderbooks = {str(k).upper(): v for k, v in orderbook.items()}
        else:
            default_symbol = str(getattr(agent_manager, "_symbol", "MentalMarket")).upper()
            self.orderbooks = {default_symbol: orderbook}
        self.default_symbol = str(getattr(agent_manager, "_symbol", "MentalMarket")).upper()
        if self.default_symbol not in self.orderbooks:
            raise ValueError(f"dashboard default_symbol not found in orderbooks: {self.default_symbol}")
        self.orderbook = self.orderbooks[self.default_symbol]
        self.index_board = index_board
        self.data_logger = data_logger
        self.host = host
        self.port = int(port)
        self.l2_depth = max(1, int(l2_depth))
        self.l2_quote_orders = int(l2_quote_orders)
        self.index_lookback = max(20, int(index_lookback))
        self.trading_day_seconds = max(1e-6, float(trading_day_seconds))

        dcfg = dashboard_config or {}
        price_trend_maxlen = int(dcfg.get("price_trend_maxlen", 600))
        sentiment_trend_maxlen = int(dcfg.get("sentiment_trend_maxlen", 600))
        deviation_trend_maxlen = int(dcfg.get("deviation_trend_maxlen", 600))

        self.recent_decisions: deque[dict] = deque(maxlen=max_recent_events)
        self.recent_tools: deque[dict] = deque(maxlen=max_recent_events)
        self.recent_trades: deque[dict] = deque(maxlen=max_recent_events)
        self.thinking_agents: dict[int, dict] = {}
        self.scheduled_agents: dict[int, dict] = {}
        self._latest_sim_time: float = 0.0
        self._price_trend: dict[str, deque] = {}
        self._price_trend_maxlen = price_trend_maxlen
        self._sentiment_trend: deque = deque(maxlen=sentiment_trend_maxlen)
        self._deviation_trend: deque = deque(maxlen=deviation_trend_maxlen)
        sentiment_window = int(dcfg.get("sentiment_window", 500))
        self._recent_sentiments: deque[float] = deque(maxlen=sentiment_window)
        self._recent_confidences: deque[float] = deque(maxlen=sentiment_window)
        self._confidence_trend: deque = deque(maxlen=sentiment_trend_maxlen)

        self._bias_counters: dict = {"sell_gain": 0, "sell_loss": 0, "herding": 0, "contrarian": 0, "overconfident": 0, "total": 0,
            "loss_hold": 0, "loss_sell": 0, "loss_buy": 0, "gain_hold": 0, "gain_sell": 0, "gain_buy": 0,
            "disposition_effect": 0, "lottery_preference": 0, "underdiversified": 0, "loss_aversion": 0,
            "averaging_down": 0, "herding_peer": 0}
        _lg_keys = ("loss_hold", "loss_sell", "loss_buy", "gain_hold", "gain_sell", "gain_buy")
        self._loss_gain_by_tom: dict[int, dict[str, int]] = {
            t: {k: 0 for k in _lg_keys} for t in (0, 1, 2)
        }

        _bias_keys = ("disposition", "overconfidence", "underdiversified", "lottery", "herding")
        self._bias_tom_day: dict[int, dict[str, int]] = {
            t: {k: 0 for k in ("total", *_bias_keys)} for t in (0, 1, 2)
        }
        self._bias_tom_current_day: int = 0
        self._bias_trend: deque = deque(maxlen=200)

        self._agent_sentiment_window: dict[int, deque] = {}
        self._cascade_counters: dict = {"total": 0, "has_news": 0, "total_perceived": 0, "following_authors": 0}
        _cascade_tom_init = lambda: {"total": 0, "has_news": 0, "total_perceived": 0, "following_authors": 0}
        self._cascade_by_tom: dict[int, dict[str, int]] = {t: _cascade_tom_init() for t in (0, 1, 2)}
        self._liquidity_counters: dict = {0: {"maker": 0, "taker": 0}, 1: {"maker": 0, "taker": 0}, 2: {"maker": 0, "taker": 0}}
        self._plan_counters: dict = {"total": 0, "adhered": 0, "deviated": 0}
        _plan_tom_init = lambda: {"total": 0, "adhered": 0, "deviated": 0}
        self._plan_by_tom: dict[int, dict[str, int]] = {t: _plan_tom_init() for t in (0, 1, 2)}

        self._ws_clients: set[web.WebSocketResponse] = set()
        self._push_task: asyncio.Task | None = None
        self._ws_push_interval: float = float(dcfg.get("ws_push_interval", 1.0))
        self._ws_heartbeat: float = float(dcfg.get("ws_heartbeat", 20.0))
        self._ws_event_queue: asyncio.Queue = asyncio.Queue(maxsize=int(dcfg.get("ws_event_queue_size", 2000)))

        self._fundamental_ref_prices: dict[str, float] = {
            str(symbol).upper(): float(ob.limit_reference_price)
            for symbol, ob in self.orderbooks.items()
        }

        self._social_graph_top_n: int = int(dcfg.get("social_graph_top_n", 30))

        self._heavy_cache: dict = {}
        self._heavy_cache_time: float = 0.0
        self._heavy_cache_interval: float = 5.0

        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._started = False

        static_dir = Path(__file__).resolve().parent / "static"
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/api/state", self._handle_state)
        if static_dir.exists():
            self._app.router.add_static("/static", str(static_dir), show_index=False)
            assets_dir = static_dir / "assets"
            if assets_dir.exists():
                self._app.router.add_static("/assets", str(assets_dir), show_index=False)

    async def start(self) -> None:
        if self._started:
            return
        self.data_logger.add_listener(self.on_log_event)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        self._started = True
        self._push_task = asyncio.ensure_future(self._ws_push_loop())

    async def stop(self) -> None:
        if not self._started:
            return
        if self._push_task is not None:
            self._push_task.cancel()
            self._push_task = None
        for ws in list(self._ws_clients):
            await ws.close()
        self._ws_clients.clear()
        self.data_logger.remove_listener(self.on_log_event)
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._started = False

    def replay_historical_records(self, run_dir: Path) -> None:
        """从 JSONL 文件回放历史记录，恢复 Dashboard 内存状态。

        全量回放（累加计数器）的文件:
            behavioral_biases, sentiment_series, info_cascade,
            liquidity_provision, plan_execution
        尾部回放（仅填充最近 N 条展示队列）的文件:
            trades, decisions
        趋势重建:
            market_snapshots → price_trend, deviation_trend
            sentiment_series → sentiment_trend, confidence_trend
        """
        full_replay = [
            "behavioral_biases",
            "info_cascade",
            "liquidity_provision",
            "plan_execution",
        ]
        total = 0
        for name in full_replay:
            jsonl_path = run_dir / f"{name}.jsonl"
            if not jsonl_path.exists():
                continue
            count = 0
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._replay_record(name, record)
                    count += 1
            total += count
            _logger.info("Dashboard replay: %s → %d records", name, count)
        if self._bias_tom_current_day > 0:
            self._snapshot_bias_trend(self._bias_tom_current_day)

        total += self._replay_sentiment_with_trends(run_dir)
        total += self._replay_market_snapshot_trends(run_dir)

        tail_replay = [
            ("trades", self.recent_trades.maxlen),
            ("decisions", self.recent_decisions.maxlen),
        ]
        for name, keep in tail_replay:
            jsonl_path = run_dir / f"{name}.jsonl"
            if not jsonl_path.exists():
                continue
            tail_lines = self._read_tail_lines(jsonl_path, keep)
            count = 0
            for line in tail_lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._replay_record(name, record)
                count += 1
            total += count
            _logger.info("Dashboard replay: %s → %d records (tail %d)", name, count, keep)
        _logger.info("Dashboard replay complete: %d total records from %s", total, run_dir)

    def _replay_sentiment_with_trends(self, run_dir: Path) -> int:
        """回放 sentiment_series 并重建 sentiment_trend / confidence_trend 时序。"""
        jsonl_path = run_dir / "sentiment_series.jsonl"
        if not jsonl_path.exists():
            return 0

        count = 0
        last_day = -1
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._replay_record("sentiment_series", record)
                count += 1

                day = int(record.get("trading_day", 0))
                sim_t = float(record.get("sim_time", 0.0) or 0.0)
                if day > last_day and last_day >= 0 and self._recent_sentiments:
                    t_rounded = round(sim_t, 1)
                    avg_sent = round(sum(self._recent_sentiments) / len(self._recent_sentiments), 4)
                    self._sentiment_trend.append({"t": t_rounded, "s": avg_sent})
                    avg_conf = 0.5
                    if self._recent_confidences:
                        avg_conf = round(sum(self._recent_confidences) / len(self._recent_confidences), 4)
                    self._confidence_trend.append({"t": t_rounded, "c": avg_conf})
                last_day = day

        if self._recent_sentiments and last_day >= 0:
            latest_t = round(last_day * self.trading_day_seconds, 1)
            if not self._sentiment_trend or self._sentiment_trend[-1]["t"] != latest_t:
                avg_sent = round(sum(self._recent_sentiments) / len(self._recent_sentiments), 4)
                self._sentiment_trend.append({"t": latest_t, "s": avg_sent})
            if not self._confidence_trend or self._confidence_trend[-1]["t"] != latest_t:
                avg_conf = round(sum(self._recent_confidences) / len(self._recent_confidences), 4) if self._recent_confidences else 0.5
                self._confidence_trend.append({"t": latest_t, "c": avg_conf})

        _logger.info("Dashboard replay: sentiment_series → %d records, trend points: sent=%d conf=%d",
                      count, len(self._sentiment_trend), len(self._confidence_trend))
        return count

    def _replay_market_snapshot_trends(self, run_dir: Path) -> int:
        """从 market_snapshots 重建 price_trend 和 deviation_trend。"""
        jsonl_path = run_dir / "market_snapshots.jsonl"
        if not jsonl_path.exists():
            return 0

        count = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                count += 1
                sim_t = float(record.get("sim_time", 0.0) or 0.0)
                t_rounded = round(sim_t, 1)
                symbol = str(record.get("symbol", "")).upper()
                last_price = record.get("last_price")

                if symbol and last_price is not None:
                    if symbol not in self._price_trend:
                        self._price_trend[symbol] = deque(maxlen=self._price_trend_maxlen)
                    series = self._price_trend[symbol]
                    if not series or series[-1]["t"] != t_rounded:
                        series.append({"t": t_rounded, "p": round(float(last_price), 4)})

                if symbol == self.default_symbol and last_price is not None:
                    dev_pct = record.get("price_deviation_pct")
                    if dev_pct is not None:
                        if not self._deviation_trend or self._deviation_trend[-1]["t"] != t_rounded:
                            self._deviation_trend.append({"t": t_rounded, "d": round(float(dev_pct), 4)})

        _logger.info("Dashboard replay: market_snapshots → %d records, price_trend symbols=%d, deviation=%d",
                      count, len(self._price_trend), len(self._deviation_trend))
        return count

    @staticmethod
    def _read_tail_lines(filepath: Path, n: int) -> list[str]:
        """从文件末尾读取最多 n 行非空行，避免全量扫描大文件。"""
        import os
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return []
        avg_line_estimate = 2048
        chunk_size = min(file_size, n * avg_line_estimate)
        lines: list[str] = []
        with open(filepath, "rb") as f:
            while len(lines) < n and chunk_size <= file_size:
                f.seek(max(0, file_size - chunk_size))
                raw = f.read()
                lines = [l for l in raw.decode("utf-8", errors="replace").splitlines() if l.strip()]
                chunk_size *= 2
        return lines[-n:]

    def _replay_record(self, name: str, record: dict) -> None:
        """回放单条历史记录，仅更新计数器，不推送 WebSocket。"""
        if name == "sentiment_series":
            sent_val = float(record.get("sentiment", 0.0) or 0.0)
            self._recent_sentiments.append(sent_val)
            conf_val = float(record.get("confidence", 0.5) or 0.5)
            self._recent_confidences.append(conf_val)
            aid = int(record.get("agent_id", 0))
            if aid > 0:
                if aid not in self._agent_sentiment_window:
                    self._agent_sentiment_window[aid] = deque(maxlen=10)
                self._agent_sentiment_window[aid].append(sent_val)

        elif name == "behavioral_biases":
            self._bias_counters["total"] += 1
            if record.get("sell_gain_pct") is not None:
                self._bias_counters["sell_gain"] += 1
            elif record.get("action") == "sell" and record.get("status") == "ok":
                self._bias_counters["sell_loss"] += 1
            if record.get("disposition_effect_flag"):
                self._bias_counters["disposition_effect"] += 1
            mc = record.get("momentum_or_contrarian")
            if mc == "momentum":
                self._bias_counters["herding"] += 1
            elif mc == "contrarian":
                self._bias_counters["contrarian"] += 1
            if record.get("overconfidence_flag"):
                self._bias_counters["overconfident"] += 1
            if record.get("lottery_preference_flag"):
                self._bias_counters["lottery_preference"] += 1
            if record.get("underdiversification_flag"):
                self._bias_counters["underdiversified"] += 1
            if record.get("loss_aversion_flag"):
                self._bias_counters["loss_aversion"] += 1
            if record.get("averaging_down_flag"):
                self._bias_counters["averaging_down"] += 1
            if record.get("herding_flag"):
                self._bias_counters["herding_peer"] += 1
            pnl_dir = record.get("prior_pnl_direction", "neutral")
            action = record.get("action", "hold")
            if pnl_dir == "loss":
                self._bias_counters[f"loss_{action}"] = self._bias_counters.get(f"loss_{action}", 0) + 1
            elif pnl_dir == "gain":
                self._bias_counters[f"gain_{action}"] = self._bias_counters.get(f"gain_{action}", 0) + 1

            tom = int(record.get("tom_level", 0))
            if tom not in self._bias_tom_day:
                tom = 0

            lg_tom = self._loss_gain_by_tom.get(tom)
            if lg_tom is not None and pnl_dir in ("loss", "gain"):
                key = f"{pnl_dir}_{action}"
                if key in lg_tom:
                    lg_tom[key] += 1

            day = int(record.get("trading_day", 0))
            if day > self._bias_tom_current_day and self._bias_tom_current_day > 0:
                self._snapshot_bias_trend(self._bias_tom_current_day)
            self._bias_tom_current_day = max(self._bias_tom_current_day, day)
            td = self._bias_tom_day[tom]
            td["total"] += 1
            if record.get("disposition_effect_flag"):
                td["disposition"] += 1
            if record.get("overconfidence_flag"):
                td["overconfidence"] += 1
            if record.get("underdiversification_flag"):
                td["underdiversified"] += 1
            if record.get("lottery_preference_flag"):
                td["lottery"] += 1
            if record.get("herding_flag"):
                td["herding"] += 1

        elif name == "info_cascade":
            self._cascade_counters["total"] += 1
            if record.get("has_news"):
                self._cascade_counters["has_news"] += 1
            perceived = int(record.get("perceived_post_count", 0))
            following = int(record.get("following_authors_in_feed", 0))
            self._cascade_counters["total_perceived"] += perceived
            self._cascade_counters["following_authors"] += following
            ct = self._cascade_by_tom.get(int(record.get("tom_level", 0)))
            if ct is not None:
                ct["total"] += 1
                if record.get("has_news"):
                    ct["has_news"] += 1
                ct["total_perceived"] += perceived
                ct["following_authors"] += following

        elif name == "liquidity_provision":
            maker_tom = int(record.get("maker_tom_level", -1))
            taker_tom = int(record.get("taker_tom_level", -1))
            if maker_tom in self._liquidity_counters:
                self._liquidity_counters[maker_tom]["maker"] += 1
            if taker_tom in self._liquidity_counters:
                self._liquidity_counters[taker_tom]["taker"] += 1

        elif name == "plan_execution":
            self._plan_counters["total"] += 1
            adherence = record.get("adherence")
            if adherence is True:
                self._plan_counters["adhered"] += 1
            elif adherence is False:
                self._plan_counters["deviated"] += 1
            pt = self._plan_by_tom.get(int(record.get("tom_level", 0)))
            if pt is not None:
                pt["total"] += 1
                if adherence is True:
                    pt["adhered"] += 1
                elif adherence is False:
                    pt["deviated"] += 1

        elif name == "decisions":
            sim_t = float(record.get("sim_time", 0.0) or 0.0)
            self._latest_sim_time = max(self._latest_sim_time, sim_t)
            tom_level = int(record.get("tom_level", 0) or 0)
            llm_out = record.get("llm_output", {}) or {}
            self.recent_decisions.append({
                "decision_id": record.get("decision_id"),
                "sim_time": sim_t,
                "agent_id": record.get("agent_id"),
                "tom_level": tom_level,
                "reasoning": _extract_reasoning(llm_out, tom_level),
                "action": str(llm_out.get("action", "hold")),
                "tool_trace": (record.get("action_executed", {}) or {}).get("tool_trace", []),
                "action_executed": record.get("action_executed", {}),
            })
            tools = (record.get("action_executed", {}) or {}).get("tool_trace", [])
            for t in tools:
                self.recent_tools.append({
                    "sim_time": record.get("sim_time"),
                    "agent_id": record.get("agent_id"),
                    "name": t.get("name", ""),
                    "args": t.get("args", {}),
                    "result": t.get("result", {}),
                })

        elif name == "trades":
            self._latest_sim_time = max(self._latest_sim_time, float(record.get("sim_time", 0.0) or 0.0))
            self.recent_trades.append(record)

    def on_agent_thinking_start(self, agent_id: int, payload: dict) -> None:
        self._latest_sim_time = max(self._latest_sim_time, float(payload.get("sim_time", 0.0)))
        self.thinking_agents[int(agent_id)] = {
            "agent_id": int(agent_id),
            "phase": "thinking",
            **payload,
        }

    def on_agent_thinking_end(self, agent_id: int, payload: dict) -> None:
        aid = int(agent_id)
        self.thinking_agents.pop(aid, None)
        if payload.get("status") == "ok":
            self.scheduled_agents[aid] = {
                "agent_id": aid,
                "phase": "decided",
                "sim_time": float(payload.get("result", {}).get("execute_time", 0.0)),
            }

    def on_agent_order_scheduled(self, agent_id: int, payload: dict) -> None:
        self._latest_sim_time = max(self._latest_sim_time, float(payload.get("execute_time", 0.0)))
        aid = int(agent_id)
        self.scheduled_agents[aid] = {
            "agent_id": aid,
            "phase": "scheduled",
            "perceived_time": float(payload.get("perceived_time", 0.0)),
            "decision_time": float(payload.get("decision_time", 0.0)),
            "execute_time": float(payload.get("execute_time", 0.0)),
            "report_time": float(payload.get("report_time", 0.0)),
        }

    def on_log_event(self, name: str, record: dict) -> None:
        if name == "decisions":
            sim_t = float(record.get("sim_time", 0.0) or 0.0)
            self._latest_sim_time = max(self._latest_sim_time, sim_t)
            tom_level = int(record.get("tom_level", 0) or 0)
            llm_out = record.get("llm_output", {}) or {}
            self.recent_decisions.append(
                {
                    "decision_id": record.get("decision_id"),
                    "sim_time": sim_t,
                    "agent_id": record.get("agent_id"),
                    "tom_level": tom_level,
                    "reasoning": _extract_reasoning(llm_out, tom_level),
                    "action": str(llm_out.get("action", "hold")),
                    "tool_trace": (record.get("action_executed", {}) or {}).get("tool_trace", []),
                    "action_executed": record.get("action_executed", {}),
                }
            )
            tools = (record.get("action_executed", {}) or {}).get("tool_trace", [])
            for t in tools:
                self.recent_tools.append(
                    {
                        "sim_time": record.get("sim_time"),
                        "agent_id": record.get("agent_id"),
                        "name": t.get("name", ""),
                        "args": t.get("args", {}),
                        "result": t.get("result", {}),
                    }
                )
            aid = int(record.get("agent_id", 0))
            if aid in self.scheduled_agents:
                self.scheduled_agents.pop(aid, None)

            if self._ws_clients:
                action_exec = record.get("action_executed", {}) or {}
                try:
                    raw_trace = action_exec.get("tool_trace", [])
                    compact_trace = [
                        {"name": t.get("name", ""), "args": t.get("args", {}), "result": t.get("result", {})}
                        for t in (raw_trace or [])
                    ]
                    self._ws_event_queue.put_nowait({
                        "type": "event_decision",
                        "data": {
                            "sim_time": sim_t,
                            "agent_id": int(record.get("agent_id", 0) or 0),
                            "tom_level": tom_level,
                            "action": str((record.get("llm_output", {}) or {}).get("action", "hold")),
                            "symbol": str(action_exec.get("symbol", "")),
                            "decision_scope": str(action_exec.get("decision_scope", "symbol")),
                            "status": str(action_exec.get("status", "")),
                            "price": float(action_exec.get("price", 0) or 0),
                            "quantity": int(action_exec.get("quantity", 0) or 0),
                            "tool_trace": compact_trace,
                            "reasoning": _extract_reasoning(llm_out, tom_level),
                        },
                    })
                except asyncio.QueueFull:
                    pass

        elif name == "sentiment_series":
            sent_val = float(record.get("sentiment", 0.0) or 0.0)
            self._recent_sentiments.append(sent_val)
            conf_val = float(record.get("confidence", 0.5) or 0.5)
            self._recent_confidences.append(conf_val)
            aid = int(record.get("agent_id", 0))
            if aid > 0:
                if aid not in self._agent_sentiment_window:
                    self._agent_sentiment_window[aid] = deque(maxlen=10)
                self._agent_sentiment_window[aid].append(sent_val)

        elif name == "behavioral_biases":
            self._bias_counters["total"] += 1
            if record.get("sell_gain_pct") is not None:
                self._bias_counters["sell_gain"] += 1
            elif record.get("action") == "sell" and record.get("status") == "ok":
                self._bias_counters["sell_loss"] += 1
            if record.get("disposition_effect_flag"):
                self._bias_counters["disposition_effect"] += 1
            mc = record.get("momentum_or_contrarian")
            if mc == "momentum":
                self._bias_counters["herding"] += 1
            elif mc == "contrarian":
                self._bias_counters["contrarian"] += 1
            if record.get("overconfidence_flag"):
                self._bias_counters["overconfident"] += 1
            if record.get("lottery_preference_flag"):
                self._bias_counters["lottery_preference"] += 1
            if record.get("underdiversification_flag"):
                self._bias_counters["underdiversified"] += 1
            if record.get("loss_aversion_flag"):
                self._bias_counters["loss_aversion"] += 1
            if record.get("averaging_down_flag"):
                self._bias_counters["averaging_down"] += 1
            if record.get("herding_flag"):
                self._bias_counters["herding_peer"] += 1
            pnl_dir = record.get("prior_pnl_direction", "neutral")
            action = record.get("action", "hold")
            if pnl_dir == "loss":
                self._bias_counters[f"loss_{action}"] = self._bias_counters.get(f"loss_{action}", 0) + 1
            elif pnl_dir == "gain":
                self._bias_counters[f"gain_{action}"] = self._bias_counters.get(f"gain_{action}", 0) + 1

            tom = int(record.get("tom_level", 0))
            if tom not in self._bias_tom_day:
                tom = 0

            lg_tom = self._loss_gain_by_tom.get(tom)
            if lg_tom is not None and pnl_dir in ("loss", "gain"):
                key = f"{pnl_dir}_{action}"
                if key in lg_tom:
                    lg_tom[key] += 1

            day = int(record.get("trading_day", 0))
            if day > self._bias_tom_current_day and self._bias_tom_current_day > 0:
                self._snapshot_bias_trend(self._bias_tom_current_day)
            self._bias_tom_current_day = max(self._bias_tom_current_day, day)
            td = self._bias_tom_day[tom]
            td["total"] += 1
            if record.get("disposition_effect_flag"):
                td["disposition"] += 1
            if record.get("overconfidence_flag"):
                td["overconfidence"] += 1
            if record.get("underdiversification_flag"):
                td["underdiversified"] += 1
            if record.get("lottery_preference_flag"):
                td["lottery"] += 1
            if record.get("herding_flag"):
                td["herding"] += 1

        elif name == "info_cascade":
            self._cascade_counters["total"] += 1
            if record.get("has_news"):
                self._cascade_counters["has_news"] += 1
            perceived = int(record.get("perceived_post_count", 0))
            following = int(record.get("following_authors_in_feed", 0))
            self._cascade_counters["total_perceived"] += perceived
            self._cascade_counters["following_authors"] += following
            ct = self._cascade_by_tom.get(int(record.get("tom_level", 0)))
            if ct is not None:
                ct["total"] += 1
                if record.get("has_news"):
                    ct["has_news"] += 1
                ct["total_perceived"] += perceived
                ct["following_authors"] += following

        elif name == "liquidity_provision":
            maker_tom = int(record.get("maker_tom_level", -1))
            taker_tom = int(record.get("taker_tom_level", -1))
            if maker_tom in self._liquidity_counters:
                self._liquidity_counters[maker_tom]["maker"] += 1
            if taker_tom in self._liquidity_counters:
                self._liquidity_counters[taker_tom]["taker"] += 1

        elif name == "plan_execution":
            self._plan_counters["total"] += 1
            adherence = record.get("adherence")
            if adherence is True:
                self._plan_counters["adhered"] += 1
            elif adherence is False:
                self._plan_counters["deviated"] += 1
            pt = self._plan_by_tom.get(int(record.get("tom_level", 0)))
            if pt is not None:
                pt["total"] += 1
                if adherence is True:
                    pt["adhered"] += 1
                elif adherence is False:
                    pt["deviated"] += 1

        elif name == "trades":
            self._latest_sim_time = max(self._latest_sim_time, float(record.get("sim_time", 0.0) or 0.0))
            self.recent_trades.append(record)

            if self._ws_clients:
                try:
                    self._ws_event_queue.put_nowait({
                        "type": "event_trade",
                        "data": {
                            "sim_time": float(record.get("sim_time", 0) or 0),
                            "symbol": str(record.get("symbol", "")),
                            "price": float(record.get("price", 0) or 0),
                            "quantity": int(record.get("quantity", 0) or 0),
                            "buyer_id": int(record.get("buyer_id", 0) or 0),
                            "seller_id": int(record.get("seller_id", 0) or 0),
                            "aggressor": str(record.get("aggressor", "")),
                        },
                    })
                except asyncio.QueueFull:
                    pass

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=self._ws_heartbeat)
        await ws.prepare(request)
        self._ws_clients.add(ws)
        _logger.info("WebSocket client connected (%d total)", len(self._ws_clients))
        try:
            state = self._build_state()
            await ws.send_json({"type": "full_state", "data": state})
            async for msg in ws:
                pass
        except Exception as ws_err:
            _logger.error("WebSocket handler error: %s: %s", type(ws_err).__name__, ws_err)
        finally:
            self._ws_clients.discard(ws)
            _logger.info("WebSocket client disconnected (%d remaining)", len(self._ws_clients))
        return ws

    async def _ws_broadcast_str(self, payload: str) -> None:
        dead: set[web.WebSocketResponse] = set()
        for ws in self._ws_clients:
            try:
                await ws.send_str(payload)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead

    async def _ws_push_loop(self) -> None:
        import time as _time
        last_full = _time.monotonic()
        while self._started:
            try:
                # 1) drain and broadcast incremental events
                events_flushed = 0
                while not self._ws_event_queue.empty() and events_flushed < 100 and self._ws_clients:
                    try:
                        event = self._ws_event_queue.get_nowait()
                        await self._ws_broadcast_str(json.dumps(event, ensure_ascii=False))
                        events_flushed += 1
                    except asyncio.QueueEmpty:
                        break

                # 2) periodic full state push
                now = _time.monotonic()
                if now - last_full >= self._ws_push_interval and self._ws_clients:
                    state = self._build_state()
                    await self._ws_broadcast_str(json.dumps({"type": "full_state", "data": state}, ensure_ascii=False))
                    last_full = now

                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.error("ws push loop error: %s: %s", type(exc).__name__, exc)
                await asyncio.sleep(0.5)

    async def _handle_index(self, request: web.Request) -> web.Response:
        static_dir = Path(__file__).resolve().parent / "static"
        index_path = static_dir / "index.html"
        if not index_path.exists():
            return web.Response(
                text="<h1>Dashboard HTML not found</h1><p>static/index.html is missing. Use the Vue frontend (npm run dev in app/dashboard/frontend/) instead.</p>",
                content_type="text/html",
                status=200,
            )
        html = index_path.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _handle_state(self, request: web.Request) -> web.Response:
        payload = self._build_state()
        return web.json_response(payload)

    def _snapshot_bias_trend(self, trading_day: int) -> None:
        """将当前交易日的按 ToM 偏差计数快照为比率，追加到时序 deque。"""
        point: dict = {"day": trading_day}
        bias_keys = ("disposition", "overconfidence", "underdiversified", "lottery", "herding")
        for tom in (0, 1, 2):
            counters = self._bias_tom_day.get(tom, {})
            total = max(1, counters.get("total", 0))
            point[f"tom{tom}"] = {
                k: round(counters.get(k, 0) / total * 100, 1) for k in bias_keys
            }
            point[f"tom{tom}"]["total"] = counters.get("total", 0)
        self._bias_trend.append(point)
        for tom in (0, 1, 2):
            for k in self._bias_tom_day.get(tom, {}):
                self._bias_tom_day[tom][k] = 0

    def _build_bias_stats(self) -> dict:
        """构建行为偏差统计，包含泡沫检测和极化/茧房指标。"""
        from app.domain.behavioral_bias import compute_self_fulfilling_prophecy, compute_polarization_echo_chamber

        stats = dict(self._bias_counters)

        conf_values = [pt["c"] for pt in self._confidence_trend] if self._confidence_trend else []
        dev_values = [pt["d"] for pt in self._deviation_trend] if self._deviation_trend else []
        stats.update(compute_self_fulfilling_prophecy(conf_values, dev_values))

        agent_sentiments = {}
        for aid, window in self._agent_sentiment_window.items():
            if window:
                agent_sentiments[aid] = sum(window) / len(window)
        follow_graph: dict[int, set[int]] = {}
        graph = self.agent_manager.social_board.social_graph
        if graph is not None:
            for aid, profile in graph._profiles.items():
                follow_graph[aid] = profile.following
        stats.update(compute_polarization_echo_chamber(agent_sentiments, follow_graph))

        stats["loss_gain_by_tom"] = {
            str(tom): dict(counters) for tom, counters in self._loss_gain_by_tom.items()
        }

        return stats

    def _build_state(self) -> dict:
        now_ts = time.time()
        sim_time = self._latest_sim_time
        trading_day = _compute_td(sim_time, self.trading_day_seconds)
        recent_window_seconds = 10.0
        window_start = sim_time - recent_window_seconds

        decision_agent_ids_10s: set[int] = set()
        order_agent_ids_10s: set[int] = set()
        for d in self.recent_decisions:
            d_sim_time = float(d.get("sim_time", 0.0) or 0.0)
            if d_sim_time < window_start:
                continue
            aid = int(d.get("agent_id", 0) or 0)
            if aid > 0:
                decision_agent_ids_10s.add(aid)
            action_executed = d.get("action_executed", {}) or {}
            action = str(action_executed.get("action", "")).lower()
            qty = int(action_executed.get("quantity", 0) or 0)
            status = str(action_executed.get("status", "")).lower()
            if aid > 0 and action in {"buy", "sell"} and qty > 0 and status == "ok":
                order_agent_ids_10s.add(aid)

        heavy = self._get_heavy_state(now_ts)
        holdings = heavy["holdings"]
        completed_trade_agents = heavy["completed_trade_agents"]
        completed_decision_agents = heavy["completed_decision_agents"]
        tom_summary = heavy["tom_summary"]
        social_hot = heavy["social_hot"]
        social_latest = heavy["social_latest"]
        social_news = heavy["social_news"]

        cda_by_symbol: dict[str, dict] = {}
        market_micro: dict[str, dict] = {}
        for symbol, ob in self.orderbooks.items():
            l2 = ob.l2_data(depth=self.l2_depth)
            l2_attr = ob.l2_attribution(depth=self.l2_depth, per_level_orders=self.l2_quote_orders)
            sym_trades = [t for t in list(self.recent_trades)[-120:] if str(t.get("symbol", "")).upper() == symbol][-80:]
            cda_by_symbol[symbol] = {
                "last_price": ob.last_price,
                "spread": l2.get("spread"),
                "bids": l2.get("bids", []),
                "asks": l2.get("asks", []),
                "bids_attribution": l2_attr.get("bids", []),
                "asks_attribution": l2_attr.get("asks", []),
                "recent_trades": sym_trades,
            }
            recent_ob_trades = ob.recent_trades(200)
            buy_vol = sum(int(t.quantity) for t in recent_ob_trades if t.aggressor_side.value == "bid")
            sell_vol = sum(int(t.quantity) for t in recent_ob_trades if t.aggressor_side.value == "ask")
            total_vol = buy_vol + sell_vol
            total_shares = sum(max(0, int(a.positions.get(symbol, 0))) for a in self.agent_manager.agents.values())
            prices = [float(t.price) for t in recent_ob_trades]
            vol_raw = _volatility(prices) if len(prices) >= 2 else None
            market_micro[symbol] = {
                "volume": total_vol,
                "buy_volume": buy_vol,
                "sell_volume": sell_vol,
                "buy_sell_ratio": round(buy_vol / max(1, sell_vol), 2),
                "turnover_rate": round(total_vol / max(1, total_shares), 4),
                "vwap": round(sum(float(t.price) * int(t.quantity) for t in recent_ob_trades) / max(1, total_vol), 4) if total_vol > 0 else None,
                "volatility": _round_or_none(vol_raw),
                "spread": round(float(l2.get("spread")), 4) if l2.get("spread") is not None else None,
                "trade_count": len(recent_ob_trades),
            }
        cda = cda_by_symbol.get(self.default_symbol, {})

        for symbol, ob in self.orderbooks.items():
            if ob.last_price is not None:
                if symbol not in self._price_trend:
                    self._price_trend[symbol] = deque(maxlen=self._price_trend_maxlen)
                series = self._price_trend[symbol]
                t_rounded = round(sim_time, 1)
                if not series or series[-1]["t"] != t_rounded:
                    series.append({"t": t_rounded, "p": round(float(ob.last_price), 4)})

        t_rounded = round(sim_time, 1)
        avg_sent = 0.0
        if self._recent_sentiments:
            avg_sent = round(sum(self._recent_sentiments) / len(self._recent_sentiments), 4)
        if not self._sentiment_trend or self._sentiment_trend[-1]["t"] != t_rounded:
            self._sentiment_trend.append({"t": t_rounded, "s": avg_sent})

        avg_conf = 0.5
        if self._recent_confidences:
            avg_conf = round(sum(self._recent_confidences) / len(self._recent_confidences), 4)
        if not self._confidence_trend or self._confidence_trend[-1]["t"] != t_rounded:
            self._confidence_trend.append({"t": t_rounded, "c": avg_conf})

        main_ob = self.orderbooks.get(self.default_symbol)
        if main_ob is not None and main_ob.last_price is not None:
            ref_px = self._fundamental_ref_prices.get(self.default_symbol, 100.0)
            dev = round((float(main_ob.last_price) - ref_px) / ref_px * 100.0, 4)
            if not self._deviation_trend or self._deviation_trend[-1]["t"] != t_rounded:
                self._deviation_trend.append({"t": t_rounded, "d": dev})

        index_snapshot = []
        index_series = {}
        broad_market = {
            "name": "大盘(加权)",
            "value": None,
            "pct_chg": None,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "total": 0,
            "volume": 0.0,
        }
        broad_index_series: list[dict] = []
        if self.index_board is not None:
            max_sim_time = float(self.agent_manager.sim_config.get("max_sim_time", 1.0) or 1.0)
            index_snapshot = self.index_board.current_snapshot(float(sim_time), max_sim_time)
            index_series = self.index_board.series_snapshot(lookback=self.index_lookback)
            broad_index_series = self.index_board.broad_index_series(lookback=self.index_lookback)
            broad_val = self.index_board.broad_index_value
            if index_snapshot:
                pct_vals = [float(r.get("pct_chg", 0.0) or 0.0) for r in index_snapshot]
                up_count = sum(1 for v in pct_vals if v > 0)
                down_count = sum(1 for v in pct_vals if v < 0)
                flat_count = len(pct_vals) - up_count - down_count
                total_volume = sum(float(r.get("volume", 0.0) or 0.0) for r in index_snapshot)
                broad_pct = None
                if broad_index_series and len(broad_index_series) >= 2:
                    broad_pct = broad_index_series[-1].get("pct_chg")
                elif broad_val is not None:
                    broad_pct = round(sum(pct_vals) / len(pct_vals), 4)
                broad_market = {
                    "name": "大盘(加权)",
                    "value": round(broad_val, 2) if broad_val is not None else None,
                    "pct_chg": broad_pct,
                    "up_count": up_count,
                    "down_count": down_count,
                    "flat_count": flat_count,
                    "total": len(pct_vals),
                    "volume": round(total_volume, 2),
                }

        indicators = self._compute_indicators(index_series)

        social_graph_stats: dict = {}
        graph = getattr(self.agent_manager.social_board, "social_graph", None)
        if graph is not None:
            profiles = list(graph._profiles.values())
            total_follows = sum(p.following_count for p in profiles)
            kol_list = sorted(
                [p for p in profiles if p.is_kol],
                key=lambda p: p.follower_count,
                reverse=True,
            )
            graph_top_n = self._social_graph_top_n
            top_by_followers = sorted(profiles, key=lambda p: p.follower_count, reverse=True)[:graph_top_n]
            top_nodes = sorted(profiles, key=lambda p: p.influence_score, reverse=True)[:graph_top_n]
            top_ids = {p.agent_id for p in top_nodes}
            graph_edges: list[dict] = []
            for p in top_nodes:
                for target_id in p.following:
                    if target_id in top_ids:
                        graph_edges.append({"source": p.agent_id, "target": target_id})
            graph_nodes = [
                {
                    "id": p.agent_id,
                    "tom": getattr(self.agent_manager.agents.get(p.agent_id), "tom_level", 0),
                    "followers": p.follower_count,
                    "influence": round(p.influence_score, 2),
                    "is_kol": p.is_kol,
                }
                for p in top_nodes
            ]
            social_graph_stats = {
                "total_agents": len(profiles),
                "total_follows": total_follows,
                "avg_following": round(total_follows / max(1, len(profiles)), 1),
                "kol_count": len(kol_list),
                "kol_threshold": graph._kol_follower_threshold,
                "kol_agents": [
                    {"agent_id": p.agent_id, "followers": p.follower_count, "following": p.following_count, "influence": round(p.influence_score, 2)}
                    for p in kol_list[:graph_top_n]
                ],
                "top_by_followers": [
                    {"agent_id": p.agent_id, "followers": p.follower_count, "following": p.following_count, "influence": round(p.influence_score, 2), "is_kol": p.is_kol}
                    for p in top_by_followers
                ],
                "graph_nodes": graph_nodes,
                "graph_edges": graph_edges,
            }

        return {
            "server_time": now_ts,
            "sim_time": sim_time,
            "trading_day": trading_day,
            "trading_day_seconds": self.trading_day_seconds,
            "metrics": {
                "window_seconds": recent_window_seconds,
                "total_agents": len(self.agent_manager.agents),
                "unique_decision_agents_10s": len(decision_agent_ids_10s),
                "unique_order_agents_10s": len(order_agent_ids_10s),
                "completed_trade_agents": completed_trade_agents,
                "completed_decision_agents": completed_decision_agents,
                "broad_market": broad_market,
            },
            "index_snapshot": index_snapshot,
            "index_series": index_series,
            "broad_index_series": broad_index_series,
            "active": {
                "thinking": list(self.thinking_agents.values()),
                "scheduled": list(self.scheduled_agents.values()),
                "running_agent_ids": sorted(
                    {
                        *[int(x.get("agent_id", 0)) for x in self.thinking_agents.values()],
                        *[int(x.get("agent_id", 0)) for x in self.scheduled_agents.values()],
                    }
                ),
                "recent_decisions": list(self.recent_decisions)[-120:],
                "recent_tools": list(self.recent_tools)[-120:],
            },
            "holdings": holdings,
            "social_hot": social_hot,
            "social_latest": social_latest,
            "social_news": social_news,
            "tom_summary": tom_summary,
            "technical_indicators": indicators,
            "price_trend": {k: list(v) for k, v in self._price_trend.items()},
            "sentiment_trend": list(self._sentiment_trend),
            "confidence_trend": list(self._confidence_trend),
            "bias_stats": self._build_bias_stats(),
            "bias_trends": list(self._bias_trend),
            "cascade_stats": {**self._cascade_counters, "by_tom": {str(k): dict(v) for k, v in self._cascade_by_tom.items()}},
            "liquidity_stats": {str(k): dict(v) for k, v in self._liquidity_counters.items()},
            "plan_stats": {**self._plan_counters, "by_tom": {str(k): dict(v) for k, v in self._plan_by_tom.items()}},
            "deviation_trend": list(self._deviation_trend),
            "cda": cda,
            "cda_by_symbol": cda_by_symbol,
            "market_micro": market_micro,
            "social_graph": social_graph_stats,
            "mm_subsidy": dict(self.agent_manager.mm_subsidy),
        }

    def _get_heavy_state(self, now_ts: float) -> dict:
        """缓存重量级状态数据（holdings/tom_summary/social），按 _heavy_cache_interval 节流更新。"""
        if self._heavy_cache and (now_ts - self._heavy_cache_time) < self._heavy_cache_interval:
            return self._heavy_cache

        holdings = []
        completed_trade_agents = 0
        completed_decision_agents = 0
        tom_data: dict[int, dict] = {0: {"wealths": [], "returns": [], "pnls": [], "trades": []},
                                      1: {"wealths": [], "returns": [], "pnls": [], "trades": []},
                                      2: {"wealths": [], "returns": [], "pnls": [], "trades": []}}
        for a in self.agent_manager.agents.values():
            if a.agent_id == 0:
                continue
            positions = {k: int(v) for k, v in getattr(a, "positions", {}).items()}
            total_shares = int(sum(max(0, int(qty)) for qty in positions.values()))
            current_positions_text = ", ".join(
                [f"{symbol}:{qty}" for symbol, qty in sorted(positions.items()) if int(qty) > 0]
            )
            pos_value = self.agent_manager._positions_market_value(positions)
            wealth = round(float(a.cash) + pos_value, 2)
            if int(getattr(a, "trade_count", 0) or 0) > 0:
                completed_trade_agents += 1
            if int(getattr(a, "decision_count", 0) or 0) > 0:
                completed_decision_agents += 1
            holdings.append(
                {
                    "agent_id": a.agent_id,
                    "tom_level": a.tom_level,
                    "cash": round(float(a.cash), 2),
                    "total_shares": total_shares,
                    "wealth": wealth,
                    "initial_asset": round(float(a.initial_asset), 2),
                    "return_pct": round((wealth - a.initial_asset) / a.initial_asset * 100, 2) if a.initial_asset > 0 else 0.0,
                    "trade_count": int(getattr(a, "trade_count", 0) or 0),
                    "decision_count": int(getattr(a, "decision_count", 0) or 0),
                    "total_pnl": round(float(getattr(a, "total_pnl", 0.0) or 0.0), 2),
                    "positions": positions,
                    "current_positions_text": current_positions_text,
                    "index_holdings": list(getattr(a, "index_holdings", [])),
                    "reasoning_text": "",
                }
            )
            td = tom_data.setdefault(a.tom_level, {"wealths": [], "returns": [], "pnls": [], "trades": []})
            td["wealths"].append(wealth)
            ret = (wealth - a.initial_asset) / a.initial_asset if a.initial_asset > 0 else 0.0
            td["returns"].append(ret)
            td["pnls"].append(a.total_pnl)
            td["trades"].append(a.trade_count)

        holdings.sort(key=lambda x: x["agent_id"])

        social_hot = []
        social_latest = []
        social_news = []
        sb = getattr(self.agent_manager, "social_board", None)
        if sb is not None:
            dual = sb.get_dual_perception(0, hot_k=20, latest_k=20)
            for feed_name, feed_list, target in [("hot", dual.get("hot", []), social_hot), ("latest", dual.get("latest", []), social_latest)]:
                for p in feed_list:
                    md = getattr(p, "metadata", {}) or {}
                    post_td = md.get("trading_day")
                    if post_td is None:
                        post_td = int(float(p.timestamp) // self.trading_day_seconds) + 1
                    target.append({
                        "post_id": p.post_id,
                        "agent_id": p.agent_id,
                        "content": p.content,
                        "timestamp": round(float(p.timestamp), 1),
                        "trading_day": int(post_td),
                        "source": p.source,
                        "likes": p.likes,
                        "dislikes": getattr(p, "dislikes", 0),
                        "retweet_count": p.retweet_count,
                        "original_post_id": p.original_post_id,
                    })

            # 新闻独立流：避免刷新时因 hot/latest 排名窗口变化而看不到新闻。
            for p in sb.get_latest_feed(top_k=sb.total_posts):
                if p.source != "news":
                    continue
                md = getattr(p, "metadata", {}) or {}
                post_td = md.get("trading_day")
                if post_td is None:
                    post_td = int(float(p.timestamp) // self.trading_day_seconds) + 1
                social_news.append({
                    "post_id": p.post_id,
                    "agent_id": p.agent_id,
                    "content": p.content,
                    "timestamp": round(float(p.timestamp), 1),
                    "trading_day": int(post_td),
                    "source": p.source,
                    "likes": p.likes,
                    "dislikes": getattr(p, "dislikes", 0),
                    "retweet_count": p.retweet_count,
                    "original_post_id": p.original_post_id,
                })
                if len(social_news) >= 40:
                    break

        tom_summary = {}
        for level in [0, 1, 2]:
            td = tom_data.get(level, {"wealths": [], "returns": [], "pnls": [], "trades": []})
            n = len(td["wealths"])
            if not n:
                tom_summary[str(level)] = {
                    "count": 0, "avg_wealth": 0, "total_wealth": 0,
                    "avg_initial_asset": 0, "avg_return_pct": 0, "roi_pct": 0,
                    "avg_pnl": 0, "positive_return_ratio": 0, "win_rate_trade_pct": 0,
                    "total_trades": 0, "avg_trades_per_agent": 0,
                    "median_wealth": 0, "min_wealth": 0, "max_wealth": 0,
                    "gini_coefficient": 0, "top10_wealth_share": 0,
                }
                continue
            wealths_sorted = sorted(td["wealths"])
            level_agents = [a for a in self.agent_manager.agents.values() if a.agent_id != 0 and a.tom_level == level]
            total_initial_asset = sum(float(a.initial_asset) for a in level_agents)
            total_realized_gains = sum(int(getattr(a, "cum_realized_gains", 0) or 0) for a in level_agents)
            total_realized_losses = sum(int(getattr(a, "cum_realized_losses", 0) or 0) for a in level_agents)
            realized_trade_count = total_realized_gains + total_realized_losses
            roi_pct = 0.0
            if total_initial_asset > 0:
                roi_pct = (sum(td["wealths"]) - total_initial_asset) / total_initial_asset * 100.0
            win_rate_trade_pct = 0.0
            if realized_trade_count > 0:
                win_rate_trade_pct = total_realized_gains / realized_trade_count * 100.0
            tom_summary[str(level)] = {
                "count": n,
                "avg_wealth": round(sum(td["wealths"]) / n, 2),
                "total_wealth": round(sum(td["wealths"]), 2),
                "median_wealth": round(wealths_sorted[n // 2], 2),
                "min_wealth": round(wealths_sorted[0], 2),
                "max_wealth": round(wealths_sorted[-1], 2),
                "avg_initial_asset": round(total_initial_asset / n, 2) if n > 0 else 0.0,
                "avg_return_pct": round(sum(td["returns"]) / n * 100, 2),
                "roi_pct": round(roi_pct, 2),
                "avg_pnl": round(sum(td["pnls"]) / n, 2),
                "positive_return_ratio": round(sum(1 for r in td["returns"] if r > 0) / n * 100, 1),
                "win_rate_trade_pct": round(win_rate_trade_pct, 1),
                "total_trades": sum(td["trades"]),
                "avg_trades_per_agent": round(sum(td["trades"]) / n, 1),
                "gini_coefficient": round(self._gini_coefficient(wealths_sorted), 4),
                "top10_wealth_share": round(sum(wealths_sorted[-max(1, n // 10):]) / max(1, sum(wealths_sorted)), 4) if sum(wealths_sorted) > 0 else 0.0,
            }

        self._heavy_cache = {
            "holdings": holdings,
            "completed_trade_agents": completed_trade_agents,
            "completed_decision_agents": completed_decision_agents,
            "tom_summary": tom_summary,
            "social_hot": social_hot,
            "social_latest": social_latest,
            "social_news": social_news,
        }
        self._heavy_cache_time = now_ts
        return self._heavy_cache

    @staticmethod
    def _gini_coefficient(sorted_values: list[float]) -> float:
        from app.utils.indicators import gini_coefficient
        return gini_coefficient(sorted_values)

    def _compute_indicators(self, index_series: dict[str, list[dict]]) -> dict:
        result: dict[str, dict] = {}

        for symbol, ob in self.orderbooks.items():
            trades = ob.recent_trades(500)
            market_prices = [float(t.price) for t in trades]
            if market_prices:
                result[symbol] = self._calc_series_indicators(market_prices)
            elif ob.last_price is not None:
                idx_prices = [float(r.get("close", 0.0) or 0.0) for r in index_series.get(symbol, []) if float(r.get("close", 0.0) or 0.0) > 0]
                result[symbol] = self._calc_series_indicators(idx_prices if idx_prices else [float(ob.last_price)])
            else:
                idx_prices = [float(r.get("close", 0.0) or 0.0) for r in index_series.get(symbol, []) if float(r.get("close", 0.0) or 0.0) > 0]
                result[symbol] = self._calc_series_indicators(idx_prices)

        return result

    @staticmethod
    def _calc_series_indicators(prices: list[float]) -> dict:
        if not prices:
            return {
                "samples": 0,
                "last_price": None,
                "sma_5": None,
                "sma_20": None,
                "ema_5": None,
                "ema_20": None,
                "rsi_14": None,
                "momentum_10": None,
                "volatility": None,
            }
        return {
            "samples": len(prices),
            "last_price": round(prices[-1], 6),
            "sma_5": _round_or_none(_sma(prices, 5)),
            "sma_20": _round_or_none(_sma(prices, 20)),
            "ema_5": _round_or_none(_ema(prices, 5)),
            "ema_20": _round_or_none(_ema(prices, 20)),
            "rsi_14": _round_or_none(_rsi(prices, 14)),
            "momentum_10": _round_or_none(_momentum(prices, 10)),
            "volatility": _round_or_none(_volatility(prices)),
        }

