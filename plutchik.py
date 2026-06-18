"""
Plutchik 情感轮映射

8基本情绪 × 3强度 = 24态
从 PAD 空间查表映射，零额外计算成本

Plutchik 8基本情绪：
  Joy(喜悦) Trust(信任) Fear(恐惧) Surprise(惊讶)
  Sadness(悲伤) Disgust(厌恶) Anger(愤怒) Anticipation(期待)

强度：low(微弱) medium(中等) high(强烈)

复合情绪（相邻两种基本情绪的混合）：
  Love = Joy + Trust
  Awe = Fear + Surprise
  etc.
"""
import math
from dataclasses import dataclass
from enum import Enum


class BasicEmotion(Enum):
    JOY = "喜悦"
    TRUST = "信任"
    FEAR = "恐惧"
    SURPRISE = "惊讶"
    SADNESS = "悲伤"
    DISGUST = "厌恶"
    ANGER = "愤怒"
    ANTICIPATION = "期待"


class Intensity(Enum):
    LOW = "微弱"
    MEDIUM = "中等"
    HIGH = "强烈"


@dataclass
class PlutchikState:
    """Plutchik 情感状态"""
    primary: BasicEmotion           # 主情绪
    primary_intensity: Intensity    # 主情绪强度
    secondary: BasicEmotion | None  # 次情绪（复合情绪时）
    secondary_intensity: Intensity | None
    compound_name: str              # 复合情绪名称（如有）
    confidence: float               # 分类置信度


# PAD 空间 → Plutchik 8情绪的锚点
# 格式：(P, A, D) → BasicEmotion
# 来源：Mehrabian PAD ↔ Russell 环形 ↔ Plutchik 的交叉映射
PLUTCHIK_ANCHORS: list[tuple[float, float, float, BasicEmotion]] = [
    # (P, A, D, emotion)
    (+0.8, +0.3, +0.5, BasicEmotion.JOY),          # 高愉悦+中唤醒 = 喜悦
    (+0.5, -0.3, +0.5, BasicEmotion.TRUST),         # 正愉悦+低唤醒+高控制 = 信任
    (-0.5, +0.7, -0.5, BasicEmotion.FEAR),          # 负愉悦+高唤醒+低控制 = 恐惧
    (+0.1, +0.8, -0.2, BasicEmotion.SURPRISE),      # 中性+极高唤醒 = 惊讶
    (-0.7, -0.5, -0.3, BasicEmotion.SADNESS),       # 高负愉悦+低唤醒 = 悲伤
    (-0.6, -0.2, +0.3, BasicEmotion.DISGUST),       # 负愉悦+低唤醒+正控制 = 厌恶
    (-0.8, +0.8, -0.6, BasicEmotion.ANGER),          # 高负愉悦+高唤醒+低控制 = 愤怒
    (+0.3, +0.5, +0.3, BasicEmotion.ANTICIPATION),  # 正愉悦+中高唤醒 = 期待
]

# 复合情绪定义（相邻两种基本情绪的混合）
COMPOUND_EMOTIONS: dict[frozenset, str] = {
    frozenset({BasicEmotion.JOY, BasicEmotion.TRUST}): "爱(Love)",
    frozenset({BasicEmotion.TRUST, BasicEmotion.FEAR}): "服从(Submission)",
    frozenset({BasicEmotion.FEAR, BasicEmotion.SURPRISE}): "敬畏(Awe)",
    frozenset({BasicEmotion.SURPRISE, BasicEmotion.SADNESS}): "失望(Disappointment)",
    frozenset({BasicEmotion.SADNESS, BasicEmotion.DISGUST}): "悔恨(Remorse)",
    frozenset({BasicEmotion.DISGUST, BasicEmotion.ANGER}): "轻蔑(Contempt)",
    frozenset({BasicEmotion.ANGER, BasicEmotion.ANTICIPATION}): "攻击性(Aggressiveness)",
    frozenset({BasicEmotion.ANTICIPATION, BasicEmotion.JOY}): "乐观(Optimism)",
}


def _pad_distance(p1: tuple, p2: tuple) -> float:
    """PAD 空间加权欧氏距离"""
    w_p, w_a, w_d = 0.45, 0.30, 0.25
    return math.sqrt(
        w_p * (p1[0] - p2[0]) ** 2 +
        w_a * (p1[1] - p2[1]) ** 2 +
        w_d * (p1[2] - p2[2]) ** 2
    )


def _intensity_from_distance(distance: float) -> Intensity:
    """距离越近 → 强度越高"""
    if distance < 0.3:
        return Intensity.HIGH
    elif distance < 0.6:
        return Intensity.MEDIUM
    else:
        return Intensity.LOW


def classify_plutchik(p: float, a: float, d: float) -> PlutchikState:
    """
    PAD → Plutchik 分类

    返回：
        主情绪 + 强度 + 次情绪（如果是复合情绪）+ 复合名称
    """
    current = (p, a, d)

    # 计算到各锚点的距离
    distances: list[tuple[float, BasicEmotion]] = []
    for ep, ea, ed, emotion in PLUTCHIK_ANCHORS:
        dist = _pad_distance(current, (ep, ea, ed))
        distances.append((dist, emotion))

    # 按距离排序
    distances.sort(key=lambda x: x[0])

    # 主情绪
    primary_dist, primary = distances[0]
    primary_intensity = _intensity_from_distance(primary_dist)

    # 次情绪（第二近的）
    secondary_dist, secondary = distances[1]
    secondary_intensity = _intensity_from_distance(secondary_dist)

    # 置信度：主次距离差距越大，越确定是单一情绪
    margin = secondary_dist - primary_dist
    confidence = min(1.0, margin / 0.5)

    # 复合情绪判断：如果主次距离很接近，且属于相邻情绪
    compound_name = ""
    pair = frozenset({primary, secondary})
    if pair in COMPOUND_EMOTIONS and margin < 0.3:
        compound_name = COMPOUND_EMOTIONS[pair]
        return PlutchikState(
            primary=primary,
            primary_intensity=primary_intensity,
            secondary=secondary,
            secondary_intensity=secondary_intensity,
            compound_name=compound_name,
            confidence=confidence,
        )

    # 单一情绪
    return PlutchikState(
        primary=primary,
        primary_intensity=primary_intensity,
        secondary=None,
        secondary_intensity=None,
        compound_name="",
        confidence=confidence,
    )


def format_plutchik(state: PlutchikState) -> str:
    """格式化 Plutchik 状态为可读字符串"""
    intensity_map = {
        Intensity.LOW: "微微",
        Intensity.MEDIUM: "",
        Intensity.HIGH: "强烈",
    }
    p_int = intensity_map[state.primary_intensity]
    p_name = state.primary.value

    if state.compound_name and state.secondary:
        return f"{state.compound_name}({p_int}{p_name}+{state.secondary.value})"
    else:
        return f"{p_int}{p_name}"


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== Plutchik 情感轮测试 ===\n")

    test_cases = [
        (+0.8, +0.3, +0.5, "空闲正常"),
        (-0.8, +0.8, -0.6, "严重过载"),
        (-0.5, +0.7, -0.5, "突发异常"),
        (-0.7, -0.5, -0.3, "低负载高错误"),
        (+0.1, +0.8, -0.2, "突发负载"),
        (+0.5, -0.3, +0.5, "恢复平静"),
        (-0.3, +0.4, -0.1, "轻度异常"),
        (+0.3, +0.5, +0.3, "忙碌但健康"),
    ]

    for p, a, d, desc in test_cases:
        state = classify_plutchik(p, a, d)
        formatted = format_plutchik(state)
        print(f"  PAD=({p:+.1f},{a:+.1f},{d:+.1f}) {desc:10s} → {formatted}  conf={state.confidence:.2f}")
