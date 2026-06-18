"""
体感维度模块 V6 — 五层感官架构

L1 计算与记忆 → Fatigue（疲劳度 / 累）
L2 吞吐与排队 → Tension（紧绷度 / 压力）
L3 传导与IO   → Tension + Comfort（卡/顺）
L4 业务表现   → Flow / Confusion（通过信号注入）
L5 物理硬件   → Fatigue（终极物理疲劳）+ Comfort
"""
import math
from collections import deque
from dataclasses import dataclass


@dataclass
class BodySense:
    """体感状态"""
    fatigue: float = 0.0         # [0, 1] 疲劳度
    tension: float = 0.0         # [0, 1] 紧绷度
    comfort: float = 1.0         # [0, 1] 舒适度
    exhaustion_risk: float = 0.0 # [0, 1] 耗竭风险


class FatigueTracker:
    """
    疲劳度追踪器 — L1 计算与记忆 + L5 物理硬件

    原理：指数衰减累积，τ=600s（10分钟半衰期）
    """

    def __init__(self, tau: float = 600.0):
        self.tau = tau
        self._fatigue = 0.0
        self._last_time: float | None = None
        self._high_load_start: float | None = None
        self._high_load_duration: float = 0.0

    def update(self, load_signal: float, now: float | None = None) -> float:
        import time
        if now is None:
            now = time.time()

        if self._last_time is None:
            self._last_time = now
            self._fatigue = load_signal
            return self._fatigue

        dt = now - self._last_time
        self._last_time = now

        alpha = 1.0 - math.exp(-dt / self.tau)
        self._fatigue = alpha * load_signal + (1 - alpha) * self._fatigue

        if load_signal > 0.6:
            if self._high_load_start is None:
                self._high_load_start = now
            self._high_load_duration = now - self._high_load_start
        else:
            self._high_load_start = None
            self._high_load_duration = max(0, self._high_load_duration - dt * 0.5)

        return self._fatigue

    @property
    def duration_minutes(self) -> float:
        return self._high_load_duration / 60.0

    def reset(self):
        self._fatigue = 0.0
        self._last_time = None
        self._high_load_start = None
        self._high_load_duration = 0.0


class TensionTracker:
    """
    紧绷度追踪器 — L2 吞吐排队 + L3 传导IO

    原理：信号方向一致性 + 队列/IO 压力叠加
    """

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._signal_history: deque[list[float]] = deque(maxlen=window_size)
        self._tension = 0.0

    def update(self, signals: list[float]) -> float:
        self._signal_history.append(signals)

        if len(self._signal_history) < 3:
            return 0.0

        data = list(self._signal_history)
        n_signals = len(signals)
        avg_directions = []
        for i in range(n_signals):
            vals = [step[i] for step in data if i < len(step)]
            avg = sum(vals) / len(vals) if vals else 0
            avg_directions.append(avg)

        positive = sum(1 for d in avg_directions if d > 0.1)
        negative = sum(1 for d in avg_directions if d < -0.1)
        total = len(avg_directions)

        if total == 0:
            return 0.0

        if positive == 0 or negative == 0:
            contradiction = 0.0
        else:
            contradiction = 2.0 * min(positive, negative) / total

        distress_level = sum(max(0, -d) for d in avg_directions) / total
        self._tension = 0.6 * contradiction + 0.4 * distress_level
        return min(1.0, self._tension)

    @property
    def current(self) -> float:
        return self._tension

    def reset(self):
        self._signal_history.clear()
        self._tension = 0.0


class ComfortTracker:
    """
    舒适度追踪器 — L3 IO + L5 物理硬件

    原理：资源余量感 + 温度 + 磁盘健康
    """

    def __init__(self):
        self._comfort = 1.0

    def update(
        self,
        disk_usage: float = 0.0,
        swap_percent: float = 0.0,
        mem_available_gb: float = 32.0,
        # L5 新增
        thermal_stress: float = 0.0,
        disk_io_latency_ms: float = 0.0,
    ) -> float:
        comfort = 1.0

        # 磁盘空间
        if disk_usage > 70:
            comfort -= 0.4 * (disk_usage - 70) / 30

        # Swap
        if swap_percent > 20:
            comfort -= 0.3 * (swap_percent - 20) / 80

        # 可用内存
        if mem_available_gb < 4:
            comfort -= 0.3 * (4 - mem_available_gb) / 4

        # L5: 温度压力
        if thermal_stress > 0:
            comfort -= 0.3 * thermal_stress

        # L3: IO 延迟高 → 不舒服
        if disk_io_latency_ms > 10:
            io_penalty = min(1.0, (disk_io_latency_ms - 10) / 40)  # 10ms以下OK，50ms很难受
            comfort -= 0.2 * io_penalty

        self._comfort = max(0.0, min(1.0, comfort))
        return self._comfort

    @property
    def current(self) -> float:
        return self._comfort

    def reset(self):
        self._comfort = 1.0


class BodySenseManager:
    """
    体感管理器 V6 — 五层感官整合

    每层向体感系统贡献信号：
    L1 → fatigue_signal（CPU过劳、降频、上下文切换）
    L2 → tension_signals（连接积压、CLOSE_WAIT、线程密度）
    L3 → tension_signals + comfort（IO延迟、队列深度）
    L4 → 通过外部注入 signals（业务错误 → 负信号）
    L5 → fatigue_signal + comfort（温度、GPU压力）
    """

    def __init__(self):
        self.fatigue = FatigueTracker(tau=600)
        self.tension = TensionTracker(window_size=10)
        self.comfort = ComfortTracker()

    def update(
        self,
        # 通用
        load_signal: float = 0.0,
        signals: list[float] | None = None,
        # L1 计算与记忆
        cpu_overwork: float = 0.0,
        freq_throttle: float = 0.0,
        ctx_switches_rate: float = 0.0,
        syscalls_rate: float = 0.0,
        # L2 吞吐与排队
        listen_backlog: float = 0.0,
        close_wait_ratio: float = 0.0,
        conn_churn_rate: float = 0.0,
        thread_density: float = 0.0,
        # L3 传导与IO
        disk_io_latency_ms: float = 0.0,
        io_congestion: float = 0.0,
        disk_queue_depth: float = 0.0,
        interrupts_rate: float = 0.0,
        interrupt_ratio: float = 0.0,
        dpc_ratio: float = 0.0,
        # L5 物理硬件
        thermal_stress: float = 0.0,
        gpu_stress: float = 0.0,
        disk_usage: float = 0.0,
        swap_percent: float = 0.0,
        mem_available_gb: float = 32.0,
    ) -> BodySense:

        # ===== L1: 疲劳度信号 =====
        fatigue_signal = load_signal
        if cpu_overwork > 0:
            fatigue_signal = max(fatigue_signal, cpu_overwork)
        if freq_throttle > 0.2:
            fatigue_signal = max(fatigue_signal, min(1.0, freq_throttle))
        if ctx_switches_rate > 20000:
            fatigue_signal = max(fatigue_signal, min(1.0, (ctx_switches_rate - 20000) / 80000))
        if syscalls_rate > 500000:
            fatigue_signal = max(fatigue_signal, min(1.0, (syscalls_rate - 500000) / 2000000))
        # L5: 温度和GPU压力直接贡献疲劳
        if thermal_stress > 0:
            fatigue_signal = max(fatigue_signal, thermal_stress)
        if gpu_stress > 0.5:
            fatigue_signal = max(fatigue_signal, gpu_stress * 0.7)

        f = self.fatigue.update(fatigue_signal)

        # ===== L2+L3: 紧绷度信号 =====
        base_signals = list(signals or [])

        # L2: 连接积压 → 紧绷
        if listen_backlog > 0.3:
            base_signals.append(-min(1.0, listen_backlog))
        if close_wait_ratio > 0.1:
            base_signals.append(-min(1.0, close_wait_ratio * 3))
        if conn_churn_rate > 10:
            base_signals.append(-min(1.0, conn_churn_rate / 50))
        if thread_density > 20:
            base_signals.append(-min(1.0, (thread_density - 20) / 30))

        # L3: IO 压力 → 紧绷
        if disk_io_latency_ms > 5:
            io_stress = min(1.0, (disk_io_latency_ms - 5) / 45)
            base_signals.append(-io_stress)
        if disk_queue_depth is not None and disk_queue_depth > 1:
            dq_stress = min(1.0, (disk_queue_depth - 1) / 9)
            base_signals.append(-dq_stress)
        if io_congestion > 2:
            base_signals.append(-min(1.0, (io_congestion - 2) / 5))

        # 神经系统
        if interrupts_rate > 15000:
            base_signals.append(-min(1.0, (interrupts_rate - 15000) / 50000))
        if interrupt_ratio > 0.03:
            base_signals.append(-min(1.0, (interrupt_ratio - 0.03) / 0.10))
        if dpc_ratio > 0.03:
            base_signals.append(-min(1.0, (dpc_ratio - 0.03) / 0.10))

        t = self.tension.update(base_signals)

        # ===== L3+L5: 舒适度 =====
        c = self.comfort.update(
            disk_usage=disk_usage,
            swap_percent=swap_percent,
            mem_available_gb=mem_available_gb,
            thermal_stress=thermal_stress,
            disk_io_latency_ms=disk_io_latency_ms,
        )

        exhaustion = f * t

        return BodySense(
            fatigue=f,
            tension=t,
            comfort=c,
            exhaustion_risk=exhaustion,
        )

    def reset(self):
        self.fatigue.reset()
        self.tension.reset()
        self.comfort.reset()


if __name__ == "__main__":
    import sys, io, time
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== 体感模块 V6 测试 ===\n")

    manager = BodySenseManager()

    # 场景1：空闲
    print("--- 场景1：空闲运行 ---")
    for i in range(5):
        s = manager.update(
            load_signal=0.1,
            signals=[0.8, 0.7, 0.9, 0.9],
            disk_usage=76.0,
            swap_percent=14.0,
            mem_available_gb=18.0,
        )
        print(f"  [{i}] 疲劳={s.fatigue:.3f} 紧绷={s.tension:.3f} 舒适={s.comfort:.2f} 耗竭={s.exhaustion_risk:.3f}")
        time.sleep(0.1)

    # 场景2：L2 连接风暴
    print("\n--- 场景2：L2 连接风暴（CLOSE_WAIT堆积）---")
    manager.reset()
    for i in range(5):
        s = manager.update(
            load_signal=0.3,
            listen_backlog=0.5,
            close_wait_ratio=0.25,
            conn_churn_rate=30,
            thread_density=25,
        )
        print(f"  [{i}] 疲劳={s.fatigue:.3f} 紧绷={s.tension:.3f} 舒适={s.comfort:.2f} 耗竭={s.exhaustion_risk:.3f}")
        time.sleep(0.1)

    # 场景3：L3 IO 阻塞
    print("\n--- 场景3：L3 IO 阻塞（磁盘延迟高）---")
    manager.reset()
    for i in range(5):
        s = manager.update(
            load_signal=0.4,
            disk_io_latency_ms=35.0,
            disk_queue_depth=5.0,
            io_congestion=3.0,
            disk_usage=85.0,
        )
        print(f"  [{i}] 疲劳={s.fatigue:.3f} 紧绷={s.tension:.3f} 舒适={s.comfort:.2f} 耗竭={s.exhaustion_risk:.3f}")
        time.sleep(0.1)

    # 场景4：L5 物理过热
    print("\n--- 场景4：L5 物理过热（CPU 90°C + GPU 88°C）---")
    manager.reset()
    for i in range(5):
        s = manager.update(
            load_signal=0.7,
            thermal_stress=0.6,
            gpu_stress=0.8,
            cpu_overwork=0.55,
            freq_throttle=0.4,
            disk_usage=90.0,
            swap_percent=35.0,
            mem_available_gb=4.0,
        )
        print(f"  [{i}] 疲劳={s.fatigue:.3f} 紧绷={s.tension:.3f} 舒适={s.comfort:.2f} 耗竭={s.exhaustion_risk:.3f}")
        time.sleep(0.1)

    # 场景5：全层并发（噩梦场景）
    print("\n--- 场景5：全层并发（噩梦场景）---")
    manager.reset()
    for i in range(8):
        s = manager.update(
            load_signal=0.9,
            cpu_overwork=0.85,
            freq_throttle=0.5,
            ctx_switches_rate=60000,
            syscalls_rate=1500000,
            listen_backlog=0.7,
            close_wait_ratio=0.3,
            conn_churn_rate=50,
            thread_density=35,
            disk_io_latency_ms=45.0,
            disk_queue_depth=8.0,
            io_congestion=4.0,
            thermal_stress=0.7,
            gpu_stress=0.9,
            disk_usage=95.0,
            swap_percent=50.0,
            mem_available_gb=2.0,
            signals=[-0.8, -0.7, -0.9, -0.6],
        )
        print(f"  [{i}] 疲劳={s.fatigue:.3f} 紧绷={s.tension:.3f} 舒适={s.comfort:.2f} 耗竭={s.exhaustion_risk:.3f}")
        time.sleep(0.1)
