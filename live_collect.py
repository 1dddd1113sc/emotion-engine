"""
情绪引擎 — 7天连续采集脚本

将五层感官原始/派生指标保存到 CSV 文件。
每次启动新文件，按时间戳命名。

用法：
  python live_collect.py --duration 3600       # 采集 1 小时
  python live_collect.py --duration 3600 --hz 2  # 2Hz 采集 1 小时
  python live_collect.py --duration 3600 --out custom.csv  # 指定输出文件

Cron 调用：
  python live_collect.py --duration 3600
"""
import sys
import os
import csv
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_collector import RealMetricCollector, RawMetrics, DerivedMetrics


def flatten_metrics(raw: RawMetrics, derived: DerivedMetrics) -> dict:
    """将 RawMetrics + DerivedMetrics 展平为一层字典"""
    d = {}

    # 时间戳
    d['timestamp'] = raw.timestamp
    d['datetime'] = datetime.fromtimestamp(raw.timestamp).isoformat()

    # L1 计算与记忆层
    d['cpu_percent'] = raw.cpu_percent
    d['cpu_per_core_max'] = round(max(raw.cpu_per_core), 1) if raw.cpu_per_core else ''
    d['cpu_per_core_min'] = round(min(raw.cpu_per_core), 1) if raw.cpu_per_core else ''
    d['cpu_user'] = raw.cpu_user
    d['cpu_system'] = raw.cpu_system
    d['cpu_idle'] = raw.cpu_idle
    d['cpu_iowait'] = raw.cpu_iowait
    d['cpu_interrupt'] = raw.cpu_interrupt
    d['cpu_dpc'] = raw.cpu_dpc
    d['ctx_switches'] = raw.ctx_switches
    d['interrupts'] = raw.interrupts
    d['syscalls'] = raw.syscalls
    d['cpu_freq_current'] = raw.cpu_freq_current or ''
    d['cpu_freq_max'] = raw.cpu_freq_max or ''
    d['cpu_freq_ratio'] = raw.cpu_freq_ratio
    d['load_average_1m'] = raw.load_average_1m or ''
    d['load_average_5m'] = raw.load_average_5m or ''
    d['load_average_15m'] = raw.load_average_15m or ''
    d['mem_percent'] = raw.mem_percent
    d['mem_available_gb'] = raw.mem_available_gb
    d['swap_percent'] = raw.swap_percent
    d['process_count'] = raw.process_count

    # L1 派生
    d['iowait_ratio'] = derived.iowait_ratio
    d['mem_pressure'] = derived.mem_pressure
    d['disk_pressure'] = derived.disk_pressure
    d['freq_throttle'] = derived.freq_throttle
    d['cpu_overwork'] = derived.cpu_overwork

    # L2 吞吐与排队层
    d['conn_established'] = raw.conn_established
    d['conn_time_wait'] = raw.conn_time_wait
    d['conn_close_wait'] = raw.conn_close_wait
    d['conn_listen'] = raw.conn_listen
    d['conn_total'] = raw.conn_total
    d['thread_count'] = raw.thread_count

    # L2 派生
    d['close_wait_ratio'] = derived.close_wait_ratio
    d['conn_turnover_pressure'] = derived.conn_turnover_pressure
    d['thread_density'] = derived.thread_density
    d['conn_churn_rate'] = derived.conn_churn_rate

    # L3 传导与IO层
    d['disk_read_bytes'] = raw.disk_read_bytes
    d['disk_write_bytes'] = raw.disk_write_bytes
    d['disk_read_count'] = raw.disk_read_count
    d['disk_write_count'] = raw.disk_write_count
    d['disk_read_time_ms'] = raw.disk_read_time_ms
    d['disk_write_time_ms'] = raw.disk_write_time_ms
    d['disk_usage_c'] = raw.disk_usage_c
    d['disk_usage_d'] = raw.disk_usage_d
    d['net_sent_bytes'] = raw.net_sent_bytes
    d['net_recv_bytes'] = raw.net_recv_bytes
    d['net_sent_packets'] = raw.net_sent_packets
    d['net_recv_packets'] = raw.net_recv_packets
    d['net_errin'] = raw.net_errin
    d['net_errout'] = raw.net_errout
    d['net_dropin'] = raw.net_dropin
    d['net_dropout'] = raw.net_dropout

    # L3 派生
    d['disk_io_latency_ms'] = derived.disk_io_latency_ms
    d['disk_read_latency_ms'] = derived.disk_read_latency_ms
    d['disk_write_latency_ms'] = derived.disk_write_latency_ms
    d['disk_throughput_mbps'] = derived.disk_throughput_mbps
    d['disk_read_iops'] = derived.disk_read_iops
    d['disk_write_iops'] = derived.disk_write_iops
    d['net_throughput_mbps'] = derived.net_throughput_mbps
    d['net_error_rate'] = derived.net_error_rate
    d['io_congestion'] = derived.io_congestion

    # L4 业务表现层
    d['error_rate'] = raw.error_rate if raw.error_rate is not None else ''
    d['http_5xx_rate'] = raw.http_5xx_rate if raw.http_5xx_rate is not None else ''
    d['http_4xx_rate'] = raw.http_4xx_rate if raw.http_4xx_rate is not None else ''
    d['response_p50_ms'] = raw.response_p50_ms if raw.response_p50_ms is not None else ''
    d['response_p99_ms'] = raw.response_p99_ms if raw.response_p99_ms is not None else ''
    d['throughput_rps'] = raw.throughput_rps if raw.throughput_rps is not None else ''
    d['timeout_rate'] = raw.timeout_rate if raw.timeout_rate is not None else ''
    d['cache_hit_rate'] = raw.cache_hit_rate if raw.cache_hit_rate is not None else ''

    # L4 派生
    d['system_health'] = derived.system_health
    d['business_health'] = derived.business_health if derived.business_health is not None else ''

    # L5 物理硬件层
    d['cpu_temp'] = raw.cpu_temp if raw.cpu_temp is not None else ''
    d['fan_speed'] = raw.fan_speed if raw.fan_speed is not None else ''
    d['gpu_temp'] = raw.gpu_temp if raw.gpu_temp is not None else ''
    d['gpu_usage'] = raw.gpu_usage if raw.gpu_usage is not None else ''
    d['gpu_mem_used_mb'] = raw.gpu_mem_used_mb if raw.gpu_mem_used_mb is not None else ''
    d['gpu_mem_total_mb'] = raw.gpu_mem_total_mb if raw.gpu_mem_total_mb is not None else ''
    d['disk_queue_depth'] = raw.disk_queue_depth if raw.disk_queue_depth is not None else ''

    # L5 派生
    d['thermal_stress'] = derived.thermal_stress
    d['gpu_stress'] = derived.gpu_stress

    # 通用派生
    d['cpu_core_variance'] = derived.cpu_core_variance
    d['process_count_delta'] = derived.process_count_delta
    d['ctx_switches_rate'] = derived.ctx_switches_rate
    d['interrupts_rate'] = derived.interrupts_rate
    d['syscalls_rate'] = derived.syscalls_rate
    d['interrupt_ratio'] = derived.interrupt_ratio
    d['dpc_ratio'] = derived.dpc_ratio

    return d


def collect_csv(duration_sec: float, hz: float, out_path: str):
    """
    连续采集并保存到 CSV。

    参数：
        duration_sec: 采集时长（秒）
        hz: 采样频率 (Hz)
        out_path: 输出 CSV 路径
    """
    import psutil
    psutil.cpu_percent(interval=0)  # 预热

    interval = 1.0 / hz
    collector = RealMetricCollector(interval=interval)

    # 生成 CSV 表头
    # 先采集一次获取列名
    raw, derived = collector.collect_once()
    sample = flatten_metrics(raw, derived)
    fieldnames = list(sample.keys())

    start_time = time.time()
    end_time = start_time + duration_sec
    count = 0
    total_rows = 0

    print(f"[live_collect] 开始采集")
    print(f"  频率: {hz} Hz  时长: {duration_sec}s  输出: {out_path}")
    print(f"  开始时间: {datetime.fromtimestamp(start_time).isoformat()}")
    print(f"  预计结束: {datetime.fromtimestamp(end_time).isoformat()}")
    print(f"  预计行数: ~{int(duration_sec * hz)}")
    print()

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        # 写入第一行
        writer.writerow(sample)
        total_rows += 1

        try:
            while time.time() < end_time:
                count += 1
                raw, derived = collector.collect_once()
                row = flatten_metrics(raw, derived)
                writer.writerow(row)
                total_rows += 1

                # 每 100 行输出进度
                if count % 100 == 0:
                    elapsed = time.time() - start_time
                    remaining = max(0, end_time - time.time())
                    print(f"  [{count:05d}] {elapsed:.0f}s elapsed | "
                          f"{remaining:.0f}s remaining | {total_rows} rows written", flush=True)

                # 精确控制间隔
                sleep_time = interval - (time.time() - raw.timestamp)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print(f"\n  ⚠️ 用户中断")

    elapsed = time.time() - start_time
    file_size_mb = os.path.getsize(out_path) / 1024**2

    print(f"\n[live_collect] 采集完成")
    print(f"  实际耗时: {elapsed:.0f}s")
    print(f"  总行数: {total_rows}")
    print(f"  实际频率: {total_rows / elapsed:.2f} Hz")
    print(f"  文件大小: {file_size_mb:.2f} MB")
    print(f"  输出路径: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="情绪引擎 7天连续采集")
    parser.add_argument("--duration", type=float, required=True,
                        help="采集时长（秒），如 3600 = 1小时")
    parser.add_argument("--hz", type=float, default=1.0,
                        help="采样频率 (Hz)，默认 1Hz")
    parser.add_argument("--out", type=str, default=None,
                        help="输出 CSV 路径，默认自动生成 live_YYYYMMDD_HHMMSS.csv")
    args = parser.parse_args()

    # 自动生成文件名
    if args.out is None:
        now = datetime.now()
        args.out = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"live_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        )

    collect_csv(args.duration, args.hz, args.out)


if __name__ == "__main__":
    main()