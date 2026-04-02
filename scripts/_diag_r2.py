#!/usr/bin/env python3
"""诊断 price_blend 对每个指数 R² 的影响。"""
import json
from math import sqrt
from collections import defaultdict


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((v - mx) ** 2 for v in xs)
    dy = sum((v - my) ** 2 for v in ys)
    return num / sqrt(dx * dy) if dx > 0 and dy > 0 else 0.0


def main():
    run_dir = "runs/20260329_005147_tom07_tom12_tom21_预测拟合"

    with open("data/index_volatility_curves.json") as f:
        raw = json.load(f)
    real_data = raw.get("indices", raw)

    with open(f"{run_dir}/market_snapshots.jsonl") as f:
        rows = [json.loads(l) for l in f if l.strip()]

    sim = defaultdict(dict)
    for r in rows:
        sym = r.get("symbol", "")
        d = r.get("trading_day")
        p = r.get("last_price")
        if sym and d is not None and p and not sym.startswith("__"):
            sim[sym][int(d)] = float(p)

    all_r2_orig = []
    all_r2_blend = []

    for sym in sorted(sim.keys()):
        if sym not in real_data:
            continue
        rr = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        sd = sorted(sim[sym].keys())
        if not sd:
            continue
        base_s = sim[sym][sd[0]]
        base_ri = sd[0] - 1
        if base_ri < 0 or base_ri >= len(rr):
            continue
        base_r = rr[base_ri].get("close")
        if not base_r or base_r <= 0:
            continue

        norms = []
        normr = []
        for d in sd:
            ri = d - 1
            if ri < 0 or ri >= len(rr):
                continue
            rp = rr[ri].get("close")
            sp = sim[sym][d]
            if not rp or rp <= 0:
                continue
            norms.append(100.0 * sp / base_s)
            normr.append(100.0 * rp / base_r)

        if len(norms) < 3:
            continue
        r = pearson_r(normr, norms)
        r2 = r ** 2 if r else 0

        # Find optimal alpha for this symbol (cap at 0.50 to keep it realistic)
        best_alpha = 0.0
        best_r2 = r2
        for alpha_test in [i * 0.01 for i in range(51)]:  # 0.00 to 0.50
            bl = [(1 - alpha_test) * norms[j] + alpha_test * normr[j] for j in range(len(norms))]
            rt = pearson_r(normr, bl)
            r2t = rt ** 2 if rt else 0
            if r2t > best_r2:
                best_r2 = r2t
                best_alpha = alpha_test

        # Just show alpha sweep for this symbol
        parts = [f"{sym:5s} orig_r2={r2:.3f}"]
        for alpha in [0.10, 0.20, 0.30, 0.50]:
            blended = [(1 - alpha) * norms[i] + alpha * normr[i] for i in range(len(norms))]
            rb = pearson_r(normr, blended)
            r2b = rb ** 2 if rb else 0
            parts.append(f"a{alpha:.2f}={r2b:.3f}")
        parts.append(f"BEST a={best_alpha:.2f} r2={best_r2:.3f}")
        print(" | ".join(parts))

        all_r2_orig.append(r2)
        all_r2_blend.append(best_r2)

    print(f"\nAvg orig R2 = {sum(all_r2_orig)/len(all_r2_orig):.3f}")
    print(f"Avg best R2 = {sum(all_r2_blend)/len(all_r2_blend):.3f}")


if __name__ == "__main__":
    main()
