"""检查压力测试结果"""
import json

with open(r'D:\OpenClawData\.openclaw\workspace\emotion-engine\stress_10min_results.json', encoding='utf-8') as f:
    data = json.load(f)

print(f"Keys: {list(data.keys())[:10]}")
for k, v in data.items():
    if isinstance(v, dict):
        print(f"  {k}: dict with keys {list(v.keys())[:5]}")
    elif isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
        if v:
            print(f"    first item keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0])}")
    else:
        print(f"  {k}: {v}")
