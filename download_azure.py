"""
Azure VM Trace 数据下载器

数据源：Azure Public Dataset - VM Traces
  - 30天，约200万台VM
  - 包含CPU利用率时序数据
  - Microsoft Research: https://github.com/Azure/AzurePublicDataset

下载方式：从Azure Blob Storage下载
"""
import sys, io, os, csv, json, time, gzip
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import urllib.request

DATA_DIR = r"D:\OpenClawData\.openclaw\workspace\emotion-engine\data"
os.makedirs(DATA_DIR, exist_ok=True)

# Azure VM Trace 2017 的公开数据
# https://github.com/Azure/AzurePublicDataset/blob/master/AzurePublicDatasetV1.md
AZURE_URL = "https://azurecloudpublicdataset.blob.core.windows.net/azurepublicdataset/trace-data/2019/AzurePackingTraceV1.csv.gz"


def download_azure_trace(max_rows=100000):
    """下载Azure VM Trace数据"""
    cache_file = os.path.join(DATA_DIR, "azure_trace_cache.json")
    
    # 检查缓存
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            data = json.load(f)
        print(f"从缓存加载: {len(data)} 条记录")
        return data
    
    print(f"下载Azure VM Trace:")
    print(f"  URL: {AZURE_URL}")
    
    try:
        # 下载gz文件
        req = urllib.request.Request(AZURE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw_data = resp.read()
        print(f"  下载完成: {len(raw_data)/1024/1024:.1f}MB (压缩)")
        
        # 解压gzip并解析CSV
        with gzip.open(io.BytesIO(raw_data), "rt", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            data = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                data.append(dict(row))
                
                if (i + 1) % 10000 == 0:
                    print(f"  已解析 {i+1} 行...")
        
        print(f"  解析完成: {len(data)} 条记录")
        
        # 缓存
        with open(cache_file, "w") as f:
            json.dump(data, f)
        print(f"  已缓存: {cache_file}")
        
        return data
        
    except Exception as e:
        print(f"  下载失败: {e}")
        return None


def analyze_azure_trace(data):
    """分析Azure VM Trace数据"""
    print(f"\n=== Azure VM Trace 分析 ===")
    print(f"  总记录: {len(data)}")
    
    if not data:
        return
    
    # 打印列名
    print(f"  列名: {list(data[0].keys())}")
    
    # 打印前5条数据
    print(f"\n  前5条数据:")
    for i, d in enumerate(data[:5]):
        print(f"    {i}: {d}")
    
    # 查找CPU相关列
    cpu_cols = [col for col in data[0].keys() if 'cpu' in col.lower() or 'util' in col.lower()]
    mem_cols = [col for col in data[0].keys() if 'mem' in col.lower() or 'memory' in col.lower()]
    
    print(f"\n  CPU相关列: {cpu_cols}")
    print(f"  内存相关列: {mem_cols}")
    
    # 分析CPU列
    for col in cpu_cols:
        values = []
        for d in data:
            try:
                v = float(d.get(col, 0))
                if v > 0:
                    values.append(v)
            except:
                pass
        
        if values:
            print(f"\n  {col}:")
            print(f"    均值: {sum(values)/len(values):.4f}")
            print(f"    最小: {min(values):.4f}")
            print(f"    最大: {max(values):.4f}")
            print(f"    中位数: {sorted(values)[len(values)//2]:.4f}")


def convert_to_engine_format(data):
    """将Azure数据转换为引擎训练格式"""
    print(f"\n=== 转换为引擎训练格式 ===")
    
    # 查找CPU列
    cpu_col = None
    mem_col = None
    for col in data[0].keys():
        if 'cpu' in col.lower() and 'util' in col.lower():
            cpu_col = col
        if 'mem' in col.lower() and 'util' in col.lower():
            mem_col = col
    
    if not cpu_col:
        print("  未找到CPU列，尝试使用第一个数值列")
        for col in data[0].keys():
            try:
                float(data[0][col])
                cpu_col = col
                break
            except:
                pass
    
    print(f"  使用CPU列: {cpu_col}")
    print(f"  使用内存列: {mem_col}")
    
    converted = []
    for d in data:
        try:
            cpu = float(d.get(cpu_col, 0)) if cpu_col else 0
            mem = float(d.get(mem_col, 0)) if mem_col else 0
            
            # Azure数据是0-1的比例，转为百分比
            if cpu <= 1:
                cpu *= 100
            if mem <= 1:
                mem *= 100
            
            sample = {
                "cpu_percent": min(100, max(0, cpu)),
                "mem_percent": min(100, max(0, mem)),
                "swap_percent": 0,
                "disk_read_bytes": 0,
                "disk_write_bytes": 0,
                "net_send_bytes": 0,
                "net_recv_bytes": 0,
                "error_rate": 0,
                "latency_ms": 100,
                "process_count": 1,
                "load_1m": cpu / 100 * 8,
                "temperature": 35 + cpu * 0.5,
            }
            converted.append(sample)
        except:
            pass
    
    print(f"  转换完成: {len(converted)} 条")
    return converted


if __name__ == "__main__":
    print("=" * 70)
    print("  Azure VM Trace 数据下载器")
    print("=" * 70)
    
    # 下载Azure VM Trace
    data = download_azure_trace(max_rows=100000)
    if data:
        analyze_azure_trace(data)
        
        # 转换为引擎格式
        engine_data = convert_to_engine_format(data)
        
        # 保存
        out_path = os.path.join(DATA_DIR, "azure_real_data.json")
        with open(out_path, "w") as f:
            json.dump(engine_data, f)
        print(f"\n  保存: {out_path} ({len(engine_data)} 条)")
    
    print("\n" + "=" * 70)
    print("  完成")
    print("=" * 70)
