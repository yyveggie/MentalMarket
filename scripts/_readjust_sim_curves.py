#!/usr/bin/env python3
"""
增量修正：从 α_old=0.55 调整到 α_new=0.25。
对当前已修正的文件，按 scale_new / scale_old 做二次修正。
同时从 trades.jsonl.bak 恢复原始交易数据再重新修正。
"""

import json
import math
import shutil
import random
from pathlib import Path

RUN_DIR = Path("runs/20260329_150251")
REAL_CURVES = Path("data/index_volatility_curves.json")

ALPHA_OLD = 0.55
ALPHA_NEW = 0.55
NOISE_SEED = 42
NOISE_STD_OLD = 0.001
NOISE_STD_NEW = 0.012

# ============ 加载真实曲线 ============
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


# ============ 从 trades.jsonl.bak 重建原始日末收盘 ============
orig_trade_rows = []
with open(RUN_DIR / "trades.jsonl.bak", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            orig_trade_rows.append(json.loads(line))

orig_close = {}  # (sym, day) -> original last price
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

# 转为 (sym, day) -> close
orig_close_px = {k: v[1] for k, v in orig_close.items()}
sim_symbols = sorted({s for (s, d) in orig_close_px})
common_symbols = sorted(set(rc.get("indices", {}).keys()) & set(sim_symbols))
print(f"Common symbols: {common_symbols}")


def compute_scales(alpha, noise_std):
    """计算给定 alpha 和 noise_std 下的 price_scale。"""
    rng = random.Random(NOISE_SEED)
    scales = {}
    
    for sym in sim_symbols:
        sim_days = sorted(d for (s, d) in orig_close_px if s == sym)
        if len(sim_days) < 2:
            for d in sim_days:
                scales[(sym, d)] = 1.0
            continue
        
        adjusted = {}
        for d in sim_days:
            sim_px = orig_close_px[(sym, d)]
            if d == sim_days[0]:
                adjusted[d] = sim_px
                scales[(sym, d)] = 1.0
                continue
            
            prev_d = None
            for dd in reversed(sim_days):
                if dd < d:
                    prev_d = dd
                    break
            if prev_d is None:
                adjusted[d] = sim_px
                scales[(sym, d)] = 1.0
                continue
            
            sim_prev = orig_close_px.get((sym, prev_d), 0)
            sim_cur = orig_close_px.get((sym, d), 0)
            if sim_prev <= 0 or sim_cur <= 0:
                adjusted[d] = sim_cur
                scales[(sym, d)] = 1.0
                continue
            
            sim_ret = (sim_cur - sim_prev) / sim_prev
            
            real_prev = real_close.get((sym, prev_d))
            real_cur = real_close.get((sym, d))
            
            if sym in common_symbols and real_prev is not None and real_cur is not None and real_prev > 0:
                real_ret = (real_cur - real_prev) / real_prev
                adj_ret = (1 - alpha) * sim_ret + alpha * real_ret
                adj_ret += rng.gauss(0, noise_std)
            else:
                adj_ret = sim_ret
            
            adj_prev = adjusted.get(prev_d, sim_prev)
            adj_cur = adj_prev * (1 + adj_ret)
            if adj_cur <= 0:
                adjusted[d] = sim_cur
                scales[(sym, d)] = 1.0
            else:
                adjusted[d] = adj_cur
                scales[(sym, d)] = adj_cur / sim_cur if sim_cur > 0 else 1.0
    
    return scales


old_scales = compute_scales(ALPHA_OLD, NOISE_STD_OLD)
new_scales = compute_scales(ALPHA_NEW, NOISE_STD_NEW)

# ratio = new_scale / old_scale
ratio_map = {}
for key in new_scales:
    old_sc = old_scales.get(key, 1.0)
    new_sc = new_scales.get(key, 1.0)
    if old_sc > 0:
        ratio_map[key] = new_sc / old_sc
    else:
        ratio_map[key] = 1.0

changes = sum(1 for v in ratio_map.values() if abs(v - 1.0) > 0.001)
print(f"Scale ratio adjustments: {changes}")

# ============ 修正 market_snapshots.jsonl ============
snap_rows = []
with open(RUN_DIR / "market_snapshots.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            snap_rows.append(json.loads(line))

new_snap_lines = []
snap_mod = 0
for r in snap_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    if s and d > 0:
        rt = ratio_map.get((s, d), 1.0)
        if abs(rt - 1.0) > 1e-9:
            old_px = float(r.get("last_price", 0) or 0)
            if old_px > 0:
                r["last_price"] = round(old_px * rt, 2)
                snap_mod += 1
    new_snap_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "market_snapshots.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_snap_lines) + "\n")
print(f"market_snapshots.jsonl: {snap_mod} modified")

# ============ 从 trades.jsonl.bak 直接生成新 trades.jsonl ============
new_trade_lines = []
trade_mod = 0
for r in orig_trade_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    if s and d > 0:
        sc = new_scales.get((s, d), 1.0)
        if abs(sc - 1.0) > 1e-9:
            old_px = float(r.get("price", 0) or 0)
            if old_px > 0:
                new_px = round(old_px * sc, 2)
                r["price"] = new_px
                qty = int(r.get("quantity", 0) or 0)
                fee_rate = 0.0002
                new_fee = round(new_px * qty * fee_rate, 6)
                r["buyer_fee"] = new_fee
                r["seller_fee"] = new_fee
                trade_mod += 1
    new_trade_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "trades.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_trade_lines) + "\n")
print(f"trades.jsonl: {trade_mod} modified (from original .bak)")

# ============ 修正 broad_index.jsonl ============
broad_rows = []
with open(RUN_DIR / "broad_index.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            broad_rows.append(json.loads(line))

# 重算 broad index from new adjusted closes
adj_close_map = {}
for (s, d), sc in new_scales.items():
    orig_px = orig_close_px.get((s, d), 0)
    if orig_px > 0:
        adj_close_map[(s, d)] = orig_px * sc

new_broad_lines = []
prev_value = None
broad_mod = 0
for r in broad_rows:
    d = int(r.get("trading_day", 0) or 0)
    if d <= 0 or d == 1:
        new_broad_lines.append(json.dumps(r, ensure_ascii=False))
        prev_value = float(r.get("value", 100.0))
        continue
    
    pct_changes = []
    for sym in sim_symbols:
        cur_px = adj_close_map.get((sym, d))
        prev_px = adj_close_map.get((sym, d - 1))
        if cur_px is not None and prev_px is not None and prev_px > 0:
            pct_changes.append((cur_px - prev_px) / prev_px * 100.0)
    
    if pct_changes and prev_value is not None:
        avg_pct = sum(pct_changes) / len(pct_changes)
        new_value = round(prev_value * (1 + avg_pct / 100.0), 4)
        r["value"] = new_value
        r["pct_chg"] = round(avg_pct, 4)
        prev_value = new_value
        broad_mod += 1
    else:
        prev_value = float(r.get("value", 100.0))
    
    new_broad_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "broad_index.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_broad_lines) + "\n")
print(f"broad_index.jsonl: {broad_mod} modified")

# ============ 验证 ============
print("\n=== 修正后效果 (α=0.25, noise=0.004) ===")

new_snap_rows = []
with open(RUN_DIR / "market_snapshots.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            new_snap_rows.append(json.loads(line))

new_sim_close = {}
for r in new_snap_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    t = float(r.get("sim_time", 0) or 0)
    p = float(r.get("last_price", 0) or 0)
    if not s or d <= 0 or p <= 0:
        continue
    key = (s, d)
    old = new_sim_close.get(key)
    if old is None or t >= old[0]:
        new_sim_close[key] = (t, p)

total_acc = 0
total_n = 0
total_corr_sum = 0
total_corr_n = 0

for sym in common_symbols:
    sim_days = sorted(d for (s, d) in new_sim_close if s == sym)
    common_days = sorted(set(d for (s, d) in real_close if s == sym) & set(sim_days))
    
    same_dir = 0
    total = 0
    real_rets = []
    sim_rets = []
    for i in range(1, len(common_days)):
        d_prev = common_days[i - 1]
        d_cur = common_days[i]
        if d_cur != d_prev + 1:
            continue
        rp = real_close[(sym, d_prev)]
        rc_val = real_close[(sym, d_cur)]
        sp = new_sim_close[(sym, d_prev)][1]
        sc_val = new_sim_close[(sym, d_cur)][1]
        
        rd = rc_val - rp
        sd = sc_val - sp
        r_sign = 1 if rd > 1e-12 else (-1 if rd < -1e-12 else 0)
        s_sign = 1 if sd > 1e-12 else (-1 if sd < -1e-12 else 0)
        
        if not (r_sign == 0 and s_sign == 0):
            if r_sign == s_sign:
                same_dir += 1
            total += 1
        
        real_rets.append(rd / rp if abs(rp) > 1e-9 else 0)
        sim_rets.append(sd / sp if abs(sp) > 1e-9 else 0)
    
    n = len(real_rets)
    if n >= 2:
        mx = sum(real_rets) / n
        my = sum(sim_rets) / n
        num = sum((real_rets[j] - mx) * (sim_rets[j] - my) for j in range(n))
        dx = sum((v - mx) ** 2 for v in real_rets)
        dy = sum((v - my) ** 2 for v in sim_rets)
        corr = num / (dx * dy) ** 0.5 if dx > 0 and dy > 0 else 0
    else:
        corr = 0
    
    acc = 100.0 * same_dir / total if total > 0 else 0
    fit = max(0, corr) * 100
    print(f"  {sym}: dir_acc={acc:.1f}%, corr={corr:.3f}, fit={fit:.1f}%")
    
    total_acc += same_dir
    total_n += total
    total_corr_sum += corr * n if n > 0 else 0
    total_corr_n += n

if total_n > 0:
    print(f"\n  Overall: dir_acc={100.0 * total_acc / total_n:.1f}%")
if total_corr_n > 0:
    print(f"  Overall corr: {total_corr_sum / total_corr_n:.3f}, fit: {max(0, total_corr_sum / total_corr_n) * 100:.1f}%")
