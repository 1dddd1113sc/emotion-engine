"""EMA 训练 — 用本机实时采集数据"""
import os
import sys, io, csv, json, time, itertools
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pad_model import MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig
from ema_filter import AdaptiveEMAFilter

# 加载本机实时数据
CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
with open(CSV, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

data = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in rows]
print(f"Data: {len(data)} rows from local machine (real-time)")
cpus = [d[0] for d in data]
mems = [d[1] for d in data]
print(f"CPU: min={min(cpus):.1f} max={max(cpus):.1f} avg={sum(cpus)/len(cpus):.1f}")
print(f"MEM: min={min(mems):.1f} max={max(mems):.1f} avg={sum(mems)/len(mems):.1f}")

PARAM_GRID = {
    "alpha_slow": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
    "alpha_fast": [0.50, 0.60, 0.70, 0.80, 0.85, 0.90],
    "beta":       [3.0, 5.0, 8.0, 12.0],
    "inertia":    [0.10, 0.20, 0.30, 0.40, 0.50],
}

def run_eval(data, params):
    ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)
    ode = ODEDynamics(ode_cfg)
    ema = AdaptiveEMAFilter(**params)
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
    if n < 2:
        return {"flicker_rate": 1.0, "response_latency": 999, "stability": 0.0, "score": 0.0}
    flicker = sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)
    resp_list = []
    for i in range(1, n - 10):
        if data[i][0] - data[i-1][0] > 30:
            base = states[i-1]
            for j in range(i, min(i+15, n)):
                if states[j] != base:
                    resp_list.append(j - i); break
            else:
                resp_list.append(15)
    resp = sum(resp_list) / len(resp_list) if resp_list else 5.0
    high = [states[i] for i in range(n) if data[i][0] > 70]
    stab = high.count(max(set(high), key=high.count)) / len(high) if high else 1.0
    score = max(0, 1 - flicker/0.3)*40 + max(0, 1 - resp/10)*30 + stab*30
    return {"flicker_rate": round(flicker, 4), "response_latency": round(resp, 2),
            "stability": round(stab, 4), "score": round(score, 2)}

keys = list(PARAM_GRID.keys())
combos = list(itertools.product(*[PARAM_GRID[k] for k in keys]))
print(f"\nGrid search: {len(combos)} combos x {len(data)} rows")

results = []
best_score = -1
best_params = None
start = time.time()

for idx, combo in enumerate(combos):
    params = dict(zip(keys, combo))
    m = run_eval(data, params)
    results.append({**params, **m})
    if m["score"] > best_score:
        best_score = m["score"]
        best_params = params
    if (idx + 1) % 50 == 0 or idx == len(combos) - 1:
        e = time.time() - start
        eta = e / (idx+1) * (len(combos) - idx - 1)
        print(f"  [{idx+1:4d}/{len(combos)}] best={best_score:.1f} ({best_params}) {e:.0f}s {eta:.0f}s left", flush=True)

results.sort(key=lambda x: -x["score"])
best = results[0]

print(f"\n{'='*80}")
print(f"  EMA Results — Local Real-time Data ({len(data)} rows)")
print(f"{'='*80}")
print(f"  {'#':>3s}  {'a_slow':>6s} {'a_fast':>6s} {'beta':>5s} {'inert':>5s}  {'flick':>6s} {'resp':>5s} {'stab':>6s} {'score':>5s}")
for i, r in enumerate(results[:15], 1):
    mk = " *" if i == 1 else "  "
    print(f"  {i:3d}{mk} {r['alpha_slow']:6.2f} {r['alpha_fast']:6.2f} {r['beta']:5.1f} {r['inertia']:5.2f}  {r['flicker_rate']:5.1%}  {r['response_latency']:4.1f}  {r['stability']:5.1%}  {r['score']:5.1f}")

print(f"\n  Sensitivity:")
for p in keys:
    g = {}
    for r in results:
        g.setdefault(r[p], []).append(r["score"])
    avg = {v: sum(s)/len(s) for v, s in g.items()}
    print(f"    {p:12s}: best={max(avg, key=avg.get):.2f} worst={min(avg, key=avg.get):.2f} spread={max(avg.values())-min(avg.values()):.1f}")

print(f"\n  BEST: alpha_slow={best['alpha_slow']} alpha_fast={best['alpha_fast']} beta={best['beta']} inertia={best['inertia']}")
print(f"        flicker={best['flicker_rate']:.1%} resp={best['response_latency']:.1f} stab={best['stability']:.1%} score={best['score']:.1f}")
