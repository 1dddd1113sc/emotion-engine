"""检查 psutil 可用的额外指标"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import psutil

print("=== cpu_stats ===")
cs = psutil.cpu_stats()
print(f"  ctx_switches: {cs.ctx_switches}")
print(f"  interrupts: {cs.interrupts}")
print(f"  soft_interrupts: {cs.soft_interrupts}")
print(f"  syscalls: {cs.syscalls}")

print("\n=== cpu_times ===")
ct = psutil.cpu_times()
for attr in ['user', 'system', 'idle', 'iowait', 'interrupt', 'dpc']:
    val = getattr(ct, attr, 'N/A')
    print(f"  {attr}: {val}")

print("\n=== cpu_times_percent ===")
ctp = psutil.cpu_times_percent(interval=0)
for attr in ['user', 'system', 'idle', 'iowait', 'interrupt', 'dpc']:
    val = getattr(ctp, attr, 'N/A')
    print(f"  {attr}: {val}")

print("\n=== net_connections (top5 states) ===")
try:
    conns = psutil.net_connections()
    states = {}
    for c in conns:
        states[c.status] = states.get(c.status, 0) + 1
    for s, cnt in sorted(states.items(), key=lambda x: -x[1])[:5]:
        print(f"  {s}: {cnt}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== disk_io_counters (perdisk) ===")
try:
    dio = psutil.disk_io_counters(perdisk=True)
    for name, counters in list(dio.items())[:3]:
        print(f"  {name}: read={counters.read_bytes/1024**2:.0f}MB write={counters.write_bytes/1024**2:.0f}MB")
except Exception as e:
    print(f"  Error: {e}")
