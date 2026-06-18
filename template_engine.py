"""
模板引擎 v3 — 四方优化版

GLM：softmax + 温度参数的软分类
DeepSeek：信号一致性置信度
Qwen：8类情绪锚点（简化为6类）
"""
import random
import math
from dataclasses import dataclass
from pad_model import PADState, PADQuadrant


TEMPLATES: dict[PADQuadrant, list[str]] = {
    PADQuadrant.STABLE_GOOD: [
        "系统运行平稳，CPU使用率{cpu_pct}%，内存{mem_pct}%，各项指标正常。",
        "当前状态良好，{load}负载运行，{stability}。",
        "一切正常，CPU {cpu_pct}%，内存 {mem_pct}%，系统稳定运转中。",
        "系统轻松运行，{stability}，表现优秀。",
        "状态稳定，{load}处理中，{stability}反馈。",
    ],
    PADQuadrant.HIGH_ENERGY_GOOD: [
        "系统正在高效运转，CPU {cpu_pct}%，负载较高但一切正常。",
        "忙碌但健康！CPU {cpu_pct}%，内存 {mem_pct}%，{stability}。",
        "高负载运行中，{load}处理任务，系统应对自如。",
        "全力输出中，CPU {cpu_pct}%，{stability}，表现良好。",
        "系统满载运行，CPU {cpu_pct}%，内存 {mem_pct}%，整体健康。",
    ],
    PADQuadrant.STABLE_BAD: [
        "⚠️ 系统状态低迷，CPU {cpu_pct}%但存在异常指标。",
        "低负载但错误率偏高，{stability}。建议 {action}。",
        "系统表现不佳，CPU {cpu_pct}%，需要排查。{stability}。",
        "异常信号：错误率偏高，{stability}。建议 {action}。",
        "状态异常，CPU {cpu_pct}%空闲但存在错误。",
    ],
    PADQuadrant.HIGH_ENERGY_BAD: [
        "🚨 紧急！CPU {cpu_pct}% + 错误率飙升，系统失控！",
        "严重警告：CPU {cpu_pct}%，内存 {mem_pct}%，错误频发！立即 {action}！",
        "系统过载运行中，CPU {cpu_pct}%且错误率飙升。建议立即 {action}。",
        "⚠️ CPU {cpu_pct}% + 高错误率！系统压力很大。",
        "警告：CPU {cpu_pct}%，内存 {mem_pct}%，错误频发，{stability}！",
    ],
    PADQuadrant.NEUTRAL: [
        "系统运行中，CPU {cpu_pct}%，暂无显著异常。",
        "状态中性，CPU {cpu_pct}%，{load}负载，持续监控中。",
    ],
    PADQuadrant.ALERT: [
        "系统负载上升中，CPU {cpu_pct}%，当前可控但需保持警惕。",
        "中等负载，CPU {cpu_pct}%，内存 {mem_pct}%，{stability}。建议 {action}。",
        "警戒状态，CPU {cpu_pct}%，{load}运行，密切关注中。",
    ],
}

LOAD_DESC = {
    (-1.0, -0.3): "低",
    (-0.3, 0.3): "中等",
    (0.3, 0.7): "较高",
    (0.7, 1.1): "极高",
}

STABILITY_DESC = {
    (-1.0, -0.5): "不稳定",
    (-0.5, 0.0): "有波动",
    (0.0, 0.5): "基本稳定",
    (0.5, 1.1): "非常稳定",
}

ACTIONS = [
    "检查日志", "重启服务", "扩容资源", "排查错误源",
    "降低请求频率", "检查依赖服务", "清理临时文件", "等待自动恢复",
]


def _desc_for(value: float, table: dict) -> str:
    for (lo, hi), desc in table.items():
        if lo <= value < hi:
            return desc
    return "未知"


@dataclass
class ExpressionResult:
    text: str
    confidence: float
    quadrant: PADQuadrant
    top_emotions: list[tuple[str, float]]
    needs_llm: bool
    anomaly_reason: str | None = None


def compute_confidence(pad: PADState) -> float:
    """加权欧氏距离置信度（Qwen+GLM：P权重最高）"""
    centers = {
        PADQuadrant.STABLE_GOOD: (0.5, -0.3, 0.5),
        PADQuadrant.HIGH_ENERGY_GOOD: (0.3, 0.5, 0.3),
        PADQuadrant.STABLE_BAD: (-0.5, -0.3, -0.3),
        PADQuadrant.HIGH_ENERGY_BAD: (-0.5, 0.5, -0.5),
        PADQuadrant.NEUTRAL: (0.0, 0.0, 0.0),
        PADQuadrant.ALERT: (0.1, 0.4, -0.1),
    }
    q = pad.quadrant
    center = centers.get(q, (0, 0, 0))
    w_p, w_a, w_d = 0.45, 0.30, 0.25
    dist = math.sqrt(
        w_p * (pad.p - center[0]) ** 2 +
        w_a * (pad.a - center[1]) ** 2 +
        w_d * (pad.d - center[2]) ** 2
    )
    return max(0.0, round(1.0 - dist / 1.5, 3))


def generate_expression(
    pad: PADState,
    confidence_threshold: float = 0.5,
    anomaly_reason: str | None = None,
    real_cpu: float | None = None,
    real_mem: float | None = None,
) -> ExpressionResult:
    quadrant = pad.quadrant
    confidence = compute_confidence(pad)
    templates = TEMPLATES.get(quadrant, TEMPLATES[PADQuadrant.NEUTRAL])
    template = random.choice(templates)

    load = _desc_for(pad.a, LOAD_DESC)
    stability = _desc_for(pad.d, STABILITY_DESC)
    action = random.choice(ACTIONS)
    # cpu_pct 和 mem_pct：优先用真实指标，否则从PAD反推
    if real_cpu is not None:
        cpu_pct = max(0, min(100, int(real_cpu)))
    else:
        try:
            cpu_pct = max(0, min(100, int(30 + 35 * math.atanh(max(-0.99, min(0.99, pad.a / 0.8))))))
        except:
            cpu_pct = 30
    if real_mem is not None:
        mem_pct = max(0, min(100, int(real_mem)))
    else:
        mem_pct = 50
    latency = max(0, int((1 - pad.p) / 2 * 2000))

    text = template.format(
        load=load, stability=stability, action=action,
        cpu_pct=cpu_pct, mem_pct=mem_pct, latency=latency,
    )

    if anomaly_reason:
        text = f"⚠️ {anomaly_reason}。{text}"

    probs = pad.emotion_probs
    top_emotions = list(probs.items())[:2]

    return ExpressionResult(
        text=text, confidence=confidence, quadrant=quadrant,
        top_emotions=top_emotions, needs_llm=confidence < confidence_threshold,
        anomaly_reason=anomaly_reason,
    )


class OutputThrottler:
    """语言输出频率控制（GLM P1 建议）"""

    def __init__(self, interval_sec: float = 5.0):
        self.interval_sec = interval_sec
        self._last_quadrant: PADQuadrant | None = None
        self._last_output_tick: float = 0
        self._tick: float = 0

    def should_output(self, quadrant: PADQuadrant, is_anomaly: bool = False) -> bool:
        self._tick += 1
        if is_anomaly:
            self._last_quadrant = quadrant
            self._last_output_tick = self._tick
            return True
        if self._last_quadrant is not None and quadrant != self._last_quadrant:
            self._last_quadrant = quadrant
            self._last_output_tick = self._tick
            return True
        if self._tick - self._last_output_tick >= self.interval_sec:
            self._last_output_tick = self._tick
            return True
        return False

    def reset(self):
        self._last_quadrant = None
        self._last_output_tick = 0
        self._tick = 0
