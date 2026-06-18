"""
极端场景模拟：验证疲劳累积、紧绷度、ODE情绪动力学

场景：
1. 空闲(10s) → 2. 渐进过载(30s) → 3. 持续高压(20s) → 4. 恢复(20s)
"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')

from system_simulator import SystemSimulator
from dirty_buffer import DirtyDataBuffer
from pad_model import metrics_to_pad, MetricsHistory, detect_anomaly
from ema_filter import AdaptiveEMAFilter
from template_engine import generate_expression, OutputThrottler
from body_sense import BodySenseManager


def run_extreme():
    print("=" * 70)
    print("  极端场景：空闲→渐进过载→持续高压→恢复")
    print("=" * 70, flush=True)

    sim = SystemSimulator(seed=42)
    buffer = DirtyDataBuffer(max_gap=3, cliff_threshold=3.0)
    history = MetricsHistory(window_size=10)
    ema = AdaptiveEMAFilter()
    throttler = OutputThrottler(interval_sec=3)
    body = BodySenseManager()

    scenarios = [
        ("空闲", "normal", 10),
        ("渐进过载", "gradual_overload", 30),
        ("持续高压", "spike", 20),
        ("恢复", "recovery", 20),
    ]

    step = 0
    for phase_name, scenario, steps in scenarios:
        sim.set_scenario(scenario)
        ema.reset()

        print(f"\n{'='*70}")
        print(f"  阶段：{phase_name}（{steps}步）")
        print(f"{'='*70}", flush=True)

        for i in range(steps):
            step += 1
            m = sim.next()

            # 模拟真实指标（加入脏数据场景）
            metrics_dict = {
                "cpu_percent": m.cpu,
                "mem_percent": m.mem,
                "swap_percent": max(0, m.mem - 50) * 0.5,  # 高内存→Swap升高
                "disk_usage_c": 84.8,  # 固定C盘
                "conn_close_wait": max(0, int(m.error_rate * 0.5)),  # 错误→连接泄漏
                "conn_time_wait": max(0, int(m.cpu * 0.3)),
                "conn_total": 200,
                "process_count": 268,
                "disk_throughput_mbps": m.latency_ms / 100,
                "net_throughput_mbps": 0.5,
                "cpu_core_variance": m.cpu * 2,  # 高负载→核间不均
                "close_wait_ratio": max(0, m.error_rate * 0.005),
                "mem_pressure": max(0, (m.mem - 60) / 40),
                "disk_pressure": max(0, (84.8 - 70) / 30),
                "net_error_rate": 0,
            }

            clean = buffer.process(metrics_dict)
            if not clean.is_valid:
                continue

            cpu = clean.data["cpu_percent"]
            mem = clean.data["mem_percent"]

            # 错误率代理
            err_proxy = 0.0
            cw = clean.data.get("close_wait_ratio", 0)
            if cw > 0.25:
                err_proxy += (cw - 0.25) * 100
            lat_proxy = m.latency_ms

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
                disk_usage=84.8,
                swap_percent=max(0, mem - 50) * 0.5,
                mem_available_gb=max(0.5, 32 - mem * 0.32),
            )

            should_output = throttler.should_output(smooth_pad.quadrant, anomaly.is_anomaly)
            result = generate_expression(smooth_pad, real_cpu=cpu, real_mem=mem)

            # 进度条
            f_bar = "=" * int(sense.fatigue * 20) + "-" * (20 - int(sense.fatigue * 20))
            t_bar = "=" * int(sense.tension * 20) + "-" * (20 - int(sense.tension * 20))
            c_bar = "=" * int(sense.comfort * 20) + "-" * (20 - int(sense.comfort * 20))

            anomaly_tag = " [!]" if anomaly.is_anomaly else ""

            print(f"[{step:03d}] {phase_name:6s} CPU={cpu:5.1f}% MEM={mem:4.1f}% ERR={err_proxy:4.1f}% LAT={lat_proxy:6.0f}ms | "
                  f"P={smooth_pad.p:+.2f} A={smooth_pad.a:+.2f} D={smooth_pad.d:+.2f} | "
                  f"{smooth_pad.quadrant.value}{anomaly_tag}", flush=True)
            print(f"      疲劳[{f_bar}] {sense.fatigue:.2f} "
                  f"紧绷[{t_bar}] {sense.tension:.2f} "
                  f"舒适[{c_bar}] {sense.comfort:.2f} "
                  f"耗竭={sense.exhaustion_risk:.2f}", flush=True)

            if should_output and result.text:
                print(f"      💬 {result.text}", flush=True)

            print(flush=True)
            time.sleep(0.05)  # 快速模拟

    print("=" * 70)
    print("  演示结束", flush=True)
    print("=" * 70)


if __name__ == "__main__":
    run_extreme()
