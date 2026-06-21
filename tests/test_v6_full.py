"""V6 五层感官 — 全量验证"""
import os
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psutil
psutil.cpu_percent(interval=0)

from real_collector import RealMetricCollector, format_metrics, RawMetrics, DerivedMetrics
from body_sense import BodySenseManager

print("=" * 70)
print("  V6 五层感官架构 — 全量指标验证")
print("=" * 70)

c = RealMetricCollector(interval=1.0)
time.sleep(0.5)
r, d = c.collect_once()

# === L1 ===
print("\n【L1 计算与记忆层 → Fatigue】")
print(f"  cpu_percent:       {r.cpu_percent}%")
print(f"  cpu_per_core:      {r.cpu_per_core[:4]}... ({len(r.cpu_per_core)}核)")
print(f"  cpu_user/system:   {r.cpu_user:.1f} / {r.cpu_system:.1f}")
print(f"  cpu_freq:          {r.cpu_freq_current}/{r.cpu_freq_max} MHz (ratio={r.cpu_freq_ratio:.3f})")
print(f"  load_avg:          {r.load_average_1m} (Windows=None)")
print(f"  mem_percent:       {r.mem_percent}%")
print(f"  mem_available:     {r.mem_available_gb:.1f} GB")
print(f"  swap:              {r.swap_percent}%")
print(f"  process_count:     {r.process_count}")
print(f"  → freq_throttle:   {d.freq_throttle:.3f}")
print(f"  → cpu_overwork:    {d.cpu_overwork:.3f}")
print(f"  → mem_pressure:    {d.mem_pressure:.3f}")

# === L2 ===
print("\n【L2 吞吐与排队层 → Stress】")
print(f"  conn_established:  {r.conn_established}")
print(f"  conn_listen:       {r.conn_listen}")
print(f"  conn_time_wait:    {r.conn_time_wait}")
print(f"  conn_close_wait:   {r.conn_close_wait}")
print(f"  conn_total:        {r.conn_total}")
print(f"  thread_count:      {r.thread_count}")
print(f"  → close_wait_ratio: {d.close_wait_ratio:.3f}")
print(f"  → listen_backlog:  {d.listen_backlog:.3f}")
print(f"  → thread_density:  {d.thread_density:.1f}")

# === L3 ===
print("\n【L3 传导与IO层 → Stress + Flow】")
print(f"  disk_usage_c:      {r.disk_usage_c}%")
print(f"  disk_read/write:   {r.disk_read_count}/{r.disk_write_count} ops")
print(f"  disk_io_time:      read={r.disk_read_time_ms}ms write={r.disk_write_time_ms}ms")
print(f"  net_sent/recv:     {r.net_sent_bytes/1024**2:.1f}/{r.net_recv_bytes/1024**2:.1f} MB")
print(f"  net_err:           in={r.net_errin} out={r.net_errout} drop={r.net_dropin}/{r.net_dropout}")
print(f"  → io_latency:      {d.disk_io_latency_ms:.2f} ms")
print(f"  → read_latency:    {d.disk_read_latency_ms:.2f} ms")
print(f"  → write_latency:   {d.disk_write_latency_ms:.2f} ms")
print(f"  → iops:            R={d.disk_read_iops:.0f} W={d.disk_write_iops:.0f}")
print(f"  → throughput:      {d.disk_throughput_mbps:.2f} MB/s")
print(f"  → net_throughput:  {d.net_throughput_mbps:.2f} MB/s")
print(f"  → net_error_rate:  {d.net_error_rate:.6f}")

# === L4 ===
print("\n【L4 业务表现层 → Flow / Confusion】")
print(f"  error_rate:        {r.error_rate} (需外部注入)")
print(f"  http_5xx_rate:     {r.http_5xx_rate} (需外部注入)")
print(f"  response_p99_ms:   {r.response_p99_ms} (需外部注入)")
print(f"  throughput_rps:    {r.throughput_rps} (需外部注入)")
print(f"  → process_crash:   {d.process_crash_rate:.3f} (代理指标)")
print(f"  → health_score:    {d.health_score:.3f}")

# === L5 ===
print("\n【L5 物理硬件层 → 终极 Fatigue】")
print(f"  cpu_temp:          {r.cpu_temp} {'°C' if r.cpu_temp else '(WMI不可用)'}")
print(f"  gpu_temp:          {r.gpu_temp}°C" if r.gpu_temp else "  gpu_temp:          N/A")
print(f"  gpu_usage:         {r.gpu_usage}%" if r.gpu_usage is not None else "  gpu_usage:         N/A")
print(f"  gpu_mem:           {r.gpu_mem_used_mb}/{r.gpu_mem_total_mb} MB" if r.gpu_mem_used_mb else "  gpu_mem:           N/A")
print(f"  disk_queue_depth:  {r.disk_queue_depth}" if r.disk_queue_depth is not None else "  disk_queue_depth:  N/A")
print(f"  → thermal_stress:  {d.thermal_stress:.3f}")
print(f"  → gpu_stress:      {d.gpu_stress:.3f}")

# === 体感集成 ===
print("\n" + "=" * 70)
print("  体感集成测试")
print("=" * 70)

mgr = BodySenseManager()
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
print(f"  疲劳={body.fatigue:.3f} 紧绷={body.tension:.3f} 舒适={body.comfort:.2f} 耗竭={body.exhaustion_risk:.3f}")

# === 格式化 ===
print(f"\n  {format_metrics(r, d)}")

# === 指标统计 ===
total_raw = len([f for f in r.__dataclass_fields__ if f != 'timestamp'])
total_derived = len([f for f in d.__dataclass_fields__ if f != 'timestamp'])
none_count = sum(1 for f in r.__dataclass_fields__ if f != 'timestamp' and getattr(r, f) is None)
available = total_raw - none_count

print(f"\n{'=' * 70}")
print(f"  指标统计: 原始={total_raw}个 派生={total_derived}个")
print(f"  可用={available}个 None={none_count}个")
print(f"  覆盖率={available/total_raw*100:.0f}%")
print(f"{'=' * 70}")
