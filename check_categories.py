import json

with open(r"D:\OpenClawData\.openclaw\workspace\emotion-engine\test_results_1000.json", encoding="utf-8") as f:
    data = json.load(f)

cats = {}
for d in data:
    cat = d.get("category", "unknown")
    if cat not in cats:
        cats[cat] = {"total": 0, "passed": 0}
    cats[cat]["total"] += 1
    if d.get("passed", False):
        cats[cat]["passed"] += 1

for cat, v in cats.items():
    pct = v["passed"] / v["total"] * 100 if v["total"] > 0 else 0
    print(f"{cat}: {v['passed']}/{v['total']} = {pct:.1f}%")

total_p = sum(v["passed"] for v in cats.values())
total_t = sum(v["total"] for v in cats.values())
print(f"Total: {total_p}/{total_t} = {total_p/total_t*100:.1f}%")
