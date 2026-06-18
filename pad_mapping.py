"""
PAD 映射核心计算 — 共享模块 (V5.0)

本模块从 pad_model.py 和 ode_dynamics.py 中提取的公共 PAD 计算逻辑。
解决两个文件中 ~200 行重复代码的维护风险。

所有 PAD 映射的数学公式、归一化、健康系数、矛盾检测、迟滞逻辑
都统一在此模块中。

提取自: pad_model.py metrics_to_pad() + ode_dynamics.py compute_target()
作者: 多AI协作 (DeepSeek + Qwen + GLM + 主模型整合)
版本: V5.0
"""
import math
from collections import deque


# === 公共归一化函数 ===

def tanh_norm(x: float, center: float, scale: float) -> float:
    """tanh 归一化：将任意值映射到 (-1, 1)"""
    return math.tanh((x - center) / max(scale, 0.01))


def sigmoid(x: float, midpoint: float, steepness: float) -> float:
    """标准 Sigmoid，溢出保护"""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if x < midpoint else 1.0


# === 公共健康系数 ===

def compute_health_score(error_rate: float, latency_ms: float) -> float:
    """
    系统健康度评分 [0, 1]
    1.0 = 完全健康 (无错误, 延迟正常)
    0.0 = 严重异常

    V5: err 权重 0.7, 让 4-5% 错误率系统不被误判为健康
    """
    err_health = 1.0 - min(1.0, max(0, error_rate) / 12.0)
    lat_health = 1.0 - max(0, min(1.0, (latency_ms - 200) / 1800.0))
    return err_health * 0.7 + lat_health * 0.3


# === 公共 PAD 原始值计算 ===

def compute_pad_raw(
    cpu: float, mem: float, error_rate: float, latency_ms: float,
    history: object | None = None,
) -> tuple[float, float, float]:
    """
    从系统指标计算 PAD 原始值（无矛盾检测、无迟滞、无 volatility）。

    这是 pad_model.metrics_to_pad() 和 ode_dynamics.compute_target() 共享的核心逻辑。

    参数:
        cpu: CPU 使用率 [0, 100]
        mem: 内存使用率 [0, 100]
        error_rate: 错误率 [0, 100]
        latency_ms: 延迟 (ms)
        history: MetricsHistory 实例（可选，用于变化率感知）

    返回:
        (p, a, d) 三个原始 PAD 值，范围 [-1, 1]
    """
    # 归一化
    err_n = tanh_norm(error_rate, center=2.0, scale=8.0)
    lat_n = tanh_norm(latency_ms, center=100, scale=400)
    cpu_n = tanh_norm(cpu, center=30, scale=35)
    mem_n = tanh_norm(mem, center=50, scale=30)

    # 变化率
    err_vel = history.err_velocity if history else 0.0
    lat_vel = history.lat_velocity if history else 0.0

    # ==================== PLEASURE (V5: 分段式情绪升级) ====================
    p = 1.0 - 0.45 * max(0, err_n) - 0.25 * max(0, lat_n)

    # 阶段 1: 警觉区 (6~12%)
    if 6 < error_rate <= 12:
        alert_factor = (error_rate - 6) / 6.0
        p -= 0.15 * alert_factor

    # 阶段 2: 担忧区 (12~20%)
    if 12 < error_rate <= 20:
        worry_factor = (error_rate - 12) / 8.0
        cpu_aggravation = 1.0 + 0.5 * max(0, cpu_n)
        p -= 0.25 * worry_factor * cpu_aggravation

    # 阶段 3: 愤怒区 (>20%)
    if error_rate > 20:
        rage_factor = min(1.0, (error_rate - 15) / 20.0) ** 0.7
        p -= 0.4 * rage_factor

    # 变化率惩罚
    if err_vel > 0.2:
        p -= 0.2 * min(1.0, err_vel)
    if lat_vel > 0.3:
        p -= 0.1 * min(1.0, lat_vel)

    # 交互项: 错误 + 高负载 = 过载
    if error_rate > 3 and cpu > 60:
        overload = min(1.0, (error_rate - 3) / 20 * (cpu - 60) / 30)
        p -= 0.25 * overload

    # 低负载高错误特殊处理
    if error_rate > 10 and cpu < 30:
        p -= 0.2 * min(1.0, (error_rate - 10) / 20)

    p = max(-1, min(1, p * 2 - 1))

    # ==================== AROUSAL (V5: 上调错误阈值 + 内存压力) ====================
    a_base = 0.6 * cpu_n + 0.2 * mem_n + 0.2 * lat_n

    a_velocity_boost = 0.0
    if err_vel > 0.2:
        a_velocity_boost = 0.5 * min(1.0, err_vel)
    if lat_vel > 0.3:
        a_velocity_boost += 0.2 * min(1.0, lat_vel)

    a_sustained = 0.0
    if error_rate > 5:
        a_sustained = 0.3 * min(1.0, (error_rate - 5) / 25)

    # V5: 内存泄漏检测 — 高内存独立贡献 A
    mem_pressure_a = 0.0
    if mem > 80:
        mem_pressure_a = 0.4 * min(1.0, (mem - 80) / 15.0)

    a = a_base + a_velocity_boost + a_sustained + mem_pressure_a

    # 边界修正: 中等 CPU 不应触发高 A
    health_for_a = compute_health_score(error_rate, latency_ms)
    if 45 < cpu < 65 and error_rate < 2 and latency_ms < 200 and health_for_a > 0.6:
        boundary_factor = 1.0 - abs(cpu - 55) / 10.0
        a -= 0.30 * max(0, boundary_factor)

    a = max(-1, min(1, a * 0.8))

    # ==================== DOMINANCE (V5: 健康感知 headroom) ====================
    health = compute_health_score(error_rate, latency_ms)

    cpu_weight = 0.6 - 0.2 * health  # [0.4, 0.6]
    mem_weight = 1.0 - cpu_weight
    headroom = 1.0 - (cpu / 100.0 * cpu_weight + mem / 100.0 * mem_weight)

    # 内存泄漏检测: 高内存单独惩罚
    if mem > 75:
        mem_pressure = (mem - 75) / 25.0
        headroom -= 0.20 * mem_pressure

    # 乘法衰减
    error_decay = math.exp(-0.06 * error_rate)
    latency_decay = math.exp(-0.002 * max(0, latency_ms - 100))

    # 侵蚀系数
    error_erosion = max(0, err_n)
    effective_headroom = headroom * (1.0 - 0.7 * error_erosion)

    # 交互惩罚
    interaction = 1.0
    if cpu > 60 and error_rate > 5:
        overload_severity = (cpu - 60) / 40.0
        error_severity = min(1.0, (error_rate - 5) / 25.0)
        interaction *= (1.0 - 0.4 * overload_severity * error_severity)

    # 变化率惩罚
    velocity_penalty = 0.0
    if err_vel > 0.3:
        velocity_penalty = 0.3 * min(1.0, err_vel)

    # 无错误高负载健康奖励 (V5)
    health_bonus = 0.0
    if error_rate < 2 and latency_ms < 500 and cpu > 50:
        health_bonus = 0.35 * health * min(1.0, (cpu - 50) / 30.0)

    # V5: 高内存独立惩罚
    mem_penalty_d = 0.0
    if mem > 80:
        mem_penalty_d = 0.25 * min(1.0, (mem - 80) / 15.0)

    d = (effective_headroom * error_decay * latency_decay * interaction
         - velocity_penalty + health_bonus - mem_penalty_d)

    # 健康感知缩放
    d_scale = 2.0 - 0.6 * health  # [1.4, 2.0]
    d_offset = 1.0 - d_scale
    d = max(-1, min(1, d * d_scale + d_offset))

    return p, a, d


# === 矛盾指标检测 ===

def detect_contradiction(
    cpu: float, error_rate: float, latency_ms: float,
    raw_d: float, raw_quadrant: str,
) -> tuple[bool, str, float]:
    """
    交叉验证: 检测指标间矛盾。
    返回: (is_contradiction, reason, d_boost)
    """
    health = compute_health_score(error_rate, latency_ms)
    cpu_severity = max(0, (cpu - 50) / 50.0)

    # 矛盾1: 高CPU + 零错误 + 正常延迟 → 不应警戒
    if cpu > 75 and error_rate < 1 and latency_ms < 300:
        if raw_quadrant in ("alert", "calm_sad"):
            boost = 0.3 + 0.3 * cpu_severity
            return True, f"高CPU({cpu:.0f}%)+健康运行(错误{error_rate:.1f}%,延迟{latency_ms:.0f}ms)", boost

    # 矛盾2: 中等CPU + 极低错误 → D不应为负
    if 45 < cpu <= 75 and error_rate < 1 and latency_ms < 200:
        if raw_d < 0 and raw_quadrant == "alert":
            boost = 0.15 + 0.1 * ((cpu - 45) / 30.0)
            return True, f"中等CPU({cpu:.0f}%)+无错误", boost

    # 矛盾3: 低CPU + 高延迟 → 应为低落, 非警戒
    if cpu < 25 and latency_ms > 2000:
        if raw_quadrant == "alert":
            return True, f"低CPU({cpu:.0f}%)+高延迟({latency_ms:.0f}ms)=依赖阻塞", -0.2

    # 矛盾4: 低CPU + 高错误 → 系统问题非负载
    if cpu < 30 and error_rate > 10:
        if raw_quadrant in ("alert", "excited_angry"):
            return True, f"低CPU({cpu:.0f}%)+高错误({error_rate:.1f}%)=应用层问题", -0.15

    return False, "", 0.0


# === 边界缓冲区 (迟滞) ===

def apply_hysteresis(
    pad_state: object, prev_quadrant: str,
    cpu: float, error_rate: float, latency_ms: float,
) -> object:
    """
    边界缓冲区: 防止在阈值附近震荡。

    策略:
    - 进入"警戒": 需要更确定的证据 (收紧)
    - 退出"警戒": 需要更确定的好转 (收紧)
    - 用不对称阈值创造"死区"
    """
    ALERT_IN_BUFFER = 0.08
    ALERT_OUT_BUFFER = 0.12
    health = compute_health_score(error_rate, latency_ms)

    # 导入延迟，避免循环引用
    from pad_model import PADState

    raw_q = pad_state.raw_quadrant

    # 从非警戒进入警戒
    if raw_q == "alert" and prev_quadrant != "alert":
        if health > 0.6 and pad_state.d > -0.15:
            return PADState(pad_state.p, max(0.05, pad_state.a), max(0.01, pad_state.d), pad_state.volatility).clamp()
        if pad_state.d > -ALERT_IN_BUFFER:
            if pad_state.p > 0 and pad_state.a > 0:
                return PADState(pad_state.p, pad_state.a, max(0.01, pad_state.d), pad_state.volatility).clamp()

    # 从警戒退出到其他状态
    if raw_q != "alert" and prev_quadrant == "alert":
        if raw_q in ("calm_happy", "excited_happy") and pad_state.d < ALERT_OUT_BUFFER:
            if health < 0.7:
                return PADState(pad_state.p, max(0.05, pad_state.a), pad_state.d, pad_state.volatility).clamp()

    # 低落边界保护
    if raw_q == "alert" and cpu < 25 and latency_ms > 1500:
        return PADState(pad_state.p, pad_state.a, min(-0.05, pad_state.d), pad_state.volatility).clamp()

    return pad_state


# === 波动性计算 ===

def calc_volatility(values: deque) -> float:
    """计算变异系数 (归一化到 [0, 1])"""
    data = list(values)
    mean = sum(data) / len(data)
    if mean == 0:
        return 0.0
    var = sum((x - mean) ** 2 for x in data) / len(data)
    return min(1.0, math.sqrt(var) / max(abs(mean), 1.0) * 3)
