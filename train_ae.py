"""
AutoEncoder 训练脚本

28维系统指标 → 3维PAD空间 → 28维重建

训练流程：
1. 加载预处理数据
2. 训练AutoEncoder
3. 保存模型和统计参数
"""
import os
import sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

# ============================================================
# AutoEncoder 定义（纯NumPy实现，不依赖PyTorch）
# ============================================================

class AutoEncoder:
    """
    纯NumPy实现的AutoEncoder
    
    架构：input(12) → 64 → 32 → 16 → 3(瓶颈) → 16 → 32 → 64 → 12
    
    激活函数：
      - 隐藏层：LeakyReLU
      - 输出层：Sigmoid（输出[0,1]）
    """
    
    def __init__(self, input_dim=12, latent_dim=3, seed=42):
        np.random.seed(seed)
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        
        # 编码器层维度
        self.enc_dims = [input_dim, 64, 32, 16, latent_dim]
        # 解码器层维度
        self.dec_dims = [latent_dim, 16, 32, 64, input_dim]
        
        # 初始化权重
        self.enc_weights = []
        self.enc_biases = []
        for i in range(len(self.enc_dims) - 1):
            # He初始化
            scale = np.sqrt(2.0 / self.enc_dims[i])
            W = np.random.randn(self.enc_dims[i], self.enc_dims[i+1]).astype(np.float32) * scale
            b = np.zeros(self.enc_dims[i+1], dtype=np.float32)
            self.enc_weights.append(W)
            self.enc_biases.append(b)
        
        self.dec_weights = []
        self.dec_biases = []
        for i in range(len(self.dec_dims) - 1):
            scale = np.sqrt(2.0 / self.dec_dims[i])
            W = np.random.randn(self.dec_dims[i], self.dec_dims[i+1]).astype(np.float32) * scale
            b = np.zeros(self.dec_dims[i+1], dtype=np.float32)
            self.dec_weights.append(W)
            self.dec_biases.append(b)
    
    def _leaky_relu(self, x, alpha=0.01):
        return np.where(x > 0, x, alpha * x)
    
    def _leaky_relu_grad(self, x, alpha=0.01):
        return np.where(x > 0, 1.0, alpha)
    
    def _sigmoid(self, x):
        x = np.clip(x, -10, 10)
        return 1.0 / (1.0 + np.exp(-x))
    
    def encode(self, x):
        """编码：输入 → 隐藏表示"""
        h = x
        self.enc_activations = [h]
        self.enc_pre_activations = []
        
        for i in range(len(self.enc_weights)):
            z = h @ self.enc_weights[i] + self.enc_biases[i]
            self.enc_pre_activations.append(z)
            
            if i < len(self.enc_weights) - 1:
                h = self._leaky_relu(z)
            else:
                h = np.tanh(z)  # 瓶颈层用tanh，输出[-1,1]
            
            self.enc_activations.append(h)
        
        return h
    
    def decode(self, z):
        """解码：隐藏表示 → 重建"""
        h = z
        self.dec_activations = [h]
        self.dec_pre_activations = []
        
        for i in range(len(self.dec_weights)):
            z_dec = h @ self.dec_weights[i] + self.dec_biases[i]
            self.dec_pre_activations.append(z_dec)
            
            if i < len(self.dec_weights) - 1:
                h = self._leaky_relu(z_dec)
            else:
                h = self._sigmoid(z_dec)  # 输出层用Sigmoid
            
            self.dec_activations.append(h)
        
        return h
    
    def forward(self, x):
        """前向传播"""
        z = self.encode(x)
        x_hat = self.decode(z)
        return z, x_hat
    
    def backward(self, x, z, x_hat, lr=0.001):
        """
        反向传播 + 权重更新
        
        损失函数：MSE + L2正则
        """
        batch_size = x.shape[0]
        
        # === 解码器反向传播 ===
        # 输出层梯度 (MSE损失)
        delta_dec = (x_hat - x) / batch_size  # (batch, input_dim)
        
        dec_grads_w = []
        dec_grads_b = []
        
        for i in range(len(self.dec_weights) - 1, -1, -1):
            # Sigmoid导数（输出层）
            if i == len(self.dec_weights) - 1:
                sig = self.dec_activations[i+1]
                delta_dec = delta_dec * sig * (1 - sig)
            
            dW = self.dec_activations[i].T @ delta_dec
            db = delta_dec.sum(axis=0)
            dec_grads_w.insert(0, dW)
            dec_grads_b.insert(0, db)
            
            if i > 0:
                delta_dec = delta_dec @ self.dec_weights[i].T
                delta_dec = delta_dec * self._leaky_relu_grad(self.dec_pre_activations[i-1])
        
        # === 编码器反向传播 ===
        # 从解码器传来的梯度
        delta_enc = delta_dec @ self.dec_weights[0].T
        delta_enc = delta_enc * (1 - z**2)  # tanh导数
        
        enc_grads_w = []
        enc_grads_b = []
        
        for i in range(len(self.enc_weights) - 1, -1, -1):
            dW = self.enc_activations[i].T @ delta_enc
            db = delta_enc.sum(axis=0)
            enc_grads_w.insert(0, dW)
            enc_grads_b.insert(0, db)
            
            if i > 0:
                delta_enc = delta_enc @ self.enc_weights[i].T
                delta_enc = delta_enc * self._leaky_relu_grad(self.enc_pre_activations[i-1])
        
        # === 权重更新（带动量） ===
        if not hasattr(self, 'enc_w_momentum'):
            self.enc_w_momentum = [np.zeros_like(w) for w in self.enc_weights]
            self.enc_b_momentum = [np.zeros_like(b) for b in self.enc_biases]
            self.dec_w_momentum = [np.zeros_like(w) for w in self.dec_weights]
            self.dec_b_momentum = [np.zeros_like(b) for b in self.dec_biases]
        
        momentum = 0.9
        l2_reg = 1e-5
        
        for i in range(len(self.enc_weights)):
            self.enc_w_momentum[i] = momentum * self.enc_w_momentum[i] - lr * (enc_grads_w[i] + l2_reg * self.enc_weights[i])
            self.enc_b_momentum[i] = momentum * self.enc_b_momentum[i] - lr * enc_grads_b[i]
            self.enc_weights[i] += self.enc_w_momentum[i]
            self.enc_biases[i] += self.enc_b_momentum[i]
        
        for i in range(len(self.dec_weights)):
            self.dec_w_momentum[i] = momentum * self.dec_w_momentum[i] - lr * (dec_grads_w[i] + l2_reg * self.dec_weights[i])
            self.dec_b_momentum[i] = momentum * self.dec_b_momentum[i] - lr * dec_grads_b[i]
            self.dec_weights[i] += self.dec_w_momentum[i]
            self.dec_biases[i] += self.dec_b_momentum[i]
        
        # 返回损失值
        mse = np.mean((x - x_hat) ** 2)
        return mse
    
    def save(self, path):
        """保存模型"""
        state = {
            "input_dim": self.input_dim,
            "latent_dim": self.latent_dim,
            "enc_weights": [w.tolist() for w in self.enc_weights],
            "enc_biases": [b.tolist() for b in self.enc_biases],
            "dec_weights": [w.tolist() for w in self.dec_weights],
            "dec_biases": [b.tolist() for b in self.dec_biases],
        }
        with open(path, "w") as f:
            json.dump(state, f)
    
    @classmethod
    def load(cls, path):
        """加载模型"""
        with open(path, "r") as f:
            state = json.load(f)
        
        ae = cls(state["input_dim"], state["latent_dim"])
        ae.enc_weights = [np.array(w, dtype=np.float32) for w in state["enc_weights"]]
        ae.enc_biases = [np.array(b, dtype=np.float32) for b in state["enc_biases"]]
        ae.dec_weights = [np.array(w, dtype=np.float32) for w in state["dec_weights"]]
        ae.dec_biases = [np.array(b, dtype=np.float32) for b in state["dec_biases"]]
        return ae


def train():
    """训练AutoEncoder"""
    print("=== AutoEncoder 训练 ===\n")
    
    # 加载数据
    data_path = os.path.join(DATA_DIR, "ae_train_data.npy")
    stats_path = os.path.join(DATA_DIR, "ae_stats.json")
    
    if not os.path.exists(data_path):
        print("数据文件不存在，先运行 ae_dataset.py 生成数据...")
        import ae_dataset
        data = ae_dataset.download_google_trace_sample()
        X, stats = ae_dataset.preprocess_for_ae(data)
        np.save(data_path, X)
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)
    else:
        X = np.load(data_path)
        with open(stats_path) as f:
            stats = json.load(f)
    
    print(f"训练数据: {X.shape}")
    print(f"特征数: {X.shape[1]}")
    print(f"样本数: {X.shape[0]}")
    print(f"值域: [{X.min():.3f}, {X.max():.3f}]")
    print()
    
    # 创建AutoEncoder
    ae = AutoEncoder(input_dim=X.shape[1], latent_dim=3)
    
    # 训练参数
    n_epochs = 200
    batch_size = 256
    lr = 0.001
    lr_decay = 0.995
    
    n_samples = X.shape[0]
    n_batches = n_samples // batch_size
    
    print(f"训练参数:")
    print(f"  epochs: {n_epochs}")
    print(f"  batch_size: {batch_size}")
    print(f"  学习率: {lr} (衰减: {lr_decay})")
    print(f"  每epoch批次数: {n_batches}")
    print()
    
    # 训练循环
    losses = []
    best_loss = float('inf')
    
    t0 = time.time()
    
    for epoch in range(n_epochs):
        # 打乱数据
        perm = np.random.permutation(n_samples)
        X_shuffled = X[perm]
        
        epoch_loss = 0
        
        for batch_idx in range(n_batches):
            start = batch_idx * batch_size
            end = start + batch_size
            x_batch = X_shuffled[start:end]
            
            # 前向传播
            z, x_hat = ae.forward(x_batch)
            
            # 反向传播 + 更新
            loss = ae.backward(x_batch, z, x_hat, lr=lr)
            epoch_loss += loss
        
        epoch_loss /= n_batches
        losses.append(epoch_loss)
        
        # 学习率衰减
        lr *= lr_decay
        
        # 保存最佳模型
        if epoch_loss < best_loss:
            best_loss = epoch_loss
            ae.save(os.path.join(MODEL_DIR, "ae_best.json"))
        
        # 打印进度
        if (epoch + 1) % 10 == 0 or epoch == 0:
            elapsed = time.time() - t0
            eta = elapsed / (epoch + 1) * (n_epochs - epoch - 1)
            print(f"  Epoch {epoch+1:4d}/{n_epochs} | Loss: {epoch_loss:.6f} | "
                  f"Best: {best_loss:.6f} | LR: {lr:.6f} | "
                  f"ETA: {eta:.0f}s")
    
    elapsed = time.time() - t0
    print(f"\n训练完成!")
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"  最终损失: {losses[-1]:.6f}")
    print(f"  最佳损失: {best_loss:.6f}")
    
    # 保存最终模型
    ae.save(os.path.join(MODEL_DIR, "ae_final.json"))
    
    # 保存训练历史
    history = {
        "losses": losses,
        "best_loss": best_loss,
        "n_epochs": n_epochs,
        "batch_size": batch_size,
        "final_lr": lr,
        "training_time": elapsed,
    }
    with open(os.path.join(MODEL_DIR, "training_history.json"), "w") as f:
        json.dump(history, f, indent=2)
    
    # 测试重建质量
    print(f"\n重建质量测试:")
    z, x_hat = ae.forward(X[:100])
    recon_error = np.mean((X[:100] - x_hat) ** 2, axis=0)
    for i, col in enumerate(stats["feature_cols"]):
        print(f"  {col:20s} | 重建误差: {recon_error[i]:.6f}")
    
    # 保存统计参数（推理时需要）
    stats_save = os.path.join(MODEL_DIR, "ae_stats.json")
    with open(stats_save, "w") as f:
        json.dump(stats, f, indent=2)
    
    print(f"\n模型文件:")
    print(f"  最佳模型: {os.path.join(MODEL_DIR, 'ae_best.json')}")
    print(f"  最终模型: {os.path.join(MODEL_DIR, 'ae_final.json')}")
    print(f"  统计参数: {stats_save}")
    print(f"  训练历史: {os.path.join(MODEL_DIR, 'training_history.json')}")
    
    return ae, stats


if __name__ == "__main__":
    train()
