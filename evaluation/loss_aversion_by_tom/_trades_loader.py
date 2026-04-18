#!/usr/bin/env python3
"""共用工具：从 trades.jsonl 重建每个 agent 的 realized gain/loss 列表，
并按"有效样本"标准过滤掉交易退化的 agent。

这是方案 A 的核心：用 avg_gain≥1% 且 n_gain≥3 过滤退化样本后再计算 λ̂。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

RUNS_ROOT = Path('/Users/mushroom/Desktop/MentalMarket/runs')
CACHE_DIR = Path(__file__).parent / '_trades_reconstruction_cache'
CACHE_DIR.mkdir(exist_ok=True)

# 过滤阈值（方案 A）
MIN_GAIN_COUNT = 3          # 至少 3 次已实现盈利事件
MIN_AVG_GAIN_PCT = 1.0      # 平均盈利幅度至少 1%
MIN_LOSS_COUNT = 1          # 至少 1 次已实现亏损事件（否则 λ 未定义）


def _load_agent_init(run_dir: Path) -> dict[int, dict]:
    """读取 agents_init.jsonl 获取 {agent_id: {tom_level, initial_positions}}

    initial_positions: {symbol: (qty, avg_buy_price)}
    """
    fp = run_dir / 'agents_init.jsonl'
    out: dict[int, dict] = {}
    if not fp.exists():
        return out
    with open(fp, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            aid = r.get('agent_id') if 'agent_id' in r else r.get('id')
            tom = r.get('tom_level')
            if aid is None or tom is None:
                continue
            positions = r.get('positions') or {}
            avg_prices = r.get('avg_buy_price_by_symbol') or {}
            init_pos: dict[str, tuple[int, float]] = {}
            for sym, qty in positions.items():
                try:
                    q = int(qty); p = float(avg_prices.get(sym, 0.0))
                    if q > 0 and p > 0:
                        init_pos[sym] = (q, p)
                except Exception:
                    continue
            out[int(aid)] = {
                'tom_level': int(tom),
                'init_positions': init_pos,
            }
    return out


def reconstruct_run(run_name: str, use_cache: bool = True) -> dict:
    """返回 {agent_id: {'tom': int, 'gains': [pct,...], 'losses': [pct,...]}}
    其中 pct 是已实现盈亏幅度（百分比，正值）。
    """
    cache_fp = CACHE_DIR / f'{run_name}.json'
    if use_cache and cache_fp.exists():
        try:
            with open(cache_fp, 'r', encoding='utf-8') as f:
                d = json.load(f)
            return {int(k): v for k, v in d.items()}
        except Exception:
            pass

    run_dir = RUNS_ROOT / run_name
    agent_init = _load_agent_init(run_dir)
    trades_fp = run_dir / 'trades.jsonl'
    if not trades_fp.exists():
        return {}

    # 用初始持仓 + 初始成本基础初始化
    positions: dict[tuple[int, str], dict] = defaultdict(
        lambda: {'qty': 0, 'cost': 0.0}
    )
    realized: dict[int, dict] = {}
    for aid, info in agent_init.items():
        realized[aid] = {
            'tom': info['tom_level'],
            'gains': [], 'losses': [],
        }
        for sym, (q, p) in info['init_positions'].items():
            positions[(aid, sym)] = {'qty': q, 'cost': p}

    def init_agent(aid: int):
        if aid not in realized:
            realized[aid] = {
                'tom': agent_init.get(aid, {}).get('tom_level', -1),
                'gains': [], 'losses': [],
            }

    def apply_buy(aid: int, sym: str, qty: int, price: float):
        init_agent(aid)
        pos = positions[(aid, sym)]
        new_qty = pos['qty'] + qty
        if new_qty > 0:
            pos['cost'] = (pos['cost'] * pos['qty'] + price * qty) / new_qty
        pos['qty'] = new_qty

    def apply_sell(aid: int, sym: str, qty: int, price: float):
        init_agent(aid)
        pos = positions[(aid, sym)]
        avg_buy = pos['cost']
        if avg_buy > 0 and pos['qty'] > 0:
            pnl_pct = abs((price - avg_buy) / avg_buy * 100.0)
            if price > avg_buy:
                realized[aid]['gains'].append(round(pnl_pct, 4))
            elif price < avg_buy:
                realized[aid]['losses'].append(round(pnl_pct, 4))
            # 裁剪 200 条上限（对齐源码 agent_analytics.py）
            if len(realized[aid]['gains']) > 200:
                realized[aid]['gains'] = realized[aid]['gains'][-200:]
            if len(realized[aid]['losses']) > 200:
                realized[aid]['losses'] = realized[aid]['losses'][-200:]
        pos['qty'] = max(0, pos['qty'] - qty)
        if pos['qty'] == 0:
            pos['cost'] = 0.0

    with open(trades_fp, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                t = json.loads(line)
            except Exception:
                continue
            sym = t.get('symbol')
            qty = int(t.get('quantity') or 0)
            price = float(t.get('price') or 0)
            buyer = t.get('buyer_id')
            seller = t.get('seller_id')
            if sym is None or qty <= 0 or price <= 0:
                continue
            if buyer is not None:
                apply_buy(int(buyer), sym, qty, price)
            if seller is not None:
                apply_sell(int(seller), sym, qty, price)

    # 写缓存
    try:
        with open(cache_fp, 'w', encoding='utf-8') as f:
            json.dump({str(k): v for k, v in realized.items()},
                      f, ensure_ascii=False)
    except Exception:
        pass

    return realized


def compute_lambda(gains: list[float], losses: list[float]) -> float | None:
    """计算单个 agent 的 λ̂。"""
    if not gains or not losses:
        return None
    avg_g = sum(gains) / len(gains)
    avg_l = sum(losses) / len(losses)
    if avg_g <= 0.01:
        return None
    return avg_l / avg_g


def is_valid_sample(
    gains: list[float],
    losses: list[float],
    min_gain_n: int = MIN_GAIN_COUNT,
    min_avg_gain: float = MIN_AVG_GAIN_PCT,
    min_loss_n: int = MIN_LOSS_COUNT,
) -> bool:
    """方案 A 筛选标准：排除交易退化样本。"""
    if len(gains) < min_gain_n:
        return False
    if len(losses) < min_loss_n:
        return False
    if (sum(gains) / len(gains)) < min_avg_gain:
        return False
    return True


def collect_filtered_lambdas(run_name: str) -> dict[int, dict]:
    """返回 {tom_level: {'valid': [λ,...], 'n_total': int, 'n_valid': int}}"""
    data = reconstruct_run(run_name)
    by_tom: dict[int, dict] = defaultdict(
        lambda: {'valid': [], 'n_total': 0, 'n_valid': 0}
    )
    for aid, d in data.items():
        tom = d['tom']
        if tom < 0:
            continue
        by_tom[tom]['n_total'] += 1
        if is_valid_sample(d['gains'], d['losses']):
            lam = compute_lambda(d['gains'], d['losses'])
            if lam is not None:
                by_tom[tom]['valid'].append(lam)
                by_tom[tom]['n_valid'] += 1
    return dict(by_tom)
