"""全量本机实时数据 — Stabilizer 参数调优"""
import os
import sys, io, csv, json, itertools
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pad_model import MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
with open(CSV, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

data = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in rows]

cpus = [d[0] for d in data]
print(f"Local real-time data: {len(data)} rows")
print(f"CPU: min={min(cpus):.1f}% max={max(cpus):.1f}% avg={sum(cpus)/len(cpus):.1f}% stdev={(sum((x-sum(cpus)/len(cpus))**2 for x in cpus)/len(cpus))**0.5:.1f}%")
print(f"MEM: avg={sum(d[1] for d in data)/len(data):.1f}%")

def evaluate(data, dz, hyst, inertia):
    ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    history = MetricsHistory(window_size=10)
    # V6.2: hysteresis 已移除，改用上下文自适应参数
    stab = QuadrantStabilizer(
        deadzone_p=dz, deadzone_a=dz, deadzone_d=dz,
        clean_dz=hyst, err_dz=dz,
        clean_inertia=inertia * 2, err_inertia=inertia,
    )
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

# Baseline (no stabilizer)
def evaluate_baseline(data):
    ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    history = MetricsHistory(window_size=10)
    states = []
    for cpu, mem in data:
        err = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        history.update(cpu, err, lat)
        raw_pad = metrics_to_pad(cpu, mem, err, lat, history)
        smooth = ema.update(raw_pad)
        states.append(smooth.quadrant.value)
    n = len(states)
    flicker = sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)
    return flicker

baseline = evaluate_baseline(data)
print(f"\nBaseline (EMA only): flicker={baseline:.2%}")

# 参数搜索
grid = {
    'dz': [0.02, 0.04, 0.06, 0.08, 0.10, 0.12],
    'hyst': [0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
    'inertia': [2, 3, 4, 5],
}

combos = list(itertools.product(grid['dz'], grid['hyst'], grid['inertia']))
print(f"\nParameter search: {len(combos)} combos")

results = []
for i, (dz, hyst, inertia) in enumerate(combos):
    f = evaluate(data, dz, hyst, inertia)
    results.append({'dz': dz, 'hyst': hyst, 'inertia': inertia, 'flicker': f})
    if (i + 1) % 50 == 0 or i == len(combos) - 1:
        best = min(results, key=lambda x: x['flicker'])
        print(f"  [{i+1:3d}/{len(combos)}] best={best['flicker']:.2%} (dz={best['dz']} hyst={best['hyst']} inertia={best['inertia']})", flush=True)

results.sort(key=lambda x: x['flicker'])

print(f"\n{'='*70}")
print(f"  Stabilizer Parameter Tuning — {len(data)} rows local data")
print(f"{'='*70}")
print(f"  Baseline (EMA only): {baseline:.2%}")
print(f"")
print(f"  {'#':>3s}  {'dz':>5s}  {'hyst':>5s}  {'inertia':>7s}  {'flicker':>8s}  {'vs baseline':>12s}")
print(f"  {'---':>3s}  {'-----':>5s}  {'-----':>5s}  {'-------':>7s}  {'--------':>8s}  {'------------':>12s}")

for i, r in enumerate(results[:20], 1):
    imp = (baseline - r['flicker']) / max(baseline, 0.0001) * 100
    mk = " *" if i == 1 else "  "
    print(f"  {i:3d}{mk} {r['dz']:5.2f}  {r['hyst']:5.2f}  {r['inertia']:7d}  {r['flicker']:7.2%}  {imp:+11.0f}%")

best = results[0]
print(f"\n  BEST: dz={best['dz']} hyst={best['hyst']} inertia={best['inertia']} flicker={best['flicker']:.2%}")
