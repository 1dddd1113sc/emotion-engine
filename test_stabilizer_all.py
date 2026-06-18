"""全量真实数据 Stabilizer 效果验证"""
import sys, io, csv, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'D:\OpenClawData\.openclaw\workspace\emotion-engine')

from pad_model import MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig
from ema_filter import AdaptiveEMAFilter
from quadrant_stabilizer import QuadrantStabilizer

DATA_DIR = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\data'

# 加载全部真实数据
datasets = {}

# 本机实时
with open(r'D:\OpenClawData\.openclaw\workspace\emotion-engine\v6_live_data.csv', encoding='utf-8-sig') as f:
    datasets['Local'] = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]

# Google 2019
with open(f'{DATA_DIR}/google_metrics_cache.json') as f:
    datasets['Google2019'] = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]

# Google 2011
with open(f'{DATA_DIR}/google_2011.json') as f:
    datasets['Google2011'] = json.load(f)

def evaluate(data, use_stab=False):
    ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)
    ode = ODEDynamics(ode_cfg)
    ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
    history = MetricsHistory(window_size=10)
    stab = QuadrantStabilizer() if use_stab else None
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
    return flicker, stab_score

print(f"{'Dataset':15s} {'rows':>7s}  {'EMA only':>22s}  {'+ Stabilizer':>22s}  {'Improvement':>15s}")
print(f"{'':15s} {'':>7s}  {'flicker':>10s} {'score':>10s}  {'flicker':>10s} {'score':>10s}  {'flicker':>10s}")

total_f1, total_f2 = 0, 0
total_rows = 0

for name, data in datasets.items():
    f1, s1 = evaluate(data, use_stab=False)
    f2, s2 = evaluate(data, use_stab=True)
    
    sc1 = max(0, 1-f1/0.3)*40 + 30 + s1*30
    sc2 = max(0, 1-f2/0.3)*40 + 30 + s2*30
    
    imp = (f1 - f2) / max(f1, 0.001) * 100
    print(f"{name:15s} {len(data):7d}  {f1:10.1%} {sc1:10.1f}  {f2:10.1%} {sc2:10.1f}  {imp:+10.0f}%")
    
    total_f1 += f1 * len(data)
    total_f2 += f2 * len(data)
    total_rows += len(data)

# 加权平均
wf1 = total_f1 / total_rows
wf2 = total_f2 / total_rows
imp = (wf1 - wf2) / max(wf1, 0.001) * 100
sc1 = max(0, 1-wf1/0.3)*40 + 30 + 70*0.3
sc2 = max(0, 1-wf2/0.3)*40 + 30 + 70*0.3
print(f"{'WEIGHTED AVG':15s} {total_rows:7d}  {wf1:10.1%} {sc1:10.1f}  {wf2:10.1%} {sc2:10.1f}  {imp:+10.0f}%")
