"""测试 Claude Code 连通性及 emotion-engine 核心模块导入"""

print("Hello from Claude Code!")
print("-" * 40)

modules_to_test = [
    "body_sense",
    "context_pad",
    "ema_filter",
    "quadrant_stabilizer",
    "ode_dynamics",
    "plutchik",
]

results = []
for mod_name in modules_to_test:
    try:
        __import__(mod_name)
        print(f"[OK]   {mod_name}")
        results.append((mod_name, True, None))
    except Exception as e:
        print(f"[FAIL] {mod_name}: {e}")
        results.append((mod_name, False, str(e)))

print("-" * 40)
ok_count = sum(1 for _, ok, _ in results if ok)
fail_count = len(results) - ok_count
print(f"结果: {ok_count} 通过, {fail_count} 失败, 共 {len(results)} 个模块")
