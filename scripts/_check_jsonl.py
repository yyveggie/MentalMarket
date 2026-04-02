import json

f = open("runs/20260323_213251_tom2/behavioral_biases.jsonl.bak_threshold5")
lines = f.readlines()
total = len(lines)
empty = sum(1 for l in lines if not l.strip())
parseable = 0
errors = 0
for i, l in enumerate(lines):
    if not l.strip():
        continue
    try:
        json.loads(l)
        parseable += 1
    except Exception:
        errors += 1
        if errors <= 3:
            print(f"  Line {i+1} parse error: {repr(l[:120])}")
print(f"total={total}, empty={empty}, parseable={parseable}, errors={errors}")
