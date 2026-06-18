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
        # 惯性窗口：连续 N 次指向同一新象限才确认切换
        inertia_window: int = 3,
        # 上下文自适应参数
        clean_dz: float = 0.12,       # clean 时放大的死区
        clean_inertia: int = 8,       # clean 时更高的惯性
        err_dz: float = 0.04,         # err 时缩小的死区
        err_inertia: int = 3,         # err 时的惯性
    ):
        self.deadzone = {'P': deadzone_p, 'A': deadzone_a, 'D': deadzone_d}
        self.inertia_window = inertia_window
        # 上下文自适应
        self.clean_dz = clean_dz
        self.clean_inertia = clean_inertia
        self.err_dz = err_dz
        self.err_inertia = err_inertia

        # 状态
        self.current_quadrant = None       # 当前稳定象限 (p_bit, a_bit, d_bit)
        self._prev_signs = {'P': 0, 'A': 0, 'D': 0}
        self._candidate_history = deque(maxlen=max(clean_inertia, inertia_window) + 2)
        self._raw_history = {'P': deque(maxlen=8), 'A': deque(maxlen=8), 'D': deque(maxlen=8)}
        self._baseline = {'P': 0.0, 'A': 0.0, 'D': 0.0}
        self._current_context = 'clean'

    def reset(self):
        self.current_quadrant = None
        self._prev_signs = {'P': 0, 'A': 0, 'D': 0}
        self._candidate_history.clear()
        for h in self._raw_history.values():
            h.clear()
        self._baseline = {'P': 0.0, 'A': 0.0, 'D': 0.0}

    def update(self, P: float, A: float, D: float, context: str = 'clean') -> tuple[float, float, float, tuple, bool]:
        """
        输入: EMA 平滑后的 P/A/D 值, 上下文标签
        输出: (P_stable, A_stable, D_stable, quadrant, is_transition)
        """
        self._current_context = context

        # ── 上下文自适应参数 ──
        if context == 'clean':
            dz = self.clean_dz
            inertia = self.clean_inertia
        else:  # err / degraded
            dz = self.err_dz
            inertia = self.err_inertia

        # ── Layer 1: 震荡检测与抑制 ──
        for dim, val in [('P', P), ('A', A), ('D', D)]:
            self._raw_history[dim].append(val)
        P, A, D = self._suppress_oscillation(P, A, D)

        # ── Layer 2: 维度死区（上下文自适应）──
        P = self._apply_deadzone_ctx(P, 'P', dz)
        A = self._apply_deadzone_ctx(A, 'A', dz)
        D = self._apply_deadzone_ctx(D, 'D', dz)

        # 候选象限
        candidate = self._to_quadrant(P, A, D)

        # 首次初始化
        if self.current_quadrant is None:
            self.current_quadrant = candidate
            self._update_baseline(P, A, D)
            return P, A, D, candidate, False

        # 象限未变
        if candidate == self.current_quadrant:
            self._candidate_history.clear()
            self._update_baseline(P, A, D)
            return P, A, D, candidate, False

        # ── Layer 3: 连续 N 次一致才切换 ──
        self._candidate_history.append(candidate)

        if len(self._candidate_history) >= inertia:
            recent = list(self._candidate_history)
            if all(q == candidate for q in recent[-inertia:]):
                self.current_quadrant = candidate
                self._candidate_history.clear()
                self._update_baseline(P, A, D)
                return P, A, D, candidate, True

        # 未满足条件，锁定在当前象限
        P, A, D = self._snap_to_quadrant(P, A, D)
        return P, A, D, self.current_quadrant, False

    # ── 内部方法 ──

    def _apply_deadzone(self, value: float, dim: str) -> float:
        """维度死区：在 [-dz, +dz] 内归零"""
        dz = self.deadzone[dim]
        return self._apply_deadzone_ctx(value, dim, dz)

    def _apply_deadzone_ctx(self, value: float, dim: str, dz: float) -> float:
        """上下文自适应维度死区"""
        if abs(value) < dz:
            return 0.0
        sign = 1.0 if value > 0 else -1.0
        return sign * (abs(value) - dz) / (1.0 - dz)

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
        dz = self.clean_dz if self._current_context == 'clean' else self.err_dz
        dims = [('P', P, q[0]), ('A', A, q[1]), ('D', D, q[2])]
        result = []
        for name, val, sign_bit in dims:
            target_sign = 1 if sign_bit else -1
            if target_sign > 0 and val < 0:
                result.append(max(val, -dz))
            elif target_sign < 0 and val > 0:
                result.append(min(val, dz))
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
