"""
语义信号层 — 从原始指标提取 4 个正交情绪信号

信号设计原则：
- error: 错误严重度（业务层直接伤害）
- load: 综合负载（系统忙碌程度）
- latency: 延迟压力（用户体验恶化）
- health: 健康余量（系统承受能力）

每个信号输出 [0, 1]，语义独立，不重叠。
"""
import math


def tanh_norm(x: float, center: float, scale: float) -> float:
    return math.tanh((x - center) / max(scale, 0.01))


class SemanticSignals:
    """4 个正交语义信号 + 上下文标签"""

    __slots__ = ('error', 'load', 'latency', 'health', 'context')

    def __init__(self, error: float, load: float, latency: float, health: float, context: str):
        self.error = error      # [0, 1] 错误严重度
        self.load = load        # [0, 1] 综合负载
        self.latency = latency  # [0, 1] 延迟压力
        self.health = health    # [0, 1] 健康余量（1=完全健康）
        self.context = context  # 'clean' | 'degraded' | 'err'

    def __repr__(self):
        return (f"Sig(err={self.error:.2f} load={self.load:.2f} "
                f"lat={self.latency:.2f} hlt={self.health:.2f} ctx={self.context})")


def extract_signals(
    cpu: float,
    mem: float,
    error_rate: float = 0.0,
    latency_ms: float = 50.0,
    swap_percent: float = 0.0,
    disk_usage: float = 0.0,
    # 历史（变化率）
    err_velocity: float = 0.0,
    lat_velocity: float = 0.0,
) -> SemanticSignals:
    """
    从原始指标提取 4 个正交语义信号。

    参数：
        cpu: CPU 使用率 [0, 100]
        mem: 内存使用率 [0, 100]
        error_rate: 错误率 [0, 100]
        latency_ms: 延迟 (ms)
        swap_percent: Swap 使用率 [0, 100]
        disk_usage: 磁盘使用率 [0, 100]
        err_velocity: 错误率变化率
        lat_velocity: 延迟变化率

    返回：
        SemanticSignals 实例
    """

    # ── Signal 1: Error（错误严重度）──
    # 只看错误本身，不看负载
    err_base = max(0, error_rate) / 100.0
    # 分段升级：低错误缓慢上升，高错误急剧上升
    if error_rate > 20:
        err_signal = min(1.0, 0.5 + 0.5 * (error_rate - 20) / 80)
    elif error_rate > 6:
        err_signal = min(0.5, 0.1 + 0.4 * (error_rate - 6) / 14)
    elif error_rate > 2:
        err_signal = min(0.1, (error_rate - 2) / 40)
    else:
        err_signal = 0.0
    # 变化率惩罚：错误飙升时加重
    if err_velocity > 0.2:
        err_signal = min(1.0, err_signal + 0.3 * min(1.0, err_velocity))

    # ── Signal 2: Load（综合负载）──
    # CPU 为主，内存为辅，Swap 补充
    cpu_norm = max(0, cpu) / 100.0
    mem_norm = max(0, mem) / 100.0
    swap_norm = max(0, swap_percent) / 100.0

    load_signal = 0.55 * cpu_norm + 0.30 * mem_norm + 0.15 * swap_norm
    # 高负载非线性放大
    if load_signal > 0.7:
        load_signal = 0.7 + 0.3 * (load_signal - 0.7) / 0.3
    load_signal = min(1.0, load_signal)

    # ── Signal 3: Latency（延迟压力）──
    lat_base = tanh_norm(latency_ms, center=100, scale=400)
    lat_signal = max(0, lat_base)  # 只取正值，低延迟不贡献压力
    # 延迟飙升加重
    if lat_velocity > 0.3:
        lat_signal = min(1.0, lat_signal + 0.2 * min(1.0, lat_velocity))
    lat_signal = min(1.0, lat_signal)

    # ── Signal 4: Health（健康余量）──
    # 与 error 互补，但独立计算
    err_health = 1.0 - min(1.0, error_rate / 12.0)
    lat_health = 1.0 - max(0, min(1.0, (latency_ms - 200) / 1800.0))
    disk_health = 1.0 - max(0, (disk_usage - 70) / 30)
    health_signal = err_health * 0.45 + lat_health * 0.25 + disk_health * 0.15 + (1 - swap_norm) * 0.15
    health_signal = max(0, min(1, health_signal))

    # ── Context Tag（上下文分类）──
    context = _classify_context(err_signal, load_signal, lat_signal, health_signal)

    return SemanticSignals(
        error=err_signal,
        load=load_signal,
        latency=lat_signal,
        health=health_signal,
        context=context,
    )


def _classify_context(err: float, load: float, lat: float, health: float) -> str:
    """
    上下文分类：决定同一信号在不同场景下的解释方式。

    'clean':    系统健康，高负载 = 高效运转
    'degraded': 性能下降但无严重错误，高负载 = 勉强支撑
    'err':      有严重错误，高负载 = 过载
    """
    if err > 0.3:
        return 'err'
    elif health < 0.5 or (lat > 0.4 and err > 0.1):
        return 'degraded'
    else:
        return 'clean'
