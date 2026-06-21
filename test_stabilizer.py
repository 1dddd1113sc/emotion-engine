"""防闪烁效果对比：原始 vs QuadrantStabilizer"""
import os
import sys, io, csv, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pad_model import MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer

# 加载数据
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
GOOGLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/google_metrics_cache.json')

with open(LOCAL, encoding='utf-8-sig') as f:
    local = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]
with open(GOOGLE) as f:
    google = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]

def evaluate(data, label, use_stabilizer=False):
    ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)
    ode = ODEDynamics(ode_cfg)
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    history = MetricsHistory(window_size=10)
    stab = QuadrantStabilizer() if use_stabilizer else None

    states = []
    for cpu, mem in data:
        err = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        history.update(cpu, err, lat)
        raw_pad = metrics_to_pad(cpu, mem, err, lat, history)
        smooth = ema.update(raw_pad)

        if stab:
            _, _, _, q, _ = stab.update(smooth.p, smooth.a, smooth.d)
            states.append(str(q))
        else:
            states.append(smooth.quadrant.value)

    n = len(states)
    flicker = sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

    high = [states[i] for i in range(n) if data[i][0] > 70]
    stab_score = high.count(max(set(high), key=high.count)) / len(high) if high else 1.0

    flicker_score = max(0, 1 - flicker/0.3) * 40
    stab_val = stab_score * 30
    score = flicker_score + 30 + stab_val  # resp=0 for both

    tag = "+ Stabilizer" if use_stabilizer else "EMA only"
    print(f"  {label:12s} ({tag:14s}): flicker={flicker:5.1%}  stab={stab_score:5.1%}  score={score:5.1f}")
    return flicker, stab_score, score

print("=== Flicker Rate Comparison ===\n")

for label, dataset in [("Local", local), ("Google", google), ("Combined", local + google)]:
    f1, s1, sc1 = evaluate(dataset, label, use_stabilizer=False)
    f2, s2, sc2 = evaluate(dataset, label, use_stabilizer=True)
    print(f"  -> Improvement: flicker {f1:.1%} -> {f2:.1%} ({(f1-f2)/max(f1,0.001)*100:+.0f}%), score {sc1:.1f} -> {sc2:.1f}")
    print()
