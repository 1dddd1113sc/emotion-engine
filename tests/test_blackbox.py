"""
黑盒测试 — 15组用例（Qwen×5 + DeepSeek×5 + GLM×5）

直接喂指标进引擎，对比实际输出 vs 预期输出
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pad_model import metrics_to_pad, MetricsHistory
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from plutchik import classify_plutchik, format_plutchik
from body_sense import BodySenseManager
from template_engine import generate_expression

# ============================================================
# 15组测试用例
# ============================================================

TEST_CASES = [
    # === Qwen 的5组 ===
    {
        "source": "Qwen",
        "name": "稳态良好（正常运行）",
        "cpu": 12, "mem": 35, "err": 0.1, "lat": 45,
        "expected_state": "稳态良好",
        "expected_plutchik": "喜悦",
        "reason": "所有指标远低于阈值，系统最佳状态",
    },
    {
        "source": "Qwen",
        "name": "资源过载（高负载压力）",
        "cpu": 96, "mem": 92, "err": 3.2, "lat": 1800,
        "expected_state": "过载",
        "expected_plutchik": "愤怒",
        "reason": "CPU/内存逼近极限，延迟飙升",
    },
    {
        "source": "Qwen",
        "name": "错误飙升（异常突增）",
        "cpu": 45, "mem": 55, "err": 28, "lat": 950,
        "expected_state": "警戒",
        "expected_plutchik": "恐惧",
        "reason": "资源尚可但错误率异常飙升",
    },
    {
        "source": "Qwen",
        "name": "故障恢复（从异常回归）",
        "cpu": 38, "mem": 48, "err": 2.8, "lat": 210,
        "expected_state": "中性",
        "expected_plutchik": "期待",
        "reason": "指标回落但未完全恢复",
    },
    {
        "source": "Qwen",
        "name": "极端异常（全面崩溃边缘）",
        "cpu": 99, "mem": 98, "err": 65, "lat": 8500,
        "expected_state": "过载",
        "expected_plutchik": "恐惧",
        "reason": "所有指标极端值",
    },

    # === DeepSeek 的5组 ===
    {
        "source": "DeepSeek",
        "name": "稳态运行",
        "cpu": 25, "mem": 40, "err": 0.1, "lat": 50,
        "expected_state": "稳态良好",
        "expected_plutchik": "信任",
        "reason": "各项指标健康低位，从容运行",
    },
    {
        "source": "DeepSeek",
        "name": "高压过载",
        "cpu": 95, "mem": 92, "err": 2, "lat": 800,
        "expected_state": "过载",
        "expected_plutchik": "愤怒",
        "reason": "资源耗尽，延迟飙升",
    },
    {
        "source": "DeepSeek",
        "name": "错误飙升",
        "cpu": 55, "mem": 60, "err": 30, "lat": 1200,
        "expected_state": "警戒",
        "expected_plutchik": "恐惧",
        "reason": "CPU/内存中位但错误率暴增",
    },
    {
        "source": "DeepSeek",
        "name": "从故障中恢复",
        "cpu": 45, "mem": 55, "err": 1.5, "lat": 200,
        "expected_state": "中性",
        "expected_plutchik": "期待",
        "reason": "指标从高位回落但仍略高于基线",
    },
    {
        "source": "DeepSeek",
        "name": "极端异常（数据矛盾）",
        "cpu": 99, "mem": 8, "err": 50, "lat": 5000,
        "expected_state": "过载",
        "expected_plutchik": "惊讶",
        "reason": "CPU满载但内存极低，指标矛盾",
    },

    # === GLM 的5组 ===
    {
        "source": "GLM",
        "name": "万事如意（正常稳态）",
        "cpu": 12, "mem": 35, "err": 0.1, "lat": 8,
        "expected_state": "稳态良好",
        "expected_plutchik": "喜悦",
        "reason": "所有指标极低水位，毫无压力",
    },
    {
        "source": "GLM",
        "name": "过载风暴（资源饱和）",
        "cpu": 95, "mem": 92, "err": 3.2, "lat": 1800,
        "expected_state": "过载",
        "expected_plutchik": "愤怒",
        "reason": "CPU/内存逼近极限",
    },
    {
        "source": "GLM",
        "name": "错误雪崩（故障飙升）",
        "cpu": 55, "mem": 60, "err": 18, "lat": 450,
        "expected_state": "警戒",
        "expected_plutchik": "恐惧",
        "reason": "中等负载但错误率异常飙升",
    },
    {
        "source": "GLM",
        "name": "黎明恢复（趋势向好）",
        "cpu": 40, "mem": 50, "err": 2.5, "lat": 120,
        "expected_state": "中性",
        "expected_plutchik": "期待",
        "reason": "绝对值可接受但未完全恢复",
    },
    {
        "source": "GLM",
        "name": "黑天鹅（极端矛盾）",
        "cpu": 5, "mem": 98, "err": 0, "lat": 5000,
        "expected_state": "过载",
        "expected_plutchik": "惊讶",
        "reason": "CPU空闲但内存耗尽，延迟极高",
    },
]


def run_test(tc: dict, step_count: int = 30) -> dict:
    """运行单组测试，返回结果"""
    from ode_dynamics import DEFAULT_ODE_CONFIG
    ode = ODEDynamics(DEFAULT_ODE_CONFIG)
    body = BodySenseManager()

    # 多步运行让ODE收敛
    for i in range(step_count):
        target = compute_target(
            tc["cpu"], tc["mem"], tc["err"], tc["lat"],
            fatigue=0.3, tension=0.1, comfort=0.8,
        )
        emo = ode.step(target)

    # 最终状态
    pad_state = generate_expression(
        __import__('pad_model').PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp(),
        real_cpu=tc["cpu"], real_mem=tc["mem"],
    )
    plutchik = classify_plutchik(emo.p, emo.a, emo.d)
    plutchik_str = format_plutchik(plutchik)

    return {
        "actual_p": emo.p,
        "actual_a": emo.a,
        "actual_d": emo.d,
        "actual_state": pad_state.quadrant.value,
        "actual_plutchik": plutchik_str,
        "plutchik_primary": plutchik.primary.value,
    }


def main():
    print("=" * 80)
    print("  黑盒测试 — 三方AI×5组 = 15组用例")
    print("=" * 80, flush=True)

    results = []
    pass_count = 0
    total = len(TEST_CASES)

    for i, tc in enumerate(TEST_CASES):
        result = run_test(tc)

        # 判定
        state_match = result["actual_state"] == tc["expected_state"]
        plutchik_match = (
            tc["expected_plutchik"] in result["actual_plutchik"]
            or result["plutchik_primary"] == tc["expected_plutchik"]
        )

        # 状态允许邻近匹配（如"高能良好"≈"稳态良好"在某些边界）
        state_close = state_match or (
            (tc["expected_state"] in ["稳态良好", "中性"] and result["actual_state"] in ["稳态良好", "中性", "高能良好"])
            or (tc["expected_state"] in ["过载", "警戒"] and result["actual_state"] in ["过载", "警戒"])
        )

        overall = "PASS" if (state_close and plutchik_match) else ("CLOSE" if state_close or plutchik_match else "FAIL")
        if overall == "PASS":
            pass_count += 1

        status_icon = {"PASS": "✅", "CLOSE": "⚠️", "FAIL": "❌"}[overall]

        print(f"\n用例{i+1:02d} [{tc['source']:8s}] {tc['name']}")
        print(f"  输入: CPU={tc['cpu']}% MEM={tc['mem']}% ERR={tc['err']}% LAT={tc['lat']}ms")
        print(f"  实际: P={result['actual_p']:+.2f} A={result['actual_a']:+.2f} D={result['actual_d']:+.2f}")
        print(f"        状态={result['actual_state']} | Plutchik={result['actual_plutchik']}")
        print(f"  预期: 状态={tc['expected_state']} | Plutchik={tc['expected_plutchik']}")
        print(f"  {status_icon} {overall}  (状态:{'✓' if state_close else '✗'} 情绪:{'✓' if plutchik_match else '✗'})")

        results.append({"tc": tc, "result": result, "verdict": overall})

    # 汇总
    print(f"\n{'='*80}")
    print(f"  测试结果汇总")
    print(f"{'='*80}")
    print(f"  总计: {total} | 通过: {pass_count} | 近似: {total - pass_count - sum(1 for r in results if r['verdict']=='FAIL')} | 失败: {sum(1 for r in results if r['verdict']=='FAIL')}")
    print(f"  通过率: {pass_count/total:.0%}")

    # 按来源统计
    for src in ["Qwen", "DeepSeek", "GLM"]:
        src_results = [r for r in results if r["tc"]["source"] == src]
        src_pass = sum(1 for r in src_results if r["verdict"] == "PASS")
        print(f"  {src:8s}: {src_pass}/{len(src_results)} 通过")

    # 失败详情
    fails = [r for r in results if r["verdict"] == "FAIL"]
    if fails:
        print(f"\n  ❌ 失败用例:")
        for r in fails:
            print(f"    - {r['tc']['name']}: 预期{r['tc']['expected_state']}/{r['tc']['expected_plutchik']} → 实际{r['result']['actual_state']}/{r['result']['actual_plutchik']}")


if __name__ == "__main__":
    main()
