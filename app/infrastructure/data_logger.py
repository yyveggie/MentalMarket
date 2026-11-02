"""
推理存储模块 (Data Logger)。
将每个 Agent 的每次推理记录、Agent 状态快照、演化事件、成交记录
以 JSONL 格式高效写入磁盘。

目录结构:
  runs/<run_id>/
    ├── config.yaml              # 本次运行使用的完整配置
    ├── agents_init.jsonl        # 所有 Agent 的初始状态
    ├── decisions.jsonl          # 每次 LLM 推理的完整记录（Prompt + 输出 + 动作）
    ├── plans.jsonl              # 计划版本日志（内容、交易天数、版本迭代）
    ├── posts.jsonl              # 公告/帖子记录（时间、发布者、来源、标的等）
    ├── trades.jsonl             # 所有成交记录
    ├── order_events.jsonl       # 订单生命周期事件（submit/cancel/expire）
    ├── sentiment_series.jsonl   # Agent 情绪时序（sentiment/confidence/action）
    ├── behavioral_biases.jsonl  # 行为偏差指标（处置效应/锚定/过度自信等）
    ├── social_graph_events.jsonl# 社交网络拓扑变化（follow/unfollow/KOL涌现）
    ├── liquidity_provision.jsonl# 每笔成交的做市/吃单角色（maker/taker）
    ├── info_cascade.jsonl       # 社交信息感知→交易决策因果链
    ├── price_discovery.jsonl    # 价格发现质量指标（方差比/自相关/Amihud）
    ├── orderbook_depth.jsonl    # 盘口深度快照（买卖各档总量/不平衡度）
    ├── reputation_history.jsonl # 声誉分数变化历史
    ├── plan_execution.jsonl     # 计划执行追踪（计划意图 vs 实际行动）
    ├── collective_behavior.jsonl# 群体行为指标（泡沫检测/群体极化/信息茧房）
    ├── evolution.jsonl          # 演化事件日志
    └── agents_final.jsonl       # 仿真结束时所有 Agent 的最终状态
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

try:
    import orjson as _orjson

    def _fast_json_dumps(obj: dict) -> str:
        return _orjson.dumps(obj, option=_orjson.OPT_NON_STR_KEYS).decode()

    def _fast_json_loads(text: str):
        return _orjson.loads(text)
except ImportError:
    import json as _json_fallback

    def _fast_json_dumps(obj: dict) -> str:
        return _json_fallback.dumps(obj, ensure_ascii=False)

    def _fast_json_loads(text: str):
        return _json_fallback.loads(text)

logger = logging.getLogger(__name__)


class DataLogger:
    """
    高吞吐量的 JSONL 追加写入日志系统。
    所有写入操作使用缓冲，定期 flush 以平衡性能和数据安全。
    """

    def __init__(self, base_dir: str = "runs", run_id: Optional[str] = None, buffer_size: int = 100, store_prompt: bool = True):
        if run_id is None:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id
        self.run_dir = Path(base_dir) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._buffer_size = buffer_size
        self._store_prompt = bool(store_prompt)

        # 文件句柄（延迟打开）
        self._files: dict[str, TextIO] = {}
        self._buffers: dict[str, list[str]] = {}
        self._decision_count = 0
        self._listeners: list = []
        self._listeners_snapshot: tuple = ()
        self._flush_fail_counts: dict[str, int] = {}
        self._snapshot_interval: float = 3600.0

        logger.info("DataLogger initialized: %s (store_prompt=%s)", self.run_dir, self._store_prompt)

    def _get_writer(self, name: str) -> TextIO:
        """获取或创建一个 JSONL 文件的写入句柄（64KB 缓冲区减少系统调用）"""
        if name not in self._files:
            path = self.run_dir / f"{name}.jsonl"
            self._files[name] = open(path, "a", encoding="utf-8", buffering=65536)
            # 重开文件句柄（flush 失败重试）时必须保留既有缓冲区，否则待重试的记录会变成孤儿而丢失
            self._buffers.setdefault(name, [])
        return self._files[name]

    def _append(self, name: str, record: dict):
        """追加一条记录到缓冲区，满了就 flush。自动补充 trading_day。"""
        if "sim_time" in record and "trading_day" not in record:
            st = float(record["sim_time"])
            record["trading_day"] = int(st // self._snapshot_interval) + 1 if self._snapshot_interval > 0 else 0
        buf = self._buffers.setdefault(name, [])
        buf.append(_fast_json_dumps(record))
        for listener in self._listeners_snapshot:
            try:
                listener(name, record)
            except Exception as e:
                logger.debug("DataLogger listener error on %s: %s", name, e)
        if len(buf) >= self._buffer_size:
            self._flush(name)

    def add_listener(self, listener):
        """注册实时监听器：listener(name, record)。"""
        if listener not in self._listeners:
            self._listeners.append(listener)
            self._listeners_snapshot = tuple(self._listeners)

    def remove_listener(self, listener):
        """移除实时监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)
            self._listeners_snapshot = tuple(self._listeners)

    def _flush(self, name: str, force_sync: bool = False):
        """将缓冲区写入文件的 64KB 缓冲区（不阻塞刷盘）。首次失败重试一次。"""
        buf = self._buffers.get(name, [])
        if not buf:
            return
        payload = "\n".join(buf) + "\n"
        for attempt in range(2):
            try:
                writer = self._get_writer(name)
                writer.write(payload)
                if force_sync:
                    writer.flush()
                self._flush_fail_counts[name] = 0
                buf.clear()
                return
            except OSError as e:
                if attempt == 0:
                    old_fh = self._files.pop(name, None)
                    if old_fh is not None:
                        try:
                            old_fh.close()
                        except Exception:
                            pass
                    logger.warning("Flush %s failed (attempt 1), reopening file: %s", name, e)
                    continue
                fc = self._flush_fail_counts.get(name, 0) + 1
                self._flush_fail_counts[name] = fc
                logger.error("Failed to flush %s (%d records retained for retry, consecutive_failures=%d): %s", name, len(buf), fc, e)
                if fc >= 10:
                    logger.critical("DISK I/O FAILURE on %s: %d consecutive flush failures — data at risk! Check disk space.", name, fc)
                    buf.clear()

    def truncate_after_sim_time(
        self,
        sim_time: float,
        skip: tuple[str, ...] = ("agents_init", "agents_final"),
    ) -> dict[str, int]:
        """续跑前调用：删除各 JSONL 中 sim_time 晚于 checkpoint 时刻的记录。

        崩溃前已落盘但未进入 checkpoint 的记录会在续跑后被重新生成（decision_id 也从
        checkpoint 计数继续），不删除就会出现重复行和重复编号。
        """
        import os

        self.flush_all()
        for fh in self._files.values():
            try:
                fh.close()
            except Exception:
                pass
        self._files.clear()

        cutoff = float(sim_time) + 1e-6
        removed: dict[str, int] = {}
        for path in sorted(self.run_dir.glob("*.jsonl")):
            name = path.stem
            if name in skip:
                continue
            tmp_path = path.with_name(path.name + ".tmp")
            dropped = 0
            with open(path, "r", encoding="utf-8") as src, open(tmp_path, "w", encoding="utf-8") as dst:
                for line in src:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = _fast_json_loads(stripped)
                    except Exception:
                        dst.write(stripped + "\n")
                        continue
                    st = record.get("sim_time") if isinstance(record, dict) else None
                    if st is not None:
                        try:
                            if float(st) > cutoff:
                                dropped += 1
                                continue
                        except (TypeError, ValueError):
                            pass
                    dst.write(stripped + "\n")
            if dropped > 0:
                os.replace(tmp_path, path)
                removed[name] = dropped
            else:
                os.remove(tmp_path)
        if removed:
            logger.info("Resume: dropped post-checkpoint records (sim_time > %.3f): %s", float(sim_time), removed)
        return removed

    # ========== 公共 API ==========

    def save_config(self, config: dict):
        """保存本次运行的完整配置"""
        import yaml
        path = self.run_dir / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    def log_agent_init(self, agent_id: int, state: dict):
        """记录 Agent 初始状态"""
        record = {"agent_id": agent_id, **state}
        self._append("agents_init", record)

    def log_agents_init_batch(self, agents: dict):
        """批量记录所有 Agent 的初始状态（排除虚拟做市商 agent_id=0）"""
        for agent_id, state in agents.items():
            if agent_id == 0:
                continue
            self.log_agent_init(agent_id, _agent_state_to_dict(state))
        self._flush("agents_init", force_sync=True)

    def log_decision(
        self,
        agent_id: int,
        sim_time: float,
        tom_level: int,
        prompt: str,
        llm_output: dict,
        action_executed: dict,
        agent_snapshot: dict,
        graph_observability: dict | None = None,
    ):
        """
        记录一次完整的推理过程。
        包含：时间、Agent信息、完整Prompt、LLM原始输出、最终执行的动作、Agent当时状态。
        """
        self._decision_count += 1
        record = {
            "decision_id": self._decision_count,
            "sim_time": round(sim_time, 3),
            "agent_id": agent_id,
            "tom_level": tom_level,
            "llm_output": llm_output,
            "action_executed": action_executed,
            "agent_snapshot": agent_snapshot,
        }
        if self._store_prompt and prompt:
            record["prompt"] = prompt
        if graph_observability is not None:
            record["graph_observability"] = graph_observability
        self._append("decisions", record)

    def log_trade(self, trade_record: dict):
        """记录一笔成交"""
        self._append("trades", trade_record)

    def log_post(self, post_record: dict):
        """记录一条公告/帖子（含时间、发布者、标的、来源等）。"""
        self._append("posts", post_record)
        # 帖子数量相对低频，实时刷盘可避免前端已更新但 posts.jsonl 仍未可见。
        self._flush("posts", force_sync=True)

    def log_plan(self, plan_record: dict):
        """记录一次计划创建/更新（含版本与前后对比）。"""
        self._append("plans", plan_record)

    def log_broad_index(self, record: dict):
        """记录大盘指数数据点（时间、值、涨跌幅）。"""
        self._append("broad_index", record)

    def log_market_snapshot(self, record: dict):
        """记录交易日市场微观结构快照（换手率/成交量/买卖比/VWAP/波动率/价差等）。"""
        self._append("market_snapshots", record)

    def log_agent_wealth_snapshot(self, records: list[dict]):
        """批量记录所有 Agent 某一时刻的精简财富快照。"""
        for r in records:
            self._append("agent_wealth", r)
        self._flush("agent_wealth")

    def log_tom_stats(self, record: dict):
        """记录某一时刻按 ToM 分层的聚合统计。"""
        self._append("tom_stats", record)

    def log_order_event(self, record: dict):
        """记录订单事件（submit/cancel/implicit_cancel/expire）。"""
        self._append("order_events", record)

    def log_sentiment(self, record: dict):
        """记录 Agent 情绪时序数据（sentiment/confidence/action）。"""
        self._append("sentiment_series", record)

    def log_behavioral_bias(self, record: dict):
        """记录行为偏差指标（处置效应/锚定/过度自信/损失厌恶/羊群效应）。"""
        self._append("behavioral_biases", record)

    def log_social_graph_event(self, record: dict):
        """记录社交网络拓扑变化事件（follow/unfollow/kol_emerge/kol_lost）。"""
        self._append("social_graph_events", record)

    def log_liquidity_provision(self, record: dict):
        """记录每笔成交的做市/吃单角色（maker/taker）。"""
        self._append("liquidity_provision", record)

    def log_info_cascade(self, record: dict):
        """记录社交信息感知与交易决策的因果链。"""
        self._append("info_cascade", record)

    def log_price_discovery(self, record: dict):
        """记录价格发现质量指标（方差比/自相关/Amihud 非流动性）。"""
        self._append("price_discovery", record)

    def log_orderbook_depth(self, record: dict):
        """记录盘口深度快照（买卖各档总量/不平衡度）。"""
        self._append("orderbook_depth", record)

    def log_reputation_history(self, record: dict):
        """记录声誉分数变化历史。"""
        self._append("reputation_history", record)

    def log_plan_execution(self, record: dict):
        """记录计划执行追踪（计划意图 vs 实际行动的一致性）。"""
        self._append("plan_execution", record)

    def log_collective_behavior(self, record: dict):
        """记录群体行为指标（自我实现预言/泡沫检测/群体极化/信息茧房）。"""
        self._append("collective_behavior", record)

    def log_evolution(self, sim_time: float, stats: dict):
        """记录一次演化事件"""
        record = {"sim_time": round(sim_time, 3), **stats}
        self._append("evolution", record)

    def log_agent_final(self, agent_id: int, state: dict):
        """记录 Agent 最终状态"""
        record = {"agent_id": agent_id, **state}
        self._append("agents_final", record)

    def log_agents_final_batch(self, agents: dict, last_price: float | dict[str, float]):
        """批量记录所有 Agent 的最终状态（排除虚拟做市商 agent_id=0）。
        文件只保留最新一份：续跑再次退出时覆盖而不是追加。"""
        self._flush("agents_final")
        old_fh = self._files.pop("agents_final", None)
        if old_fh is not None:
            try:
                old_fh.close()
            except Exception:
                pass
        self._buffers["agents_final"] = []
        with open(self.run_dir / "agents_final.jsonl", "w", encoding="utf-8"):
            pass
        if isinstance(last_price, dict):
            price_map = last_price
        else:
            price_map = {"UNKNOWN": float(last_price)}
        default_px = next(iter(price_map.values()), 0.0) if price_map else 0.0
        for agent_id, state in agents.items():
            if agent_id == 0:
                continue
            d = _agent_state_to_dict(state)
            positions = getattr(state, "positions", {}) or {}
            final_wealth = float(state.cash)
            for symbol, qty in positions.items():
                if int(qty) <= 0:
                    continue
                px = price_map.get(symbol, default_px)
                final_wealth += float(px) * int(qty)
            d["final_wealth"] = round(final_wealth, 2)
            d["total_return"] = round(
                (d["final_wealth"] - state.initial_asset) / state.initial_asset
                if state.initial_asset > 0 else 0.0,
                4,
            )
            self.log_agent_final(agent_id, d)
        self._flush("agents_final")

    def flush_all(self):
        """将所有缓冲区强制写入磁盘（包括已写入文件对象但仍留在其 64KB 缓冲里的数据）"""
        for name in list(self._buffers.keys()):
            self._flush(name, force_sync=True)
        for fh in self._files.values():
            try:
                fh.flush()
            except Exception as e:
                logger.debug("flush_all: file flush failed: %s", e)

    def close(self):
        """关闭所有文件句柄"""
        self.flush_all()
        for f in self._files.values():
            f.close()
        self._files.clear()
        self._buffers.clear()
        logger.info(
            "DataLogger closed: %d decisions logged to %s",
            self._decision_count, self.run_dir,
        )

    @property
    def decisions_logged(self) -> int:
        return self._decision_count

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


_FLOAT_ROUND_FIELDS = {"cash": 2, "total_pnl": 2, "initial_asset": 2}
_CUSTOM_SERIALIZED_FIELDS = {
    "positions", "avg_buy_price_by_symbol", "index_holdings", "active_order_ids",
    "plan_content", "plan_days_left", "plan_version",
    "deception_plan_content", "deception_plan_days_left", "deception_plan_version",
}
_INTERNAL_ONLY_FIELDS = {
    "daily_trade_notional", "daily_trade_count", "daily_trade_symbols",
    "last_turnover_reset_day", "last_plan_consumed_day",
}

def _agent_state_to_dict(state) -> dict:
    """将 AgentState dataclass 转为可序列化的字典。
    _CUSTOM_SERIALIZED_FIELDS 在主循环中跳过，随后以自定义格式添加。
    _INTERNAL_ONLY_FIELDS 是纯运行时内部状态，不写入日志。
    """
    from dataclasses import fields as _dc_fields
    skip = _CUSTOM_SERIALIZED_FIELDS | _INTERNAL_ONLY_FIELDS
    d = {}
    for f in _dc_fields(state):
        name = f.name
        if name in skip:
            continue
        val = getattr(state, name)
        if name in _FLOAT_ROUND_FIELDS:
            d[name] = round(val, _FLOAT_ROUND_FIELDS[name])
        else:
            d[name] = val
    d["positions"] = {k: int(v) for k, v in getattr(state, "positions", {}).items()}
    d["avg_buy_price_by_symbol"] = {
        k: round(float(v), 4) for k, v in getattr(state, "avg_buy_price_by_symbol", {}).items()
    }
    d["index_holdings"] = list(state.index_holdings)
    d["active_order_ids"] = list(state.active_order_ids) if state.active_order_ids else []
    if state.plan_content or state.plan_days_left > 0:
        d["plan_content"] = state.plan_content
        d["plan_days_left"] = state.plan_days_left
        d["plan_version"] = state.plan_version
    if state.deception_plan_content or state.deception_plan_days_left > 0:
        d["deception_plan_content"] = state.deception_plan_content
        d["deception_plan_days_left"] = state.deception_plan_days_left
        d["deception_plan_version"] = state.deception_plan_version
    return d
