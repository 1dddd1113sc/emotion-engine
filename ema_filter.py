"""
自适应 EMA 滤波器 V6.0

V5: 变化率大时快速响应
V6: 基于 Google Cluster Data 50K行 + 本机实时数据交叉验证
    alpha_slow=0.35, alpha_fast=0.60, beta=12.0, inertia=0.20
    训练结果: 加权闪烁率 1.43%（上下文自适应 Stabilizer 配合）
版本: V6.0
"""
import math
from pad_model import PADState


class AdaptiveEMAFilter:
    """
    自适应 EMA + 情绪惯性
    α_eff = α_slow + (α_fast - α_slow) * sigmoid(β * (|Δ| - threshold))
    """

    def __init__(
        self,
        alpha_slow: float = 0.35,
        alpha_fast: float = 0.60,
        beta: float = 12.0,
        inertia: float = 0.2,
    ):
        self.alpha_slow = alpha_slow
        self.alpha_fast = alpha_fast
        self.beta = beta
        self.inertia = inertia
        self._state: PADState | None = None
        self._emotion_state: PADState | None = None

    def _adaptive_alpha(self, delta: float) -> float:
        sigmoid = 1.0 / (1.0 + math.exp(-self.beta * (abs(delta) - 0.3)))
        return self.alpha_slow + (self.alpha_fast - self.alpha_slow) * sigmoid

    def update(self, raw: PADState) -> PADState:
        if self._state is None:
            self._state = raw
            self._emotion_state = raw
            return raw

        delta = math.sqrt(
            (raw.p - self._state.p) ** 2 +
            (raw.a - self._state.a) ** 2 +
            (raw.d - self._state.d) ** 2
        )

        alpha = self._adaptive_alpha(delta)

        self._state = PADState(
            p=alpha * raw.p + (1 - alpha) * self._state.p,
            a=alpha * raw.a + (1 - alpha) * self._state.a,
            d=alpha * raw.d + (1 - alpha) * self._state.d,
            volatility=alpha * raw.volatility + (1 - alpha) * self._state.volatility,
        )

        # 情绪惯性层（GLM 建议）
        w = 1.0 - self.inertia
        self._emotion_state = PADState(
            p=w * self._state.p + self.inertia * self._emotion_state.p,
            a=w * self._state.a + self.inertia * self._emotion_state.a,
            d=w * self._state.d + self.inertia * self._emotion_state.d,
            volatility=self._state.volatility,
        )

        return self._emotion_state

    def force_update(self, state: PADState):
        """异常 override 时跳过平滑"""
        self._state = state
        self._emotion_state = state

    @property
    def current(self) -> PADState | None:
        return self._emotion_state

    def reset(self):
        self._state = None
        self._emotion_state = None
