"""
防闪烁象限控制器 — 三方整合版

整合 DeepSeek + Qwen + GLM 方案：
[1] 维度死区 ±0.06 — 0线附近锁零
[2] 象限滞回 ±0.08 — 离开象限需确认
[3] 惯性窗口 3步 — 连续3次相同才切换
[4] 震荡检测 — 短时往返自动抑制
"""
from collections import deque


class QuadrantStabilizer:
    """
    象限稳定器：在 EMA 之后、象限判断之前插入。
    
    信号流：
    PAD原始值 → [EMA平滑] → [本控制器] → 稳定象限
    """

    def __init__(
        self,
        # 维度死区：P/A/D 在 [-dz, +dz] 内锁定为 0
        deadzone_p: float = 0.06,
        deadzone_a: float = 0.06,
        deadzone_d: float = 0.06,
        # 象限滞回：离开当前象限需要越过的阈值
        hysteresis: float = 0.08,
        # 惯性窗口：连续 N 次指向同一新象限才确认切换
        inertia_window: int = 3,
        # 震荡检测窗口
        oscillation_window: int = 8,
        # 震荡抑制强度 (0=不抑制, 1=完全锁定)
        oscillation_suppress: float = 0.7,
    ):
        self.deadzone = {'P': deadzone_p, 'A': deadzone_a, 'D': deadzone_d}
        self.hysteresis = hysteresis
        self.inertia_window = inertia_window
        self.oscillation_window = oscillation_window
        self.oscillation_suppress = oscillation_suppress

        # 状态
        self.current_quadrant = None       # 当前稳定象限 (p_bit, a_bit, d_bit)
        self._prev_signs = {'P': 0, 'A': 0, 'D': 0}
        self._candidate_history = deque(maxlen=inertia_window)
        self._raw_history = {'P': deque(maxlen=oscillation_window),
                             'A': deque(maxlen=oscillation_window),
                             'D': deque(maxlen=oscillation_window)}
        self._baseline = {'P': 0.0, 'A': 0.0, 'D': 0.0}  # 上一个稳定值

    def reset(self):
        self.current_quadrant = None
        self._prev_signs = {'P': 0, 'A': 0, 'D': 0}
        self._candidate_history.clear()
        for h in self._raw_history.values():
            h.clear()
        self._baseline = {'P': 0.0, 'A': 0.0, 'D': 0.0}

    def update(self, P: float, A: float, D: float) -> tuple[float, float, float, tuple, bool]:
        """
        输入: EMA 平滑后的 P/A/D 值
        输出: (P_stable, A_stable, D_stable, quadrant, is_transition)
        """
        # ── Layer 1: 震荡检测与抑制 ──
        for dim, val in [('P', P), ('A', A), ('D', D)]:
            self._raw_history[dim].append(val)
        P, A, D = self._suppress_oscillation(P, A, D)

        # ── Layer 2: 维度死区 ──
        P = self._apply_deadzone(P, 'P')
        A = self._apply_deadzone(A, 'A')
        D = self._apply_deadzone(D, 'D')

        # ── Layer 3: 象限滞回 ──
        P_s = self._apply_hysteresis(P, 'P')
        A_s = self._apply_hysteresis(A, 'A')
        D_s = self._apply_hysteresis(D, 'D')

        # 候选象限
        candidate = self._to_quadrant(P_s, A_s, D_s)

        # 首次初始化
        if self.current_quadrant is None:
            self.current_quadrant = candidate
            self._update_baseline(P, A, D)
            return P_s, A_s, D_s, candidate, False

        # 象限未变
        if candidate == self.current_quadrant:
            self._update_baseline(P, A, D)
            return P_s, A_s, D_s, candidate, False

        # ── Layer 4: 惯性窗口 ──
        self._candidate_history.append(candidate)

        if len(self._candidate_history) >= self.inertia_window:
            # 检查最近 N 次是否全部指向同一个新象限
            recent = list(self._candidate_history)
            if all(q == candidate for q in recent[-self.inertia_window:]):
                # 确认切换
                old = self.current_quadrant
                self.current_quadrant = candidate
                self._candidate_history.clear()
                self._update_baseline(P, A, D)
                return P_s, A_s, D_s, candidate, True

        # 未满足条件，锁定在当前象限
        P_s, A_s, D_s = self._snap_to_quadrant(P_s, A_s, D_s)
        return P_s, A_s, D_s, self.current_quadrant, False

    # ── 内部方法 ──

    def _apply_deadzone(self, value: float, dim: str) -> float:
        """维度死区：在 [-dz, +dz] 内归零"""
        dz = self.deadzone[dim]
        if abs(value) < dz:
            return 0.0
        sign = 1.0 if value > 0 else -1.0
        return sign * (abs(value) - dz) / (1.0 - dz)

    def _apply_hysteresis(self, value: float, dim: str) -> float:
        """象限滞回：当前正区间时，值必须 < -hysteresis 才翻负"""
        h = self.hysteresis
        prev = self._prev_signs[dim]

        if prev >= 0:
            if value < -h:
                self._prev_signs[dim] = -1
                return value
            else:
                self._prev_signs[dim] = 1
                return max(value, 0.0) if prev > 0 else value
        else:
            if value > h:
                self._prev_signs[dim] = 1
                return value
            else:
                self._prev_signs[dim] = -1
                return min(value, 0.0) if prev < 0 else value

    def _suppress_oscillation(self, P: float, A: float, D: float) -> tuple[float, float, float]:
        """震荡检测：短时内方向反复反转 → 抑制"""
        result = {}
        for dim, val in [('P', P), ('A', A), ('D', D)]:
            hist = list(self._raw_history[dim])
            if len(hist) < 4:
                result[dim] = val
                continue

            # 计算方向反转次数
            reversals = 0
            for i in range(2, len(hist)):
                d1 = hist[i-1] - hist[i-2]
                d2 = hist[i] - hist[i-1]
                if d1 * d2 < 0:
                    reversals += 1

            if reversals >= 3:
                # 震荡中，向 baseline 靠拢
                s = self.oscillation_suppress
                result[dim] = s * self._baseline[dim] + (1 - s) * val
            else:
                result[dim] = val

        return result['P'], result['A'], result['D']

    def _snap_to_quadrant(self, P: float, A: float, D: float) -> tuple[float, float, float]:
        """将接近 0 的值吸附到当前象限内侧"""
        q = self.current_quadrant
        dims = [('P', P, q[0]), ('A', A, q[1]), ('D', D, q[2])]
        result = []
        for name, val, sign_bit in dims:
            target_sign = 1 if sign_bit else -1
            if target_sign > 0 and val < 0:
                result.append(max(val, -self.deadzone[name]))
            elif target_sign < 0 and val > 0:
                result.append(min(val, self.deadzone[name]))
            else:
                result.append(val)
        return tuple(result)

    def _to_quadrant(self, P: float, A: float, D: float) -> tuple:
        """P/A/D 正负 → 象限 ID"""
        return (P > 0, A > 0, D > 0)

    def _update_baseline(self, P: float, A: float, D: float):
        """更新 baseline（用于震荡抑制）"""
        alpha = 0.3
        self._baseline['P'] = alpha * P + (1 - alpha) * self._baseline['P']
        self._baseline['A'] = alpha * A + (1 - alpha) * self._baseline['A']
        self._baseline['D'] = alpha * D + (1 - alpha) * self._baseline['D']

    def get_state(self) -> dict:
        """调试用：返回当前内部状态"""
        return {
            'quadrant': self.current_quadrant,
            'prev_signs': dict(self._prev_signs),
            'baseline': dict(self._baseline),
            'candidate_history': list(self._candidate_history),
        }


# ═══════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════

if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    stab = QuadrantStabilizer()

    # 场景1：稳定信号 → 不应切换
    print("=== 场景1：稳定 ===")
    for i in range(10):
        P, A, D, q, t = stab.update(0.3, 0.2, 0.1)
        print(f"  [{i}] P={P:+.3f} A={A:+.3f} D={D:+.3f} -> {q} transition={t}")

    # 场景2：小幅噪声振荡 → 不应切换
    print("\n=== 场景2：噪声振荡 ===")
    noise = [0.05, -0.03, 0.04, -0.02, 0.06, -0.01, 0.03, -0.04]
    for i, n in enumerate(noise):
        P, A, D, q, t = stab.update(0.3 + n, 0.2, 0.1)
        print(f"  [{i}] P={P:+.3f} A={A:+.3f} D={D:+.3f} -> {q} transition={t}")

    # 场景3：真实大幅变化 → 应该切换
    print("\n=== 场景3：真实变化 ===")
    for i in range(5):
        P, A, D, q, t = stab.update(-0.5, -0.3, -0.4)
        print(f"  [{i}] P={P:+.3f} A={A:+.3f} D={D:+.3f} -> {q} transition={t}")

    # 场景4：回来 → 需要惯性窗口确认
    print("\n=== 场景4：回来 ===")
    stab2 = QuadrantStabilizer()
    for i in range(5):
        stab2.update(0.3, 0.2, 0.1)
    for i, n in enumerate([0.05, -0.03, 0.04, -0.02, 0.06]):
        P, A, D, q, t = stab2.update(0.3 + n, 0.2, 0.1)
        print(f"  [{i}] P={P:+.3f} A={A:+.3f} D={D:+.3f} -> {q} transition={t}")
