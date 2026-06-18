"""新架构验证：context_pad vs 旧 metrics_to_pad"""
import sys, io, csv, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'D:\OpenClawData\.openclaw\workspace\emotion-engine')

from semantic_signals import extract_signals
from context_pad import compute_pad_context_aware, compose_pad
from quadrant_stabilizer import QuadrantStabilizer

# 加载数据
LOCAL = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\v6_live_data.csv'
GOOGLE = r'D:\OpenClawData\.openclaw\workspace\emotion-engine\data\google_metrics_cache.json'

with open(LOCAL, encoding='utf-8-sig') as f:
    local = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]
with open(GOOGLE) as f:
    google = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]

def evaluate_new(data, label):
    stab = QuadrantStabilizer()
    states = []
    sigs = []
    for cpu, mem in data:
        err_proxy = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat_proxy = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
        pad = compute_pad_context_aware(cpu, mem, err_proxy, lat_proxy)
        _, _, _, q, _ = stab.update(pad.p, pad.a, pad.d)
        states.append(str(q))
        sigs.append(extract_signals(cpu, mem, err_proxy, lat_proxy))

    n = len(states)
    flicker = sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

    # 统计上下文分布
    ctx_counts = {}
    for s in sigs:
        ctx_counts[s.context] = ctx_counts.get(s.context, 0) + 1

    print(f"  {label:12s}: flicker={flicker:5.1%}  contexts={ctx_counts}")
    return flicker

# 旧架构（EMA + Stabilizer）
def evaluate_old(data, label):
    from pad_model import MetricsHistory, metrics_to_pad
    from ema_filter import AdaptiveEMAFilter
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
    print(f"  {label:12s}: flicker={flicker:5.1%}  (old: EMA + Stabilizer)")
    return flicker

print("=== Architecture Comparison ===\n")

for name, dataset in [("Local", local), ("Google", google)]:
    f_old = evaluate_old(dataset, f"{name} OLD")
    f_new = evaluate_new(dataset, f"{name} NEW")
    imp = (f_old - f_new) / max(f_old, 0.0001) * 100
    print(f"  -> Improvement: {f_old:.1%} -> {f_new:.1%} ({imp:+.0f}%)")
    print()

# 示例：展示上下文感知效果
print("\n=== Context-Aware Examples ===\n")
examples = [
    ("空闲健康", 15, 40, 0, 50),
    ("忙碌健康", 70, 55, 0, 200),
    ("忙碌出错", 70, 55, 15, 800),
    ("空闲出错", 15, 40, 15, 800),
    ("过载", 95, 90, 25, 2000),
]
for name, cpu, mem, err, lat in examples:
    sig = extract_signals(cpu, mem, err, lat)
    pad = compute_pad_context_aware(cpu, mem, err, lat)
    print(f"  {name:8s}: {sig} -> P={pad.p:+.3f} A={pad.a:+.3f} D={pad.d:+.3f}")
