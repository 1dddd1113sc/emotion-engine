"""
10分钟极限攻击测试 — 每秒随机生成极端数据轰炸引擎

攻击策略：
- 30% 概率：极端异常（CPU 95-99%, ERR 30-80%, LAT 5000-15000ms）
- 20% 概率：断崖跳变（从正常瞬间拉满或反之）
- 20% 概率：矛盾指标（物理差+业务好 或反之）
- 15% 概率：边界值（CPU 45-55%, ERR 4-6%）
- 15% 概率：正常波动（CPU 10-40%, ERR 0-2%）

记录每秒结果，输出闪烁统计和异常检测率。
"""
import sys, io, random, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pad_model import PADState
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from plutchik import classify_plutchik, format_plutchik
from ema_filter import AdaptiveEMAFilter
from emotion_output import generate_output, format_top2_short

rng = random.Random(int(time.time()))

DURATION = 600  # 10分钟
INTERVAL = 1.0  # 每秒


def generate_adversarial_step(prev_cpu=30, prev_mem=50, prev_err=0.5, prev_lat=50):
    """生成一步攻击数据"""
    r = rng.random()

    if r < 0.30:
        # 极端异常
        cpu = rng.uniform(90, 99.9)
        mem = rng.uniform(85, 99)
        err = rng.uniform(20, 80)
        lat = rng.uniform(3000, 15000)
        tag = "EXTREME"

    elif r < 0.50:
        # 断崖跳变
        if rng.random() < 0.5:
            # 正常→拉满
            cpu = rng.uniform(92, 99)
            mem = rng.uniform(88, 98)
            err = rng.uniform(15, 60)
            lat = rng.uniform(2000, 10000)
            tag = "CLIFF_UP"
        else:
            # 拉满→归零
            cpu = rng.uniform(0.5, 5)
            mem = rng.uniform(5, 20)
            err = 0
            lat = rng.uniform(1, 10)
            tag = "CLIFF_DOWN"

    elif r < 0.70:
        # 矛盾指标
        sub = rng.random()
        if sub < 0.33:
            # 物理差+业务好
            cpu = rng.uniform(88, 99)
            mem = rng.uniform(85, 95)
            err = rng.uniform(0, 0.5)
            lat = rng.uniform(20, 100)
            tag = "CONTRA_BAD_GOOD"
        elif sub < 0.66:
            # 物理好+业务差
            cpu = rng.uniform(3, 15)
            mem = rng.uniform(10, 30)
            err = rng.uniform(20, 60)
            lat = rng.uniform(3000, 10000)
            tag = "CONTRA_GOOD_BAD"
        else:
            # CPU满+MEM空
            cpu = rng.uniform(95, 99.9)
            mem = rng.uniform(2, 8)
            err = rng.uniform(0, 1)
            lat = rng.uniform(20, 100)
            tag = "CONTRA_CPU_FULL"

    elif r < 0.85:
        # 边界值
        cpu = rng.uniform(45, 55)
        mem = rng.uniform(40, 60)
        err = rng.uniform(4, 6)
        lat = rng.uniform(200, 500)
        tag = "BOUNDARY"

    else:
        # 正常波动
        cpu = rng.uniform(10, 40)
        mem = rng.uniform(30, 60)
        err = rng.uniform(0, 2)
        lat = rng.uniform(20, 150)
        tag = "NORMAL"

    # 5%概率注入脏数据
    if rng.random() < 0.05:
        dirty = rng.choice(["null_cpu", "null_err", "spike_lat", "negative"])
        if dirty == "null_cpu":
            cpu = None
            tag += "+DIRTY"
        elif dirty == "null_err":
            err = None
            tag += "+DIRTY"
        elif dirty == "spike_lat":
            lat = rng.uniform(50000, 100000)
            tag += "+DIRTY"
        elif dirty == "negative":
            cpu = -rng.uniform(1, 10)
            tag += "+DIRTY"

    return cpu, mem, err, lat, tag


def safe_val(v, default=0.0):
    """处理None和负值"""
    if v is None:
        return default
    return max(0, v)


def main():
    print("=" * 90)
    print(f"  10分钟极限攻击测试 — {DURATION}秒，每秒随机极端数据")
    print("=" * 90, flush=True)

    ode = ODEDynamics(ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0))
    ema = AdaptiveEMAFilter()

    results = []
    prev_state = None
    flicker_count = 0
    tag_counts = {}
    dirty_count = 0
    anomaly_states = {"过载", "低落", "警戒"}

    start_time = time.time()

    for step in range(DURATION):
        # 生成攻击数据
        cpu_raw, mem_raw, err_raw, lat_raw, tag = generate_adversarial_step()

        # 脏数据处理
        if "DIRTY" in tag:
            dirty_count += 1

        cpu = safe_val(cpu_raw, 30)
        mem = safe_val(mem_raw, 50)
        err = safe_val(err_raw, 0.5)
        lat = safe_val(lat_raw, 50)

        # ODE计算
        target = compute_target(cpu, mem, err, lat)
        emo = ode.step(target)
        pad = PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()
        smooth = ema.update(pad)
        plutchik = classify_plutchik(smooth.p, smooth.a, smooth.d)

        # 状态切换检测
        state_change = prev_state is not None and smooth.quadrant != prev_state
        if state_change:
            flicker_count += 1
        prev_state = smooth.quadrant

        # 统计
        tag_base = tag.split("+")[0]
        tag_counts[tag_base] = tag_counts.get(tag_base, 0) + 1

        is_anomaly = smooth.quadrant.value in anomaly_states

        # 生成Top-2输出
        payload = generate_output(smooth, real_cpu=cpu, real_mem=mem)
        top2_desc = format_top2_short(payload)

        result = {
            "step": step + 1,
            "tag": tag,
            "cpu": round(cpu, 1), "mem": round(mem, 1),
            "err": round(err, 2), "lat": round(lat, 0),
            "p": round(smooth.p, 3), "a": round(smooth.a, 3),
            "d": round(smooth.d, 3),
            "state": smooth.quadrant.value,
            "plutchik": format_plutchik(plutchik),
            "top2": top2_desc,
            "cluster": payload.cluster.value,
            "cluster_emoji": payload.cluster_emoji,
            "intent": payload.intent,
            "confidence": payload.confidence,
            "state_change": state_change,
            "is_anomaly": is_anomaly,
        }
        results.append(result)

        # 实时输出（每10步或状态切换时）
        if step % 10 == 0 or state_change or "DIRTY" in tag:
            chg = " <<<" if state_change else ""
            dirty = " [DIRTY]" if "DIRTY" in tag else ""
            anomaly = " !!!" if is_anomaly else ""
            print(f"[{step+1:04d}] {tag:20s} CPU={cpu:5.1f} ERR={err:5.1f} LAT={lat:6.0f}"
                  f" | P={smooth.p:+.2f} A={smooth.a:+.2f} D={smooth.d:+.2f}"
                  f" | {top2_desc}{chg}{dirty}{anomaly}",
                  flush=True)

        time.sleep(INTERVAL)

    elapsed = time.time() - start_time

    # === 汇总 ===
    print(f"\n{'='*90}")
    print(f"  10分钟极限攻击测试结果")
    print(f"{'='*90}")

    total = len(results)
    state_changes = sum(1 for r in results if r["state_change"])
    anomaly_count = sum(1 for r in results if r["is_anomaly"])

    print(f"\n  运行时间:     {elapsed:.0f}s ({elapsed/60:.1f}分钟)")
    print(f"  总步数:       {total}")
    print(f"  状态切换:     {state_changes}次 ({state_changes/total:.1%})")
    print(f"  脏数据注入:   {dirty_count}次 ({dirty_count/total:.1%})")
    print(f"  异常状态触发: {anomaly_count}次 ({anomaly_count/total:.1%})")

    # 状态分布
    print(f"\n  情绪状态分布:")
    state_dist = {}
    for r in results:
        state_dist[r["state"]] = state_dist.get(r["state"], 0) + 1
    for s, cnt in sorted(state_dist.items(), key=lambda x: -x[1]):
        bar = "█" * int(cnt / total * 50)
        print(f"    {s:8s} {bar} {cnt} ({cnt/total:.1%})")

    # 攻击类型分布
    print(f"\n  攻击类型分布:")
    for tag, cnt in sorted(tag_counts.items(), key=lambda x: -x[1]):
        bar = "█" * int(cnt / total * 50)
        print(f"    {tag:20s} {bar} {cnt} ({cnt/total:.1%})")

    # A值统计（检测坍塌）
    a_values = [r["a"] for r in results]
    a_max = max(a_values)
    a_min = min(a_values)
    a_stuck_high = sum(1 for a in a_values if a > 0.95)
    a_stuck_low = sum(1 for a in a_values if a < -0.95)

    print(f"\n  A值统计:")
    print(f"    范围: [{a_min:+.3f}, {a_max:+.3f}]")
    print(f"    卡在>0.95: {a_stuck_high}步 ({a_stuck_high/total:.1%})")
    print(f"    卡在<-0.95: {a_stuck_low}步 ({a_stuck_low/total:.1%})")
    print(f"    坍塌判定: {'✅ 无坍塌' if a_stuck_high < 10 and a_stuck_low < 10 else '⚠️ 存在坍塌'}")

    # 闪烁分析
    print(f"\n  闪烁分析:")
    # 连续闪烁检测（3步内切换2次以上）
    rapid_flicker = 0
    for i in range(2, len(results)):
        if results[i]["state_change"] and results[i-1]["state_change"]:
            rapid_flicker += 1
    print(f"    总切换: {state_changes}次")
    print(f"    连续闪烁(3步内2次): {rapid_flicker}次")
    print(f"    闪烁率: {state_changes/total:.1%}")
    print(f"    判定: {'✅ 稳定' if state_changes/total < 0.15 else '⚠️ 闪烁较多' if state_changes/total < 0.3 else '❌ 严重闪烁'}")

    # 每分钟统计
    print(f"\n  每分钟统计:")
    print(f"  {'分钟':>4s}  {'步数':>4s}  {'切换':>4s}  {'异常':>4s}  {'脏数据':>4s}  {'A_max':>6s}  {'A_min':>6s}")
    for minute in range(10):
        start = minute * 60
        end = min(start + 60, total)
        chunk = results[start:end]
        if not chunk:
            break
        chg = sum(1 for r in chunk if r["state_change"])
        anom = sum(1 for r in chunk if r["is_anomaly"])
        dirty = sum(1 for r in chunk if "DIRTY" in r["tag"])
        a_max_c = max(r["a"] for r in chunk)
        a_min_c = min(r["a"] for r in chunk)
        print(f"  {minute+1:4d}  {len(chunk):4d}  {chg:4d}  {anom:4d}  {dirty:4d}  {a_max_c:+.3f}  {a_min_c:+.3f}")

    # 保存
    import os
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stress_10min_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  完整结果已保存: {out_path}")


if __name__ == "__main__":
    main()
