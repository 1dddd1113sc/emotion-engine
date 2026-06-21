"""
探测悲伤触发条件 — 扫描 PAD 空间
"""
import os
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plutchik import classify_plutchik, format_plutchik, PLUTCHIK_ANCHORS, BasicEmotion, _pad_distance

# 1. 悲伤锚点附近的 PAD 扫描
print("=" * 70)
print("悲伤锚点附近扫描 (PAD 各 ±0.3 范围)")
print("=" * 70)
print(f"{'P':>6} {'A':>6} {'D':>6} {'情绪':>25} {'置信度':>6}")
print("-" * 55)

for p in [-0.9, -0.8, -0.7, -0.6, -0.5, -0.4]:
    for a in [-0.7, -0.6, -0.5, -0.4, -0.3, -0.2, -0.1]:
        for d in [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0]:
            state = classify_plutchik(p, a, d)
            if state.primary == BasicEmotion.SADNESS:
                print(f"{p:+6.1f} {a:+6.1f} {d:+6.1f} {format_plutchik(state):>25} {state.confidence:6.3f}")

print()

# 2. 竞技场：与所有锚点的距离对比
print("=" * 70)
print("悲伤 vs 最强竞争对手 — 什么条件下悲伤排第一")
print("=" * 70)
print(f"{'P':>6} {'A':>6} {'D':>6} {'#1距离':>8} {'#1情绪':>12} {'#2距离':>8} {'#2情绪':>12} {'margin':>8}")
print("-" * 70)

test_points = [
    (-0.7, -0.5, -0.3),  # 悲伤锚点本身
    (-0.7, -0.5, -0.2),
    (-0.7, -0.5, -0.1),
    (-0.7, -0.4, -0.3),
    (-0.7, -0.4, -0.1),
    (-0.6, -0.5, -0.3),
    (-0.6, -0.4, -0.3),
    (-0.6, -0.4, -0.1),
    (-0.8, -0.4, -0.3),
    (-0.8, -0.3, -0.3),
    (-0.5, -0.5, -0.3),
    (-0.5, -0.4, -0.3),
    (-0.5, -0.3, -0.3),
    (-0.7, -0.3, -0.3),
    (-0.6, -0.3, -0.3),
    (-0.7, -0.5, 0.0),
    (-0.7, -0.5, 0.2),
    (-0.5, -0.5, 0.0),
]

for p, a, d in test_points:
    current = (p, a, d)
    distances = [(_pad_distance(current, (ep, ea, ed)), em) for ep, ea, ed, em in PLUTCHIK_ANCHORS]
    distances.sort(key=lambda x: x[0])
    d1, e1 = distances[0]
    d2, e2 = distances[1]
    margin = d2 - d1
    marker = "★" if e1 == BasicEmotion.SADNESS else " "
    print(f"{p:+6.1f} {a:+6.1f} {d:+6.1f} {d1:8.4f} {e1.value:>12} {d2:8.4f} {e2.value:>12} {margin:+8.4f} {marker}")

print()

# 3. 悲伤 vs 厌恶 — 边界在哪里
print("=" * 70)
print("悲伤 vs 厌恶 — 边界分析")
print("悲伤锚点: (-0.7,-0.5,-0.3)  厌恶锚点: (-0.6,-0.2,+0.3)")
print("=" * 70)
print(f"{'P':>6} {'A':>6} {'D':>6} {'到悲伤':>8} {'到厌恶':>8} {'胜者':>10}")
print("-" * 50)

# 固定 P=-0.65, 扫描 A/D
for a in [-0.6, -0.5, -0.4, -0.35, -0.3, -0.25, -0.2]:
    for d in [-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]:
        d_sad = _pad_distance((p, a, d), (-0.7, -0.5, -0.3))
        d_dis = _pad_distance((p, a, d), (-0.6, -0.2, 0.3))
        winner = "悲伤" if d_sad < d_dis else "厌恶"
        if abs(d_sad - d_dis) < 0.15:  # 只打印边界附近
            print(f"{p:+6.1f} {a:+6.1f} {d:+6.1f} {d_sad:8.4f} {d_dis:8.4f} {winner:>10}")

print()

# 4. 完整扫描：悲伤出现的区域
print("=" * 70)
print("悲伤触发区域 (D 固定=-0.3)")
print("=" * 70)
print("   P\\A  ", end="")
for a in range(-8, 9, 2):
    a_val = a / 10
    print(f"{a_val:+5.1f}", end="")
print()

for p in range(-10, 0, 1):
    p_val = p / 10
    print(f"{p_val:+6.1f} ", end="")
    for a in range(-8, 9, 2):
        a_val = a / 10
        state = classify_plutchik(p_val, a_val, -0.3)
        if state.primary == BasicEmotion.SADNESS:
            print("  SAD", end="")
        elif state.primary == BasicEmotion.DISGUST:
            print("  DIS", end="")
        elif state.primary == BasicEmotion.FEAR:
            print("  FEA", end="")
        elif state.primary == BasicEmotion.ANGER:
            print("  ANG", end="")
        else:
            print("   . ", end="")
    print()

print()
print("=" * 70)
print("悲伤触发区域 (A 固定=-0.5)")
print("=" * 70)
print("   P\\D  ", end="")
for d in range(-8, 7, 2):
    d_val = d / 10
    print(f"{d_val:+5.1f}", end="")
print()

for p in range(-10, 0, 1):
    p_val = p / 10
    print(f"{p_val:+6.1f} ", end="")
    for d in range(-8, 7, 2):
        d_val = d / 10
        state = classify_plutchik(p_val, -0.5, d_val)
        if state.primary == BasicEmotion.SADNESS:
            print("  SAD", end="")
        elif state.primary == BasicEmotion.DISGUST:
            print("  DIS", end="")
        elif state.primary == BasicEmotion.FEAR:
            print("  FEA", end="")
        elif state.primary == BasicEmotion.ANGER:
            print("  ANG", end="")
        elif state.primary == BasicEmotion.TRUST:
            print("  TRU", end="")
        else:
            print("   . ", end="")
    print()