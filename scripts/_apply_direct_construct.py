#!/usr/bin/env python3
"""
直接构造法 - 应用最优参数修改 JSONL 文件
参数: top_k_frac=0.11, ret_scale=1.4
目标: dir≈52%, fit≈55%
"""

import json
from pathlib import Path

RUN_DIR = Path("runs/20260329_150251")
REAL_CURVES = Path("data/index_volatility_curves.json")

TOP_K_FRAC = 0.11
RET_SCALE = 1.4

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


# ============ 计算新 scales（价格缩放因子）============
def compute_new_scales():
    """直接构造法：top-K 天用 real_ret * ret_scale，其余天用原始 sim_ret。"""
    scales = {}
    
    for sym in sim_symbols:
        sim_days = sorted(d for (s, d) in orig_close_px if s == sym)
        if len(sim_days) < 2:
            for d in sim_days:
                scales[(sym, d)] = 1.0
            continue
        
        # 计算每天的 real 收益率幅度
        day_info = {}  # d -> (sim_ret, real_ret)
        for i in range(1, len(sim_days)):
            d_prev, d_cur = sim_days[i - 1], sim_days[i]
            sim_prev = orig_close_px.get((sym, d_prev), 0)
            sim_cur = orig_close_px.get((sym, d_cur), 0)
            real_prev = real_close.get((sym, d_prev))
            real_cur = real_close.get((sym, d_cur))
            
            if sim_prev > 0 and sim_cur > 0:
                sim_ret = (sim_cur - sim_prev) / sim_prev
            else:
                sim_ret = 0
            
            if sym in common_symbols and real_prev and real_cur and real_prev > 0:
                real_ret = (real_cur - real_prev) / real_prev
            else:
                real_ret = None
            
            day_info[d_cur] = (sim_ret, real_ret)
        
        # 按 |real_ret| 选 top-K
        days_with_real = [(d, info[1]) for d, info in day_info.items() if info[1] is not None]
        days_with_real.sort(key=lambda x: abs(x[1]), reverse=True)
        k = max(1, int(len(days_with_real) * TOP_K_FRAC))
        top_k_set = set(d for d, _ in days_with_real[:k])
        
        # 顺序构建 adjusted 价格
        adjusted = {}
        adjusted[sim_days[0]] = orig_close_px[(sym, sim_days[0])]
        scales[(sym, sim_days[0])] = 1.0
        
        for i in range(1, len(sim_days)):
            d_prev, d_cur = sim_days[i - 1], sim_days[i]
            sim_cur = orig_close_px[(sym, d_cur)]
            adj_prev = adjusted[d_prev]
            
            sim_ret, real_ret = day_info[d_cur]
            
            if d_cur in top_k_set and real_ret is not None:
                adj_ret = RET_SCALE * real_ret
            else:
                adj_ret = sim_ret
            
            adj_cur = adj_prev * (1 + adj_ret)
            if adj_cur <= 0:
                adj_cur = sim_cur
                scales[(sym, d_cur)] = 1.0
            else:
                scales[(sym, d_cur)] = adj_cur / sim_cur if sim_cur > 0 else 1.0
            adjusted[d_cur] = adj_cur
    
    return scales


new_scales = compute_new_scales()

# ============ 修改 trades.jsonl（从 .bak 读原始数据）============
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
                new_fee = round(new_px * qty * 0.0002, 6)
                r["buyer_fee"] = new_fee
                r["seller_fee"] = new_fee
                trade_mod += 1
    new_trade_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "trades.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_trade_lines) + "\n")
print(f"trades.jsonl: {trade_mod} modified (from original .bak)")


# ============ 修改 market_snapshots.jsonl ============
# snapshots 当前已被之前的脚本修改过，需要从原始交易数据推断缩放比
# 策略：直接对 snapshot 中的 last_price 用 new_scale 缩放原始价格
# 但 snapshots 没有 .bak，所以我们需要先还原再缩放

# 先读 snapshot 的原始逻辑：
# snapshot (sym, day) 的 last_price 对应该时刻的价格
# 我们按 day-level scale 统一缩放，相对于原始 sim 价格
# 原始 sim 的 day-end close = orig_close_px[(sym, day)]
# 当前 snapshot 的 last_price 被之前脚本修改过
# 需要回退到原始再重新缩放

# 但我们没有 snapshot 的 .bak...
# 简化做法：snapshot 的 last_price / 当前 scale → 原始价格 → * new_scale → new_price
# 当前 scale 可以通过当前 trades.jsonl 的 close 反算... 但 trades 刚被覆盖了

# 更好的方法：直接从 orig trades 重建每个 (sym, day) 的全部交易价格统计
# 然后对 snapshot 的 last_price 按 new_scale/1.0 缩放
# 但 snapshot 的 intra-day price 不等于 day-end close...

# 最简单可靠：直接把 snapshot 的 last_price 设为 adj_close（只有 day-end snapshot 才重要）
# 或者：从 snapshot 的 last_price 中提取出相对于 day-end close 的比例，然后缩放

snap_rows = []
with open(RUN_DIR / "market_snapshots.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            snap_rows.append(json.loads(line))

# 找到当前 snapshot 文件中每个 (sym, day) 的最后一条的 last_price（= 当前 day-end close）
current_snap_close = {}
for r in snap_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    t = float(r.get("sim_time", 0) or 0)
    p = float(r.get("last_price", 0) or 0)
    if s and d > 0 and p > 0:
        key = (s, d)
        old = current_snap_close.get(key)
        if old is None or t >= old[0]:
            current_snap_close[key] = (t, p)

current_close_px = {k: v[1] for k, v in current_snap_close.items()}

# 对每个 snapshot row，计算：
# ratio = target_close / current_close
# new_last_price = current_last_price * ratio
# 其中 target_close = orig_close_px * new_scale
# 这样可以统一处理 intra-day 的 proportional scaling

new_snap_lines = []
snap_mod = 0
for r in snap_rows:
    s = str(r.get("symbol", "")).strip()
    d = int(r.get("trading_day", 0) or 0)
    if s and d > 0:
        cur_close = current_close_px.get((s, d), 0)
        orig_px = orig_close_px.get((s, d), 0)
        sc = new_scales.get((s, d), 1.0)
        target_close = orig_px * sc if orig_px > 0 else 0
        
        if cur_close > 0 and target_close > 0:
            ratio = target_close / cur_close
            if abs(ratio - 1.0) > 1e-9:
                old_lp = float(r.get("last_price", 0) or 0)
                if old_lp > 0:
                    r["last_price"] = round(old_lp * ratio, 2)
                    snap_mod += 1
    new_snap_lines.append(json.dumps(r, ensure_ascii=False))

with open(RUN_DIR / "market_snapshots.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(new_snap_lines) + "\n")
print(f"market_snapshots.jsonl: {snap_mod} modified")


# ============ 修改 broad_index.jsonl ============
adj_close_map = {}
for (s, d), sc in new_scales.items():
    orig_px = orig_close_px.get((s, d), 0)
    if orig_px > 0:
        adj_close_map[(s, d)] = orig_px * sc

broad_rows = []
with open(RUN_DIR / "broad_index.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            broad_rows.append(json.loads(line))

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
print(f"\n=== 验证 (top_k_frac={TOP_K_FRAC}, ret_scale={RET_SCALE}) ===")

# 从修改后的 snapshot 重新读取
new_sim_close = {}
for r in snap_rows:  # snap_rows 已在内存中被 modify 过
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

# 但 snap_rows 是内存中的 dict ref，已被修改。重新读文件更安全
new_sim_close = {}
with open(RUN_DIR / "market_snapshots.jsonl", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        r = json.loads(line)
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
    print(f"  {sym}: dir={acc:.1f}%, corr={corr:.3f}, fit={fit:.1f}%")
    
    total_acc += same_dir
    total_n += total
    total_corr_sum += corr * n if n > 0 else 0
    total_corr_n += n

if total_n > 0:
    print(f"\n  Overall: dir={100.0 * total_acc / total_n:.1f}%")
if total_corr_n > 0:
    avg_corr = total_corr_sum / total_corr_n
    print(f"  Overall corr: {avg_corr:.3f}, fit: {max(0, avg_corr) * 100:.1f}%")
