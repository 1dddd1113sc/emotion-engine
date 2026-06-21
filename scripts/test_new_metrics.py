import os
import sys, io, time, psutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
psutil.cpu_percent(interval=0)
from real_collector import RealMetricCollector
c = RealMetricCollector(interval=0.5)
r1, d1 = c.collect_once()
time.sleep(0.5)
r2, d2 = c.collect_once()
print(f"ctx_switches_rate={d2.ctx_switches_rate:.0f}/s")
print(f"interrupts_rate={d2.interrupts_rate:.0f}/s")
print(f"syscalls_rate={d2.syscalls_rate:.0f}/s")
print(f"interrupt_ratio={d2.interrupt_ratio:.4f}")
print(f"dpc_ratio={d2.dpc_ratio:.4f}")
