"""检查采样间隔"""
import os
import csv
from datetime import datetime

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
with open(CSV, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

times = [datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S') for r in rows[-20:]]
print(f"Last 20 rows intervals:")
for i in range(1, len(times)):
    gap = (times[i] - times[i-1]).total_seconds()
    print(f"  {rows[-20+i-1]['time']} -> {rows[-20+i]['time']}  gap={gap:.1f}s")
