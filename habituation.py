"""
防疲劳表达模块 — Weber-Fechner 习惯化模型

核心思想：用户对重复刺激会"习惯"，需要更强的刺激才能引起注意。

Weber-Fechner 定律：
  perceived_intensity = k * log(1 + actual_intensity / adaptation_level)

adaptation_level 随时间上升（用户习惯了），需要更强的情绪变化才能触发输出。

实现：
1. 追踪最近 N 次输出的情绪强度
2. 计算"适应水平"（用户已经习惯了多强的刺激）
3. 只有当前情绪强度 > 适应水平 × 阈值倍数时才输出
4. 状态转移时强制输出（不管适应水平）
"""
import math
from collections import deque
from dataclasses import dataclass


@dataclass
class HabituationState:
    """习惯化状态"""
    adaptation_level: float   # 当前适应水平 [0, 1]
    perceived_intensity: float  # 感知强度 [0, 1]
    should_express: bool      # 是否应该表达
    suppression_reason: str   # 被抑制的原因（如果有）


class HabituationManager:
    """
    防疲劳表达管理器

    用法：
        hab = HabituationManager()
        state = hab.update(
            emotion_intensity=0.7,
            is_state_change=True,
            is_anomaly=False,
        )
        if state.should_express:
            # 输出情绪表达
    """

    def __init__(
        self,
        window_size: int = 20,       # 适应窗口大小
        threshold_ratio: float = 1.3, # 当前强度 > 适应水平 × 此值时才输出
        decay_rate: float = 0.95,     # 适应水平衰减率（每步）
        min_adaptation: float = 0.05, # 最低适应水平
        force_express_cooldown: float = 5.0,  # 强制输出冷却（秒）
    ):
        self.window_size = window_size
        self.threshold_ratio = threshold_ratio
        self.decay_rate = decay_rate
        self.min_adaptation = min_adaptation
        self.force_express_cooldown = force_express_cooldown

        self._intensity_history: deque[float] = deque(maxlen=window_size)
        self._adaptation = min_adaptation
        self._last_force_express: float = 0
        self._step: int = 0

    def _compute_adaptation(self) -> float:
        """计算适应水平：最近N次输出的平均强度"""
        if len(self._intensity_history) < 3:
            return self.min_adaptation
        avg = sum(self._intensity_history) / len(self._intensity_history)
        return max(self.min_adaptation, avg)

    def _perceived_intensity(self, actual: float) -> float:
        """Weber-Fechner：感知强度 = k * log(1 + I / A)"""
        k = 1.0 / math.log(2)  # 归一化因子
        return k * math.log(1 + actual / max(self._adaptation, 0.01))

    def update(
        self,
        emotion_intensity: float,
        is_state_change: bool = False,
        is_anomaly: bool = False,
        current_time: float | None = None,
    ) -> HabituationState:
        """
        更新习惯化状态

        参数：
            emotion_intensity: 当前情绪强度 [0, 1]
            is_state_change: 是否发生状态转移
            is_anomaly: 是否异常
            current_time: 当前时间戳

        返回：
            HabituationState
        """
        import time
        if current_time is None:
            current_time = time.time()

        self._step += 1

        # 适应水平衰减（用户会逐渐"脱敏"）
        self._adaptation = max(
            self.min_adaptation,
            self._adaptation * self.decay_rate
        )

        # 感知强度
        perceived = self._perceived_intensity(emotion_intensity)

        # 判断是否应该表达
        should_express = False
        reason = ""

        # 规则1：异常强制输出
        if is_anomaly:
            should_express = True
            reason = "异常事件"

        # 规则2：状态转移强制输出（有冷却时间）
        elif is_state_change:
            if current_time - self._last_force_express > self.force_express_cooldown:
                should_express = True
                self._last_force_express = current_time
                reason = "状态转移"
            else:
                reason = f"状态转移冷却中({self.force_express_cooldown}s)"

        # 规则3：感知强度超过阈值
        elif perceived > self._adaptation * self.threshold_ratio:
            should_express = True
            reason = "感知强度超阈值"

        # 规则4：历史不足时强制输出（建立基线）
        elif len(self._intensity_history) < 5:
            should_express = True
            reason = "建立基线"

        else:
            reason = f"感知强度不足({perceived:.2f} < {self._adaptation * self.threshold_ratio:.2f})"

        # 更新历史
        if should_express:
            self._intensity_history.append(emotion_intensity)
            # 更新适应水平
            self._adaptation = self._compute_adaptation()

        return HabituationState(
            adaptation_level=self._adaptation,
            perceived_intensity=perceived,
            should_express=should_express,
            suppression_reason=reason if not should_express else "",
        )

    def reset(self):
        self._intensity_history.clear()
        self._adaptation = self.min_adaptation
        self._last_force_express = 0
        self._step = 0


if __name__ == "__main__":
    import sys, io, time
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== 防疲劳表达测试 ===\n")

    hab = HabituationManager()

    # 场景1：持续相同强度的情绪（应该逐渐被抑制）
    print("--- 场景1：持续相同强度(0.5) ---")
    print("  预期：前几次输出，之后被抑制（习惯化）\n")
    for i in range(15):
        state = hab.update(emotion_intensity=0.5, current_time=i * 1.0)
        tag = "OUTPUT" if state.should_express else "  mute"
        adapt_bar = "=" * int(state.adaptation_level * 20)
        print(f"  [{i+1:02d}] {tag} | 强度=0.50 感知={state.perceived_intensity:.2f} "
              f"适应={state.adaptation_level:.2f} [{adapt_bar:20s}] "
              f"{'| ' + state.suppression_reason if state.suppression_reason else ''}")

    # 场景2：突然增强的情绪（应该突破习惯化）
    print("\n--- 场景2：突然增强到 0.9 ---")
    print("  预期：突破阈值，强制输出\n")
    for i in range(5):
        state = hab.update(emotion_intensity=0.9, current_time=(15 + i) * 1.0)
        tag = "OUTPUT" if state.should_express else "  mute"
        print(f"  [{16+i:02d}] {tag} | 强度=0.90 感知={state.perceived_intensity:.2f} "
              f"适应={state.adaptation_level:.2f}")

    # 场景3：状态转移（应该强制输出）
    print("\n--- 场景3：状态转移 ---")
    state = hab.update(emotion_intensity=0.3, is_state_change=True, current_time=21.0)
    print(f"  状态转移: {'OUTPUT' if state.should_express else 'mute'} | {state.suppression_reason}")
