"""回填 behavioral_biases.jsonl: 以 -1.5% 阈值重算 averaging_down_flag / loss_aversion_flag"""
import json, glob, shutil
from pathlib import Path

NEW_THRESHOLD = -1.5

files = sorted(glob.glob("runs/*/behavioral_biases.jsonl"))
print(f"共 {len(files)} 个文件\n")

for fpath in files:
    fpath = Path(fpath)
    # 优先从原始备份读取
    backup = fpath.with_suffix(".jsonl.bak_threshold5")
    src = backup if backup.exists() else fpath
    lines = src.read_text().splitlines()
    rows = []
    for line in lines:
        if line.strip():
            rows.append(json.loads(line))

    changed_avg = 0
    changed_la = 0
    for r in rows:
        pct = r.get("unrealized_pnl_pct")
        action = r.get("action", "")
        direction = r.get("prior_pnl_direction", "")

        in_significant_loss = (
            direction == "loss"
            and pct is not None
            and pct < NEW_THRESHOLD
        )

        new_avg = in_significant_loss and action == "buy"
        new_la = in_significant_loss and action == "hold"

        if r.get("averaging_down_flag") != new_avg:
            changed_avg += 1
        r["averaging_down_flag"] = new_avg

        if r.get("loss_aversion_flag") != new_la:
            changed_la += 1
        r["loss_aversion_flag"] = new_la

    with fpath.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    run_name = fpath.parent.name
    print(f"{run_name}: avg_down+={changed_avg}, loss_aversion+={changed_la}, rows={len(rows)}")

print("\n回填完成 (阈值 -1.5%)")
