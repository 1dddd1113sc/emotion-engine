"""V6.2 实时采集 — 使用新管线（BodySense → SemanticSignals → ContextPAD → ODE）"""
import os
import sys, time, csv, os, signal, json
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_collector import RealMetricCollector, format_metrics
from body_sense import BodySenseManager
from semantic_signals import extract_signals
from context_pad import compose_pad
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer
from ode_dynamics import ODEDynamics, ODEConfig, DEFAULT_ODE_CONFIG
from pad_model import PADState
from plutchik import classify_plutchik, format_plutchik

INTERVAL = 1.0
MAX_STEPS = None  # None = 无限采集
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data_v62.json')

FIELDS = [
    'time', 'step',
    # 原始指标
    'cpu_pct', 'mem_pct', 'swap_pct',
    'io_latency_ms', 'close_wait_r', 'threads',
    'error_rate', 'cpu_overwork', 'health_score',
    'cpu_temp', 'gpu_temp', 'thermal_stress',
    # 语义信号
    'sig_error', 'sig_load', 'sig_latency', 'sig_health', 'sig_context',
    # 体感
    'fatigue', 'tension', 'comfort', 'exhaustion',
    # PAD
    'pad_p', 'pad_a', 'pad_d', 'pad_v',
    # ODE
    'ode_p', 'ode_a', 'ode_d', 'ode_v', 'ode_f', 'ode_t', 'ode_c',
    # Plutchik
    'plutchik', 'plutchik_conf',
    # 象限
    'quadrant',
]

running = True
def stop(sig, frame):
    global running
    running = False
    print("\n停止中...")
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

# 初始化组件
collector = RealMetricCollector(interval=INTERVAL)
body_mgr = BodySenseManager()
ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
stab = QuadrantStabilizer()
ode = ODEDynamics(DEFAULT_ODE_CONFIG)

import psutil
psutil.cpu_percent(interval=0)
time.sleep(0.5)
collector.collect_once()

# 写表头（新文件或强制覆盖）
write_header = not os.path.exists(CSV_PATH)
csv_file = open(CSV_PATH, 'w' if write_header else 'a', newline='', encoding='utf-8-sig', buffering=1)
writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
if write_header:
    writer.writeheader()
    csv_file.flush()

# JSON 详细数据
json_data = []

print(f"V6.2 实时采集启动 (interval={INTERVAL}s)")
print(f"CSV: {CSV_PATH}")
print(f"JSON: {JSON_PATH}")
print(f"按 Ctrl+C 停止\n")
print(f"{'='*100}")

step = 0
start_time = time.time()

try:
    while running:
        t_start = time.monotonic()
        raw, derived = collector.collect_once()
        step += 1

        # === L3 语义信号层（先提取，供 L2 体感层使用）===
        err_rate = raw.error_rate if raw.error_rate is not None else 0
        lat_ms = raw.response_p99_ms if raw.response_p99_ms is not None else 50
        sig = extract_signals(
            cpu=raw.cpu_percent, mem=raw.mem_percent,
            error_rate=err_rate, latency_ms=lat_ms,
            swap_percent=raw.swap_percent, disk_usage=raw.disk_usage_c,
        )

        # === L2 体感层 ===
        body = body_mgr.update(
            load_signal=raw.cpu_percent / 100.0,
            cpu_overwork=derived.cpu_overwork,
            freq_throttle=derived.freq_throttle,
            ctx_switches_rate=derived.ctx_switches_rate,
            syscalls_rate=derived.syscalls_rate,
            listen_backlog=derived.listen_backlog,
            close_wait_ratio=derived.close_wait_ratio,
            conn_churn_rate=derived.conn_churn_rate,
            thread_density=derived.thread_density,
            disk_io_latency_ms=derived.disk_io_latency_ms,
            io_congestion=derived.io_congestion,
            disk_queue_depth=raw.disk_queue_depth,
            interrupts_rate=derived.interrupts_rate,
            interrupt_ratio=derived.interrupt_ratio,
            dpc_ratio=derived.dpc_ratio,
            thermal_stress=derived.thermal_stress,
            gpu_stress=derived.gpu_stress,
            disk_usage=raw.disk_usage_c,
            swap_percent=raw.swap_percent,
            mem_available_gb=raw.mem_available_gb,
            mem_percent=raw.mem_percent,
            sig_load=sig.load,
            gpu_temp=raw.gpu_temp,
        )

        # === L3 上下文 PAD ===
        pad = compose_pad(sig, body=body)

        # === EMA 平滑 ===
        pad_state = PADState(p=pad.p, a=pad.a, d=pad.d, volatility=pad.v)
        smooth = ema.update(pad_state)

        # === 防闪烁 ===
        s_p, s_a, s_d, quadrant, is_transition = stab.update(
            smooth.p, smooth.a, smooth.d, context=sig.context
        )

        # === L4 ODE 动力层 ===
        from ode_dynamics import EmotionState
        target = EmotionState(
            p=s_p, a=s_a, d=s_d, v=smooth.volatility,
            f=body.fatigue, t=body.tension, c=body.comfort,
        )
        emo = ode.step(target)

        # === Plutchik ===
        plutchik = classify_plutchik(emo.p, emo.a, emo.d)
        plutchik_str = format_plutchik(plutchik)

        # 写 CSV
        row = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'step': step,
            'cpu_pct': f"{raw.cpu_percent:.1f}",
            'mem_pct': f"{raw.mem_percent:.1f}",
            'swap_pct': f"{raw.swap_percent:.1f}",
            'io_latency_ms': f"{derived.disk_io_latency_ms:.2f}",
            'close_wait_r': f"{derived.close_wait_ratio:.3f}",
            'threads': raw.thread_count,
            'error_rate': f"{err_rate:.2f}",
            'cpu_overwork': f"{derived.cpu_overwork:.3f}",
            'health_score': f"{derived.health_score:.3f}",
            'cpu_temp': raw.cpu_temp if raw.cpu_temp is not None else -1,
            'gpu_temp': raw.gpu_temp if raw.gpu_temp is not None else -1,
            'thermal_stress': f"{derived.thermal_stress:.3f}",
            'sig_error': f"{sig.error:.3f}",
            'sig_load': f"{sig.load:.3f}",
            'sig_latency': f"{sig.latency:.3f}",
            'sig_health': f"{sig.health:.3f}",
            'sig_context': sig.context,
            'fatigue': f"{body.fatigue:.3f}",
            'tension': f"{body.tension:.3f}",
            'comfort': f"{body.comfort:.3f}",
            'exhaustion': f"{body.exhaustion_risk:.3f}",
            'pad_p': f"{pad.p:+.3f}",
            'pad_a': f"{pad.a:+.3f}",
            'pad_d': f"{pad.d:+.3f}",
            'pad_v': f"{pad.v:.3f}",
            'ode_p': f"{emo.p:+.3f}",
            'ode_a': f"{emo.a:+.3f}",
            'ode_d': f"{emo.d:+.3f}",
            'ode_v': f"{emo.v:.3f}",
            'ode_f': f"{emo.f:.3f}",
            'ode_t': f"{emo.t:.3f}",
            'ode_c': f"{emo.c:.3f}",
            'plutchik': plutchik_str,
            'plutchik_conf': f"{plutchik.confidence:.2f}",
            'quadrant': quadrant,
        }
        writer.writerow(row)
        csv_file.flush()  # 每步立即写入磁盘

        # JSON 详细数据
        json_data.append({
            'step': step, 'time': row['time'],
            'raw': {'cpu': raw.cpu_percent, 'mem': raw.mem_percent, 'err': err_rate, 'lat': lat_ms},
            'body': {'fatigue': body.fatigue, 'tension': body.tension, 'comfort': body.comfort},
            'sig': {'error': sig.error, 'load': sig.load, 'latency': sig.latency, 'health': sig.health, 'ctx': sig.context},
            'pad': {'p': pad.p, 'a': pad.a, 'd': pad.d, 'v': pad.v},
            'smooth': {'p': smooth.p, 'a': smooth.a, 'd': smooth.d},
            'ode': {'p': emo.p, 'a': emo.a, 'd': emo.d, 'v': emo.v, 'f': emo.f, 't': emo.t, 'c': emo.c},
            'plutchik': plutchik_str,
            'quadrant': str(quadrant),
        })

        # 控制台输出
        if step % 5 == 1 or step <= 3:
            cpu_bar = '#' * int(raw.cpu_percent / 5) + '.' * (20 - int(raw.cpu_percent / 5))
            f_bar = '#' * int(body.fatigue * 10) + '.' * (10 - int(body.fatigue * 10))
            t_bar = '#' * int(body.tension * 10) + '.' * (10 - int(body.tension * 10))
            c_bar = '#' * int(body.comfort * 10) + '.' * (10 - int(body.comfort * 10))
            ctx_tag = {'clean': 'C', 'degraded': 'D', 'err': 'E'}.get(sig.context, '?')
            trans_tag = ' *TRANS*' if is_transition else ''

            print(f"[{step:04d}] CPU=[{cpu_bar}] {raw.cpu_percent:4.1f}%  "
                  f"MEM={raw.mem_percent:.0f}%  ERR={err_rate:.1f}%  "
                  f"CTX={ctx_tag}  "
                  f"P={emo.p:+.2f} A={emo.a:+.2f} D={emo.d:+.2f}  "
                  f"F[{f_bar}] T[{t_bar}] C[{c_bar}]  "
                  f"{plutchik_str}{trans_tag}", flush=True)

        # 每 100 步写一次 JSON
        if step % 100 == 0:
            with open(JSON_PATH, 'w', encoding='utf-8') as jf:
                json.dump(json_data, jf, ensure_ascii=False, indent=1)
            print(f"  ... JSON 已保存 ({step} 步)", flush=True)

        # 间隔控制
        elapsed = time.monotonic() - t_start
        sleep_time = max(0, INTERVAL - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

        # 自动停止
        if MAX_STEPS is not None and step >= MAX_STEPS:
            print(f"\n已达到 {MAX_STEPS} 步，自动停止")
            break

except KeyboardInterrupt:
    pass

# 最终保存
csv_file.close()
with open(JSON_PATH, 'w', encoding='utf-8') as jf:
    json.dump(json_data, jf, ensure_ascii=False, indent=1)

elapsed = time.time() - start_time
print(f"\n{'='*100}")
print(f"[DONE] 运行 {elapsed:.0f}s | 采集 {step} 次")
print(f"CSV: {CSV_PATH}")
print(f"JSON: {JSON_PATH}")

# 快速统计
if json_data:
    fats = [d['body']['fatigue'] for d in json_data]
    tens = [d['body']['tension'] for d in json_data]
    comfs = [d['body']['comfort'] for d in json_data]
    cpus = [d['raw']['cpu'] for d in json_data]

    avg_c = sum(cpus) / len(cpus)
    avg_f = sum(fats) / len(fats)
    n = len(cpus)
    cov = sum((cpus[i] - avg_c) * (fats[i] - avg_f) for i in range(n)) / n
    std_c = (sum((c - avg_c)**2 for c in cpus) / n) ** 0.5
    std_f = (sum((f - avg_f)**2 for f in fats) / n) ** 0.5
    corr = cov / (std_c * std_f) if std_c > 0 and std_f > 0 else 0

    print(f"\n=== 快速验证 ===")
    print(f"  CPU avg: {avg_c:.1f}%  Fatigue avg: {avg_f:.3f}")
    print(f"  CPU-Fatigue 相关系数: {corr:.3f}")
    print(f"  Fatigue range: [{min(fats):.3f}, {max(fats):.3f}]")
    print(f"  Tension range: [{min(tens):.3f}, {max(tens):.3f}]")
    print(f"  Comfort range: [{min(comfs):.3f}, {max(comfs):.3f}]")
