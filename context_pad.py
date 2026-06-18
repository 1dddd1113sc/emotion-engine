"""
上下文感知 PAD 组合器 — 替代 metrics_to_pad()

核心思想：同一个 load 信号，在不同上下文下产生不同的情绪。
- clean:    load↑ → P↑ A↑ D↑  (忙碌但健康 = 自信/高效)
- degraded: load↑ → P  A↑ D↓  (勉强支撑 = 紧张)
- err:      load↑ → P↓ A↑ D↓  (过载 = 焦虑/愤怒)
"""
import math
from dataclasses import dataclass
from semantic_signals import SemanticSignals, extract_signals


@dataclass
class PADOutput:
    """PAD 组合器输出"""
    p: float        # Pleasure [-1, 1]
    a: float        # Arousal [-1, 1]
    d: float        # Dominance [-1, 1]
    v: float = 0.0  # Volatility [0, 1]
    # 传递给 ODE 的附加信息
    fatigue: float = 0.0
    tension: float = 0.0
    comfort: float = 1.0

    def clamp(self):
        self.p = max(-1, min(1, self.p))
        self.a = max(-1, min(1, self.a))
        self.d = max(-1, min(1, self.d))
        self.v = max(0, min(1, self.v))
        self.fatigue = max(0, min(1, self.fatigue))
        self.tension = max(0, min(1, self.tension))
        self.comfort = max(0, min(1, self.comfort))
        return self


def compose_pad(sig: SemanticSignals) -> PADOutput:
    """
    上下文感知 PAD 组合。

    输入: SemanticSignals（4 个正交信号 + 上下文标签）
    输出: PADOutput（P/A/D + 体感）
    """
    err = sig.error
    load = sig.load
    lat = sig.latency
    hlt = sig.health
    ctx = sig.context

    # ═══════════════════════════════════════
    # PLEASURE (P)
    # ═══════════════════════════════════════
    # 基线：健康时 P 高位（校准参数 p_base_k=0.8）
    p_base = 0.68 * hlt + 0.08

    if ctx == 'clean':
        # 健康运行：错误惩罚小，负载是正面的（忙碌=有事做）
        p = p_base - 0.15 * err - 0.05 * lat + 0.05 * (load - 0.5)
    elif ctx == 'degraded':
        # 性能下降：中等惩罚
        p = p_base - 0.4 * err - 0.25 * lat - 0.1 * max(0, load - 0.5)
    else:  # err
        # 严重错误：强惩罚
        p = p_base - 0.7 * err - 0.3 * lat - 0.2 * max(0, load - 0.3)

    # ═══════════════════════════════════════
    # AROUSAL (A)
    # ═══════════════════════════════════════
    # 基线：负载驱动
    a_base = 0.6 * load + 0.2 * lat + 0.1 * err

    if ctx == 'clean':
        # 健康忙碌：适度唤醒，不过度
        a = a_base + 0.1 * err
        # 边界修正：中等负载+健康 → 不应高唤醒
        if 0.3 < load < 0.6 and hlt > 0.7:
            a -= 0.2
    elif ctx == 'degraded':
        # 性能下降：唤醒升高
        a = a_base + 0.3 * err + 0.2 * (1 - hlt)
    else:  # err
        # 严重错误：高唤醒
        a = a_base + 0.5 * err + 0.3 * (1 - hlt)

    # ═══════════════════════════════════════
    # DOMINANCE (D)
    # ═══════════════════════════════════════
    # 基线：健康余量
    d_base = 0.7 * hlt - 0.2

    if ctx == 'clean':
        # 健康运行：高控制感
        d = d_base + 0.1 * (1 - load) - 0.1 * err
        # 健康高负载奖励：忙但不乱 → 自信
        if load > 0.5 and hlt > 0.7 and err < 0.05:
            d += 0.2 * (load - 0.5)
    elif ctx == 'degraded':
        # 性能下降：控制感降低
        d = d_base - 0.2 * load - 0.3 * (1 - hlt) - 0.2 * lat
    else:  # err
        # 严重错误：控制感崩塌
        d = d_base - 0.5 * err - 0.4 * load - 0.2 * lat

    # ═══════════════════════════════════════
    # VOLATILITY (V)
    # ═══════════════════════════════════════
    v = min(1, err * 0.5 + abs(load - 0.5) * 0.3 + lat * 0.2)

    # ═══════════════════════════════════════
    # 体感信号（传递给 ODE）
    # ═══════════════════════════════════════
    # Fatigue：负载累积效应
    fatigue = load * 0.6 + (1 - hlt) * 0.3 + err * 0.1

    # Tension：信号矛盾程度
    # 高错误+低负载 = 矛盾（软件bug）→ 高紧绷
    # 高错误+高负载 = 一致（过载）→ 中紧绷
    if err > 0.1 and load < 0.3:
        tension = 0.5 + 0.5 * err  # 矛盾：低负载高错误
    elif err > 0.1 and load > 0.6:
        tension = 0.3 + 0.4 * err  # 一致但严重
    else:
        tension = err * 0.3 + lat * 0.2 + max(0, load - 0.7) * 0.5

    # Comfort：资源余量
    comfort = hlt * 0.6 + (1 - load) * 0.2 + (1 - lat) * 0.2

    return PADOutput(p=p, a=a, d=d, v=v, fatigue=fatigue, tension=tension, comfort=comfort).clamp()


# ═══════════════════════════════════════
# 便捷函数：一步到位
# ═══════════════════════════════════════

def compute_pad_context_aware(
    cpu: float, mem: float, error_rate: float = 0.0, latency_ms: float = 50.0,
    swap_percent: float = 0.0, disk_usage: float = 0.0,
    err_velocity: float = 0.0, lat_velocity: float = 0.0,
) -> PADOutput:
    """
    一步完成：原始指标 → 语义信号 → 上下文分类 → PAD 输出。

    替代原来的 metrics_to_pad()。
    """
    sig = extract_signals(
        cpu=cpu, mem=mem, error_rate=error_rate, latency_ms=latency_ms,
        swap_percent=swap_percent, disk_usage=disk_usage,
        err_velocity=err_velocity, lat_velocity=lat_velocity,
    )
    return compose_pad(sig)
