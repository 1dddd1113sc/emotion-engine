"""
情绪引擎 V6.2 — 完整管线入口 (BodySense + 上下文感知 PAD)

V6 四层管线：采集层 → BodySense → SemanticSignals → ContextPAD → EMA → Stabilizer → ODE → Plutchik

用法:
  python main.py --fast                  # 快速完整演示（全部场景）
  python main.py --fast --scenario spike  # 只跑突发负载场景
  python main.py --benchmark             # 性能基准（V6 管线单步延迟）
  python main.py --flicker               # 闪烁测试（Stabilizer inertia）
  python main.py --hz 2                  # 2Hz 采样
  python main.py --quiet                 # 静默模式
"""
import argparse
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

from real_collector import RealMetricCollector, RawMetrics, DerivedMetrics
from dirty_buffer import DirtyDataBuffer
from body_sense import BodySenseManager
from semantic_signals import extract_signals
from context_pad import compose_pad
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer
from ode_dynamics import ODEDynamics, ODEConfig, DEFAULT_ODE_CONFIG, EmotionState
from plutchik import classify_plutchik, format_plutchik
from template_engine import generate_expression, OutputThrottler
from system_simulator import SystemSimulator
from pad_model import PADState, MetricsHistory, detect_anomaly, PADQuadrant


SCENARIOS = [
    ("normal",           20, "🟢 正常运行"),
    ("spike",            45, "🔴 突发负载"),
    ("error_burst",      40, "🟠 错误飙升"),
    ("gradual_overload", 65, "🟡 渐进过载"),
    ("recovery",         45, "🔵 故障恢复"),
]


def sim_to_metrics_dict(m) -> dict[str, float]:
    """模拟器输出 → 兼容 dirty_buffer 的指标字典"""
    return {
        "cpu_percent": m.cpu,
        "mem_percent": m.mem,
        "error_rate": m.error_rate,
        "latency_ms": m.latency_ms,
        # 模拟器无以下字段，用默认值
        "swap_percent": 0.0,
        "disk_usage_c": 50.0,
        "close_wait_ratio": 0.0,
        "net_error_rate": 0.0,
        "disk_pressure": 0.0,
        "cpu_core_variance": 0.0,
        "mem_pressure": max(0, (m.mem - 60) / 40),  # 粗略估算
    }


def raw_to_metrics_dict(raw: RawMetrics, derived: DerivedMetrics) -> dict[str, float]:
    """真实采集输出 → 指标字典"""
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


def cleaned_to_pad_input(cleaned: dict[str, float]) -> tuple[float, float, float, float]:
    """清洗后的指标字典 → (cpu, mem, error_proxy, latency_proxy) 供管线使用"""
    cpu = cleaned.get("cpu_percent", 0)
    mem = cleaned.get("mem_percent", 0)

    # 错误代理：close_wait_ratio + net_error_rate
    cw_ratio = cleaned.get("close_wait_ratio", 0)
    net_err = cleaned.get("net_error_rate", 0)
    error_proxy = cleaned.get("error_rate", 0)
    if error_proxy == 0:
        if cw_ratio > 0.25:
            error_proxy += (cw_ratio - 0.25) * 100
        error_proxy += net_err * 500

    # 延迟代理：disk_pressure + cpu_core_variance
    latency_proxy = cleaned.get("latency_ms", 0)
    if latency_proxy == 0:
        disk_pressure = cleaned.get("disk_pressure", 0)
        if disk_pressure > 0.5:
            latency_proxy = (disk_pressure - 0.5) * 2000
        core_var = cleaned.get("cpu_core_variance", 0)
        if core_var > 200:
            latency_proxy += (core_var - 200) * 0.5

    return cpu, mem, error_proxy, latency_proxy


def build_body_sense_kwargs(
    cleaned: dict[str, float], cpu: float, mem: float,
    error_proxy: float, latency_proxy: float,
) -> dict:
    """从清洗后的指标构建 BodySenseManager.update() 的参数"""
    cpu_good = max(-1, min(1, 1 - cpu / 50))
    mem_good = max(-1, min(1, 1 - mem / 70))
    err_good = max(-1, min(1, 1 - error_proxy / 10))
    lat_good = max(-1, min(1, 1 - latency_proxy / 500))

    return dict(
        load_signal=cpu / 100.0,
        signals=[cpu_good, mem_good, err_good, lat_good],
        disk_usage=cleaned.get("disk_usage_c", 50),
        swap_percent=cleaned.get("swap_percent", 0),
        mem_available_gb=cleaned.get("mem_available_gb", 18.0),
        mem_percent=mem,
        close_wait_ratio=cleaned.get("close_wait_ratio", 0),
        ctx_switches_rate=cleaned.get("ctx_switches_rate", 0),
        interrupts_rate=cleaned.get("interrupts_rate", 0),
        syscalls_rate=cleaned.get("syscalls_rate", 0),
        interrupt_ratio=cleaned.get("interrupt_ratio", 0),
        dpc_ratio=cleaned.get("dpc_ratio", 0),
    )


def emotion_to_pad(emo: EmotionState) -> PADState:
    """ODE 情感状态 → PADState（供模板引擎使用）"""
    return PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()


def run_v6_pipeline_step(
    i: int, cpu: float, mem: float, error_proxy: float, latency_proxy: float,
    cleaned: dict[str, float], history: MetricsHistory,
    body: BodySenseManager, ema: AdaptiveEMAFilter,
    stabilizer: QuadrantStabilizer, ode: ODEDynamics,
    throttler: OutputThrottler, anomaly,
    verbose: bool, fast: bool,
) -> dict:
    """
    V6 管线单步执行。

    流程：指标 → BodySense → SemanticSignals → ContextPAD → EMA → Stabilizer → ODE → Plutchik
    返回：包含所有中间结果的字典
    """
    # ── 1. 体感更新（BodySenseManager）──
    body_kwargs = build_body_sense_kwargs(cleaned, cpu, mem, error_proxy, latency_proxy)
    body_sense = body.update(**body_kwargs)

    # ── 2. 语义信号提取 ──
    sig = extract_signals(
        cpu=cpu, mem=mem,
        error_rate=error_proxy, latency_ms=latency_proxy,
        swap_percent=cleaned.get("swap_percent", 0),
        disk_usage=cleaned.get("disk_usage_c", 50),
        err_velocity=history.err_velocity if history else 0.0,
        lat_velocity=history.lat_velocity if history else 0.0,
    )

    # ── 3. 上下文感知 PAD 组合（注意 body 参数！）──
    pad_output = compose_pad(sig, body=body_sense)

    # 转为 PADState 供 EMA 使用
    raw_pad = PADState(
        p=pad_output.p, a=pad_output.a, d=pad_output.d, volatility=pad_output.v,
    ).clamp()

    # ── 4. 异常检测 override ──
    if anomaly.override_pad:
        ema.force_update(anomaly.override_pad)
        smooth_pad = anomaly.override_pad
    else:
        # ── 5. 自适应 EMA 平滑 ──
        smooth_pad = ema.update(raw_pad)

    # ── 6. 防闪烁象限稳定器 ──
    p_s, a_s, d_s, quadrant, is_transition = stabilizer.update(
        smooth_pad.p, smooth_pad.a, smooth_pad.d, context=sig.context,
    )
    stable_pad = PADState(p=p_s, a=a_s, d=d_s, volatility=smooth_pad.volatility)

    # ── 7. ODE 动力系统步进 ──
    # 构建 ODE 目标：使用上下文 PAD 输出 + 体感 F/T/C
    target = EmotionState(
        p=pad_output.p, a=pad_output.a, d=pad_output.d, v=pad_output.v,
        f=body_sense.fatigue, t=body_sense.tension, c=body_sense.comfort,
    ).clamp()

    if anomaly.override_pad:
        # 严重异常：强制覆盖 ODE 状态
        ode.state.p = anomaly.override_pad.p
        ode.state.a = anomaly.override_pad.a
        ode.state.d = anomaly.override_pad.d
        emo = ode.state
    else:
        emo = ode.step(target)

    # ── 8. Plutchik 情感轮分类 ──
    plutchik = classify_plutchik(emo.p, emo.a, emo.d)
    plutchik_str = format_plutchik(plutchik)

    # ── 9. 输出频率控制 ──
    should_output = throttler.should_output(stable_pad.quadrant, anomaly.is_anomaly)

    # ── 10. 生成表达 ──
    result = generate_expression(
        stable_pad,
        anomaly_reason=anomaly.reason if anomaly.is_anomaly else None,
        real_cpu=cpu, real_mem=mem,
    )

    # ── 11. 输出 ──
    if verbose:
        top2 = ", ".join(f"{k}:{v:.1%}" for k, v in result.top_emotions)
        anomaly_tag = " 🚨异常" if anomaly.is_anomaly else ""

        # 体感条
        f_bar = "=" * int(emo.f * 10) + "-" * (10 - int(emo.f * 10))
        t_bar = "=" * int(emo.t * 10) + "-" * (10 - int(emo.t * 10))
        c_bar = "=" * int(emo.c * 10) + "-" * (10 - int(emo.c * 10))

        print(f"\n[{i+1:02d}] CPU={cpu:5.1f}% MEM={mem:5.1f}% "
              f"ERR={error_proxy:5.2f}% LAT={latency_proxy:6.1f}ms")
        print(f"     PAD: P={stable_pad.p:+.3f} A={stable_pad.a:+.3f} D={stable_pad.d:+.3f}"
              f" V={stable_pad.volatility:.2f}  ctx={sig.context}")
        print(f"     体感: F[{f_bar}] T[{t_bar}] C[{c_bar}]"
              f"  f={emo.f:.2f} t={emo.t:.2f} c={emo.c:.2f}")
        print(f"     → {stable_pad.quadrant.value} | [{top2}]"
              f"  🎭 {plutchik_str}{anomaly_tag}")

        if not should_output:
            print(f"     🔇 [节流]")
        elif result.text:
            print(f"     💬 {result.text}")

    return {
        "quadrant": stable_pad.quadrant.value,
        "expression": result.text if should_output else None,
        "confidence": result.confidence,
        "is_anomaly": anomaly.is_anomaly,
        "is_output": should_output,
        "plutchik": plutchik_str,
    }


def run_scenario(sim, scenario, steps, hz, verbose=True, fast=False, alpha=0.3):
    """场景模式：用 SystemSimulator 生成模拟数据，经 V6 管线处理"""
    sim.set_scenario(scenario)

    # 初始化 V6 管线组件
    history = MetricsHistory(window_size=10)
    ema = AdaptiveEMAFilter()
    body = BodySenseManager()
    stabilizer = QuadrantStabilizer()
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)
    throttler = OutputThrottler(interval_sec=5)
    interval = 1.0 / hz

    quadrant_counts: dict[str, int] = {}
    expressions: list[str] = []
    anomaly_count = 0
    suppressed_count = 0
    steps_done = 0

    if verbose:
        print(f"\n{'='*60}")
        print(f"场景: {scenario} ({steps} 步, {hz}Hz)")
        print(f"{'='*60}")

    for i in range(steps):
        m = sim.next()

        # 模拟器指标 → 字典 → 脏数据清洗
        metrics_dict = sim_to_metrics_dict(m)
        cpu = metrics_dict["cpu_percent"]
        mem = metrics_dict["mem_percent"]
        error_proxy = metrics_dict.get("error_rate", m.error_rate)
        latency_proxy = metrics_dict.get("latency_ms", m.latency_ms)

        # 历史窗口
        history.update(cpu, error_proxy, latency_proxy)

        # 异常检测
        anomaly = detect_anomaly(cpu, mem, error_proxy, latency_proxy, history)

        # V6 管线
        result = run_v6_pipeline_step(
            i, cpu, mem, error_proxy, latency_proxy,
            metrics_dict, history,
            body, ema, stabilizer, ode, throttler, anomaly,
            verbose, fast,
        )

        q_name = result["quadrant"]
        quadrant_counts[q_name] = quadrant_counts.get(q_name, 0) + 1
        if result["is_anomaly"]:
            anomaly_count += 1
        if result["is_output"] and result["expression"]:
            expressions.append(result["expression"])
        elif not result["is_output"]:
            suppressed_count += 1
        steps_done += 1

        if not fast:
            time.sleep(interval)

    if verbose and steps_done > 0:
        print(f"\n  📊 统计: 异常={anomaly_count}次 | "
              f"节流={suppressed_count}次 | 输出={len(expressions)}条")

    return quadrant_counts, expressions, anomaly_count


def run_benchmark(hz, alpha):
    """性能基准：测试 V6 管线的单步延迟"""
    import timeit

    # 初始化所有组件
    history = MetricsHistory(window_size=10)
    ema = AdaptiveEMAFilter()
    body = BodySenseManager()
    stabilizer = QuadrantStabilizer()
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)

    # 预热：建立历史基线
    for _ in range(10):
        history.update(50, 1, 100)

    test_cpu, test_mem, test_err, test_lat = 50.0, 60.0, 5.0, 200.0
    test_cleaned = {"cpu_percent": 50, "mem_percent": 60, "swap_percent": 0,
                    "disk_usage_c": 50, "error_rate": 5, "latency_ms": 200}

    # 预热体感
    body_kwargs = build_body_sense_kwargs(test_cleaned, test_cpu, test_mem, test_err, test_lat)
    body.update(**body_kwargs)

    # 预热 EMA
    test_pad = PADState(0.5, -0.3, 0.7, 0.1)
    ema.update(test_pad)

    n = 5000

    # 基准 1：BodySense 更新
    def bench_body():
        body.update(**body_kwargs)
    elapsed_body = timeit.timeit(bench_body, number=n)
    avg_body = elapsed_body / n * 1_000_000

    # 基准 2：SemanticSignals 提取
    def bench_signals():
        extract_signals(cpu=test_cpu, mem=test_mem, error_rate=test_err, latency_ms=test_lat)
    elapsed_sig = timeit.timeit(bench_signals, number=n)
    avg_sig = elapsed_sig / n * 1_000_000

    # 基准 3：ContextPAD 组合
    sig = extract_signals(cpu=test_cpu, mem=test_mem, error_rate=test_err, latency_ms=test_lat)
    body_sense = body.update(**body_kwargs)
    def bench_pad():
        compose_pad(sig, body=body_sense)
    elapsed_pad = timeit.timeit(bench_pad, number=n)
    avg_pad = elapsed_pad / n * 1_000_000

    # 基准 4：EMA 平滑
    def bench_ema():
        ema.update(test_pad)
    elapsed_ema = timeit.timeit(bench_ema, number=n)
    avg_ema = elapsed_ema / n * 1_000_000

    # 基准 5：Stabilizer
    def bench_stab():
        stabilizer.update(0.3, 0.2, 0.1, context='clean')
    elapsed_stab = timeit.timeit(bench_stab, number=n)
    avg_stab = elapsed_stab / n * 1_000_000

    # 基准 6：ODE 步进
    target = EmotionState(p=0.3, a=0.2, d=0.1, v=0.1, f=0.3, t=0.2, c=0.8).clamp()
    def bench_ode():
        ode.step(target)
    elapsed_ode = timeit.timeit(bench_ode, number=n)
    avg_ode = elapsed_ode / n * 1_000_000

    # 基准 7：Plutchik 分类
    def bench_plutchik():
        classify_plutchik(0.3, 0.2, 0.1)
    elapsed_plutchik = timeit.timeit(bench_plutchik, number=n)
    avg_plutchik = elapsed_plutchik / n * 1_000_000

    # 基准 8：模板生成
    def bench_template():
        generate_expression(test_pad)
    elapsed_tpl = timeit.timeit(bench_template, number=n)
    avg_tpl = elapsed_tpl / n * 1_000_000

    # 基准 9：异常检测
    def bench_anomaly():
        detect_anomaly(50, 60, 5, 200, history)
    elapsed_anom = timeit.timeit(bench_anomaly, number=n)
    avg_anom = elapsed_anom / n * 1_000_000

    print(f"\n{'='*60}")
    print(f"⚡ 性能基准 (V6 管线)")
    print(f"{'='*60}")
    print(f"  BodySense:     {avg_body:.1f} μs ({avg_body/1000:.3f} ms)")
    print(f"  SemanticSig:   {avg_sig:.1f} μs ({avg_sig/1000:.3f} ms)")
    print(f"  ContextPAD:    {avg_pad:.1f} μs ({avg_pad/1000:.3f} ms)")
    print(f"  EMA 平滑:      {avg_ema:.1f} μs ({avg_ema/1000:.3f} ms)")
    print(f"  Stabilizer:    {avg_stab:.1f} μs ({avg_stab/1000:.3f} ms)")
    print(f"  ODE 步进:      {avg_ode:.1f} μs ({avg_ode/1000:.3f} ms)")
    print(f"  Plutchik:      {avg_plutchik:.1f} μs ({avg_plutchik/1000:.3f} ms)")
    print(f"  模板生成:      {avg_tpl:.1f} μs ({avg_tpl/1000:.3f} ms)")
    print(f"  异常检测:      {avg_anom:.1f} μs ({avg_anom/1000:.3f} ms)")
    print(f"  {'─'*50}")
    total_us = avg_body + avg_sig + avg_pad + avg_ema + avg_stab + avg_ode + avg_plutchik + avg_tpl + avg_anom
    print(f"  端到端:        {total_us:.1f} μs ({total_us/1000:.3f} ms)")
    print(f"  吞吐量:        {1_000_000/total_us:,.0f} 次/秒")
    print(f"  结论:          {'✅ 远超需求' if total_us < 5000 else '⚠️ 可能需要优化'}")


def run_flicker_test():
    """闪烁测试：用 V6 管线测试 Stabilizer 的 inertia 参数"""
    print(f"\n{'='*60}")
    print(f"📊 闪烁测试：V6 Stabilizer 惯性窗口")
    print(f"{'='*60}")

    for inertia_window in [0, 2, 3, 5, 8]:
        sim = SystemSimulator(seed=42)
        sim.set_scenario("spike")

        history = MetricsHistory(window_size=10)
        ema = AdaptiveEMAFilter()
        body = BodySenseManager()
        stabilizer = QuadrantStabilizer(inertia_window=inertia_window)
        ode = ODEDynamics(DEFAULT_ODE_CONFIG)

        quadrant_changes = 0
        last_q = None
        steps = 45

        for i in range(steps):
            m = sim.next()
            metrics_dict = sim_to_metrics_dict(m)
            cpu = metrics_dict["cpu_percent"]
            mem = metrics_dict["mem_percent"]
            error_proxy = m.error_rate
            latency_proxy = m.latency_ms

            history.update(cpu, error_proxy, latency_proxy)

            # V6 管线
            body_kwargs = build_body_sense_kwargs(metrics_dict, cpu, mem, error_proxy, latency_proxy)
            body_sense = body.update(**body_kwargs)

            sig = extract_signals(cpu=cpu, mem=mem, error_rate=error_proxy, latency_ms=latency_proxy)
            pad_output = compose_pad(sig, body=body_sense)
            raw_pad = PADState(p=pad_output.p, a=pad_output.a, d=pad_output.d, volatility=pad_output.v).clamp()

            smooth_pad = ema.update(raw_pad)

            p_s, a_s, d_s, q, is_trans = stabilizer.update(
                smooth_pad.p, smooth_pad.a, smooth_pad.d, context=sig.context,
            )

            if last_q is not None and q != last_q:
                quadrant_changes += 1
            last_q = q

        status = ('✅ 稳定' if quadrant_changes <= 3
                  else '⚠️ 较频繁' if quadrant_changes <= 6
                  else '❌ 闪烁')
        print(f"  惯性窗口={inertia_window} → 象限切换 {quadrant_changes} 次 / {steps} 步  {status}")


def run_realtime(hz, alpha, fast, quiet):
    """实时模式：用 RealMetricCollector 采集真实数据，经 V6 管线"""
    from pad_model import MetricsHistory

    print(f"\n🟢 实时模式 — V6 BodySense 管线")
    print(f"   采样: {hz} Hz | 按 Ctrl+C 停止\n")

    # 初始化采集器和管线
    collector = RealMetricCollector(interval=1.0 / hz)
    buffer = DirtyDataBuffer(max_gap=3, cliff_threshold=3.0)
    history = MetricsHistory(window_size=10)
    ema = AdaptiveEMAFilter()
    body = BodySenseManager()
    stabilizer = QuadrantStabilizer()
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)
    throttler = OutputThrottler(interval_sec=5)

    step = 0
    start_time = time.time()
    output_count = 0
    anomaly_count = 0
    quadrant_counts: dict[str, int] = {}

    try:
        for raw, derived in collector.stream():
            step += 1

            # 1. 采集 → 指标字典
            metrics_dict = raw_to_metrics_dict(raw, derived)

            # 2. 脏数据清洗
            clean_result = buffer.process(metrics_dict)
            if not clean_result.is_valid:
                if not quiet:
                    print(f"[{step:04d}] ⚠️ 数据无效，跳过")
                continue

            # 3. 指标提取
            cpu, mem, error_proxy, latency_proxy = cleaned_to_pad_input(clean_result.data)

            # 4. 历史窗口
            history.update(cpu, error_proxy, latency_proxy)

            # 5. 异常检测
            anomaly = detect_anomaly(cpu, mem, error_proxy, latency_proxy, history)

            # 6. V6 管线
            result = run_v6_pipeline_step(
                step - 1, cpu, mem, error_proxy, latency_proxy,
                clean_result.data, history,
                body, ema, stabilizer, ode, throttler, anomaly,
                verbose=not quiet, fast=fast,
            )

            q_name = result["quadrant"]
            quadrant_counts[q_name] = quadrant_counts.get(q_name, 0) + 1
            if result["is_anomaly"]:
                anomaly_count += 1
            if result["is_output"] and result["expression"]:
                output_count += 1

    except KeyboardInterrupt:
        pass

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[DONE] 运行 {elapsed:.0f}s | 采集 {step} 次 | 输出 {output_count} 条 | 异常 {anomaly_count} 次")
    if quadrant_counts:
        total = sum(quadrant_counts.values())
        print(f"\n📈 象限分布:")
        for q, count in sorted(quadrant_counts.items(), key=lambda x: -x[1]):
            bar = '█' * int(count / total * 30)
            print(f"  {q:8s}  {bar}  {count:3d} ({count/total*100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="情绪引擎 V6.2 — 完整管线入口")
    parser.add_argument("--scenario", type=str, default=None,
                        help="指定场景: normal/spike/error_burst/gradual_overload/recovery")
    parser.add_argument("--hz", type=float, default=1.0, help="采样频率 (Hz)")
    parser.add_argument("--benchmark", action="store_true", help="性能基准测试")
    parser.add_argument("--flicker", action="store_true", help="闪烁测试")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    parser.add_argument("--fast", action="store_true", help="快速模式（无延迟）")
    parser.add_argument("--alpha", type=float, default=0.3, help="EMA alpha 参数（兼容旧接口）")
    args = parser.parse_args()

    print("🧠 情绪引擎 V6.2 — BodySense + 上下文感知 PAD")
    print(f"   管线: 采集 → BodySense → SemanticSig → ContextPAD → EMA → Stabilizer → ODE → Plutchik")
    print(f"   采样: {args.hz} Hz | 间隔: {1000/args.hz:.0f} ms")

    # ── 基准模式 ──
    if args.benchmark:
        run_benchmark(args.hz, args.alpha)
        return

    # ── 闪烁测试 ──
    if args.flicker:
        run_flicker_test()
        return

    # ── 场景模式 ──
    if args.scenario:
        matched = [s for s in SCENARIOS if s[0] == args.scenario]
        if not matched:
            print(f"❌ 未知场景: {args.scenario}")
            print(f"   可选: {', '.join(s[0] for s in SCENARIOS)}")
            return
        name, steps, desc = matched[0]
        sim = SystemSimulator(seed=42)
        print(f"\n{desc}")
        run_scenario(sim, name, steps, args.hz,
                     verbose=not args.quiet, fast=args.fast, alpha=args.alpha)
        return

    # ── 无 --scenario：全部场景依次运行 ──
    if not args.scenario:
        # 检查是否有真实采集器可用
        try:
            collector = RealMetricCollector(interval=1.0)
            # 快速测试一下能否采集
            import psutil
            psutil.cpu_percent(interval=0)
            has_real_collector = True
        except Exception:
            has_real_collector = False

        if has_real_collector:
            # 有真实采集器 → 实时模式
            run_realtime(args.hz, args.alpha, args.fast, args.quiet)
        else:
            # 无真实采集器 → 模拟全部场景
            sim = SystemSimulator(seed=42)
            all_q: dict[str, int] = {}
            total_anomaly = 0
            total_steps = 0

            for name, steps, desc in SCENARIOS:
                print(f"\n{desc}")
                q_counts, _, anomaly_cnt = run_scenario(
                    sim, name, steps, args.hz,
                    verbose=not args.quiet, fast=args.fast, alpha=args.alpha,
                )
                for k, v in q_counts.items():
                    all_q[k] = all_q.get(k, 0) + v
                total_anomaly += anomaly_cnt
                total_steps += steps

            total = sum(all_q.values())
            print(f"\n{'='*60}")
            print(f"📈 汇总统计")
            print(f"{'='*60}")
            for q, count in sorted(all_q.items(), key=lambda x: -x[1]):
                bar = '█' * int(count / total * 30)
                print(f"  {q:8s}  {bar}  {count:3d} ({count/total*100:.1f}%)")
            print(f"  {'总计':8s}  {'─'*30}  {total:3d}")
            print(f"\n  异常总数: {total_anomaly}")


if __name__ == "__main__":
    main()
