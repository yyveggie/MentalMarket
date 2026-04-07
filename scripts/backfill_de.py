#!/usr/bin/env python3
"""Backfill de_odean / pgr / plr for experiments where they are all None."""
import json, os, shutil
from collections import defaultdict

RUNS = [
    ("tom0", "runs/20260322_132820_tom0"),
    ("tom1", "runs/20260322_231352_tom1"),
    ("tom2", "runs/20260323_213251_tom2"),
]

for tag, run_dir in RUNS:
    fpath = os.path.join(run_dir, "behavioral_biases.jsonl")
    bak = fpath + ".bak_de"

    records = []
    with open(fpath) as f:
        for line in f:
            records.append(json.loads(line))
    print(f"=== {tag}: {len(records)} records ===")

    # Sort by (agent_id, sim_time) for chronological replay
    records.sort(key=lambda r: (r.get("agent_id", 0), r.get("sim_time", 0)))

    # Per-agent cumulative counters
    cum = defaultdict(lambda: {"rg": 0, "rl": 0, "ga": 0, "la": 0})
    filled = 0
    already = 0

    for r in records:
        aid = r.get("agent_id", 0)
        c = cum[aid]

        # Accumulate
        c["ga"] += r.get("gains_available", 0) or 0
        c["la"] += r.get("losses_available", 0) or 0
        c["rg"] += r.get("realized_gain", 0) or 0
        c["rl"] += r.get("realized_loss", 0) or 0

        # If already has non-None de_odean, skip
        if r.get("de_odean") is not None:
            already += 1
            continue

        # Compute PGR / PLR / DE
        pgr = round(c["rg"] / c["ga"], 4) if c["ga"] > 0 else None
        plr = round(c["rl"] / c["la"], 4) if c["la"] > 0 else None
        de = round(pgr - plr, 4) if pgr is not None and plr is not None else None

        r["pgr"] = pgr
        r["plr"] = plr
        r["de_odean"] = de
        if de is not None:
            filled += 1

    print(f"  de_odean: already={already}, filled={filled}")

    # Re-sort to original order
    records.sort(key=lambda r: (r.get("sim_time", 0), r.get("agent_id", 0)))

    if not os.path.exists(bak):
        shutil.copy2(fpath, bak)
        print(f"  backup -> {bak}")

    with open(fpath, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  written {len(records)} records")
    print()

print("Done!")
