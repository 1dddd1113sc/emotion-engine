"""
EMA 参数网格搜索训练脚本 V5.0

用 Google Cluster Data 2011 的真实 CPU/Memory 数据作为输入，
对 EMA 滤波器的 alpha_slow、alpha_fast、beta、inertia 四个参数进行网格搜索，
找到 flicker rate 最低、response latency 最小、stability 最高的参数组合。

数据来源: Google Cluster Data 2011 (task_usage)
训练方法: 网格搜索 + 多目标评分

用法:
    python train_ema.py                    # 默认 5000 步
    python train_ema.py --steps 20000      # 自定义步数
    python train_ema.py --part 1           # 指定数据分片
"""
import sys
import io
import time
import argparse
import itertools
import urllib.request
import gzip
import json
import math

sys.stdout.reconfigure(encoding='utf-8')

# ── 导入情绪引擎 ──
from pad_model import PADState, MetricsHistory, metrics_to_pad
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from plutchik import classify_plutchik
from ema_filter import AdaptiveEMAFilter

# ── Google Cluster Data 配置 ──
BUCKET = "clusterdata-2011-2"
TASK_USAGE_SCHEMA = [
    "start_time", "end_time", "job_id", "task_index", "machine_id",
    "cpu_rate", "canonical_memory_usage", "assigned_memory_usage",
    "unmapped_page_cache_memory", "total_page_cache_memory",
    "maximum_memory", "disk_io_time", "maximum_disk_rate",
    "average_disk_rate", "average_disk_rate_sampled",
    "cycles_per_instruction", "memory_accesses_per_instruction",
    "sample_portion", "aggregation_type", "sampled_cpu_usage",
]


def stream_cluster_data(part: int = 0, max_rows: int = 5000):
    """从 GCS 流式读取 task_usage 数据（自动放缩到系统监控值域）"""
    filename = f"task_usage/part-{part:05d}-of-00500.csv.gz"
    url = f"https://storage.googleapis.com/{BUCKET}/{filename}"

    print(f"📥 正在流式读取: {filename} (最多 {max_rows} 行)", flush=True)

    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw_rows = []
            with gzip.GzipFile(fileobj=resp) as gz:
                with io.TextIOWrapper(gz, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if len(raw_rows) >= max_rows:
                            break
                        fields = line.strip().split(",")
                        if len(fields) < 6:
                            continue
                        try:
                            cpu_rate = float(fields[5]) if fields[5] else 0.0
                            mem_usage = float(fields[6]) if fields[6] else 0.0
                            raw_rows.append((cpu_rate, mem_usage))
                        except (ValueError, IndexError):
                            continue

            if not raw_rows:
                raise ValueError("空数据")

            # 值域放缩：task_usage 是单任务级别 (0~1)，需要放缩到系统级 (0~100)
            # 策略：归一化后放大到 [0, 100]，保留原始分布形态
            cpus_raw = [r[0] for r in raw_rows]
            mems_raw = [r[1] for r in raw_rows]
            cpu_max = max(cpus_raw) if max(cpus_raw) > 0 else 1.0
            mem_max = max(mems_raw) if max(mems_raw) > 0 else 1.0

            # 线性放缩到 [0, 100]，保留原始数据的分布特征
            rows = [
                (cpu / cpu_max * 100, mem / mem_max * 100)
                for cpu, mem in raw_rows
            ]

            print(f"✅ 读取完成: {len(rows)} 行有效数据 (原始值域 CPU:[0,{cpu_max:.3f}] MEM:[0,{mem_max:.3f}] → 放缩到 [0,100])", flush=True)
            return rows
    except Exception as e:
        print(f"⚠️ 网络读取失败: {e}", flush=True)
        print("📋 使用内置模拟数据作为备选", flush=True)
        return _generate_simulated_data(max_rows)


def _generate_simulated_data(n: int):
    """
    生成多样化的模拟集群数据（当网络不可用时使用）。
    覆盖: 正常基线 / CPU 突刺 / 错误爆发 / 渐进过载 / 断崖恢复 / 矛盾场景
    """
    import random
    rng = random.Random(42)
    rows = []

    # 场景定义：(名称, 时长占比, CPU分布, MEM分布)
    scenarios = [
        ("normal_low",     0.15, (15, 5),  (35, 5)),
        ("normal_mid",     0.10, (35, 8),  (50, 5)),
        ("cpu_spike",      0.10, (75, 15), (55, 8)),
        ("high_load",      0.12, (82, 10), (72, 8)),
        ("extreme_load",   0.08, (93, 4),  (88, 5)),
        ("error_burst",    0.10, (45, 10), (55, 5)),   # 中等CPU但异常
        ("mem_leak",       0.08, (40, 8),  (85, 8)),   # 内存泄漏
        ("gradual_up",     0.10, None,     None),       # 渐进上升
        ("gradual_down",   0.07, None,     None),       # 渐进下降
        ("cliff_drop",     0.05, (50, 20), (60, 15)),   # 断崖波动
        ("contradictory",  0.05, (88, 5),  (20, 5)),   # CPU高+MEM低
    ]

    idx = 0
    for name, ratio, cpu_params, mem_params in scenarios:
        count = int(n * ratio)
        for j in range(count):
            if name == "gradual_up":
                t = j / max(count, 1)
                cpu = rng.gauss(10 + 80 * t, 8)
                mem = rng.gauss(30 + 50 * t, 5)
            elif name == "gradual_down":
                t = j / max(count, 1)
                cpu = rng.gauss(85 - 60 * t, 8)
                mem = rng.gauss(80 - 40 * t, 5)
            elif name == "cliff_drop":
                # 正常→瞬间拉满→瞬间归零循环
                phase = j % 20
                if phase < 8:
                    cpu = rng.gauss(30, 5)
                    mem = rng.gauss(50, 3)
                elif phase < 10:
                    cpu = rng.gauss(95, 3)
                    mem = rng.gauss(90, 3)
                elif phase < 18:
                    cpu = rng.gauss(95, 3)
                    mem = rng.gauss(90, 3)
                else:
                    cpu = rng.gauss(5, 3)
                    mem = rng.gauss(15, 5)
            else:
                cpu = rng.gauss(*cpu_params) if cpu_params else rng.gauss(30, 10)
                mem = rng.gauss(*mem_params) if mem_params else rng.gauss(50, 10)
            rows.append((max(0, min(100, cpu)), max(0, min(100, mem))))
            idx += 1

    # 补齐不足的部分
    while len(rows) < n:
        cpu = rng.gauss(35, 15)
        mem = rng.gauss(50, 10)
        rows.append((max(0, min(100, cpu)), max(0, min(100, mem))))

    rows = rows[:n]

    cpus = [r[0] for r in rows]
    print(f"✅ 模拟数据生成完成: {len(rows)} 行 (CPU:[{min(cpus):.0f},{max(cpus):.0f}] avg={sum(cpus)/len(cpus):.0f})")
    return rows


# ── 网格搜索参数空间 ──
PARAM_GRID = {
    "alpha_slow": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
    "alpha_fast": [0.50, 0.60, 0.70, 0.80, 0.85, 0.90],
    "beta":       [3.0, 5.0, 8.0, 12.0],
    "inertia":    [0.10, 0.20, 0.30, 0.40, 0.50],
}

# 精简搜索（快速模式）
PARAM_GRID_FAST = {
    "alpha_slow": [0.15, 0.20, 0.30],
    "alpha_fast": [0.70, 0.85, 0.90],
    "beta":       [5.0, 8.0],
    "inertia":    [0.20, 0.30],
}


def run_ema_eval(data: list[tuple], params: dict, ode_cfg: ODEConfig | None = None) -> dict:
    """
    用指定的 EMA 参数运行情绪引擎，返回评估指标。

    参数:
        data: [(cpu, mem), ...] 的指标序列
        params: {"alpha_slow": x, "alpha_fast": x, "beta": x, "inertia": x}
        ode_cfg: ODE 配置

    返回:
        {
            "flicker_rate": float,      # 象限切换频率（越低越好）
            "response_latency": float,  # 突变后首次切换所需步数（越低越好）
            "stability": float,         # 高负载时状态一致性（越高越好）
            "score": float,             # 综合评分（越高越好）
        }
    """
    if ode_cfg is None:
        ode_cfg = ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0)

    ode = ODEDynamics(ode_cfg)
    ema = AdaptiveEMAFilter(
        alpha_slow=params["alpha_slow"],
        alpha_fast=params["alpha_fast"],
        beta=params["beta"],
        inertia=params["inertia"],
    )
    history = MetricsHistory(window_size=10)

    states = []
    for cpu, mem in data:
        # 用简化误差率（CPU高时模拟错误率上升）
        err_proxy = max(0, (cpu - 60) / 40 * 15) if cpu > 60 else max(0, cpu / 30 * 0.5)
        lat_proxy = max(0, (cpu - 50) / 50 * 1000) if cpu > 50 else 50.0

        history.update(cpu, err_proxy, lat_proxy)
        raw_pad = metrics_to_pad(cpu, mem, err_proxy, lat_proxy, history)
        smooth = ema.update(raw_pad)
        states.append(smooth.quadrant.value)

    n = len(states)
    if n < 2:
        return {"flicker_rate": 1.0, "response_latency": 999, "stability": 0.0, "score": 0.0}

    # ── 指标 1: 闪烁率（状态切换频率）──
    flicker_count = sum(1 for i in range(1, n) if states[i] != states[i - 1])
    flicker_rate = flicker_count / (n - 1)

    # ── 指标 2: 突变响应延迟 ──
    # 检测 CPU 从低→高的突变点，计算首次状态切换所需步数
    response_latencies = []
    for i in range(1, n - 10):
        cpu_prev = data[i - 1][0]
        cpu_curr = data[i][0]
        # CPU 突增 > 30%
        if cpu_curr - cpu_prev > 30:
            baseline_state = states[i - 1]
            for j in range(i, min(i + 15, n)):
                if states[j] != baseline_state:
                    response_latencies.append(j - i)
                    break
            else:
                response_latencies.append(15)  # 超时

    avg_response = sum(response_latencies) / len(response_latencies) if response_latencies else 5.0

    # ── 指标 3: 高负载稳定性 ──
    # CPU > 70% 时，状态应一致（不应频繁跳变）
    high_load_states = [states[i] for i in range(n) if data[i][0] > 70]
    if high_load_states:
        most_common = max(set(high_load_states), key=high_load_states.count)
        stability = high_load_states.count(most_common) / len(high_load_states)
    else:
        stability = 1.0

    # ── 综合评分 ──
    # flicker_rate: 越低越好，理想 < 0.1
    # avg_response: 越低越好，理想 < 3
    # stability: 越高越好，理想 > 0.8
    flicker_score = max(0, 1.0 - flicker_rate / 0.3) * 40    # 满分40
    response_score = max(0, 1.0 - avg_response / 10) * 30    # 满分30
    stability_score = stability * 30                           # 满分30
    score = flicker_score + response_score + stability_score

    return {
        "flicker_rate": round(flicker_rate, 4),
        "response_latency": round(avg_response, 2),
        "stability": round(stability, 4),
        "score": round(score, 2),
    }


def grid_search(data: list[tuple], grid: dict) -> list[dict]:
    """执行网格搜索，返回按 score 降序排列的结果"""
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total = len(combos)

    print(f"\n🔍 网格搜索: {total} 组参数组合", flush=True)
    print(f"   参数空间: {', '.join(f'{k}={grid[k]}' for k in keys)}", flush=True)

    results = []
    best_score = -1
    start_time = time.time()

    for idx, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        metrics = run_ema_eval(data, params)

        result = {**params, **metrics}
        results.append(result)

        if metrics["score"] > best_score:
            best_score = metrics["score"]
            best_params = params

        # 进度显示
        if (idx + 1) % max(1, total // 20) == 0 or idx == total - 1:
            elapsed = time.time() - start_time
            eta = elapsed / (idx + 1) * (total - idx - 1)
            print(f"   [{idx+1:4d}/{total}] "
                  f"当前最优 score={best_score:.1f} "
                  f"({best_params['alpha_slow']}/{best_params['alpha_fast']}/"
                  f"{best_params['beta']}/{best_params['inertia']}) "
                  f"已用{elapsed:.0f}s 剩余{eta:.0f}s",
                  flush=True)

    elapsed = time.time() - start_time
    print(f"\n✅ 搜索完成: {elapsed:.1f}s ({total} 组)", flush=True)

    results.sort(key=lambda x: -x["score"])
    return results


def print_results(results: list[dict], top_n: int = 10):
    """打印 Top-N 结果"""
    print(f"\n{'='*90}")
    print(f"  EMA 参数训练结果 Top-{top_n}")
    print(f"{'='*90}")
    print(f"  {'排名':>3s}  {'α_slow':>7s} {'α_fast':>7s} {'β':>5s} {'inertia':>7s}"
          f"  {'闪烁率':>6s} {'响应延迟':>6s} {'稳定性':>6s} {'评分':>6s}")
    print(f"  {'─'*3}  {'─'*7} {'─'*7} {'─'*5} {'─'*7}  {'─'*6} {'─'*6} {'─'*6} {'─'*6}")

    for rank, r in enumerate(results[:top_n], 1):
        marker = " ⭐" if rank == 1 else "   "
        print(f"  {rank:3d}{marker} "
              f"{r['alpha_slow']:7.2f} {r['alpha_fast']:7.2f} {r['beta']:5.1f} {r['inertia']:7.2f}"
              f"  {r['flicker_rate']:6.1%} {r['response_latency']:6.1f}  "
              f"{r['stability']:6.1%} {r['score']:6.1f}")

    # 参数敏感度分析
    if len(results) >= 10:
        print(f"\n{'='*90}")
        print(f"  参数敏感度分析")
        print(f"{'='*90}")

        for param in ["alpha_slow", "alpha_fast", "beta", "inertia"]:
            # 按参数值分组，计算平均 score
            groups = {}
            for r in results:
                val = r[param]
                if val not in groups:
                    groups[val] = []
                groups[val].append(r["score"])
            avg_scores = {v: sum(s) / len(s) for v, s in groups.items()}
            best_val = max(avg_scores, key=avg_scores.get)
            worst_val = min(avg_scores, key=avg_scores.get)
            spread = avg_scores[best_val] - avg_scores[worst_val]
            print(f"  {param:12s}: 最优={best_val:.2f} (avg_score={avg_scores[best_val]:.1f})"
                  f"  最差={worst_val:.2f} (avg_score={avg_scores[worst_val]:.1f})"
                  f"  影响度={spread:.1f}")


def save_results(results: list[dict], path: str):
    """保存完整结果到 JSON"""
    output = {
        "total_combos": len(results),
        "top_10": results[:10],
        "best_params": {k: results[0][k] for k in ["alpha_slow", "alpha_fast", "beta", "inertia"]},
        "best_metrics": {k: results[0][k] for k in ["flicker_rate", "response_latency", "stability", "score"]},
        "all_results": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 完整结果已保存: {path}")


def main():
    parser = argparse.ArgumentParser(description="EMA 参数网格搜索训练")
    parser.add_argument("--steps", type=int, default=5000, help="数据步数")
    parser.add_argument("--part", type=int, default=0, help="task_usage 分片号 (gcs 模式)")
    parser.add_argument("--fast", action="store_true", help="精简搜索（快速模式）")
    parser.add_argument("--output", type=str, default="ema_train_results.json", help="结果输出路径")
    parser.add_argument("--data", type=str, default="mixed", choices=["gcs", "sim", "mixed"],
                        help="数据源: gcs=Google Cluster Data, sim=模拟数据, mixed=两者合并(默认)")
    args = parser.parse_args()

    print("=" * 90)
    print("  EMA 参数训练 V5.0")
    print("=" * 90, flush=True)
    print(f"  数据步数: {args.steps}")
    print(f"  数据源:   {args.data}")
    print(f"  搜索模式: {'精简' if args.fast else '完整'}")

    # 1. 获取数据
    data = []
    if args.data in ("gcs", "mixed"):
        gcs_data = stream_cluster_data(part=args.part, max_rows=args.steps // 2 if args.data == "mixed" else args.steps)
        data.extend(gcs_data)
    if args.data in ("sim", "mixed"):
        sim_count = args.steps // 2 if args.data == "mixed" else args.steps
        sim_data = _generate_simulated_data(sim_count)
        data.extend(sim_data)

    if not data:
        print("❌ 无有效数据，退出", flush=True)
        return

    # 数据统计
    cpus = [d[0] for d in data]
    mems = [d[1] for d in data]
    print(f"\n📊 数据统计:")
    print(f"  CPU: min={min(cpus):.1f}% max={max(cpus):.1f}% avg={sum(cpus)/len(cpus):.1f}%")
    print(f"  MEM: min={min(mems):.1f}% max={max(mems):.1f}% avg={sum(mems)/len(mems):.1f}%")

    # 2. 网格搜索
    grid = PARAM_GRID_FAST if args.fast else PARAM_GRID
    results = grid_search(data, grid)

    # 3. 打印结果
    print_results(results, top_n=15)

    # 4. 保存结果
    save_results(results, args.output)

    # 5. 输出推荐参数
    best = results[0]
    print(f"\n{'='*90}")
    print(f"  🏆 推荐 EMA 参数")
    print(f"{'='*90}")
    print(f"  alpha_slow = {best['alpha_slow']}")
    print(f"  alpha_fast = {best['alpha_fast']}")
    print(f"  beta       = {best['beta']}")
    print(f"  inertia    = {best['inertia']}")
    print(f"  ────────────────────")
    print(f"  闪烁率     = {best['flicker_rate']:.1%}")
    print(f"  响应延迟   = {best['response_latency']:.1f} 步")
    print(f"  稳定性     = {best['stability']:.1%}")
    print(f"  综合评分   = {best['score']:.1f}/100")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
