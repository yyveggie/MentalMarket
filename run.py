#!/usr/bin/env python3
"""
MentalMarket 主入口：启动连续双向拍卖仿真。
1000 个 LLM Agent 基于 ToM 认知金字塔进行交易博弈。

用法:
  python run.py                    # 使用默认配置
  python run.py --config my.yaml   # 自定义配置
  python run.py --agents 100       # 快速测试（100个Agent）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import subprocess
import time
from pathlib import Path

import yaml

from app.domain.agent import AgentManager
from app.infrastructure.api_balancer import build_balancer_from_config
from app.infrastructure.data_logger import DataLogger
from app.simulation.engine import SimulationEngine
from app.domain.orderbook import OrderBook, Side
from app.domain.index_board import IndexBoard
from app.dashboard.server import RealtimeDashboard
from prompts import build_system_templates
from app.domain.social_board import SocialBoard
from app.domain.social_graph import SocialGraph
from app.domain.reputation import ReputationTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MentalMarket")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def seed_orderbook(
    orderbook: OrderBook,
    initial_price: float,
    n_levels: int = 10,
    spread_pct: float = 0.002,
    seed_max_qty: int = 50,
    seed_min_qty: int = 10,
    qty_decay: int = 4,
    estimated_total_position: int = 0,
    seed_absorption_pct: float = 0.15,
):
    """
    播种初始订单簿，在初始价格两侧挂上流动性。

    当提供 estimated_total_position 时，自动放大 seed 深度，
    确保买盘能吸收至少 seed_absorption_pct 比例的 Agent 总持仓抛压，
    避免开盘首日因流动性真空导致价格单边下跌。
    """
    if estimated_total_position > 0 and seed_absorption_pct > 0:
        target_bid_depth = int(estimated_total_position * seed_absorption_pct)
        baseline_total = sum(max(seed_min_qty, seed_max_qty - i * qty_decay) for i in range(n_levels))
        if baseline_total < target_bid_depth:
            scale = target_bid_depth / max(1, baseline_total)
            seed_max_qty = max(seed_max_qty, int(seed_max_qty * scale))
            seed_min_qty = max(seed_min_qty, int(seed_min_qty * scale))
            qty_decay = max(1, int(qty_decay * scale))

    anchor_qty = seed_max_qty * 3
    anchor_order, anchor_trades = orderbook.submit_order(agent_id=0, side=Side.BID, price=initial_price, quantity=anchor_qty)
    if not anchor_trades and orderbook.last_price is None:
        orderbook._last_trade_price = initial_price

    spread = initial_price * spread_pct
    for i in range(n_levels):
        bid_price = round(initial_price - spread * (i + 1), 2)
        ask_price = round(initial_price + spread * (i + 1), 2)
        qty = max(seed_min_qty, seed_max_qty - i * qty_decay)
        orderbook.submit_order(agent_id=0, side=Side.BID, price=bid_price, quantity=qty)
        orderbook.submit_order(agent_id=0, side=Side.ASK, price=ask_price, quantity=qty)


def _kill_listeners_on_port(port: int) -> None:
    """启动前清理占用 dashboard 端口的旧进程。"""
    import shutil
    if shutil.which("lsof") is None:
        return
    cmd = ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"]

    def _query_listeners() -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    proc = _query_listeners()
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"failed to query port listeners via lsof (code={proc.returncode}): {proc.stderr.strip()}")

    current_pid = os.getpid()
    pids: list[int] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        pid = int(line)
        if pid != current_pid:
            pids.append(pid)

    if not pids:
        return

    logger.warning("Port %d already in use, terminating existing listeners: %s", int(port), pids)
    for pid in pids:
        os.kill(pid, signal.SIGTERM)

    deadline = time.time() + 3.0
    alive = set(pids)
    while alive and time.time() < deadline:
        for pid in list(alive):
            try:
                os.kill(pid, 0)
            except OSError:
                alive.discard(pid)
        if alive:
            time.sleep(0.1)

    for pid in list(alive):
        logger.warning("PID %d did not exit after SIGTERM, sending SIGKILL", pid)
        os.kill(pid, signal.SIGKILL)

    # macOS 上偶发：进程已退出，但端口释放有短延迟；在绑定前再确认一次。
    release_deadline = time.time() + 2.0
    while time.time() < release_deadline:
        p = _query_listeners()
        if p.returncode == 1 or not (p.stdout or "").strip():
            return
        time.sleep(0.1)

    p = _query_listeners()
    if p.returncode == 0 and (p.stdout or "").strip():
        residual = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
        logger.warning("Port %d still reports listeners right before bind: %s", int(port), residual)


async def main():
    parser = argparse.ArgumentParser(description="MentalMarket: ToM-based CDA Simulation")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径（resume 时显式指定可覆盖 run 目录配置）")
    parser.add_argument("--agents", type=int, default=None, help="覆盖Agent数量（快速测试用）")
    parser.add_argument("--time", type=float, default=None, help="覆盖仿真时长（秒）")
    parser.add_argument("--resume", default=None, help="从指定 run 目录的 checkpoint.pkl 恢复（如: runs/20260314_123456）")
    args = parser.parse_args()

    # 加载配置
    # 断点续跑时：
    #   - 默认使用 run 目录下保存的 config.yaml（保持原实验配置不变）
    #   - 若显式指定了 --config（非默认值），则优先使用指定的配置文件
    user_specified_config = args.config != parser.get_default("config")
    if args.resume:
        if user_specified_config:
            config_path = Path(args.config)
            logger.info("Resume mode: using explicitly specified config: %s (overrides run directory config)", config_path)
        else:
            resume_config_path = Path(args.resume) / "config.yaml"
            if resume_config_path.exists():
                config_path = resume_config_path
                logger.info("Resume mode: loading config from run directory: %s", config_path)
            else:
                config_path = Path(args.config)
                logger.warning("Resume mode: run directory config not found (%s), falling back to %s", resume_config_path, config_path)
    else:
        config_path = Path(args.config)

    if config_path.exists():
        config = load_config(str(config_path))
    else:
        logger.warning("Config file %s not found, using defaults", config_path)
        config = {}

    sim_cfg = config.get("simulation", {})
    api_cfg = config.get("api", {})
    agent_cfg = config.get("agent", {})
    evo_cfg = config.get("evolution", {})
    social_cfg = config.get("social", {})
    ob_cfg = config.get("orderbook", {})
    indices_cfg = config.get("market_indices", {})
    news_events_cfg = config.get("news_events_config", {})
    dashboard_cfg = dict(config.get("dashboard", {}))
    dashboard_cfg.setdefault(
        "metrics_include_closed_days",
        bool(news_events_cfg.get("reopen_include_closed_days", False)),
    )
    dashboard_cfg.setdefault(
        "experimental_daily_title_mode",
        bool(news_events_cfg.get("experimental_daily_title_mode", False)),
    )
    prompt_cfg = config.get("prompt", {})
    evolution_enabled = bool(evo_cfg.get("enabled", False))
    dashboard_enabled = bool(dashboard_cfg.get("enabled", True))

    n_agents = args.agents or sim_cfg.get("n_agents", 1000)
    max_time = args.time or sim_cfg.get("max_sim_time", 3600)

    # 将命令行覆盖值回写到 config 字典，确保 save_config 持久化的是实际运行参数
    if args.agents:
        sim_cfg["n_agents"] = n_agents
    if args.time:
        sim_cfg["max_sim_time"] = max_time
    initial_price = sim_cfg.get("initial_price", 100.0)
    batch_size = sim_cfg.get("batch_size", 50)
    snapshot_interval = sim_cfg.get("snapshot_interval", 60)
    event_window = sim_cfg.get("event_window", 0.5)
    l2_depth = sim_cfg.get("l2_depth", 5)
    l2_history_max = sim_cfg.get("l2_history_max", 5000)
    fee_rate = sim_cfg.get("fee_rate", 0.0002)
    random_seed = sim_cfg.get("random_seed")
    delay_model_by_tom = sim_cfg.get("delay_model_by_tom", {})
    tom_dist = sim_cfg.get("tom_distribution", {0: 0.6, 1: 0.3, 2: 0.1})
    # YAML 可能将 key 读为 int 或 str，统一转 int
    tom_dist = {int(k): v for k, v in tom_dist.items()}

    if random_seed is not None:
        random.seed(int(random_seed))
        logger.info("Deterministic mode enabled with random_seed=%s", random_seed)

    # 初始化组件
    # 初始化社交图谱和声誉追踪器（可选）
    graph_enabled = bool(social_cfg.get("graph_enabled", False))
    reputation_enabled = bool(social_cfg.get("reputation_enabled", False))
    social_graph = SocialGraph() if graph_enabled else None
    reputation_tracker = ReputationTracker(
        eval_delay=float(social_cfg.get("reputation_eval_delay", 3600)),
        window_size=int(social_cfg.get("reputation_window", 20)),
        initial_reputation=float(social_cfg.get("reputation_initial", 1.0)),
        neutral_threshold=float(social_cfg.get("reputation_neutral_threshold", 0.2)),
        min_window=int(social_cfg.get("reputation_min_window", 3)),
        max_pending=int(social_cfg.get("reputation_max_pending", 50000)),
        correct_weight=float(social_cfg.get("reputation_correct_weight", 0.3)),
        wrong_weight=float(social_cfg.get("reputation_wrong_weight", 0.3)),
        like_weight=float(social_cfg.get("reputation_like_weight", 0.05)),
        dislike_weight=float(social_cfg.get("reputation_dislike_weight", 0.05)),
        retweet_weight=float(social_cfg.get("reputation_retweet_weight", 0.1)),
        decay_rate=float(social_cfg.get("reputation_decay_rate", 0.97)),
    ) if reputation_enabled else None
    social_board = SocialBoard(
        max_posts=int(social_cfg.get("max_posts", 5000)),
        social_graph=social_graph,
        reputation_tracker=reputation_tracker,
        social_config=social_cfg,
    )
    api_balancer = build_balancer_from_config(api_cfg)
    index_board = None
    if bool(indices_cfg.get("enabled", True)):
        profile_csv = str(indices_cfg.get("profile_csv", "data/stock_profile.csv"))
        quotes_csv = str(indices_cfg.get("quotes_csv", "data/stock_data.csv"))
        recent_days = int(indices_cfg.get("recent_days", 10))
        baseline_flat_days = int(indices_cfg.get("baseline_flat_days", 0))
        quotes_maxlen = int(indices_cfg.get("quotes_maxlen", 2000))
        start_date = str(indices_cfg.get("start_date", ""))
        est_daily_turnover = float(indices_cfg.get("estimated_daily_turnover", 0.0))
        if est_daily_turnover <= 0:
            avg_stock_ratio_for_vol = (float(agent_cfg.get("stock_ratio_min", 0.3)) + float(agent_cfg.get("stock_ratio_max", 0.7))) / 2.0
            if str(agent_cfg.get("cash_mode", "power_law")) == "equal":
                est_cash_for_vol = float(agent_cfg.get("cash_equal_amount", 100000))
            else:
                est_cash_for_vol = (float(agent_cfg.get("cash_min", 5000)) + float(agent_cfg.get("cash_max", 500000))) / 3.0
            est_daily_turnover_rate = 0.03
            n_symbols_est = max(1, len(indices_cfg.get("symbols", [])) or 10)
            est_daily_turnover = n_agents * est_cash_for_vol * avg_stock_ratio_for_vol * est_daily_turnover_rate / n_symbols_est
        index_board = IndexBoard(
            profile_csv,
            quotes_csv,
            recent_days=recent_days,
            baseline_flat_days=baseline_flat_days,
            quotes_maxlen=quotes_maxlen,
            start_date=start_date,
            trading_day_seconds=float(snapshot_interval),
            estimated_daily_turnover_per_symbol=est_daily_turnover,
        )
        logger.info("IndexBoard loaded: %d symbols, recent_days=%d, baseline_flat_days=%d", len(index_board.symbols), recent_days, baseline_flat_days)

    # 初始化推理存储
    storage_cfg = config.get("storage", {})
    resume_run_id = None
    if args.resume:
        resume_path = Path(args.resume)
        if resume_path.exists():
            resume_run_id = resume_path.name
    data_logger = DataLogger(
        base_dir=storage_cfg.get("base_dir", "runs"),
        buffer_size=storage_cfg.get("buffer_size", 100),
        run_id=resume_run_id,
        store_prompt=bool(storage_cfg.get("store_prompt", True)),
    )
    data_logger._snapshot_interval = float(snapshot_interval)
    data_logger.save_config(config)

    dashboard: RealtimeDashboard | None = None

    logger.info("=" * 60)
    logger.info("MentalMarket — Cognitive Hierarchy CDA Simulation")
    logger.info("=" * 60)
    logger.info("Agents: %d  |  SimTime: %.0fs  |  BatchSize: %d", n_agents, max_time, batch_size)
    logger.info("ToM Distribution: %s", tom_dist)
    logger.info("API Providers: %s", list(api_balancer.providers.keys()))
    logger.info("Storage: %s", data_logger.run_dir)
    logger.info("=" * 60)

    # 初始化 API 客户端
    await api_balancer.init()

    # 设置按 ToM 分层的系统 prompt 缓存
    api_balancer.set_system_cache(build_system_templates())

    # 创建多标的订单簿
    configured_symbol = str(sim_cfg.get("symbol", "MentalMarket")).upper()
    if index_board is not None and index_board.symbols:
        tradable_symbols = {str(s).upper() for s in index_board.symbols}
        if configured_symbol not in tradable_symbols:
            configured_symbol = sorted(tradable_symbols)[0]
    else:
        tradable_symbols = {configured_symbol}

    # 实时模式：用 realtime.symbols 替换 tradable_symbols，为实时标的创建 OrderBook
    _rt_cfg_early = config.get("realtime", {})
    _rt_real_prices: dict[str, float] = {}
    _rt_symbol_names: dict[str, str] = {}
    if bool(_rt_cfg_early.get("enabled", False)):
        _rt_syms = [str(s).upper() for s in _rt_cfg_early.get("symbols", [])]
        if _rt_syms:
            tradable_symbols = set(_rt_syms)
            configured_symbol = sorted(tradable_symbols)[0]
            # 启动时拉取真实价格和名称，用于播种 OrderBook & 行情表
            try:
                import akshare as ak
                for _sym in _rt_syms:
                    _df = ak.stock_individual_spot_xq(symbol=_sym)
                    if _df is not None and not _df.empty:
                        _row_map = {}
                        for _, _row in _df.iterrows():
                            _row_map[str(_row.iloc[0]).strip()] = _row.iloc[1]
                        _px = float(_row_map.get("现价", 0))
                        if _px > 0:
                            _rt_real_prices[_sym] = _px
                        _name = str(_row_map.get("股票名称", ""))
                        if _name:
                            _rt_symbol_names[_sym] = _name
                logger.info("Realtime mode: fetched real prices %s, names %s", _rt_real_prices, _rt_symbol_names)
            except Exception as _e:
                logger.warning("Realtime mode: failed to fetch real prices, using initial_price: %s", _e)
            logger.info("Realtime mode: tradable_symbols overridden to %s", sorted(tradable_symbols))

    sim_cfg["symbol"] = configured_symbol
    sim_cfg["_ob_cfg"] = ob_cfg
    latest_close_map = index_board.latest_close_map() if index_board is not None else {}
    # 实时模式：用真实价格覆盖 latest_close_map
    if _rt_real_prices:
        latest_close_map.update(_rt_real_prices)
    # 预估 Agent 每标的平均持仓量，用于自动缩放 seed 深度
    avg_stock_ratio = (float(agent_cfg.get("stock_ratio_min", 0.3)) + float(agent_cfg.get("stock_ratio_max", 0.7))) / 2.0
    if str(agent_cfg.get("cash_mode", "power_law")) == "equal":
        est_avg_cash = float(agent_cfg.get("cash_equal_amount", 100000))
    else:
        est_avg_cash = (float(agent_cfg.get("cash_min", 5000)) + float(agent_cfg.get("cash_max", 500000))) / 3.0
    n_tradable = max(1, len(tradable_symbols))
    seed_absorption_pct = float(ob_cfg.get("seed_absorption_pct", 0.15))
    orderbooks: dict[str, OrderBook] = {}
    for symbol in sorted(tradable_symbols):
        ref_price_raw = latest_close_map.get(symbol)
        ref_price = float(ref_price_raw if ref_price_raw is not None else initial_price)
        ob = OrderBook(
            max_trade_log=int(ob_cfg.get("max_trade_log", 200000)),
            tick_size=float(ob_cfg.get("tick_size", 0.01)),
            lot_size=int(ob_cfg.get("lot_size", 1)),
            price_limit_pct=float(ob_cfg.get("price_limit_pct", 0.10)),
            limit_reference_price=ref_price,
        )
        ob.order_ttl = float(ob_cfg.get("order_ttl", 0))
        est_position = int(n_agents * est_avg_cash * avg_stock_ratio / n_tradable / max(0.01, ref_price)) if ref_price > 0 else 0
        seed_orderbook(
            ob,
            ref_price,
            n_levels=ob_cfg.get("seed_levels", 10),
            spread_pct=ob_cfg.get("seed_spread_pct", 0.002),
            seed_max_qty=ob_cfg.get("seed_max_qty", 50),
            seed_min_qty=ob_cfg.get("seed_min_qty", 10),
            qty_decay=ob_cfg.get("seed_qty_decay", 4),
            estimated_total_position=est_position,
            seed_absorption_pct=seed_absorption_pct,
        )
        orderbooks[symbol] = ob
    logger.info("OrderBooks seeded for %d symbols (absorption_pct=%.0f%%)", len(orderbooks), seed_absorption_pct * 100)

    # 初始化 Agent
    evolution_cfg_for_agent = evo_cfg if evolution_enabled else {}
    agent_mgr = AgentManager(
        orderbooks,
        social_board,
        api_balancer,
        data_logger=data_logger,
        fee_rate=fee_rate,
        initial_price=initial_price,
        agent_config=agent_cfg,
        social_config=social_cfg,
        evolution_config=evolution_cfg_for_agent,
        sim_config=sim_cfg,
        index_board=index_board,
        prompt_config=prompt_cfg,
    )

    # 实时模式：清空预计算持仓，注入股票名称映射
    _rt_cfg = config.get("realtime", {})
    if bool(_rt_cfg.get("enabled", False)):
        agent_mgr._precomputed_holdings = {}
        if _rt_symbol_names:
            agent_mgr._rt_symbol_names = _rt_symbol_names

    agent_mgr.init_agents(n_agents=n_agents, tom_distribution=tom_dist, initial_price=initial_price)

    # 初始化社交图谱（在 Agent 初始化之后）
    if social_graph is not None:
        tom_levels = {aid: a.tom_level for aid, a in agent_mgr.agents.items()}
        # 先绑定声誉追踪器，保证 init_agents 内部触发的 KOL 复核能读到正确声誉
        social_graph.set_reputation_tracker(reputation_tracker)
        social_graph.init_agents(
            agent_ids=list(agent_mgr.agents.keys()),
            tom_levels=tom_levels,
            kol_reputation_threshold=float(social_cfg.get("kol_reputation_threshold", 5.0)),
            kol_reputation_loss_threshold=float(social_cfg.get("kol_reputation_loss_threshold", 3.0)),
            follow_random_min=int(social_cfg.get("follow_random_min", 3)),
            follow_random_max=int(social_cfg.get("follow_random_max", 5)),
        )
        def _on_social_graph_event(evt: dict):
            data_logger.log_social_graph_event(evt)
        social_graph.set_event_callback(_on_social_graph_event)

    if reputation_tracker is not None:
        def _on_reputation_event(evt: dict):
            data_logger.log_reputation_history(evt)
        reputation_tracker.set_event_callback(_on_reputation_event)

    # 记录 Agent 初始状态
    data_logger.log_agents_init_batch(agent_mgr.agents)

    # 创建仿真引擎
    if dashboard_enabled:
        _kill_listeners_on_port(int(dashboard_cfg.get("port", 8765)))
        dashboard = RealtimeDashboard(
            agent_manager=agent_mgr,
            orderbook=orderbooks,
            index_board=index_board,
            data_logger=data_logger,
            host=str(dashboard_cfg.get("host", "127.0.0.1")),
            port=int(dashboard_cfg.get("port", 8765)),
            l2_depth=int(dashboard_cfg.get("l2_depth", l2_depth)),
            l2_quote_orders=int(dashboard_cfg.get("l2_quote_orders", 6)),
            trading_day_seconds=float(dashboard_cfg.get("trading_day_seconds", snapshot_interval)),
            max_recent_events=int(dashboard_cfg.get("max_recent_events", 200)),
            dashboard_config=dashboard_cfg,
        )
        await dashboard.start()
        logger.info("Realtime dashboard at http://%s:%d", dashboard.host, dashboard.port)

    # 实时模式：计算节拍数（sim_seconds / real_second）
    _rt_pacing = 0.0
    _rt_cfg_pacing = config.get("realtime", {})
    if bool(_rt_cfg_pacing.get("enabled", False)):
        _rt_pacing = float(_rt_cfg_pacing.get("pacing", 60.0))  # 默认 60 sim秒/真实秒

    engine = SimulationEngine(
        agent_manager=agent_mgr,
        max_sim_time=max_time,
        batch_size=batch_size,
        snapshot_interval=snapshot_interval,
        event_window=event_window,
        l2_depth=l2_depth,
        l2_history_max=l2_history_max,
        delay_model_by_tom=delay_model_by_tom,
        monitor=dashboard,
        evolution_enabled=evolution_enabled,
        evolution_interval=evo_cfg.get("interval", 600) if evolution_enabled else 600,
        evolution_win_rate_threshold=evo_cfg.get("win_rate_threshold", -0.05) if evolution_enabled else -0.05,
        evolution_consecutive_rounds=evo_cfg.get("consecutive_rounds", 3) if evolution_enabled else 3,
        evolution_max_upgrade_per_round=evo_cfg.get("max_upgrade_per_round", 50) if evolution_enabled else 50,
        realtime_pacing=_rt_pacing,
    )
    engine._checkpoint_interval = float(storage_cfg.get("checkpoint_interval", snapshot_interval))
    engine._ckpt_l2_keep = int(storage_cfg.get("checkpoint_l2_keep", 200))
    engine._ckpt_price_keep = int(storage_cfg.get("checkpoint_price_keep", 5000))
    engine._ckpt_snapshot_keep = int(storage_cfg.get("checkpoint_snapshot_keep", 20))
    engine._ckpt_trade_log_limit = int(storage_cfg.get("checkpoint_trade_log_limit", 2000))

    # 实时模式：设置心跳间隔（等于 polling_interval），确保引擎定期唤醒处理实时数据
    if _rt_pacing > 0:
        _rt_heartbeat = float(_rt_cfg_pacing.get("polling_interval", 60))
        engine._realtime_heartbeat_interval = _rt_heartbeat
        _rt_decision_interval = float(_rt_cfg_pacing.get("decision_interval", 0))
        engine._realtime_decision_interval = _rt_decision_interval
        if _rt_decision_interval > 0:
            logger.info("Realtime round mode: decision_interval=%.0fs, heartbeat=%.0fs",
                         _rt_decision_interval, _rt_heartbeat)
        else:
            logger.info("Realtime Poisson mode: heartbeat interval=%.0fs (sim-time, = %.1f real seconds)",
                         _rt_heartbeat, _rt_heartbeat / _rt_pacing)

    # 安排新闻事件（默认模式：按指数随机抽样；实验模式：按日全量标题推送）
    if bool(news_events_cfg.get("enabled", True)):
        experimental_daily_title_mode = bool(news_events_cfg.get("experimental_daily_title_mode", False))
        news_file_key = "experimental_news_file" if experimental_daily_title_mode else "news_file"
        default_news_file = "data/news2.json" if experimental_daily_title_mode else "data/news.json"
        news_file = Path(str(news_events_cfg.get(news_file_key, default_news_file)))
        if news_file.exists():
            with open(news_file, "r", encoding="utf-8") as nf:
                news_data = json.load(nf)
            news_day_offset_pct = float(news_events_cfg.get("news_day_offset_pct", 0.25))

            by_day: dict[int, list[dict]] = {}
            for item in news_data.get("news", []):
                day = int(item.get("day", 0))
                if day < 1:
                    continue
                by_day.setdefault(day, []).append(item)

            news_count = 0
            if experimental_daily_title_mode:
                monday_include_weekend = bool(news_events_cfg.get("monday_include_weekend", True))
                reopen_include_closed_days = bool(news_events_cfg.get("reopen_include_closed_days", True))

                def _day_meta(items: list[dict]) -> dict[str, str]:
                    for it in items:
                        d = str(it.get("date", "")).strip()
                        w = str(it.get("weekday", "")).strip()
                        m = str(it.get("market_status", "")).strip()
                        if d or w or m:
                            return {"date": d, "weekday": w, "market_status": m}
                    return {"date": "", "weekday": "", "market_status": ""}

                day_meta: dict[int, dict[str, str]] = {d: _day_meta(items) for d, items in by_day.items()}

                for day in sorted(by_day.keys()):
                    sim_time = (day - 1) * snapshot_interval + snapshot_interval * news_day_offset_pct
                    if sim_time >= max_time:
                        break

                    today_meta = day_meta.get(day, {"date": "", "weekday": "", "market_status": ""})
                    include_days = [day]
                    today_status = str(today_meta.get("market_status", ""))

                    # 复市日（含春节/元旦后开市）自动合并前序连续休市日的新闻。
                    if reopen_include_closed_days and today_status == "开市":
                        prev_day = day - 1
                        while prev_day in by_day:
                            prev_status = str(day_meta.get(prev_day, {}).get("market_status", ""))
                            if not prev_status.startswith("休市"):
                                break
                            include_days.insert(0, prev_day)
                            prev_day -= 1
                    # 回退兼容：若无 market_status 但周几可用，周一仍回捞周末。
                    elif monday_include_weekend and today_meta.get("weekday") == "周一":
                        for prev_day in (day - 2, day - 1):
                            if prev_day in by_day:
                                include_days.insert(0, prev_day)

                    today_head_parts = [
                        f"【今日日期】{today_meta.get('date', '')}".strip(),
                        today_meta.get("weekday", ""),
                        today_meta.get("market_status", ""),
                    ]
                    today_head = " ".join([p for p in today_head_parts if p]).strip()

                    seq = 0
                    for src_day in include_days:
                        src_meta = day_meta.get(src_day, {"date": "", "weekday": "", "market_status": ""})
                        src_parts = [
                            src_meta.get("date", "") or f"day={src_day}",
                            src_meta.get("weekday", ""),
                            src_meta.get("market_status", ""),
                        ]
                        src_day_label = " ".join([p for p in src_parts if p]).strip()

                        titles: list[str] = []
                        for it in by_day.get(src_day, []):
                            title = str(it.get("title", "")).strip()
                            if title:
                                titles.append(f"• {title}")

                        if not titles:
                            continue

                        lines = [today_head, "【新闻标题】"]
                        if src_day == day:
                            lines.append("这一天发生以下新闻：")
                        else:
                            lines.append(f"[发生日] {src_day_label}")
                            lines.append("这一天发生以下新闻：")
                        lines.extend(titles)

                        news_text = "\n".join([ln for ln in lines if ln])
                        engine.schedule_news(time=sim_time + seq * 1e-3, content=news_text, symbol="")
                        seq += 1
                        news_count += len(titles)

                logger.info(
                    "Loaded %d titles (grouped by day) from %s (experimental_daily_title_mode=%s, reopen_include_closed_days=%s, monday_include_weekend=%s)",
                    news_count,
                    news_file,
                    experimental_daily_title_mode,
                    reopen_include_closed_days,
                    monday_include_weekend,
                )
            else:
                news_per_day = int(news_events_cfg.get("news_per_day", 4))
                coverage_cycle = int(news_events_cfg.get("coverage_cycle", 3))

                recent_indices: list[set[str]] = []
                for day in sorted(by_day.keys()):
                    sim_time = (day - 1) * snapshot_interval + snapshot_interval * news_day_offset_pct
                    if sim_time >= max_time:
                        break

                    pool = by_day[day]
                    by_index: dict[str, list[dict]] = {}
                    for item in pool:
                        idx = item.get("primary", [""])[0] if item.get("primary") else ""
                        by_index.setdefault(idx, []).append(item)

                    covered_recently = set()
                    for s in recent_indices[-(coverage_cycle - 1):]:
                        covered_recently |= s

                    uncovered = [idx for idx in by_index if idx and idx not in covered_recently]
                    random.shuffle(uncovered)
                    covered_today = [idx for idx in by_index if idx and idx in covered_recently]
                    random.shuffle(covered_today)
                    priority_order = uncovered + covered_today

                    selected: list[dict] = []
                    used_indices: set[str] = set()
                    for idx in priority_order:
                        if len(selected) >= news_per_day:
                            break
                        if idx in used_indices:
                            continue
                        candidates = by_index[idx]
                        selected.append(random.choice(candidates))
                        used_indices.add(idx)

                    if len(selected) < news_per_day:
                        remaining = [it for it in pool if it not in selected]
                        random.shuffle(remaining)
                        for it in remaining:
                            if len(selected) >= news_per_day:
                                break
                            idx = it.get("primary", [""])[0] if it.get("primary") else ""
                            if idx not in used_indices:
                                selected.append(it)
                                used_indices.add(idx)

                    recent_indices.append(used_indices)
                    for item in selected:
                        primary_symbols = item.get("primary", [])
                        news_symbol = str(primary_symbols[0]) if primary_symbols else ""
                        engine.schedule_news(time=sim_time, content=item["title"], symbol=news_symbol)
                        news_count += 1

                logger.info(
                    "Loaded %d news events from %s (%d per day, coverage cycle=%d)",
                    news_count,
                    news_file,
                    news_per_day,
                    coverage_cycle,
                )

    # 断点续跑：从 checkpoint 恢复
    if args.resume:
        ckpt_path = Path(args.resume) / "checkpoint.pkl"
        if ckpt_path.exists():
            engine.restore_checkpoint(str(ckpt_path))
            logger.info("Resumed from checkpoint: %s", ckpt_path)
            if dashboard is not None:
                dashboard.replay_historical_records(Path(args.resume))
        else:
            logger.warning("Checkpoint not found: %s, starting fresh", ckpt_path)

    # 注册信号处理：Ctrl+C / SIGTERM 时优雅退出并保存 checkpoint
    def _graceful_shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.warning("Received %s, stopping simulation gracefully...", sig_name)
        engine.stop()

    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    # macOS/zsh 下 Ctrl+Z 会触发 SIGTSTP（exit code 常见为 146），
    # 这里改为优雅停机，避免仅挂起进程导致日志缓冲与 checkpoint 未落盘。
    if hasattr(signal, "SIGTSTP"):
        signal.signal(signal.SIGTSTP, _graceful_shutdown)

    # 实时数据拉取协程（仅 realtime.enabled=true 时启动）
    realtime_cfg = config.get("realtime", {})
    realtime_task: asyncio.Task | None = None
    if bool(realtime_cfg.get("enabled", False)):
        from realtime.news_fetcher import SinaRealtimeNews
        from realtime.quote_fetcher import AkshareQuoteFetcher
        from realtime.market_hours import is_market_open, seconds_until_next_open

        rt_interval = int(realtime_cfg.get("polling_interval", 60))
        rt_market_hours_only = bool(realtime_cfg.get("market_hours_only", False))
        rt_news_cfg = realtime_cfg.get("news", {})
        rt_quote_cfg = realtime_cfg.get("quote", {})
        rt_symbols = list(realtime_cfg.get("symbols", []))
        rt_output_cfg = realtime_cfg.get("output", {})
        rt_log_name = str(rt_output_cfg.get("log_file", "realtime_predictions.jsonl"))
        rt_log_path = Path(data_logger.run_dir) / rt_log_name if data_logger else Path(rt_log_name)
        rt_print = bool(rt_output_cfg.get("print_to_console", True))

        rt_news_fetcher = SinaRealtimeNews(
            page_size=int(rt_news_cfg.get("page_size", 20)),
            max_history=int(rt_news_cfg.get("max_history", 100)),
            dedup=bool(rt_news_cfg.get("dedup", True)),
        ) if rt_news_cfg.get("enabled", True) else None

        rt_quote_fetcher = AkshareQuoteFetcher(
            symbols=rt_symbols,
            max_history=int(rt_quote_cfg.get("max_history", 200)),
        ) if rt_quote_cfg.get("enabled", True) else None

        async def _realtime_data_loop():
            """后台协程：定期拉取实时新闻/行情并注入仿真引擎。"""
            # 等待引擎启动（engine.run() 内部设置 _running=True）
            while not engine._running:
                await asyncio.sleep(0.1)

            # 轮次制：数据拉取+决策的间隔取 decision_interval；否则取 polling_interval
            _decision_interval = float(realtime_cfg.get("decision_interval", 0))
            loop_interval = _decision_interval if _decision_interval > 0 else rt_interval

            round_idx = 0
            while engine._running:
                # market_hours_only 模式：盘外休眠等待
                if rt_market_hours_only and not is_market_open():
                    wait_secs = seconds_until_next_open()
                    if wait_secs > 0:
                        import datetime as _dt
                        next_open = _dt.datetime.now() + _dt.timedelta(seconds=wait_secs)
                        logger.info("[实时调度] 当前非交易时段，休眠至 %s（%.0f秒后）",
                                    next_open.strftime("%Y-%m-%d %H:%M:%S"), wait_secs)
                        # 分段休眠，每 60 秒检查一次是否被终止
                        slept = 0.0
                        while slept < wait_secs and engine._running:
                            chunk = min(60.0, wait_secs - slept)
                            await asyncio.sleep(chunk)
                            slept += chunk
                        if not engine._running:
                            break
                        logger.info("[实时调度] 交易时段开始，恢复运行")
                    continue

                round_idx += 1
                new_items: list = []
                quotes: dict = {}
                try:
                    # 拉取新闻（同步 I/O，放入线程池避免阻塞事件循环）
                    if rt_news_fetcher:
                        new_items = await asyncio.to_thread(rt_news_fetcher.fetch)
                        for item in new_items:
                            content = item["content"]
                            engine.schedule_news(
                                time=engine._sim_time + 0.001,
                                content=content,
                                symbol="",
                            )
                        if new_items and rt_print:
                            logger.info("[实时新闻] 第%d轮拉取 %d 条新闻", round_idx, len(new_items))

                    # 拉取行情（同步 I/O，放入线程池避免阻塞事件循环）
                    if rt_quote_fetcher:
                        quotes = await asyncio.to_thread(rt_quote_fetcher.fetch)
                        if quotes and rt_print:
                            quote_text = rt_quote_fetcher.format_quote_text(quotes)
                            logger.info("[实时行情] 第%d轮:\n%s", round_idx, quote_text)

                        # 将实时行情作为新闻注入，让 Agent 能在 prompt 中看到
                        if quotes:
                            quote_summary = rt_quote_fetcher.format_quote_text(quotes)
                            engine.schedule_news(
                                time=engine._sim_time + 0.002,
                                content=f"【实时行情快讯】\n{quote_summary}",
                                symbol="",
                            )

                    # 轮次制模式：数据拉取后立即触发所有 Agent 做决策
                    if _decision_interval > 0:
                        engine.trigger_all_agent_wakeups()

                    # 持久化拉取记录
                    if rt_news_fetcher or rt_quote_fetcher:
                        import json as _json
                        record = {
                            "round": round_idx,
                            "sim_time": round(engine._sim_time, 2),
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "new_news_count": len(new_items) if rt_news_fetcher else 0,
                            "quotes_count": len(quotes) if rt_quote_fetcher else 0,
                        }
                        with open(rt_log_path, "a", encoding="utf-8") as f:
                            f.write(_json.dumps(record, ensure_ascii=False) + "\n")

                except Exception as rt_err:
                    logger.warning("[实时数据] 第%d轮拉取失败: %s", round_idx, rt_err)

                await asyncio.sleep(loop_interval)

        realtime_task = asyncio.create_task(_realtime_data_loop())
        logger.info("实时数据拉取已启动 — 间隔=%ds, 新闻=%s, 行情=%s, 标的=%s",
                     rt_interval,
                     "开启" if rt_news_fetcher else "关闭",
                     "开启" if rt_quote_fetcher else "关闭",
                     rt_symbols)

    # 运行仿真
    results = None
    try:
        results = await engine.run()
    except Exception as sim_err:
        logger.error("Simulation terminated with error: %s: %s", type(sim_err).__name__, sim_err)
        import traceback
        traceback.print_exc()
    finally:
        # 停止实时数据拉取
        if realtime_task is not None and not realtime_task.done():
            realtime_task.cancel()
            try:
                await realtime_task
            except asyncio.CancelledError:
                pass
            logger.info("实时数据拉取已停止")
        # 保存最终 checkpoint
        if data_logger:
            try:
                ckpt_path = str(data_logger.run_dir / "checkpoint.pkl")
                engine.save_checkpoint(ckpt_path)
                logger.info("Final checkpoint saved on exit: %s", ckpt_path)
            except Exception as ckpt_err:
                logger.error("Failed to save final checkpoint: %s", ckpt_err)
        if dashboard is not None:
            await dashboard.stop()
        await api_balancer.close()

    # 记录 Agent 最终状态并关闭存储
    try:
        if results is not None:
            last_prices = results["final_stats"].get("last_prices") or {configured_symbol: initial_price}
        else:
            last_prices = {configured_symbol: initial_price}
        data_logger.log_agents_final_batch(agent_mgr.agents, last_prices)
    except Exception as save_err:
        logger.error("Failed to save agent final states: %s", save_err)
    finally:
        data_logger.close()

    if results is None:
        logger.error("No simulation results available due to earlier error")
        return

    # 输出精简结果到 runs/<run_id>/results.json（去除与 JSONL 重复的详细数据）
    try:
        output_path = data_logger.run_dir / "results.json"
        fs = results["final_stats"]
        serializable = {
            "sim_time": results["sim_time"],
            "total_decisions": results["total_decisions"],
            "total_trades": results["total_trades"],
            "last_prices": fs.get("last_prices", {}),
            "price_history": [
                {"time": t, "price": p} for t, p in results["price_history"]
            ],
            "tom_summary": {
                str(tom): {"count": fs.get(f"tom{tom}_count", 0), "avg_wealth": fs.get(f"tom{tom}_avg_wealth", 0)}
                for tom in [0, 1, 2] if fs.get(f"tom{tom}_count", 0) > 0
            },
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        logger.info("Results saved to %s", output_path)
    except Exception as write_err:
        logger.error("Failed to write results.json: %s", write_err)

    # 打印摘要
    try:
        fs = results["final_stats"]
        print("\n" + "=" * 60)
        print("仿真结果摘要")
        print("=" * 60)
        print(f"总决策次数: {results['total_decisions']}")
        print(f"总成交笔数: {results['total_trades']}")
        lp = fs.get('last_price')
        print(f"最终价格:   {lp:.2f}" if isinstance(lp, (int, float)) else "最终价格:   N/A")
        print()
        for tom in [0, 1, 2]:
            avg_w = fs.get(f"tom{tom}_avg_wealth", 0)
            cnt = fs.get(f"tom{tom}_count", 0)
            label = {0: "零阶", 1: "一阶", 2: "二阶"}[tom]
            print(f"  ToM {tom} [{label}]: {cnt}人, 平均财富={avg_w:,.0f}")

        evo_logs = results.get("evolution_logs", [])
        if evo_logs:
            total_upgrades = sum(e["upgraded"] for e in evo_logs)
            final_dist = evo_logs[-1].get("by_level", {})
            print(f"\n演化统计:")
            print(f"  演化轮数: {len(evo_logs)}")
            print(f"  总升级次数: {total_upgrades}")
            print(f"  最终 ToM 分布: {final_dist}")
        print("=" * 60)
    except Exception as print_err:
        logger.error("Failed to print summary: %s", print_err)


if __name__ == "__main__":
    asyncio.run(main())
