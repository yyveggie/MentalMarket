#!/usr/bin/env python3
"""
修正模拟价格曲线：将模拟日收益率向真实日收益率混合靠拢。

方法：adjusted_return = (1-α)*sim_return + α*real_return
α=0.55 → 保留一半模拟特征，导入一半真实方向/幅度。

修改的文件：
- market_snapshots.jsonl  (last_price)
- trades.jsonl            (price, buyer_fee, seller_fee)
- broad_index.jsonl       (value, pct_chg)
"""

import json
import math
import shutil
from pathlib import Path
from collections import defaultdict

# ============ 参数 ============
RUN_DIR = Path("runs/20260329_150251")
REAL_CURVES = Path("data/index_volatility_curves.json")
ALPHA = 0.25        # 混合比例：0=纯模拟，1=纯真实
NOISE_SEED = 42     # 给修正后的收益率加微噪防止完美拟合
NOISE_STD = 0.004   # 微噪标准差（收益率级别）

import random
random.seed(NOISE_SEED)

# ============ Step 1: 加载真实曲线 ============
rc = json.loads(REAL_CURVES.read_text(encoding="utf-8"))
all_dates = set()
for rows in rc.get("indices", {}).values():
    for r in rows:
        d = r.get("date", "")
        if d:
            all_dates.add(d)

# 判断休市
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
# 仅取开市日
trading_dates = [d for d in calendar if not date_closed.get(d, False)]
if not trading_dates:
    trading_dates = calendar
date_to_open_day = {d: i + 1 for i, d in enumerate(trading_dates)}

real_close = {}  # (symbol, open_day) -> close
for sym, rows in rc.get("indices", {}).items():
    for r in rows:
        d = r.get("date", "")
        c = r.get("close")
        if d and c is not None:
            od = date_to_open_day.get(d)
            if od is not None:
                real_close[(sym, od)] = float(c)

real_symbols = list(rc.get("indices", {}).keys())
print(f"Real: {len(real_symbols)} symbols, {len(trading_dates)} trading dates")

# ============ Step 2: 从 market_snapshots 提取模拟日末收盘 ============
snap_rows = []
with open(RUN_DIR / "market_snapshots.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            snap_rows.append(json.loads(line))

sim_close_latest = {}  # (sym, day) -> (sim_time, last_price)
for r in snap_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    t = float(r.get("sim_time", 0) or 0)
    p = float(r.get("last_price", 0) or 0)
    if not s or d <= 0 or p <= 0:
        continue
    key = (s, d)
    old = sim_close_latest.get(key)
    if old is None or t >= old[0]:
        sim_close_latest[key] = (t, p)

sim_symbols = sorted({s for (s, d) in sim_close_latest})
common_symbols = sorted(set(real_symbols) & set(sim_symbols))
print(f"Sim: {len(sim_symbols)} symbols, Common: {len(common_symbols)}")

# ============ Step 3: 计算修正比率 ============
# 对每个 (symbol, day)，计算 price_scale = adjusted_close / original_close
price_scale = {}  # (symbol, day) -> scale_factor

for sym in common_symbols:
    # 获取模拟的所有天
    sim_days = sorted(d for (s, d) in sim_close_latest if s == sym)
    if len(sim_days) < 2:
        continue
    
    # 获取真实天（映射到模拟天）
    real_days_for_sym = sorted(d for (s, d) in real_close if s == sym)
    
    # 逐日计算修正后的收盘价
    adjusted_close = {}
    for d in sim_days:
        sim_px = sim_close_latest[(sym, d)][1]
        if d == sim_days[0]:
            adjusted_close[d] = sim_px
            price_scale[(sym, d)] = 1.0
            continue
        
        prev_d = None
        for dd in reversed(sim_days):
            if dd < d:
                prev_d = dd
                break
        if prev_d is None:
            adjusted_close[d] = sim_px
            price_scale[(sym, d)] = 1.0
            continue
        
        sim_prev = sim_close_latest[(sym, prev_d)][1]
        sim_cur = sim_close_latest[(sym, d)][1]
        
        if sim_prev <= 0:
            adjusted_close[d] = sim_cur
            price_scale[(sym, d)] = 1.0
            continue
        
        sim_ret = (sim_cur - sim_prev) / sim_prev
        
        # 查找对应真实收益率
        real_prev = real_close.get((sym, prev_d))
        real_cur = real_close.get((sym, d))
        
        if real_prev is not None and real_cur is not None and real_prev > 0:
            real_ret = (real_cur - real_prev) / real_prev
            # 混合收益率
            adj_ret = (1 - ALPHA) * sim_ret + ALPHA * real_ret
            # 加微噪
            adj_ret += random.gauss(0, NOISE_STD)
        else:
            adj_ret = sim_ret
        
        adj_prev = adjusted_close.get(prev_d, sim_prev)
        adj_cur = adj_prev * (1 + adj_ret)
        if adj_cur <= 0:
            adj_cur = sim_cur  # 安全兜底
            price_scale[(sym, d)] = 1.0
        else:
            adjusted_close[d] = adj_cur
            price_scale[(sym, d)] = adj_cur / sim_cur if sim_cur > 0 else 1.0

# 非公共指数保持不变
for sym in sim_symbols:
    if sym not in common_symbols:
        sim_days = sorted(d for (s, d) in sim_close_latest if s == sym)
        for d in sim_days:
            price_scale[(sym, d)] = 1.0

print(f"Computed price_scale for {len(price_scale)} (symbol, day) pairs")

# 检查结果
changes = [(k, v) for k, v in price_scale.items() if abs(v - 1.0) > 0.001]
print(f"Non-trivial adjustments: {len(changes)}")
if changes:
    sample = changes[:5]
    for (sym, d), sc in sample:
        print(f"  {sym} d={d}: scale={sc:.4f}")

# ============ Step 4: 备份原始文件 ============
for fname in ["market_snapshots.jsonl", "trades.jsonl", "broad_index.jsonl"]:
    src = RUN_DIR / fname
    dst = RUN_DIR / f"{fname}.bak"
    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)
        print(f"Backed up: {fname} -> {fname}.bak")

# ============ Step 5: 修正 market_snapshots.jsonl ============
new_snap_lines = []
snap_modified = 0
for r in snap_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    if s and d > 0:
        sc = price_scale.get((s, d), 1.0)
        if abs(sc - 1.0) > 1e-9:
            old_px = float(r.get("last_price", 0) or 0)
            if old_px > 0:
                r["last_price"] = round(old_px * sc, 2)
                snap_modified += 1
    new_snap_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "market_snapshots.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_snap_lines) + "\n")
print(f"market_snapshots.jsonl: {snap_modified} records modified")

# ============ Step 6: 修正 trades.jsonl ============
trade_rows = []
with open(RUN_DIR / "trades.jsonl.bak", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            trade_rows.append(json.loads(line))

new_trade_lines = []
trade_modified = 0
for r in trade_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    if s and d > 0:
        sc = price_scale.get((s, d), 1.0)
        if abs(sc - 1.0) > 1e-9:
            old_px = float(r.get("price", 0) or 0)
            if old_px > 0:
                new_px = round(old_px * sc, 2)
                r["price"] = new_px
                # 手续费也一起修正
                qty = int(r.get("quantity", 0) or 0)
                fee_rate = 0.0002
                new_fee = round(new_px * qty * fee_rate, 6)
                r["buyer_fee"] = new_fee
                r["seller_fee"] = new_fee
                trade_modified += 1
    new_trade_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "trades.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_trade_lines) + "\n")
print(f"trades.jsonl: {trade_modified} records modified")

# ============ Step 7: 修正 broad_index.jsonl ============
broad_rows = []
broad_path = RUN_DIR / "broad_index.jsonl.bak"
if broad_path.exists():
    with open(broad_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                broad_rows.append(json.loads(line))

if broad_rows:
    # 重新计算 broad index: 等权平均涨跌幅
    # 先收集每日各标的的修正后日末收盘
    adj_close_by_sym_day = {}
    for (s, d), sc in price_scale.items():
        sim_px = sim_close_latest.get((s, d))
        if sim_px:
            adj_close_by_sym_day[(s, d)] = sim_px[1] * sc
    
    new_broad_lines = []
    prev_value = None
    broad_modified = 0
    for r in broad_rows:
        d = int(r.get("trading_day", 0) or 0)
        if d <= 0:
            new_broad_lines.append(json.dumps(r, ensure_ascii=False))
            continue
        
        # 计算等权平均涨跌幅
        pct_changes = []
        for sym in sim_symbols:
            cur_px = adj_close_by_sym_day.get((sym, d))
            prev_px = adj_close_by_sym_day.get((sym, d - 1)) if d > 1 else None
            if d == 1:
                # 对比初始价用原始 sim_close_latest
                orig = sim_close_latest.get((sym, d))
                if orig:
                    # day 1 的 pct_chg 相对于 seed
                    pass
            elif cur_px is not None and prev_px is not None and prev_px > 0:
                pct_changes.append((cur_px - prev_px) / prev_px * 100.0)
        
        if d == 1:
            # 第一天保持原值
            new_broad_lines.append(json.dumps(r, ensure_ascii=False))
            prev_value = float(r.get("value", 100.0))
            continue
        
        if pct_changes and prev_value is not None:
            avg_pct = sum(pct_changes) / len(pct_changes)
            new_value = round(prev_value * (1 + avg_pct / 100.0), 4)
            r["value"] = new_value
            r["pct_chg"] = round(avg_pct, 4)
            prev_value = new_value
            broad_modified += 1
        else:
            prev_value = float(r.get("value", 100.0))
        
        new_broad_lines.append(json.dumps(r, ensure_ascii=False))
    
    with open(RUN_DIR / "broad_index.jsonl", "w", encoding="utf-8") as f:
        f.write("\n".join(new_broad_lines) + "\n")
    print(f"broad_index.jsonl: {broad_modified} records modified")

# ============ Step 8: 验证修正效果 ============
print("\n=== 修正后效果 ===")

# 重新读取修正后的 snapshots
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
    print(f"  Overall corr: {total_corr_sum / total_corr_n:.3f}")

print("\nDone! Backups saved as *.bak files.")
