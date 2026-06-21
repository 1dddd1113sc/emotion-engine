"""V6.2 异常注入采集 — 主动制造压力，生成多样化训练数据"""
import os
import sys, time, csv, os, signal, json, threading, subprocess, random, tempfile
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_collector import RealMetricCollector
from body_sense import BodySenseManager
from semantic_signals import extract_signals
from context_pad import compose_pad
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer
from ode_dynamics import ODEDynamics, DEFAULT_ODE_CONFIG, EmotionState
from pad_model import PADState
from plutchik import classify_plutchik, format_plutchik

# ============================================================
# 配置
# ============================================================
INTERVAL = 1.0
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data_stress.csv')
JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data_stress.json')

# 异常场景时间表（秒）
SCENARIOS = [
    # (开始秒, 持续秒, 描述, 场景类型)
    (0,   15,  "基线idle",          "idle"),
    (15,  20,  "CPU飙升100%",       "cpu_burn"),
    (35,  10,  "恢复期",            "recovery"),
    (45,  20,  "内存压力(分配2GB)", "mem_pressure"),
    (65,  10,  "恢复期",            "recovery"),
    (75,  20,  "IO压力(大量写入)",  "io_burn"),
    (95,  10,  "恢复期",            "recovery"),
    (105, 20,  "CPU+内存 双重压力", "cpu_mem"),
    (125, 10,  "恢复期",            "recovery"),
    (135, 20,  "线程炸弹(50线程)",  "thread_bomb"),
    (155, 10,  "恢复期",            "recovery"),
    (165, 20,  "混合全压(CPU+IO+Mem)", "full_stress"),
    (185, 15,  "最终恢复",          "recovery"),
]
TOTAL_DURATION = 200  # 总采集时间秒

FIELDS = [
    'time', 'step', 'scenario',
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

# ============================================================
# 压力制造器
# ============================================================
class StressGenerator:
    """根据场景类型制造真实系统压力"""

    CPU_BURN_SCRIPT = '''
import time
while True:
    _ = sum(i * i for i in range(10000))
'''

    def __init__(self):
        self._workers = []
        self._stop_event = threading.Event()
        self._active_scenario = "idle"

    def _spawn_cpu_burners(self, n: int):
        """Windows: 用 subprocess 启动 CPU burner，避免 multiprocessing pickle 问题"""
        for _ in range(n):
            p = subprocess.Popen(
                [sys.executable, "-c", self.CPU_BURN_SCRIPT],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._workers.append(p)

    def start_scenario(self, scenario: str):
        self.stop()
        self._stop_event.clear()
        self._active_scenario = scenario

        if scenario == "cpu_burn":
            # CPU: 多核满载
            n = os.cpu_count() or 4
            self._spawn_cpu_burners(n)

        elif scenario == "mem_pressure":
            # 内存: 分配大块内存并持续写入
            t = threading.Thread(target=self._mem_pressure, daemon=True)
            t.start()
            self._workers.append(t)

        elif scenario == "io_burn":
            # IO: 大量写入临时文件
            t = threading.Thread(target=self._io_burner, daemon=True)
            t.start()
            self._workers.append(t)

        elif scenario == "cpu_mem":
            # CPU + 内存双重
            n = max(1, (os.cpu_count() or 4) // 2)
            self._spawn_cpu_burners(n)
            t = threading.Thread(target=self._mem_pressure, daemon=True)
            t.start()
            self._workers.append(t)

        elif scenario == "thread_bomb":
            # 大量线程
            for _ in range(50):
                t = threading.Thread(target=self._thread_sleeper, daemon=True)
                t.start()
                self._workers.append(t)

        elif scenario == "full_stress":
            # 全压
            n = os.cpu_count() or 4
            self._spawn_cpu_burners(n)
            t1 = threading.Thread(target=self._mem_pressure, daemon=True)
            t1.start()
            self._workers.append(t1)
            t2 = threading.Thread(target=self._io_burner, daemon=True)
            t2.start()
            self._workers.append(t2)
            for _ in range(30):
                t = threading.Thread(target=self._thread_sleeper, daemon=True)
                t.start()
                self._workers.append(t)

        elif scenario in ("idle", "recovery"):
            pass  # 不施加压力

    def stop(self):
        self._stop_event.set()
        for w in self._workers:
            if isinstance(w, subprocess.Popen):
                w.terminate()
                try:
                    w.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    w.kill()
            elif isinstance(w, threading.Thread):
                w.join(timeout=2)
        self._workers.clear()
        self._active_scenario = "idle"

    def _mem_pressure(self):
        """分配大量内存并周期性写入"""
        chunks = []
        try:
            for _ in range(50):
                if self._stop_event.is_set():
                    break
                chunks.append(bytearray(40 * 1024 * 1024))  # 40MB each
                time.sleep(0.3)
            while not self._stop_event.is_set():
                for c in chunks:
                    c[0] = (c[0] + 1) % 256
                time.sleep(0.1)
        except MemoryError:
            pass
        finally:
            chunks.clear()

    def _io_burner(self):
        """大量小文件写入"""
        tmpdir = tempfile.gettempdir()
        i = 0
        while not self._stop_event.is_set():
            fname = os.path.join(tmpdir, f"stress_io_{i}.tmp")
            try:
                with open(fname, 'wb') as f:
                    f.write(os.urandom(1024 * 1024))  # 1MB
                os.unlink(fname)
            except:
                pass
            i += 1

    def _thread_sleeper(self):
        while not self._stop_event.is_set():
            time.sleep(0.5)

    def get_active_scenario(self) -> str:
        return self._active_scenario


# ============================================================
# 主采集
# ============================================================
def main():
    running = True
    def stop_handler(sig, frame):
        nonlocal running
        running = False
        print("\n\n停止中...")
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    # 初始化
    collector = RealMetricCollector(interval=INTERVAL)
    body_mgr = BodySenseManager()
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    stab = QuadrantStabilizer()
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)
    stress = StressGenerator()

    import psutil
    psutil.cpu_percent(interval=0)
    time.sleep(0.5)
    collector.collect_once()

    # CSV
    csv_file = open(CSV_PATH, 'w', newline='', encoding='utf-8-sig', buffering=1)
    writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
    writer.writeheader()
    csv_file.flush()

    json_data = []

    print("=" * 100)
    print("V6.2 异常注入采集启动")
    print(f"总时长: {TOTAL_DURATION}s | 场景数: {len(SCENARIOS)}")
    print("=" * 100)
    for start_s, dur, desc, stype in SCENARIOS:
        print(f"  t={start_s:3d}s  [{stype:12s}] {desc} ({dur}s)")
    print("=" * 100)
    print("采集中...\n")

    step = 0
    start_time = time.time()
    last_scenario = None

    try:
        while running:
            elapsed = time.time() - start_time
            if elapsed > TOTAL_DURATION:
                break

            t_step = time.monotonic()

            # 检查当前场景
            current_scenario = "idle"
            for start_s, dur, desc, stype in SCENARIOS:
                if start_s <= elapsed < start_s + dur:
                    current_scenario = stype
                    break

            if current_scenario != last_scenario:
                if last_scenario is not None:
                    print(f"\n>>> t={elapsed:.0f}s 切换场景: {last_scenario} -> {current_scenario}")
                stress.start_scenario(current_scenario)
                last_scenario = current_scenario

            # 采集
            raw, derived = collector.collect_once()
            step += 1

            # 语义信号
            err_rate = raw.error_rate if raw.error_rate is not None else 0
            lat_ms = raw.response_p99_ms if raw.response_p99_ms is not None else 50
            sig = extract_signals(
                cpu=raw.cpu_percent, mem=raw.mem_percent,
                error_rate=err_rate, latency_ms=lat_ms,
                swap_percent=raw.swap_percent, disk_usage=raw.disk_usage_c,
            )

            # 体感
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

            # 上下文 PAD
            pad = compose_pad(sig, body=body)

            # EMA
            pad_state = PADState(p=pad.p, a=pad.a, d=pad.d, volatility=pad.v)
            smooth = ema.update(pad_state)

            # 防闪烁
            s_p, s_a, s_d, quadrant, is_transition = stab.update(
                smooth.p, smooth.a, smooth.d, context=sig.context
            )

            # ODE
            target = EmotionState(
                p=s_p, a=s_a, d=s_d, v=smooth.volatility,
                f=body.fatigue, t=body.tension, c=body.comfort,
            )
            emo = ode.step(target)

            # Plutchik
            plutchik = classify_plutchik(emo.p, emo.a, emo.d)
            plutchik_str = format_plutchik(plutchik)

            # 写 CSV
            row = {
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'step': step,
                'scenario': current_scenario,
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
            csv_file.flush()

            # JSON
            json_data.append({
                'step': step, 'time': row['time'], 'scenario': current_scenario,
                'raw': {'cpu': raw.cpu_percent, 'mem': raw.mem_percent, 'err': err_rate},
                'body': {'fatigue': body.fatigue, 'tension': body.tension, 'comfort': body.comfort},
                'sig': {'error': sig.error, 'load': sig.load, 'latency': sig.latency, 'ctx': sig.context},
                'pad': {'p': pad.p, 'a': pad.a, 'd': pad.d, 'v': pad.v},
                'ode': {'p': emo.p, 'a': emo.a, 'd': emo.d, 'v': emo.v, 'f': emo.f, 't': emo.t, 'c': emo.c},
                'plutchik': plutchik_str,
                'quadrant': str(quadrant),
            })

            # 控制台输出
            if step % 3 == 1 or step <= 3:
                cpu_bar = '#' * min(int(raw.cpu_percent / 5), 20) + '.' * max(20 - int(raw.cpu_percent / 5), 0)
                f_bar = '#' * int(body.fatigue * 10) + '.' * (10 - int(body.fatigue * 10))
                ctx_tag = {'clean': 'C', 'degraded': 'D', 'err': 'E'}.get(sig.context, '?')
                trans_tag = ' *TRANS*' if is_transition else ''
                print(f"[{step:04d}] t={elapsed:5.1f}s [{current_scenario:12s}] "
                      f"CPU=[{cpu_bar}] {raw.cpu_percent:4.1f}%  "
                      f"M={raw.mem_percent:.0f}%  "
                      f"F[{f_bar}] {body.fatigue:.2f}  "
                      f"P={emo.p:+.2f} A={emo.a:+.2f} D={emo.d:+.2f}  "
                      f"CTX={ctx_tag}  {plutchik_str}{trans_tag}", flush=True)

            # 间隔控制
            step_time = time.monotonic() - t_step
            sleep_time = max(0, INTERVAL - step_time)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass
    finally:
        stress.stop()
        csv_file.close()
        with open(JSON_PATH, 'w', encoding='utf-8') as jf:
            json.dump(json_data, jf, ensure_ascii=False, indent=1)

    elapsed_total = time.time() - start_time
    print(f"\n{'='*100}")
    print(f"[DONE] 运行 {elapsed_total:.0f}s | 采集 {step} 步")
    print(f"CSV: {CSV_PATH}")
    print(f"JSON: {JSON_PATH}")

    # 统计
    if json_data:
        import pandas as pd
        df = pd.read_csv(CSV_PATH, encoding='utf-8-sig')
        print(f"\n=== 场景分布 ===")
        print(df['scenario'].value_counts().to_string())
        print(f"\n=== 情绪分布 ===")
        print(df['plutchik'].value_counts().to_string())
        print(f"\n=== 象限分布 ===")
        print(df['quadrant'].value_counts().to_string())
        print(f"\n=== 关键指标范围 ===")
        print(f"  CPU: [{df['cpu_pct'].min():.1f}, {df['cpu_pct'].max():.1f}]")
        print(f"  Fatigue: [{df['fatigue'].min():.3f}, {df['fatigue'].max():.3f}]")
        print(f"  Tension: [{df['tension'].min():.3f}, {df['tension'].max():.3f}]")
        print(f"  Comfort: [{df['comfort'].min():.3f}, {df['comfort'].max():.3f}]")


if __name__ == '__main__':
    main()