"""
真实系统指标采集器 V6 — 五层感官架构

L1 计算与记忆层 → Fatigue
L2 吞吐与排队层 → Stress
L3 传导与IO层   → Stress + Flow
L4 业务表现层   → Flow / Confusion
L5 物理硬件层   → 终极 Fatigue

采集源：psutil + WMI + nvidia-smi + Prometheus
"""
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from l4_metrics import L4Collector


@dataclass
class RawMetrics:
    """一次采集的原始指标快照"""
    timestamp: float

    # ========== L1 计算与记忆层 ==========
    cpu_percent: float = 0.0
    cpu_per_core: list[float] = field(default_factory=list)
    cpu_user: float = 0.0
    cpu_system: float = 0.0
    cpu_idle: float = 0.0
    cpu_iowait: float = 0.0
    cpu_interrupt: float = 0.0
    cpu_dpc: float = 0.0
    ctx_switches: int = 0
    interrupts: int = 0
    syscalls: int = 0
    cpu_freq_current: float | None = None
    cpu_freq_max: float | None = None
    cpu_freq_ratio: float = 1.0
    load_average_1m: float | None = None
    load_average_5m: float | None = None
    load_average_15m: float | None = None
    mem_percent: float = 0.0
    mem_available_gb: float = 0.0
    swap_percent: float = 0.0
    process_count: int = 0

    # ========== L2 吞吐与排队层 ==========
    conn_established: int = 0
    conn_time_wait: int = 0
    conn_close_wait: int = 0
    conn_listen: int = 0
    conn_total: int = 0
    thread_count: int = 0                # 系统总线程数

    # ========== L3 传导与IO层 ==========
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    disk_read_count: int = 0
    disk_write_count: int = 0
    disk_read_time_ms: int = 0           # 累计读取耗时(ms)
    disk_write_time_ms: int = 0          # 累计写入耗时(ms)
    disk_usage_c: float = 0.0
    disk_usage_d: float = 0.0
    net_sent_bytes: int = 0
    net_recv_bytes: int = 0
    net_sent_packets: int = 0
    net_recv_packets: int = 0
    net_errin: int = 0
    net_errout: int = 0
    net_dropin: int = 0
    net_dropout: int = 0

    # ========== L4 业务表现层 ==========
    # 以下指标需要外部注入（APM/日志/Prometheus）
    # 采集器提供接口，无数据时为 None
    error_rate: float | None = None          # 业务错误率
    http_5xx_rate: float | None = None       # 5xx 错误率
    http_4xx_rate: float | None = None       # 4xx 错误率
    response_p50_ms: float | None = None     # P50 响应时间
    response_p99_ms: float | None = None     # P99 响应时间
    throughput_rps: float | None = None      # 每秒请求数
    timeout_rate: float | None = None        # 超时率
    cache_hit_rate: float | None = None      # 缓存命中率

    # ========== L5 物理硬件层 ==========
    cpu_temp: float | None = None            # CPU 温度(°C)
    fan_speed: float | None = None           # 风扇转速(RPM)
    gpu_temp: float | None = None            # GPU 温度(°C)
    gpu_usage: float | None = None           # GPU 使用率(%)
    gpu_mem_used_mb: float | None = None     # GPU 显存已用(MB)
    gpu_mem_total_mb: float | None = None    # GPU 显存总量(MB)
    disk_queue_depth: float | None = None    # 磁盘队列深度


@dataclass
class DerivedMetrics:
    """派生指标"""
    timestamp: float

    # L1 疲劳度
    iowait_ratio: float = 0.0
    mem_pressure: float = 0.0
    disk_pressure: float = 0.0
    freq_throttle: float = 0.0
    cpu_overwork: float = 0.0

    # L2 紧绷度
    close_wait_ratio: float = 0.0
    listen_backlog: float = 0.0              # 监听积压比
    thread_density: float = 0.0              # 线程密度（线程/进程比）
    conn_churn_rate: float = 0.0             # 连接变动率

    # L3 流畅度
    disk_io_latency_ms: float = 0.0          # 磁盘IO平均延迟(ms)
    disk_read_latency_ms: float = 0.0        # 读延迟
    disk_write_latency_ms: float = 0.0       # 写延迟
    disk_throughput_mbps: float = 0.0
    disk_read_iops: float = 0.0              # 读IOPS
    disk_write_iops: float = 0.0             # 写IOPS
    net_throughput_mbps: float = 0.0
    net_error_rate: float = 0.0
    io_congestion: float = 0.0

    # L4 业务
    process_crash_rate: float = 0.0          # 进程崩溃率（代理指标）
    health_score: float = 1.0                # 综合健康分 [0,1]

    # L5 物理
    thermal_stress: float = 0.0              # 温度压力 [0,1]
    gpu_stress: float = 0.0                  # GPU压力 [0,1]

    # 通用
    cpu_core_variance: float = 0.0
    process_count_delta: float = 0.0
    ctx_switches_rate: float = 0.0
    interrupts_rate: float = 0.0
    syscalls_rate: float = 0.0
    interrupt_ratio: float = 0.0
    dpc_ratio: float = 0.0


class RealMetricCollector:
    """V6 五层感官采集器"""

    def __init__(self, interval: float = 1.0, l4_url: str | None = None):
        """
        参数：
            interval: 采集间隔（秒）
            l4_url:   Prometheus metrics 端点，如 'http://localhost:8000'
                      None 则不采集 L4 业务指标
        """
        self.interval = interval
        self._prev_raw: RawMetrics | None = None
        self._prev_time: float = 0
        self._window_size = 10
        self._cpu_history: list[float] = []
        self._mem_history: list[float] = []
        self._process_count_history: list[int] = []
        # GPU 采集缓存
        self._gpu_cache: dict | None = None
        self._gpu_cache_time: float = 0
        self._gpu_cache_ttl: float = 2.0
        # L4 Prometheus 采集器
        self._l4 = None
        if l4_url:
            try:
                from l4_metrics import L4Collector
                self._l4 = L4Collector(l4_url)
            except ImportError:
                pass  # l4_metrics 模块不存在则跳过

    def _collect_gpu(self) -> dict | None:
        """采集 GPU 指标（nvidia-smi，带缓存）"""
        now = time.time()
        if self._gpu_cache and (now - self._gpu_cache_time) < self._gpu_cache_ttl:
            return self._gpu_cache

        try:
            import subprocess
            r = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = [p.strip() for p in r.stdout.strip().split(',')]
                if len(parts) >= 4:
                    self._gpu_cache = {
                        'temp': float(parts[0]),
                        'usage': float(parts[1]),
                        'mem_used': float(parts[2]),
                        'mem_total': float(parts[3]),
                    }
                    self._gpu_cache_time = now
                    return self._gpu_cache
        except Exception:
            pass
        return self._gpu_cache  # 返回旧缓存或 None

    def collect_once(self) -> tuple[RawMetrics, DerivedMetrics]:
        import psutil

        now = time.time()
        raw = RawMetrics(timestamp=now)

        # ===== L1 计算与记忆层 =====
        raw.cpu_percent = psutil.cpu_percent(interval=0)
        raw.cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)
        ct = psutil.cpu_times()
        raw.cpu_user = ct.user
        raw.cpu_system = ct.system
        raw.cpu_idle = ct.idle
        raw.cpu_iowait = getattr(ct, 'iowait', 0.0)
        raw.cpu_interrupt = getattr(ct, 'interrupt', 0.0)
        raw.cpu_dpc = getattr(ct, 'dpc', 0.0)

        try:
            cs = psutil.cpu_stats()
            raw.ctx_switches = cs.ctx_switches
            raw.interrupts = cs.interrupts
            raw.syscalls = cs.syscalls
        except Exception:
            pass

        try:
            freq = psutil.cpu_freq()
            if freq:
                raw.cpu_freq_current = freq.current
                raw.cpu_freq_max = freq.max if freq.max > 0 else freq.current
                if raw.cpu_freq_max and raw.cpu_freq_max > 0:
                    raw.cpu_freq_ratio = freq.current / raw.cpu_freq_max
        except Exception:
            pass

        try:
            import os
            if hasattr(os, 'getloadavg'):
                la1, la5, la15 = os.getloadavg()
                raw.load_average_1m = la1
                raw.load_average_5m = la5
                raw.load_average_15m = la15
        except Exception:
            pass

        v = psutil.virtual_memory()
        raw.mem_percent = v.percent
        raw.mem_available_gb = v.available / 1024**3
        s = psutil.swap_memory()
        raw.swap_percent = s.percent
        raw.process_count = len(list(psutil.process_iter()))

        # ===== L2 吞吐与排队层 =====
        try:
            conns = psutil.net_connections()
            for c in conns:
                raw.conn_total += 1
                if c.status == 'ESTABLISHED':
                    raw.conn_established += 1
                elif c.status == 'TIME_WAIT':
                    raw.conn_time_wait += 1
                elif c.status == 'CLOSE_WAIT':
                    raw.conn_close_wait += 1
                elif c.status == 'LISTEN':
                    raw.conn_listen += 1
        except Exception:
            pass

        # 线程数和句柄数
        try:
            raw.thread_count = psutil.os.sysconf('SC_THREAD_THREADS_MAX') if hasattr(psutil.os, 'sysconf') else 0
        except Exception:
            pass
        # 线程数：缓存 10 秒（遍历进程很慢 ~3.7s）
        now_ts = time.time()
        if not hasattr(self, '_thread_cache') or now_ts - self._thread_cache_time > 10:
            try:
                total_threads = 0
                for p in psutil.process_iter(['num_threads']):
                    try:
                        total_threads += p.info.get('num_threads', 0) or 0
                    except Exception:
                        pass
                raw.thread_count = total_threads
                self._thread_cache = total_threads
                self._thread_cache_time = now_ts
            except Exception:
                pass
        else:
            raw.thread_count = self._thread_cache if hasattr(self, '_thread_cache') else 0

        # ===== L3 传导与IO层 =====
        try:
            raw.disk_usage_c = psutil.disk_usage('C:\\').percent
        except Exception:
            pass
        try:
            raw.disk_usage_d = psutil.disk_usage('D:\\').percent
        except Exception:
            pass

        dio = psutil.disk_io_counters()
        if dio:
            raw.disk_read_bytes = dio.read_bytes
            raw.disk_write_bytes = dio.write_bytes
            raw.disk_read_count = dio.read_count
            raw.disk_write_count = dio.write_count
            raw.disk_read_time_ms = dio.read_time
            raw.disk_write_time_ms = dio.write_time

        nio = psutil.net_io_counters()
        if nio:
            raw.net_sent_bytes = nio.bytes_sent
            raw.net_recv_bytes = nio.bytes_recv
            raw.net_sent_packets = nio.packets_sent
            raw.net_recv_packets = nio.packets_recv
            raw.net_errin = nio.errin
            raw.net_errout = nio.errout
            raw.net_dropin = nio.dropin
            raw.net_dropout = nio.dropout

        # ===== L4 业务表现层 =====
        if self._l4:
            try:
                l4snap = self._l4.scrape()
                raw.error_rate = l4snap.error_rate if l4snap.total_requests > 0 else None
                raw.http_5xx_rate = l4snap.http_5xx_rate if l4snap.total_requests > 0 else None
                raw.http_4xx_rate = l4snap.http_4xx_rate if l4snap.total_requests > 0 else None
                raw.response_p50_ms = l4snap.latency_p50 * 1000 if l4snap.latency_p50 > 0 else None
                raw.response_p99_ms = l4snap.latency_p99 * 1000 if l4snap.latency_p99 > 0 else None
                raw.throughput_rps = l4snap.requests_per_second if l4snap.requests_per_second > 0 else None
                raw.timeout_rate = l4snap.timeout_rate if l4snap.timeout_count > 0 else None
            except Exception:
                pass  # L4 采集失败不影响其他层

        # ===== L5 物理硬件层 =====
        # CPU/GPU 温度：LibreHardwareMonitor DLL 直连
        try:
            from l5_temp import read_temperatures
            temps = read_temperatures()
            raw.cpu_temp = temps.get('cpu_temp')
            if temps.get('gpu_temp'):
                raw.gpu_temp = temps['gpu_temp']
        except Exception:
            pass

        # GPU：nvidia-smi（带缓存）
        gpu = self._collect_gpu()
        if gpu:
            raw.gpu_temp = gpu['temp']
            raw.gpu_usage = gpu['usage']
            raw.gpu_mem_used_mb = gpu['mem_used']
            raw.gpu_mem_total_mb = gpu['mem_total']

        # 磁盘队列深度：WMI
        try:
            import wmi
            c = wmi.WMI(namespace=r'root\cimv2')
            disks = c.Win32_PerfFormattedData_PerfDisk_PhysicalDisk()
            for d in disks:
                if d.Name == '_Total':
                    raw.disk_queue_depth = float(d.CurrentDiskQueueLength)
                    break
        except Exception:
            raw.disk_queue_depth = None

        # ========== 派生指标 ==========
        derived = DerivedMetrics(timestamp=now)

        # --- L1 疲劳度 ---
        total_cpu = raw.cpu_user + raw.cpu_system + raw.cpu_idle
        if total_cpu > 0:
            derived.iowait_ratio = raw.cpu_iowait / total_cpu
        derived.mem_pressure = max(0, (raw.mem_percent - 60) / 40)
        derived.disk_pressure = max(0, (raw.disk_usage_c - 70) / 30)
        if raw.cpu_freq_ratio < 1.0:
            derived.freq_throttle = max(0, (1.0 - raw.cpu_freq_ratio) / 0.5)
        cpu_load = max(0, (raw.cpu_percent - 60) / 40)
        derived.cpu_overwork = min(1.0, cpu_load * 0.7 + derived.freq_throttle * 0.3)

        # --- L2 紧绷度 ---
        if raw.conn_total > 0:
            derived.close_wait_ratio = raw.conn_close_wait / raw.conn_total
        if raw.conn_total > 0:
            derived.listen_backlog = raw.conn_listen / raw.conn_total
        if raw.process_count > 0:
            derived.thread_density = raw.thread_count / raw.process_count

        # --- L3 流畅度（增量计算）---
        if self._prev_raw:
            dt = now - self._prev_time
            if dt > 0:
                # 磁盘 IO 延迟（psutil read_time/write_time 是毫秒）
                d_read_ops = raw.disk_read_count - self._prev_raw.disk_read_count
                d_write_ops = raw.disk_write_count - self._prev_raw.disk_write_count
                d_read_time = raw.disk_read_time_ms - self._prev_raw.disk_read_time_ms
                d_write_time = raw.disk_write_time_ms - self._prev_raw.disk_write_time_ms

                if d_read_ops > 0:
                    derived.disk_read_latency_ms = d_read_time / d_read_ops
                if d_write_ops > 0:
                    derived.disk_write_latency_ms = d_write_time / d_write_ops
                total_ops = d_read_ops + d_write_ops
                if total_ops > 0:
                    derived.disk_io_latency_ms = (d_read_time + d_write_time) / total_ops

                # IOPS
                derived.disk_read_iops = d_read_ops / dt
                derived.disk_write_iops = d_write_ops / dt

                # 吞吐
                d_read = raw.disk_read_bytes - self._prev_raw.disk_read_bytes
                d_write = raw.disk_write_bytes - self._prev_raw.disk_write_bytes
                derived.disk_throughput_mbps = (d_read + d_write) / dt / 1024**2

                d_sent = raw.net_sent_bytes - self._prev_raw.net_sent_bytes
                d_recv = raw.net_recv_bytes - self._prev_raw.net_recv_bytes
                derived.net_throughput_mbps = (d_sent + d_recv) / dt / 1024**2

                derived.process_count_delta = (raw.process_count - self._prev_raw.process_count) / dt

                # 连接变动率
                d_conn = abs(raw.conn_total - self._prev_raw.conn_total)
                derived.conn_churn_rate = d_conn / dt

                # 上下文切换/中断率（负值=计数器溢出，归零）
                d_ctx = raw.ctx_switches - self._prev_raw.ctx_switches
                d_int = raw.interrupts - self._prev_raw.interrupts
                d_sys = raw.syscalls - self._prev_raw.syscalls
                derived.ctx_switches_rate = max(0, d_ctx) / dt
                derived.interrupts_rate = max(0, d_int) / dt
                derived.syscalls_rate = max(0, d_sys) / dt

        # 网络错误率
        total_net = raw.net_sent_packets + raw.net_recv_packets
        if total_net > 0:
            net_errors = raw.net_errin + raw.net_errout + raw.net_dropin + raw.net_dropout
            derived.net_error_rate = net_errors / total_net

        # IO 拥塞
        if raw.disk_read_bytes > 0:
            derived.io_congestion = raw.disk_write_bytes / max(raw.disk_read_bytes, 1)

        # 核间方差
        if raw.cpu_per_core:
            mean = sum(raw.cpu_per_core) / len(raw.cpu_per_core)
            derived.cpu_core_variance = sum((x - mean)**2 for x in raw.cpu_per_core) / len(raw.cpu_per_core)

        # 中断/DPC 占比
        total_cpu_time = raw.cpu_user + raw.cpu_system
        if total_cpu_time > 0:
            derived.interrupt_ratio = raw.cpu_interrupt / total_cpu_time
            derived.dpc_ratio = raw.cpu_dpc / total_cpu_time

        # --- L4 业务：进程崩溃率（代理）---
        if self._prev_raw and (now - self._prev_time) > 0:
            dt = now - self._prev_time
            delta = raw.process_count - self._prev_raw.process_count
            # 进程数骤降可能是崩溃
            if delta < -3:
                derived.process_crash_rate = abs(delta) / dt

        # 健康分
        err = raw.error_rate if raw.error_rate is not None else 0
        lat = raw.response_p99_ms if raw.response_p99_ms is not None else 0
        err_health = 1.0 - min(1.0, err / 12.0) if err > 0 else 1.0
        lat_health = 1.0 - max(0, min(1.0, (lat - 200) / 1800.0)) if lat > 0 else 1.0
        derived.health_score = err_health * 0.7 + lat_health * 0.3

        # --- L5 物理：温度压力 ---
        if raw.cpu_temp is not None:
            if raw.cpu_temp > 80:
                derived.thermal_stress = min(1.0, (raw.cpu_temp - 80) / 20)
            elif raw.cpu_temp > 65:
                derived.thermal_stress = (raw.cpu_temp - 65) / 60
        elif raw.gpu_temp is not None:
            # 无 CPU 温度时用 GPU 温度代理
            if raw.gpu_temp > 85:
                derived.thermal_stress = min(1.0, (raw.gpu_temp - 85) / 15)
            elif raw.gpu_temp > 70:
                derived.thermal_stress = (raw.gpu_temp - 70) / 60

        # GPU 压力
        if raw.gpu_usage is not None:
            derived.gpu_stress = max(0, (raw.gpu_usage - 70) / 30)

        # 更新历史
        self._prev_raw = raw
        self._prev_time = now
        self._cpu_history.append(raw.cpu_percent)
        self._mem_history.append(raw.mem_percent)
        self._process_count_history.append(raw.process_count)
        if len(self._cpu_history) > self._window_size:
            self._cpu_history.pop(0)
            self._mem_history.pop(0)
            self._process_count_history.pop(0)

        return raw, derived

    def stream(self):
        while True:
            raw, derived = self.collect_once()
            yield raw, derived
            time.sleep(self.interval)


def format_metrics(raw: RawMetrics, derived: DerivedMetrics) -> str:
    """全量格式化（一行摘要）"""
    freq = f"FREQ={raw.cpu_freq_current:.0f}MHz({raw.cpu_freq_ratio:.0%})" if raw.cpu_freq_current else ""
    gpu = f"GPU={raw.gpu_temp}°C/{raw.gpu_usage}%" if raw.gpu_temp is not None else "GPU=N/A"
    disk_lat = f"IOlat={derived.disk_io_latency_ms:.1f}ms" if derived.disk_io_latency_ms > 0 else "IOlat=-"
    dq = f"DQ={raw.disk_queue_depth}" if raw.disk_queue_depth is not None else ""

    return (
        f"L1: CPU={raw.cpu_percent:4.1f}% MEM={raw.mem_percent:4.1f}% "
        f"{freq} 过劳={derived.cpu_overwork:.2f} | "
        f"L2: CONN={raw.conn_total}(CW={raw.conn_close_wait}) "
        f"THR={raw.thread_count} 积压={derived.listen_backlog:.2f} | "
        f"L3: {disk_lat} {dq} "
        f"IOPS={derived.disk_read_iops:.0f}/{derived.disk_write_iops:.0f} "
        f"吞吐={derived.disk_throughput_mbps:.1f}MB/s | "
        f"L4: 健康={derived.health_score:.2f} | "
        f"L5: {gpu} 温压={derived.thermal_stress:.2f}"
    )


if __name__ == "__main__":
    import psutil
    psutil.cpu_percent(interval=0)

    print("[V6] 五层感官采集器", flush=True)
    print("     按 Ctrl+C 停止\n", flush=True)

    collector = RealMetricCollector(interval=1.0)
    count = 0
    try:
        for raw, derived in collector.stream():
            count += 1
            print(f"[{count:04d}] {format_metrics(raw, derived)}", flush=True)
    except KeyboardInterrupt:
        print(f"\n已停止，共采集 {count} 次", flush=True)
