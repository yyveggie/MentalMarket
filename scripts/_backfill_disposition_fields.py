#!/usr/bin/env python3
"""回填 behavioral_biases.jsonl 中缺失的 gains_available / losses_available /
realized_gain / realized_loss / pgr / plr / de_odean 字段。

用法:
    python _backfill_disposition_fields.py <run_dir> [run_dir2 ...]

对每条记录，如果缺少 gains_available，则从基础字段推算并写回。
"""
import json
import sys
import shutil
from pathlib import Path


def backfill(run_dir: str):
    p = Path(run_dir) / "behavioral_biases.jsonl"
    if not p.exists():
        print(f"[SKIP] {p} 不存在")
        return

    # 备份
    bak = p.with_suffix(".jsonl.bak_disposition")
    if not bak.exists():
        shutil.copy2(p, bak)
        print(f"[备份] {bak}")

    rows = []
    patched = 0
    with open(p) as f:
        for line in f:
            r = json.loads(line)
            if "gains_available" not in r:
                needs_patch = True
            else:
                needs_patch = True  # 统一重算，确保口径一致

            if needs_patch:
                hc = r.get("holdings_count") or 0
                ulc = r.get("unrealized_loss_count") or 0
                gain_positions = max(0, hc - ulc)

                action = r.get("action", "")
                status = r.get("status", "")

                rg = rl = 0
                if action == "sell" and status == "ok":
                    sgp = r.get("sell_gain_pct")
                    mp = r.get("market_price")
                    abp = r.get("avg_buy_price")
                    if sgp is not None:
                        if sgp > 0:
                            rg = 1
                        elif sgp < 0:
                            rl = 1
                    elif mp is not None and abp is not None and abp > 0:
                        if mp > abp:
                            rg = 1
                        elif mp < abp:
                            rl = 1

                ga = rg + gain_positions
                la = rl + ulc

                r["gains_available"] = ga
                r["losses_available"] = la
                r["realized_gain"] = rg
                r["realized_loss"] = rl
                # pgr / plr / de_odean 是累计指标，单条记录放当日快照不太合适
                # 这里放 None，绘图时用累计方式计算
                if "pgr" not in r:
                    r["pgr"] = None
                if "plr" not in r:
                    r["plr"] = None
                if "de_odean" not in r:
                    r["de_odean"] = None
                patched += 1
            rows.append(r)

    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[完成] {p}: 共 {len(rows)} 条, 回填 {patched} 条")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _backfill_disposition_fields.py <run_dir> [run_dir2 ...]")
        sys.exit(1)
    for d in sys.argv[1:]:
        backfill(d)
