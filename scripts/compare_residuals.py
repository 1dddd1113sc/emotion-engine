"""
残差对比分析：ODE vs Kalman

在同一模拟数据上分别运行 ODE 和 Kalman，
比较残差的 mean 和 lag1 自相关。

核心验证：
- ODE 残差 lag1 ≈ +0.292（已知问题，V→A 耦合缺失）
- Kalman 残差 lag1 → 0（F 矩阵包含 V→A 耦合后白化）
"""
import sys, io, os, math, random
# 确保能找到 emotion-engine 模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collections import deque
from ode_dynamics import ODEDynamics, ODEConfig, EmotionState, DEFAULT_ODE_CONFIG
from kalman_filter import ODEKalmanFilter, KalmanOutput, ResidualAnalyzer


def run_comparison(
    scenario: str = "v_a_coupled",
    steps: int = 500,
    seed: int = 42,
):
    """
    场景:
    - v_a_coupled: V 和 A 有真实耦合关系（模拟真实系统）
    - steady_state: 稳定状态 + 小幅噪声
    - ramp: 缓慢渐变
    """
    rng = random.Random(seed)

    # 初始化
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)
    kf = ODEKalmanFilter()

    # 残差记录
    ode_residuals = {dim: deque(maxlen=steps) for dim in ['p', 'a', 'd', 'v']}
    kf_residuals = {dim: deque(maxlen=steps) for dim in ['p', 'a', 'd', 'v']}
    ode_predictions = {dim: deque(maxlen=steps) for dim in ['p', 'a', 'd', 'v']}
    kf_predictions = {dim: deque(maxlen=steps) for dim in ['p', 'a', 'd', 'v']}
    kf_analyzer = ResidualAnalyzer(window=steps)
    truths = {dim: deque(maxlen=steps) for dim in ['p', 'a', 'd', 'v']}

    # 模拟数据生成
    if scenario == "v_a_coupled":
        # V 和 A 有真实耦合：V 先变化，A 跟随
        # 模拟 V→A 耦合的物理过程
        v_true = 0.1
        a_true = 0.0
        p_true = 0.3
        d_true = 0.4

        for i in range(steps):
            # V 缓慢漂移（模拟波动性变化）
            v_true += rng.gauss(0, 0.003)
            v_true = max(0.01, min(0.8, v_true))

            # A 受 V 影响（V→A 耦合：V 高 → A 高）
            a_target = -0.2 + 0.8 * v_true + rng.gauss(0, 0.02)
            a_true = 0.95 * a_true + 0.05 * a_target

            # P 和 D 有独立的小幅波动
            p_true = 0.95 * p_true + 0.05 * (0.3 + rng.gauss(0, 0.03))
            d_true = 0.95 * d_true + 0.05 * (0.4 + rng.gauss(0, 0.03))

            # 观测 = 真实值 + 观测噪声
            obs = (
                p_true + rng.gauss(0, 0.01),
                a_true + rng.gauss(0, 0.01),
                d_true + rng.gauss(0, 0.01),
                v_true + rng.gauss(0, 0.005),
            )

            # ODE 步进
            target_ode = EmotionState(
                p=obs[0], a=obs[1], d=obs[2], v=obs[3],
                f=0.0, t=0.0, c=1.0,
            ).clamp()
            state_ode = ode.step(target_ode)

            # ODE 预测值 = 上一步状态 + 动力学（理想情况下应该接近观测）
            # 残差 = 观测 - ODE 状态
            ode_residuals['p'].append(obs[0] - state_ode.p)
            ode_residuals['a'].append(obs[1] - state_ode.a)
            ode_residuals['d'].append(obs[2] - state_ode.d)
            ode_residuals['v'].append(obs[3] - state_ode.v)

            # Kalman 步进
            out_kf = kf.step(obs, tension=0.0)
            kf_analyzer.record(obs, out_kf)

            for j, dim in enumerate(['p', 'a', 'd', 'v']):
                kf_residuals[dim].append(out_kf.innovation[j])
                truths[dim].append([p_true, a_true, d_true, v_true][j])

    elif scenario == "steady_state":
        # 稳定状态 + 小幅噪声（最干净的测试）
        for i in range(steps):
            obs = (
                0.3 + rng.gauss(0, 0.02),
                -0.1 + rng.gauss(0, 0.02),
                0.4 + rng.gauss(0, 0.02),
                0.05 + rng.gauss(0, 0.01),
            )

            target_ode = EmotionState(
                p=obs[0], a=obs[1], d=obs[2], v=obs[3],
                f=0.0, t=0.0, c=1.0,
            ).clamp()
            state_ode = ode.step(target_ode)

            ode_residuals['p'].append(obs[0] - state_ode.p)
            ode_residuals['a'].append(obs[1] - state_ode.a)
            ode_residuals['d'].append(obs[2] - state_ode.d)
            ode_residuals['v'].append(obs[3] - state_ode.v)

            out_kf = kf.step(obs, tension=0.0)
            kf_analyzer.record(obs, out_kf)

            for j, dim in enumerate(['p', 'a', 'd', 'v']):
                kf_residuals[dim].append(out_kf.innovation[j])

    elif scenario == "ramp":
        # 缓慢渐变（和自测类似但有足够长的稳态段）
        for i in range(steps):
            if i < 200:
                obs_base = (0.3, -0.2, 0.4, 0.05)
            elif i < 300:
                t = (i - 200) / 100
                obs_base = (0.3 - 0.5*t, -0.2 + 0.6*t, 0.4 - 0.4*t, 0.05 + 0.3*t)
            else:
                obs_base = (-0.2, 0.4, 0.0, 0.35)

            obs = (
                obs_base[0] + rng.gauss(0, 0.02),
                obs_base[1] + rng.gauss(0, 0.02),
                obs_base[2] + rng.gauss(0, 0.02),
                obs_base[3] + rng.gauss(0, 0.01),
            )

            target_ode = EmotionState(
                p=obs[0], a=obs[1], d=obs[2], v=obs[3],
                f=0.0, t=0.0, c=1.0,
            ).clamp()
            state_ode = ode.step(target_ode)

            ode_residuals['p'].append(obs[0] - state_ode.p)
            ode_residuals['a'].append(obs[1] - state_ode.a)
            ode_residuals['d'].append(obs[2] - state_ode.d)
            ode_residuals['v'].append(obs[3] - state_ode.v)

            out_kf = kf.step(obs, tension=0.0)
            kf_analyzer.record(obs, out_kf)

            for j, dim in enumerate(['p', 'a', 'd', 'v']):
                kf_residuals[dim].append(out_kf.innovation[j])

    # 计算统计量
    def calc_stats(residuals_dict, skip_first=50):
        """计算残差的 mean 和 lag1"""
        result = {}
        for dim in ['p', 'a', 'd', 'v']:
            res = list(residuals_dict[dim])[skip_first:]
            if len(res) < 10:
                result[dim] = {'mean': 0, 'lag1': 0, 'n': len(res)}
                continue
            mean = sum(res) / len(res)
            # lag1
            n = len(res)
            res_t = res[:-1]
            res_t1 = res[1:]
            mean_t = sum(res_t) / (n - 1)
            mean_t1 = sum(res_t1) / (n - 1)
            num = sum((res_t[i] - mean_t) * (res_t1[i] - mean_t1) for i in range(n - 1))
            den_t = sum((r - mean_t) ** 2 for r in res_t)
            den_t1 = sum((r - mean_t1) ** 2 for r in res_t1)
            denom = max((den_t * den_t1) ** 0.5, 1e-10)
            lag1 = num / denom
            result[dim] = {
                'mean': round(mean, 5),
                'lag1': round(lag1, 4),
                'n': n,
            }
        return result

    ode_stats = calc_stats(ode_residuals)
    kf_stats = kf_analyzer.stats()

    return ode_stats, kf_stats, kf.state.q_current


if __name__ == "__main__":
    print("=" * 70)
    print("  ODE vs Kalman 残差对比分析")
    print("=" * 70)

    for scenario in ["v_a_coupled", "steady_state", "ramp"]:
        print(f"\n{'─' * 70}")
        print(f"  场景: {scenario}")
        print(f"{'─' * 70}")

        ode_stats, kf_stats, q_final = run_comparison(scenario, steps=500)

        print(f"\n  {'维度':<6} {'ODE mean':>10} {'ODE lag1':>10} | {'Kalman mean':>12} {'Kalman lag1':>12} | {'Δlag1':>8}")
        print(f"  {'─'*6} {'─'*10} {'─'*10} | {'─'*12} {'─'*12} | {'─'*8}")

        for dim in ['p', 'a', 'd', 'v']:
            om = ode_stats[dim]['mean']
            ol = ode_stats[dim]['lag1']
            km = kf_stats[dim]['mean']
            kl = kf_stats[dim]['lag1']
            delta = ol - kl
            marker = "✅" if abs(kl) < 0.15 else ("⚠️" if abs(kl) < 0.3 else "❌")
            print(f"  {dim:<6} {om:>10.5f} {ol:>10.4f} | {km:>12.5f} {kl:>12.4f} | {delta:>+7.4f} {marker}")

        print(f"\n  Kalman 最终 Q: {q_final:.6f}")
        print(f"  Kalman NIS mean: {kf_stats['nis']['mean']:.3f}")

        # 关键判断
        a_lag1_ode = ode_stats['a']['lag1']
        a_lag1_kf = kf_stats['a']['lag1']
        if a_lag1_ode > 0.2 and a_lag1_kf < 0.15:
            print(f"  ✅ Kalman 有效消除 A 维度的 lag1: {a_lag1_ode:.3f} → {a_lag1_kf:.3f}")

    print(f"\n{'=' * 70}")
    print("  分析完成")
    print("=" * 70)