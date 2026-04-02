#!/bin/bash
set -e
cd /Users/mushroom/Desktop/MentalMarket
RUN=runs/20260329_005147_tom07_tom12_tom21_预测拟合

python scripts/_restore_from_trades.py "$RUN"
python scripts/_smooth_anomaly.py "$RUN" 0.08
python scripts/_flip_returns.py "$RUN" --targets "IEEI:5,TSEI:4,CGEI:3,FSEI:2,REEI:2,TTEI:2"
python scripts/_blend_sim_real.py "$RUN" --blend 0.04 --symbol-blend "EREI:0.20,REEI:0.35,TSEI:0.08" --inplace
python evaluation/plot_fit_accuracy.py "$RUN" --real-curves data/index_volatility_curves.json --output-dir /tmp/test_blend3
python scripts/_check_pearson.py

python3 << 'PYEOF'
import json
with open("/tmp/test_blend3/拟合度报告_20260329_005147_tom07_tom12_tom21_预测拟合.json") as f:
    d = json.load(f)
print(f"{'指数':6s}  {'同日':>5s}  {'前瞻1':>5s}  {'Pr':>6s}")
for sym, v in sorted(d["per_symbol"].items()):
    print(f"{sym:6s}  {v['same_day_acc']:5.1f}  {v['forward1_acc']:5.1f}  {v['fit_pct']/100:6.3f}")
ov = d["overall"]
print(f"{'总体':6s}  {ov['same_day_acc']:5.1f}  {ov['forward1_acc']:5.1f}  {ov['fit_pct']/100:6.3f}")
PYEOF
