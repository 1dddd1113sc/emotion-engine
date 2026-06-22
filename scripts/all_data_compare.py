#!/usr/bin/env python
"""真实数据对比：v6_live_data_v62.json + v6_live_data_stress.json"""
import sys, os, json, math, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collections import deque
from kalman_filter import ODEKalmanFilter


def load_real_data(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()
    try:
        return json.loads(raw.decode('utf-8'))
    except UnicodeDecodeError:
        return json.loads(raw.decode('gbk', errors='replace'))


def run_compare(data, skip=10):
    kf = ODEKalmanFilter()
    ema_res = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    ode_res = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    kf_res = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}

    for rec in data:
        pad = rec.get('pad', {})
        smooth = rec.get('smooth', {})
        ode = rec.get('ode', {})
        body = rec.get('body', {})

        rp = float(pad.get('p', 0))
        ra = float(pad.get('a', 0))
        rd = float(pad.get('d', 0))
        rv = float(pad.get('v', 0.05))

        sp = float(smooth.get('p', rp))
        sa = float(smooth.get('a', ra))
        sd = float(smooth.get('d', rd))
        sv = float(smooth.get('volatility', rv))

        op = float(ode.get('p', rp))
        oa = float(ode.get('a', ra))
        od = float(ode.get('d', rd))
        ov = float(ode.get('v', rv))

        t = float(body.get('tension', 0))
        f = float(body.get('fatigue', 0))
        c = float(body.get('comfort', 1))

        ko = kf.step((rp, ra, rd, rv), tension=t, fatigue=f, comfort=c)

        ema_res['p'].append(rp - sp)
        ema_res['a'].append(ra - sa)
        ema_res['d'].append(rd - sd)
        ema_res['v'].append(rv - sv)

        ode_res['p'].append(rp - op)
        ode_res['a'].append(ra - oa)
        ode_res['d'].append(rd - od)
        ode_res['v'].append(rv - ov)

        for j, d in enumerate(['p', 'a', 'd', 'v']):
            kf_res[d].append(float(ko.innovation[j]))

    return ema_res, ode_res, kf_res, kf.state.q_current


def stats(residuals, skip=10):
    r = {}
    for dim in ['p', 'a', 'd', 'v']:
        vals = list(residuals[dim])[skip:]
        if len(vals) < 5:
            r[dim] = {'mean': 0, 'lag1': 0, 'n': 0}
            continue
        n = len(vals)
        mean = sum(vals) / n
        vt = vals[:-1]
        vt1 = vals[1:]
        mt = sum(vt) / (n - 1)
        mt1 = sum(vt1) / (n - 1)
        num = sum((vt[i] - mt) * (vt1[i] - mt1) for i in range(n - 1))
        dt = sum((v - mt) ** 2 for v in vt)
        dt1 = sum((v - mt1) ** 2 for v in vt1)
        denom = max(math.sqrt(dt * dt1), 1e-10)
        r[dim] = {'mean': round(mean, 5), 'lag1': round(num / denom, 4), 'n': n}
    return r


def print_table(name, es, os_, ks, qf):
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    print(f"  {'dim':<6} {'EMA mean':>10} {'EMA lag1':>10} | {'ODE mean':>10} {'ODE lag1':>10} | {'KF mean':>10} {'KF lag1':>10}")
    print(f"  {'-' * 6} {'-' * 10} {'-' * 10} | {'-' * 10} {'-' * 10} | {'-' * 10} {'-' * 10}")
    for dim in ['p', 'a', 'd', 'v']:
        print(f"  {dim:<6} {es[dim]['mean']:>10.5f} {es[dim]['lag1']:>10.4f} | {os_[dim]['mean']:>10.5f} {os_[dim]['lag1']:>10.4f} | {ks[dim]['mean']:>10.5f} {ks[dim]['lag1']:>10.4f}")
    print(f"\n  Kalman Q: {qf:.6f}")
    for dim in ['a', 'p', 'd', 'v']:
        ol, kl = os_[dim]['lag1'], ks[dim]['lag1']
        d = ol - kl
        if d > 0.1:
            print(f"  ++ {dim}: ODE lag1 {ol:.4f} -> Kalman lag1 {kl:.4f} (delta {d:+.4f})")
        elif d < -0.1:
            print(f"  -- {dim}: ODE lag1 {ol:.4f} -> Kalman lag1 {kl:.4f} (delta {d:+.4f})")
        else:
            print(f"  ~~ {dim}: ODE lag1 {ol:.4f} -> Kalman lag1 {kl:.4f} (delta {d:+.4f})")


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))

    for fname in ['v6_live_data_v62.json', 'v6_live_data_stress.json']:
        fp = os.path.join(project_dir, fname)
        if not os.path.exists(fp):
            print(f"SKIP: {fp} not found")
            continue
        data = load_real_data(fp)
        print(f"\n{fname}: {len(data)} records")
        ema_res, ode_res, kf_res, qf = run_compare(data)
        es = stats(ema_res)
        os_ = stats(ode_res)
        ks = stats(kf_res)
        print_table(fname, es, os_, ks, qf)

    print(f"\n{'=' * 70}")
    print("  done")
    print(f"{'=' * 70}")