"""检查 v6_live_data.csv 数据"""
import os
import csv, sys, statistics
sys.stdout.reconfigure(encoding='utf-8')

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')

with open(CSV, encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    fields = reader.fieldnames

print(f"=== v6_live_data.csv 数据概览 ===")
print(f"总行数: {len(rows)}")
print(f"列数: {len(fields)}")
print(f"列名: {fields}")
print()

if not rows:
    print("空文件!")
    sys.exit(0)

# 时间范围
times = [r['time'] for r in rows if r.get('time')]
if times:
    print(f"时间范围: {times[0]} ~ {times[-1]}")

# 关键指标统计
key_cols = [
    'cpu_pct', 'mem_pct', 'swap_pct',
    'io_latency_ms', 'close_wait_r', 'threads',
    'error_rate', 'health_score',
    'cpu_temp', 'gpu_temp', 'thermal_stress',
    'fatigue', 'tension', 'comfort', 'exhaustion',
]

print(f"\n=== 关键指标统计 ===")
for col in key_cols:
    vals = []
    for r in rows:
        v = r.get(col, '')
        if v and v != '-1' and v != '':
            try:
                vals.append(float(v))
            except ValueError:
                pass
    if vals:
        avg = statistics.mean(vals)
        mn = min(vals)
        mx = max(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0
        print(f"  {col:20s}: n={len(vals):5d}  avg={avg:8.2f}  min={mn:8.2f}  max={mx:8.2f}  std={std:8.2f}")
    else:
        print(f"  {col:20s}: 无有效数据")

# 体感维度检查
print(f"\n=== 体感维度预期检查 ===")
fatigues = [float(r['fatigue']) for r in rows if r.get('fatigue') and r['fatigue'] != '-1']
tensions = [float(r['tension']) for r in rows if r.get('tension') and r['tension'] != '-1']
comforts = [float(r['comfort']) for r in rows if r.get('comfort') and r['comfort'] != '-1']

if fatigues:
    print(f"  Fatigue: avg={statistics.mean(fatigues):.3f} range=[{min(fatigues):.3f}, {max(fatigues):.3f}]")
    if max(fatigues) > 1.0 or min(fatigues) < 0.0:
        print(f"    WARNING: Fatigue 超出 [0,1] 范围!")
    else:
        print(f"    OK: Fatigue 在 [0,1] 范围内")

if tensions:
    print(f"  Tension: avg={statistics.mean(tensions):.3f} range=[{min(tensions):.3f}, {max(tensions):.3f}]")
    if max(tensions) > 1.0 or min(tensions) < 0.0:
        print(f"    WARNING: Tension 超出 [0,1] 范围!")
    else:
        print(f"    OK: Tension 在 [0,1] 范围内")

if comforts:
    print(f"  Comfort: avg={statistics.mean(comforts):.3f} range=[{min(comforts):.3f}, {max(comforts):.3f}]")
    if max(comforts) > 1.0 or min(comforts) < 0.0:
        print(f"    WARNING: Comfort 超出 [0,1] 范围!")
    else:
        print(f"    OK: Comfort 在 [0,1] 范围内")

# CPU 与 Fatigue 相关性
if fatigues and len(fatigues) > 10:
    cpus = [float(r['cpu_pct']) for r in rows if r.get('cpu_pct') and r['cpu_pct'] != '-1']
    if len(cpus) == len(fatigues):
        # 简单相关性
        n = min(len(cpus), len(fatigues))
        avg_c = sum(cpus[:n]) / n
        avg_f = sum(fatigues[:n]) / n
        cov = sum((cpus[i] - avg_c) * (fatigues[i] - avg_f) for i in range(n)) / n
        std_c = (sum((c - avg_c)**2 for c in cpus[:n]) / n) ** 0.5
        std_f = (sum((f - avg_f)**2 for f in fatigues[:n]) / n) ** 0.5
        corr = cov / (std_c * std_f) if std_c > 0 and std_f > 0 else 0
        print(f"\n  CPU-Fatigue 相关系数: {corr:.3f}")
        if corr > 0.5:
            print(f"    OK: 正相关，CPU 高时 Fatigue 高")
        elif corr > 0.2:
            print(f"    OK: 弱正相关")
        else:
            print(f"    WARNING: 相关性不足，可能体感计算有问题")
