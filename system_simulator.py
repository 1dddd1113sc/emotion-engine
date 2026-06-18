"""
系统指标模拟器：生成逼真的系统负载场景用于测试
支持多种场景：正常、突发负载、错误飙升、渐进过载等
"""
import random
import math
from dataclasses import dataclass


@dataclass
class SystemMetrics:
    cpu: float         # 0-100 %
    mem: float         # 0-100 %
    error_rate: float  # 0-100 %
    latency_ms: float  # 0-5000 ms


class SystemSimulator:
    """模拟系统指标，支持注入不同场景"""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.tick = 0
        self._base_cpu = 30.0
        self._base_mem = 45.0
        self._base_error = 0.5
        self._base_latency = 50.0
        self._scenario = "normal"
        self._scenario_tick = 0

    def set_scenario(self, scenario: str):
        """切换场景: normal, spike, error_burst, gradual_overload, recovery"""
        self._scenario = scenario
        self._scenario_tick = 0

    def next(self) -> SystemMetrics:
        """生成下一时刻的系统指标"""
        self.tick += 1
        self._scenario_tick += 1

        if self._scenario == "normal":
            return self._normal()
        elif self._scenario == "spike":
            return self._spike()
        elif self._scenario == "error_burst":
            return self._error_burst()
        elif self._scenario == "gradual_overload":
            return self._gradual_overload()
        elif self._scenario == "recovery":
            return self._recovery()
        else:
            return self._normal()

    def _noise(self, base: float, scale: float = 3.0) -> float:
        return base + self.rng.gauss(0, scale)

    def _normal(self) -> SystemMetrics:
        """正常运行：低负载，偶尔小波动"""
        return SystemMetrics(
            cpu=max(0, min(100, self._noise(30, 5))),
            mem=max(0, min(100, self._noise(45, 2))),
            error_rate=max(0, min(100, self._noise(0.5, 0.3))),
            latency_ms=max(0, self._noise(50, 15)),
        )

    def _spike(self) -> SystemMetrics:
        """突发负载：前 10 步正常，然后 CPU 飙升 30 步，再恢复"""
        if self._scenario_tick < 10:
            return self._normal()
        elif self._scenario_tick < 40:
            spike_intensity = math.sin((self._scenario_tick - 10) / 30 * math.pi)
            return SystemMetrics(
                cpu=max(0, min(100, self._noise(30 + 60 * spike_intensity, 8))),
                mem=max(0, min(100, self._noise(45 + 30 * spike_intensity, 3))),
                error_rate=max(0, min(100, self._noise(0.5 + 15 * spike_intensity, 3))),
                latency_ms=max(0, self._noise(50 + 800 * spike_intensity, 100)),
            )
        else:
            self.set_scenario("normal")
            return self._normal()

    def _error_burst(self) -> SystemMetrics:
        """错误飙升：CPU 正常但错误率突然升高"""
        if self._scenario_tick < 5:
            return self._normal()
        elif self._scenario_tick < 35:
            error_peak = min(1.0, self._scenario_tick / 20)
            return SystemMetrics(
                cpu=max(0, min(100, self._noise(35, 5))),
                mem=max(0, min(100, self._noise(48, 2))),
                error_rate=max(0, min(100, self._noise(5 + 40 * error_peak, 8))),
                latency_ms=max(0, self._noise(50 + 300 * error_peak, 80)),
            )
        else:
            self.set_scenario("normal")
            return self._normal()

    def _gradual_overload(self) -> SystemMetrics:
        """渐进过载：负载缓慢上升"""
        progress = min(1.0, self._scenario_tick / 60)
        return SystemMetrics(
            cpu=max(0, min(100, self._noise(20 + 70 * progress, 5))),
            mem=max(0, min(100, self._noise(40 + 45 * progress, 3))),
            error_rate=max(0, min(100, self._noise(0.3 + 20 * progress * progress, 3))),
            latency_ms=max(0, self._noise(40 + 1500 * progress * progress, 100)),
        )

    def _recovery(self) -> SystemMetrics:
        """恢复：从高负载逐渐回到正常"""
        progress = min(1.0, self._scenario_tick / 40)
        recovery = 1.0 - progress
        return SystemMetrics(
            cpu=max(0, min(100, self._noise(30 + 50 * recovery, 5))),
            mem=max(0, min(100, self._noise(45 + 25 * recovery, 2))),
            error_rate=max(0, min(100, self._noise(0.5 + 20 * recovery, 3))),
            latency_ms=max(0, self._noise(50 + 600 * recovery, 80)),
        )
