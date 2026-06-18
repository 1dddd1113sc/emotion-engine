"""
情绪引擎 — 实时版 v2
真实指标 → 脏数据清洗 → ODE动力系统 → 情绪表达

用法：
  python main_live.py              # 实时运行
  python main_live.py --duration 30  # 运行30秒
  python main_live.py --verbose    # 显示清洗警告
"""
import argparse
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

from real_collector import RealMetricCollector, RawMetrics, DerivedMetrics
from dirty_buffer import DirtyDataBuffer
from pad_model import MetricsHistory, detect_anomaly, PADState
from template_engine import generate_expression, OutputThrottler
from body_sense import BodySenseManager
from ode_dynamics import ODEDynamics, ODEConfig, EmotionState, compute_target
from plutchik import classify_plutchik, format_plutchik
from habituation import HabituationManager


def raw_to_metrics_dict(raw: RawMetrics, derived: DerivedMetrics) -> dict[str, float]:
    return {
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


def metrics_dict_to_pad_input(cleaned: dict[str, float]) -> tuple[float, float, float, float]:
    cpu = cleaned.get("cpu_percent", 0)
    mem = cleaned.get("mem_percent", 0)

    cw_ratio = cleaned.get("close_wait_ratio", 0)
    net_err = cleaned.get("net_error_rate", 0)
    error_proxy = 0.0
    if cw_ratio > 0.25:
        error_proxy += (cw_ratio - 0.25) * 100
    error_proxy += net_err * 500

    disk_pressure = cleaned.get("disk_pressure", 0)
    latency_proxy = 0.0
    if disk_pressure > 0.5:
        latency_proxy = (disk_pressure - 0.5) * 2000

    core_var = cleaned.get("cpu_core_variance", 0)
    if core_var > 200:
        latency_proxy += (core_var - 200) * 0.5

    return cpu, mem, error_proxy, latency_proxy


def emotion_to_pad(emo: EmotionState) -> PADState:
    """ODE情感状态 → PADState（供模板引擎使用）"""
    return PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()


def format_line(step, raw, emo, pad, result, anomaly, is_output, body_sense):
    top2 = ", ".join(f"{k}:{v:.0%}" for k, v in result.top_emotions[:2])
    anomaly_tag = " [!]" if anomaly.is_anomaly else ""
    output_tag = "" if is_output else " [muted]"

    # 体感条
    f_bar = "=" * int(emo.f * 10) + "-" * (10 - int(emo.f * 10))
    t_bar = "=" * int(emo.t * 10) + "-" * (10 - int(emo.t * 10))
    c_bar = "=" * int(emo.c * 10) + "-" * (10 - int(emo.c * 10))

    return (
        f"[{step:04d}] "
        f"CPU={raw.cpu_percent:4.1f}% MEM={raw.mem_percent:4.1f}% "
        f"C盘={raw.disk_usage_c:4.1f}% CW={raw.conn_close_wait:2d} "
        f"| P={emo.p:+.2f} A={emo.a:+.2f} D={emo.d:+.2f} "
        f"| {result.quadrant.value} [{top2}] "
        f"| F[{f_bar}] T[{t_bar}] C[{c_bar}]"
        f"{anomaly_tag}{output_tag}"
    )


def main():
    parser = argparse.ArgumentParser(description="情绪引擎 - 实时版 v2 (ODE)")
    parser.add_argument("--duration", type=int, default=0, help="运行秒数，0=无限")
    parser.add_argument("--interval", type=float, default=1.0, help="采集间隔秒数")
    parser.add_argument("--verbose", action="store_true", help="显示详细信息")
    args = parser.parse_args()

    print("[LIVE] 情绪引擎 v2 — ODE动力系统", flush=True)
    print(f"       采集间隔: {args.interval}s | 持续时间: {'无限' if args.duration == 0 else f'{args.duration}s'}", flush=True)
    print(f"       按 Ctrl+C 停止\n", flush=True)
    print(f"{'='*90}", flush=True)

    # 初始化组件
    collector = RealMetricCollector(interval=args.interval)
    buffer = DirtyDataBuffer(max_gap=3, cliff_threshold=3.0)
    history = MetricsHistory(window_size=10)
    throttler = OutputThrottler(interval_sec=5)
    habituation = HabituationManager()
    body = BodySenseManager()
    from ode_dynamics import DEFAULT_ODE_CONFIG
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)

    import psutil
    psutil.cpu_percent(interval=0)

    step = 0
    start_time = time.time()
    output_count = 0
    anomaly_count = 0
    last_quadrant = None

    try:
        for raw, derived in collector.stream():
            step += 1

            # 1. 采集 → 原始字典
            metrics_dict = raw_to_metrics_dict(raw, derived)

            # 2. 脏数据清洗
            clean_result = buffer.process(metrics_dict)
            if not clean_result.is_valid:
                print(f"[{step:04d}] ⚠️ 数据无效，跳过", flush=True)
                continue

            # 3. 指标 → PAD输入
            cpu, mem, error_proxy, latency_proxy = metrics_dict_to_pad_input(clean_result.data)

            # 4. 历史窗口
            history.update(cpu, error_proxy, latency_proxy)

            # 5. 异常检测
            anomaly = detect_anomaly(cpu, mem, error_proxy, latency_proxy, history)

            # 6. 体感更新
            cpu_good = max(-1, min(1, 1 - cpu / 50))
            mem_good = max(-1, min(1, 1 - mem / 70))
            err_good = max(-1, min(1, 1 - error_proxy / 10))
            lat_good = max(-1, min(1, 1 - latency_proxy / 500))
            body_sense = body.update(
                load_signal=cpu / 100.0,
                signals=[cpu_good, mem_good, err_good, lat_good],
                disk_usage=raw.disk_usage_c,
                swap_percent=raw.swap_percent,
                mem_available_gb=raw.mem_available_gb,
                ctx_switches_rate=derived.ctx_switches_rate,
                interrupts_rate=derived.interrupts_rate,
                syscalls_rate=derived.syscalls_rate,
                interrupt_ratio=derived.interrupt_ratio,
                dpc_ratio=derived.dpc_ratio,
            )

            # 7. 计算ODE目标值
            target = compute_target(
                cpu, mem, error_proxy, latency_proxy,
                fatigue=body_sense.fatigue,
                tension=body_sense.tension,
                comfort=body_sense.comfort,
            )

            # 8. ODE步进（核心：情绪有惯性/爆发/衰减）
            if anomaly.override_pad:
                # 严重异常：强制override
                ode.state.p = anomaly.override_pad.p
                ode.state.a = anomaly.override_pad.a
                ode.state.d = anomaly.override_pad.d
                emo = ode.state
            else:
                emo = ode.step(target)

            # 9. ODE状态 → PAD（供模板引擎）
            pad = emotion_to_pad(emo)

            # 10. Plutchik 情感轮分类
            plutchik = classify_plutchik(emo.p, emo.a, emo.d)
            plutchik_str = format_plutchik(plutchik)

            # 11. 防疲劳表达（Habituation）
            emotion_intensity = (abs(emo.p) + abs(emo.a) + abs(emo.d)) / 3
            is_state_change = (pad.quadrant != last_quadrant)
            last_quadrant = pad.quadrant
            hab_state = habituation.update(
                emotion_intensity=emotion_intensity,
                is_state_change=is_state_change,
                is_anomaly=anomaly.is_anomaly,
            )

            # 12. 输出频率控制（三重过滤）
            should_output = (
                throttler.should_output(pad.quadrant, anomaly.is_anomaly)
                and hab_state.should_express
            )

            # 13. 生成表达
            result = generate_expression(
                pad,
                anomaly_reason=anomaly.reason if anomaly.is_anomaly else None,
                real_cpu=raw.cpu_percent,
                real_mem=raw.mem_percent,
            )

            # 14. 输出
            if anomaly.is_anomaly:
                anomaly_count += 1

            line = format_line(step, raw, emo, pad, result, anomaly, should_output, body_sense)
            print(line, flush=True)

            # Plutchik 标签
            if should_output or step % 5 == 0:
                print(f"         🎭 {plutchik_str} | 适应={hab_state.adaptation_level:.2f}", flush=True)

            if should_output:
                output_count += 1
                if result.text:
                    print(f"         💬 {result.text}", flush=True)
                if args.verbose and clean_result.warnings:
                    for w in clean_result.warnings:
                        print(f"         ⚠️ {w}", flush=True)

            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                break

    except KeyboardInterrupt:
        pass

    elapsed = time.time() - start_time
    print(f"\n{'='*90}", flush=True)
    print(f"[DONE] 运行 {elapsed:.0f}s | 采集 {step} 次 | 输出 {output_count} 条 | 异常 {anomaly_count} 次", flush=True)


if __name__ == "__main__":
    main()
