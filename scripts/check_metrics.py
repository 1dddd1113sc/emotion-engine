"""检查本机可用的系统指标"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import psutil, platform

print("=" * 50)
print("  本机可采集的系统指标清单")
print("=" * 50)

# 系统信息
print(f"\n【系统】 {platform.system()} {platform.release()} {platform.machine()}")
print(f"  CPU: {psutil.cpu_count(logical=False)}物理核 / {psutil.cpu_count(logical=True)}逻辑核")
print(f"  内存: {psutil.virtual_memory().total / 1024**3:.1f} GB")

# CPU
print(f"\n{'='*50}")
print("【CPU】")
cpu_pct = psutil.cpu_percent(interval=1)
print(f"  总使用率:     {cpu_pct}%")
print(f"  每核使用率:   {psutil.cpu_percent(interval=0, percpu=True)}")
freq = psutil.cpu_freq()
if freq:
    print(f"  频率:         当前={freq.current:.0f}MHz 最小={freq.min} 最大={freq.max}")
try:
    load = psutil.get_loadavg()
    print(f"  负载均值:     1min={load[0]:.2f} 5min={load[1]:.2f} 15min={load[2]:.2f}")
except:
    print(f"  负载均值:     Windows不支持(用CPU%替代)")
times = psutil.cpu_times()
print(f"  时间分布:     user={times.user:.1f}s system={times.system:.1f}s idle={times.idle:.1f}s")
if hasattr(times, 'iowait'):
    print(f"  IO等待:       {times.iowait:.1f}s")

# 内存
print(f"\n{'='*50}")
print("【内存】")
v = psutil.virtual_memory()
print(f"  总量:         {v.total / 1024**3:.1f} GB")
print(f"  已用:         {v.used / 1024**3:.1f} GB ({v.percent}%)")
print(f"  可用:         {v.available / 1024**3:.1f} GB")
print(f"  缓存:         {getattr(v, 'cached', 0) / 1024**3:.1f} GB")
print(f"  缓冲:         {getattr(v, 'buffers', 0) / 1024**3:.1f} GB")
s = psutil.swap_memory()
print(f"  Swap:         {s.total / 1024**3:.1f}GB 已用={s.used / 1024**3:.1f}GB ({s.percent}%)")

# 磁盘
print(f"\n{'='*50}")
print("【磁盘】")
for p in psutil.disk_partitions():
    try:
        u = psutil.disk_usage(p.mountpoint)
        print(f"  {p.mountpoint:8s} [{p.fstype}] {u.total / 1024**3:.0f}GB 已用={u.used / 1024**3:.1f}GB ({u.percent}%)")
    except:
        pass
dio = psutil.disk_io_counters()
if dio:
    print(f"  IO统计:       读={dio.read_bytes / 1024**2:.0f}MB 写={dio.write_bytes / 1024**2:.0f}MB")
    print(f"  IO次数:       读={dio.read_count} 写={dio.write_count}")

# 网络
print(f"\n{'='*50}")
print("【网络】")
n = psutil.net_io_counters()
print(f"  流量:         发送={n.bytes_sent / 1024**2:.1f}MB 接收={n.bytes_recv / 1024**2:.1f}MB")
print(f"  包数:         发送={n.packets_sent} 接收={n.packets_recv}")
print(f"  错误:         发送={n.errout} 接收={n.errin} 丢弃={n.dropin}/{n.dropout}")
try:
    conns = psutil.net_connections()
    states = {}
    for c in conns:
        states[c.status] = states.get(c.status, 0) + 1
    print(f"  连接数:       {len(conns)}")
    for s, cnt in sorted(states.items(), key=lambda x: -x[1]):
        print(f"    {s}: {cnt}")
except:
    print(f"  连接数:       需要管理员权限")

# 进程 Top10
print(f"\n{'='*50}")
print("【进程 Top10 CPU】")
all_procs = []
for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
    try:
        all_procs.append(p.info)
    except:
        pass
all_procs.sort(key=lambda x: x.get('cpu_percent', 0) or 0, reverse=True)
print(f"  总进程数:     {len(all_procs)}")
print(f"  {'PID':>6s}  {'名称':25s}  {'CPU%':>6s}  {'MEM%':>6s}")
for p in all_procs[:10]:
    print(f"  {p['pid']:>6d}  {(p['name'] or ''):25s}  {p.get('cpu_percent', 0) or 0:5.1f}%  {p.get('memory_percent', 0) or 0:5.1f}%")

# 传感器
print(f"\n{'='*50}")
print("【传感器】")
try:
    temps = psutil.sensors_temperatures()
    if temps:
        for name, entries in temps.items():
            for e in entries:
                print(f"  温度 {name}/{e.label}: {e.current}°C (高={e.high} 危={e.critical})")
    else:
        print("  温度: 无数据")
except:
    print("  温度: 不支持")

try:
    fans = psutil.sensors_fans()
    if fans:
        for name, entries in fans.items():
            for e in entries:
                print(f"  风扇 {name}/{e.label}: {e.current} RPM")
    else:
        print("  风扇: 无数据")
except:
    print("  风扇: 不支持")

try:
    bat = psutil.sensors_battery()
    if bat:
        print(f"  电池: {bat.percent}% {'充电中' if bat.power_plugged else '放电中'}")
        if bat.secsleft != psutil.POWER_TIME_UNLIMITED:
            print(f"  剩余时间: {bat.secsleft // 60}分钟")
    else:
        print("  电池: 无(台式机)")
except:
    print("  电池: 不支持")

# 汇总：可用于情绪引擎的指标
print(f"\n{'='*50}")
print("【情绪引擎可用指标汇总】")
print("""
  一级指标（直接可用，延迟<1ms）:
    cpu_percent        → Arousal 主驱动
    memory_percent     → Arousal 辅助
    disk_io.read/write → Arousal IO负载
    net_io.bytes       → Arousal 网络负载

  二级指标（需要计算/累积）:
    cpu_times.iowait   → 紧绷度（IO等待=系统卡顿）
    load_average       → 疲劳度（1/5/15分钟均值）
    连接状态分布       → 紧绷度（TIME_WAIT多=连接风暴）
    进程数变化率       → 波动性

  三级指标（需要额外工具）:
    温度/风扇          → 舒适度（物理层）
    错误率             → 需要从日志/监控系统获取
    响应延迟           → 需要从应用层获取
""")
