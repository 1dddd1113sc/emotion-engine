"""
情绪引擎 v3 — 四方优化版
Qwen + DeepSeek + GLM + 我的方案融合

用法:
  python main.py --fast                  # 快速完整演示
  python main.py --fast --scenario spike  # 只跑突发负载
  python main.py --benchmark             # 性能基准
  python main.py --flicker               # 闪烁测试
"""
import argparse
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

from pad_model import metrics_to_pad, PADQuadrant, MetricsHistory, detect_anomaly
from ema_filter import AdaptiveEMAFilter
from template_engine import generate_expression, compute_confidence, OutputThrottler
from system_simulator import SystemSimulator


SCENARIOS = [
    ("normal",           20, "🟢 正常运行"),
    ("spike",            45, "🔴 突发负载"),
    ("error_burst",      40, "🟠 错误飙升"),
    ("gradual_overload", 65, "🟡 渐进过载"),
    ("recovery",         45, "🔵 故障恢复"),
]


def run_scenario(sim, ema, scenario, steps, hz, verbose=True, fast=False):
    sim.set_scenario(scenario)
    ema.reset()

    history = MetricsHistory(window_size=10)
    throttler = OutputThrottler(interval_sec=5)
    interval = 1.0 / hz

    quadrant_counts: dict[str, int] = {}
    expressions: list[str] = []
    confidence_sum = 0.0
    llm_needed_count = 0
    anomaly_count = 0
    suppressed_count = 0

    if verbose:
        print(f"\n{'='*60}")
        print(f"场景: {scenario} ({steps} 步, {hz}Hz)")
        print(f"{'='*60}")

    for i in range(steps):
        m = sim.next()
        history.update(m.cpu, m.error_rate, m.latency_ms)

        # 异常检测前处理
        anomaly = detect_anomaly(m.cpu, m.mem, m.error_rate, m.latency_ms, history)

        # PAD 映射（v3：分段P + 乘法D + 速度感知）
        raw_pad = metrics_to_pad(m.cpu, m.mem, m.error_rate, m.latency_ms, history)

        # 自适应 EMA 平滑
        if anomaly.override_pad:
            ema.force_update(anomaly.override_pad)
            smooth_pad = anomaly.override_pad
        else:
            smooth_pad = ema.update(raw_pad)

        # 语言输出频率控制
        should_output = throttler.should_output(smooth_pad.quadrant, anomaly.is_anomaly)

        # 生成表达
        result = generate_expression(
            smooth_pad,
            anomaly_reason=anomaly.reason if anomaly.is_anomaly else None,
        )

        q_name = smooth_pad.quadrant.value
        quadrant_counts[q_name] = quadrant_counts.get(q_name, 0) + 1
        confidence_sum += result.confidence
        llm_needed_count += (1 if result.needs_llm else 0)
        if anomaly.is_anomaly:
            anomaly_count += 1

        if verbose:
            top2 = ", ".join(f"{k}:{v:.1%}" for k, v in result.top_emotions)
            anomaly_tag = " 🚨异常" if anomaly.is_anomaly else ""
            llm_tag = " 🔶需LLM" if result.needs_llm else ""
            suppressed = not should_output

            print(f"\n[{i+1:02d}] CPU={m.cpu:5.1f}% MEM={m.mem:5.1f}% "
                  f"ERR={m.error_rate:5.2f}% LAT={m.latency_ms:6.1f}ms")
            print(f"     PAD: P={smooth_pad.p:+.3f} A={smooth_pad.a:+.3f} D={smooth_pad.d:+.3f}"
                  f" V={smooth_pad.volatility:.2f}")
            print(f"     → {q_name} | 置信={result.confidence:.2f} | [{top2}]"
                  f"{anomaly_tag}{llm_tag}")

            if suppressed:
                print(f"     🔇 [节流]")
                suppressed_count += 1
            else:
                print(f"     💬 {result.text}")
                expressions.append(result.text)

        if not fast:
            time.sleep(interval)

    total_steps = len(expressions) if expressions else 1
    avg_confidence = confidence_sum / steps if steps > 0 else 0
    llm_ratio = llm_needed_count / steps if steps > 0 else 0

    if verbose:
        print(f"\n  📊 统计: 置信度={avg_confidence:.2f} | "
              f"需LLM={llm_ratio:.0%} | 异常={anomaly_count}次 | "
              f"节流={suppressed_count}次 | 输出={len(expressions)}条")

    return quadrant_counts, expressions, avg_confidence, llm_needed_count


def run_benchmark(hz, alpha):
    from pad_model import PADState, MetricsHistory
    import timeit

    ema = AdaptiveEMAFilter()
    history = MetricsHistory()
    for _ in range(10):
        history.update(50, 1, 100)
    test_pad = PADState(0.5, -0.3, 0.7, 0.1)
    ema.update(test_pad)

    n = 10000
    elapsed = timeit.timeit(lambda: generate_expression(test_pad), number=n)
    avg_us = elapsed / n * 1_000_000

    elapsed2 = timeit.timeit(lambda: metrics_to_pad(50, 60, 5, 200, history), number=n)
    avg_us2 = elapsed2 / n * 1_000_000

    elapsed3 = timeit.timeit(lambda: detect_anomaly(50, 60, 5, 200, history), number=n)
    avg_us3 = elapsed3 / n * 1_000_000

    print(f"\n{'='*60}")
    print(f"⚡ 性能基准 (v3)")
    print(f"{'='*60}")
    print(f"  PAD 映射:      {avg_us2:.1f} μs ({avg_us2/1000:.3f} ms)")
    print(f"  异常检测:      {avg_us3:.1f} μs ({avg_us3/1000:.3f} ms)")
    print(f"  模板生成:      {avg_us:.1f} μs ({avg_us/1000:.3f} ms)")
    total_us = avg_us2 + avg_us3 + avg_us
    print(f"  端到端:        {total_us:.1f} μs")
    print(f"  吞吐量:        {1_000_000/total_us:,.0f} 次/秒")
    print(f"  结论:          {'✅ 远超需求' if total_us < 1000 else '⚠️ 可能需要优化'}")


def run_flicker_test():
    print(f"\n{'='*60}")
    print(f"📊 闪烁测试：v3 自适应 EMA + 情绪惯性")
    print(f"{'='*60}")

    for inertia in [0.0, 0.2, 0.3, 0.5]:
        sim = SystemSimulator(seed=42)
        ema = AdaptiveEMAFilter(inertia=inertia)
        history = MetricsHistory()
        sim.set_scenario("spike")

        quadrant_changes = 0
        last_q = None
        steps = 45

        for _ in range(steps):
            m = sim.next()
            history.update(m.cpu, m.error_rate, m.latency_ms)
            raw = metrics_to_pad(m.cpu, m.mem, m.error_rate, m.latency_ms, history)
            smooth = ema.update(raw)
            q = smooth.quadrant
            if last_q is not None and q != last_q:
                quadrant_changes += 1
            last_q = q

        status = '✅ 稳定' if quadrant_changes <= 3 else '⚠️ 较频繁' if quadrant_changes <= 6 else '❌ 闪烁'
        print(f"  惯性={inertia:.1f} → 象限切换 {quadrant_changes} 次 / {steps} 步  {status}")


def main():
    parser = argparse.ArgumentParser(description="情绪引擎 v3 — 四方优化版")
    parser.add_argument("--scenario", type=str, default=None)
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--flicker", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.3)
    args = parser.parse_args()

    print("🧠 情绪引擎 v3 — 四方优化版")
    print(f"   分段P + 乘法D + 速度感知 + 软分类 + 异常检测")
    print(f"   采样: {args.hz} Hz | 间隔: {1000/args.hz:.0f} ms")

    if args.benchmark:
        run_benchmark(args.hz, args.alpha)
        return

    if args.flicker:
        run_flicker_test()
        return

    sim = SystemSimulator(seed=42)
    ema = AdaptiveEMAFilter()

    if args.scenario:
        matched = [s for s in SCENARIOS if s[0] == args.scenario]
        if not matched:
            print(f"❌ 未知场景: {args.scenario}")
            print(f"   可选: {', '.join(s[0] for s in SCENARIOS)}")
            return
        name, steps, desc = matched[0]
        print(f"\n{desc}")
        run_scenario(sim, ema, name, steps, args.hz, verbose=not args.quiet, fast=args.fast)
    else:
        all_q: dict[str, int] = {}
        total_confidence = 0.0
        total_llm_needed = 0
        total_steps = 0

        for name, steps, desc in SCENARIOS:
            print(f"\n{desc}")
            q_counts, _, avg_conf, llm_cnt = run_scenario(
                sim, ema, name, steps, args.hz,
                verbose=not args.quiet, fast=args.fast
            )
            for k, v in q_counts.items():
                all_q[k] = all_q.get(k, 0) + v
            total_confidence += avg_conf * steps
            total_llm_needed += llm_cnt
            total_steps += steps

        total = sum(all_q.values())
        print(f"\n{'='*60}")
        print(f"📈 汇总统计")
        print(f"{'='*60}")
        for q, count in sorted(all_q.items(), key=lambda x: -x[1]):
            bar = '█' * int(count / total * 30)
            print(f"  {q:8s}  {bar}  {count:3d} ({count/total*100:.1f}%)")
        print(f"  {'总计':8s}  {'─'*30}  {total:3d}")

        overall_conf = total_confidence / total_steps if total_steps > 0 else 0
        llm_ratio = total_llm_needed / total_steps if total_steps > 0 else 0
        print(f"\n{'='*60}")
        print(f"🎯 置信度分流")
        print(f"{'='*60}")
        print(f"  平均置信度:   {overall_conf:.3f}")
        print(f"  需 LLM 比例:  {llm_ratio:.1%}")
        print(f"  模板覆盖率:   {1-llm_ratio:.1%}")


if __name__ == "__main__":
    main()
