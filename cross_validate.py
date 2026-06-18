"""交叉验证：同一参数在两个数据集上的表现"""
import sys, io, csv, json, itertools
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'D:\OpenClawData\.openclaw\workspace\emotion-engine')

from pad_model import MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer

# 加载两个数据集
LOCAL = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\v6_live_data.csv'
GOOGLE = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\data\google_metrics_cache.json'

with open(LOCAL, encoding='utf-8-sig') as f:
    local = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]
with open(GOOGLE) as f:
    google = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]

def evaluate(data, dz, hyst, inertia):
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    history = MetricsHistory(window_size=10)
    stab = QuadrantStabilizer(deadzone_p=dz, deadzone_a=dz, deadzone_d=dz,
                               hysteresis=hyst, inertia_window=inertia)
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
    return sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

def baseline(data):
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
    return sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

bl_local = baseline(local)
bl_google = baseline(google)

print(f"Baseline:  Local={bl_local:.2%}  Google={bl_google:.2%}")

# 搜参数，优化两个数据集的加权平均
grid = {
    'dz': [0.02, 0.04, 0.06, 0.08, 0.10],
    'hyst': [0.06, 0.08, 0.10, 0.12],
    'inertia': [3, 4, 5],
}

combos = list(itertools.product(grid['dz'], grid['hyst'], grid['inertia']))
print(f"Search: {len(combos)} combos\n")

results = []
for dz, hyst, inertia in combos:
    fl = evaluate(local, dz, hyst, inertia)
    fg = evaluate(google, dz, hyst, inertia)
    # 加权：Google 数据量是本机的 2 倍
    wavg = (fl * len(local) + fg * len(google)) / (len(local) + len(google))
    results.append({'dz': dz, 'hyst': hyst, 'inertia': inertia,
                    'local': fl, 'google': fg, 'wavg': wavg})

results.sort(key=lambda x: x['wavg'])

print(f"{'#':>3s}  {'dz':>4s} {'hyst':>5s} {'inert':>5s}  {'Local':>8s} {'Google':>8s} {'Weighted':>8s}  {'Local imp':>9s} {'Google imp':>10s}")
print(f"{'---':>3s}  {'----':>4s} {'-----':>5s} {'-----':>5s}  {'--------':>8s} {'--------':>8s} {'--------':>8s}  {'---------':>9s} {'----------':>10s}")

for i, r in enumerate(results[:15], 1):
    li = (bl_local - r['local']) / max(bl_local, 0.0001) * 100
    gi = (bl_google - r['google']) / max(bl_google, 0.0001) * 100
    mk = " *" if i == 1 else "  "
    print(f"{i:3d}{mk} {r['dz']:4.2f} {r['hyst']:5.2f} {r['inertia']:5d}  {r['local']:7.2%} {r['google']:7.2%} {r['wavg']:7.2%}  {li:+8.0f}% {gi:+9.0f}%")

best = results[0]
print(f"\nBEST UNIVERSAL: dz={best['dz']} hyst={best['hyst']} inertia={best['inertia']}")
print(f"  Local:  {bl_local:.2%} -> {best['local']:.2%} ({(bl_local-best['local'])/max(bl_local,0.0001)*100:+.0f}%)")
print(f"  Google: {bl_google:.2%} -> {best['google']:.2%} ({(bl_google-best['google'])/max(bl_google,0.0001)*100:+.0f}%)")
print(f"  Weighted avg: {best['wavg']:.2%}")
