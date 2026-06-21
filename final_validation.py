"""最终验证：新架构优化参数 vs 旧架构"""
import os
import sys, io, csv, json

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from context_pad import compute_pad_context_aware
    from ema_filter import AdaptiveEMAFilter
    from quadrant_stabilizer import QuadrantStabilizer
    from pad_model import PADState, MetricsHistory, metrics_to_pad

    LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data.csv')
    GOOGLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/google_metrics_cache.json')
    G2011 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/google_2011.json')

    with open(LOCAL, encoding='utf-8-sig') as f:
        local = [(float(r['cpu_pct']), float(r['mem_pct'])) for r in csv.DictReader(f)]
    with open(GOOGLE) as f:
        google = [(d['cpu_percent'], d['mem_percent']) for d in json.load(f)[::5]]
    with open(G2011) as f:
        g2011 = json.load(f)

    def eval_new(data):
        ema = AdaptiveEMAFilter(alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20)
        # V6.2: hysteresis 已移除，改用上下文自适应参数
        stab = QuadrantStabilizer(deadzone_p=0.06, deadzone_a=0.06, deadzone_d=0.06,
                                   clean_dz=0.06, err_dz=0.04, clean_inertia=10, err_inertia=5)
        states = []
        for cpu, mem in data:
            err = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
            lat = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0
            pad = compute_pad_context_aware(cpu, mem, err, lat)
            smooth = ema.update(PADState(p=pad.p, a=pad.a, d=pad.d, volatility=pad.v))
            _, _, _, q, _ = stab.update(smooth.p, smooth.a, smooth.d)
            states.append(str(q))
        n = len(states)
        return sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

    def eval_old(data):
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
        return sum(1 for i in range(1, n) if states[i] != states[i-1]) / (n - 1)

    print("=" * 80)
    print("  Final Validation: New Architecture (optimized) vs Old")
    print("=" * 80)
    print(f"  {'Dataset':12s} {'Rows':>7s}  {'Old':>7s}  {'New':>7s}  {'Change':>8s}")
    print(f"  {'-'*12} {'-'*7}  {'-'*7}  {'-'*7}  {'-'*8}")

    total_old_w, total_new_w, total_rows = 0, 0, 0
    for name, data in [("Local", local), ("Google2019", google), ("Google2011", g2011), ("Combined", local+google+g2011)]:
        f_old = eval_old(data)
        f_new = eval_new(data)
        imp = (f_old - f_new) / max(f_old, 0.0001) * 100
        print(f"  {name:12s} {len(data):7d}  {f_old:6.2%}  {f_new:6.2%}  {imp:+7.0f}%")
        total_old_w += f_old * len(data)
        total_new_w += f_new * len(data)
        total_rows += len(data)

    w_old = total_old_w / total_rows
    w_new = total_new_w / total_rows
    imp = (w_old - w_new) / max(w_old, 0.0001) * 100
    print(f"  {'-'*12} {'-'*7}  {'-'*7}  {'-'*7}  {'-'*8}")
    print(f"  {'WEIGHTED':12s} {total_rows:7d}  {w_old:6.2%}  {w_new:6.2%}  {imp:+7.0f}%")
