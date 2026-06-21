"""
Google Cluster Trace v2 (2019) 数据下载器

直接从GCS公开存储桶流式读取
数据地址：gs://clusterdata-2019/
文档：https://github.com/google/cluster-data/blob/master/Documentation/Schema.md
"""
import os
import sys, io, os, csv, json, time, struct, gzip
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Google Cluster Data 2019 公开GCS地址
GCS_BASE = "https://storage.googleapis.com/clusterdata-2019"

# 表和对应的列名
TABLES = {
    "machine_events": {
        "columns": [
            "timestamp",        # 纳秒时间戳
            "machine_id",       # 机器ID
            "event_type",       # 事件类型: 0=ADD, 1=REMOVE, 2=UPDATE
            "platform_id",      # 平台ID(哈希)
            "capacity:cpu",     # CPU容量(归一化)
            "capacity:memory",  # 内存容量(归一化)
        ],
        "file": "machine_events/part-00000-of-00001.csv.gz",
        "description": "机器属性和状态变化事件",
    },
    "instance_events": {
        "columns": [
            "timestamp",
            "instance_index",
            "event_type",       # 0=SUBMIT, 1=QUEUE, 2=ENABLE, 3=DISABLE, 4=FAIL, 5=KILL, 6=LOST, 7=UPDATE, 8=EVICTION
            "collection_id",
            "collection_type",  # 0=regular, 1=uncertain
            "collection_name",
            "logical_job_name",
            "resource_request:cpu",
            "resource_request:memory",
            "constraint",       # 二进制约束
            "alloc_collection_id",
            "alloc_instance_index",
            "machine_id",
        ],
        "file": "instance_events/part-00000-of-00500.csv.gz",
        "description": "实例/任务的提交、调度、资源请求等事件",
    },
    "instance_usage": {
        "columns": [
            "start_time",
            "end_time",
            "instance_index",
            "collection_id",
            "collection_type",
            "collection_name",
            "logical_job_name",
            "resource_request:cpu",
            "resource_request:memory",
            "resource_request:cpus_specified",
            "cycles_per_instruction",
            "memory_accesses_per_instruction",
            "sample_portion",
            "aggregation_type",
            "cpu_usage_distribution:percentile_0",
            "cpu_usage_distribution:percentile_25",
            "cpu_usage_distribution:percentile_50",
            "cpu_usage_distribution:percentile_75",
            "cpu_usage_distribution:percentile_99",
            "cpu_usage_distribution:max",
            "memory_usage_distribution:percentile_0",
            "memory_usage_distribution:percentile_25",
            "memory_usage_distribution:percentile_50",
            "memory_usage_distribution:percentile_75",
            "memory_usage_distribution:percentile_99",
            "memory_usage_distribution:max",
        ],
        "file": "instance_usage/part-00000-of-05000.csv.gz",
        "description": "实例资源使用统计（每5分钟聚合）",
    },
}


def download_and_parse(table_name, max_rows=50000):
    """下载并解析指定表的数据"""
    table = TABLES[table_name]
    url = f"{GCS_BASE}/{table['file']}"
    cache_file = os.path.join(DATA_DIR, f"{table_name}_cache.json")
    
    # 检查缓存
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            data = json.load(f)
        print(f"[{table_name}] 从缓存加载: {len(data)} 条记录")
        return data
    
    print(f"[{table_name}] {table['description']}")
    print(f"  下载: {url}")
    print(f"  列: {', '.join(table['columns'])}")
    
    try:
        # 下载gz文件
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_data = resp.read()
        print(f"  下载完成: {len(raw_data)/1024/1024:.1f}MB (压缩)")
        
        # 解压gzip
        with gzip.open(io.BytesIO(raw_data), "rt", encoding="utf-8") as f:
            reader = csv.reader(f)
            data = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                if len(row) == len(table["columns"]):
                    record = {}
                    for j, col in enumerate(table["columns"]):
                        try:
                            # 尝试转为数字
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


def analyze_machine_events(data):
    """分析机器事件数据"""
    print(f"\n=== 机器事件分析 ===")
    print(f"  总记录: {len(data)}")
    
    # 事件类型分布
    event_types = {}
    for d in data:
        et = d.get("event_type", -1)
        event_types[et] = event_types.get(et, 0) + 1
    
    type_names = {0: "ADD(添加)", 1: "REMOVE(移除)", 2: "UPDATE(更新)"}
    for et, count in sorted(event_types.items()):
        name = type_names.get(et, f"未知({et})")
        print(f"  {name}: {count} ({count/len(data)*100:.1f}%)")
    
    # CPU和内存分布
    cpus = [d.get("capacity:cpu", 0) for d in data if d.get("capacity:cpu", 0) > 0]
    mems = [d.get("capacity:memory", 0) for d in data if d.get("capacity:memory", 0) > 0]
    
    if cpus:
        print(f"\n  CPU容量:")
        print(f"    均值: {sum(cpus)/len(cpus):.4f}")
        print(f"    最小: {min(cpus):.4f}")
        print(f"    最大: {max(cpus):.4f}")
    
    if mems:
        print(f"\n  内存容量:")
        print(f"    均值: {sum(mems)/len(mems):.4f}")
        print(f"    最小: {min(mems):.4f}")
        print(f"    最大: {max(mems):.4f}")
    
    # 唯一机器数
    machine_ids = set(d.get("machine_id") for d in data)
    print(f"\n  唯一机器数: {len(machine_ids)}")


def analyze_instance_usage(data):
    """分析实例使用数据"""
    print(f"\n=== 实例使用分析 ===")
    print(f"  总记录: {len(data)}")
    
    # CPU使用分布
    cpu_p50 = [d.get("cpu_usage_distribution:percentile_50", 0) for d in data 
                if d.get("cpu_usage_distribution:percentile_50") is not None]
    cpu_p99 = [d.get("cpu_usage_distribution:percentile_99", 0) for d in data 
                if d.get("cpu_usage_distribution:percentile_99") is not None]
    
    if cpu_p50:
        print(f"\n  CPU使用(P50):")
        print(f"    均值: {sum(cpu_p50)/len(cpu_p50):.4f}")
        print(f"    最小: {min(cpu_p50):.4f}")
        print(f"    最大: {max(cpu_p50):.4f}")
    
    if cpu_p99:
        print(f"\n  CPU使用(P99):")
        print(f"    均值: {sum(cpu_p99)/len(cpu_p99):.4f}")
        print(f"    最小: {min(cpu_p99):.4f}")
        print(f"    最大: {max(cpu_p99):.4f}")
    
    # 内存使用分布
    mem_p50 = [d.get("memory_usage_distribution:percentile_50", 0) for d in data 
                if d.get("memory_usage_distribution:percentile_50") is not None]
    
    if mem_p50:
        print(f"\n  内存使用(P50):")
        print(f"    均值: {sum(mem_p50)/len(mem_p50):.4f}")
        print(f"    最小: {min(mem_p50):.4f}")
        print(f"    最大: {max(mem_p50):.4f}")
    
    # 资源请求vs实际使用
    req_cpu = [d.get("resource_request:cpu", 0) for d in data 
               if d.get("resource_request:cpu") is not None]
    if req_cpu and cpu_p50:
        avg_req = sum(req_cpu) / len(req_cpu)
        avg_use = sum(cpu_p50) / len(cpu_p50)
        print(f"\n  资源利用率:")
        print(f"    平均请求CPU: {avg_req:.4f}")
        print(f"    平均实际使用: {avg_use:.4f}")
        print(f"    利用率: {avg_use/avg_req*100:.1f}%" if avg_req > 0 else "    利用率: N/A")


def convert_to_engine_format(data, table_name):
    """将Google数据转换为引擎训练格式"""
    print(f"\n=== 转换为引擎训练格式 ===")
    
    if table_name == "instance_usage":
        converted = []
        for d in data:
            sample = {
                "cpu_percent": (d.get("cpu_usage_distribution:percentile_50", 0) or 0) * 100,
                "mem_percent": (d.get("memory_usage_distribution:percentile_50", 0) or 0) * 100,
                "swap_percent": 0,  # Google数据不包含swap
                "disk_read_bytes": 0,  # Google数据不包含磁盘I/O
                "disk_write_bytes": 0,
                "net_send_bytes": 0,  # Google数据不包含网络
                "net_recv_bytes": 0,
                "error_rate": 0,
                "latency_ms": 100,  # 默认值
                "process_count": 1,
                "load_1m": (d.get("cpu_usage_distribution:percentile_50", 0) or 0) * 8,
                "temperature": 40 + (d.get("cpu_usage_distribution:percentile_50", 0) or 0) * 40,
            }
            converted.append(sample)
        
        print(f"  转换完成: {len(converted)} 条")
        return converted
    
    elif table_name == "machine_events":
        converted = []
        for d in data:
            if d.get("capacity:cpu", 0) > 0:
                sample = {
                    "cpu_percent": 0,  # 机器事件不包含使用率
                    "mem_percent": 0,
                    "swap_percent": 0,
                    "disk_read_bytes": 0,
                    "disk_write_bytes": 0,
                    "net_send_bytes": 0,
                    "net_recv_bytes": 0,
                    "error_rate": 0,
                    "latency_ms": 100,
                    "process_count": 1,
                    "load_1m": 0,
                    "temperature": 40,
                    "machine_id": d.get("machine_id"),
                    "cpu_capacity": d.get("capacity:cpu"),
                    "mem_capacity": d.get("capacity:memory"),
                }
                converted.append(sample)
        
        print(f"  转换完成: {len(converted)} 条")
        return converted
    
    return []


if __name__ == "__main__":
    print("=" * 70)
    print("  Google Cluster Trace v2 (2019) 数据下载器")
    print("=" * 70)
    
    # 下载机器事件
    machine_data = download_and_parse("machine_events", max_rows=50000)
    if machine_data:
        analyze_machine_events(machine_data)
    
    # 下载实例使用数据
    usage_data = download_and_parse("instance_usage", max_rows=50000)
    if usage_data:
        analyze_instance_usage(usage_data)
        
        # 转换为引擎格式
        engine_data = convert_to_engine_format(usage_data, "instance_usage")
        
        # 保存
        out_path = os.path.join(DATA_DIR, "google_real_data.json")
        with open(out_path, "w") as f:
            json.dump(engine_data, f)
        print(f"\n  保存: {out_path} ({len(engine_data)} 条)")
    
    print("\n" + "=" * 70)
    print("  完成")
    print("=" * 70)
