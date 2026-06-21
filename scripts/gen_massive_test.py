"""
大规模测试数据生成器 + 批量评估

生成1000组测试用例，覆盖：
- 随机正常态（40%）
- 随机异常态（30%）
- 边界值（10%）
- 矛盾指标（10%）
- 极端值（10%）
"""
import os
import sys, io, random, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pad_model import PADState
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from plutchik import classify_plutchik, format_plutchik
from template_engine import generate_expression

rng = random.Random(42)  # 回到原始种子对比


def generate_case(case_id: int) -> dict:
    """生成一组测试用例"""
    category = rng.choices(
        ["normal", "anomaly", "boundary", "contradiction", "extreme"],
        weights=[40, 30, 10, 10, 10]
    )[0]

    if category == "normal":
        cpu = rng.uniform(2, 45)
        mem = rng.uniform(20, 65)
        err = rng.uniform(0, 2)
        lat = rng.uniform(5, 200)
        expect_alert = False

    elif category == "anomaly":
        sub = rng.choice(["error_spike", "overload", "mem_leak", "latency"])
        if sub == "error_spike":
            cpu = rng.uniform(20, 60)
            mem = rng.uniform(40, 70)
            err = rng.uniform(10, 50)
            lat = rng.uniform(200, 2000)
        elif sub == "overload":
            cpu = rng.uniform(85, 99)
            mem = rng.uniform(80, 98)
            err = rng.uniform(0, 15)
            lat = rng.uniform(500, 5000)
        elif sub == "mem_leak":
            cpu = rng.uniform(10, 40)
            mem = rng.uniform(85, 98)
            err = rng.uniform(0, 3)
            lat = rng.uniform(50, 500)
        else:  # latency
            cpu = rng.uniform(10, 50)
            mem = rng.uniform(30, 60)
            err = rng.uniform(0, 5)
            lat = rng.uniform(2000, 8000)
        expect_alert = True

    elif category == "boundary":
        boundary = rng.choice(["cpu50", "cpu80", "cpu95", "err5", "err15"])
        if boundary == "cpu50":
            cpu = rng.uniform(48, 52)
            mem = rng.uniform(35, 50)
            err = rng.uniform(0, 1)
            lat = rng.uniform(30, 150)
        elif boundary == "cpu80":
            cpu = rng.uniform(78, 82)
            mem = rng.uniform(65, 80)
            err = rng.uniform(0, 3)
            lat = rng.uniform(100, 400)
        elif boundary == "cpu95":
            cpu = rng.uniform(93, 97)
            mem = rng.uniform(85, 95)
            err = rng.uniform(0, 10)
            lat = rng.uniform(200, 3000)
        elif boundary == "err5":
            cpu = rng.uniform(20, 60)
            mem = rng.uniform(40, 70)
            err = rng.uniform(4, 6)
            lat = rng.uniform(100, 500)
        else:  # err15
            cpu = rng.uniform(30, 70)
            mem = rng.uniform(45, 75)
            err = rng.uniform(13, 17)
            lat = rng.uniform(300, 1000)
        expect_alert = err > 10 or cpu > 90

    elif category == "contradiction":
        sub = rng.choice(["low_cpu_high_lat", "high_cpu_no_err", "low_cpu_high_err"])
        if sub == "low_cpu_high_lat":
            cpu = rng.uniform(3, 20)
            mem = rng.uniform(15, 40)
            err = rng.uniform(0, 3)
            lat = rng.uniform(2000, 8000)
        elif sub == "high_cpu_no_err":
            cpu = rng.uniform(85, 98)
            mem = rng.uniform(60, 85)
            err = rng.uniform(0, 0.5)
            lat = rng.uniform(30, 200)
        else:  # low_cpu_high_err
            cpu = rng.uniform(5, 25)
            mem = rng.uniform(20, 50)
            err = rng.uniform(15, 40)
            lat = rng.uniform(500, 3000)
        expect_alert = sub != "high_cpu_no_err"

    else:  # extreme
        sub = rng.choice(["all_max", "all_min", "spike"])
        if sub == "all_max":
            cpu = rng.uniform(95, 99.9)
            mem = rng.uniform(95, 99.9)
            err = rng.uniform(40, 80)
            lat = rng.uniform(5000, 15000)
        elif sub == "all_min":
            cpu = rng.uniform(0.5, 5)
            mem = rng.uniform(5, 20)
            err = 0
            lat = rng.uniform(1, 10)
        else:  # spike
            cpu = rng.uniform(90, 99)
            mem = rng.uniform(50, 70)
            err = rng.uniform(5, 20)
            lat = rng.uniform(1000, 5000)
        expect_alert = sub != "all_min"

    return {
        "id": f"T{case_id:04d}",
        "category": category,
        "cpu": round(cpu, 1),
        "mem": round(mem, 1),
        "err": round(err, 2),
        "lat": round(lat, 0),
        "expect_alert": expect_alert,
    }


def evaluate_case(tc: dict) -> dict:
    """评估单组"""
    ode = ODEDynamics(ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0))
    for _ in range(20):
        target = compute_target(tc["cpu"], tc["mem"], tc["err"], tc["lat"])
        emo = ode.step(target)

    pad = PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()
    result = generate_expression(pad, real_cpu=tc["cpu"], real_mem=tc["mem"])
    plutchik = classify_plutchik(emo.p, emo.a, emo.d)

    is_alert = pad.quadrant.value in ["过载", "低落", "警戒"]
    correct_alert = (is_alert == tc["expect_alert"])

    return {
        "id": tc["id"],
        "category": tc["category"],
        "cpu": tc["cpu"], "mem": tc["mem"], "err": tc["err"], "lat": tc["lat"],
        "expect_alert": tc["expect_alert"],
        "state": pad.quadrant.value,
        "plutchik": format_plutchik(plutchik),
        "p": round(emo.p, 3), "a": round(emo.a, 3), "d": round(emo.d, 3),
        "is_alert": is_alert,
        "correct_alert": correct_alert,
        "text": result.text,
    }


def main():
    N = 1000
    print(f"=== 生成 {N} 组测试用例 ===", flush=True)

    cases = [generate_case(i) for i in range(N)]
    cat_counts = {}
    for c in cases:
        cat_counts[c["category"]] = cat_counts.get(c["category"], 0) + 1
    for cat, cnt in sorted(cat_counts.items()):
        print(f"  {cat}: {cnt}")

    print(f"\n=== 批量评估 ===", flush=True)
    t0 = time.time()
    results = [evaluate_case(c) for c in cases]
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s ({elapsed/N*1000:.1f}ms/组)")

    # 汇总
    total = len(results)
    correct = sum(1 for r in results if r["correct_alert"])
    false_alarm = sum(1 for r in results if not r["expect_alert"] and r["is_alert"])
    missed = sum(1 for r in results if r["expect_alert"] and not r["is_alert"])

    print(f"\n=== 总体结果 ===")
    print(f"  总计: {total}")
    print(f"  报警准确率: {correct}/{total} = {correct/total:.1%}")
    print(f"  误报: {false_alarm} ({false_alarm/total:.1%})")
    print(f"  漏报: {missed} ({missed/total:.1%})")

    # 按类别
    print(f"\n=== 按类别 ===")
    for cat in ["normal", "anomaly", "boundary", "contradiction", "extreme"]:
        cat_r = [r for r in results if r["category"] == cat]
        if not cat_r:
            continue
        cat_correct = sum(1 for r in cat_r if r["correct_alert"])
        cat_fa = sum(1 for r in cat_r if not r["expect_alert"] and r["is_alert"])
        cat_miss = sum(1 for r in cat_r if r["expect_alert"] and not r["is_alert"])
        print(f"  {cat:14s}: {cat_correct}/{len(cat_r)}={cat_correct/len(cat_r):.1%} "
              f"误报={cat_fa} 漏报={cat_miss}")

    # 情绪分布
    print(f"\n=== 情绪状态分布 ===")
    state_counts = {}
    for r in results:
        state_counts[r["state"]] = state_counts.get(r["state"], 0) + 1
    for s, cnt in sorted(state_counts.items(), key=lambda x: -x[1]):
        bar = "█" * int(cnt / total * 40)
        print(f"  {s:8s} {bar} {cnt} ({cnt/total:.1%})")

    # Plutchik分布
    print(f"\n=== Plutchik情绪分布 ===")
    pl_counts = {}
    for r in results:
        p = r["plutchik"].split("(")[0]  # 取主情绪
        pl_counts[p] = pl_counts.get(p, 0) + 1
    for p, cnt in sorted(pl_counts.items(), key=lambda x: -x[1])[:8]:
        bar = "█" * int(cnt / total * 40)
        print(f"  {p:14s} {bar} {cnt} ({cnt/total:.1%})")

    # 漏报详情（按类别）
    missed_cases = [r for r in results if r["expect_alert"] and not r["is_alert"]]
    if missed_cases:
        print(f"\n=== 漏报详情 ({len(missed_cases)}组) ===")
        miss_by_cat = {}
        for r in missed_cases:
            miss_by_cat.setdefault(r["category"], []).append(r)
        for cat, rs in miss_by_cat.items():
            print(f"  [{cat}] {len(rs)}组")
            for r in rs[:3]:
                print(f"    {r['id']} CPU={r['cpu']} MEM={r['mem']} ERR={r['err']} LAT={r['lat']}"
                      f" → {r['state']} {r['plutchik']}")

    # 误报详情
    fa_cases = [r for r in results if not r["expect_alert"] and r["is_alert"]]
    if fa_cases:
        print(f"\n=== 误报详情 ({len(fa_cases)}组) ===")
        fa_by_cat = {}
        for r in fa_cases:
            fa_by_cat.setdefault(r["category"], []).append(r)
        for cat, rs in fa_by_cat.items():
            print(f"  [{cat}] {len(rs)}组")
            for r in rs[:3]:
                print(f"    {r['id']} CPU={r['cpu']} MEM={r['mem']} ERR={r['err']} LAT={r['lat']}"
                      f" → {r['state']} {r['plutchik']}")

    # 保存结果
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_results_1000.json')
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
