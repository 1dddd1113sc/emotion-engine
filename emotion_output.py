"""
情绪输出引擎 — Top-2 混合情绪 + 运维意图映射

504种混合状态 → 5种运维行动意图
"""
from dataclasses import dataclass, field
from enum import Enum
from plutchik import (
    BasicEmotion, Intensity, PlutchikState,
    classify_plutchik, format_plutchik,
    PLUTCHIK_ANCHORS, COMPOUND_EMOTIONS,
)
from pad_model import PADState
import math


# === 运维行动意图簇（5类降维）===

class IntentCluster(Enum):
    CRITICAL = "濒危/崩溃"
    OVERLOAD = "紧绷/过载"
    CONFUSED = "困惑/中毒"
    FATIGUED = "疲劳/老化"
    FLOW = "心流/掌控"


CLUSTER_ACTIONS = {
    IntentCluster.CRITICAL: {
        "intent": "立刻救命",
        "auto": ["自动隔离节点", "熔断", "重启", "呼叫On-call"],
        "emoji": "🔴",
    },
    IntentCluster.OVERLOAD: {
        "intent": "释放压力",
        "auto": ["自动扩容", "限流", "降级非核心业务"],
        "emoji": "🟠",
    },
    IntentCluster.CONFUSED: {
        "intent": "排查逻辑",
        "auto": ["抓取Dump", "分析Error日志", "阻断恶意IP"],
        "emoji": "🟡",
    },
    IntentCluster.FATIGUED: {
        "intent": "计划维护",
        "auto": ["安排低峰期重启", "清理缓存", "触发深度GC"],
        "emoji": "🟢",
    },
    IntentCluster.FLOW: {
        "intent": "保持观察",
        "auto": ["记录基线", "无需干预", "生成健康报告"],
        "emoji": "🔵",
    },
}

# 情绪→簇映射表
EMOTION_TO_CLUSTER = {
    # 恐惧系 → 濒危/紧绷
    BasicEmotion.FEAR: IntentCluster.CRITICAL,
    BasicEmotion.ANGER: IntentCluster.CRITICAL,
    # 惊讶系 → 紧绷
    BasicEmotion.SURPRISE: IntentCluster.OVERLOAD,
    # 厌恶系 → 困惑
    BasicEmotion.DISGUST: IntentCluster.CONFUSED,
    # 悲伤系 → 疲劳
    BasicEmotion.SADNESS: IntentCluster.FATIGUED,
    # 喜悦/信任/期待 → 心流
    BasicEmotion.JOY: IntentCluster.FLOW,
    BasicEmotion.TRUST: IntentCluster.FLOW,
    BasicEmotion.ANTICIPATION: IntentCluster.FLOW,
}


@dataclass
class Top2Emotion:
    """Top-2 混合情绪状态"""
    # 主情绪
    primary_emo: BasicEmotion
    primary_intensity: Intensity
    primary_score: float  # 距离得分(0-1)
    # 副情绪
    secondary_emo: BasicEmotion
    secondary_intensity: Intensity
    secondary_score: float
    # 复合名称
    compound_name: str = ""
    # 混合描述
    mix_description: str = ""


@dataclass
class OutputPayload:
    """完整的机器情绪输出"""
    # PAD原始值
    p: float
    a: float
    d: float
    # 情绪状态
    quadrant: str
    top2: Top2Emotion
    # 运维意图
    cluster: IntentCluster
    cluster_emoji: str
    intent: str
    auto_actions: list[str]
    # 置信度
    confidence: float
    # 异常原因
    anomaly_reason: str | None = None
    # 人类可读描述
    human_text: str = ""
    # 机器可读JSON字段
    machine_dict: dict = field(default_factory=dict)


def _pad_distance(p1: tuple, p2: tuple) -> float:
    w_p, w_a, w_d = 0.45, 0.30, 0.25
    return math.sqrt(
        w_p * (p1[0] - p2[0]) ** 2 +
        w_a * (p1[1] - p2[1]) ** 2 +
        w_d * (p1[2] - p2[2]) ** 2
    )


def _intensity_from_distance(distance: float) -> Intensity:
    if distance < 0.3:
        return Intensity.HIGH
    elif distance < 0.6:
        return Intensity.MEDIUM
    else:
        return Intensity.LOW


def _score_from_distance(distance: float) -> float:
    """距离→得分(0-1)，距离越近得分越高"""
    return max(0.0, min(1.0, 1.0 - distance / 1.2))


def _intensity_label(intensity: Intensity) -> str:
    return {
        Intensity.LOW: "微弱",
        Intensity.MEDIUM: "中等",
        Intensity.HIGH: "强烈",
    }[intensity]


def compute_top2(p: float, a: float, d: float) -> Top2Emotion:
    """计算Top-2混合情绪"""
    current = (p, a, d)

    # 计算到各锚点的距离和得分
    scored: list[tuple[float, float, BasicEmotion]] = []  # (score, distance, emotion)
    for ep, ea, ed, emotion in PLUTCHIK_ANCHORS:
        dist = _pad_distance(current, (ep, ea, ed))
        score = _score_from_distance(dist)
        scored.append((score, dist, emotion))

    # 按得分降序排列
    scored.sort(key=lambda x: -x[0])

    primary_score, primary_dist, primary_emo = scored[0]
    secondary_score, secondary_dist, secondary_emo = scored[1]

    primary_intensity = _intensity_from_distance(primary_dist)
    secondary_intensity = _intensity_from_distance(secondary_dist)

    # 检查复合情绪
    pair = frozenset({primary_emo, secondary_emo})
    compound_name = COMPOUND_EMOTIONS.get(pair, "")

    # 混合描述
    p_label = _intensity_label(primary_intensity)
    s_label = _intensity_label(secondary_intensity)
    p_name = primary_emo.value
    s_name = secondary_emo.value

    if compound_name:
        mix_desc = f"{compound_name}({p_label}{p_name}+{s_label}{s_name})"
    else:
        mix_desc = f"{p_label}{p_name}，伴有{s_label}{s_name}"

    return Top2Emotion(
        primary_emo=primary_emo,
        primary_intensity=primary_intensity,
        primary_score=round(primary_score, 3),
        secondary_emo=secondary_emo,
        secondary_intensity=secondary_intensity,
        secondary_score=round(secondary_score, 3),
        compound_name=compound_name,
        mix_description=mix_desc,
    )


def _determine_cluster(top2: Top2Emotion, pad: PADState) -> IntentCluster:
    """从Top-2情绪+PAD值确定运维意图簇"""
    # 规则优先级：极端PAD值直接判定
    if pad.p < -0.6 and pad.a > 0.6 and pad.d < -0.5:
        return IntentCluster.CRITICAL
    if pad.a > 0.7 and pad.d < -0.3:
        return IntentCluster.OVERLOAD
    if pad.p < -0.3 and pad.a < 0.0:
        return IntentCluster.FATIGUED

    # 否则从主情绪映射
    primary_cluster = EMOTION_TO_CLUSTER.get(top2.primary_emo, IntentCluster.FLOW)
    secondary_cluster = EMOTION_TO_CLUSTER.get(top2.secondary_emo, IntentCluster.FLOW)

    # 如果主副情绪属于不同簇，取更"严重"的
    severity = {
        IntentCluster.CRITICAL: 4,
        IntentCluster.OVERLOAD: 3,
        IntentCluster.CONFUSED: 2,
        IntentCluster.FATIGUED: 1,
        IntentCluster.FLOW: 0,
    }
    if severity.get(primary_cluster, 0) >= severity.get(secondary_cluster, 0):
        return primary_cluster
    return secondary_cluster


def generate_output(
    pad: PADState,
    anomaly_reason: str | None = None,
    real_cpu: float | None = None,
    real_mem: float | None = None,
) -> OutputPayload:
    """
    生成完整的机器情绪输出

    返回：
        - Top-2混合情绪
        - 运维意图簇
        - 人类可读文本
        - 机器可读字典
    """
    # 计算Top-2
    top2 = compute_top2(pad.p, pad.a, pad.d)

    # 确定意图簇
    cluster = _determine_cluster(top2, pad)
    cluster_info = CLUSTER_ACTIONS[cluster]

    # 置信度
    margin = top2.primary_score - top2.secondary_score
    confidence = min(1.0, round(margin / 0.3, 3))

    # 真实指标
    cpu = int(real_cpu) if real_cpu is not None else "N/A"
    mem = int(real_mem) if real_mem is not None else "N/A"

    # 人类可读文本
    emoji = cluster_info["emoji"]
    intent = cluster_info["intent"]
    actions = "、".join(cluster_info["auto"][:2])

    anomaly_prefix = f"⚠️ {anomaly_reason}。" if anomaly_reason else ""
    human_text = (
        f"{anomaly_prefix}{emoji} {top2.mix_description} | "
        f"意图：{intent} | 自动响应：{actions} | "
        f"PAD=({pad.p:+.2f},{pad.a:+.2f},{pad.d:+.2f}) "
        f"CPU={cpu}% MEM={mem}%"
    )

    # 机器可读字典
    machine_dict = {
        "pad": {"p": round(pad.p, 3), "a": round(pad.a, 3), "d": round(pad.d, 3)},
        "quadrant": pad.quadrant.value,
        "top2": {
            "primary": {
                "emotion": top2.primary_emo.value,
                "intensity": _intensity_label(top2.primary_intensity),
                "score": top2.primary_score,
            },
            "secondary": {
                "emotion": top2.secondary_emo.value,
                "intensity": _intensity_label(top2.secondary_intensity),
                "score": top2.secondary_score,
            },
            "compound": top2.compound_name,
            "description": top2.mix_description,
        },
        "cluster": {
            "name": cluster.value,
            "emoji": cluster_info["emoji"],
            "intent": intent,
            "auto_actions": cluster_info["auto"],
        },
        "confidence": confidence,
        "metrics": {"cpu": cpu, "mem": mem},
        "anomaly": anomaly_reason,
    }

    return OutputPayload(
        p=pad.p, a=pad.a, d=pad.d,
        quadrant=pad.quadrant.value,
        top2=top2,
        cluster=cluster,
        cluster_emoji=emoji,
        intent=intent,
        auto_actions=cluster_info["auto"],
        confidence=confidence,
        anomaly_reason=anomaly_reason,
        human_text=human_text,
        machine_dict=machine_dict,
    )


def format_top2_short(payload: OutputPayload) -> str:
    """简短格式：emoji + 情绪 + 意图"""
    t = payload.top2
    c = payload.cluster_emoji
    return f"{c} {t.mix_description} → {payload.intent}"


def format_top2_full(payload: OutputPayload) -> str:
    """完整格式：包含PAD、指标、自动响应"""
    return payload.human_text


def format_top2_json(payload: OutputPayload) -> dict:
    """机器可读格式"""
    return payload.machine_dict


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== Top-2 混合情绪输出测试 ===\n")

    test_cases = [
        (+0.8, +0.3, +0.5, "空闲正常", 15.0, 40.0),
        (-0.8, +0.8, -0.6, "严重过载", 98.0, 95.0),
        (-0.5, +0.7, -0.5, "突发异常", 92.0, 80.0),
        (-0.7, -0.5, -0.3, "低负载高错误", 10.0, 30.0),
        (+0.1, +0.8, -0.2, "突发负载", 85.0, 70.0),
        (+0.5, -0.3, +0.5, "恢复平静", 25.0, 45.0),
        (-0.3, +0.4, -0.1, "轻度异常", 60.0, 55.0),
        (+0.3, +0.5, +0.3, "忙碌但健康", 75.0, 60.0),
        (-0.9, +0.9, -0.8, "进程崩溃", 99.0, 98.0),
        (+0.6, +0.2, +0.6, "完美自愈", 35.0, 50.0),
    ]

    for p, a, d, desc, cpu, mem in test_cases:
        pad = PADState(p=p, a=a, d=d).clamp()
        payload = generate_output(pad, real_cpu=cpu, real_mem=mem)
        short = format_top2_short(payload)
        print(f"  {desc:10s} PAD=({p:+.1f},{a:+.1f},{d:+.1f})")
        print(f"    → {short}")
        print(f"    → JSON: {format_top2_json(payload)['top2']['description']}")
        print()
