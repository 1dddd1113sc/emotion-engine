"""V6 数据质量扫描"""
import os
import csv, statistics

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')

with open(CSV, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

n = len(rows)
issues = []

print(f"Total: {n} samples")
print(f"Time:  {rows[0]['time']} -> {rows[-1]['time']}")
print()

def stats(field, label=None):
    vals = [float(r[field]) for r in rows]
    label = label or field
    non_neg1 = [v for v in vals if v != -1]
    if not non_neg1:
        print(f"  {label}: all -1 (no data)")
        return vals
    print(f"  {label}: avg={statistics.mean(non_neg1):.2f} min={min(non_neg1):.2f} max={max(non_neg1):.2f} stdev={statistics.stdev(non_neg1):.2f}" if len(non_neg1) > 1 else f"  {label}: {non_neg1[0]:.2f}")
    return vals

print("=== L1 计算与记忆 ===")
stats('cpu_pct', 'CPU%')
stats('mem_pct', 'MEM%')
stats('mem_avail_gb', 'MEM_AVAIL_GB')
stats('swap_pct', 'SWAP%')
stats('cpu_freq_mhz', 'FREQ_MHz')
stats('freq_ratio', 'FREQ_RATIO')
stats('freq_throttle', 'THROTTLE')
stats('cpu_overwork', 'OVERWORK')
stats('mem_pressure', 'MEM_PRESS')
stats('ctx_sw_rate', 'CTX_SW/S')
stats('syscalls_rate', 'SYSCALL/S')

print("\n=== L2 吞吐与排队 ===")
stats('conn_total', 'CONN_TOTAL')
stats('conn_estab', 'CONN_ESTAB')
stats('conn_tw', 'CONN_TW')
stats('conn_cw', 'CONN_CW')
stats('conn_listen', 'CONN_LISTEN')
stats('threads', 'THREADS')
stats('close_wait_r', 'CW_RATIO')
stats('listen_backlog', 'LISTEN_BL')
stats('thread_density', 'THR_DENSITY')

print("\n=== L3 传导与IO ===")
stats('disk_c_pct', 'DISK_C%')
stats('disk_d_pct', 'DISK_D%')
stats('io_latency_ms', 'IO_LAT_MS')
stats('read_lat_ms', 'READ_LAT_MS')
stats('write_lat_ms', 'WRITE_LAT_MS')
stats('read_iops', 'READ_IOPS')
stats('write_iops', 'WRITE_IOPS')
stats('disk_tp_mbps', 'DISK_TP_MB/s')
stats('net_tp_mbps', 'NET_TP_MB/s')
stats('net_err_rate', 'NET_ERR_RATE')
stats('disk_queue', 'DISK_QUEUE')

print("\n=== L4 业务 ===")
stats('error_rate', 'ERR_RATE')
stats('http_5xx', '5XX')
stats('p99_ms', 'P99_MS')
stats('health_score', 'HEALTH')

print("\n=== L5 物理 ===")
stats('cpu_temp', 'CPU_TEMP')
stats('gpu_temp', 'GPU_TEMP')
stats('gpu_usage', 'GPU%')
stats('gpu_mem_mb', 'GPU_MEM_MB')
stats('thermal_stress', 'THERMAL')
stats('gpu_stress', 'GPU_STRESS')

print("\n=== Body Sense ===")
stats('fatigue', 'FATIGUE')
stats('tension', 'TENSION')
stats('comfort', 'COMFORT')
stats('exhaustion', 'EXHAUST')

# === 异常检测 ===
print("\n=== Anomaly Detection ===")

cpus = [float(r['cpu_pct']) for r in rows]
mems = [float(r['mem_pct']) for r in rows]
threads = [int(r['threads']) for r in rows]

# CPU 突变
cpu_deltas = [abs(cpus[i] - cpus[i-1]) for i in range(1, len(cpus))]
big_jumps = [(i+2, cpu_deltas[i]) for i in range(len(cpu_deltas)) if cpu_deltas[i] > 20]
print(f"CPU big jumps (>20%): {len(big_jumps)}" + (f" (worst: step {big_jumps[0][0]} delta={big_jumps[0][1]:.1f}%)" if big_jumps else ""))

# MEM 趋势
half = n // 2
mem_drift = statistics.mean(mems[half:]) - statistics.mean(mems[:half])
thr_drift = statistics.mean([float(t) for t in threads[half:]]) - statistics.mean([float(t) for t in threads[:half]])
print(f"MEM drift: {mem_drift:+.2f}% ({'rising' if mem_drift > 0.5 else 'stable' if abs(mem_drift) < 0.5 else 'falling'})")
print(f"THREAD drift: {thr_drift:+.0f} ({'rising' if thr_drift > 10 else 'stable' if abs(thr_drift) < 10 else 'falling'})")

# 第一行 tension=0 检查
if float(rows[0]['tension']) == 0 and float(rows[2]['tension']) > 0:
    print("TENSION: row 1=0 (normal: tracker needs 3 samples)")

# io_latency 全 0 检查
io_lats = [float(r['io_latency_ms']) for r in rows]
nonzero = sum(1 for x in io_lats if x > 0)
print(f"IO_LATENCY: {nonzero}/{n} nonzero ({nonzero/n*100:.1f}%)")
if nonzero == 0:
    print("  -> disk completely idle during test, expected")

# L4 全 -1
if all(float(r['error_rate']) == -1 for r in rows):
    print("L4: all -1 (no service running, expected)")

# cpu_temp 全 -1
if all(float(r['cpu_temp']) == -1 for r in rows):
    print("CPU_TEMP: all -1 (WMI not available, expected)")

print("\n=== Issues ===")
# 数据合理性
if max(cpus) > 100: issues.append(f"CPU > 100%: {max(cpus)}")
if min(cpus) < 0: issues.append(f"CPU < 0%: {min(cpus)}")
if max(mems) > 100: issues.append(f"MEM > 100%: {max(mems)}")
if mem_drift > 5: issues.append(f"MEM rising fast: +{mem_drift:.1f}%")
if thr_drift > 100: issues.append(f"THREADS rising fast: +{thr_drift:.0f}")
if any(int(r['step']) != i+1 for i, r in enumerate(rows)): issues.append("Step sequence broken")
if any(r['time'] < r_prev['time'] for r, r_prev in zip(rows[1:], rows)): issues.append("Time not monotonic")

if issues:
    for i in issues:
        print(f"  ! {i}")
else:
    print("  All clear, no issues found.")
