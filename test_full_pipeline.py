"""新架构完整管线：语义信号 → 上下文PAD → EMA → Stabilizer → ODE"""
import sys, io, csv, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'D:\OpenClawData\.openclaw\workspace\emotion-engine')

from context_pad import compute_pad_context_aware, PADOutput
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer
from pad_model import PADState, MetricsHistory, metrics_to_pad

LOCAL = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\v6_live_data.csv'
GOOGLE = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\data\google_metrics_cache.json'

with open(LOCAL, encoding='utf-8-sig') as f:
    local = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]
with open(GOOGLE) as f:
    google = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]

def evaluate_new_pipeline(data, label):
    """新管线：context_pad → EMA → Stabilizer"""
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    stab = QuadrantStabilizer()
    states = []
    for cpu, mem in data:
        err = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        pad = compute_pad_context_aware(cpu, mem, err, lat)
        smooth = ema.update(PADState(p=pad.p, a=pad.a, d=pad.d, volatility=pad.v))
        _, _, _, q, _ = stab.update(smooth.p, smooth.a, smooth.d)
        states.append(str(q))
    n = len(states)
    flicker = sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)
    return flicker

def evaluate_old_pipeline(data, label):
    """旧管线：metrics_to_pad → EMA → Stabilizer"""
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    history = MetricsHistory(window_size=10)
    stab = QuadrantStabilizer()
    states = []
    for cpu, mem in data:
        err = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        history.update(cpu, err, lat)
        raw_pad = metrics_to_pad(cpu, mem, err, lat, history)
        smooth = ema.update(raw_pad)
        _, _, _, q, _ = stab.update(smooth.p, smooth.a, smooth.d)
        states.append(str(q))
    n = len(states)
    flicker = sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)
    return flicker

print("=== Full Pipeline Comparison ===")
print("  Old: metrics_to_pad -> EMA -> Stabilizer")
print("  New: context_pad -> EMA -> Stabilizer")
print()

for name, dataset in [("Local", local), ("Google", google), ("Combined", local + google)]:
    f_old = evaluate_old_pipeline(dataset, name)
    f_new = evaluate_new_pipeline(dataset, name)
    imp = (f_old - f_new) / max(f_old, 0.0001) * 100
    print(f"  {name:10s}: OLD={f_old:5.1%}  NEW={f_new:5.1%}  change={imp:+.0f}%")
