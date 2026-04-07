#!/usr/bin/env python3
"""Backfill lambda_estimate and loss_trading_flag for tom2."""
import json, os, shutil
from collections import defaultdict

OVERCONF_THRESHOLD = 0.5
run_dir = "runs/20260323_213251_tom2"
fpath = os.path.join(run_dir, "behavioral_biases.jsonl")
bak = fpath + ".bak_lambda_lt"

# If tom2 was partially written, restore from backup first
if os.path.exists(bak):
    shutil.copy2(bak, fpath)
    print("Restored from backup")

records = []
with open(fpath) as f:
    for line in f:
        records.append(json.loads(line))
print(f"tom2: {len(records)} records")

records.sort(key=lambda r: (r.get("agent_id", 0), r.get("sim_time", 0)))

# Pass 1: max daily_trade_count per (agent_id, day)
max_dtc = defaultdict(int)
for r in records:
    aid, day = r.get("agent_id", 0), r.get("trading_day", 0)
    dtc = r.get("daily_trade_count", 0) or 0
    k = (aid, day)
    if dtc > max_dtc[k]:
        max_dtc[k] = dtc

agent_days = defaultdict(list)
for (aid, day), mx in max_dtc.items():
    agent_days[aid].append((day, mx))
for aid in agent_days:
    agent_days[aid].sort()

agent_cum_before = {}
for aid, daylist in agent_days.items():
    cum, before = 0, {}
    for d, mx in daylist:
        before[d] = cum
        cum += mx
    agent_cum_before[aid] = before

# Pass 2: backfill
agent_gm = defaultdict(list)
agent_lm = defaultdict(list)
filled_lambda = filled_lt = already_lambda = already_lt = 0

for r in records:
    aid = r.get("agent_id", 0)
    action = str(r.get("action", "")).strip().lower()
    status = str(r.get("status", "")).strip().lower()
    tp = r.get("target_price", 0)
    abp = r.get("avg_buy_price", 0)

    if action == "sell" and status == "ok" and abp and abp > 0:
        pnl = abs((tp - abp) / abp * 100.0)
        if tp > abp:
            agent_gm[aid].append(round(pnl, 4))
            if len(agent_gm[aid]) > 200:
                agent_gm[aid] = agent_gm[aid][-200:]
        elif tp < abp:
            agent_lm[aid].append(round(pnl, 4))
            if len(agent_lm[aid]) > 200:
                agent_lm[aid] = agent_lm[aid][-200:]

    gm, lm = agent_gm[aid], agent_lm[aid]
    new_lam = None
    if gm and lm:
        ag = sum(gm) / len(gm)
        al = sum(lm) / len(lm)
        if ag > 0.01:
            new_lam = round(al / ag, 4)

    if "lambda_estimate" in r and r["lambda_estimate"] is not None:
        already_lambda += 1
    else:
        r["lambda_estimate"] = new_lam
        if new_lam is not None:
            filled_lambda += 1

    day = r.get("trading_day", 0)
    dtc = r.get("daily_trade_count", 0) or 0
    cb = agent_cum_before.get(aid, {}).get(day, 0)
    ttc = cb + dtc
    cr = r.get("cumulative_return_pct", 0) or 0
    tr = r.get("turnover_rate", 0) or 0
    new_lt = cr < -3.0 and ttc >= 10 and tr > OVERCONF_THRESHOLD * 0.5

    if "loss_trading_flag" in r and r["loss_trading_flag"] is not None:
        already_lt += 1
    else:
        r["loss_trading_flag"] = new_lt
        filled_lt += 1

print(f"  lambda: already={already_lambda}, filled={filled_lambda}")
print(f"  loss_trading: already={already_lt}, filled={filled_lt}")

records.sort(key=lambda r: (r.get("sim_time", 0), r.get("agent_id", 0)))
if not os.path.exists(bak):
    shutil.copy2(fpath, bak)
    print(f"  backup -> {bak}")
with open(fpath, "w") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"  written {len(records)} records. Done!")
