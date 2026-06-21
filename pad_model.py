"""
PAD 情绪模型 V4.1 - 四方优化版
Qwen + DeepSeek + GLM + 我的方案融合

核心改进:
1. 分段式 P 映射(Qwen+GLM 共识):警觉→担忧→愤怒的阶段跃迁
2. D 值乘法衰减(Qwen+DeepSeek+GLM 三方共识):exp(-0.06*err)
3. 变化率感知(DeepSeek+GLM 共识):错误/延迟趋势驱动情绪
4. 低负载高错误特殊处理(DeepSeek+GLM 共识):额外不安惩罚
5. 软分类概率(GLM):softmax + 温度参数
"""
from dataclasses import dataclass
from enum import Enum
from collections import deque
import math


class PADQuadrant(Enum):
    STABLE_GOOD = "稳态良好"
    HIGH_ENERGY_GOOD = "高能良好"
    STABLE_BAD = "低落"
    HIGH_ENERGY_BAD = "过载"
    NEUTRAL = "中性"
    ALERT = "警戒"


QUADRANT_TO_STATE = {
    "calm_happy": PADQuadrant.STABLE_GOOD,
    "excited_happy": PADQuadrant.HIGH_ENERGY_GOOD,
    "calm_sad": PADQuadrant.STABLE_BAD,
    "excited_angry": PADQuadrant.HIGH_ENERGY_BAD,
    "relaxed": PADQuadrant.STABLE_GOOD,
    "alert": PADQuadrant.ALERT,
    "depressed": PADQuadrant.STABLE_BAD,
    "panic": PADQuadrant.HIGH_ENERGY_BAD,
}


@dataclass
class PADState:
    p: float  # pleasure [-1, 1]
    a: float  # arousal [-1, 1]
    d: float  # dominance [-1, 1]
    volatility: float = 0.0

    @property
    def raw_quadrant(self) -> str:
        if self.p >= 0 and self.a <= 0 and self.d >= 0:
            return "calm_happy"
        elif self.p >= 0 and self.a > 0 and self.d >= 0:
            return "excited_happy"
        elif self.p < 0 and self.a <= 0 and self.d >= 0:
            return "calm_sad"
        elif self.p < 0 and self.a > 0 and self.d < 0:
            return "excited_angry"
        elif self.p >= 0 and self.a <= 0 and self.d < 0:
            return "relaxed"
        elif self.p >= 0 and self.a > 0 and self.d < 0:
            return "alert"
        elif self.p < 0 and self.a <= 0 and self.d < 0:
            return "depressed"
        else:
            return "panic"

    @property
    def quadrant(self) -> PADQuadrant:
        return QUADRANT_TO_STATE[self.raw_quadrant]

    @property
    def emotion_probs(self) -> dict[str, float]:
        """软分类概率分布(GLM 建议:softmax + 温度)"""
        centers = {
            "稳态良好": (0.5, -0.3, 0.5),
            "高能良好": (0.3, 0.5, 0.3),
            "低落": (-0.5, -0.3, -0.3),
            "过载": (-0.5, 0.5, -0.5),
            "中性": (0.0, 0.0, 0.0),
            "警戒": (0.1, 0.4, -0.1),
        }
        # 加权距离(Qwen+GLM:P权重最高)
        w_p, w_a, w_d = 0.45, 0.30, 0.25
        dists = {}
        for name, (cp, ca, cd) in centers.items():
            d = math.sqrt(
                w_p * (self.p - cp)**2 +
                w_a * (self.a - ca)**2 +
                w_d * (self.d - cd)**2
            )
            dists[name] = d

        # Softmax with temperature(GLM 建议)
        temp = 0.3  # 越小越"果断"
        logits = {k: -v / temp for k, v in dists.items()}
        max_l = max(logits.values())
        exps = {k: math.exp(v - max_l) for k, v in logits.items()}
        total = sum(exps.values())
        probs = {k: round(v / total, 3) for k, v in exps.items()}
        return dict(sorted(probs.items(), key=lambda x: -x[1]))

    def clamp(self) -> 'PADState':
        return PADState(
            max(-1, min(1, self.p)),
            max(-1, min(1, self.a)),
            max(-1, min(1, self.d)),
            max(0, min(1, self.volatility)),
        )


class MetricsHistory:
    """指标历史窗口(DeepSeek+GLM:变化率感知)"""

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.cpu_hist = deque(maxlen=window_size)
        self.err_hist = deque(maxlen=window_size)
        self.lat_hist = deque(maxlen=window_size)

    def update(self, cpu: float, error_rate: float, latency_ms: float):
        self.cpu_hist.append(cpu)
        self.err_hist.append(error_rate)
        self.lat_hist.append(latency_ms)

    def velocity(self, values: deque) -> float:
        """变化率(DeepSeek:最近 N 步平均 delta,tanh 归一化)"""
        if len(values) < 2:
            return 0.0
        data = list(values)
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        avg_delta = sum(deltas) / len(deltas)
        return math.tanh(avg_delta / 5.0)

    def trend(self, values: deque) -> float:
        """趋势(GLM:错误率变化斜率)"""
        if len(values) < 3:
            return 0.0
        data = list(values)
        n = len(data)
        mid = n // 2
        old_avg = sum(data[:mid]) / mid
        new_avg = sum(data[mid:]) / (n - mid)
        if old_avg == 0:
            return 0.0
        return (new_avg - old_avg) / max(old_avg, 1.0)

    @property
    def err_velocity(self) -> float:
        return self.velocity(self.err_hist)

    @property
    def lat_velocity(self) -> float:
        return self.velocity(self.lat_hist)

    @property
    def err_trend(self) -> float:
        return self.trend(self.err_hist)


def _tanh_norm(x: float, center: float, scale: float) -> float:
    return math.tanh((x - center) / max(scale, 0.01))


def _sigmoid(x: float, midpoint: float, steepness: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if x < midpoint else 1.0


def _compute_health_score(error_rate: float, latency_ms: float) -> float:
    """
    系统健康度评分 [0, 1]
    1.0 = 完全健康(无错误,延迟正常)
    0.0 = 严重异常

    V4.1: err 权重提高到 0.7,让 4-5% 错误率系统不被误判为健康
    """
    err_health = 1.0 - min(1.0, max(0, error_rate) / 12.0)
    lat_health = 1.0 - max(0, min(1.0, (latency_ms - 200) / 1800.0))
    return err_health * 0.7 + lat_health * 0.3


def _detect_contradiction(
    cpu: float, error_rate: float, latency_ms: float,
    raw_d: float, raw_quadrant: str,
) -> tuple[bool, str, float]:
    """
    交叉验证:检测指标间矛盾
    返回: (is_contradiction, reason, d_boost)
    """
    health = _compute_health_score(error_rate, latency_ms)
    cpu_severity = max(0, (cpu - 50) / 50.0)  # CPU>50% 开始有严重度

    # === 矛盾1:高CPU + 零错误 + 正常延迟 → 不应警戒 ===
    if cpu > 75 and error_rate < 1 and latency_ms < 300:
        if raw_quadrant in ("alert", "calm_sad"):
            boost = 0.3 + 0.3 * cpu_severity
            return True, f"高CPU({cpu:.0f}%)+健康运行(错误{error_rate:.1f}%,延迟{latency_ms:.0f}ms)", boost

    # === 矛盾2:中等CPU + 极低错误 → D不应为负 ===
    if 45 < cpu <= 75 and error_rate < 1 and latency_ms < 200:
        if raw_d < 0 and raw_quadrant == "alert":
            boost = 0.15 + 0.1 * ((cpu - 45) / 30.0)
            return True, f"中等CPU({cpu:.0f}%)+无错误", boost

    # === 矛盾3:低CPU + 高延迟 → 应为低落,非警戒 ===
    if cpu < 25 and latency_ms > 2000:
        if raw_quadrant == "alert":
            return True, f"低CPU({cpu:.0f}%)+高延迟({latency_ms:.0f}ms)=依赖阻塞", -0.2

    # === 矛盾4:低CPU + 高错误 → 系统问题非负载 ===
    if cpu < 30 and error_rate > 10:
        if raw_quadrant in ("alert", "excited_angry"):
            return True, f"低CPU({cpu:.0f}%)+高错误({error_rate:.1f}%)=应用层问题", -0.15

    return False, "", 0.0


def _apply_hysteresis(
    pad: PADState, prev_quadrant: str,
    cpu: float, error_rate: float, latency_ms: float,
) -> PADState:
    """
    边界缓冲区:防止在阈值附近震荡

    策略:
    - 进入"警戒":需要更确定的证据(收紧)
    - 退出"警戒":需要更确定的好转(收紧)
    - 用不对称阈值创造"死区"
    """
    ALERT_IN_BUFFER = 0.08   # 进入警戒的额外门槛
    ALERT_OUT_BUFFER = 0.12  # 退出警戒的额外门槛
    health = _compute_health_score(error_rate, latency_ms)

    # 当前原始象限
    raw_q = pad.raw_quadrant

    # === 从非警戒进入警戒 ===
    if raw_q == "alert" and prev_quadrant != "alert":
        # 健康系统不应因边界微小差异进入警戒
        if health > 0.6 and pad.d > -0.15:
            # D 接近0且系统健康 → 修正为高能良好
            return PADState(pad.p, max(0.05, pad.a), max(0.01, pad.d), pad.volatility).clamp()
        # 非健康系统:需要 D 明确低于缓冲区
        if pad.d > -ALERT_IN_BUFFER:
            if pad.p > 0 and pad.a > 0:
                return PADState(pad.p, pad.a, max(0.01, pad.d), pad.volatility).clamp()

    # === 从警戒退出到其他状态 ===
    if raw_q != "alert" and prev_quadrant == "alert":
        # 退出时也需要确认,防止在警戒边界反复跳
        if raw_q in ("calm_happy", "excited_happy") and pad.d < ALERT_OUT_BUFFER:
            if health < 0.7:
                return PADState(pad.p, max(0.05, pad.a), pad.d, pad.volatility).clamp()

    # === 低落边界保护 ===
    # 低CPU+高延迟应判"低落",不应误入"警戒"
    if raw_q == "alert" and cpu < 25 and latency_ms > 1500:
        return PADState(pad.p, pad.a, min(-0.05, pad.d), pad.volatility).clamp()

    return pad


def metrics_to_pad(
    cpu: float, mem: float, error_rate: float, latency_ms: float,
    history: MetricsHistory | None = None,
    prev_quadrant: str | None = None,
) -> PADState:
    """
    V4 PAD 映射 - 边界优化版

    V3 基础 + V4 改进:
    1. 健康感知 headroom(解决边界误报核心)
    2. 无错误高负载豁免(D值修正)
    3. 矛盾指标交叉验证
    4. 边界缓冲区(hysteresis)
    """
    # 校准说明:
    # - cpu center=30 表示 30% 是"正常"基线,不是 40%
    # - scale 放大到 35 让 tanh 在 0~80% 范围内线性度更好
    # - mem center=50 表示 50% 是正常基线
    err_n = _tanh_norm(error_rate, center=2.0, scale=8.0)
    lat_n = _tanh_norm(latency_ms, center=100, scale=400)
    cpu_n = _tanh_norm(cpu, center=30, scale=35)
    mem_n = _tanh_norm(mem, center=50, scale=30)

    # 变化率(DeepSeek 核心建议)
    err_vel = history.err_velocity if history else 0.0
    lat_vel = history.lat_velocity if history else 0.0

    # ==================== PLEASURE ====================
    # 基础 P
    p = 1.0 - 0.45 * max(0, err_n) - 0.25 * max(0, lat_n)

    # 分段式情绪升级(V4.1: 上调阈值,减少边界误报)
    # 阶段 1:警觉区 (6~12%) - 原3%太激进,5%就触发警觉导致大量误报
    if 6 < error_rate <= 12:
        alert_factor = (error_rate - 6) / 6.0
        p -= 0.15 * alert_factor

    # 阶段 2:担忧区 (12~20%)
    if 12 < error_rate <= 20:
        worry_factor = (error_rate - 12) / 8.0
        cpu_aggravation = 1.0 + 0.5 * max(0, cpu_n)
        p -= 0.25 * worry_factor * cpu_aggravation

    # 阶段 3:愤怒区 (>20%)
    if error_rate > 20:
        rage_factor = min(1.0, (error_rate - 15) / 20.0) ** 0.7
        p -= 0.4 * rage_factor

    # 变化率惩罚(DeepSeek:错误飙升时额外恶化 P)
    if err_vel > 0.2:
        p -= 0.2 * min(1.0, err_vel)
    if lat_vel > 0.3:
        p -= 0.1 * min(1.0, lat_vel)

    # 交互项(错误+高负载=过载)
    if error_rate > 3 and cpu > 60:
        overload = min(1.0, (error_rate - 3) / 20 * (cpu - 60) / 30)
        p -= 0.25 * overload

    # 低负载高错误特殊处理(DeepSeek+GLM 共识)
    if error_rate > 10 and cpu < 30:
        p -= 0.2 * min(1.0, (error_rate - 10) / 20)

    p = max(-1, min(1, p * 2 - 1))

    # ==================== AROUSAL ====================
    # 基础 A:负载驱动
    a_base = 0.6 * cpu_n + 0.2 * mem_n + 0.2 * lat_n

    # 变化率驱动(DeepSeek:错误飙升 → A 暴涨)
    a_velocity_boost = 0.0
    if err_vel > 0.2:
        a_velocity_boost = 0.5 * min(1.0, err_vel)
    if lat_vel > 0.3:
        a_velocity_boost += 0.2 * min(1.0, lat_vel)

    # 持续高错误 → 持续高 A
    a_sustained = 0.0
    if error_rate > 5:
        a_sustained = 0.3 * min(1.0, (error_rate - 5) / 25)

    # V4.1: 内存泄漏检测 - 高内存独立贡献A(修复漏报核心)
    mem_pressure_a = 0.0
    if mem > 80:
        mem_pressure_a = 0.4 * min(1.0, (mem - 80) / 15.0)  # 80%开始,95%满

    a = a_base + a_velocity_boost + a_sustained + mem_pressure_a

    # --- 边界修正:中等CPU不应触发高A ---
    health_for_a = _compute_health_score(error_rate, latency_ms)
    if 45 < cpu < 65 and error_rate < 2 and latency_ms < 200 and health_for_a > 0.6:
        boundary_factor = 1.0 - abs(cpu - 55) / 10.0
        a -= 0.30 * max(0, boundary_factor)

    a = max(-1, min(1, a * 0.8))

    # ==================== DOMINANCE (V4 核心改进) ====================
    # --- 1. 健康感知 headroom ---
    # 原始: 1 - (cpu*0.6 + mem*0.4) → CPU>66% 就变负,太激进
    # V4: 降低 CPU 权重,引入健康度调节
    health = _compute_health_score(error_rate, latency_ms)

    # 健康系统:CPU惩罚从 0.6 降到 0.4
    # 不健康系统:保持 0.6(不放松惩罚)
    cpu_weight = 0.6 - 0.2 * health  # [0.4, 0.6]
    mem_weight = 1.0 - cpu_weight     # [0.4, 0.6]
    headroom = 1.0 - (cpu / 100.0 * cpu_weight + mem / 100.0 * mem_weight)

    # 内存泄漏检测:高内存单独惩罚(不依赖CPU)
    if mem > 75:
        mem_pressure = (mem - 75) / 25.0  # [0, 1] for mem 75~100
        headroom -= 0.20 * mem_pressure   # 额外惩罚,确保D为负

    # --- 2. 乘法衰减(保持V3) ---
    error_decay = math.exp(-0.06 * error_rate)
    latency_decay = math.exp(-0.002 * max(0, latency_ms - 100))

    # --- 3. 侵蚀系数(保持V3) ---
    error_erosion = max(0, err_n)
    effective_headroom = headroom * (1.0 - 0.7 * error_erosion)

    # --- 4. 交互惩罚(保持V3) ---
    interaction = 1.0
    if cpu > 60 and error_rate > 5:
        overload_severity = (cpu - 60) / 40.0
        error_severity = min(1.0, (error_rate - 5) / 25.0)
        interaction *= (1.0 - 0.4 * overload_severity * error_severity)

    # --- 5. 变化率惩罚(保持V3) ---
    velocity_penalty = 0.0
    if err_vel > 0.3:
        velocity_penalty = 0.3 * min(1.0, err_vel)

    # --- 6. 无错误高负载健康奖励 (V4 核心修正) ---
    health_bonus = 0.0
    if error_rate < 2 and latency_ms < 500 and cpu > 50:
        health_bonus = 0.35 * health * min(1.0, (cpu - 50) / 30.0)

    # --- 6b. V4.1: 高内存独立惩罚（修复内存泄漏漏报） ---
    mem_penalty_d = 0.0
    if mem > 80:
        mem_penalty_d = 0.25 * min(1.0, (mem - 80) / 15.0)  # 80%开始，95%满

    d = effective_headroom * error_decay * latency_decay * interaction - velocity_penalty + health_bonus - mem_penalty_d
    # 健康感知缩放:健康系统保留更多正值空间
    # 原始 d*2-1 对 headroom=0.3 映射到 -0.4,太激进
    # V4: 健康系统用 d*1.4-0.4(保留正值),不健康保持 d*2-1
    d_scale = 2.0 - 0.6 * health  # [1.4, 2.0]
    d_offset = 1.0 - d_scale       # [-0.4, -1.0]
    d = max(-1, min(1, d * d_scale + d_offset))

    # --- 7. 矛盾指标交叉验证 (V4 新增) ---
    # 先算原始 PAD 确定象限,再做交叉验证修正
    raw_pad = PADState(p, a, d, 0.0).clamp()
    is_contra, contra_reason, d_boost = _detect_contradiction(
        cpu, error_rate, latency_ms, d, raw_pad.raw_quadrant
    )
    if is_contra:
        d = max(-1, min(1, d + d_boost))

    # ==================== VOLATILITY ====================
    vol = 0.0
    if history and len(history.cpu_hist) >= 3:
        cpu_vol = _calc_volatility(history.cpu_hist)
        err_vol = _calc_volatility(history.err_hist)
        vol = (cpu_vol + err_vol) / 2

    final_pad = PADState(p, a, d, vol).clamp()

    # --- 8. 边界缓冲区 hysteresis (V4 新增) ---
    if prev_quadrant is not None:
        final_pad = _apply_hysteresis(final_pad, prev_quadrant, cpu, error_rate, latency_ms)

    return final_pad


def _calc_volatility(values: deque) -> float:
    """计算变异系数(归一化到 [0,1])"""
    data = list(values)
    mean = sum(data) / len(data)
    if mean == 0:
        return 0.0
    var = sum((x - mean) ** 2 for x in data) / len(data)
    return min(1.0, math.sqrt(var) / max(abs(mean), 1.0) * 3)


# === 异常检测层 ===

@dataclass
class AnomalyAlert:
    is_anomaly: bool
    reason: str
    severity: str
    override_pad: PADState | None = None


def detect_anomaly(
    cpu: float, mem: float, error_rate: float, latency_ms: float,
    history: MetricsHistory | None = None,
) -> AnomalyAlert:
    reasons = []

    if error_rate > 30:
        reasons.append(f"错误率 {error_rate:.1f}% 超过 30% 阈值")
    elif error_rate > 15 and history and history.err_trend > 0.3:
        reasons.append(f"错误率 {error_rate:.1f}% 且持续上升")

    if latency_ms > 3000:
        reasons.append(f"延迟 {latency_ms:.0f}ms 超过 3s 阈值")

    if cpu > 95 and mem > 90:
        reasons.append(f"CPU {cpu:.0f}% + 内存 {mem:.0f}% 双高")

    if error_rate > 10 and cpu > 80:
        reasons.append(f"错误率 {error_rate:.1f}% + CPU {cpu:.0f}% 双高")

    if not reasons:
        return AnomalyAlert(is_anomaly=False, reason="", severity="")

    severity = "critical" if any("30%" in r or "3000" in r or "双高" in r for r in reasons) else "warning"
    reason_str = ";".join(reasons)

    override = None
    if severity == "critical":
        override = PADState(p=-0.7, a=0.8, d=-0.6, volatility=0.9).clamp()

    return AnomalyAlert(is_anomaly=True, reason=reason_str, severity=severity, override_pad=override)
