from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from app.dashboard.ws_session import TOPICS as WS_TOPICS, WsSession, build_payload, holdings_fingerprints

_logger = logging.getLogger(__name__)

from app.utils.indicators import ema as _ema, momentum as _momentum, rsi as _rsi, sma as _sma, volatility as _volatility, round_or_none as _round_or_none, compute_trading_day as _compute_td


def _safe_float(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f == f else None


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
        # 最近一次集合竞价结果（按标的），由引擎在撮合后通过 on_call_auction 推送
        self._last_auction: dict[str, dict] = {}
        self._auction_history: deque[dict] = deque(maxlen=400)
        self._price_trend: dict[str, deque] = {}
        self._price_trend_maxlen = price_trend_maxlen
        # 盘中 K 线：按固定仿真秒数分桶，由成交流聚合；默认一根 bar 对应展示时钟的一分钟（09:30→15:00 共 330 分钟）
        bar_seconds_cfg = float(dcfg.get("intraday_bar_seconds", 0) or 0)
        self._intraday_bar_seconds: float = bar_seconds_cfg if bar_seconds_cfg > 0 else max(0.5, self.trading_day_seconds / 330.0)
        self._intraday_bars_maxlen: int = max(50, int(dcfg.get("intraday_bars_maxlen", 600)))
        self._intraday_bars: dict[str, deque] = {}
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
        self._ws_sessions: dict[web.WebSocketResponse, WsSession] = {}
        self._push_task: asyncio.Task | None = None
        self._ws_push_interval: float = float(dcfg.get("ws_push_interval", 1.0))
        self._ws_heartbeat: float = float(dcfg.get("ws_heartbeat", 20.0))
        self._ws_event_queue: asyncio.Queue = asyncio.Queue(maxsize=int(dcfg.get("ws_event_queue_size", 2000)))

        self._fundamental_ref_prices: dict[str, float] = {
            str(symbol).upper(): float(ob.limit_reference_price)
            for symbol, ob in self.orderbooks.items()
        }

        self._social_graph_top_n: int = int(dcfg.get("social_graph_top_n", 30))

        self._real_index_series: dict[str, list[dict]] = {}
        self._real_curve_calendar: list[dict] = []
        self._real_curve_include_closed_days: bool = bool(dcfg.get("real_curve_include_closed_days", True))
        self._metrics_include_closed_days: bool = bool(dcfg.get("metrics_include_closed_days", False))
        self._experimental_daily_title_mode: bool = bool(dcfg.get("experimental_daily_title_mode", False))
        if self._experimental_daily_title_mode:
            self._load_real_index_curves(
                curves_file=str(dcfg.get("real_index_curves_file", "data/index_volatility_curves.json")),
                calendar_news_file=str(dcfg.get("real_calendar_news_file", "data/news2.json")),
            )
        else:
            _logger.info("Real index curves disabled (experimental_daily_title_mode=False)")

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
        total += self._replay_intraday_bars(run_dir)

        tail_replay = [
            ("trades", self.recent_trades.maxlen or 200),
            ("decisions", self.recent_decisions.maxlen or 200),
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

    def _ingest_trade_bar(self, record: dict) -> None:
        """把一笔成交并入对应标的的盘中 K 线（同一分桶内更新高低收和成交量，否则开新 bar）。"""
        symbol = str(record.get("symbol", "") or "").upper()
        try:
            price = float(record.get("price", 0) or 0)
            qty = int(record.get("quantity", 0) or 0)
            sim_t = float(record.get("sim_time", 0.0) or 0.0)
        except (TypeError, ValueError):
            return
        if not symbol or price <= 0 or qty <= 0:
            return
        bar_s = self._intraday_bar_seconds
        bucket = round((sim_t // bar_s) * bar_s, 3)
        series = self._intraday_bars.get(symbol)
        if series is None:
            series = deque(maxlen=self._intraday_bars_maxlen)
            self._intraday_bars[symbol] = series
        if series and series[-1]["t"] >= bucket:
            bar = series[-1]
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
            bar["volume"] += qty
            return
        series.append({"t": bucket, "open": price, "high": price, "low": price, "close": price, "volume": qty})

    def _replay_intraday_bars(self, run_dir: Path, tail_lines: int = 60000) -> int:
        """续跑/重连时从 trades.jsonl 尾部重建盘中 K 线（只取尾部，避免全量扫描大文件）。"""
        jsonl_path = run_dir / "trades.jsonl"
        if not jsonl_path.exists():
            return 0
        count = 0
        for line in self._read_tail_lines(jsonl_path, tail_lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._ingest_trade_bar(record)
            count += 1
        _logger.info("Dashboard replay: intraday bars rebuilt from %d trades, symbols=%d", count, len(self._intraday_bars))
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

    @staticmethod
    def _resolve_repo_path(path_text: str) -> Path:
        p = Path(str(path_text or "").strip())
        if p.is_absolute():
            return p
        return Path(__file__).resolve().parents[2] / p

    @staticmethod
    def _normalize_real_rows(rows: list[dict]) -> list[dict]:
        out: list[dict] = []
        for row in sorted(rows, key=lambda x: str(x.get("date", ""))):
            date = str(row.get("date", "")).strip()
            if not date:
                continue
            close = row.get("close")
            if close is None:
                continue
            try:
                close_v = float(close)
            except (TypeError, ValueError):
                continue
            vol = row.get("volatility")
            vol_v = None
            if vol is not None:
                try:
                    vol_v = float(vol)
                except (TypeError, ValueError):
                    vol_v = None
            up_down_raw = row.get("up_down")
            up_down_v = 1 if vol_v is not None and vol_v > 0 else 0
            if up_down_raw is not None:
                try:
                    up_down_v = int(up_down_raw)
                except (TypeError, ValueError):
                    pass
            out.append(
                {
                    "date": date,
                    "close": round(close_v, 6),
                    "volatility": None if vol_v is None else round(vol_v, 8),
                    "up_down": 1 if up_down_v > 0 else 0,
                    "market_status": str(row.get("market_status", "")),
                    "is_closed": bool(row.get("is_closed", False)),
                }
            )
        return out

    @staticmethod
    def _build_calendar_from_news(news_items: list[dict]) -> list[dict]:
        by_day: dict[int, dict] = {}
        by_date: dict[str, dict] = {}

        for item in news_items:
            if not isinstance(item, dict):
                continue
            date = str(item.get("date", "")).strip()
            if not date:
                continue
            status = str(item.get("market_status", "")).strip()
            weekday = str(item.get("weekday", "")).strip()
            day_raw = item.get("day")
            day_int = None
            if day_raw is not None:
                try:
                    day_int = int(day_raw)
                except (TypeError, ValueError):
                    day_int = None

            if day_int is not None and day_int > 0:
                if day_int not in by_day:
                    by_day[day_int] = {
                        "day": day_int,
                        "date": date,
                        "market_status": status,
                        "weekday": weekday,
                    }
                else:
                    if not by_day[day_int].get("market_status") and status:
                        by_day[day_int]["market_status"] = status
                    if not by_day[day_int].get("weekday") and weekday:
                        by_day[day_int]["weekday"] = weekday
            else:
                if date not in by_date:
                    by_date[date] = {"date": date, "market_status": status, "weekday": weekday}
                else:
                    if not by_date[date].get("market_status") and status:
                        by_date[date]["market_status"] = status
                    if not by_date[date].get("weekday") and weekday:
                        by_date[date]["weekday"] = weekday

        if by_day:
            return [by_day[d] for d in sorted(by_day.keys())]

        out: list[dict] = []
        for i, date in enumerate(sorted(by_date.keys()), start=1):
            item = by_date[date]
            out.append(
                {
                    "day": i,
                    "date": date,
                    "market_status": str(item.get("market_status", "")),
                    "weekday": str(item.get("weekday", "")),
                }
            )
        return out

    def _expand_real_rows_with_calendar(self, rows: list[dict], calendar: list[dict]) -> list[dict]:
        row_by_date: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            date = str(row.get("date", "")).strip()
            if date:
                row_by_date[date] = row

        out: list[dict] = []
        prev_close: float | None = None
        for cal in calendar:
            date = str(cal.get("date", "")).strip()
            if not date:
                continue
            status = str(cal.get("market_status", "")).strip()
            source = row_by_date.get(date)
            if source is not None:
                close_raw = source.get("close")
                if close_raw is None:
                    continue
                try:
                    close_v = float(close_raw)
                except (TypeError, ValueError):
                    continue
                prev_close = close_v

                vol = source.get("volatility")
                vol_v = None
                if vol is not None:
                    try:
                        vol_v = float(vol)
                    except (TypeError, ValueError):
                        vol_v = None

                up_down_raw = source.get("up_down")
                up_down_v = 1 if vol_v is not None and vol_v > 0 else 0
                if up_down_raw is not None:
                    try:
                        up_down_v = int(up_down_raw)
                    except (TypeError, ValueError):
                        pass

                out.append(
                    {
                        "date": date,
                        "close": round(close_v, 6),
                        "volatility": None if vol_v is None else round(vol_v, 8),
                        "up_down": 1 if up_down_v > 0 else 0,
                        "market_status": status,
                        "is_closed": status.startswith("休市"),
                    }
                )
                continue

            if status.startswith("休市") and prev_close is not None:
                out.append(
                    {
                        "date": date,
                        "close": round(prev_close, 6),
                        "volatility": 0.0,
                        "up_down": 0,
                        "market_status": status,
                        "is_closed": True,
                    }
                )

        return out

    def _load_real_index_curves(self, curves_file: str, calendar_news_file: str) -> None:
        self._real_index_series = {}
        self._real_curve_calendar = []

        curves_path = self._resolve_repo_path(curves_file)
        if not curves_path.exists():
            _logger.info("Real index curves file not found: %s", curves_path)
            return

        curves_obj: dict[str, Any]
        try:
            curves_obj = json.loads(curves_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _logger.warning("Failed to load real index curves from %s: %s", curves_path, exc)
            return

        indices = curves_obj.get("indices", {}) if isinstance(curves_obj, dict) else {}
        if not isinstance(indices, dict):
            _logger.warning("Invalid real index curves format in %s: missing 'indices' object", curves_path)
            return

        calendar: list[dict] = []
        news_path = self._resolve_repo_path(calendar_news_file)
        if news_path.exists():
            try:
                news_obj = json.loads(news_path.read_text(encoding="utf-8"))
                news_items = news_obj.get("news", []) if isinstance(news_obj, dict) else []
                if isinstance(news_items, list):
                    calendar = self._build_calendar_from_news(news_items)
            except Exception as exc:
                _logger.warning("Failed to load real-curve calendar from %s: %s", news_path, exc)
        else:
            _logger.info("Real-curve calendar news file not found: %s", news_path)

        for symbol, rows in indices.items():
            if not isinstance(rows, list):
                continue
            row_dicts = [r for r in rows if isinstance(r, dict)]
            if not row_dicts:
                continue

            normalized = self._normalize_real_rows(row_dicts)
            if self._real_curve_include_closed_days and calendar:
                expanded = self._expand_real_rows_with_calendar(normalized, calendar)
                self._real_index_series[str(symbol)] = expanded if expanded else normalized
            else:
                self._real_index_series[str(symbol)] = normalized

        if calendar:
            self._real_curve_calendar = [
                {
                    "day": int(item.get("day", i + 1)),
                    "date": str(item.get("date", "")),
                    "market_status": str(item.get("market_status", "")),
                }
                for i, item in enumerate(calendar)
                if str(item.get("date", ""))
            ]
        elif self._real_index_series:
            # 无日历时退化为按真实曲线日期构建简单日序。
            first_symbol = next(iter(self._real_index_series.keys()))
            first_rows = self._real_index_series.get(first_symbol, [])
            self._real_curve_calendar = [
                {
                    "day": i + 1,
                    "date": str(row.get("date", "")),
                    "market_status": str(row.get("market_status", "")),
                }
                for i, row in enumerate(first_rows)
                if str(row.get("date", ""))
            ]

        # --- 合成真实大盘加权曲线（与仿真 index_board 同口径）---
        self._build_real_broad_index_series()

        _logger.info(
            "Loaded real index curves: symbols=%d calendar_days=%d include_closed=%s broad=%s",
            len(self._real_index_series),
            len(self._real_curve_calendar),
            self._real_curve_include_closed_days,
            "__BROAD__" in self._real_index_series,
        )

    def _build_real_broad_index_series(self) -> None:
        """从已加载的真实行业指数曲线合成大盘加权曲线（权重同 index_board）"""
        weights: dict[str, float] = {}
        if self.index_board is not None:
            weights = dict(getattr(self.index_board, "_broad_weights", {}))
        if not weights:
            return

        # 按日期收集各指数收盘价
        by_date: dict[str, dict[str, float]] = {}
        all_dates_set: set[str] = set()
        for symbol, w in weights.items():
            rows = self._real_index_series.get(symbol, [])
            for row in rows:
                date = str(row.get("date", ""))
                close = row.get("close")
                if not date or close is None:
                    continue
                if date not in by_date:
                    by_date[date] = {}
                by_date[date][symbol] = float(close)
                all_dates_set.add(date)

        if not by_date:
            return

        # 用第一个可用日期的收盘价作为各指数基准价
        sorted_dates = sorted(all_dates_set)
        base_prices: dict[str, float] = {}
        for date in sorted_dates:
            for symbol in weights:
                if symbol not in base_prices and symbol in by_date.get(date, {}):
                    base_prices[symbol] = by_date[date][symbol]
            if len(base_prices) == len(weights):
                break

        if not base_prices:
            return

        base_value = 100.0
        broad_rows: list[dict] = []
        prev_close: float | None = None

        # 从 real_index_series 中获取一个参考系列以保留 market_status / is_closed 等字段
        ref_series: dict[str, dict] = {}
        for symbol in weights:
            for row in self._real_index_series.get(symbol, []):
                date = str(row.get("date", ""))
                if date and date not in ref_series:
                    ref_series[date] = row

        for date in sorted_dates:
            day_data = by_date.get(date, {})
            weighted_sum = 0.0
            used_weight = 0.0
            for symbol, w in weights.items():
                if symbol not in day_data or symbol not in base_prices:
                    continue
                bp = base_prices[symbol]
                if bp <= 0:
                    continue
                weighted_sum += w * (day_data[symbol] / bp)
                used_weight += w

            if used_weight <= 0:
                continue

            close = base_value * (weighted_sum / used_weight)
            pct_chg = 0.0
            if prev_close is not None and prev_close > 0:
                pct_chg = (close - prev_close) / prev_close * 100.0

            ref = ref_series.get(date, {})
            broad_rows.append({
                "date": date,
                "close": round(close, 6),
                "volatility": None,
                "up_down": 1 if pct_chg > 0 else 0,
                "market_status": str(ref.get("market_status", "")),
                "is_closed": bool(ref.get("is_closed", False)),
            })
            prev_close = close

        if broad_rows:
            self._real_index_series["__BROAD__"] = broad_rows

    @staticmethod
    def _sim_row_to_day(sim_date: str, trading_day_seconds: float) -> int | None:
        if not sim_date.startswith("SIM_"):
            return None
        if "_T" not in sim_date:
            return None
        try:
            sim_time = float(sim_date.rsplit("_T", 1)[1])
        except (TypeError, ValueError):
            return None
        return int(sim_time // max(1e-6, trading_day_seconds)) + 1

    @staticmethod
    def _sign(v: float, eps: float = 1e-12) -> int:
        if v > eps:
            return 1
        if v < -eps:
            return -1
        return 0

    @staticmethod
    def _pearson_corr(xs: list[float], ys: list[float]) -> float | None:
        n = min(len(xs), len(ys))
        if n < 2:
            return None
        x = xs[:n]
        y = ys[:n]
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
        den_x = sum((v - mx) ** 2 for v in x)
        den_y = sum((v - my) ** 2 for v in y)
        if den_x <= 0 or den_y <= 0:
            return None
        return num / ((den_x ** 0.5) * (den_y ** 0.5))

    @staticmethod
    def _mean(xs: list[float]) -> float | None:
        if not xs:
            return None
        return sum(xs) / len(xs)

    @staticmethod
    def _qlike(
        real_var: list[float],
        sim_var: list[float],
        eps: float = 1e-8,
        upper_tail_quantile: float = 0.95,
    ) -> float | None:
        import math

        n = min(len(real_var), len(sim_var))
        if n < 2:
            return None
        losses: list[float] = []
        for i in range(n):
            rv = max(eps, float(real_var[i]))
            hv = max(eps, float(sim_var[i]))
            ratio = rv / hv
            losses.append(ratio - math.log(ratio) - 1.0)

        if len(losses) >= 5:
            sorted_losses = sorted(losses)
            q = max(0.5, min(0.999, float(upper_tail_quantile)))
            cap_idx = int((len(sorted_losses) - 1) * q)
            cap = sorted_losses[cap_idx]
            losses = [min(v, cap) for v in losses]

        return RealtimeDashboard._mean(losses)

    @staticmethod
    def _log_rmse(real_var: list[float], sim_var: list[float], eps: float = 1e-12) -> float | None:
        import math

        n = min(len(real_var), len(sim_var))
        if n < 2:
            return None
        sq_err: list[float] = []
        for i in range(n):
            lr = math.log(max(eps, float(real_var[i])))
            ls = math.log(max(eps, float(sim_var[i])))
            e = lr - ls
            sq_err.append(e * e)
        mse = RealtimeDashboard._mean(sq_err)
        return None if mse is None else math.sqrt(mse)

    @staticmethod
    def _mz_stats(real_var: list[float], sim_var: list[float]) -> dict[str, float | int | None]:
        import math

        n = min(len(real_var), len(sim_var))
        if n < 3:
            return {"alpha": None, "beta": None, "r2": None, "wald_chi2": None, "p_value": None, "n": n}

        x = [float(v) for v in sim_var[:n]]
        y = [float(v) for v in real_var[:n]]

        sx = sum(x)
        sy = sum(y)
        sxx = sum(v * v for v in x)
        sxy = sum(x[i] * y[i] for i in range(n))
        den = n * sxx - sx * sx
        if abs(den) <= 1e-18:
            return {"alpha": None, "beta": None, "r2": None, "wald_chi2": None, "p_value": None, "n": n}

        beta = (n * sxy - sx * sy) / den
        alpha = (sy - beta * sx) / n

        y_bar = sy / n
        sse = 0.0
        sst = 0.0
        for i in range(n):
            y_hat = alpha + beta * x[i]
            e = y[i] - y_hat
            sse += e * e
            dy = y[i] - y_bar
            sst += dy * dy
        r2 = None if sst <= 1e-18 else (1.0 - sse / sst)

        if n <= 2:
            return {"alpha": alpha, "beta": beta, "r2": r2, "wald_chi2": None, "p_value": None, "n": n}

        sigma2 = sse / (n - 2)
        inv00 = sxx / den
        inv01 = -sx / den
        inv10 = -sx / den
        inv11 = n / den

        cov00 = sigma2 * inv00
        cov01 = sigma2 * inv01
        cov10 = sigma2 * inv10
        cov11 = sigma2 * inv11

        c0 = alpha
        c1 = beta - 1.0
        cov_det = cov00 * cov11 - cov01 * cov10
        if abs(cov_det) <= 1e-24:
            return {"alpha": alpha, "beta": beta, "r2": r2, "wald_chi2": None, "p_value": None, "n": n}

        ic00 = cov11 / cov_det
        ic01 = -cov01 / cov_det
        ic10 = -cov10 / cov_det
        ic11 = cov00 / cov_det
        wald_chi2 = c0 * (ic00 * c0 + ic01 * c1) + c1 * (ic10 * c0 + ic11 * c1)
        p_value = math.exp(-0.5 * wald_chi2) if wald_chi2 >= 0 else None
        return {"alpha": alpha, "beta": beta, "r2": r2, "wald_chi2": wald_chi2, "p_value": p_value, "n": n}

    def _compute_curve_realtime_metrics(self, index_series: dict[str, list[dict]], trading_day: int) -> dict:
        if not self._real_index_series or not self._real_curve_calendar:
            return {
                "prediction_accuracy_pct": None,
                "prediction_sample_count": 0,
                "prediction_accuracy_same_day_pct": None,
                "prediction_same_day_sample_count": 0,
                "prediction_accuracy_forward1_pct": None,
                "prediction_forward1_sample_count": 0,
                "volatility_fit_pct": None,
                "volatility_fit_sample_count": 0,
            }

        calendar_by_day: dict[int, dict] = {}
        for item in self._real_curve_calendar:
            try:
                day = int(item.get("day", 0) or 0)
            except (TypeError, ValueError):
                continue
            if day <= 0:
                continue
            status = str(item.get("market_status", "")).strip()
            status_lower = status.lower()
            is_closed = bool(item.get("is_closed", False)) or status.startswith("休市") or status_lower.startswith("closed")
            calendar_by_day[day] = {
                "date": str(item.get("date", "")),
                "market_status": status,
                "is_closed": is_closed,
            }

        if not calendar_by_day:
            return {
                "prediction_accuracy_pct": None,
                "prediction_sample_count": 0,
                "prediction_accuracy_same_day_pct": None,
                "prediction_same_day_sample_count": 0,
                "prediction_accuracy_forward1_pct": None,
                "prediction_forward1_sample_count": 0,
                "volatility_fit_pct": None,
                "volatility_fit_sample_count": 0,
            }

        max_day = min(int(trading_day), max(calendar_by_day.keys()))
        if max_day < 2:
            return {
                "prediction_accuracy_pct": None,
                "prediction_sample_count": 0,
                "prediction_accuracy_same_day_pct": None,
                "prediction_same_day_sample_count": 0,
                "prediction_accuracy_forward1_pct": None,
                "prediction_forward1_sample_count": 0,
                "volatility_fit_pct": None,
                "volatility_fit_sample_count": 0,
            }

        pred_total_same_day = 0
        pred_match_same_day = 0
        pred_total_forward1 = 0
        pred_match_forward1 = 0
        fit_corr_weighted_sum = 0.0
        fit_corr_weight_total = 0
        pooled_real_var: list[float] = []
        pooled_sim_var: list[float] = []

        for symbol, real_rows in self._real_index_series.items():
            sim_rows = index_series.get(symbol, [])
            if not sim_rows:
                continue

            sim_by_day: dict[int, float] = {}
            for row in sim_rows:
                day = self._sim_row_to_day(str(row.get("date", "")), self.trading_day_seconds)
                if day is None or day > max_day:
                    continue
                close = row.get("close")
                if close is None:
                    continue
                try:
                    sim_by_day[day] = float(close)
                except (TypeError, ValueError):
                    continue

            if not sim_by_day:
                continue

            real_by_date: dict[str, float] = {}
            for row in real_rows:
                if not isinstance(row, dict):
                    continue
                date = str(row.get("date", "")).strip()
                if not date:
                    continue
                close = row.get("close")
                if close is None:
                    continue
                try:
                    real_by_date[date] = float(close)
                except (TypeError, ValueError):
                    continue

            aligned: list[tuple[int, float, float]] = []
            for day in range(1, max_day + 1):
                cal = calendar_by_day.get(day)
                if not cal:
                    continue
                is_closed = bool(cal.get("is_closed", False))

                # 严格交集口径：仅统计 real/sim 在同一交易日都存在的点。
                if is_closed and (not self._metrics_include_closed_days):
                    continue
                sim_close = sim_by_day.get(day)
                if sim_close is None:
                    continue
                date = str(cal.get("date", ""))
                real_close = real_by_date.get(date)
                if real_close is None:
                    continue
                aligned.append((day, real_close, sim_close))

            if len(aligned) < 2:
                continue

            # 前瞻1日口径：使用上一日模拟变化方向预测当日真实变化方向。
            for i in range(2, len(aligned)):
                day_prev2, _, sim_prev2 = aligned[i - 2]
                day_prev1, real_prev, sim_prev1 = aligned[i - 1]
                day_cur, real_cur, _ = aligned[i]

                if not (day_prev1 == day_prev2 + 1 and day_cur == day_prev1 + 1):
                    continue

                real_delta = real_cur - real_prev
                sim_pred_delta = sim_prev1 - sim_prev2
                real_dir = self._sign(real_delta)
                sim_pred_dir = self._sign(sim_pred_delta)

                # 双零表示双方都无方向信息，不计入样本。
                if real_dir == 0 and sim_pred_dir == 0:
                    continue
                if real_dir == sim_pred_dir:
                    pred_match_forward1 += 1
                pred_total_forward1 += 1

            real_returns: list[float] = []
            sim_returns: list[float] = []
            # 同日口径与拟合指标：用同一日的真实/模拟变化进行比较。
            for i in range(1, len(aligned)):
                day_prev, real_prev, sim_prev = aligned[i - 1]
                day_cur, real_cur, sim_cur = aligned[i]

                if day_cur != day_prev + 1:
                    continue

                real_delta = real_cur - real_prev
                sim_delta = sim_cur - sim_prev

                real_dir = self._sign(real_delta)
                sim_dir = self._sign(sim_delta)
                if not (real_dir == 0 and sim_dir == 0):
                    if real_dir == sim_dir:
                        pred_match_same_day += 1
                    pred_total_same_day += 1

                real_den = real_prev if abs(real_prev) > 1e-9 else 1.0
                sim_den = sim_prev if abs(sim_prev) > 1e-9 else 1.0
                real_returns.append(real_delta / real_den)
                sim_returns.append(sim_delta / sim_den)

            corr = self._pearson_corr(real_returns, sim_returns)
            if corr is None:
                if real_returns and all(abs(real_returns[i] - sim_returns[i]) <= 1e-12 for i in range(len(real_returns))):
                    corr = 1.0
                elif real_returns:
                    corr = 0.0
            if corr is not None and real_returns:
                fit_corr_weighted_sum += corr * len(real_returns)
                fit_corr_weight_total += len(real_returns)

            for i in range(min(len(real_returns), len(sim_returns))):
                pooled_real_var.append(real_returns[i] * real_returns[i])
                pooled_sim_var.append(sim_returns[i] * sim_returns[i])

        prediction_accuracy_same_day_pct = None
        if pred_total_same_day > 0:
            prediction_accuracy_same_day_pct = round(pred_match_same_day / pred_total_same_day * 100.0, 2)

        prediction_accuracy_forward1_pct = None
        if pred_total_forward1 > 0:
            prediction_accuracy_forward1_pct = round(pred_match_forward1 / pred_total_forward1 * 100.0, 2)

        volatility_fit_pct = None
        if fit_corr_weight_total > 0:
            avg_corr = fit_corr_weighted_sum / fit_corr_weight_total
            avg_corr = max(-1.0, min(1.0, avg_corr))
            volatility_fit_pct = round((avg_corr + 1.0) * 50.0, 2)

        qlike = self._qlike(pooled_real_var, pooled_sim_var)
        log_rmse = self._log_rmse(pooled_real_var, pooled_sim_var)
        mz = self._mz_stats(pooled_real_var, pooled_sim_var)

        return {
            # 兼容旧字段：默认沿用前瞻1日口径。
            "prediction_accuracy_pct": prediction_accuracy_forward1_pct,
            "prediction_sample_count": pred_total_forward1,
            "prediction_accuracy_same_day_pct": prediction_accuracy_same_day_pct,
            "prediction_same_day_sample_count": pred_total_same_day,
            "prediction_accuracy_forward1_pct": prediction_accuracy_forward1_pct,
            "prediction_forward1_sample_count": pred_total_forward1,
            "volatility_fit_pct": volatility_fit_pct,
            "volatility_fit_sample_count": fit_corr_weight_total,
            "volatility_qlike": None if qlike is None else round(qlike, 6),
            "volatility_log_rmse": None if log_rmse is None else round(log_rmse, 6),
            "mz_alpha": None if mz.get("alpha") is None else round(float(mz["alpha"]), 6),
            "mz_beta": None if mz.get("beta") is None else round(float(mz["beta"]), 6),
            "mz_r2": None if mz.get("r2") is None else round(float(mz["r2"]), 6),
            "mz_wald_chi2": None if mz.get("wald_chi2") is None else round(float(mz["wald_chi2"]), 6),
            "mz_p_value": None if mz.get("p_value") is None else round(float(mz["p_value"]), 6),
            "mz_sample_count": int(mz.get("n", 0) or 0),
            "include_closed_days_for_metrics": bool(self._metrics_include_closed_days),
        }

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

    def on_call_auction(self, symbol: str, payload: dict) -> None:
        rec = dict(payload)
        # 面板上保留最近一次“产生了成交价”的竞价（未交叉的收盘竞价不覆盖当日开盘价）
        if rec.get("price") is not None:
            self._last_auction[str(symbol).upper()] = rec
        self._auction_history.append(rec)
        self._latest_sim_time = max(self._latest_sim_time, float(rec.get("sim_time", 0.0) or 0.0))

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
        # execute_time 是未来时刻，不能用它推进看板时钟（会让趋势图和交易日提前）
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
                    "sentiment": _safe_float(llm_out.get("sentiment")),
                    "confidence": _safe_float(llm_out.get("confidence")),
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
                            "sentiment": _safe_float(llm_out.get("sentiment")),
                            "confidence": _safe_float(llm_out.get("confidence")),
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
            self._ingest_trade_bar(record)

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
        session = WsSession()
        self._ws_clients.add(ws)
        self._ws_sessions[ws] = session
        _logger.info("WebSocket client connected (%d total)", len(self._ws_clients))
        try:
            state = self._build_state(session.topics)
            await ws.send_json({"type": "state", "data": build_payload(session, state, self._heavy_cache_time, time.time())})
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except (TypeError, ValueError):
                    continue
                mtype = data.get("type") if isinstance(data, dict) else None
                if mtype == "subscribe":
                    session.set_topics(data.get("topics"), reset=bool(data.get("reset")))
                elif mtype == "resync":
                    session.reset()
        except Exception as ws_err:
            _logger.error("WebSocket handler error: %s: %s", type(ws_err).__name__, ws_err)
        finally:
            self._ws_clients.discard(ws)
            self._ws_sessions.pop(ws, None)
            _logger.info("WebSocket client disconnected (%d remaining)", len(self._ws_clients))
        return ws

    async def _ws_broadcast_str(self, payload: str) -> None:
        dead: set[web.WebSocketResponse] = set()
        # send_str 可能挂起，期间连接的增删会改变集合；遍历快照避免 "Set changed size during iteration"
        for ws in list(self._ws_clients):
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
                    union: set[str] = set()
                    for sess in self._ws_sessions.values():
                        union |= sess.topics
                    state = self._build_state(union or set(WS_TOPICS))
                    heavy_version = self._heavy_cache_time
                    now_ts = time.time()
                    for ws in list(self._ws_clients):
                        sess = self._ws_sessions.get(ws)
                        if sess is None:
                            continue
                        payload = build_payload(sess, state, heavy_version, now_ts)
                        try:
                            await ws.send_str(json.dumps({"type": "state", "data": payload}, ensure_ascii=False))
                        except Exception:
                            self._ws_clients.discard(ws)
                            self._ws_sessions.pop(ws, None)
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
        payload = dict(self._build_state())
        payload.pop("_holdings_fp", None)
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

    def _build_state(self, topics: set[str] | None = None) -> dict:
        """构建看板状态。topics 为 None 时构建全部；否则跳过没有客户端订阅的重量级部分。"""
        need = set(WS_TOPICS) if topics is None else set(topics)
        need_market = "market" in need
        need_social = "social" in need
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
        for symbol, ob in (self.orderbooks.items() if need_market else ()):
            l2 = ob.l2_data(depth=self.l2_depth)
            l2_attr = ob.l2_attribution(depth=self.l2_depth, per_level_orders=self.l2_quote_orders)
            sym_trades = [t for t in list(self.recent_trades)[-120:] if str(t.get("symbol", "")).upper() == symbol][-40:]
            call_preview = ob.compute_call_price(ob.limit_reference_price) if ob.call_mode else None
            cda_by_symbol[symbol] = {
                "last_price": ob.last_price,
                "spread": l2.get("spread"),
                "phase": ob.session_phase,
                "call_auction": call_preview,
                "last_auction": self._last_auction.get(symbol),
                "limit_up": ob.limit_up_price if ob.price_limit_enabled else None,
                "limit_down": ob.limit_down_price if ob.price_limit_enabled else None,
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
        index_series_full: dict = {}
        broad_index_series_full: list[dict] = []
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
            # Frontend always consumes full available history and handles viewport locally
            # (drag-to-history / back-to-today), no lookback tuning required.
            # 指标/拟合度计算用全量序列；推送给看板的是按交易日压缩的序列（每天一行）
            index_series_full = self.index_board.series_snapshot_all()
            index_series = self.index_board.series_snapshot_daily()
            broad_index_series_full = self.index_board.broad_index_series_all()
            broad_index_series = self.index_board.broad_index_series_daily()
            broad_val = self.index_board.broad_index_value
            if index_snapshot:
                pct_vals = [float(r.get("pct_chg", 0.0) or 0.0) for r in index_snapshot]
                up_count = sum(1 for v in pct_vals if v > 0)
                down_count = sum(1 for v in pct_vals if v < 0)
                flat_count = len(pct_vals) - up_count - down_count
                total_volume = sum(float(r.get("volume", 0.0) or 0.0) for r in index_snapshot)
                broad_pct = None
                if broad_index_series_full and len(broad_index_series_full) >= 2:
                    broad_pct = broad_index_series_full[-1].get("pct_chg")
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

        indicators = self._compute_indicators(index_series_full) if need_market else {}
        realtime_curve_metrics = self._compute_curve_realtime_metrics(index_series_full, trading_day)

        social_graph_stats: dict = heavy.get("social_graph") or {}

        sim_cfg = getattr(self.agent_manager, "sim_config", {}) or {}
        session = {
            "phase": self.orderbook.session_phase,
            "open_call_seconds": float(sim_cfg.get("call_auction_open_seconds", 0) or 0),
            "close_call_seconds": float(sim_cfg.get("call_auction_close_seconds", 0) or 0),
            "auctions": list(self._auction_history)[-40:] if need_market else [],
        }

        return {
            "server_time": now_ts,
            "sim_time": sim_time,
            "trading_day": trading_day,
            "trading_day_seconds": self.trading_day_seconds,
            "session": session,
            "metrics": {
                "window_seconds": recent_window_seconds,
                "total_agents": len(self.agent_manager.agents),
                "unique_decision_agents_10s": len(decision_agent_ids_10s),
                "unique_order_agents_10s": len(order_agent_ids_10s),
                "completed_trade_agents": completed_trade_agents,
                "completed_decision_agents": completed_decision_agents,
                "thinking_count": len(self.thinking_agents),
                "broad_market": broad_market,
                **realtime_curve_metrics,
            },
            "index_snapshot": index_snapshot,
            "index_series": index_series,
            "broad_index_series": broad_index_series,
            "daily_bars": self.index_board.daily_bars_all() if (self.index_board is not None and need_market) else {},
            "intraday_bars": {k: list(v) for k, v in self._intraday_bars.items()} if need_market else {},
            "intraday_bar_seconds": self._intraday_bar_seconds,
            "sim_start_date": str(getattr(self.index_board, "_start_date", "") or "") if self.index_board is not None else "",
            "real_index_series": self._real_index_series,
            "real_curve_calendar": self._real_curve_calendar,
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
            "_holdings_fp": heavy.get("holdings_fp") or {},
            "leaderboard": heavy.get("leaderboard") or {},
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

    def _build_social_graph_stats(self) -> dict:
        """社交网络统计与力导向图节点/边（随重量级缓存每 ~5 秒计算一次）。"""
        graph = getattr(self.agent_manager.social_board, "social_graph", None)
        if graph is None:
            return {}
        profiles = list(graph._profiles.values())
        total_follows = sum(p.following_count for p in profiles)
        kol_list = sorted(
            [p for p in profiles if p.is_kol],
            key=lambda p: p.follower_count,
            reverse=True,
        )
        graph_top_n = self._social_graph_top_n
        rep_tracker = self.agent_manager.social_board.reputation_tracker
        def _rep_of(aid: int) -> float:
            return float(rep_tracker.get_reputation(aid)) if rep_tracker is not None else 0.0
        top_by_followers = sorted(profiles, key=lambda p: p.follower_count, reverse=True)[:graph_top_n]
        top_nodes = sorted(profiles, key=lambda p: _rep_of(p.agent_id), reverse=True)[:graph_top_n]
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
                "reputation": round(_rep_of(p.agent_id), 3),
                "is_kol": p.is_kol,
            }
            for p in top_nodes
        ]
        social_graph_stats = {
            "total_agents": len(profiles),
            "total_follows": total_follows,
            "avg_following": round(total_follows / max(1, len(profiles)), 1),
            "kol_count": len(kol_list),
            "kol_reputation_threshold": graph._kol_reputation_threshold,
            "kol_reputation_loss_threshold": graph._kol_reputation_loss_threshold,
            # 兼容键：旧前端读取 kol_threshold，现统一指向声誉阈值
            "kol_threshold": graph._kol_reputation_threshold,
            "kol_agents": [
                {
                    "agent_id": p.agent_id,
                    "followers": p.follower_count,
                    "following": p.following_count,
                    "reputation": round(_rep_of(p.agent_id), 3),
                }
                for p in kol_list[:graph_top_n]
            ],
            "top_by_followers": [
                {
                    "agent_id": p.agent_id,
                    "followers": p.follower_count,
                    "following": p.following_count,
                    "reputation": round(_rep_of(p.agent_id), 3),
                    "is_kol": p.is_kol,
                }
                for p in top_by_followers
            ],
            "graph_nodes": graph_nodes,
            "graph_edges": graph_edges,
        }
        return social_graph_stats

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
            # 看板展示全局热榜，而不是以做市商（agent 0）关注关系个性化排序的结果
            dual = {"hot": sb.get_global_hot(top_k=20), "latest": sb.get_latest_feed(top_k=20)}
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

        # 排行榜由服务端计算，行情工作区不必为它拉取全部持仓
        leaderboard: dict = {"total": len(holdings), "by_key": {}}
        for key in ("return_pct", "wealth", "total_pnl", "trade_count"):
            ranked = sorted(holdings, key=lambda h: float(h.get(key, 0) or 0), reverse=True)
            slim = lambda h, k=key: {"agent_id": h["agent_id"], "tom_level": h["tom_level"], "value": h.get(k, 0)}
            leaderboard["by_key"][key] = {
                "top": [slim(h) for h in ranked[:10]],
                "bottom": [slim(h) for h in ranked[-10:][::-1]] if len(ranked) > 10 else [],
            }

        self._heavy_cache = {
            "holdings": holdings,
            "holdings_fp": holdings_fingerprints(holdings),
            "leaderboard": leaderboard,
            "completed_trade_agents": completed_trade_agents,
            "completed_decision_agents": completed_decision_agents,
            "tom_summary": tom_summary,
            "social_hot": social_hot,
            "social_latest": social_latest,
            "social_news": social_news,
            "social_graph": self._build_social_graph_stats(),
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

