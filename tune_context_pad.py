"""新架构参数调优 — 本机 + Google 交叉验证"""
import os
import sys, io, csv, json, itertools
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from context_pad import PADOutput, compose_pad, extract_signals
from semantic_signals import SemanticSignals
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer
from pad_model import PADState

LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
GOOGLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/google_metrics_cache.json')

with open(LOCAL, encoding='utf-8-sig') as f:
    local = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]
with open(GOOGLE) as f:
    google = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]

def evaluate(data, p_base_k, p_base_b, a_base_k, stab_dz, stab_hyst, stab_inertia):
    """用指定参数评估闪烁率"""
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    # V6.2: hysteresis 已移除，改用上下文自适应参数
    stab = QuadrantStabilizer(deadzone_p=stab_dz, deadzone_a=stab_dz, deadzone_d=stab_dz,
                               clean_dz=stab_hyst, err_dz=stab_dz,
                               clean_inertia=stab_inertia * 2, err_inertia=stab_inertia)
    states = []
    for cpu, mem in data:
        err = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        sig = extract_signals(cpu, mem, err, lat)
        pad = compose_pad(sig)
        # 用可调基线覆盖
        pad.p = p_base_k * pad.p + p_base_b
        pad.a = a_base_k * pad.a
        smooth = ema.update(PADState(p=pad.p, a=pad.a, d=pad.d, volatility=pad.v))
        _, _, _, q, _ = stab.update(smooth.p, smooth.a, smooth.d)
        states.append(str(q))
    n = len(states)
    return sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

# 参数空间
grid = {
    'p_base_k': [0.8, 1.0, 1.2, 1.5],      # P 缩放系数
    'p_base_b': [0.0, 0.05, 0.10, 0.15],     # P 偏移
    'a_base_k': [0.8, 1.0, 1.2],              # A 缩放
    'stab_dz': [0.06, 0.08, 0.10],            # 稳定器死区
    'stab_hyst': [0.06, 0.08, 0.10],          # 稳定器滞回
    'stab_inertia': [4, 5],                    # 惯性窗口
}

keys = list(grid.keys())
combos = list(itertools.product(*[grid[k] for k in keys]))
print(f"Search: {len(combos)} combos x {len(local)+len(google)} rows")

results = []
best_wavg = 999
best_params = None

for idx, combo in enumerate(combos):
    params = dict(zip(keys, combo))
    fl = evaluate(local, **params)
    fg = evaluate(google, **params)
    wavg = (fl * len(local) + fg * len(google)) / (len(local) + len(google))
    results.append({**params, 'local': fl, 'google': fg, 'wavg': wavg})
    if wavg < best_wavg:
        best_wavg = wavg
        best_params = params
    if (idx + 1) % 100 == 0 or idx == len(combos) - 1:
        print(f"  [{idx+1}/{len(combos)}] best_wavg={best_wavg:.2%} local={best_params['local' if 'local' in best_params else 'p_base_k']:.2f}", flush=True)

results.sort(key=lambda x: x['wavg'])

print(f"\n{'='*100}")
print(f"{'#':>3s}  {'p_k':>4s} {'p_b':>4s} {'a_k':>4s} {'dz':>4s} {'hyst':>4s} {'in':>3s}  {'Local':>7s} {'Google':>7s} {'Weighted':>8s}")
print(f"{'---':>3s}  {'----':>4s} {'----':>4s} {'----':>4s} {'----':>4s} {'----':>4s} {'---':>3s}  {'-------':>7s} {'-------':>7s} {'--------':>8s}")

for i, r in enumerate(results[:15], 1):
    mk = " *" if i == 1 else "  "
    print(f"{i:3d}{mk} {r['p_base_k']:4.1f} {r['p_base_b']:4.2f} {r['a_base_k']:4.1f} {r['stab_dz']:4.2f} {r['stab_hyst']:4.2f} {r['stab_inertia']:3d}  "
          f"{r['local']:6.2%} {r['google']:6.2%} {r['wavg']:7.2%}")

best = results[0]
print(f"\nBEST: p_k={best['p_base_k']} p_b={best['p_base_b']} a_k={best['a_base_k']} dz={best['stab_dz']} hyst={best['stab_hyst']} inertia={best['stab_inertia']}")
print(f"  Local:    {best['local']:.2%}")
print(f"  Google:   {best['google']:.2%}")
print(f"  Weighted: {best['wavg']:.2%}")
