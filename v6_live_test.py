"""V6 五层感官 — 本机实测数据采集"""
import os
import sys, io, time, csv, json, os
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psutil
psutil.cpu_percent(interval=0)

from real_collector import RealMetricCollector, RawMetrics, DerivedMetrics
from body_sense import BodySenseManager

DURATION = 30  # 采集秒数
INTERVAL = 1.0
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

print(f"V6 五层感官 - 本机实测 ({DURATION}s)")
print("=" * 60)

collector = RealMetricCollector(interval=INTERVAL)
mgr = BodySenseManager()

# 预热一次
time.sleep(0.5)
collector.collect_once()

rows = []
start_time = time.time()

for step in range(DURATION):
    r, d = collector.collect_once()
    
    body = mgr.update(
        load_signal=r.cpu_percent / 100.0,
        cpu_overwork=d.cpu_overwork,
        freq_throttle=d.freq_throttle,
        ctx_switches_rate=d.ctx_switches_rate,
        syscalls_rate=d.syscalls_rate,
        listen_backlog=d.listen_backlog,
        close_wait_ratio=d.close_wait_ratio,
        conn_churn_rate=d.conn_churn_rate,
        thread_density=d.thread_density,
        disk_io_latency_ms=d.disk_io_latency_ms,
        io_congestion=d.io_congestion,
        disk_queue_depth=r.disk_queue_depth,
        interrupts_rate=d.interrupts_rate,
        interrupt_ratio=d.interrupt_ratio,
        dpc_ratio=d.dpc_ratio,
        thermal_stress=d.thermal_stress,
        gpu_stress=d.gpu_stress,
        disk_usage=r.disk_usage_c,
        swap_percent=r.swap_percent,
        mem_available_gb=r.mem_available_gb,
    )
    
    row = {
        'step': step + 1,
        'time': datetime.now().strftime('%H:%M:%S'),
        # L1
        'cpu_pct': r.cpu_percent,
        'mem_pct': r.mem_percent,
        'swap_pct': r.swap_percent,
        'mem_avail_gb': round(r.mem_available_gb, 1),
        'cpu_freq_mhz': r.cpu_freq_current or 0,
        'freq_ratio': r.cpu_freq_ratio,
        'freq_throttle': round(d.freq_throttle, 3),
        'cpu_overwork': round(d.cpu_overwork, 3),
        'mem_pressure': round(d.mem_pressure, 3),
        'ctx_sw_rate': round(d.ctx_switches_rate, 0),
        'syscalls_rate': round(d.syscalls_rate, 0),
        # L2
        'conn_total': r.conn_total,
        'conn_estab': r.conn_established,
        'conn_tw': r.conn_time_wait,
        'conn_cw': r.conn_close_wait,
        'conn_listen': r.conn_listen,
        'threads': r.thread_count,
        'close_wait_r': round(d.close_wait_ratio, 3),
        'listen_backlog': round(d.listen_backlog, 3),
        'thread_density': round(d.thread_density, 1),
        # L3
        'disk_c_pct': r.disk_usage_c,
        'disk_d_pct': r.disk_usage_d,
        'io_latency_ms': round(d.disk_io_latency_ms, 2),
        'read_lat_ms': round(d.disk_read_latency_ms, 2),
        'write_lat_ms': round(d.disk_write_latency_ms, 2),
        'read_iops': round(d.disk_read_iops, 0),
        'write_iops': round(d.disk_write_iops, 0),
        'disk_tp_mbps': round(d.disk_throughput_mbps, 2),
        'net_tp_mbps': round(d.net_throughput_mbps, 2),
        'net_err_rate': round(d.net_error_rate, 6),
        'disk_queue': r.disk_queue_depth if r.disk_queue_depth is not None else -1,
        # L4
        'error_rate': r.error_rate if r.error_rate is not None else -1,
        'http_5xx': r.http_5xx_rate if r.http_5xx_rate is not None else -1,
        'p99_ms': r.response_p99_ms if r.response_p99_ms is not None else -1,
        'health_score': round(d.health_score, 3),
        # L5
        'cpu_temp': r.cpu_temp if r.cpu_temp is not None else -1,
        'gpu_temp': r.gpu_temp if r.gpu_temp is not None else -1,
        'gpu_usage': r.gpu_usage if r.gpu_usage is not None else -1,
        'gpu_mem_mb': r.gpu_mem_used_mb if r.gpu_mem_used_mb is not None else -1,
        'thermal_stress': round(d.thermal_stress, 3),
        'gpu_stress': round(d.gpu_stress, 3),
        # Body Sense
        'fatigue': round(body.fatigue, 3),
        'tension': round(body.tension, 3),
        'comfort': round(body.comfort, 3),
        'exhaustion': round(body.exhaustion_risk, 3),
    }
    rows.append(row)
    
    # 实时输出
    print(f"[{step+1:02d}] CPU={r.cpu_percent:4.1f}% MEM={r.mem_percent:4.1f}% "
          f"GPU={r.gpu_temp or 0:.0f}C "
          f"IOlat={d.disk_io_latency_ms:.1f}ms "
          f"CONN={r.conn_total} "
          f"F={body.fatigue:.2f} T={body.tension:.2f} C={body.comfort:.2f}")
    
    time.sleep(INTERVAL)

# 写 CSV
csv_path = os.path.join(OUTPUT_DIR, 'v6_test_data.csv')
with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

# 写汇总 JSON
summary = {
    'test_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'duration_sec': DURATION,
    'samples': len(rows),
    'l1': {
        'cpu_avg': round(sum(r['cpu_pct'] for r in rows) / len(rows), 1),
        'cpu_max': round(max(r['cpu_pct'] for r in rows), 1),
        'mem_avg': round(sum(r['mem_pct'] for r in rows) / len(rows), 1),
        'mem_max': round(max(r['mem_pct'] for r in rows), 1),
        'freq_throttle_avg': round(sum(r['freq_throttle'] for r in rows) / len(rows), 3),
        'overwork_avg': round(sum(r['cpu_overwork'] for r in rows) / len(rows), 3),
    },
    'l2': {
        'conn_avg': round(sum(r['conn_total'] for r in rows) / len(rows), 0),
        'conn_max': max(r['conn_total'] for r in rows),
        'cw_avg': round(sum(r['conn_cw'] for r in rows) / len(rows), 0),
        'threads_avg': round(sum(r['threads'] for r in rows) / len(rows), 0),
    },
    'l3': {
        'io_latency_avg': round(sum(r['io_latency_ms'] for r in rows) / len(rows), 2),
        'io_latency_max': round(max(r['io_latency_ms'] for r in rows), 2),
        'disk_tp_avg': round(sum(r['disk_tp_mbps'] for r in rows) / len(rows), 2),
        'net_tp_avg': round(sum(r['net_tp_mbps'] for r in rows) / len(rows), 2),
        'disk_queue_avg': round(sum(max(0, r['disk_queue']) for r in rows) / len(rows), 1),
    },
    'l4': {
        'status': 'no_service_running',
        'note': 'L4 needs a running HTTP service with /metrics endpoint',
    },
    'l5': {
        'gpu_temp_avg': round(sum(r['gpu_temp'] for r in rows if r['gpu_temp'] >= 0) / max(1, sum(1 for r in rows if r['gpu_temp'] >= 0)), 1),
        'gpu_temp_max': max((r['gpu_temp'] for r in rows if r['gpu_temp'] >= 0), default=-1),
        'gpu_usage_avg': round(sum(r['gpu_usage'] for r in rows if r['gpu_usage'] >= 0) / max(1, sum(1 for r in rows if r['gpu_usage'] >= 0)), 1),
        'thermal_stress_avg': round(sum(r['thermal_stress'] for r in rows) / len(rows), 3),
    },
    'body_sense': {
        'fatigue_avg': round(sum(r['fatigue'] for r in rows) / len(rows), 3),
        'fatigue_max': round(max(r['fatigue'] for r in rows), 3),
        'tension_avg': round(sum(r['tension'] for r in rows) / len(rows), 3),
        'tension_max': round(max(r['tension'] for r in rows), 3),
        'comfort_avg': round(sum(r['comfort'] for r in rows) / len(rows), 3),
        'comfort_min': round(min(r['comfort'] for r in rows), 3),
        'exhaustion_avg': round(sum(r['exhaustion'] for r in rows) / len(rows), 3),
    },
}

json_path = os.path.join(OUTPUT_DIR, 'v6_test_summary.json')
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print()
print("=" * 60)
print(f"CSV: {csv_path}")
print(f"JSON: {json_path}")
print()
print("Summary:")
for layer, data in summary.items():
    if isinstance(data, dict) and layer not in ('test_time', 'duration_sec', 'samples'):
        print(f"  {layer}: {json.dumps(data, ensure_ascii=False)}")
print("=" * 60)
