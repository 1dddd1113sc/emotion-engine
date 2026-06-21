"""逐个审查所有指标是否真正可用"""
import os
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psutil, time

psutil.cpu_percent(interval=0)
from real_collector import RealMetricCollector, RawMetrics, DerivedMetrics

c = RealMetricCollector(interval=1.0)
time.sleep(0.5)
r, d = c.collect_once()

print("=" * 60)
print("  指标可用性逐项审查")
print("=" * 60)

issues = []
ok_count = 0
warn_count = 0
fail_count = 0

def check(name, value, category, expect_range=None):
    global ok_count, warn_count, fail_count
    status = "OK"
    note = ""
    
    if value is None:
        status = "FAIL"
        note = "返回None，不可用"
        fail_count += 1
    elif isinstance(value, float) and value == 0.0:
        # 0可能是正常的，也可能表示不可用
        if name in ['cpu_iowait', 'error_rate', 'p99_latency_ms', 'cpu_temp', 'fan_speed',
                     'queue_depth', 'thread_pool_active', 'cache_hit_rate']:
            status = "WARN"
            note = "固定为0，可能Windows不支持"
            warn_count += 1
        else:
            status = "OK"
            note = "值为0（正常）"
            ok_count += 1
    elif isinstance(value, list) and len(value) == 0:
        status = "FAIL"
        note = "空列表"
        fail_count += 1
    else:
        status = "OK"
        note = f"值={value}"
        ok_count += 1
    
    icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}[status]
    print(f"  {icon} [{category}] {name:30s} → {note}")
    if status != "OK":
        issues.append((name, status, note))

print("\n── RawMetrics 原始指标 ──\n")

# 一级：直接可用
print("【一级：直接可用】")
check("cpu_percent", r.cpu_percent, "CPU")
check("cpu_per_core", r.cpu_per_core, "CPU")
check("mem_percent", r.mem_percent, "MEM")
check("mem_available_gb", r.mem_available_gb, "MEM")
check("swap_percent", r.swap_percent, "MEM")
check("disk_usage_c", r.disk_usage_c, "DISK")
check("disk_usage_d", r.disk_usage_d, "DISK")
check("disk_read_bytes", r.disk_read_bytes, "DISK IO")
check("disk_write_bytes", r.disk_write_bytes, "DISK IO")
check("disk_read_count", r.disk_read_count, "DISK IO")
check("disk_write_count", r.disk_write_count, "DISK IO")
check("net_sent_bytes", r.net_sent_bytes, "NET IO")
check("net_recv_bytes", r.net_recv_bytes, "NET IO")
check("net_sent_packets", r.net_sent_packets, "NET IO")
check("net_recv_packets", r.net_recv_packets, "NET IO")
check("net_errin", r.net_errin, "NET IO")
check("net_errout", r.net_errout, "NET IO")
check("net_dropin", r.net_dropin, "NET IO")
check("net_dropout", r.net_dropout, "NET IO")
check("conn_established", r.conn_established, "CONN")
check("conn_time_wait", r.conn_time_wait, "CONN")
check("conn_close_wait", r.conn_close_wait, "CONN")
check("conn_listen", r.conn_listen, "CONN")
check("conn_total", r.conn_total, "CONN")
check("process_count", r.process_count, "PROC")

# CPU时间
print("\n【CPU时间】")
check("cpu_user", r.cpu_user, "CPU TIME")
check("cpu_system", r.cpu_system, "CPU TIME")
check("cpu_idle", r.cpu_idle, "CPU TIME")
check("cpu_iowait", r.cpu_iowait, "CPU TIME")
check("cpu_interrupt", r.cpu_interrupt, "CPU TIME")
check("cpu_dpc", r.cpu_dpc, "CPU TIME")

# CPU统计
print("\n【CPU统计（增量）】")
check("ctx_switches", r.ctx_switches, "CPU STAT")
check("interrupts", r.interrupts, "CPU STAT")
check("syscalls", r.syscalls, "CPU STAT")

# 三级：不可用
print("\n【三级：标记为None/不可用】")
check("cpu_temp", r.cpu_temp, "SENSOR")
check("fan_speed", r.fan_speed, "SENSOR")
check("error_rate", r.error_rate, "APP")
check("p99_latency_ms", r.p99_latency_ms, "APP")
check("queue_depth", r.queue_depth, "APP")
check("thread_pool_active", r.thread_pool_active, "APP")
check("cache_hit_rate", r.cache_hit_rate, "APP")

print("\n── DerivedMetrics 派生指标 ──\n")

print("【疲劳度】")
check("iowait_ratio", d.iowait_ratio, "FATIGUE")
check("mem_pressure", d.mem_pressure, "FATIGUE")
check("disk_pressure", d.disk_pressure, "FATIGUE")

print("\n【紧绷度】")
check("close_wait_ratio", d.close_wait_ratio, "TENSION")
check("io_congestion", d.io_congestion, "TENSION")
check("net_error_rate", d.net_error_rate, "TENSION")

print("\n【流畅度】")
check("disk_throughput_mbps", d.disk_throughput_mbps, "FLUID")
check("net_throughput_mbps", d.net_throughput_mbps, "FLUID")

print("\n【波动性】")
check("cpu_core_variance", d.cpu_core_variance, "VOLATILE")
check("process_count_delta", d.process_count_delta, "VOLATILE")

print("\n【上下文切换/中断】")
check("ctx_switches_rate", d.ctx_switches_rate, "CTX")
check("interrupts_rate", d.interrupts_rate, "CTX")
check("syscalls_rate", d.syscalls_rate, "CTX")
check("interrupt_ratio", d.interrupt_ratio, "CTX")
check("dpc_ratio", d.dpc_ratio, "CTX")

# 汇总
print("\n" + "=" * 60)
print(f"  汇总: ✅ OK={ok_count}  ⚠️ WARN={warn_count}  ❌ FAIL={fail_count}")
print("=" * 60)

if issues:
    print("\n⚠️  问题项：")
    for name, status, note in issues:
        icon = "⚠️" if status == "WARN" else "❌"
        print(f"  {icon} {name}: {note}")

# 特别检查：iowait在Windows上的行为
print("\n── Windows 特殊行为检查 ──\n")
ct = psutil.cpu_times()
print(f"  cpu_times.iowait 存在: {hasattr(ct, 'iowait')}")
if hasattr(ct, 'iowait'):
    print(f"  cpu_times.iowait 值: {ct.iowait}")
    if ct.iowait == 0.0:
        print("  ⚠️  iowait 在 Windows 上固定为 0，DerivedMetrics.iowait_ratio 永远为 0")
        print("     → 建议：用 cpu_times.interrupt + cpu_times.dpc 替代 IO 等待信号")

# 检查 syscalls 是否可靠
print(f"\n  cpu_stats.syscalls: {r.syscalls}")
if r.syscalls == 0:
    print("  ⚠️  syscalls 在 Windows 上可能不可靠（返回0或不准确）")
