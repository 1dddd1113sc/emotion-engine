"""
真实数据对比：EMA vs Kalman on v6_live_data_v62.json

用真实的 pipeline 记录数据，对比：
- EMA 平滑输出（原 pipeline 的 smooth 字段）
- ODE 状态（原 pipeline 的 ode 字段）
- Kalman 滤波输出（新加的）

核心指标：残差的 mean 和 lag1 自相关
"""
import sys, os, io, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
from collections import deque
from kalman_filter import ODEKalmanFilter, ResidualAnalyzer


def load_real_data(filepath: str) -> list[dict]:
    """加载真实数据，处理编码"""
    with open(filepath, 'rb') as f:
        raw = f.read()
    # 尝试 UTF-8，失败则用 GBK
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('gbk', errors='replace')
    return json.loads(text)


def run_comparison_on_real_data(data: list[dict], skip_first: int = 10):
    """
    在真实数据上运行 Kalman，和 EMA/ODE 对比。

    数据字段：
    - pad: {p, a, d, v} — context_pad 原始输出
    - smooth: {p, a, d, volatility} — EMA 平滑后
    - ode: {p, a, d, v, f, t, c} — ODE 状态
    - body: {fatigue, tension, comfort} — 体感
    """
    kf = ODEKalmanFilter()
    analyzer = ResidualAnalyzer(window=len(data))

    # 残差记录
    ema_residuals = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    ode_residuals = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    kf_residuals = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}

    # 状态记录
    ema_states = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    ode_states = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    kf_states = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}
    raw_states = {d: deque(maxlen=len(data)) for d in ['p', 'a', 'd', 'v']}

    for i, record in enumerate(data):
        pad = record.get('pad', {})
        smooth = record.get('smooth', {})
        ode = record.get('ode', {})
        body = record.get('body', {})

        # 提取值
        raw_p = float(pad.get('p', 0))
        raw_a = float(pad.get('a', 0))
        raw_d = float(pad.get('d', 0))
        raw_v = float(pad.get('v', 0.05))

        smooth_p = float(smooth.get('p', raw_p))
        smooth_a = float(smooth.get('a', raw_a))
        smooth_d = float(smooth.get('d', raw_d))
        smooth_v = float(smooth.get('volatility', raw_v))

        ode_p = float(ode.get('p', raw_p))
        ode_a = float(ode.get('a', raw_a))
        ode_d = float(ode.get('d', raw_d))
        ode_v = float(ode.get('v', raw_v))

        tension = float(body.get('tension', 0))
        fatigue = float(body.get('fatigue', 0))
        comfort = float(body.get('comfort', 1))

        # Kalman 步进
        kf_out = kf.step(
            (raw_p, raw_a, raw_d, raw_v),
            tension=tension,
            fatigue=fatigue,
            comfort=comfort,
        )

        # 记录原始值
        raw_states['p'].append(raw_p)
        raw_states['a'].append(raw_a)
        raw_states['d'].append(raw_d)
        raw_states['v'].append(raw_v)

        # EMA 残差 = raw - smooth（EMA 输出和原始输入的差）
        ema_residuals['p'].append(raw_p - smooth_p)
        ema_residuals['a'].append(raw_a - smooth_a)
        ema_residuals['d'].append(raw_d - smooth_d)
        ema_residuals['v'].append(raw_v - smooth_v)

        # ODE 残差 = raw - ode（ODE 状态和原始输入的差）
        ode_residuals['p'].append(raw_p - ode_p)
        ode_residuals['a'].append(raw_a - ode_a)
        ode_residuals['d'].append(raw_d - ode_d)
        ode_residuals['v'].append(raw_v - ode_v)

        # Kalman 残差 = innovation（观测 - 预测）
        kf_residuals['p'].append(float(kf_out.innovation[0]))
        kf_residuals['a'].append(float(kf_out.innovation[1]))
        kf_residuals['d'].append(float(kf_out.innovation[2]))
        kf_residuals['v'].append(float(kf_out.innovation[3]))

        # 状态记录
        ema_states['p'].append(smooth_p)
        ema_states['a'].append(smooth_a)
        ema_states['d'].append(smooth_d)
        ema_states['v'].append(smooth_v)

        ode_states['p'].append(ode_p)
        ode_states['a'].append(ode_a)
        ode_states['d'].append(ode_d)
        ode_states['v'].append(ode_v)

        kf_states['p'].append(kf_out.p)
        kf_states['a'].append(kf_out.a)
        kf_states['d'].append(kf_out.d)
        kf_states['v'].append(kf_out.v)

    return {
        'raw': raw_states,
        'ema': {'residuals': ema_residuals, 'states': ema_states},
        'ode': {'residuals': ode_residuals, 'states': ode_states},
        'kalman': {'residuals': kf_residuals, 'states': kf_states, 'q_final': kf.state.q_current},
    }


def calc_residual_stats(residuals: dict, skip: int = 50) -> dict:
    """计算残差的 mean, lag1, std"""
    result = {}
    for dim in ['p', 'a', 'd', 'v']:
        res = list(residuals[dim])[skip:]
        if len(res) < 10:
            result[dim] = {'mean': 0, 'lag1': 0, 'std': 0, 'n': 0}
            continue
        n = len(res)
        mean = sum(res) / n
        std = math.sqrt(sum((r - mean)**2 for r in res) / (n - 1))

        # lag1
        res_t = res[:-1]
        res_t1 = res[1:]
        mean_t = sum(res_t) / (n - 1)
        mean_t1 = sum(res_t1) / (n - 1)
        num = sum((res_t[i] - mean_t) * (res_t1[i] - mean_t1) for i in range(n - 1))
        den_t = sum((r - mean_t)**2 for r in res_t)
        den_t1 = sum((r - mean_t1)**2 for r in res_t1)
        denom = max(math.sqrt(den_t * den_t1), 1e-10)
        lag1 = num / denom

        result[dim] = {
            'mean': round(mean, 6),
            'lag1': round(lag1, 4),
            'std': round(std, 6),
            'n': n,
        }
    return result


def calc_state_lag1(states: dict, skip: int = 50) -> dict:
    """计算状态本身的 lag1 自相关（衡量平滑程度）"""
    result = {}
    for dim in ['p', 'a', 'd', 'v']:
        vals = list(states[dim])[skip:]
        if len(vals) < 10:
            result[dim] = 0
            continue
        n = len(vals)
        v_t = vals[:-1]
        v_t1 = vals[1:]
        mean_t = sum(v_t) / (n - 1)
        mean_t1 = sum(v_t1) / (n - 1)
        num = sum((v_t[i] - mean_t) * (v_t1[i] - mean_t1) for i in range(n - 1))
        den_t = sum((v - mean_t)**2 for v in v_t)
        den_t1 = sum((v - mean_t1)**2 for v in v_t1)
        denom = max(math.sqrt(den_t * den_t1), 1e-10)
        result[dim] = round(num / denom, 4)
    return result


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)

    data_file = os.path.join(project_dir, 'v6_live_data_v62.json')
    print(f"📂 加载真实数据: {data_file}")
    data = load_real_data(data_file)
    print(f"   共 {len(data)} 条记录")

    print(f"\n{'='*75}")
    print("  真实数据上的 EMA vs ODE vs Kalman 对比")
    print(f"{'='*75}")

    results = run_comparison_on_real_data(data)

    # 残差统计
    ema_stats = calc_residual_stats(results['ema']['residuals'])
    ode_stats = calc_residual_stats(results['ode']['residuals'])
    kf_stats = calc_residual_stats(results['kalman']['residuals'])

    print(f"\n{'─'*75}")
    print(f"  残差分析 (残差 = 观测 - 状态, 跳过前50步)")
    print(f"{'─'*75}")
    print(f"\n  {'维度':<6} {'EMA mean':>10} {'EMA lag1':>10} {'EMA std':>10} | {'ODE mean':>10} {'ODE lag1':>10} {'ODE std':>10} | {'Kalman mean':>10} {'Kalman lag1':>10} {'Kalman std':>10}")
    print(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10} | {'─'*10} {'─'*10} {'─'*10} | {'─'*10} {'─'*10} {'─'*10}")

    for dim in ['p', 'a', 'd', 'v']:
        em = ema_stats[dim]
        om = ode_stats[dim]
        km = kf_stats[dim]
        print(f"  {dim:<6} {em['mean']:>10.5f} {em['lag1']:>10.4f} {em['std']:>10.5f} | "
              f"{om['mean']:>10.5f} {om['lag1']:>10.4f} {om['std']:>10.5f} | "
              f"{km['mean']:>10.5f} {km['lag1']:>10.4f} {km['std']:>10.5f}")

    # 状态 lag1
    raw_lag1 = calc_state_lag1(results['raw'])
    ema_lag1 = calc_state_lag1(results['ema']['states'])
    ode_lag1 = calc_state_lag1(results['ode']['states'])
    kf_lag1 = calc_state_lag1(results['kalman']['states'])

    print(f"\n{'─'*75}")
    print(f"  状态 lag1 自相关 (衡量平滑程度，越高越平滑/滞后)")
    print(f"{'─'*75}")
    print(f"\n  {'维度':<6} {'Raw lag1':>10} {'EMA lag1':>10} {'ODE lag1':>10} {'Kalman lag1':>10}")
    print(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")
    for dim in ['p', 'a', 'd', 'v']:
        print(f"  {dim:<6} {raw_lag1[dim]:>10.4f} {ema_lag1[dim]:>10.4f} {ode_lag1[dim]:>10.4f} {kf_lag1[dim]:>10.4f}")

    # 关键判断
    print(f"\n{'─'*75}")
    print(f"  关键指标")
    print(f"{'─'*75}")
    print(f"  Kalman 最终 Q: {results['kalman']['q_final']:.6f}")

    # 原始问题：ODE A维度 lag1≈+0.292
    # 检查 Kalman 是否改善
    for dim in ['a', 'p', 'd', 'v']:
        ode_l1 = ode_stats[dim]['lag1']
        kf_l1 = kf_stats[dim]['lag1']
        delta = ode_l1 - kf_l1
        if abs(ode_l1) > 0.1 and abs(kf_l1) < abs(ode_l1):
            print(f"  ✅ {dim} 维度: ODE lag1={ode_l1:.4f} → Kalman lag1={kf_l1:.4f} (改善 {delta:+.4f})")
        elif abs(kf_l1) < 0.1:
            print(f"  ✅ {dim} 维度: Kalman lag1={kf_l1:.4f} (接近白噪声)")
        else:
            print(f"  ⚠️ {dim} 维度: ODE lag1={ode_l1:.4f}, Kalman lag1={kf_l1:.4f} (改善 {delta:+.4f})")

    # 残差 mean 是否接近 0
    for dim in ['p', 'a', 'd', 'v']:
        km = kf_stats[dim]['mean']
        if abs(km) < 0.01:
            print(f"  ✅ {dim} 残差 mean={km:.6f} (接近零)")
        elif abs(km) < 0.05:
            print(f"  ⚠️ {dim} 残差 mean={km:.6f} (轻微偏置)")
        else:
            print(f"  ❌ {dim} 残差 mean={km:.6f} (有偏置)")

    print(f"\n{'='*75}")
    print("  分析完成")
    print(f"{'='*75}")