"""
脏数据缓冲层 — 真实世界数据清洗

处理三类脏数据：
1. 空值/缺失：监控组件重启导致的 None
2. 断崖突变：网络丢包导致的数值骤降/骤升
3. 时间戳乱序：采集间隔不均匀

策略：
- 空值 → 用最近有效值填充（向前填充），超过max_gap个采样周期则标记为无效
- 断崖 → 变化率超过阈值时，用EMA平滑过渡而非直接采用
- 乱序 → 按时间戳排序，丢弃过期数据
"""
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class CleanResult:
    """清洗后的数据"""
    data: dict           # 清洗后的指标字典
    is_valid: bool       # 数据是否有效
    warnings: list[str]  # 清洗过程中的警告
    fill_count: int      # 填充的空值数量
    smooth_count: int    # 平滑的断崖数量


class DirtyDataBuffer:
    """
    脏数据缓冲层

    用法：
        buffer = DirtyDataBuffer(max_gap=5, cliff_threshold=3.0)
        result = buffer.process(raw_metrics_dict)
        if result.is_valid:
            # 送入情绪引擎
    """

    def __init__(
        self,
        max_gap: int = 5,           # 最大容忍缺失采样数
        cliff_threshold: float = 3.0,  # 断崖检测阈值（标准差倍数）
        window_size: int = 30,      # 统计窗口大小
        ema_alpha: float = 0.3,     # 断崖平滑系数
    ):
        self.max_gap = max_gap
        self.cliff_threshold = cliff_threshold
        self.window_size = window_size
        self.ema_alpha = ema_alpha

        # 每个指标的滑动窗口
        self._windows: dict[str, deque] = {}
        # 最近有效值（用于向前填充）
        self._last_valid: dict[str, float] = {}
        # 连续缺失计数
        self._gap_count: dict[str, int] = {}
        # EMA平滑后的值（用于断崖平滑）
        self._ema_state: dict[str, float] = {}
        # 时间戳历史
        self._timestamps: deque = deque(maxlen=window_size)

    def _get_window(self, key: str) -> deque:
        if key not in self._windows:
            self._windows[key] = deque(maxlen=self.window_size)
        return self._windows[key]

    def _update_stats(self, key: str, value: float):
        """更新统计窗口"""
        window = self._get_window(key)
        window.append(value)

    def _get_mean_std(self, key: str) -> tuple[float, float]:
        """获取窗口均值和标准差"""
        window = self._get_window(key)
        if len(window) < 3:
            return 0.0, 1.0
        data = list(window)
        mean = sum(data) / len(data)
        var = sum((x - mean) ** 2 for x in data) / len(data)
        return mean, max(0.01, var ** 0.5)

    def _is_cliff(self, key: str, value: float) -> bool:
        """检测是否为断崖突变"""
        mean, std = self._get_mean_std(key)
        if len(self._get_window(key)) < 5:
            return False
        z_score = abs(value - mean) / std
        return z_score > self.cliff_threshold

    def _smooth_cliff(self, key: str, value: float) -> float:
        """断崖平滑：用EMA过渡"""
        if key not in self._ema_state:
            self._ema_state[key] = value
        else:
            self._ema_state[key] = self.ema_alpha * value + (1 - self.ema_alpha) * self._ema_state[key]
        return self._ema_state[key]

    def process(self, raw: dict[str, float | None], timestamp: float | None = None) -> CleanResult:
        """
        处理一批原始指标

        参数：
            raw: {指标名: 值}，值可以是None（缺失）
            timestamp: 采集时间戳，None则用当前时间

        返回：
            CleanResult 包含清洗后的数据和警告
        """
        if timestamp is None:
            timestamp = time.time()

        self._timestamps.append(timestamp)

        cleaned = {}
        warnings = []
        fill_count = 0
        smooth_count = 0

        for key, value in raw.items():
            # --- 情况1：缺失值 ---
            if value is None:
                self._gap_count[key] = self._gap_count.get(key, 0) + 1
                gap = self._gap_count[key]

                if gap > self.max_gap:
                    # 超过最大容忍缺失数，标记警告
                    warnings.append(f"{key}: 连续缺失{gap}次，超过阈值{self.max_gap}")
                    # 仍然用最后有效值填充，但标记为无效数据
                    cleaned[key] = self._last_valid.get(key, 0.0)
                else:
                    # 向前填充
                    filled = self._last_valid.get(key, 0.0)
                    cleaned[key] = filled
                    fill_count += 1
                    if gap > 1:
                        warnings.append(f"{key}: 连续缺失{gap}次，向前填充={filled:.3f}")

                continue

            # 有效值，重置缺失计数
            self._gap_count[key] = 0

            # --- 情况2：断崖突变 ---
            if self._is_cliff(key, value):
                smoothed = self._smooth_cliff(key, value)
                warnings.append(f"{key}: 断崖检测 {value:.3f} → 平滑为 {smoothed:.3f}")
                cleaned[key] = smoothed
                smooth_count += 1
            else:
                # 正常值，直接采用
                cleaned[key] = value
                # 更新EMA状态
                self._ema_state[key] = value

            # 更新统计和最后有效值
            self._update_stats(key, cleaned[key])
            self._last_valid[key] = cleaned[key]

        # --- 情况3：时间戳乱序检测 ---
        if len(self._timestamps) >= 2:
            if self._timestamps[-1] < self._timestamps[-2]:
                warnings.append(f"时间戳乱序: {self._timestamps[-1]:.3f} < {self._timestamps[-2]:.3f}")

        # --- 整体有效性判断 ---
        # 如果超过50%的指标都是填充的，标记为无效
        total = len(raw)
        is_valid = fill_count < total * 0.5

        return CleanResult(
            data=cleaned,
            is_valid=is_valid,
            warnings=warnings,
            fill_count=fill_count,
            smooth_count=smooth_count,
        )

    def reset(self):
        """重置所有状态"""
        self._windows.clear()
        self._last_valid.clear()
        self._gap_count.clear()
        self._ema_state.clear()
        self._timestamps.clear()


def test_buffer():
    """测试脏数据缓冲层"""
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    buffer = DirtyDataBuffer(max_gap=3, cliff_threshold=2.5)

    print("=== 测试1: 正常数据 ===")
    for i in range(5):
        r = buffer.process({"cpu": 30 + i * 2, "mem": 60.0})
        print(f"  [{i}] cpu={r.data['cpu']:.1f} mem={r.data['mem']:.1f} valid={r.is_valid} warn={r.warnings}")

    print("\n=== 测试2: 缺失值（向前填充）===")
    for i in range(5):
        cpu = None if i in [1, 2] else 35.0
        r = buffer.process({"cpu": cpu, "mem": 60.0})
        print(f"  [{i}] cpu={r.data['cpu']:.1f} fill={r.fill_count} valid={r.is_valid} warn={r.warnings}")

    print("\n=== 测试3: 断崖突变 ===")
    for val in [30, 32, 28, 31, 95, 33, 29]:  # 95是断崖
        r = buffer.process({"cpu": val, "mem": 60.0})
        print(f"  cpu_raw={val:5.1f} → cleaned={r.data['cpu']:.1f} smooth={r.smooth_count} warn={r.warnings}")

    print("\n=== 测试4: 连续缺失超阈值 ===")
    for i in range(7):
        r = buffer.process({"cpu": None, "mem": 60.0})
        print(f"  [{i}] cpu={r.data['cpu']:.1f} valid={r.is_valid} warn={r.warnings}")


if __name__ == "__main__":
    test_buffer()
