"""回填 behavioral_biases.jsonl 的 averaging_down_flag / loss_aversion_flag，阈值从 -5% 改为 -3%"""
import json, glob, shutil
from pathlib import Path

NEW_THRESHOLD = -3.0

files = sorted(glob.glob("runs/*/behavioral_biases.jsonl"))
print(f"共 {len(files)} 个文件需要回填\n")

for fpath in files:
    fpath = Path(fpath)
    rows = [json.loads(l) for l in fpath.open() if l.strip()]

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

    # 备份再写入
    backup = fpath.with_suffix(".jsonl.bak_threshold5")
    if not backup.exists():
        shutil.copy2(fpath, backup)

    with fpath.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    run_name = fpath.parent.name
    print(f"{run_name}: avg_down变更={changed_avg}, loss_aversion变更={changed_la}, 总行数={len(rows)}")

print("\n回填完成！原文件已备份为 .jsonl.bak_threshold5")
