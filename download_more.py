"""检查 Google 数据并下载更多"""
import os
import json, os, sys, io, gzip, csv, time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
CACHE_FILE = os.path.join(DATA_DIR, "google_metrics_cache.json")

# 1. 检查现有缓存
with open(CACHE_FILE) as f:
    data = json.load(f)

print(f"=== 现有缓存 ===")
print(f"  记录数: {len(data)}")
print(f"  字段: {list(data[0].keys())}")

types = {}
for d in data:
    t = d.get("machine_type", "unknown")
    types[t] = types.get(t, 0) + 1
print(f"  机器类型: {types}")

cpus = [d["cpu_percent"] for d in data]
print(f"  CPU: min={min(cpus):.1f} max={max(cpus):.1f} avg={sum(cpus)/len(cpus):.1f}")

# 2. 尝试下载更多分片
GCS_BASE = "https://storage.googleapis.com/clusterdata-2019"
INSTANCE_USAGE_COLS = [
    "start_time", "end_time", "instance_index", "collection_id",
    "collection_type", "collection_name", "logical_job_name",
    "resource_request:cpu", "resource_request:memory",
    "resource_request:cpus_specified", "cycles_per_instruction",
    "memory_accesses_per_instruction", "sample_portion",
    "aggregation_type",
    "cpu_usage_distribution:percentile_0", "cpu_usage_distribution:percentile_25",
    "cpu_usage_distribution:percentile_50", "cpu_usage_distribution:percentile_75",
    "cpu_usage_distribution:percentile_99", "cpu_usage_distribution:max",
    "memory_usage_distribution:percentile_0", "memory_usage_distribution:percentile_25",
    "memory_usage_distribution:percentile_50", "memory_usage_distribution:percentile_75",
    "memory_usage_distribution:percentile_99", "memory_usage_distribution:max",
]

def download_part(part_num, max_rows=100000):
    """下载一个分片"""
    filename = f"instance_usage/part-{part_num:05d}-of-05000.csv.gz"
    url = f"{GCS_BASE}/{filename}"
    
    print(f"\n  Downloading {filename} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
        print(f"  Downloaded: {len(raw)/1024/1024:.1f} MB compressed", flush=True)
        
        rows = []
        with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                if len(row) >= 15:
                    try:
                        cpu_p50 = float(row[16]) if row[16] else 0.0
                        mem_p50 = float(row[22]) if row[22] else 0.0
                        rows.append({
                            "cpu_percent": cpu_p50 * 100,
                            "mem_percent": mem_p50 * 100,
                        })
                    except (ValueError, IndexError):
                        continue
                if (i + 1) % 50000 == 0:
                    print(f"    Parsed {i+1} rows...", flush=True)
        
        print(f"  Valid rows: {len(rows)}", flush=True)
        return rows
    except Exception as e:
        print(f"  Failed: {e}", flush=True)
        return []

# 下载额外分片
print(f"\n=== 下载更多 Google Cluster Data ===")
new_data = []
parts_to_try = [1, 2, 3, 4, 5]  # 尝试 5 个分片

for part in parts_to_try:
    rows = download_part(part, max_rows=100000)
    if rows:
        new_data.extend(rows)
        print(f"  累计新数据: {len(new_data)} 行")
    if len(new_data) >= 200000:  # 够了就停
        break
    time.sleep(1)  # 礼貌间隔

print(f"\n=== 结果 ===")
print(f"  原有缓存: {len(data)} 行")
print(f"  新下载:   {len(new_data)} 行")
print(f"  总计:     {len(data) + len(new_data)} 行")

# 保存新数据到单独文件
if new_data:
    new_file = os.path.join(DATA_DIR, "google_extra_data.json")
    with open(new_file, "w") as f:
        json.dump(new_data, f)
    print(f"  保存到: {new_file}")
