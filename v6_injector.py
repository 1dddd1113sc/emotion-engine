"""
V6.2 压力注入器 — 模拟真实业务负载，生成多样化训练数据

设计思路：
- 在后台采集器运行的同时，注入脚本周期性注入合成信号
- 通过修改 shared state 或直接写入 CSV（作为额外行），模拟各种工况
- 目标：让 LLM 看到"低负载轻松"到"全层并发崩溃"的全谱段情绪

注入场景（按复杂度递增）：
1. 空闲          — CPU 5-15%,  no errors
2. 轻度负载      — CPU 30-50%, no errors
3. 中度负载+IO   — CPU 60-80%, IO latency 20ms
4. L4 错误注入   — error_rate 5-15%, CPU 50-70%
5. 连接风暴      — close_wait 高, CPU 70-85%
6. L5 过热       — GPU 70°C+, CPU 80-95%
7. 全层并发崩溃  — 所有信号同时恶化
8. 恢复          — 从高负载逐步降回正常

运行方式：
    python v6_injector.py --scenario all --duration 600
    python v6_injector.py --scenario 4 --duration 120
"""
import sys, time, csv, os, random, argparse, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

WORK_DIR = Path(__file__).parent
CSV_PATH = WORK_DIR / 'v6_live_data.csv'

# 37 列 header
FIELDS = [
    'time', 'step',
    'cpu_pct', 'mem_pct', 'swap_pct',
    'io_latency_ms', 'close_wait_r', 'threads',
    'error_rate', 'cpu_overwork', 'health_score',
    'cpu_temp', 'gpu_temp', 'thermal_stress',
    'sig_error', 'sig_load', 'sig_latency', 'sig_health', 'sig_context',
    'fatigue', 'tension', 'comfort', 'exhaustion',
    'pad_p', 'pad_a', 'pad_d', 'pad_v',
    'ode_p', 'ode_a', 'ode_d', 'ode_v', 'ode_f', 'ode_t', 'ode_c',
    'plutchik', 'plutchik_conf', 'quadrant',
]

# 模拟场景定义
SCENARIOS = {
    'idle': {
        'label': '空闲',
        'cpu_range': (3, 15),
        'mem_range': (45, 55),
        'swap': 6.0,
        'io_latency': 0.0,
        'close_wait': 0.02,
        'threads': 5000,
        'error_rate': 0.0,
        'cpu_temp': 45,
        'gpu_temp': 50,
        'thermal_stress': 0.0,
        'ctx': 'clean',
        'duration': 60,
    },
    'light_load': {
        'label': '轻度负载',
        'cpu_range': (30, 50),
        'mem_range': (50, 60),
        'swap': 7.0,
        'io_latency': 1.0,
        'close_wait': 0.03,
        'threads': 5200,
        'error_rate': 0.0,
        'cpu_temp': 48,
        'gpu_temp': 52,
        'thermal_stress': 0.0,
        'ctx': 'clean',
        'duration': 60,
    },
    'moderate_load_io': {
        'label': '中度负载+IO',
        'cpu_range': (60, 80),
        'mem_range': (55, 65),
        'swap': 10.0,
        'io_latency': (15, 30),
        'close_wait': 0.05,
        'threads': 5500,
        'error_rate': 0.0,
        'cpu_temp': 55,
        'gpu_temp': 58,
        'thermal_stress': 0.1,
        'ctx': 'degraded',
        'duration': 60,
    },
    'error_burst': {
        'label': 'L4 错误注入',
        'cpu_range': (50, 75),
        'mem_range': (55, 65),
        'swap': 12.0,
        'io_latency': (5, 15),
        'close_wait': 0.06,
        'threads': 5800,
        'error_rate': (5, 15),
        'cpu_temp': 58,
        'gpu_temp': 60,
        'thermal_stress': 0.1,
        'ctx': 'err',
        'duration': 60,
    },
    'conn_storm': {
        'label': '连接风暴',
        'cpu_range': (70, 88),
        'mem_range': (60, 70),
        'swap': 18.0,
        'io_latency': (5, 20),
        'close_wait': (0.15, 0.30),
        'threads': (6800, 8500),
        'error_rate': (1, 3),
        'cpu_temp': 62,
        'gpu_temp': 65,
        'thermal_stress': 0.25,
        'ctx': 'degraded',
        'duration': 60,
    },
    'overheat': {
        'label': 'L5 过热',
        'cpu_range': (80, 98),
        'mem_range': (65, 75),
        'swap': 25.0,
        'io_latency': (10, 35),
        'close_wait': 0.08,
        'threads': 7000,
        'error_rate': (2, 5),
        'cpu_temp': (75, 90),
        'gpu_temp': (70, 85),
        'thermal_stress': (0.4, 0.7),
        'ctx': 'degraded',
        'duration': 60,
    },
    'nightmare': {
        'label': '全层并发崩溃',
        'cpu_range': (90, 100),
        'mem_range': (75, 95),
        'swap': (30, 50),
        'io_latency': (30, 60),
        'close_wait': (0.25, 0.45),
        'threads': (9000, 12000),
        'error_rate': (15, 35),
        'cpu_temp': (85, 95),
        'gpu_temp': (85, 95),
        'thermal_stress': (0.6, 0.9),
        'ctx': 'err',
        'duration': 60,
    },
    'recovery': {
        'label': '恢复',
        'cpu_range': (95, 15),  # 从高到低
        'mem_range': (80, 55),
        'swap': (40, 8),
        'io_latency': (50, 2),
        'close_wait': (0.35, 0.03),
        'threads': (10000, 5200),
        'error_rate': (25, 0),
        'cpu_temp': (90, 50),
        'gpu_temp': (88, 55),
        'thermal_stress': (0.8, 0.05),
        'ctx': 'err',
        'duration': 90,
    },
}


def random_in_range(val):
    """解析范围值，返回随机数"""
    if isinstance(val, tuple):
        lo, hi = val
        if lo > hi:  # 递减范围（如 recovery）
            return random.uniform(hi, lo)
        return random.uniform(lo, hi)
    return val


def write_injected_row(scenario_name: str, scenario: dict, step: int, start_time: float):
    """生成一行模拟数据并写入 CSV"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cpu = random_in_range(scenario['cpu_range'])
    mem = random_in_range(scenario['mem_range'])
    swap = random_in_range(scenario['swap'])
    io_lat = random_in_range(scenario['io_latency'])
    cw = random_in_range(scenario['close_wait'])
    threads = int(random_in_range(scenario['threads']))
    err_rate = random_in_range(scenario['error_rate'])
    cpu_temp = random_in_range(scenario['cpu_temp'])
    gpu_temp = random_in_range(scenario['gpu_temp'])
    thermal = random_in_range(scenario['thermal_stress'])
    ctx = scenario['ctx']

    # 计算派生指标
    cpu_overwork = min(1.0, max(0, (cpu - 60) / 40) * 0.7)
    from semantic_signals import extract_signals
    sig = extract_signals(
        cpu=cpu, mem=mem, error_rate=err_rate, latency_ms=io_lat,
        swap_percent=swap, disk_usage=70,
    )
    health_score = sig.health

    # 体感：简化模型
    fatigue = cpu / 100.0 * 0.7 + thermal * 0.3
    tension = min(1.0, cw * 3 + io_lat / 50 + err_rate / 30)
    comfort = 1.0 - (cpu / 100.0 * 0.4 + thermal * 0.3 + cw * 2 + io_lat / 50 * 0.15)
    comfort = max(0.0, min(1.0, comfort))
    exhaustion = fatigue * tension

    # PAD：简化映射
    pad_p = 0.5 - cpu / 100.0 * 0.4 + comfort * 0.3
    pad_a = -0.3 + cpu / 100.0 * 0.5 + err_rate / 30 * 0.3
    pad_d = 0.2 + cpu / 100.0 * 0.3 + io_lat / 50 * 0.2

    # ODE：跟随 PAD
    ode_p = pad_p
    ode_a = pad_a
    ode_d = pad_d
    ode_v = 0.1
    ode_f = fatigue
    ode_t = tension
    ode_c = comfort

    # Plutchik：简化分类
    from plutchik import classify_plutchik, format_plutchik
    plutchik = classify_plutchik(ode_p, ode_a, ode_d)
    plutchik_str = format_plutchik(plutchik)
    plutchik_conf = plutchik.confidence

    # 象限
    if pad_p > 0 and pad_a > 0:
        quadrant = 'Q1'
    elif pad_p < 0 and pad_a > 0:
        quadrant = 'Q2'
    elif pad_p < 0 and pad_a < 0:
        quadrant = 'Q3'
    elif pad_a < 0.1:
        quadrant = 'C'
    else:
        quadrant = 'Q4'

    row = {
        'time': now,
        'step': f'[INJ]{step}',
        'cpu_pct': f'{cpu:.1f}',
        'mem_pct': f'{mem:.1f}',
        'swap_pct': f'{swap:.1f}',
        'io_latency_ms': f'{io_lat:.2f}',
        'close_wait_r': f'{cw:.3f}',
        'threads': str(threads),
        'error_rate': f'{err_rate:.2f}',
        'cpu_overwork': f'{cpu_overwork:.3f}',
        'health_score': f'{health_score:.3f}',
        'cpu_temp': f'{cpu_temp:.1f}',
        'gpu_temp': f'{gpu_temp:.1f}',
        'thermal_stress': f'{thermal:.3f}',
        'sig_error': f'{sig.error:.3f}',
        'sig_load': f'{sig.load:.3f}',
        'sig_latency': f'{sig.latency:.3f}',
        'sig_health': f'{sig.health:.3f}',
        'sig_context': ctx,
        'fatigue': f'{fatigue:.3f}',
        'tension': f'{tension:.3f}',
        'comfort': f'{comfort:.3f}',
        'exhaustion': f'{exhaustion:.3f}',
        'pad_p': f'{pad_p:+.3f}',
        'pad_a': f'{pad_a:+.3f}',
        'pad_d': f'{pad_d:+.3f}',
        'pad_v': f'{0.1:.3f}',
        'ode_p': f'{ode_p:+.3f}',
        'ode_a': f'{ode_a:+.3f}',
        'ode_d': f'{ode_d:+.3f}',
        'ode_v': f'{ode_v:.3f}',
        'ode_f': f'{ode_f:.3f}',
        'ode_t': f'{ode_t:.3f}',
        'ode_c': f'{ode_c:.3f}',
        'plutchik': plutchik_str,
        'plutchik_conf': f'{plutchik_conf:.2f}',
        'quadrant': quadrant,
    }
    return row


def run_injection(scenarios: list[str], total_duration: int = 600, interval: float = 1.0):
    """运行压力注入"""
    # 解析场景
    if 'all' in scenarios:
        scenario_order = list(SCENARIOS.keys())
    else:
        scenario_order = [s for s in scenarios if s in SCENARIOS]

    if not scenario_order:
        print(f"未知场景: {scenarios}")
        print(f"可用: {list(SCENARIOS.keys())} + all")
        return

    print(f"=== V6.2 压力注入器 ===")
    print(f"场景: {[SCENARIOS[s]['label'] for s in scenario_order]}")
    print(f"总时长: {total_duration}s")
    print(f"输出: {CSV_PATH}\n")

    # 确保 CSV 有 header
    write_header = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, 'a' if not write_header else 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
            f.flush()

    step = 0
    start_time = time.time()

    # 按场景顺序循环，直到总时间到
    scenario_idx = 0
    scenario_start = time.time()
    current_scenario = scenario_order[scenario_idx]
    current_label = SCENARIOS[current_scenario]['label']
    current_duration = SCENARIOS[current_scenario]['duration']

    print(f"[{current_label}] 开始...")

    try:
        while time.time() - start_time < total_duration:
            step += 1

            # 检查是否需要切换场景
            scenario_elapsed = time.time() - scenario_start
            if scenario_elapsed >= current_duration:
                scenario_idx = (scenario_idx + 1) % len(scenario_order)
                current_scenario = scenario_order[scenario_idx]
                current_label = SCENARIOS[current_scenario]['label']
                current_duration = SCENARIOS[current_scenario]['duration']
                scenario_start = time.time()
                print(f"\n[{current_label}] 开始...")

            scenario = SCENARIOS[current_scenario]
            row = write_injected_row(current_scenario, scenario, step, start_time)

            with open(CSV_PATH, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writerow(row)

            # 进度
            if step % 10 == 0:
                elapsed = time.time() - start_time
                print(f"  [{step:4d}] {current_label} | "
                      f"CPU={row['cpu_pct']}% err={row['error_rate']}% "
                      f"F={row['fatigue']} T={row['tension']} C={row['comfort']} "
                      f"| {row['plutchik']}")

            sleep_time = max(0, interval - (time.time() - (scenario_start - scenario_elapsed)))
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\n用户中断")

    elapsed = time.time() - start_time
    print(f"\n=== 注入完成 ===")
    print(f"运行 {elapsed:.0f}s | 注入 {step} 行")
    print(f"输出: {CSV_PATH}")

    # 统计各场景行数
    try:
        with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        total = len(rows)
        injected = [r for r in rows if r['step'].startswith('[INJ]')]
        real = [r for r in rows if not r['step'].startswith('[INJ]')]
        print(f"  真实数据: {len(real)} 行 | 注入数据: {len(injected)} 行 | 总计: {total}")
    except Exception:
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='V6.2 压力注入器')
    parser.add_argument('--scenario', nargs='+', default=['all'],
                        help='场景名: idle light_load moderate_load_io error_burst conn_storm overheat nightmare recovery all')
    parser.add_argument('--duration', type=int, default=600,
                        help='总运行时间（秒），默认 600')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='注入间隔（秒），默认 1.0')
    parser.add_argument('--list', action='store_true',
                        help='列出所有场景')
    args = parser.parse_args()

    if args.list:
        print("可用场景:")
        for name, sc in SCENARIOS.items():
            dur = sc['duration']
            cpu = sc['cpu_range']
            err = sc['error_rate']
            print(f"  {name:<20s} {sc['label']:<12s} {dur}s  CPU:{cpu}  ERR:{err}")
        sys.exit(0)

    run_injection(args.scenario, args.duration, args.interval)