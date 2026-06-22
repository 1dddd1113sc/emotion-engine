import sys, os, json, math, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collections import deque
from kalman_filter import ODEKalmanFilter

def load_real_data(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('gbk', errors='replace')
    return json.loads(text)

def run_compare(data, skip=10):
    kf = ODEKalmanFilter()
    ema_res = {d: deque(maxlen=len(data)) for d in ['p','a','d','v']}
    ode_res = {d: deque(maxlen=len(data)) for d in ['p','a','d','v']}
    kf_res = {d: deque(maxlen=len(data)) for d in ['p','a','d','v']}
    
    for rec in data:
        pad = rec.get('pad', {})
        smooth = rec.get('smooth', {})
        ode = rec.get('ode', {})
        body = rec.get('body', {})
        
        rp, ra, rd, rv = float(pad.get('p',0)), float(pad.get('a',0)), float(pad.get('d',0)), float(pad.get('v',0.05))
        sp, sa, sd, sv = float(smooth.get('p',rp)), float(smooth.get('a',ra)), float(smooth.get('d',rd)), float(smooth.get('volatility',rv))
        op, oa, od, ov = float(ode.get('p',rp)), float(ode.get('a',ra)), float(ode.get('d',rd)), float(ode.get('v',rv))
        t, f, c = float(body.get('tension',0)), float(body.get('fatigue',0)), float(body.get('comfort',1))
        
        ko = kf.step((rp, ra, rd, rv), tension=t, fatigue=f, comfort=c)
        
        ema_res['p'].append(rp-sp); ema_res['a'].append(ra-sa); ema_res['d'].append(rd-sd); ema_res['v'].append(rv-sv)
        ode_res['p'].append(rp-op); ode_res['a'].append(ra-oa); ode_res['d'].append(rd-od); ode_res['v'].append(rv-ov)
        for j, d in enumerate(['p','a','d','v']):
            kf_res[d].append(float(ko.innovation[j]))
    
    return ema_res, ode_res, kf_res, kf.state.q_current

def stats(residuals, skip=10):
    r = {}
    for dim in ['p','a','d','v']:
        vals = list(residuals[dim])[skip:]
        if len(vals) < 5:
            r[dim] = {'mean':0,'lag1':0,'n':0}
            continue
        n = len(vals)
        mean = sum(vals)/n
        vt = vals[:-1]; vt1 = vals[1:]
        mt = sum(vt)/(n-1); mt1 = sum(vt1)/(n-1)
        num = sum((vt[i]-mt)*(vt1[i]-mt1) for i in range(n-1))
        dt = sum((v-mt)**2 for v in vt); dt1 = sum((v-mt1)**2 for v in vt1)
        denom = max(math.sqrt(dt*dt1), 1e-10)
        r[dim] = {'mean': round(mean,5), 'lag1': round(num/denom,4), 'n': n}
    return r

data = load_real_data('v6_live_data_stress.json')
print(f'stress data: {len(data)} records')
ema_res, ode_res, kf_res, qf = run_compare(data)
es = stats(ema_res); os_ = stats(ode_res); ks = stats(kf_res)

print(f"\n{'='*70}")
print(f"  stress data residuals")
print(f"{'='*70}")
print(f"  {'dim':<6} {'EMA mean':>10} {'EMA lag1':>10} | {'ODE mean':>10} {'ODE lag1':>10} | {'Kalman mean':>10} {'Kalman lag1':>10}")
print(f"  {'-'*6} {'-'*10} {'-'*10} | {'-'*10} {'-'*10} | {'-'*10} {'-'*10}")
for dim in ['p','a','d','v']:
    print(f"  {dim:<6} {es[dim]['mean']:>10.5f} {es[dim]['lag1']:>10.4f} | {os_[dim]['mean']:>10.5f} {os_[dim]['lag1']:>10.4f} | {ks[dim]['mean']:>10.5f} {ks[dim]['lag1']:>10.4f}")

print(f"\nQ: {qf:.6f}")
for dim in ['a','p','d','v']:
    ol, kl = os_[dim]['lag1'], ks[dim]['lag1']
    d = ol - kl
    tag = '+++' if d > 0.1 else ('---' if d < -0.1 else '~~~')
    print(f"  {tag} {dim}: ODE {ol:.4f} -> Kalman {kl:.4f} (delta {d:+.4f})")
