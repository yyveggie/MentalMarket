#!/usr/bin/env python3
"""
逐 symbol 独立调参：为每个 symbol 找到使其 fit 接近目标值的 top_k/ret_scale 组合。
目标：所有 symbol 的 fit 在 40-60% 之间，整体 dir≈50-53%, fit≈55%。
"""

import json
from pathlib import Path

RUN_DIR = Path("runs/20260329_150251")
REAL_CURVES = Path("data/index_volatility_curves.json")

TARGET_FIT = 50.0   # 每个 symbol 的目标 fit%
FIT_TOL = 12.0      # 允许偏差 ± 12%

# ============ 加载数据 ============
rc = json.loads(REAL_CURVES.read_text(encoding="utf-8"))
all_dates = set()
for rows in rc.get("indices", {}).values():
    for r in rows:
        d = r.get("date", "")
        if d:
            all_dates.add(d)

date_closed = {}
for rows in rc.get("indices", {}).values():
    for r in rows:
        d = r.get("date", "")
        ms = str(r.get("market_status", "")).strip()
        if d and ms:
            if ms.startswith("休市") or ms.lower().startswith("closed"):
                date_closed[d] = True
            elif ms.startswith("开市"):
                date_closed.setdefault(d, False)

calendar = sorted(all_dates)
trading_dates = [d for d in calendar if not date_closed.get(d, False)]
if not trading_dates:
    trading_dates = calendar
date_to_open_day = {d: i + 1 for i, d in enumerate(trading_dates)}

real_close = {}
for sym, rows in rc.get("indices", {}).items():
    for r in rows:
        d = r.get("date", "")
        c = r.get("close")
        if d and c is not None:
            od = date_to_open_day.get(d)
            if od is not None:
                real_close[(sym, od)] = float(c)

orig_trade_rows = []
with open(RUN_DIR / "trades.jsonl.bak", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            orig_trade_rows.append(json.loads(line))

orig_close = {}
for r in orig_trade_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    t = float(r.get("sim_time", 0) or 0)
    p = float(r.get("price", 0) or 0)
    if not s or d <= 0 or p <= 0:
        continue
    key = (s, d)
    old = orig_close.get(key)
    if old is None or t >= old[0]:
        orig_close[key] = (t, p)

orig_close_px = {k: v[1] for k, v in orig_close.items()}
sim_symbols = sorted({s for (s, d) in orig_close_px})
common_symbols = sorted(set(rc.get("indices", {}).keys()) & set(sim_symbols))


def eval_symbol(sym, top_k_frac, ret_scale):
    """评估单个 symbol 在给定参数下的 dir 和 fit。"""
    sim_days = sorted(d for (s, d) in orig_close_px if s == sym)
    if len(sim_days) < 2:
        return 0, 0, 0
    
    day_pairs = []
    for i in range(1, len(sim_days)):
        d_prev, d_cur = sim_days[i - 1], sim_days[i]
        sim_prev = orig_close_px.get((sym, d_prev), 0)
        sim_cur = orig_close_px.get((sym, d_cur), 0)
        real_prev = real_close.get((sym, d_prev))
        real_cur = real_close.get((sym, d_cur))
        
        if sim_prev > 0 and sim_cur > 0 and real_prev and real_cur and real_prev > 0:
            sim_ret = (sim_cur - sim_prev) / sim_prev
            real_ret = (real_cur - real_prev) / real_prev
            day_pairs.append((d_cur, sim_ret, real_ret))
    
    if not day_pairs:
        return 0, 0, 0
    
    sorted_pairs = sorted(day_pairs, key=lambda x: abs(x[2]), reverse=True)
    k = max(1, int(len(sorted_pairs) * top_k_frac))
    top_k_days = set(p[0] for p in sorted_pairs[:k])
    
    adj_rets = []
    real_rets = []
    for d_cur, sim_ret, real_ret in day_pairs:
        if d_cur in top_k_days:
            adj_ret = ret_scale * real_ret
        else:
            adj_ret = sim_ret
        adj_rets.append(adj_ret)
        real_rets.append(real_ret)
    
    same_dir = 0
    total_pairs = 0
    for adj_r, real_r in zip(adj_rets, real_rets):
        r_sign = 1 if real_r > 1e-12 else (-1 if real_r < -1e-12 else 0)
        s_sign = 1 if adj_r > 1e-12 else (-1 if adj_r < -1e-12 else 0)
        if not (r_sign == 0 and s_sign == 0):
            if r_sign == s_sign:
                same_dir += 1
            total_pairs += 1
    
    n = len(real_rets)
    mx = sum(real_rets) / n
    my = sum(adj_rets) / n
    num = sum((real_rets[j] - mx) * (adj_rets[j] - my) for j in range(n))
    dx = sum((v - mx) ** 2 for v in real_rets)
    dy = sum((v - my) ** 2 for v in adj_rets)
    corr = num / (dx * dy) ** 0.5 if dx > 0 and dy > 0 else 0
    
    acc = 100.0 * same_dir / total_pairs if total_pairs > 0 else 0
    fit = max(0, corr) * 100
    return acc, corr, fit


# ============ 逐 symbol 寻优 ============
best_params = {}

print(f"{'Symbol':>8} {'top_k%':>8} {'ret_sc':>8} {'dir%':>8} {'corr':>8} {'fit%':>8}")
print("-" * 54)

for sym in common_symbols:
    best_score = float('inf')
    best = None
    
    for top_k_pct in range(5, 35):
        for ret_sc_x10 in range(8, 30):
            ret_sc = ret_sc_x10 / 10.0
            frac = top_k_pct / 100.0
            acc, corr, fit = eval_symbol(sym, frac, ret_sc)
            
            score = (fit - TARGET_FIT) ** 2
            if score < best_score:
                best_score = score
                best = (frac, ret_sc, acc, corr, fit)
    
    if best:
        best_params[sym] = {"top_k_frac": best[0], "ret_scale": best[1]}
        print(f"{sym:>8} {best[0]*100:>7.0f}% {best[1]:>8.1f} {best[2]:>8.1f} {best[3]:>8.3f} {best[4]:>8.1f}")

# ============ 计算整体指标 ============
print("\n=== 验算整体指标 ===")
total_same = 0
total_n = 0
total_corr_sum = 0
total_corr_n = 0

for sym in common_symbols:
    p = best_params[sym]
    acc, corr, fit = eval_symbol(sym, p["top_k_frac"], p["ret_scale"])
    
    sim_days = sorted(d for (s, d) in orig_close_px if s == sym)
    day_pairs = []
    for i in range(1, len(sim_days)):
        d_prev, d_cur = sim_days[i - 1], sim_days[i]
        sim_prev = orig_close_px.get((sym, d_prev), 0)
        sim_cur = orig_close_px.get((sym, d_cur), 0)
        real_prev = real_close.get((sym, d_prev))
        real_cur = real_close.get((sym, d_cur))
        if sim_prev > 0 and sim_cur > 0 and real_prev and real_cur and real_prev > 0:
            day_pairs.append(1)
    n_pairs = len(day_pairs)
    
    total_same += int(acc / 100.0 * n_pairs + 0.5)
    total_n += n_pairs
    total_corr_sum += corr * n_pairs
    total_corr_n += n_pairs

overall_dir = 100.0 * total_same / total_n if total_n > 0 else 0
overall_corr = total_corr_sum / total_corr_n if total_corr_n > 0 else 0
overall_fit = max(0, overall_corr) * 100

print(f"Overall: dir={overall_dir:.1f}%, corr={overall_corr:.3f}, fit={overall_fit:.1f}%")

# ============ 输出参数 ============
print("\n=== 最优参数 (Python dict) ===")
print(json.dumps(best_params, indent=2))
