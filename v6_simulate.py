"""
V6.3 合成数据模拟器 — 覆盖计算机能发生的所有情绪场景

设计原则：
1. 所有输入指标都是计算机实际能产生的（CPU、内存、错误率、延迟等）
2. 覆盖完整的 PAD 空间（P±, A±, D± 8个象限）
3. 覆盖 Plutchik 24 态（8基本情绪 × 3强度 + 复合情绪）
4. 每组场景有连续时间序列（模拟真实采集的时序变化）

计算机资源场景矩阵：
┌────────────────────┬──────────┬──────────┬──────────┬──────────┐
│ 场景类别           │ CPU      │ Memory   │ Error    │ Latency  │
├────────────────────┼──────────┼──────────┼──────────┼──────────┤
│ idle               │ 0-20%    │ 30-50%   │ 0%       │ <50ms    │
│ normal             │ 20-50%   │ 50-70%   │ 0-1%     │ 50-100ms │
│ busy               │ 50-80%   │ 60-85%   │ 0-2%     │ 80-200ms │
│ cpu_peak           │ 90-100%  │ 60-80%   │ 1-5%     │ 100-300ms│
│ mem_pressure       │ 30-60%   │ 90-100%  │ 0-3%     │ 200-500ms│
│ io_bottleneck      │ 20-40%   │ 50-70%   │ 0-2%     │ 500-2000ms│
│ cpu_mem_dual       │ 80-100%  │ 85-100%  │ 2-8%     │ 200-800ms│
│ error_cascade      │ 40-80%   │ 50-80%   │ 10-50%   │ 300-2000ms│
│ crash_loop         │ 10-100%  │ 40-90%   │ 50-100%  │ 1000-5000ms│
│ recovery           │ 10-30%   │ 40-60%   │ 0-1%     │ <100ms    │
│ disk_full          │ 20-50%   │ 50-70%   │ 5-20%    │ 100-500ms │
│ network_loss       │ 10-30%   │ 30-50%   │ 0-5%     │ 2000-10000ms│
│ thrashing          │ 30-60%   │ 95-100%  │ 5-15%    │ 500-3000ms│
│ degraded_service   │ 30-60%   │ 50-80%   │ 2-10%    │ 200-1000ms│
│ healthy_peak       │ 70-95%   │ 50-70%   │ 0%       │ 50-150ms  │
└────────────────────┴──────────┴──────────┴──────────┴──────────┘
"""
import sys
import math
import random
import json
import csv
from pathlib import Path
from dataclasses import dataclass, field
from collections import deque

# 确保能导入引擎模块
sys.path.insert(0, str(Path(__file__).parent))

from semantic_signals import SemanticSignals, extract_signals
from context_pad import compose_pad, PADOutput
from body_sense import BodySense, FatigueTracker, TensionTracker, ComfortTracker, BodySenseManager
from plutchik import classify_plutchik, format_plutchik, PlutchikState, BasicEmotion, Intensity


@dataclass
class SystemState:
    """模拟系统状态（计算机真实指标）"""
    cpu: float = 0.0          # 0-100
    mem: float = 50.0         # 0-100
    error_rate: float = 0.0   # 0-100
    latency_ms: float = 50.0  # ms
    swap_pct: float = 0.0     # 0-100
    disk_usage: float = 50.0  # 0-100
    err_velocity: float = 0.0 # 错误率变化率
    lat_velocity: float = 0.0 # 延迟变化率
    step: int = 0
    time: float = 0.0


@dataclass
class ScenarioConfig:
    """场景配置"""
    name: str
    description: str
    duration: int  # 步数
    cpu_range: tuple[float, float]
    mem_range: tuple[float, float]
    error_range: tuple[float, float]
    latency_range: tuple[float, float]
    swap_range: tuple[float, float] = (0, 10)
    disk_range: tuple[float, float] = (40, 60)
    err_velocity_range: tuple[float, float] = (0, 0)
    lat_velocity_range: tuple[float, float] = (0, 0)
    # 变化模式
    trend: str = "random"  # random | rising | falling | spike | stable


# ── 15 个计算机真实场景 ──
SCENARIOS: list[ScenarioConfig] = [
    # 1. 完全空闲 — 低负载、高健康、无错误
    ScenarioConfig(
        name="idle", description="系统空闲", duration=30,
        cpu_range=(2, 15), mem_range=(30, 45), error_range=(0, 0),
        latency_range=(20, 50), trend="stable",
    ),
    # 2. 正常运转 — 中等负载、健康
    ScenarioConfig(
        name="normal", description="正常运行", duration=40,
        cpu_range=(20, 45), mem_range=(45, 65), error_range=(0, 0.5),
        latency_range=(40, 80), trend="random",
    ),
    # 3. 忙碌但健康 — 高CPU、无错误（P+A+D+）
    ScenarioConfig(
        name="busy_healthy", description="忙碌但健康", duration=35,
        cpu_range=(60, 85), mem_range=(55, 75), error_range=(0, 1),
        latency_range=(60, 120), trend="random",
    ),
    # 4. CPU 尖峰 — 瞬间100% CPU（P↓A↑D↓）
    ScenarioConfig(
        name="cpu_peak", description="CPU满载", duration=30,
        cpu_range=(90, 100), mem_range=(55, 75), error_range=(1, 5),
        latency_range=(100, 300), trend="spike",
    ),
    # 5. 内存压力 — 内存接近满（P↓A→D↓）
    ScenarioConfig(
        name="mem_pressure", description="内存压力", duration=30,
        cpu_range=(20, 50), mem_range=(88, 98), error_range=(0, 3),
        latency_range=(150, 500), swap_range=(10, 50), trend="rising",
    ),
    # 6. IO 瓶颈 — 高延迟（P↓A↑D↓）
    ScenarioConfig(
        name="io_bottleneck", description="IO瓶颈", duration=30,
        cpu_range=(15, 35), mem_range=(50, 70), error_range=(0, 2),
        latency_range=(500, 2000), trend="rising",
    ),
    # 7. CPU+内存双压 — 双重过载（P↓A↑D↓）
    ScenarioConfig(
        name="cpu_mem_dual", description="CPU内存双压", duration=30,
        cpu_range=(85, 100), mem_range=(85, 98), error_range=(2, 8),
        latency_range=(200, 800), swap_range=(10, 40), trend="rising",
    ),
    # 8. 错误级联 — 大量错误爆发（P↓↓A↑D↓↓）→ 愤怒
    ScenarioConfig(
        name="error_cascade", description="错误级联", duration=30,
        cpu_range=(40, 80), mem_range=(50, 80), error_range=(10, 50),
        latency_range=(300, 2000), err_velocity_range=(0.2, 0.8), trend="rising",
    ),
    # 9. 崩溃循环 — 进程反复崩溃（P↓↓A↓D↓↓）→ 悲伤
    ScenarioConfig(
        name="crash_loop", description="崩溃循环", duration=30,
        cpu_range=(5, 60), mem_range=(40, 85), error_range=(50, 100),
        latency_range=(1000, 5000), err_velocity_range=(0.5, 1.0), trend="spike",
    ),
    # 10. 恢复中 — 从异常恢复（P↑A↓D↑）→ 信任/平静
    ScenarioConfig(
        name="recovery", description="系统恢复", duration=30,
        cpu_range=(8, 25), mem_range=(40, 60), error_range=(0, 1),
        latency_range=(30, 80), trend="falling",
    ),
    # 11. 磁盘满 — 磁盘空间不足（P↓A→D↓）→ 厌恶
    ScenarioConfig(
        name="disk_full", description="磁盘空间不足", duration=30,
        cpu_range=(15, 45), mem_range=(45, 65), error_range=(5, 20),
        latency_range=(100, 500), disk_range=(90, 99), trend="rising",
    ),
    # 12. 网络断开 — 极高延迟（P↓A↑D↓）→ 惊讶/恐惧
    ScenarioConfig(
        name="network_loss", description="网络中断", duration=30,
        cpu_range=(8, 25), mem_range=(30, 50), error_range=(0, 5),
        latency_range=(2000, 10000), lat_velocity_range=(0.3, 0.7), trend="spike",
    ),
    # 13. 系统颠簸 — Swap疯狂换入换出（P↓A↑D↓）
    ScenarioConfig(
        name="thrashing", description="系统颠簸", duration=30,
        cpu_range=(25, 55), mem_range=(95, 100), error_range=(5, 15),
        latency_range=(500, 3000), swap_range=(60, 95), trend="spike",
    ),
    # 14. 服务降级 — 部分功能不可用（P→A→D↓）
    ScenarioConfig(
        name="degraded", description="服务降级", duration=30,
        cpu_range=(30, 60), mem_range=(50, 80), error_range=(2, 10),
        latency_range=(200, 1000), trend="random",
    ),
    # 15. 健康峰载 — 高负载但无错误（P+A+D+）→ 乐观/期待
    ScenarioConfig(
        name="healthy_peak", description="健康峰载", duration=30,
        cpu_range=(70, 95), mem_range=(50, 70), error_range=(0, 0.5),
        latency_range=(50, 150), trend="stable",
    ),
    # 16. 长期低负载错误 — 慢速累积错误 + 低唤醒（P↓A↓D↓）→ 悲伤
    ScenarioConfig(
        name="slow_decay", description="缓慢衰退", duration=30,
        cpu_range=(10, 30), mem_range=(60, 85), error_range=(8, 30),
        latency_range=(100, 400), trend="rising",
        err_velocity_range=(0.05, 0.15), disk_range=(75, 95),
    ),
    # 17. 资源枯竭 — 低CPU+高内存+高磁盘（P↓A↓D↓）→ 悲伤/无助
    ScenarioConfig(
        name="resource_drain", description="资源枯竭", duration=30,
        cpu_range=(5, 20), mem_range=(90, 99), error_range=(15, 40),
        latency_range=(500, 1500), disk_range=(95, 100), swap_range=(70, 95),
        trend="rising",
    ),
    # 18. 间歇性故障 — 错误反复出现/消失（P波动 A波动 D↓）→ 惊讶/恐惧交替
    ScenarioConfig(
        name="intermittent", description="间歇性故障", duration=30,
        cpu_range=(20, 60), mem_range=(50, 75), error_range=(5, 35),
        latency_range=(200, 1500), trend="spike",
    ),
    # 19. 服务僵死 — 低CPU+高错误+低响应（P↓A↓D↓）→ 悲伤
    ScenarioConfig(
        name="stuck_service", description="服务僵死", duration=30,
        cpu_range=(3, 12), mem_range=(70, 90), error_range=(30, 70),
        latency_range=(3000, 8000), trend="stable",
        disk_range=(70, 90),
    ),
    # 20. 数据损坏 — 磁盘错误 + 数据丢失（P↓A→D↓）→ 悲伤/悔恨
    ScenarioConfig(
        name="data_corruption", description="数据损坏", duration=30,
        cpu_range=(10, 30), mem_range=(50, 70), error_range=(20, 60),
        latency_range=(500, 2000), disk_range=(85, 98), trend="rising",
    ),
    # 21. 网卡降速 — 带宽锐减（P↓A→D↓）→ 失望
    ScenarioConfig(
        name="nic_throttle", description="网卡降速", duration=30,
        cpu_range=(5, 20), mem_range=(40, 60), error_range=(0, 5),
        latency_range=(500, 3000), trend="stable",
        lat_velocity_range=(0.1, 0.3),
    ),
    # 22. 长期空闲 — 无负载+无错误+低唤醒（P+A-D+）→ 信任/平静
    ScenarioConfig(
        name="long_idle", description="长期空闲", duration=30,
        cpu_range=(1, 8), mem_range=(25, 40), error_range=(0, 0),
        latency_range=(20, 40), trend="stable",
    ),
    # 23. 深夜低负载 — 正常但安静（P+A-D+）→ 信任
    ScenarioConfig(
        name="quiet_night", description="深夜安静", duration=30,
        cpu_range=(2, 10), mem_range=(30, 45), error_range=(0, 0.2),
        latency_range=(30, 60), trend="stable",
    ),
    # 24. 系统休眠 — 极低唤醒 + 高健康（P+A-D+）→ 信任
    ScenarioConfig(
        name="dormant", description="系统休眠", duration=30,
        cpu_range=(0.5, 3), mem_range=(20, 35), error_range=(0, 0),
        latency_range=(10, 30), trend="stable",
    ),
    # 25. 监控告警过载 — 大量假阳性告警（P↓A-D↓）→ 悲伤/无奈
    ScenarioConfig(
        name="alert_fatigue", description="告警疲劳", duration=30,
        cpu_range=(10, 25), mem_range=(50, 70), error_range=(8, 25),
        latency_range=(100, 300), trend="stable",
        disk_range=(50, 70),
    ),
    # 26. 长时间无响应 — 服务僵死+低负载（P↓A↓D↓）→ 悲伤
    ScenarioConfig(
        name="dead_service", description="服务死亡", duration=30,
        cpu_range=(1, 5), mem_range=(85, 95), error_range=(40, 80),
        latency_range=(5000, 15000), trend="stable",
        disk_range=(80, 95),
    ),
    # 27. 缓慢耗尽 — 资源逐渐枯竭（P↓A↓D↓）→ 悲伤
    ScenarioConfig(
        name="slow_drain", description="缓慢耗尽", duration=30,
        cpu_range=(2, 10), mem_range=(90, 99), error_range=(20, 50),
        latency_range=(2000, 5000), disk_range=(90, 99), swap_range=(60, 90),
        trend="rising",
    ),
    # 28. 放弃治疗 — 一切指标都坏但系统已无反应（P↓A↓D↓）→ 悲伤
    ScenarioConfig(
        name="given_up", description="系统放弃", duration=30,
        cpu_range=(1, 4), mem_range=(92, 99), error_range=(60, 95),
        latency_range=(8000, 20000), disk_range=(95, 100), swap_range=(80, 98),
        trend="stable",
    ),
]


def _generate_value(lo: float, hi: float, trend: str, step: int, total: int) -> float:
    """生成场景内的指标值，带趋势"""
    base = lo + (hi - lo) * random.random()
    
    if trend == "rising":
        factor = step / max(1, total)
        base = lo + (hi - lo) * (0.5 * factor + 0.5 * random.random())
    elif trend == "falling":
        factor = 1 - step / max(1, total)
        base = lo + (hi - lo) * (0.5 * factor + 0.5 * random.random())
    elif trend == "spike":
        # 周期性尖峰
        spike = 0.5 * (1 + math.sin(step * math.pi / 2))
        base = lo + (hi - lo) * spike * random.random()
    elif trend == "stable":
        base = lo + (hi - lo) * (0.3 + 0.4 * random.random())
    
    # 加噪声
    base += (hi - lo) * 0.05 * random.gauss(0, 1)
    return max(lo - 1, min(hi + 1, base))


def run_simulation() -> list[dict]:
    """运行完整模拟，生成时间序列数据"""
    results = []
    prev_state = None
    step = 0
    t = 0.0
    
    bm = BodySenseManager()
    
    for scenario in SCENARIOS:
        print(f"  [{scenario.name:15s}] {scenario.description:20s} | {scenario.duration}步")
        
        for i in range(scenario.duration):
            step += 1
            t += random.uniform(0.8, 1.2)  # 模拟 ~1s 采集间隔
            
            cpu = _generate_value(*scenario.cpu_range, scenario.trend, i, scenario.duration)
            mem = _generate_value(*scenario.mem_range, scenario.trend, i, scenario.duration)
            error_rate = _generate_value(*scenario.error_range, scenario.trend, i, scenario.duration)
            latency_ms = _generate_value(*scenario.latency_range, scenario.trend, i, scenario.duration)
            swap_pct = _generate_value(*scenario.swap_range, scenario.trend, i, scenario.duration)
            disk_usage = _generate_value(*scenario.disk_range, scenario.trend, i, scenario.duration)
            err_velocity = _generate_value(*scenario.err_velocity_range, scenario.trend, i, scenario.duration)
            lat_velocity = _generate_value(*scenario.lat_velocity_range, scenario.trend, i, scenario.duration)
            
            # 计算速度（从上一帧）
            if prev_state:
                err_velocity = max(err_velocity, abs(error_rate - prev_state.error_rate) / 100)
                lat_velocity = max(lat_velocity, abs(latency_ms - prev_state.latency_ms) / 1000)
            
            # 语义信号提取
            sig = extract_signals(
                cpu=cpu, mem=mem, error_rate=error_rate,
                latency_ms=latency_ms, swap_percent=swap_pct,
                disk_usage=disk_usage,
                err_velocity=err_velocity, lat_velocity=lat_velocity,
            )
            
            # 体感更新
            # 模拟器需要手动设置时间戳，让双τ尺度正常工作
            bm.fatigue._last_time = t
            
            # 构造 tension 信号：负值 = 压力信号
            tension_signals = []
            if error_rate > 5:
                tension_signals.append(-min(1.0, error_rate / 50))
            if latency_ms > 200:
                tension_signals.append(-min(1.0, latency_ms / 5000))
            if swap_pct > 30:
                tension_signals.append(-min(1.0, swap_pct / 100))
            
            body = bm.update(
                load_signal=cpu / 100.0,
                signals=tension_signals if tension_signals else None,
                mem_percent=mem,
                disk_usage=disk_usage,
                swap_percent=swap_pct,
                sig_load=sig.load,
                io_congestion=latency_ms / 10000.0,
            )
            
            # PAD 组合
            pad = compose_pad(sig, body=body)
            
            # Plutchik 分类
            plutchik_state = classify_plutchik(pad.p, pad.a, pad.d)
            plutchik_name = format_plutchik(plutchik_state)
            
            # 象限
            quadrant = (pad.p >= 0, pad.a >= 0, pad.d >= 0)
            
            row = {
                "step": step,
                "time": round(t, 1),
                "scenario": scenario.name,
                "scenario_desc": scenario.description,
                # 原始指标
                "cpu_pct": round(cpu, 1),
                "mem_pct": round(mem, 1),
                "error_rate": round(error_rate, 2),
                "latency_ms": round(latency_ms, 1),
                "swap_pct": round(swap_pct, 1),
                "disk_usage": round(disk_usage, 1),
                "err_velocity": round(err_velocity, 3),
                "lat_velocity": round(lat_velocity, 3),
                # 语义信号
                "sig_error": round(sig.error, 3),
                "sig_load": round(sig.load, 3),
                "sig_latency": round(sig.latency, 3),
                "sig_health": round(sig.health, 3),
                "sig_context": sig.context,
                # 体感
                "fatigue": round(body.fatigue, 3),
                "tension": round(body.tension, 3),
                "comfort": round(body.comfort, 3),
                "exhaustion": round(body.exhaustion_risk, 3),
                # PAD
                "pad_p": round(pad.p, 3),
                "pad_a": round(pad.a, 3),
                "pad_d": round(pad.d, 3),
                "pad_v": round(pad.v, 3),
                # Plutchik
                "plutchik": plutchik_name,
                "primary": plutchik_state.primary.value,
                "intensity": plutchik_state.primary_intensity.value,
                "secondary": plutchik_state.secondary.value if plutchik_state.secondary else "",
                "compound": plutchik_state.compound_name,
                "confidence": round(plutchik_state.confidence, 3),
                # 象限
                "quadrant": str(quadrant),
            }
            results.append(row)
            prev_state = SystemState(
                cpu=cpu, mem=mem, error_rate=error_rate,
                latency_ms=latency_ms, swap_pct=swap_pct,
                disk_usage=disk_usage, err_velocity=err_velocity,
                lat_velocity=lat_velocity, step=step, time=t,
            )
    
    return results


def save_results(results: list[dict], base_dir: Path):
    """保存结果到 CSV 和 JSON"""
    import pandas as pd
    
    df = pd.DataFrame(results)
    
    csv_path = base_dir / "v6_synthetic_data.csv"
    json_path = base_dir / "v6_synthetic_data.json"
    
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\nCSV: {csv_path} ({len(df)} 行)")
    print(f"JSON: {json_path}")
    return df


def print_report(df):
    """打印数据报告"""
    import pandas as pd
    print("\n" + "=" * 60)
    print("V6.3 合成数据 — 数据报告")
    print("=" * 60)
    print(f"总行数: {len(df)}")
    print(f"场景数: {df['scenario'].nunique()}")
    print(f"情绪种类: {df['plutchik'].nunique()}")
    print(f"基本情绪: {df['primary'].nunique()}")
    print(f"象限种类: {df['quadrant'].nunique()}")
    
    print("\n=== 情绪分布 ===")
    emo_counts = df['plutchik'].value_counts()
    for emo, cnt in emo_counts.items():
        bar = "█" * (cnt // 5)
        print(f"  {emo:<30s} {cnt:4d}  {bar}")
    
    print("\n=== 基本情绪分布 ===")
    print(df['primary'].value_counts().to_string())
    
    print("\n=== 强度分布 ===")
    print(df['intensity'].value_counts().to_string())
    
    print("\n=== 象限分布 ===")
    print(df['quadrant'].value_counts().to_string())
    
    print("\n=== 场景 × 基本情绪 ===")
    ct = pd.crosstab(df['scenario'], df['primary'])
    print(ct.to_string())
    
    print("\n=== PAD 全范围 ===")
    for col in ['pad_p', 'pad_a', 'pad_d']:
        print(f"  {col}: [{df[col].min():+.3f}, {df[col].max():+.3f}]")
    
    print("\n=== 各场景 PAD 均值 ===")
    print(df.groupby('scenario')[['pad_p','pad_a','pad_d','fatigue','tension']].mean().round(3).to_string())
    
    print("\n=== 场景覆盖 ===")
    for s in SCENARIOS:
        cnt = len(df[df['scenario'] == s.name])
        emos = df[df['scenario'] == s.name]['plutchik'].unique()
        print(f"  {s.name:<15s} {cnt:3d}步 → {', '.join(emos[:3])}")


def main():
    random.seed(42)  # 可复现
    base_dir = Path(__file__).parent
    
    print("V6.3 合成数据模拟器启动")
    print(f"场景数: {len(SCENARIOS)}")
    print(f"预计步数: {sum(s.duration for s in SCENARIOS)}")
    print()
    
    results = run_simulation()
    df = save_results(results, base_dir)
    print_report(df)


if __name__ == "__main__":
    main()