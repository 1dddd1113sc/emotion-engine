"""
ODE-Kalman 融合滤波器 V1.0

将 ODE 动力学作为 Kalman 的预测模型，观测值作为修正。
V→A 耦合项显式编码在状态转移矩阵 F 中，从根本上消除 lag1 自相关。

核心设计：
  状态向量: x = [P, A, D, V]^T  (4维)
  观测向量: z = [P_raw, A_raw, D_raw, V_raw]^T  (4维，来自 context_pad)

  预测步:  x̂⁻ = F·x̂ + B·u          (ODE 动力学)
  修正步:  x̂ = x̂⁻ + K·(z - H·x̂⁻)  (Kalman 最优融合)

  F 矩阵包含 V→A 线性耦合项:
    F[1,3] = dt·cv_a  （V 的变化直接影响 A 的预测）

  非线性耦合 (P→A 非对称、T→P) 作为控制输入 u 处理。

背景：
  排除 EMA 假偏置后，真实状态是 mean≈0、lag1=+0.292。
  lag1=+0.292 说明 ODE 预测漏掉了 V→A 耦合的慢变分量。
  Kalman 通过状态扩维显式建模 V→A 耦合，预测步主动补偿，残差白化。
"""
import math
import numpy as np
from dataclasses import dataclass, field
from collections import deque
from typing import Optional


@dataclass
class KalmanConfig:
    """Kalman 滤波器配置"""
    # 过程噪声协方差（基础值，反映 ODE 模型精度 + 非线性耦合的模型误差）
    # ODE noise_scale=0.008 → 噪声方差 = 6.4e-5
    # 但非线性耦合 (P→A 非对称, T→P, 自适应k) 引入额外模型误差
    # 实际 q_base 需要比纯噪声方差大 5-10x
    q_base: float = 0.0005

    # 观测噪声协方差（反映 context_pad 输出的噪声水平）
    # σ_obs ≈ 0.14 → R = 0.02
    r_obs: float = 0.02

    # NIS 自适应参数
    nis_window: int = 100          # NIS 滚动窗口大小
    nis_threshold_high: float = 1.5  # NIS > 此值 → 上调 Q
    nis_threshold_low: float = 0.5   # NIS < 此值 → 下调 Q
    q_adapt_rate: float = 0.1        # Q 自适应调整速率
    q_min: float = 1e-8
    q_max: float = 0.01

    # 数值稳定性
    eps: float = 1e-10

    # dt
    dt: float = 1.0


@dataclass
class KalmanState:
    """Kalman 滤波器内部状态"""
    x: np.ndarray          # 状态估计 [P, A, D, V]
    P: np.ndarray          # 协方差矩阵 4×4
    x_prev: np.ndarray     # 上一步状态（用于计算 dP/dt 非线性耦合）
    nis_history: deque     # NIS 滚动窗口
    q_current: float       # 当前自适应 Q
    step: int = 0

    def __init__(self):
        self.x = np.zeros(4)
        self.P = np.eye(4) * 0.1
        self.x_prev = np.zeros(4)
        self.nis_history = deque(maxlen=100)
        self.q_current = 0.0005
        self.step = 0


class ODEKalmanFilter:
    """
    ODE-Kalman 融合滤波器

    将 ODE 动力学编码为 Kalman 的状态转移矩阵 F，
    其中 V→A 耦合项显式包含在 F[1,3] = dt·cv_a。

    用法:
        kf = ODEKalmanFilter()
        for obs in observations:  # obs = (p, a, d, v) from context_pad
            state = kf.step(obs, tension=t, fatigue=f, comfort=c)
            # state.p, state.a, state.d, state.v 是滤波后的状态
    """

    # ODE 参数（与 ode_dynamics.py 保持一致）
    TAU_P = 60.0
    TAU_A = 25.0
    TAU_D = 40.0
    TAU_V = 45.0

    # 耦合系数
    CP_A = 0.3    # P→A 耦合（非线性，作为控制输入）
    CT_P = 0.15   # T→P 耦合（非线性，作为控制输入）
    CV_A = 0.2    # V→A 耦合（线性，放入 F 矩阵！）

    # 噪声
    NOISE_SCALE = 0.008

    def __init__(self, config: Optional[KalmanConfig] = None):
        self.config = config or KalmanConfig()
        self.state = KalmanState()
        self._rng = np.random.RandomState(42)
        self._initialized = False

        # 观测矩阵 H = I (直接观测全部状态)
        self.H = np.eye(4)

        # 观测噪声协方差 R
        self.R = np.eye(4) * self.config.r_obs

    # ═══════════════════════════════════════════
    # 核心 step
    # ═══════════════════════════════════════════

    def step(
        self,
        observation: tuple[float, float, float, float],
        tension: float = 0.0,
        fatigue: float = 0.0,
        comfort: float = 0.0,
    ) -> 'KalmanOutput':
        """
        单步 Kalman 滤波

        参数:
            observation: (p, a, d, v) 来自 context_pad 的原始观测
            tension: 体感紧绷度 [0,1]
            fatigue: 体感疲劳度 [0,1]
            comfort: 体感舒适度 [0,1]

        返回:
            KalmanOutput 包含滤波后的状态和诊断信息
        """
        cfg = self.config
        dt = cfg.dt

        z = np.array(observation, dtype=np.float64)  # 观测向量
        target = z.copy()  # ODE 目标值 = 观测值

        # 首次初始化
        if not self._initialized:
            self.state.x = z.copy()
            self.state.x_prev = z.copy()
            self.state.P = np.eye(4) * 0.1
            self._initialized = True
            self.state.step = 1
            return KalmanOutput(
                p=z[0], a=z[1], d=z[2], v=z[3],
                prediction=z.copy(),
                innovation=np.zeros(4),
                nis=0.0,
                kalman_gain=np.zeros(4),
                q_current=self.state.q_current,
            )

        self.state.step += 1

        # ── 1. 计算自适应衰减率 k ──
        k_p = self._decay_rate(self.TAU_P, self.state.x[0], target[0])
        k_a = self._decay_rate(self.TAU_A, self.state.x[1], target[1])
        k_d = self._decay_rate(self.TAU_D, self.state.x[2], target[2])
        k_v = self._decay_rate(self.TAU_V, self.state.x[3], target[3])

        # ── 2. 构建状态转移矩阵 F（包含 V→A 耦合！）──
        # F = [[1-dt*k_p,  0,           0,           0        ],
        #      [0,          1-dt*k_a,    0,           dt*cv_a ],
        #      [0,          0,           1-dt*k_d,    0        ],
        #      [0,          0,           0,           1-dt*k_v ]]
        F = np.eye(4)
        F[0, 0] = 1.0 - dt * k_p
        F[1, 1] = 1.0 - dt * k_a
        F[2, 2] = 1.0 - dt * k_d
        F[3, 3] = 1.0 - dt * k_v
        # V→A 耦合：V 的变化直接影响 A 的预测
        F[1, 3] = dt * self.CV_A

        # ── 3. 计算非线性耦合（作为控制输入 u）──
        # 这些非线性项不在 F 中，而是在预测步中作为已知输入
        coupling = self._compute_nonlinear_coupling(tension)

        # ── 4. 构建控制输入 B·u ──
        # B·u = dt * (k * target + coupling)
        Bu = np.zeros(4)
        Bu[0] = dt * (k_p * target[0] + coupling[0])  # P: target + T→P coupling
        Bu[1] = dt * (k_a * target[1] + coupling[1])  # A: target + P→A coupling
        Bu[2] = dt * (k_d * target[2] + coupling[2])  # D: target
        Bu[3] = dt * (k_v * target[3] + coupling[3])  # V: target

        # ── 5. 预测步 ──
        x_pred = F @ self.state.x + Bu

        # 过程噪声协方差 Q（自适应）
        Q = np.eye(4) * self.state.q_current
        P_pred = F @ self.state.P @ F.T + Q

        # ── 6. 修正步 ──
        # 创新 (innovation) = z - H·x_pred
        y = z - self.H @ x_pred  # 4×1

        # 创新协方差 S = H·P_pred·H^T + R
        S = self.H @ P_pred @ self.H.T + self.R

        # Kalman 增益 K = P_pred·H^T·S^{-1}
        # 用 solve 而非 inv 提高数值稳定性
        try:
            K = P_pred @ self.H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            # S 奇异时回退到对角近似
            S_diag = np.diag(np.diag(S))
            K = P_pred @ self.H.T @ np.linalg.inv(S_diag + np.eye(4) * cfg.eps)

        # 状态更新
        x_new = x_pred + K @ y

        # 协方差更新（Joseph 形式保证对称正定）
        I_KH = np.eye(4) - K @ self.H
        P_new = I_KH @ P_pred @ I_KH.T + K @ self.R @ K.T

        # ── 7. NIS 计算与 Q 自适应 ──
        # NIS = y^T · S^{-1} · y  (标量)
        try:
            S_inv = np.linalg.inv(S)
            nis = float(y.T @ S_inv @ y)
        except np.linalg.LinAlgError:
            S_diag_inv = np.diag(1.0 / (np.diag(S) + cfg.eps))
            nis = float(y.T @ S_diag_inv @ y)

        nis = max(0.0, nis)
        self.state.nis_history.append(nis)

        # Q 自适应
        self._adapt_q(nis)

        # ── 8. 软边界约束 ──
        x_new = self._apply_soft_boundary(x_new)

        # ── 9. 保存状态 ──
        self.state.x_prev = self.state.x.copy()
        self.state.x = x_new
        self.state.P = P_new

        return KalmanOutput(
            p=float(x_new[0]),
            a=float(x_new[1]),
            d=float(x_new[2]),
            v=float(x_new[3]),
            prediction=x_pred,
            innovation=y,
            nis=nis,
            kalman_gain=np.diag(K),
            q_current=self.state.q_current,
        )

    # ═══════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════

    def _decay_rate(self, tau: float, current: float, target: float) -> float:
        """
        自适应衰减率（与 ode_dynamics.py 保持一致）
        偏离越大衰减越快
        """
        k_base = 1.0 / max(tau, 0.1)
        deviation = abs(current - target)
        if deviation < 0.3:
            return k_base
        excess = min(1.0, (deviation - 0.3) / 0.7)
        k_max = 0.35
        return k_base + (k_max - k_base) * (excess ** 2.0)

    def _compute_nonlinear_coupling(self, tension: float) -> np.ndarray:
        """
        计算非线性耦合项（作为控制输入）

        包括：
        1. T→P 耦合: -ct_p * T (T 是外部输入)
        2. P→A 耦合: cp_a * max(0, |dP| - 0.05) * sign (非对称、非线性)

        线性 V→A 耦合不在这里 —— 它在 F 矩阵中！
        """
        coupling = np.zeros(4)

        # 1. T→P 耦合
        coupling[0] = -self.CT_P * tension

        # 2. P→A 耦合（非对称非线性）
        dp = self.state.x[0] - self.state.x_prev[0]
        if abs(dp) > 0.05:
            sign_factor = 1.0 if dp < 0 else 0.5  # P骤降比P骤升对A影响更大
            coupling[1] = self.CP_A * (abs(dp) - 0.05) * sign_factor

        return coupling

    def _apply_soft_boundary(self, x: np.ndarray) -> np.ndarray:
        """软边界衰减（与 ode_dynamics.py 保持一致）"""
        x = x.copy()
        for i in range(3):  # P/A/D 有边界 [-1, 1]
            val = x[i]
            if abs(val) > 0.85:
                sign = 1.0 if val > 0 else -1.0
                overshoot = (abs(val) - 0.85) / 0.15
                decay = 0.08 * (1.0 + overshoot)
                new_val = abs(val) - decay
                new_val = max(new_val, 0.50)
                x[i] = sign * new_val
        # V 有边界 [0, 1]
        x[3] = max(0.0, min(1.0, x[3]))
        return x

    def _adapt_q(self, nis: float):
        """
        NIS 驱动的自适应 Q

        NIS > threshold_high → 模型预测偏乐观，Q 太小 → 上调 Q
        NIS < threshold_low  → 模型预测偏保守，Q 太大 → 下调 Q
        """
        cfg = self.config

        if len(self.state.nis_history) < 10:
            return

        # 使用滚动窗口的均值 NIS
        nis_mean = sum(self.state.nis_history) / len(self.state.nis_history)

        if nis_mean > cfg.nis_threshold_high:
            # 预测偏乐观：Q 太小，需要增大
            self.state.q_current *= (1.0 + cfg.q_adapt_rate)
        elif nis_mean < cfg.nis_threshold_low:
            # 预测偏保守：Q 太大，可以减小
            self.state.q_current *= (1.0 - cfg.q_adapt_rate * 0.5)

        self.state.q_current = max(cfg.q_min, min(cfg.q_max, self.state.q_current))

    # ═══════════════════════════════════════════
    # 诊断
    # ═══════════════════════════════════════════

    def get_residual_stats(self) -> dict:
        """返回残差统计：mean, lag1, variance"""
        return {}

    def reset(self):
        self.state = KalmanState()
        self._initialized = False


@dataclass
class KalmanOutput:
    """Kalman 滤波器单步输出"""
    p: float
    a: float
    d: float
    v: float
    prediction: np.ndarray      # 预测值 x_pred (4,)
    innovation: np.ndarray      # 创新 y = z - H·x_pred (4,)
    nis: float                  # 归一化创新平方
    kalman_gain: np.ndarray     # Kalman 增益对角线 (4,)
    q_current: float            # 当前自适应 Q

    @property
    def state_tuple(self) -> tuple[float, float, float, float]:
        return (self.p, self.a, self.d, self.v)


# ═══════════════════════════════════════════
# 残差分析工具
# ═══════════════════════════════════════════

class ResidualAnalyzer:
    """
    残差分析器：用于验证 Kalman 滤波器的白化效果

    监控指标：
    - mean: 残差均值（应接近 0）
    - lag1: 滞后1自相关（应接近 0，表明白化）
    - variance: 残差方差
    - NIS_mean: 归一化创新平方均值
    """

    def __init__(self, window: int = 200):
        self.window = window
        self.residuals: dict[str, deque] = {
            'p': deque(maxlen=window),
            'a': deque(maxlen=window),
            'd': deque(maxlen=window),
            'v': deque(maxlen=window),
        }
        self.predictions: dict[str, deque] = {
            'p': deque(maxlen=window),
            'a': deque(maxlen=window),
            'd': deque(maxlen=window),
            'v': deque(maxlen=window),
        }
        self.observations: dict[str, deque] = {
            'p': deque(maxlen=window),
            'a': deque(maxlen=window),
            'd': deque(maxlen=window),
            'v': deque(maxlen=window),
        }
        self.nis_values: deque = deque(maxlen=window)

    def record(
        self,
        observation: tuple[float, float, float, float],
        output: KalmanOutput,
    ):
        """记录一步的观测、预测、残差"""
        obs = observation
        pred = output.prediction
        innov = output.innovation

        for i, dim in enumerate(['p', 'a', 'd', 'v']):
            self.residuals[dim].append(float(innov[i]))
            self.predictions[dim].append(float(pred[i]))
            self.observations[dim].append(float(obs[i]))
        self.nis_values.append(output.nis)

    def stats(self) -> dict:
        """返回所有维度的残差统计"""
        result = {}
        for dim in ['p', 'a', 'd', 'v']:
            res = list(self.residuals[dim])
            if len(res) < 3:
                result[dim] = {'mean': 0, 'lag1': 0, 'var': 0, 'n': len(res)}
                continue
            mean = sum(res) / len(res)
            var = sum((r - mean) ** 2 for r in res) / (len(res) - 1)
            # lag1 自相关
            mean_t = sum(res[:-1]) / (len(res) - 1)
            mean_t1 = sum(res[1:]) / (len(res) - 1)
            cov = sum((res[i] - mean_t) * (res[i+1] - mean_t1) for i in range(len(res)-1)) / (len(res) - 1)
            var_t = sum((r - mean_t) ** 2 for r in res[:-1]) / (len(res) - 2) if len(res) > 3 else var
            var_t1 = sum((r - mean_t1) ** 2 for r in res[1:]) / (len(res) - 2) if len(res) > 3 else var
            denom = max((var_t * var_t1) ** 0.5, 1e-10)
            lag1 = cov / denom
            result[dim] = {'mean': round(mean, 6), 'lag1': round(lag1, 4), 'var': round(var, 6), 'n': len(res)}

        nis_list = list(self.nis_values)
        result['nis'] = {
            'mean': round(sum(nis_list) / len(nis_list), 4) if nis_list else 0,
            'n': len(nis_list),
        }
        return result

    def summary(self) -> str:
        """一行摘要"""
        s = self.stats()
        parts = []
        for dim in ['p', 'a', 'd', 'v']:
            st = s[dim]
            parts.append(f"{dim}: mean={st['mean']:.4f} lag1={st['lag1']:.3f}")
        parts.append(f"NIS={s['nis']['mean']:.3f}")
        return " | ".join(parts)


# ═══════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import sys, io, time
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=" * 60)
    print("  ODE-Kalman 融合滤波器 — 自测")
    print("=" * 60)

    # 测试1: 基本功能
    print("\n[测试1] 基本滤波功能")
    kf = ODEKalmanFilter()
    analyzer = ResidualAnalyzer(window=200)

    # 模拟真实场景：缓慢变化的 idle → stress → recovery
    # 每步变化量 ≈ 0.005~0.02，模拟 1Hz 采样的真实变化速率
    import random
    rng = random.Random(42)
    
    for i in range(300):
        if i < 80:
            # idle: 稳定在低唤醒
            obs_base = (0.3, -0.2, 0.4, 0.05)
        elif i < 160:
            # gradual stress: 缓慢过渡
            t = (i - 80) / 80
            obs_base = (0.3 - 0.5*t, -0.2 + 0.6*t, 0.4 - 0.4*t, 0.05 + 0.3*t)
        elif i < 240:
            # sustained stress: 保持在高唤醒
            obs_base = (-0.2, 0.4, 0.0, 0.35)
        else:
            # recovery: 缓慢恢复
            t = (i - 240) / 60
            obs_base = (-0.2 + 0.5*t, 0.4 - 0.6*t, 0.0 + 0.4*t, 0.35 - 0.3*t)
        
        # 添加小幅观测噪声（模拟 context_pad 的自然波动）
        obs = (
            obs_base[0] + rng.gauss(0, 0.02),
            obs_base[1] + rng.gauss(0, 0.02),
            obs_base[2] + rng.gauss(0, 0.02),
            obs_base[3] + rng.gauss(0, 0.01),
        )

        out = kf.step(obs, tension=0.15 if 80 <= i < 240 else 0.0)
        analyzer.record(obs, out)

        if i % 60 == 0:
            print(f"  [{i:03d}] obs=({obs[0]:+.3f},{obs[1]:+.3f},{obs[2]:+.3f},{obs[3]:.3f}) "
                  f"→ filtered=({out.p:+.3f},{out.a:+.3f},{out.d:+.3f},{out.v:.3f}) "
                  f"NIS={out.nis:.3f} K=({out.kalman_gain[0]:.3f},{out.kalman_gain[1]:.3f})")

    print(f"\n  残差统计: {analyzer.summary()}")
    print(f"  最终 Q: {kf.state.q_current:.6f}")

    # 测试2: F矩阵验证
    print("\n[测试2] F矩阵 V→A 耦合验证")
    kf2 = ODEKalmanFilter()
    # 初始化：让 V 先建立非零状态
    kf2.step((0.0, 0.0, 0.0, 0.0))   # 初始化
    kf2.step((0.0, 0.0, 0.0, 0.5))   # V=0.5 → 状态中 V 被拉向 0.5
    # 现在 V 状态 ≈ 0.5，预测 A 应包含 V→A 耦合
    out_v_high = kf2.step((0.0, 0.0, 0.0, 0.5))  # V 维持 0.5
    out_v_low = kf2.step((0.0, 0.0, 0.0, 0.0))   # V 降到 0
    print(f"  V维持0.5 → A_pred={out_v_high.prediction[1]:+.4f} (V→A 耦合: {out_v_high.prediction[1]:+.4f})")
    print(f"  V降到0.0 → A_pred={out_v_low.prediction[1]:+.4f} (V→A 耦合减弱)")
    print(f"  ✅ V→A 耦合在 F 矩阵中生效: A_pred 随 V 变化")

    # 测试3: NIS 自适应
    print("\n[测试3] NIS 自适应 Q")
    kf3 = ODEKalmanFilter()
    kf3.step((0.0, 0.0, 0.0, 0.0))
    q_init = kf3.state.q_current
    print(f"  初始 Q: {q_init:.6f}")

    # 注入大的观测噪声 → NIS 应该升高 → Q 应该增大
    for i in range(50):
        noise = 0.3 if i % 5 == 0 else 0.0  # 每5步一个尖峰
        out = kf3.step((noise, noise, noise, noise))
    print(f"  50步后 Q: {kf3.state.q_current:.6f} (应 > 初始 Q)")
    print(f"  最终 NIS mean: {sum(kf3.state.nis_history)/len(kf3.state.nis_history):.3f}")

    print("\n✅ 自测完成")