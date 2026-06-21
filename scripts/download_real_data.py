"""下载更多真实数据源"""
import os
import sys, io, os, gzip, csv, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# ── 1. Google Cluster Data 2019 ──
def download_google(part, max_rows=100000):
    url = f'https://storage.googleapis.com/clusterdata-2019/instance_usage/part-{part:05d}-of-05000.csv.gz'
    print(f'  Downloading part-{part:05d}...', flush=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
        print(f'  Downloaded: {len(raw)/1024/1024:.1f} MB', flush=True)
        
        rows = []
        with gzip.open(io.BytesIO(raw), 'rt', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                if len(row) >= 16:
                    try:
                        cpu = float(row[16]) * 100 if row[16] else 0
                        mem = float(row[22]) * 100 if row[22] else 0
                        rows.append((cpu, mem))
                    except:
                        continue
        print(f'  Valid: {len(rows)} rows', flush=True)
        return rows
    except Exception as e:
        print(f'  Failed: {e}', flush=True)
        return []

# ── 2. Azure Public Dataset (虚拟机trace) ──
def download_azure():
    url = 'https://azurecloudpublicdataset2.blob.core.windows.net/azurepublicdatasetv2tracedatasets/AzureFunctionsInvocationTrace/trace/azurefunctions_function_invocations.csv'
    print(f'  Downloading Azure Functions trace...', flush=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
        print(f'  Downloaded: {len(raw)/1024/1024:.1f} MB', flush=True)
        
        rows = []
        with io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            header = next(reader)
            print(f'  Columns: {header}', flush=True)
            for i, row in enumerate(reader):
                if i >= 50000:
                    break
                # Azure trace 格式: HashApp,HashFunction,HashOwner,TriggerTimestamp,EndTimestamp,Duration,Success
                # 没有 CPU/MEM，但有 Duration 和 Success
                try:
                    duration = float(row[5]) if row[5] else 0
                    success = int(row[6]) if row[6] else 1
                    # 用 duration 代理 latency，success 代理 error
                    cpu_proxy = min(100, duration / 10)  # 粗略映射
                    mem_proxy = 50  # 无内存数据
                    rows.append((cpu_proxy, mem_proxy))
                except:
                    continue
        print(f'  Valid: {len(rows)} rows', flush=True)
        return rows
    except Exception as e:
        print(f'  Failed: {e}', flush=True)
        return []

# ── 3. Alibaba Cluster Trace 2018 ──
def download_alibaba():
    # Alibaba trace 需要从 Tianchi 下载，公开链接可能已失效
    # 先试 GCS mirror
    url = 'https://storage.googleapis.com/clusterdata-2011-2/task_usage/part-00000-of-00500.csv.gz'
    print(f'  Downloading Google Cluster 2011 task_usage...', flush=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
        print(f'  Downloaded: {len(raw)/1024/1024:.1f} MB', flush=True)
        
        rows = []
        with gzip.open(io.BytesIO(raw), 'rt', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i >= 100000:
                    break
                if len(row) >= 7:
                    try:
                        cpu = float(row[5]) * 100 if row[5] else 0
                        mem = float(row[6]) * 100 if row[6] else 0
                        if 0 <= cpu <= 100 and 0 <= mem <= 100:
                            rows.append((cpu, mem))
                    except:
                        continue
        print(f'  Valid: {len(rows)} rows', flush=True)
        return rows
    except Exception as e:
        print(f'  Failed: {e}', flush=True)
        return []

# ── 执行 ──
print('=== Downloading Real Datasets ===\n')

all_data = {}

# Google 2019 (已有缓存)
cache_file = os.path.join(DATA_DIR, 'google_metrics_cache.json')
if os.path.exists(cache_file):
    with open(cache_file) as f:
        cached = json.load(f)
    google_data = [(d['cpu_percent'], d['mem_percent']) for d in cached[::5]]
    all_data['google_2019'] = google_data
    print(f'Google 2019 (cache): {len(google_data)} rows')

# Google 2011 (新下载)
g2011 = download_alibaba()
if g2011:
    all_data['google_2011'] = g2011
    with open(os.path.join(DATA_DIR, 'google_2011.json'), 'w') as f:
        json.dump(g2011, f)
    print(f'Saved google_2011.json: {len(g2011)} rows')

# Google 2019 extra parts
for part in [1, 2, 3]:
    extra = download_google(part, max_rows=100000)
    if extra:
        key = f'google_2019_p{part}'
        all_data[key] = extra
        with open(os.path.join(DATA_DIR, f'{key}.json'), 'w') as f:
            json.dump(extra, f)
        print(f'Saved {key}.json: {len(extra)} rows')
    time.sleep(2)

# Azure
azure = download_azure()
if azure:
    all_data['azure'] = azure
    with open(os.path.join(DATA_DIR, 'azure_functions.json'), 'w') as f:
        json.dump(azure, f)
    print(f'Saved azure_functions.json: {len(azure)} rows')

# 汇总
print(f'\n=== Summary ===')
total = 0
for name, data in all_data.items():
    cpus = [d[0] for d in data]
    print(f'  {name:20s}: {len(data):6d} rows  CPU avg={sum(cpus)/len(cpus):.1f}% min={min(cpus):.1f}% max={max(cpus):.1f}%')
    total += len(data)
print(f'  {"TOTAL":20s}: {total:6d} rows')
