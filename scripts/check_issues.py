"""Quick issue check"""
import os
import csv

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
with open(CSV, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

# syscalls anomalies
sc = [float(r['syscalls_rate']) for r in rows]
neg = [(i, sc[i]) for i in range(len(sc)) if sc[i] < 0]
print(f"syscalls_rate: {len(neg)} negative out of {len(sc)}")
if neg:
    neg.sort(key=lambda x: x[1])
    for idx, val in neg[:5]:
        print(f"  row {idx+1} step={rows[idx]['step']}: {val:.0f} time={rows[idx]['time']}")

# step gaps
steps = [int(r['step']) for r in rows]
gaps = []
for i in range(1, len(steps)):
    if steps[i] != steps[i-1] + 1:
        gaps.append((i, steps[i-1], steps[i]))
print(f"\nStep gaps: {len(gaps)}")
for i, prev, curr in gaps[:5]:
    print(f"  row {i+1}: {prev} -> {curr}")
