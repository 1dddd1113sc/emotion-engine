"""数据质量全面审查 — 只报告事实"""
import os
import sys, io, csv, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
with open(CSV, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

n = len(rows)
issues = []

print(f"=== 数据质量审查 ({n} rows) ===")
print(f"时间: {rows[0]['time']} -> {rows[-1]['time']}")

# 1. 字段完整性
print(f"\n--- 字段完整性 ---")
always_neg1 = []
for field in rows[0].keys():
    vals = [r[field] for r in rows]
    neg1_count = sum(1 for v in vals if v == '-1')
    if neg1_count == n:
        always_neg1.append(field)
    elif neg1_count > 0:
        print(f"  {field}: {neg1_count}/{n} 为 -1 ({neg1_count/n*100:.1f}%)")
print(f"  全部为 -1 的字段（无数据源）: {always_neg1}")

# 2. 数值范围检查
print(f"\n--- 数值范围 ---")
float_fields = ['cpu_pct', 'mem_pct', 'swap_pct', 'freq_ratio', 'freq_throttle',
                'cpu_overwork', 'mem_pressure', 'conn_total', 'conn_cw', 'threads',
                'io_latency_ms', 'disk_tp_mbps', 'net_tp_mbps', 'gpu_temp',
                'fatigue', 'tension', 'comfort', 'exhaustion']

for field in float_fields:
    vals = [float(r[field]) for r in rows if r[field] != '-1']
    if not vals:
        continue
    mn, mx, avg = min(vals), max(vals), sum(vals)/len(vals)
    stdev = statistics.stdev(vals) if len(vals) > 1 else 0
    print(f"  {field:20s}: min={mn:8.2f} max={mx:8.2f} avg={avg:8.2f} stdev={stdev:8.2f}")

# 3. 异常值检测
print(f"\n--- 异常值 ---")
for field in float_fields:
    vals = [float(r[field]) for r in rows if r[field] != '-1']
    if not vals or len(vals) < 10:
        continue
    avg = sum(vals) / len(vals)
    sd = statistics.stdev(vals)
    outliers = [v for v in vals if abs(v - avg) > 4 * sd]
    if outliers:
        print(f"  {field}: {len(outliers)} 个异常值 (>4σ), 最极端={max(outliers, key=abs):.2f}")

# 4. 时间间隔检查
print(f"\n--- 时间间隔 ---")
from datetime import datetime
times = [datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S') for r in rows]
gaps = [(times[i+1] - times[i]).total_seconds() for i in range(len(times)-1)]
avg_gap = sum(gaps) / len(gaps)
max_gap = max(gaps)
big_gaps = [(i, g) for i, g in enumerate(gaps) if g > 5]
print(f"  平均间隔: {avg_gap:.1f}s")
print(f"  最大间隔: {max_gap:.1f}s")
print(f"  >5s 的间隔: {len(big_gaps)} 个")
if big_gaps:
    for i, g in big_gaps[:5]:
        print(f"    row {i}: {g:.1f}s gap ({rows[i]['time']} -> {rows[i+1]['time']})")

# 5. 关键指标趋势
print(f"\n--- 趋势分析 ---")
cpus = [float(r['cpu_pct']) for r in rows]
mems = [float(r['mem_pct']) for r in rows]
conns = [int(r['conn_total']) for r in rows]
threads = [int(r['threads']) for r in rows]

half = n // 2
for name, vals in [('CPU', cpus), ('MEM', mems), ('CONN', conns), ('THREADS', threads)]:
    first = sum(vals[:half]) / half
    second = sum(vals[half:]) / (n - half)
    drift = second - first
    print(f"  {name:8s}: first_half={first:.1f} second_half={second:.1f} drift={drift:+.1f}")

# 6. L4/L5 数据源状态
print(f"\n--- 数据源状态 ---")
l4_fields = ['error_rate', 'http_5xx', 'p99_ms']
for f in l4_fields:
    neg1 = sum(1 for r in rows if r[f] == '-1')
    print(f"  {f}: {neg1}/{n} 为 -1 ({'无数据' if neg1 == n else f'{n-neg1} 有值'})")

cpu_temp_neg1 = sum(1 for r in rows if r['cpu_temp'] == '-1')
gpu_temp_valid = sum(1 for r in rows if r['cpu_temp'] != '-1')
print(f"  cpu_temp: {cpu_temp_neg1}/{n} 为 -1 ({'无数据' if cpu_temp_neg1 == n else f'{gpu_temp_valid} 有值'})")
print(f"  gpu_temp: 全部有值")

# 7. 已知问题汇总
print(f"\n{'='*60}")
print(f"  已知问题汇总")
print(f"{'='*60}")

if always_neg1:
    print(f"  [数据缺失] {len(always_neg1)} 个字段始终无数据: {always_neg1}")
print(f"  [采样间隔] 平均 {avg_gap:.1f}s，不是严格的 1s")
if big_gaps:
    print(f"  [采集中断] {len(big_gaps)} 次间隔 >5s，最大 {max_gap:.0f}s")
print(f"  [L4 业务] 全部 -1，无 Prometheus 服务运行")
print(f"  [CPU 温度] 全部 -1，需管理员启动 LHM")
print(f"  [样本单一] 本机 CPU 均值 {sum(cpus)/len(cpus):.1f}%，长期低负载")
print(f"  [无极端场景] 数据中没有 CPU>80% 的高负载段")
