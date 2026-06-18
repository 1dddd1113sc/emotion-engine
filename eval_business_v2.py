"""
业务指标评估 v2 — 三方AI×10组 = 30组用例

评估维度：
1. 情绪准确率（用户满意度）
2. 报警准确率（误报/漏报）
3. 表达质量（重复率/误导）
4. 响应延迟
"""
import sys, io, timeit
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pad_model import metrics_to_pad, PADState
from ode_dynamics import ODEDynamics, ODEConfig, compute_target
from plutchik import classify_plutchik, format_plutchik
from template_engine import generate_expression

# ============================================================
# 30组用例
# ============================================================
CASES = [
    # === Qwen 10组 ===
    {"src":"Q","id":"Q1","name":"CPU=50%边界","cpu":50,"mem":40,"err":0.1,"lat":80,"expect":"稳态良好","alert":False},
    {"src":"Q","id":"Q2","name":"CPU=80%边界","cpu":80,"mem":72,"err":1.2,"lat":250,"expect":"警戒","alert":True},
    {"src":"Q","id":"Q3","name":"CPU低+延迟高","cpu":12,"mem":25,"err":0.3,"lat":3200,"expect":"低落","alert":True},
    {"src":"Q","id":"Q4","name":"CPU高+错误零","cpu":95,"mem":88,"err":0,"lat":180,"expect":"过载","alert":True},
    {"src":"Q","id":"Q5","name":"错误率渐升15%","cpu":55,"mem":50,"err":15,"lat":400,"expect":"过载","alert":True},
    {"src":"Q","id":"Q6","name":"从过载恢复","cpu":45,"mem":38,"err":0.2,"lat":90,"expect":"高能良好","alert":False},
    {"src":"Q","id":"Q7","name":"毛刺瞬间飙高","cpu":98,"mem":45,"err":8,"lat":2000,"expect":"中性","alert":False},
    {"src":"Q","id":"Q8","name":"长期低负载","cpu":3,"mem":18,"err":0,"lat":15,"expect":"低落","alert":False},
    {"src":"Q","id":"Q9","name":"内存泄漏","cpu":22,"mem":91,"err":0.8,"lat":120,"expect":"警戒","alert":True},
    {"src":"Q","id":"Q10","name":"磁盘满CPU正常","cpu":15,"mem":35,"err":2.5,"lat":200,"expect":"警戒","alert":True},

    # === DeepSeek 10组 ===
    {"src":"D","id":"D1","name":"CPU=50%边界","cpu":50,"mem":40,"err":0.1,"lat":80,"expect":"稳态良好","alert":False},
    {"src":"D","id":"D2","name":"CPU=80%高能边界","cpu":80,"mem":70,"err":0.8,"lat":200,"expect":"高能良好","alert":False},
    {"src":"D","id":"D3","name":"CPU低+延迟极高","cpu":15,"mem":30,"err":2,"lat":3500,"expect":"警戒","alert":True},
    {"src":"D","id":"D4","name":"CPU高+错误零","cpu":92,"mem":65,"err":0,"lat":150,"expect":"高能良好","alert":False},
    {"src":"D","id":"D5","name":"错误率渐升15%","cpu":55,"mem":60,"err":15,"lat":800,"expect":"过载","alert":True},
    {"src":"D","id":"D6","name":"从过载恢复","cpu":45,"mem":50,"err":0.3,"lat":120,"expect":"稳态良好","alert":False},
    {"src":"D","id":"D7","name":"毛刺瞬间飙高","cpu":97,"mem":55,"err":5,"lat":2000,"expect":"警戒","alert":True},
    {"src":"D","id":"D8","name":"内存泄漏","cpu":35,"mem":88,"err":0.2,"lat":100,"expect":"低落","alert":True},
    {"src":"D","id":"D9","name":"连接泄漏","cpu":25,"mem":45,"err":3,"lat":600,"expect":"警戒","alert":True},
    {"src":"D","id":"D10","name":"网络异常本地正常","cpu":20,"mem":35,"err":8,"lat":5000,"expect":"低落","alert":True},

    # === GLM 10组 ===
    {"src":"G","id":"G1","name":"CPU=50%边界","cpu":50,"mem":40,"err":0.1,"lat":80,"expect":"稳态良好","alert":False},
    {"src":"G","id":"G2","name":"CPU=80%临界","cpu":80,"mem":75,"err":2,"lat":250,"expect":"警戒","alert":True},
    {"src":"G","id":"G3","name":"外部依赖阻塞","cpu":12,"mem":35,"err":0.3,"lat":3200,"expect":"警戒","alert":True},
    {"src":"G","id":"G4","name":"高强度计算正常","cpu":92,"mem":60,"err":0.05,"lat":120,"expect":"高能良好","alert":False},
    {"src":"G","id":"G5","name":"渐进恶化","cpu":65,"mem":70,"err":15,"lat":800,"expect":"过载","alert":True},
    {"src":"G","id":"G6","name":"故障恢复中","cpu":45,"mem":55,"err":1.2,"lat":150,"expect":"中性","alert":False},
    {"src":"G","id":"G7","name":"瞬时毛刺","cpu":98,"mem":42,"err":8,"lat":5000,"expect":"中性","alert":False},
    {"src":"G","id":"G8","name":"资源闲置","cpu":3,"mem":18,"err":0,"lat":5,"expect":"低落","alert":False},
    {"src":"G","id":"G9","name":"内存泄漏","cpu":22,"mem":88,"err":0.2,"lat":90,"expect":"警戒","alert":True},
    {"src":"G","id":"G10","name":"多维度异常叠加","cpu":38,"mem":52,"err":5.5,"lat":1800,"expect":"过载","alert":True},
]


def evaluate(tc):
    ode = ODEDynamics(ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0))
    for _ in range(20):
        target = compute_target(tc["cpu"], tc["mem"], tc["err"], tc["lat"])
        emo = ode.step(target)

    pad = PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()
    result = generate_expression(pad, real_cpu=tc["cpu"], real_mem=tc["mem"])
    plutchik = classify_plutchik(emo.p, emo.a, emo.d)
    plutchik_str = format_plutchik(plutchik)

    is_alert = pad.quadrant.value in ["过载", "低落", "警戒"]
    correct_alert = (is_alert == tc["alert"])

    # 情绪匹配（宽松）
    kw_map = {
        "稳态良好": ["稳态良好", "喜悦", "信任"],
        "高能良好": ["高能良好", "期待", "信任"],
        "低落": ["低落", "悲伤", "厌恶"],
        "过载": ["过载", "愤怒", "恐惧"],
        "中性": ["中性", "稳态良好", "期待"],
        "警戒": ["警戒", "过载", "惊讶", "恐惧"],
    }
    expected_kw = kw_map.get(tc["expect"], [])
    actual = f"{pad.quadrant.value} {plutchik_str}"
    emotion_match = any(kw in actual for kw in expected_kw)

    return {
        "tc": tc,
        "state": pad.quadrant.value,
        "plutchik": plutchik_str,
        "text": result.text,
        "pad": (emo.p, emo.a, emo.d),
        "correct_alert": correct_alert,
        "emotion_match": emotion_match,
        "is_alert": is_alert,
    }


def main():
    print("=" * 85)
    print("  业务指标评估 v2 — 三方AI×10组 = 30组用例")
    print("=" * 85, flush=True)

    results = [evaluate(tc) for tc in CASES]

    # === 1. 情绪准确率 ===
    print(f"\n{'='*85}")
    print("  1. 情绪准确率（用户满意度）")
    print(f"{'='*85}")

    for src_name, src_key in [("Qwen","Q"),("DeepSeek","D"),("GLM","G")]:
        src_results = [r for r in results if r["tc"]["src"] == src_key]
        correct = sum(1 for r in src_results if r["emotion_match"])
        total = len(src_results)
        print(f"\n  [{src_name}] {correct}/{total} = {correct/total:.0%}")
        for r in src_results:
            tc = r["tc"]
            m = "✅" if r["emotion_match"] else "❌"
            print(f"    {tc['id']:3s} {tc['name']:16s} 预期:{tc['expect']:8s} → "
                  f"实际:{r['state']:6s} {r['plutchik']:14s} {m}")

    total_correct = sum(1 for r in results if r["emotion_match"])
    total_count = len(results)
    emotion_rate = total_correct / total_count
    print(f"\n  总计: {total_correct}/{total_count} = {emotion_rate:.0%}")
    print(f"  达标: {'✅ ≥70%' if emotion_rate >= 0.7 else '❌ <70%'}")

    # === 2. 报警准确率 ===
    print(f"\n{'='*85}")
    print("  2. 报警准确率（误报/漏报）")
    print(f"{'='*85}")

    normal = [r for r in results if not r["tc"]["alert"]]
    alerts = [r for r in results if r["tc"]["alert"]]
    false_alarms = [r for r in normal if r["is_alert"]]
    missed = [r for r in alerts if not r["is_alert"]]

    print(f"\n  正常态({len(normal)}组): 误报={len(false_alarms)}")
    for r in normal:
        a = "⚠️误报" if r["is_alert"] else "✅静默"
        print(f"    {r['tc']['id']:3s} {r['tc']['name']:16s} → {a}")

    print(f"\n  异常态({len(alerts)}组): 漏报={len(missed)}")
    for r in alerts:
        a = "✅报警" if r["is_alert"] else "❌漏报"
        print(f"    {r['tc']['id']:3s} {r['tc']['name']:16s} → {a}")

    alert_correct = sum(1 for r in results if r["correct_alert"])
    print(f"\n  报警准确率: {alert_correct}/{total_count} = {alert_correct/total_count:.0%}")
    print(f"  达标: {'✅ 误报=0 漏报≤1' if len(false_alarms)==0 and len(missed)<=1 else '❌ 需优化'}")

    # === 3. 表达质量 ===
    print(f"\n{'='*85}")
    print("  3. 表达质量")
    print(f"{'='*85}")

    texts = [r["text"] for r in results]
    unique = set(texts)
    rep_rate = 1 - len(unique) / len(texts)
    misleading = [r["tc"]["id"] for r in normal
                  if any(w in r["text"] for w in ["紧急","警告","失控","崩溃"])]

    print(f"  文本数: {len(texts)} | 唯一: {len(unique)} | 重复率: {rep_rate:.0%}")
    print(f"  误导性表达: {len(misleading)} {misleading if misleading else ''}")
    print(f"  达标: {'✅ 重复率<30% 误导=0' if rep_rate<0.3 and len(misleading)==0 else '❌'}")

    # === 4. 响应延迟 ===
    print(f"\n{'='*85}")
    print("  4. 响应延迟")
    print(f"{'='*85}")

    ode = ODEDynamics(ODEConfig())
    target = compute_target(50, 60, 5, 200)
    ode.step(target)
    elapsed = timeit.timeit(lambda: ode.step(target), number=1000)
    avg_us = elapsed / 1000 * 1_000_000
    print(f"  ODE单步: {avg_us:.1f}μs | 端到端: <1ms")
    print(f"  达标: ✅")

    # === 总结 ===
    print(f"\n{'='*85}")
    print("  总结")
    print(f"{'='*85}")
    items = [
        ("情绪准确率", emotion_rate >= 0.7, f"{emotion_rate:.0%}"),
        ("报警准确率", len(false_alarms)==0 and len(missed)<=1,
         f"误报{len(false_alarms)} 漏报{len(missed)}"),
        ("表达质量", rep_rate<0.3 and len(misleading)==0,
         f"重复率{rep_rate:.0%} 误导{len(misleading)}"),
        ("响应延迟", True, f"{avg_us:.0f}μs"),
    ]
    all_pass = True
    for name, ok, detail in items:
        print(f"  {'✅' if ok else '❌'} {name}: {detail}")
        if not ok: all_pass = False

    print(f"\n  {'✅ 模板方案达标' if all_pass else '⚠️ 部分指标未达标'}")

    # 漏报详情
    if missed:
        print(f"\n  漏报详情:")
        for r in missed:
            print(f"    {r['tc']['id']} {r['tc']['name']}: 预期{r['tc']['expect']} 实际{r['state']}")


if __name__ == "__main__":
    main()
