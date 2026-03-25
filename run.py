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
import sys
import time
from pathlib import Path

import yaml

from app.domain.agent import AgentManager
from app.infrastructure.api_balancer import APIBalancer, build_balancer_from_config
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
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--agents", type=int, default=None, help="覆盖Agent数量（快速测试用）")
    parser.add_argument("--time", type=float, default=None, help="覆盖仿真时长（秒）")
    parser.add_argument("--resume", default=None, help="从指定 run 目录的 checkpoint.pkl 恢复（如: runs/20260314_123456）")
    args = parser.parse_args()

    # 加载配置
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
    dashboard_cfg = config.get("dashboard", {})
    prompt_cfg = config.get("prompt", {})
    evolution_enabled = bool(evo_cfg.get("enabled", False))
    dashboard_enabled = bool(dashboard_cfg.get("enabled", True))

    n_agents = args.agents or sim_cfg.get("n_agents", 1000)
    max_time = args.time or sim_cfg.get("max_sim_time", 3600)
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
        initial_reputation=float(social_cfg.get("reputation_initial", 0.5)),
        neutral_threshold=float(social_cfg.get("reputation_neutral_threshold", 0.2)),
        min_window=int(social_cfg.get("reputation_min_window", 5)),
        max_pending=int(social_cfg.get("reputation_max_pending", 50000)),
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
    sim_cfg["symbol"] = configured_symbol
    sim_cfg["_ob_cfg"] = ob_cfg
    latest_close_map = index_board.latest_close_map() if index_board is not None else {}
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
    agent_mgr.init_agents(n_agents=n_agents, tom_distribution=tom_dist, initial_price=initial_price)

    # 初始化社交图谱（在 Agent 初始化之后）
    if social_graph is not None:
        tom_levels = {aid: a.tom_level for aid, a in agent_mgr.agents.items()}
        social_graph.init_agents(
            agent_ids=list(agent_mgr.agents.keys()),
            tom_levels=tom_levels,
            kol_follower_threshold=int(social_cfg.get("kol_follower_threshold", 30)),
            kol_influence=float(social_cfg.get("kol_influence", 5.0)),
            base_influence_by_tom={
                int(k): float(v)
                for k, v in social_cfg.get("base_influence_by_tom", {0: 1.0, 1: 1.5, 2: 2.0}).items()
            },
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
            index_lookback=int(dashboard_cfg.get("index_lookback", 240)),
            trading_day_seconds=float(dashboard_cfg.get("trading_day_seconds", snapshot_interval)),
            max_recent_events=int(dashboard_cfg.get("max_recent_events", 200)),
            dashboard_config=dashboard_cfg,
        )
        await dashboard.start()
        logger.info("Realtime dashboard at http://%s:%d", dashboard.host, dashboard.port)

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
    )
    engine._checkpoint_interval = float(storage_cfg.get("checkpoint_interval", snapshot_interval))
    engine._ckpt_l2_keep = int(storage_cfg.get("checkpoint_l2_keep", 200))
    engine._ckpt_price_keep = int(storage_cfg.get("checkpoint_price_keep", 5000))
    engine._ckpt_snapshot_keep = int(storage_cfg.get("checkpoint_snapshot_keep", 20))
    engine._ckpt_trade_log_limit = int(storage_cfg.get("checkpoint_trade_log_limit", 2000))

    # 安排新闻事件（从 news.json 文件加载）
    # 每个交易日随机选取 news_per_day 条不同指数的新闻，
    # 尽量保证每 coverage_cycle 个交易日内所有指数至少出现一次。
    news_events_cfg = config.get("news_events_config", {})
    if bool(news_events_cfg.get("enabled", True)):
        news_file = Path(str(news_events_cfg.get("news_file", "data/news.json")))
        if news_file.exists():
            with open(news_file, "r", encoding="utf-8") as nf:
                news_data = json.load(nf)
            news_per_day = int(news_events_cfg.get("news_per_day", 4))
            coverage_cycle = int(news_events_cfg.get("coverage_cycle", 3))
            news_day_offset_pct = float(news_events_cfg.get("news_day_offset_pct", 0.25))

            by_day: dict[int, list[dict]] = {}
            for item in news_data.get("news", []):
                day = int(item.get("day", 0))
                if day < 1:
                    continue
                by_day.setdefault(day, []).append(item)

            recent_indices: list[set[str]] = []
            news_count = 0
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

            logger.info("Loaded %d news events from %s (%d per day, coverage cycle=%d)",
                        news_count, news_file, news_per_day, coverage_cycle)

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

    # 运行仿真
    results = None
    try:
        results = await engine.run()
    except Exception as sim_err:
        logger.error("Simulation terminated with error: %s: %s", type(sim_err).__name__, sim_err)
        import traceback
        traceback.print_exc()
    finally:
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
