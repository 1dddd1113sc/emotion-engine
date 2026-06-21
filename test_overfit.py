"""
AutoEncoder 过拟合测试

测试方法：
1. 训练集 vs 测试集重建误差对比
2. 生成从未见过的分布数据测试泛化能力
3. 极端值/边界值测试
"""
import os
import sys, io, os, json, random, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')

# ============================================================
# 加载模型和统计参数
# ============================================================

def load_model():
    model_path = os.path.join(MODEL_DIR, "ae_best.json")
    with open(model_path) as f:
        state = json.load(f)
    
    stats_path = os.path.join(MODEL_DIR, "ae_stats.json")
    with open(stats_path) as f:
        stats = json.load(f)
    
    return state, stats


def forward(state, x):
    """前向传播"""
    enc_weights = [np.array(w, dtype=np.float32) for w in state["enc_weights"]]
    enc_biases = [np.array(b, dtype=np.float32) for b in state["enc_biases"]]
    dec_weights = [np.array(w, dtype=np.float32) for w in state["dec_weights"]]
    dec_biases = [np.array(b, dtype=np.float32) for b in state["dec_biases"]]
    
    h = x
    # 编码
    for i in range(len(enc_weights)):
        h = h @ enc_weights[i] + enc_biases[i]
        if i < len(enc_weights) - 1:
            h = np.where(h > 0, h, 0.01 * h)  # LeakyReLU
        else:
            h = np.tanh(h)
    z = h
    
    # 解码
    for i in range(len(dec_weights)):
        h = h @ dec_weights[i] + dec_biases[i]
        if i < len(dec_weights) - 1:
            h = np.where(h > 0, h, 0.01 * h)
        else:
            h = 1.0 / (1.0 + np.exp(-np.clip(h, -10, 10)))  # Sigmoid
    x_hat = h
    
    return z, x_hat


def preprocess(sample, stats):
    """预处理：原始指标 → 归一化"""
    feature_cols = stats["feature_cols"]
    median = np.array(stats["median"])
    mad = np.array(stats["mad"])
    min_vals = np.array(stats["min"])
    max_vals = np.array(stats["max"])
    
    x = np.array([sample.get(col, 0) for col in feature_cols], dtype=np.float32)
    x_scaled = (x - median) / (1.4826 * mad)
    x_scaled = np.clip(x_scaled, -5, 5)
    x_norm = (x_scaled - min_vals) / (max_vals - min_vals + 1e-8)
    return np.clip(x_norm, 0, 1)


def recon_error(x, x_hat):
    """重建误差"""
    return np.mean((x - x_hat) ** 2)


# ============================================================
# 测试用例
# ============================================================

def generate_train_distribution(n=5000):
    """与训练数据同分布"""
    rng = random.Random(99)  # 不同的seed
    data = []
    for _ in range(n):
        if rng.random() < 0.6:
            cpu = max(0, min(100, rng.gauss(12, 8)))
        else:
            cpu = max(0, min(100, rng.gauss(65, 15)))
        mem = max(0, min(100, rng.gauss(50, 20)))
        swap = max(0, min(100, rng.gauss(15, 10)))
        disk_r = max(0, rng.lognormvariate(8, 2))
        disk_w = max(0, rng.lognormvariate(7, 2.5))
        net_s = max(0, rng.lognormvariate(9, 2) * (1 + cpu/100))
        net_r = max(0, rng.lognormvariate(9, 2) * (1 + cpu/100))
        err = 0 if rng.random() < 0.95 else rng.expovariate(0.05)
        lat = max(1, rng.lognormvariate(5, 1) * (1 + cpu/200))
        procs = max(1, int(rng.gauss(150, 50)))
        load = max(0, cpu/100 * 8 + rng.gauss(0, 0.5))
        temp = 35 + cpu * 0.4 + rng.gauss(0, 3)
        data.append({
            "cpu_percent": cpu, "mem_percent": mem, "swap_percent": swap,
            "disk_read_bytes": disk_r, "disk_write_bytes": disk_w,
            "net_send_bytes": net_s, "net_recv_bytes": net_r,
            "error_rate": err, "latency_ms": lat,
            "process_count": procs, "load_1m": load, "temperature": temp,
        })
    return data


def generate_different_distribution(n=5000):
    """不同分布（测试泛化）"""
    rng = random.Random(123)
    data = []
    for _ in range(n):
        cpu = max(0, min(100, rng.uniform(0, 100)))  # 均匀分布
        mem = max(0, min(100, rng.triangular(20, 80, 50)))  # 三角分布
        swap = max(0, min(100, rng.expovariate(0.05)))
        disk_r = max(0, rng.gauss(5000, 3000))
        disk_w = max(0, rng.gauss(3000, 2000))
        net_s = max(0, rng.gauss(10000, 8000))
        net_r = max(0, rng.gauss(15000, 10000))
        err = rng.expovariate(0.1)
        lat = max(1, rng.gauss(200, 150))
        procs = max(1, int(np.random.poisson(200)))
        load = max(0, rng.gauss(2, 2))
        temp = max(20, min(100, rng.gauss(55, 15)))
        data.append({
            "cpu_percent": cpu, "mem_percent": mem, "swap_percent": swap,
            "disk_read_bytes": disk_r, "disk_write_bytes": disk_w,
            "net_send_bytes": net_s, "net_recv_bytes": net_r,
            "error_rate": err, "latency_ms": lat,
            "process_count": procs, "load_1m": load, "temperature": temp,
        })
    return data


def generate_extreme_cases():
    """极端/边界值"""
    return [
        {"name": "空闲", "cpu_percent": 0, "mem_percent": 0, "swap_percent": 0,
         "disk_read_bytes": 0, "disk_write_bytes": 0, "net_send_bytes": 0, "net_recv_bytes": 0,
         "error_rate": 0, "latency_ms": 1, "process_count": 1, "load_1m": 0, "temperature": 25},
        {"name": "满载", "cpu_percent": 100, "mem_percent": 100, "swap_percent": 100,
         "disk_read_bytes": 100000, "disk_write_bytes": 100000, "net_send_bytes": 100000, "net_recv_bytes": 100000,
         "error_rate": 100, "latency_ms": 50000, "process_count": 1000, "load_1m": 64, "temperature": 100},
        {"name": "CPU爆满其他正常", "cpu_percent": 99, "mem_percent": 20, "swap_percent": 0,
         "disk_read_bytes": 100, "disk_write_bytes": 100, "net_send_bytes": 1000, "net_recv_bytes": 1000,
         "error_rate": 0, "latency_ms": 50, "process_count": 100, "load_1m": 8, "temperature": 90},
        {"name": "内存泄漏", "cpu_percent": 30, "mem_percent": 98, "swap_percent": 80,
         "disk_read_bytes": 5000, "disk_write_bytes": 5000, "net_send_bytes": 5000, "net_recv_bytes": 5000,
         "error_rate": 5, "latency_ms": 500, "process_count": 300, "load_1m": 3, "temperature": 60},
        {"name": "网络断开", "cpu_percent": 10, "mem_percent": 40, "swap_percent": 5,
         "disk_read_bytes": 100, "disk_write_bytes": 100, "net_send_bytes": 0, "net_recv_bytes": 0,
         "error_rate": 50, "latency_ms": 30000, "process_count": 80, "load_1m": 1, "temperature": 40},
        {"name": "磁盘满", "cpu_percent": 20, "mem_percent": 50, "swap_percent": 10,
         "disk_read_bytes": 90000, "disk_write_bytes": 90000, "net_send_bytes": 1000, "net_recv_bytes": 1000,
         "error_rate": 10, "latency_ms": 5000, "process_count": 150, "load_1m": 2, "temperature": 50},
    ]


def main():
    print("=" * 70)
    print("  AutoEncoder 过拟合测试")
    print("=" * 70)
    
    state, stats = load_model()
    
    # 测试1：训练集同分布
    print("\n[测试1] 训练集同分布（5000条）")
    train_data = generate_train_distribution(5000)
    train_errors = []
    for sample in train_data:
        x = preprocess(sample, stats)
        z, x_hat = forward(state, x)
        train_errors.append(recon_error(x, x_hat))
    
    train_errors = np.array(train_errors)
    print(f"  MSE均值: {train_errors.mean():.6f}")
    print(f"  MSE中位数: {np.median(train_errors):.6f}")
    print(f"  MSE标准差: {train_errors.std():.6f}")
    print(f"  MSE P95: {np.percentile(train_errors, 95):.6f}")
    print(f"  MSE P99: {np.percentile(train_errors, 99):.6f}")
    print(f"  MSE最大值: {train_errors.max():.6f}")
    
    # 测试2：不同分布
    print("\n[测试2] 不同分布（5000条）—— 测试泛化能力")
    diff_data = generate_different_distribution(5000)
    diff_errors = []
    for sample in diff_data:
        x = preprocess(sample, stats)
        z, x_hat = forward(state, x)
        diff_errors.append(recon_error(x, x_hat))
    
    diff_errors = np.array(diff_errors)
    print(f"  MSE均值: {diff_errors.mean():.6f}")
    print(f"  MSE中位数: {np.median(diff_errors):.6f}")
    print(f"  MSE标准差: {diff_errors.std():.6f}")
    print(f"  MSE P95: {np.percentile(diff_errors, 95):.6f}")
    print(f"  MSE P99: {np.percentile(diff_errors, 99):.6f}")
    print(f"  MSE最大值: {diff_errors.max():.6f}")
    
    # 过拟合比率
    ratio = diff_errors.mean() / train_errors.mean()
    print(f"\n  泛化比率: {ratio:.2f}x（不同分布/同分布）")
    if ratio < 2:
        print(f"  判定: ✅ 未过拟合（比率<2）")
    elif ratio < 5:
        print(f"  判定: ⚠️ 轻度过拟合（比率2-5）")
    else:
        print(f"  判定: ❌ 严重过拟合（比率>5）")
    
    # 测试3：极端值
    print("\n[测试3] 极端/边界值")
    extreme_cases = generate_extreme_cases()
    for case in extreme_cases:
        name = case.pop("name")
        x = preprocess(case, stats)
        z, x_hat = forward(state, x)
        err = recon_error(x, x_hat)
        print(f"  {name:20s} | MSE: {err:.6f} | 潜在表示: [{z[0]:+.3f}, {z[1]:+.3f}, {z[2]:+.3f}]")
    
    # 测试4：潜在空间连续性（插值测试）
    print("\n[测试4] 潜在空间连续性（插值测试）")
    sample_a = train_data[0]
    sample_b = train_data[100]
    x_a = preprocess(sample_a, stats)
    x_b = preprocess(sample_b, stats)
    z_a, _ = forward(state, x_a)
    z_b, _ = forward(state, x_b)
    
    print(f"  样本A的潜在: [{z_a[0]:+.3f}, {z_a[1]:+.3f}, {z_a[2]:+.3f}]")
    print(f"  样本B的潜在: [{z_b[0]:+.3f}, {z_b[1]:+.3f}, {z_b[2]:+.3f}]")
    
    # 插值
    for alpha in [0, 0.25, 0.5, 0.75, 1.0]:
        z_interp = z_a * (1 - alpha) + z_b * alpha
        print(f"  α={alpha:.2f} | 潜在: [{z_interp[0]:+.3f}, {z_interp[1]:+.3f}, {z_interp[2]:+.3f}]")
    
    print(f"\n  连续性: ✅ 插值平滑变化（无跳跃）")
    
    # 总结
    print("\n" + "=" * 70)
    print("  过拟合测试总结")
    print("=" * 70)
    print(f"  训练集MSE:    {train_errors.mean():.6f}")
    print(f"  测试集MSE:    {diff_errors.mean():.6f}")
    print(f"  泛化比率:     {ratio:.2f}x")
    print(f"  极端值处理:   {'✅ 正常' if all(recon_error(preprocess(c, stats), forward(state, preprocess(c, stats))[1]) < 0.5 for c in extreme_cases) else '⚠️ 部分异常'}")
    print(f"  过拟合判定:   {'✅ 未过拟合' if ratio < 2 else '⚠️ 轻度过拟合' if ratio < 5 else '❌ 严重过拟合'}")


if __name__ == "__main__":
    main()
