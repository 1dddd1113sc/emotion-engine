"""
真实采集 CSV 数据：ODE vs Kalman 残差对比

在 date/ 目录的 p0_live_data CSV 上运行 Kalman，
比较 ODE 残差(target - state)和 Kalman innovation。

用法:
    PYTHONPATH=. python tests/test_kalman_vs_ode_csv.py
"""
import sys, os, csv, math, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collections import deque
from kalman_filter import ODEKalmanFilter


def run_on_csv(filepath: str) -> tuple:
    """在 CSV 数据上运行 Kalman，返回 ODE 残差和 Kalman innovation"""
    kf = ODEKalmanFilter()
    ode_res = {d: deque() for d in ['p', 'a', 'd']}
    kf_res = {d: deque() for d in ['p', 'a', 'd']}
    targets = {d: deque() for d in ['p', 'a', 'd']}

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                tp = float(row['target_p'])
                ta = float(row['target_a'])
                td = float(row['target_d'])
                op = float(row['p'])
                oa = float(row['a'])
                od = float(row['d'])
                ov = float(row['v'])
                tn = float(row['tension'])
                fat = float(row['fatigue'])
                com = float(row['comfort'])
            except (KeyError, ValueError):
                continue

            ko = kf.step((tp, ta, td, ov), tension=tn, fatigue=fat, comfort=com)

            ode_res['p'].append(tp - op)
            ode_res['a'].append(ta - oa)
            ode_res['d'].append(td - od)

            kf_res['p'].append(float(ko.innovation[0]))
            kf_res['a'].append(float(ko.innovation[1]))
            kf_res['d'].append(float(ko.innovation[2]))

            targets['p'].append(tp)
            targets['a'].append(ta)
            targets['d'].append(td)

    return ode_res, kf_res, targets, kf.state.q_current


def compute_stats(vals: deque, skip: int = 100) -> tuple:
    """返回 (mean, lag1, variance, n)"""
    v = list(vals)[skip:]
    n = len(v)
    if n < 5:
        return 0.0, 0.0, 0.0, n
    mean = sum(v) / n
    vt, vt1 = v[:-1], v[1:]
    mt, mt1 = sum(vt) / (n - 1), sum(vt1) / (n - 1)
    num = sum((vt[i] - mt) * (vt1[i] - mt1) for i in range(n - 1))
    dt = sum((x - mt) ** 2 for x in vt)
    dt1 = sum((x - mt1) ** 2 for x in vt1)
    denom = max(math.sqrt(dt * dt1), 1e-10)
    lag1 = num / denom
    var = sum((x - mean) ** 2 for x in v) / (n - 1)
    return mean, lag1, var, n


def print_table(label: str, ode_res: dict, kf_res: dict, targets: dict, qf: float):
    print(f"\n{'=' * 80}")
    print(f"  {label}")
    print(f"{'=' * 80}")
    hdr = f"  {'dim':<6} {'target lag1':>12} {'ODE mean':>10} {'ODE lag1':>10} {'ODE var':>10} | {'KF mean':>10} {'KF lag1':>10} {'KF var':>10} | {'dLag1':>8} {'dBias':>8}"
    print(hdr)
    print(f"  {'-' * 6} {'-' * 12} {'-' * 10} {'-' * 10} {'-' * 10} | {'-' * 10} {'-' * 10} {'-' * 10} | {'-' * 8} {'-' * 8}")

    for dim in ['p', 'a', 'd']:
        tl = compute_stats(targets[dim])[1]
        om, ol, ov, _ = compute_stats(ode_res[dim])
        km, kl, kv, _ = compute_stats(kf_res[dim])
        d_lag1 = ol - kl
        d_bias = abs(om) - abs(km)
        print(f"  {dim:<6} {tl:>12.4f} {om:>10.5f} {ol:>10.4f} {ov:>10.6f} | {km:>10.5f} {kl:>10.4f} {kv:>10.6f} | {d_lag1:>+7.4f} {d_bias:>+7.4f}")

    print(f"\n  Kalman Q_final: {qf:.6f}")
    if qf >= 0.019:
        print(f"  ⚠️ Q 达到上限，真实数据噪声超过模型预期，建议增大 q_max")


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    date_dir = os.path.join(project_dir, 'date')

    files = sorted([f for f in os.listdir(date_dir) if f.endswith('.csv')])
    if not files:
        print("ERROR: date/ 目录下没有 CSV 文件")
        sys.exit(1)

    for fname in files:
        fp = os.path.join(date_dir, fname)
        size_kb = os.path.getsize(fp) / 1024
        print(f"\n  📂 {fname} ({size_kb:.0f} KB)", end='', flush=True)

        ode_res, kf_res, targets, qf = run_on_csv(fp)
        n = compute_stats(ode_res['p'])[3]
        print(f" → {n} 条有效记录")
        print_table(fname, ode_res, kf_res, targets, qf)

    print(f"\n{'=' * 80}")
    print("  完成")
    print(f"{'=' * 80}")