"""
体感演示：空闲 → 压力 → 恢复
用 CPU 密集任务制造真实负载，观察疲劳/紧绷/舒适变化
"""
import sys, time, threading, os
sys.stdout.reconfigure(encoding='utf-8')

from real_collector import RealMetricCollector
from dirty_buffer import DirtyDataBuffer
from pad_model import metrics_to_pad, MetricsHistory, detect_anomaly
from ema_filter import AdaptiveEMAFilter
from template_engine import generate_expression, OutputThrottler
from body_sense import BodySenseManager


def cpu_burn(seconds: int):
    """CPU密集任务"""
    end = time.time() + seconds
    while time.time() < end:
        _ = sum(i * i for i in range(10000))


def run_demo():
    print("=" * 70)
    print("  体感演示：空闲(10s) → CPU压力(20s) → 恢复(15s)")
    print("=" * 70, flush=True)

    collector = RealMetricCollector(interval=1.0)
    buffer = DirtyDataBuffer(max_gap=3, cliff_threshold=3.0)
    history = MetricsHistory(window_size=10)
    ema = AdaptiveEMAFilter()
    throttler = OutputThrottler(interval_sec=3)
    body = BodySenseManager()

    import psutil
    psutil.cpu_percent(interval=0)

    step = 0
    phase = "idle"
    burn_thread = None

    for raw, derived in collector.stream():
        step += 1

        # 阶段切换
        if step == 11 and phase == "idle":
            phase = "stress"
            print(f"\n{'='*70}")
            print(f"  >>> 开始施加 CPU 压力（4线程 × 20秒）<<<")
            print(f"{'='*70}\n", flush=True)
            threads = []
            for _ in range(4):
                t = threading.Thread(target=cpu_burn, args=(20,), daemon=True)
                t.start()
                threads.append(t)

        if step == 31 and phase == "stress":
            phase = "recovery"
            print(f"\n{'='*70}")
            print(f"  >>> 压力释放，观察恢复过程 <<<")
            print(f"{'='*70}\n", flush=True)

        if step > 46:
            break

        # 指标处理
        metrics_dict = {
            "cpu_percent": raw.cpu_percent,
            "mem_percent": raw.mem_percent,
            "swap_percent": raw.swap_percent,
            "disk_usage_c": raw.disk_usage_c,
            "conn_close_wait": float(raw.conn_close_wait),
            "conn_time_wait": float(raw.conn_time_wait),
            "conn_total": float(raw.conn_total),
            "process_count": float(raw.process_count),
            "disk_throughput_mbps": derived.disk_throughput_mbps,
            "net_throughput_mbps": derived.net_throughput_mbps,
            "cpu_core_variance": derived.cpu_core_variance,
            "close_wait_ratio": derived.close_wait_ratio,
            "mem_pressure": derived.mem_pressure,
            "disk_pressure": derived.disk_pressure,
            "net_error_rate": derived.net_error_rate,
        }
        clean = buffer.process(metrics_dict)
        if not clean.is_valid:
            continue

        cpu = clean.data["cpu_percent"]
        mem = clean.data["mem_percent"]
        err_proxy = 0.0
        cw = clean.data.get("close_wait_ratio", 0)
        if cw > 0.25:
            err_proxy += (cw - 0.25) * 100
        lat_proxy = 0.0
        dp = clean.data.get("disk_pressure", 0)
        if dp > 0.5:
            lat_proxy = (dp - 0.5) * 2000

        history.update(cpu, err_proxy, lat_proxy)
        anomaly = detect_anomaly(cpu, mem, err_proxy, lat_proxy, history)
        raw_pad = metrics_to_pad(cpu, mem, err_proxy, lat_proxy, history)

        if anomaly.override_pad:
            ema.force_update(anomaly.override_pad)
            smooth_pad = anomaly.override_pad
        else:
            smooth_pad = ema.update(raw_pad)

        # 体感
        cpu_good = max(-1, min(1, 1 - cpu / 50))
        mem_good = max(-1, min(1, 1 - mem / 70))
        err_good = max(-1, min(1, 1 - err_proxy / 10))
        lat_good = max(-1, min(1, 1 - lat_proxy / 500))
        sense = body.update(
            load_signal=cpu / 100.0,
            signals=[cpu_good, mem_good, err_good, lat_good],
            disk_usage=raw.disk_usage_c,
            swap_percent=raw.swap_percent,
            mem_available_gb=raw.mem_available_gb,
        )

        should_output = throttler.should_output(smooth_pad.quadrant, anomaly.is_anomaly)
        result = generate_expression(smooth_pad, real_cpu=raw.cpu_percent, real_mem=raw.mem_percent)

        # 输出
        phase_tag = {"idle": "空闲", "stress": "压力", "recovery": "恢复"}[phase]
        anomaly_tag = " [!]" if anomaly.is_anomaly else ""

        # 疲劳条
        f_bar = "█" * int(sense.fatigue * 20) + "░" * (20 - int(sense.fatigue * 20))
        t_bar = "█" * int(sense.tension * 20) + "░" * (20 - int(sense.tension * 20))
        c_bar = "█" * int(sense.comfort * 20) + "░" * (20 - int(sense.comfort * 20))

        print(f"[{step:03d}] {phase_tag} CPU={cpu:5.1f}% MEM={mem:4.1f}% | "
              f"P={smooth_pad.p:+.2f} A={smooth_pad.a:+.2f} D={smooth_pad.d:+.2f} | "
              f"{smooth_pad.quadrant.value}", flush=True)
        print(f"      疲劳[{f_bar}] {sense.fatigue:.2f} "
              f"紧绷[{t_bar}] {sense.tension:.2f} "
              f"舒适[{c_bar}] {sense.comfort:.2f}", flush=True)

        if should_output and result.text:
            print(f"      💬 {result.text}{anomaly_tag}", flush=True)

        print(flush=True)

    # 汇总
    print("=" * 70)
    print("  演示结束", flush=True)
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
