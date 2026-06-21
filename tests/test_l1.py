"""L1 指标验证"""
import os
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psutil
psutil.cpu_percent(interval=0)
from real_collector import RealMetricCollector, format_metrics

print("=" * 60)
print("  L1 计算与记忆层 — 新增指标验证")
print("=" * 60)

c = RealMetricCollector(interval=0.5)
time.sleep(0.3)
r, d = c.collect_once()

print(f"\n【原始指标】")
print(f"  cpu_percent:      {r.cpu_percent}%")
print(f"  cpu_freq_current: {r.cpu_freq_current} MHz")
print(f"  cpu_freq_max:     {r.cpu_freq_max} MHz")
print(f"  cpu_freq_ratio:   {r.cpu_freq_ratio:.3f} ({r.cpu_freq_ratio:.0%})")
print(f"  load_average_1m:  {r.load_average_1m}")
print(f"  load_average_5m:  {r.load_average_5m}")
print(f"  load_average_15m: {r.load_average_15m}")
print(f"  mem_percent:      {r.mem_percent}%")
print(f"  mem_available_gb: {r.mem_available_gb:.1f} GB")
print(f"  swap_percent:     {r.swap_percent}%")

print(f"\n【派生指标】")
print(f"  freq_throttle:    {d.freq_throttle:.3f} (降频惩罚, 0=满速)")
print(f"  cpu_overwork:     {d.cpu_overwork:.3f} (综合过劳度)")
print(f"  mem_pressure:     {d.mem_pressure:.3f}")
print(f"  disk_pressure:    {d.disk_pressure:.3f}")

print(f"\n【格式化输出】")
print(f"  {format_metrics(r, d)}")

print(f"\n【体感集成测试】")
from body_sense import BodySenseManager
mgr = BodySenseManager()
body = mgr.update(
    load_signal=r.cpu_percent / 100.0,
    signals=[0.5, 0.5, 0.5, 0.5],
    disk_usage=r.disk_usage_c,
    swap_percent=r.swap_percent,
    mem_available_gb=r.mem_available_gb,
    cpu_overwork=d.cpu_overwork,
    freq_throttle=d.freq_throttle,
)
print(f"  疲劳={body.fatigue:.3f} 紧绷={body.tension:.3f} 舒适={body.comfort:.2f}")

print(f"\n{'=' * 60}")
print("  ✅ L1 指标全部接入成功")
