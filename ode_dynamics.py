"""
ODE 情感动力系统

核心思想：情绪不是对当前刺激的即时反应，而是一个有记忆的动态系统。
- 惯性：从愤怒恢复到平静需要时间
- 爆发：持续压抑后一个小触发可能引爆
- 衰减：没有新刺激时情绪自然回落
- 耦合：P剧变时A飙升（惊讶/恐慌），疲劳侵蚀D

数学模型（Euler法求解ODE）：
  dE/dt = -k * (E - E_target) + coupling + noise

其中：
  k = 1/τ（衰减率）
  E_target = 当前指标映射的目标值
  coupling = 维度间耦合项
  noise = 自然波动
"""
import math
import random
from dataclasses import dataclass


@dataclass
class EmotionState:
    """7维情感状态"""
    p: float = 0.0      # Pleasure [-1, 1]
    a: float = 0.0      # Arousal [-1, 1]
    d: float = 0.0      # Dominance [-1, 1]
    v: float = 0.0      # Volatility [0, 1]
    f: float = 0.0      # Fatigue [0, 1]
    t: float = 0.0      # Tension [0, 1]
    c: float = 1.0      # Comfort [0, 1]

    def clamp(self):
        self.p = max(-1, min(1, self.p))
        self.a = max(-1, min(1, self.a))
        self.d = max(-1, min(1, self.d))
        self.v = max(0, min(1, self.v))
        self.f = max(0, min(1, self.f))
        self.t = max(0, min(1, self.t))
        self.c = max(0, min(1, self.c))
        return self


@dataclass
class ODEConfig:
    """ODE参数配置"""
    # 各维度衰减时间常数 τ（秒）
    tau_p: float = 60.0     # P：适中（原120太慢，30太激进）
    tau_a: float = 25.0     # A：快速响应
    tau_d: float = 40.0     # D：适中
    tau_v: float = 45.0     # V：中等衰减
    tau_f: float = 600.0    # F：疲劳持久（10分钟半衰期）
    tau_t: float = 90.0     # T：中慢衰减
    tau_c: float = 180.0    # C：中等衰减

    # 耦合系数
    cp_a: float = 0.3       # P剧变 → A飙升
    cf_d: float = 0.2       # F高 → D被侵蚀
    ct_p: float = 0.15      # T高 → P被拉低
    cv_a: float = 0.2       # V高 → A升高

    # 噪声幅度（0.02太大干扰正常态，降到0.008）
    noise_scale: float = 0.008

    # 时间步长
    dt: float = 1.0


# 统一默认配置（所有入口文件应引用此常量，避免参数不一致）
DEFAULT_ODE_CONFIG = ODEConfig(
    tau_p=60, tau_a=25, tau_d=40, tau_v=45,
    tau_f=600, tau_t=90, tau_c=180,
    noise_scale=0.008, dt=1.0,
)


class ODEDynamics:
    """
    ODE情感动力系统

    用法：
        ode = ODEDynamics()
        for step in range(100):
            # 从当前指标计算目标值
            target = compute_target(cpu, mem, error_rate, latency)
            # ODE步进
            state = ode.step(target, dt=1.0)
            # state.p, state.a, ... 就是当前情感状态
    """

    def __init__(self, config: ODEConfig | None = None):
        self.config = config or ODEConfig()
        self.state = EmotionState()
        self._prev_p: float = 0.0
        self._prev_a: float = 0.0
        self._step: int = 0
        self._rng = random.Random(42)
        self._initialized = False
        # 断崖检测（三方共识）
        self._cliff_counter: int = 0
        self._cliff_mode: bool = False
        self._prev_target_p: float = 0.0
        self._prev_target_a: float = 0.0
        self._prev_target_d: float = 0.0

    def _decay_rate(self, tau: float, current: float = 0.0, target: float = 0.0) -> float:
        """
        自适应衰减率（三方共识：偏离越大衰减越快）
        正常范围：k_base = 1/τ
        极端偏离：k_max ≈ 0.35（2步可回落）
        """
        k_base = 1.0 / max(tau, 0.1)
        deviation = abs(current - target)
        if deviation < 0.3:
            return k_base
        # 偏离越大，衰减越快（幂律缩放）
        excess = min(1.0, (deviation - 0.3) / 0.7)
        k_max = 0.35
        return k_base + (k_max - k_base) * (excess ** 2.0)

    def _coupling(self, target: EmotionState) -> tuple[float, float, float, float]:
        """
        计算维度间耦合项

        核心耦合：
        1. P剧变 → A飙升（惊讶/恐慌）
        2. F高 → D被侵蚀（疲劳削弱控制感）
        3. T高 → P被拉低（紧绷降低愉悦）
        4. V高 → A升高（波动增加兴奋）
        """
        cfg = self.config

        # 1. P的变化率 → A的耦合
        dp = self.state.p - self._prev_p
        coupling_a = cfg.cp_a * max(0, abs(dp) - 0.05) * (1 if dp < 0 else 0.5)
        # P骤降比P骤升对A的影响更大（负面冲击更强）

        # 2. F → D 耦合已移除：F由外部体感模块控制，不应参与ODE耦合
        # 否则每步 -0.06 的恒定耦合会把D拉到-1
        coupling_d = 0.0

        # 3. T → P 耦合（紧绷降低愉悦）
        coupling_p = -cfg.ct_p * self.state.t

        # 4. V → A 耦合（波动增加兴奋）
        coupling_a += cfg.cv_a * self.state.v

        return coupling_p, coupling_a, coupling_d, 0.0

    def _noise(self) -> float:
        """高斯噪声"""
        return self._rng.gauss(0, self.config.noise_scale)

    def step(self, target: EmotionState, dt: float | None = None) -> EmotionState:
        """
        ODE步进

        参数：
            target: 当前指标映射的目标情感状态
            dt: 时间步长（秒），None则用配置默认值

        返回：
            更新后的情感状态
        """
        if dt is None:
            dt = self.config.dt

        self._step += 1
        cfg = self.config

        # 首次步进：用目标值初始化
        if not self._initialized:
            self.state = EmotionState(
                p=target.p * 0.7, a=target.a * 0.5,
                d=target.d * 0.7, v=target.v * 0.5,
                f=target.f, t=target.t, c=target.c,
            )
            self._prev_p = self.state.p
            self._prev_a = self.state.a
            self._prev_target_p = target.p
            self._prev_target_a = target.a
            self._prev_target_d = target.d
            self._initialized = True

        # === 断崖检测（三方共识）===
        # 检测目标值突变（指标瞬间变化导致target突变）
        target_delta = max(
            abs(target.p - self._prev_target_p),
            abs(target.a - self._prev_target_a),
            abs(target.d - self._prev_target_d),
        )
        if target_delta > 0.4:
            self._cliff_mode = True
            self._cliff_counter = 3  # 断崖模式持续3步

        cliff_boost = 0.0
        if self._cliff_mode:
            # 断崖模式：加速收敛（alpha≈0.95）
            cliff_boost = 0.5  # 额外衰减量
            self._cliff_counter -= 1
            if self._cliff_counter <= 0:
                self._cliff_mode = False

        self._prev_target_p = target.p
        self._prev_target_a = target.a
        self._prev_target_d = target.d

        # 保存上一步的P（用于计算dP/dt）
        self._prev_p = self.state.p
        self._prev_a = self.state.a

        # 计算耦合项（用当前ODE状态）
        cp, ca, cd, cv = self._coupling(target)

        # === 自适应衰减率（三方共识：偏离越大衰减越快）===
        k_p = self._decay_rate(cfg.tau_p, self.state.p, target.p)
        k_a = self._decay_rate(cfg.tau_a, self.state.a, target.a)
        k_d = self._decay_rate(cfg.tau_d, self.state.d, target.d)
        k_v = self._decay_rate(cfg.tau_v, self.state.v, target.v)

        # 断崖模式：额外加速衰减
        if self._cliff_mode:
            k_p = max(k_p, 0.5)
            k_a = max(k_a, 0.5)
            k_d = max(k_d, 0.5)

        # Euler法求解 ODE：dE/dt = -k*(E - E_target) + coupling + noise
        self.state.p += dt * (-k_p * (self.state.p - target.p) + cp + self._noise())
        self.state.a += dt * (-k_a * (self.state.a - target.a) + ca + self._noise())
        self.state.d += dt * (-k_d * (self.state.d - target.d) + cd + self._noise())
        self.state.v += dt * (-k_v * (self.state.v - target.v) + cv + self._noise())

        # === 软边界衰减（GLM建议：防止A锁定在±1）===
        for attr in ['p', 'a', 'd']:
            val = getattr(self.state, attr)
            if abs(val) > 0.85:
                sign = 1.0 if val > 0 else -1.0
                overshoot = (abs(val) - 0.85) / 0.15  # [0, 1]
                decay = 0.08 * (1.0 + overshoot)  # 超出越多衰减越快
                new_val = abs(val) - decay
                new_val = max(new_val, 0.50)  # 保留底色
                setattr(self.state, attr, sign * new_val)

        # === 惯性反转加速（GLM建议）===
        # 当方向反转时，降低惯性阻力
        if (self.state.p - target.p) * (self._prev_p - target.p) < 0:
            self.state.p = 0.7 * self.state.p + 0.3 * target.p
        if (self.state.a - target.a) * (self._prev_a - target.a) < 0:
            self.state.a = 0.7 * self.state.a + 0.3 * target.a

        # F/T/C 由外部体感模块独立计算，直接覆盖（不做ODE）
        self.state.f = target.f
        self.state.t = target.t
        self.state.c = target.c

        self.state.clamp()
        return self.state

    def reset(self):
        self.state = EmotionState()
        self._prev_p = 0.0
        self._prev_a = 0.0
        self._step = 0


def compute_target(
    cpu: float, mem: float, error_rate: float, latency_ms: float,
    fatigue: float = 0.0, tension: float = 0.0, comfort: float = 1.0,
) -> EmotionState:
    """
    从当前指标计算目标情感状态（即"如果系统无记忆，此刻应该是什么情绪"）

    这就是 PAD 映射函数的输出，作为 ODE 的"引力源"
    """
    import math

    def tanh_norm(x, center, scale):
        return math.tanh((x - center) / max(scale, 0.01))

    err_n = tanh_norm(error_rate, 2.0, 8.0)
    lat_n = tanh_norm(latency_ms, 100, 400)
    cpu_n = tanh_norm(cpu, 30, 35)
    mem_n = tanh_norm(mem, 50, 30)

    # P：分段sigmoid
    p = 1.0 - 0.45 * max(0, err_n) - 0.25 * max(0, lat_n)
    # V4.1: 上调阈值，减少边界误报
    if 6 < error_rate <= 12:
        p -= 0.15 * (error_rate - 6) / 6.0
    if 12 < error_rate <= 20:
        p -= 0.25 * (error_rate - 12) / 8.0 * (1 + 0.5 * max(0, cpu_n))
    if error_rate > 20:
        p -= 0.4 * min(1, (error_rate - 20) / 20) ** 0.7
    if error_rate > 6 and cpu > 60:
        p -= 0.25 * min(1, (error_rate - 6) / 20 * (cpu - 60) / 30)
    if error_rate > 15 and cpu < 30:
        p -= 0.2 * min(1, (error_rate - 15) / 20)
    p = p * 2 - 1

    # A (V4.1: 上调错误阈值 + 内存压力)
    a = (0.6 * cpu_n + 0.2 * mem_n + 0.2 * lat_n) * 0.8
    if error_rate > 8:
        a += 0.3 * min(1, (error_rate - 8) / 25)
    # 内存泄漏检测：高内存独立贡献A
    if mem > 80:
        a += 0.4 * min(1.0, (mem - 80) / 15.0)
    # 边界修正：中等CPU不应触发高A
    health_a = 1.0 - min(1.0, max(0, error_rate) / 12.0) * 0.7 - max(0, min(1.0, (latency_ms - 200) / 1800.0)) * 0.3
    if 45 < cpu < 65 and error_rate < 2 and latency_ms < 200 and health_a > 0.6:
        boundary_factor = 1.0 - abs(cpu - 55) / 10.0
        a -= 0.30 * max(0, boundary_factor)
    a = max(-1, min(1, a))

    # D：乘法衰减
    # 健康感知 headroom（V4：降低健康系统的CPU惩罚）
    health = 1.0 - min(1.0, max(0, error_rate) / 12.0) * 0.7 - max(0, min(1.0, (latency_ms - 200) / 1800.0)) * 0.3
    cpu_weight = 0.6 - 0.2 * health  # [0.4, 0.6]
    mem_weight = 1.0 - cpu_weight
    headroom = 1 - (cpu / 100 * cpu_weight + mem / 100 * mem_weight)
    # 内存泄漏检测：高内存单独惩罚（V4）
    if mem > 75:
        mem_pressure = (mem - 75) / 25.0
        headroom -= 0.20 * mem_pressure
    err_decay = math.exp(-0.06 * error_rate)
    lat_decay = math.exp(-0.002 * max(0, latency_ms - 100))
    err_erosion = max(0, err_n)
    d = headroom * (1 - 0.7 * err_erosion) * err_decay * lat_decay
    # 无错误高负载健康奖励（V4）
    if error_rate < 2 and latency_ms < 500 and cpu > 50:
        d += 0.35 * health * min(1.0, (cpu - 50) / 30.0)
    # 健康感知缩放（V4：保留正值空间）
    d_scale = 2.0 - 0.6 * health  # [1.4, 2.0]
    d_offset = 1.0 - d_scale       # [-0.4, -1.0]
    d = d * d_scale + d_offset

    # V
    v = min(1, abs(cpu_n) * 0.5 + max(0, err_n) * 0.5)

    return EmotionState(p=p, a=a, d=d, v=v, f=fatigue, t=tension, c=comfort).clamp()


if __name__ == "__main__":
    import sys, io, time
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== ODE 情感动力系统测试 ===\n")

    ode = ODEDynamics()

    # 场景1：空闲 → 突发异常 → 恢复
    print("--- 场景：空闲 → 突发异常 → 恢复 ---")
    print("  观察：P骤降时A是否飙升（耦合效应）\n")

    scenarios = [
        ("空闲", 10, {"cpu": 20, "mem": 50, "err": 0, "lat": 50}),
        ("突发异常", 5, {"cpu": 30, "mem": 55, "err": 25, "lat": 800}),
        ("持续异常", 10, {"cpu": 35, "mem": 60, "err": 20, "lat": 600}),
        ("恢复", 15, {"cpu": 25, "mem": 52, "err": 1, "lat": 80}),
    ]

    step = 0
    for phase, steps, m in scenarios:
        for i in range(steps):
            step += 1
            target = compute_target(m["cpu"], m["mem"], m["err"], m["lat"])
            state = ode.step(target)

            # 标记关键变化
            tag = ""
            if step > 1 and abs(state.p - ode._prev_p) > 0.1:
                tag = " ← P剧变!"
            if state.a > 0.5:
                tag += " A飙升!"

            print(f"  [{step:03d}] {phase:8s} | "
                  f"P={state.p:+.3f} A={state.a:+.3f} D={state.d:+.3f} "
                  f"V={state.v:.3f} F={state.f:.3f} T={state.t:.3f} C={state.c:.3f}"
                  f"{tag}")
            time.sleep(0.02)

    # 场景2：长时间高负载（疲劳累积）
    print("\n--- 场景：长时间高负载（疲劳累积）---")
    print("  观察：F缓慢上升，D被侵蚀\n")

    ode.reset()
    for i in range(30):
        # 渐进式负载：从40%升到80%
        progress = i / 30
        cpu_val = 40 + 45 * progress
        err_val = 1 + 4 * progress
        target = compute_target(cpu_val, 70, err_val, 200, fatigue=0.5, tension=0.2, comfort=0.6)
        state = ode.step(target, dt=5.0)  # 5秒步长
        print(f"  [{i+1:03d}] | "
              f"P={state.p:+.3f} A={state.a:+.3f} D={state.d:+.3f} "
              f"F={state.f:.3f} T={state.t:.3f} C={state.c:.3f} "
              f"| 疲劳={'█' * int(state.f * 20)}{'.' * (20 - int(state.f * 20))}")
        time.sleep(0.02)
