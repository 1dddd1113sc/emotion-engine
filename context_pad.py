"""
上下文感知 PAD 组合器 — 替代 metrics_to_pad()

核心思想：同一个 load 信号，在不同上下文下产生不同的情绪。
- clean:    load↑ → P↑ A↑ D↑  (忙碌但健康 = 自信/高效)
- degraded: load↑ → P  A↑ D↓  (勉强支撑 = 紧张)
- err:      load↑ → P↓ A↑ D↓  (过载 = 焦虑/愤怒)
"""
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING
from semantic_signals import SemanticSignals, extract_signals

if TYPE_CHECKING:
    from body_sense import BodySense


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


def compose_pad(sig: SemanticSignals, body: 'BodySense | None' = None) -> PADOutput:
    """
    上下文感知 PAD 组合。

    输入:
        SemanticSignals（4 个正交信号 + 上下文标签）
        BodySense（可选，来自 BodySenseManager 的 EMA 体感状态）
    输出: PADOutput（P/A/D + 体感）

    当 body 提供时，使用 BodySenseManager 的累积体感值；
    否则回退到瞬时计算（兼容旧调用方式）。
    """
    err = sig.error
    load = sig.load
    lat = sig.latency
    hlt = sig.health
    ctx = sig.context

    # ═══════════════════════════════════════
    # PLEASURE (P)
    # ═══════════════════════════════════════
    # V6.3: 重新设计 P 基线为 0.0 中性，让负载/疲劳产生双向影响
    # idle+健康 → P>0, 高负载+疲劳 → P<0
    p = 0.0  # 中性基线
    
    # 健康信号 → +P（系统健康=愉悦）
    p += (hlt - 0.5) * 1.2  # hlt=0.9→+0.48, hlt=0.5→0
    
    # 低负载 → +P（空闲=轻松）
    if load < 0.3:
        p += (0.3 - load) * 1.5  # load=0.1→+0.3
    
    # 高负载 → -P（压力大=不舒服）
    if load > 0.5:
        p -= (load - 0.5) * 1.0  # load=1.0→-0.5
    
    # 疲劳/紧绷 → -P（累了=不愉悦）
    if body is not None:
        p -= body.fatigue * 0.6  # fatigue=0.6→-0.36
        p -= body.tension * 0.3
    
    # 错误惩罚 — 低负载时高错误更严重（系统死掉了，什么都没做却有错）
    if load > 0.3:
        p -= err * 0.8  # 繁忙时错误=正常代价
    else:
        p -= err * 1.2  # 空闲时错误=系统坏了，更严重
    
    # 延迟惩罚
    if lat > 0.2:
        p -= (lat - 0.2) * 1.0

    # ═══════════════════════════════════════
    # AROUSAL (A)
    # ═══════════════════════════════════════
    # V6.4: 负载映射到[-1,1]，idle→负A, 高负载→正A
    a = (load - 0.3) * 1.5  # load=0.1→-0.3, load=0.5→+0.3, load=1.0→+1.05
    
    # 体感增强
    if body is not None:
        a += body.tension * 0.4
    
    # 错误/延迟对唤醒的影响取决于负载状态：
    # - 高负载 + 高错误 → 系统在挣扎，A↑ (愤怒/恐惧)
    # - 低负载 + 高错误 → 系统已放弃，A↓ (悲伤/无助)
    if load > 0.3:
        # 系统活跃：错误增加唤醒
        a += err * 0.5 + lat * 0.3
    else:
        # 系统低活跃：错误降低唤醒（系统放弃抵抗）
        a += err * (-0.3) + lat * (-0.2)

    # ═══════════════════════════════════════
    # DOMINANCE (D)
    # ═══════════════════════════════════════
    # V6.3: 简化 D 计算，高负载/高疲劳 → 失去控制感
    d = 0.3  # 中性基线
    
    # 健康 → +D（健康=有控制力）
    d += (hlt - 0.5) * 0.8
    
    # 低负载 → +D（空闲=掌控）
    if load < 0.3:
        d += (0.3 - load) * 0.8
    
    # 高负载 → -D（太忙=失控）
    if load > 0.5:
        d -= (load - 0.5) * 0.8
    
    # 疲劳 → -D（累了=控制力下降）
    if body is not None:
        d -= body.fatigue * 0.5
    
    # 错误 → -D
    d -= err * 0.6

    # ═══════════════════════════════════════
    # VOLATILITY (V)
    # ═══════════════════════════════════════
    v = min(1, err * 0.5 + abs(load - 0.5) * 0.3 + lat * 0.2)

    # ═══════════════════════════════════════
    # 体感信号（传递给 ODE）
    # ═══════════════════════════════════════
    if body is not None:
        # 优先使用 BodySenseManager 的 EMA 累积值
        fatigue = body.fatigue
        tension = body.tension
        comfort = body.comfort
    else:
        # 回退：瞬时计算（无记忆，兼容旧调用方式）
        fatigue = load * 0.6 + (1 - hlt) * 0.3 + err * 0.1
        if err > 0.1 and load < 0.3:
            tension = 0.5 + 0.5 * err
        elif err > 0.1 and load > 0.6:
            tension = 0.3 + 0.4 * err
        else:
            tension = err * 0.3 + lat * 0.2 + max(0, load - 0.7) * 0.5
        comfort = hlt * 0.6 + (1 - load) * 0.2 + (1 - lat) * 0.2

    return PADOutput(p=p, a=a, d=d, v=v, fatigue=fatigue, tension=tension, comfort=comfort).clamp()


# ═══════════════════════════════════════
# 便捷函数：一步到位
# ═══════════════════════════════════════

def compute_pad_context_aware(
    cpu: float, mem: float, error_rate: float = 0.0, latency_ms: float = 50.0,
    swap_percent: float = 0.0, disk_usage: float = 0.0,
    err_velocity: float = 0.0, lat_velocity: float = 0.0,
    body: 'BodySense | None' = None,
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
    return compose_pad(sig, body=body)
