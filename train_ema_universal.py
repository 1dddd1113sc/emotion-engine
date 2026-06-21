"""EMA 通用参数训练 — 合并本机 + Google 数据"""
import os
import sys, io, csv, json, time, itertools
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pad_model import MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig
from ema_filter import AdaptiveEMAFilter

# 1. 本机数据
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
with open(LOCAL, encoding='utf-8-sig') as f:
    local_rows = list(csv.DictReader(f))
local_data = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in local_rows]

# 2. Google 数据（抽样）
GOOGLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/google_metrics_cache.json')
with open(GOOGLE) as f:
    google_raw = json.load(f)
google_data = [(d['cpu_percent'], d['mem_percent']) for d in google_raw[::10]]  # 5000条

# 3. 模拟极端场景（补足 Google 没覆盖的边界）
import random
rng = random.Random(42)
extreme_data = []
for _ in range(2000):
    scenario = rng.choice(['idle', 'burst', 'leak', 'recovery', 'sustained'])
    if scenario == 'idle':
        extreme_data.append((rng.gauss(8, 3), rng.gauss(30, 5)))
    elif scenario == 'burst':
        extreme_data.append((rng.gauss(85, 10), rng.gauss(60, 10)))
    elif scenario == 'leak':
        t = rng.random()
        extreme_data.append((rng.gauss(30, 5), rng.gauss(40 + 50*t, 5)))
    elif scenario == 'recovery':
        t = rng.random()
        extreme_data.append((rng.gauss(90 - 80*t, 8), rng.gauss(70 - 30*t, 5)))
    else:
        extreme_data.append((rng.gauss(70, 8), rng.gauss(65, 8)))
    extreme_data[-1] = (max(0, min(100, extreme_data[-1][0])), max(0, min(100, extreme_data[-1][1])))

# 合并
data = local_data + google_data + extreme_data
random.shuffle(data)

print(f"=== Merged Dataset ===")
print(f"  Local:   {len(local_data)} rows (CPU avg={sum(d[0] for d in local_data)/len(local_data):.1f}%)")
print(f"  Google:  {len(google_data)} rows (CPU avg={sum(d[0] for d in google_data)/len(google_data):.1f}%)")
print(f"  Extreme: {len(extreme_data)} rows")
print(f"  Total:   {len(data)} rows")
cpus = [d[0] for d in data]
print(f"  CPU range: {min(cpus):.1f} ~ {max(cpus):.1f}, avg={sum(cpus)/len(cpus):.1f}")

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
        print(f"  [{idx+1:4d}/{len(combos)}] best={best_score:.1f} {e:.0f}s {eta:.0f}s left", flush=True)

results.sort(key=lambda x: -x["score"])
best = results[0]

print(f"\n{'='*90}")
print(f"  EMA Universal Results — Merged Data ({len(data)} rows)")
print(f"{'='*90}")
print(f"  {'#':>3s}  {'a_slow':>6s} {'a_fast':>6s} {'beta':>5s} {'inert':>5s}  {'flick':>6s} {'resp':>5s} {'stab':>6s} {'score':>5s}")
for i, r in enumerate(results[:20], 1):
    mk = " *" if i == 1 else "  "
    print(f"  {i:3d}{mk} {r['alpha_slow']:6.2f} {r['alpha_fast']:6.2f} {r['beta']:5.1f} {r['inertia']:5.2f}  {r['flicker_rate']:5.1%}  {r['response_latency']:4.1f}  {r['stability']:5.1%}  {r['score']:5.1f}")

# 用最优参数分别在三个数据集上评估
print(f"\n{'='*90}")
print(f"  Cross-validation: Best params on each dataset")
print(f"{'='*90}")
best_p = {k: best[k] for k in keys}
for name, subset in [("Local", local_data), ("Google", google_data), ("Extreme", extreme_data), ("Merged", data)]:
    m = run_eval(subset, best_p)
    print(f"  {name:10s}: flicker={m['flicker_rate']:5.1%} resp={m['response_latency']:4.1f} stab={m['stability']:5.1%} score={m['score']:5.1f}")

print(f"\n{'='*90}")
print(f"  UNIVERSAL EMA PARAMS")
print(f"{'='*90}")
print(f"  alpha_slow = {best['alpha_slow']}")
print(f"  alpha_fast = {best['alpha_fast']}")
print(f"  beta       = {best['beta']}")
print(f"  inertia    = {best['inertia']}")
print(f"  flicker    = {best['flicker_rate']:.1%}")
print(f"  response   = {best['response_latency']:.1f}")
print(f"  stability  = {best['stability']:.1%}")
print(f"  score      = {best['score']:.1f}/100")
