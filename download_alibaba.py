"""
Alibaba Cluster Trace 数据下载器

数据源：Alibaba Cluster Trace 2018
  - 8天，约4000台容器
  - 包含CPU、内存等指标
  - GitHub: https://github.com/alibaba/clusterdata

下载方式：从GitHub Release下载CSV子集
"""
import sys, io, os, csv, json, time, gzip
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import urllib.request

DATA_DIR = r"D:\OpenClawData\.openclaw\workspace\emotion-engine\data"
os.makedirs(DATA_DIR, exist_ok=True)

# Alibaba Cluster Trace 2018 的公开数据
# 使用较小的子集
ALIBABA_URLS = {
    "machine_meta": "https://raw.githubusercontent.com/alibaba/clusterdata/master/cluster-trace-v2018/machine_meta/part-00000-of-00001.csv.gz",
    "machine_usage": "https://raw.githubusercontent.com/alibaba/clusterdata/master/cluster-trace-v2018/machine_usage/part-00000-of-00001.csv.gz",
    "container_meta": "https://raw.githubusercontent.com/alibaba/clusterdata/master/cluster-trace-v2018/container_meta/part-00000-of-00001.csv.gz",
    "container_usage": "https://raw.githubusercontent.com/alibaba/clusterdata/master/cluster-trace-v2018/container_usage/part-00000-of-00001.csv.gz",
}

# 表的列定义
TABLE_COLUMNS = {
    "machine_meta": [
        "machine_id",           # 机器ID
        "time_stamp",           # 时间戳
        "disaster_level_1",     # 灾难级别1
        "disaster_level_2",     # 灾难级别2
        "cpu",                  # CPU容量
        "mem",                  # 内存容量
        "gpu",                  # GPU类型
        "gpu_type",             # GPU型号
    ],
    "machine_usage": [
        "machine_id",           # 机器ID
        "time_stamp",           # 时间戳
        "cpu_util_percent",     # CPU使用率(%)
        "mem_util_percent",     # 内存使用率(%)
        "mem_gps",              # 内存带宽(KB/s)
        "mkpi",                 # cache miss(KB/s)
        "net_in",               # 网络输入(MB/s)
        "net_out",              # 网络输出(MB/s)
        "disk_io_percent",      # 磁盘IO使用率(%)
    ],
    "container_meta": [
        "container_id",         # 容器ID
        "machine_id",           # 机器ID
        "time_stamp",           # 时间戳
        "app_du",               # 应用部署单元
        "status",               # 状态
        "cpu_request",          # CPU请求
        "cpu_limit",            # CPU上限
        "mem_size",             # 内存大小
    ],
    "container_usage": [
        "container_id",         # 容器ID
        "machine_id",           # 机器ID
        "time_stamp",           # 时间戳
        "cpu_util_percent",     # CPU使用率(%)
        "mem_util_percent",     # 内存使用率(%)
        "cpi",                  # 每指令周期数
        "mem_cache",            # 内存缓存(MB)
        "mkpi",                 # cache miss(KB/s)
        "net_in",               # 网络输入(MB/s)
        "net_out",              # 网络输出(MB/s)
        "disk_io_percent",      # 磁盘IO使用率(%)
    ],
}


def download_and_parse(table_name, max_rows=50000):
    """下载并解析指定表的数据"""
    url = ALIBABA_URLS.get(table_name)
    if not url:
        print(f"[{table_name}] 未知表")
        return None
    
    cache_file = os.path.join(DATA_DIR, f"alibaba_{table_name}_cache.json")
    
    # 检查缓存
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            data = json.load(f)
        print(f"[{table_name}] 从缓存加载: {len(data)} 条记录")
        return data
    
    columns = TABLE_COLUMNS[table_name]
    print(f"\n[{table_name}]")
    print(f"  下载: {url}")
    print(f"  列: {', '.join(columns)}")
    
    try:
        # 下载gz文件
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw_data = resp.read()
        print(f"  下载完成: {len(raw_data)/1024/1024:.1f}MB (压缩)")
        
        # 解压gzip
        with gzip.open(io.BytesIO(raw_data), "rt", encoding="utf-8") as f:
            reader = csv.reader(f)
            data = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                if len(row) == len(columns):
                    record = {}
                    for j, col in enumerate(columns):
                        try:
                            if "." in row[j]:
                                record[col] = float(row[j])
                            else:
                                record[col] = int(row[j])
                        except:
                            record[col] = row[j]
                    data.append(record)
                
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


def analyze_machine_usage(data):
    """分析机器使用数据"""
    print(f"\n=== 机器使用分析 ===")
    print(f"  总记录: {len(data)}")
    
    # CPU使用率分布
    cpu_utils = [d.get("cpu_util_percent", 0) for d in data if d.get("cpu_util_percent") is not None]
    mem_utils = [d.get("mem_util_percent", 0) for d in data if d.get("mem_util_percent") is not None]
    disk_utils = [d.get("disk_io_percent", 0) for d in data if d.get("disk_io_percent") is not None]
    net_in = [d.get("net_in", 0) for d in data if d.get("net_in") is not None]
    net_out = [d.get("net_out", 0) for d in data if d.get("net_out") is not None]
    
    if cpu_utils:
        print(f"\n  CPU使用率:")
        print(f"    均值: {sum(cpu_utils)/len(cpu_utils):.2f}%")
        print(f"    最小: {min(cpu_utils):.2f}%")
        print(f"    最大: {max(cpu_utils):.2f}%")
        print(f"    中位数: {sorted(cpu_utils)[len(cpu_utils)//2]:.2f}%")
    
    if mem_utils:
        print(f"\n  内存使用率:")
        print(f"    均值: {sum(mem_utils)/len(mem_utils):.2f}%")
        print(f"    最小: {min(mem_utils):.2f}%")
        print(f"    最大: {max(mem_utils):.2f}%")
    
    if disk_utils:
        print(f"\n  磁盘IO使用率:")
        print(f"    均值: {sum(disk_utils)/len(disk_utils):.2f}%")
        print(f"    最小: {min(disk_utils):.2f}%")
        print(f"    最大: {max(disk_utils):.2f}%")
    
    if net_in:
        print(f"\n  网络输入:")
        print(f"    均值: {sum(net_in)/len(net_in):.2f} MB/s")
        print(f"    最小: {min(net_in):.2f} MB/s")
        print(f"    最大: {max(net_in):.2f} MB/s")
    
    # 唯一机器数
    machine_ids = set(d.get("machine_id") for d in data)
    print(f"\n  唯一机器数: {len(machine_ids)}")


def convert_to_engine_format(data):
    """将Alibaba数据转换为引擎训练格式"""
    print(f"\n=== 转换为引擎训练格式 ===")
    
    converted = []
    for d in data:
        sample = {
            "cpu_percent": d.get("cpu_util_percent", 0) or 0,
            "mem_percent": d.get("mem_util_percent", 0) or 0,
            "swap_percent": 0,  # Alibaba数据不包含swap
            "disk_read_bytes": (d.get("disk_io_percent", 0) or 0) * 1000,  # 估算
            "disk_write_bytes": (d.get("disk_io_percent", 0) or 0) * 1000,
            "net_send_bytes": (d.get("net_out", 0) or 0) * 1024 * 1024,  # MB转bytes
            "net_recv_bytes": (d.get("net_in", 0) or 0) * 1024 * 1024,
            "error_rate": 0,
            "latency_ms": 100,  # 默认值
            "process_count": 1,
            "load_1m": (d.get("cpu_util_percent", 0) or 0) / 100 * 8,  # 估算
            "temperature": 35 + (d.get("cpu_util_percent", 0) or 0) * 0.5,  # 估算
        }
        converted.append(sample)
    
    print(f"  转换完成: {len(converted)} 条")
    return converted


if __name__ == "__main__":
    print("=" * 70)
    print("  Alibaba Cluster Trace 2018 数据下载器")
    print("=" * 70)
    
    # 下载机器使用数据（最有价值）
    usage_data = download_and_parse("machine_usage", max_rows=50000)
    if usage_data:
        analyze_machine_usage(usage_data)
        
        # 转换为引擎格式
        engine_data = convert_to_engine_format(usage_data)
        
        # 保存
        out_path = os.path.join(DATA_DIR, "alibaba_real_data.json")
        with open(out_path, "w") as f:
            json.dump(engine_data, f)
        print(f"\n  保存: {out_path} ({len(engine_data)} 条)")
    
    print("\n" + "=" * 70)
    print("  完成")
    print("=" * 70)
