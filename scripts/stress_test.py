"""
压力测试 — 脏数据/极端数据轰炸引擎

三种攻击集：
1. 白噪声集：指标在基准线上下随机微小波动（验证防抖）
2. 断崖集：指标瞬间归零或瞬间拉满（验证边界兜底）
3. 矛盾集：物理层指标极差，但业务层指标极好（验证权重优先级）

记录所有结果到表格，审查闪烁和概率坍塌现象。
"""
import sys, io, os, random, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pad_model import PADState
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from plutchik import classify_plutchik, format_plutchik
from ema_filter import AdaptiveEMAFilter

rng = random.Random(42)


def run_sequence(name: str, steps: list[dict], ode_cfg: ODEConfig = None) -> list[dict]:
    """运行一组序列，记录每步结果"""
    from ode_dynamics import DEFAULT_ODE_CONFIG
    if ode_cfg is None:
        ode_cfg = DEFAULT_ODE_CONFIG

    ode = ODEDynamics(ode_cfg)
    ema = AdaptiveEMAFilter()
    results = []
    prev_state = None

    for i, step in enumerate(steps):
        target = compute_target(step["cpu"], step["mem"], step["err"], step["lat"])
        emo = ode.step(target)
        pad = PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()
        smooth = ema.update(pad)
        plutchik = classify_plutchik(smooth.p, smooth.a, smooth.d)

        state_change = prev_state is not None and smooth.quadrant != prev_state
        prev_state = smooth.quadrant

        results.append({
            "step": i + 1,
            "cpu": step["cpu"], "mem": step["mem"],
            "err": step["err"], "lat": step["lat"],
            "p": round(smooth.p, 3), "a": round(smooth.a, 3),
            "d": round(smooth.d, 3), "v": round(smooth.volatility, 3),
            "state": smooth.quadrant.value,
            "plutchik": format_plutchik(plutchik),
            "state_change": state_change,
            "tag": step.get("tag", ""),
        })

    return results


# ============================================================
# 攻击集1：白噪声（100步，验证防抖）
# ============================================================
def gen_white_noise(baseline_cpu=30, baseline_mem=50, steps=100):
    """基准线+/-5%随机波动"""
    seq = []
    for i in range(steps):
        seq.append({
            "cpu": baseline_cpu + rng.uniform(-5, 5),
            "mem": baseline_mem + rng.uniform(-5, 5),
            "err": max(0, 0.5 + rng.uniform(-0.3, 0.3)),
            "lat": max(0, 50 + rng.uniform(-20, 20)),
            "tag": "noise",
        })
    return seq


# ============================================================
# 攻击集2：断崖（瞬间归零/拉满）
# ============================================================
def gen_cliff(steps_per_phase=10):
    """正常→瞬间拉满→瞬间归零→正常，重复3轮"""
    seq = []
    for round_num in range(3):
        # 正常
        for _ in range(steps_per_phase):
            seq.append({"cpu": 30, "mem": 50, "err": 0.5, "lat": 50, "tag": f"normal_r{round_num}"})
        # 瞬间拉满
        seq.append({"cpu": 99, "mem": 98, "err": 80, "lat": 15000, "tag": f"cliff_up_r{round_num}"})
        # 拉满持续
        for _ in range(steps_per_phase):
            seq.append({"cpu": 99, "mem": 98, "err": 80, "lat": 15000, "tag": f"high_r{round_num}"})
        # 瞬间归零
        seq.append({"cpu": 1, "mem": 10, "err": 0, "lat": 1, "tag": f"cliff_down_r{round_num}"})
        # 归零持续
        for _ in range(steps_per_phase):
            seq.append({"cpu": 1, "mem": 10, "err": 0, "lat": 1, "tag": f"low_r{round_num}"})
    return seq


# ============================================================
# 攻击集3：矛盾（物理层差+业务层好，反之亦然）
# ============================================================
def gen_contradiction(steps_per_case=15):
    """多种矛盾组合"""
    seq = []
    cases = [
        # 物理层差，业务层好
        {"cpu": 95, "mem": 92, "err": 0, "lat": 50, "tag": "物理差业务好:CPU+MEM满+零错误"},
        {"cpu": 90, "mem": 88, "err": 0.1, "lat": 30, "tag": "物理差业务好:高负载+极低错误"},
        # 物理层好，业务层差
        {"cpu": 10, "mem": 20, "err": 50, "lat": 8000, "tag": "物理好业务差:空闲+大量错误"},
        {"cpu": 5, "mem": 15, "err": 30, "lat": 5000, "tag": "物理好业务差:极低负载+高错误"},
        # 混合矛盾
        {"cpu": 80, "mem": 30, "err": 40, "lat": 200, "tag": "混合:CPU高+MEM低+错误高"},
        {"cpu": 20, "mem": 90, "err": 0, "lat": 3000, "tag": "混合:CPU低+MEM高+零错误+高延迟"},
        {"cpu": 50, "mem": 50, "err": 25, "lat": 100, "tag": "混合:中等负载+高错误+低延迟"},
        {"cpu": 99, "mem": 5, "err": 0, "lat": 50, "tag": "混合:CPU满+MEM空+零错误"},
    ]
    for case in cases:
        for _ in range(steps_per_phase := steps_per_case):
            seq.append({
                "cpu": case["cpu"] + rng.uniform(-2, 2),
                "mem": case["mem"] + rng.uniform(-2, 2),
                "err": max(0, case["err"] + rng.uniform(-1, 1)),
                "lat": max(0, case["lat"] + rng.uniform(-50, 50)),
                "tag": case["tag"],
            })
    return seq


def count_flickers(results: list[dict]) -> dict:
    """统计闪烁（连续状态切换次数）"""
    flickers = 0
    for i in range(1, len(results)):
        if results[i]["state"] != results[i-1]["state"]:
            flickers += 1
    return {
        "total_steps": len(results),
        "state_changes": flickers,
        "flicker_rate": flickers / max(1, len(results) - 1),
    }


def main():
    print("=" * 100)
    print("  压力测试 — 脏数据/极端数据轰炸")
    print("=" * 100, flush=True)

    all_results = {}

    # === 攻击集1：白噪声 ===
    print(f"\n{'='*100}")
    print("  攻击集1: 白噪声 (100步，基准线±5%波动)")
    print(f"{'='*100}")
    noise_seq = gen_white_noise(baseline_cpu=30, baseline_mem=50, steps=100)
    noise_results = run_sequence("白噪声", noise_seq)
    flicker = count_flickers(noise_results)
    all_results["white_noise"] = {"results": noise_results, "flicker": flicker}

    print(f"\n  防抖评估:")
    print(f"    总步数: {flicker['total_steps']}")
    print(f"    状态切换: {flicker['state_changes']}次")
    print(f"    闪烁率: {flicker['flicker_rate']:.1%}")
    print(f"    判定: {'✅ 稳定(闪烁率<10%)' if flicker['flicker_rate'] < 0.1 else '⚠️ 闪烁' if flicker['flicker_rate'] < 0.3 else '❌ 严重闪烁'}")

    # 前20步详情
    print(f"\n  前20步详情:")
    print(f"  {'步':>3s}  {'CPU':>5s}  {'MEM':>5s}  {'ERR':>5s}  {'LAT':>5s}  | {'P':>6s} {'A':>6s} {'D':>6s} | {'状态':8s} {'Plutchik':14s} {'切换'}")
    for r in noise_results[:20]:
        chg = "←" if r["state_change"] else ""
        print(f"  {r['step']:3d}  {r['cpu']:5.1f}  {r['mem']:5.1f}  {r['err']:5.2f}  {r['lat']:5.0f}  | {r['p']:+.3f} {r['a']:+.3f} {r['d']:+.3f} | {r['state']:8s} {r['plutchik']:14s} {chg}")

    # === 攻击集2：断崖 ===
    print(f"\n{'='*100}")
    print("  攻击集2: 断崖 (正常→瞬间拉满→瞬间归零，3轮)")
    print(f"{'='*100}")
    cliff_seq = gen_cliff(steps_per_phase=10)
    cliff_results = run_sequence("断崖", cliff_seq)
    flicker2 = count_flickers(cliff_results)
    all_results["cliff"] = {"results": cliff_results, "flicker": flicker2}

    print(f"\n  边界兜底评估:")
    print(f"    总步数: {flicker2['total_steps']}")
    print(f"    状态切换: {flicker2['state_changes']}次")

    # 找到断崖点
    cliff_ups = [r for r in cliff_results if "cliff_up" in r["tag"]]
    cliff_downs = [r for r in cliff_results if "cliff_down" in r["tag"]]

    print(f"\n  断崖瞬间（拉满）:")
    for r in cliff_ups:
        print(f"    step {r['step']:3d}: CPU={r['cpu']:.0f}% ERR={r['err']:.0f}% LAT={r['lat']:.0f}ms → {r['state']} {r['plutchik']}")

    print(f"\n  断崖瞬间（归零）:")
    for r in cliff_downs:
        print(f"    step {r['step']:3d}: CPU={r['cpu']:.0f}% ERR={r['err']:.0f}% LAT={r['lat']:.0f}ms → {r['state']} {r['plutchik']}")

    # 拉满/归零持续期的状态稳定性
    high_phases = [r for r in cliff_results if "high_" in r["tag"]]
    low_phases = [r for r in cliff_results if "low_" in r["tag"]]
    high_states = set(r["state"] for r in high_phases)
    low_states = set(r["state"] for r in low_phases)

    print(f"\n  持续期稳定性:")
    print(f"    拉满持续({len(high_phases)}步): 状态={high_states} {'✅ 稳定' if len(high_states)==1 else '⚠️ 漂移'}")
    print(f"    归零持续({len(low_phases)}步): 状态={low_states} {'✅ 稳定' if len(low_states)==1 else '⚠️ 漂移'}")

    # 全部断崖详情
    print(f"\n  全部断崖序列详情:")
    print(f"  {'步':>3s}  {'标签':18s}  {'CPU':>5s}  {'MEM':>5s}  {'ERR':>5s}  {'LAT':>6s}  | {'P':>6s} {'A':>6s} {'D':>6s} | {'状态':8s} {'Plutchik':14s} {'切换'}")
    for r in cliff_results:
        chg = "←" if r["state_change"] else ""
        print(f"  {r['step']:3d}  {r['tag']:18s}  {r['cpu']:5.1f}  {r['mem']:5.1f}  {r['err']:5.2f}  {r['lat']:6.0f}  | {r['p']:+.3f} {r['a']:+.3f} {r['d']:+.3f} | {r['state']:8s} {r['plutchik']:14s} {chg}")

    # === 攻击集3：矛盾 ===
    print(f"\n{'='*100}")
    print("  攻击集3: 矛盾指标 (8种矛盾组合×15步)")
    print(f"{'='*100}")
    contra_seq = gen_contradiction(steps_per_case=15)
    contra_results = run_sequence("矛盾", contra_seq)
    flicker3 = count_flickers(contra_results)
    all_results["contradiction"] = {"results": contra_results, "flicker": flicker3}

    print(f"\n  权重优先级评估:")
    print(f"    总步数: {flicker3['total_steps']}")
    print(f"    状态切换: {flicker3['state_changes']}次")

    # 按矛盾类型分组
    tag_groups = {}
    for r in contra_results:
        tag = r["tag"]
        if tag not in tag_groups:
            tag_groups[tag] = []
        tag_groups[tag].append(r)

    print(f"\n  各矛盾组合判定:")
    for tag, rs in tag_groups.items():
        states = [r["state"] for r in rs]
        most_common = max(set(states), key=states.count)
        stability = states.count(most_common) / len(states)
        avg_p = sum(r["p"] for r in rs) / len(rs)
        avg_a = sum(r["a"] for r in rs) / len(rs)
        avg_d = sum(r["d"] for r in rs) / len(rs)
        print(f"    {tag:30s} → {most_common:8s} (稳定{stability:.0%}) P={avg_p:+.2f} A={avg_a:+.2f} D={avg_d:+.2f}")

    # 矛盾序列详情
    print(f"\n  全部矛盾序列详情:")
    print(f"  {'步':>3s}  {'标签':30s}  {'CPU':>5s}  {'MEM':>5s}  {'ERR':>5s}  {'LAT':>6s}  | {'P':>6s} {'A':>6s} {'D':>6s} | {'状态':8s} {'Plutchik':14s} {'切换'}")
    for r in contra_results:
        chg = "←" if r["state_change"] else ""
        print(f"  {r['step']:3d}  {r['tag']:30s}  {r['cpu']:5.1f}  {r['mem']:5.1f}  {r['err']:5.2f}  {r['lat']:6.0f}  | {r['p']:+.3f} {r['a']:+.3f} {r['d']:+.3f} | {r['state']:8s} {r['plutchik']:14s} {chg}")

    # === 总结 ===
    print(f"\n{'='*100}")
    print("  总结")
    print(f"{'='*100}")

    for name, data in all_results.items():
        f = data["flicker"]
        label = {"white_noise": "白噪声防抖", "cliff": "断崖兜底", "contradiction": "矛盾权重"}[name]
        flicker_ok = f["flicker_rate"] < 0.1 if name == "white_noise" else f["state_changes"] < len(data["results"]) * 0.5
        print(f"  {label:10s}: 切换{f['state_changes']}/{f['total_steps']}步 闪烁率{f['flicker_rate']:.1%} {'✅' if flicker_ok else '⚠️'}")

    # 保存完整结果
    out_path = os.path.join(os.path.dirname(__file__), "stress_test_results.json")
    save_data = {}
    for name, data in all_results.items():
        save_data[name] = {
            "flicker": data["flicker"],
            "results": data["results"],
        }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  完整结果已保存: {out_path}")


if __name__ == "__main__":
    main()
