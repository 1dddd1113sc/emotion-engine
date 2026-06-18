"""分析1000组测试失败详情"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open(r'D:\OpenClawData\.openclaw\workspace\emotion-engine\test_results_1000.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Boundary false positives
boundary = [r for r in data if r['category'] == 'boundary']
boundary_fa = [r for r in boundary if not r['expect_alert'] and r['is_alert']]
print(f'=== Boundary: {len(boundary)} total, {len(boundary_fa)} false alarms ===')
for r in boundary_fa[:15]:
    print(f"  {r['id']} CPU={r['cpu']} MEM={r['mem']} ERR={r['err']} LAT={r['lat']} → {r['state']} P={r['p']} A={r['a']} D={r['d']}")

# Contradiction misclassifications
contra = [r for r in data if r['category'] == 'contradiction']
contra_err = [r for r in contra if not r['correct_alert']]
print(f'\n=== Contradiction: {len(contra)} total, {len(contra_err)} errors ===')
for r in contra_err[:15]:
    print(f"  {r['id']} CPU={r['cpu']} MEM={r['mem']} ERR={r['err']} LAT={r['lat']} expect={r['expect_alert']} → {r['state']} P={r['p']} A={r['a']} D={r['d']}")

# Summary by quadrant
print(f'\n=== All results by quadrant ===')
from collections import Counter
state_counts = Counter(r['state'] for r in data)
for s, c in state_counts.most_common():
    print(f"  {s}: {c}")
