"""V6 持续采集 — 后台运行，数据实时写 CSV"""
import sys, time, csv, os, signal
from datetime import datetime

sys.path.insert(0, r'D:\OpenClawData\.openclaw\workspace\emotion-engine')
import psutil
psutil.cpu_percent(interval=0)

from real_collector import RealMetricCollector
from body_sense import BodySenseManager

INTERVAL = 1.0  # 采集间隔（秒）
CSV_PATH = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\v6_live_data.csv'

FIELDS = [
    'time','step',
    # L1
    'cpu_pct','mem_pct','swap_pct','mem_avail_gb','cpu_freq_mhz','freq_ratio',
    'freq_throttle','cpu_overwork','mem_pressure','ctx_sw_rate','syscalls_rate',
    # L2
    'conn_total','conn_estab','conn_tw','conn_cw','conn_listen','threads',
    'close_wait_r','listen_backlog','thread_density',
    # L3
    'disk_c_pct','disk_d_pct','io_latency_ms','read_lat_ms','write_lat_ms',
    'read_iops','write_iops','disk_tp_mbps','net_tp_mbps','net_err_rate','disk_queue',
    # L4
    'error_rate','http_5xx','p99_ms','health_score',
    # L5
    'cpu_temp','gpu_temp','gpu_usage','gpu_mem_mb','thermal_stress','gpu_stress',
    # Body
    'fatigue','tension','comfort','exhaustion',
]

running = True
def stop(sig, frame):
    global running
    running = False
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

collector = RealMetricCollector(interval=INTERVAL)
mgr = BodySenseManager()

# 预热
time.sleep(0.5)
collector.collect_once()

# 写表头
write_header = not os.path.exists(CSV_PATH)
csv_file = open(CSV_PATH, 'a', newline='', encoding='utf-8-sig')
writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
if write_header:
    writer.writeheader()

print(f"V6 continuous collector started (interval={INTERVAL}s)")
print(f"CSV: {CSV_PATH}")
print(f"Press Ctrl+C to stop\n")

step = 0
try:
    while running:
        t_start = time.monotonic()
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
        step += 1

        row = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'step': step,
            'cpu_pct': r.cpu_percent, 'mem_pct': r.mem_percent,
            'swap_pct': r.swap_percent, 'mem_avail_gb': round(r.mem_available_gb, 1),
            'cpu_freq_mhz': r.cpu_freq_current or 0, 'freq_ratio': r.cpu_freq_ratio,
            'freq_throttle': round(d.freq_throttle, 3), 'cpu_overwork': round(d.cpu_overwork, 3),
            'mem_pressure': round(d.mem_pressure, 3),
            'ctx_sw_rate': round(d.ctx_switches_rate, 0), 'syscalls_rate': round(d.syscalls_rate, 0),
            'conn_total': r.conn_total, 'conn_estab': r.conn_established,
            'conn_tw': r.conn_time_wait, 'conn_cw': r.conn_close_wait,
            'conn_listen': r.conn_listen, 'threads': r.thread_count,
            'close_wait_r': round(d.close_wait_ratio, 3),
            'listen_backlog': round(d.listen_backlog, 3),
            'thread_density': round(d.thread_density, 1),
            'disk_c_pct': r.disk_usage_c, 'disk_d_pct': r.disk_usage_d,
            'io_latency_ms': round(d.disk_io_latency_ms, 2),
            'read_lat_ms': round(d.disk_read_latency_ms, 2),
            'write_lat_ms': round(d.disk_write_latency_ms, 2),
            'read_iops': round(d.disk_read_iops, 0), 'write_iops': round(d.disk_write_iops, 0),
            'disk_tp_mbps': round(d.disk_throughput_mbps, 2),
            'net_tp_mbps': round(d.net_throughput_mbps, 2),
            'net_err_rate': round(d.net_error_rate, 6),
            'disk_queue': r.disk_queue_depth if r.disk_queue_depth is not None else -1,
            'error_rate': r.error_rate if r.error_rate is not None else -1,
            'http_5xx': r.http_5xx_rate if r.http_5xx_rate is not None else -1,
            'p99_ms': r.response_p99_ms if r.response_p99_ms is not None else -1,
            'health_score': round(d.health_score, 3),
            'cpu_temp': r.cpu_temp if r.cpu_temp is not None else -1,
            'gpu_temp': r.gpu_temp if r.gpu_temp is not None else -1,
            'gpu_usage': r.gpu_usage if r.gpu_usage is not None else -1,
            'gpu_mem_mb': r.gpu_mem_used_mb if r.gpu_mem_used_mb is not None else -1,
            'thermal_stress': round(d.thermal_stress, 3), 'gpu_stress': round(d.gpu_stress, 3),
            'fatigue': round(body.fatigue, 3), 'tension': round(body.tension, 3),
            'comfort': round(body.comfort, 3), 'exhaustion': round(body.exhaustion_risk, 3),
        }

        writer.writerow(row)
        csv_file.flush()

        if step % 30 == 0:
            print(f"[{step}] CPU={r.cpu_percent:4.1f}% MEM={r.mem_percent:4.1f}% "
                  f"GPU={r.gpu_temp or 0:.0f}C CONN={r.conn_total} "
                  f"F={body.fatigue:.2f} T={body.tension:.2f} C={body.comfort:.2f} "
                  f"| {row['time']}")

        elapsed = time.monotonic() - t_start
        time.sleep(max(0, INTERVAL - elapsed))

finally:
    csv_file.close()
    print(f"\nStopped. {step} samples written to {CSV_PATH}")
