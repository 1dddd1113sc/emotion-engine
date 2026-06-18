"""EMA 完整训练 — 用本地缓存的 Google 真实数据"""
import sys, io, json, time, itertools, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'D:\OpenClawData\.openclaw\workspace\emotion-engine')

from pad_model import PADState, MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from ema_filter import AdaptiveEMAFilter

# 加载真实数据
CACHE = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\data\google_metrics_cache.json'
with open(CACHE) as f:
    raw = json.load(f)

# 提取 (cpu, mem) 序列，每隔 N 行抽样加速
STEP = 1  # 全量50000条
data = [(d['cpu_percent'], d['mem_percent']) for d in raw[::STEP]]
print(f"Data: {len(data)} rows from Google Cluster Data 2019")
print(f"CPU: min={min(d[0] for d in data):.1f} max={max(d[0] for d in data):.1f} avg={sum(d[0] for d in data)/len(data):.1f}")
print(f"MEM: min={min(d[1] for d in data):.1f} max={max(d[1] for d in data):.1f} avg={sum(d[1] for d in data)/len(data):.1f}")

# 完整参数空间
PARAM_GRID = {
    "alpha_slow": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
    "alpha_fast": [0.50, 0.60, 0.70, 0.80, 0.85, 0.90],
    "beta":       [3.0, 5.0, 8.0, 12.0],
    "inertia":    [0.10, 0.20, 0.30, 0.40, 0.50],
}

def run_eval(data, params, ode_cfg=None):
    if ode_cfg is None:
        ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)
    
    ode = ODEDynamics(ode_cfg)
    ema = AdaptiveEMAFilter(
        alpha_slow=params["alpha_slow"],
        alpha_fast=params["alpha_fast"],
        beta=params["beta"],
        inertia=params["inertia"],
    )
    history = MetricsHistory(window_size=10)
    
    states = []
    for cpu, mem in data:
        err_proxy = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat_proxy = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        history.update(cpu, err_proxy, lat_proxy)
        raw_pad = metrics_to_pad(cpu, mem, err_proxy, lat_proxy, history)
        smooth = ema.update(raw_pad)
        states.append(smooth.quadrant.value)
    
    n = len(states)
    if n < 2:
        return {"flicker_rate": 1.0, "response_latency": 999, "stability": 0.0, "score": 0.0}
    
    flicker_count = sum(1 for i in range(1, n) if states[i] != states[i-1])
    flicker_rate = flicker_count / (n - 1)
    
    response_latencies = []
    for i in range(1, n - 10):
        if data[i][0] - data[i-1][0] > 30:
            baseline = states[i-1]
            for j in range(i, min(i + 15, n)):
                if states[j] != baseline:
                    response_latencies.append(j - i)
                    break
            else:
                response_latencies.append(15)
    avg_response = sum(response_latencies) / len(response_latencies) if response_latencies else 5.0
    
    high_load = [states[i] for i in range(n) if data[i][0] > 70]
    if high_load:
        most_common = max(set(high_load), key=high_load.count)
        stability = high_load.count(most_common) / len(high_load)
    else:
        stability = 1.0
    
    flicker_score = max(0, 1.0 - flicker_rate / 0.3) * 40
    response_score = max(0, 1.0 - avg_response / 10) * 30
    stability_score = stability * 30
    score = flicker_score + response_score + stability_score
    
    return {
        "flicker_rate": round(flicker_rate, 4),
        "response_latency": round(avg_response, 2),
        "stability": round(stability, 4),
        "score": round(score, 2),
    }

# 网格搜索
keys = list(PARAM_GRID.keys())
combos = list(itertools.product(*[PARAM_GRID[k] for k in keys]))
total = len(combos)

print(f"\nGrid search: {total} combos x {len(data)} data points")
print(f"Estimated time: ~{total * len(data) / 50000:.0f}s\n")

results = []
best_score = -1
best_params = None
start = time.time()

for idx, combo in enumerate(combos):
    params = dict(zip(keys, combo))
    metrics = run_eval(data, params)
    result = {**params, **metrics}
    results.append(result)
    
    if metrics["score"] > best_score:
        best_score = metrics["score"]
        best_params = params
    
    if (idx + 1) % 50 == 0 or idx == total - 1:
        elapsed = time.time() - start
        eta = elapsed / (idx + 1) * (total - idx - 1)
        print(f"  [{idx+1:4d}/{total}] best={best_score:.1f} "
              f"({best_params['alpha_slow']}/{best_params['alpha_fast']}/"
              f"{best_params['beta']}/{best_params['inertia']}) "
              f"{elapsed:.0f}s elapsed {eta:.0f}s left", flush=True)

elapsed = time.time() - start
print(f"\nDone: {elapsed:.1f}s")

# 排序
results.sort(key=lambda x: -x["score"])

# 打印 Top 15
print(f"\n{'='*90}")
print(f"  EMA Training Results Top-15 (Google Cluster Data {len(data)} rows)")
print(f"{'='*90}")
print(f"  {'#':>3s}  {'a_slow':>7s} {'a_fast':>7s} {'beta':>5s} {'inertia':>7s}"
      f"  {'flicker':>7s} {'resp':>6s} {'stable':>7s} {'score':>6s}")
print(f"  {'---':>3s}  {'-------':>7s} {'-------':>7s} {'-----':>5s} {'-------':>7s}"
      f"  {'-------':>7s} {'------':>6s} {'-------':>7s} {'------':>6s}")

for rank, r in enumerate(results[:15], 1):
    marker = " *" if rank == 1 else "  "
    print(f"  {rank:3d}{marker} "
          f"{r['alpha_slow']:7.2f} {r['alpha_fast']:7.2f} {r['beta']:5.1f} {r['inertia']:7.2f}"
          f"  {r['flicker_rate']:6.1%}  {r['response_latency']:5.1f}  "
          f"{r['stability']:6.1%}  {r['score']:5.1f}")

# 参数敏感度
print(f"\n{'='*90}")
print(f"  Parameter Sensitivity")
print(f"{'='*90}")
for param in keys:
    groups = {}
    for r in results:
        v = r[param]
        if v not in groups:
            groups[v] = []
        groups[v].append(r["score"])
    avg = {v: sum(s)/len(s) for v, s in groups.items()}
    best = max(avg, key=avg.get)
    worst = min(avg, key=avg.get)
    print(f"  {param:12s}: best={best:.2f} (avg={avg[best]:.1f}) worst={worst:.2f} (avg={avg[worst]:.1f}) spread={avg[best]-avg[worst]:.1f}")

# 保存
best = results[0]
output = {
    "data_source": "Google Cluster Data 2019",
    "data_rows": len(data),
    "total_combos": total,
    "best_params": {k: best[k] for k in keys},
    "best_metrics": {k: best[k] for k in ["flicker_rate", "response_latency", "stability", "score"]},
    "top_15": results[:15],
}
out_path = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\ema_train_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nSaved: {out_path}")

print(f"\n{'='*90}")
print(f"  BEST EMA PARAMS")
print(f"{'='*90}")
print(f"  alpha_slow = {best['alpha_slow']}")
print(f"  alpha_fast = {best['alpha_fast']}")
print(f"  beta       = {best['beta']}")
print(f"  inertia    = {best['inertia']}")
print(f"  flicker    = {best['flicker_rate']:.1%}")
print(f"  response   = {best['response_latency']:.1f}")
print(f"  stability  = {best['stability']:.1%}")
print(f"  score      = {best['score']:.1f}/100")
