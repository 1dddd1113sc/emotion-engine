import os, json

# P6
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'massive_test_results.json')
print(f"P6 massive_test_results.json exists: {os.path.exists(path)}")

# P4
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_results_1000.json'), encoding="utf-8") as f:
    data = json.load(f)
boundary = [d for d in data if d.get("category") == "boundary"]
correct = sum(1 for d in boundary if d.get("passed", False))
print(f"P4 boundary: {correct}/{len(boundary)} = {correct/len(boundary)*100:.1f}%")

# P7
py_dir = os.path.dirname(os.path.abspath(__file__))
py_files = [f for f in os.listdir(py_dir) if f.endswith(".py")]
total_lines = 0
total_size = 0
for f in py_files:
    fp = os.path.join(py_dir, f)
    total_size += os.path.getsize(fp)
    with open(fp, encoding="utf-8", errors="ignore") as fh:
        total_lines += sum(1 for _ in fh)
print(f"P7 py files: {len(py_files)}, total lines: {total_lines}, total size: {total_size/1024:.0f}KB")

# P9
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data\ae_stats.json'), encoding="utf-8") as f:
    stats = json.load(f)
print(f"P9 ae_stats feature_cols: {len(stats.get('feature_cols', []))}")

# P5
print("P5: train_ema.py uses clusterdata-2011-2 (2011), report ref [8] says 2019")
