# 情绪引擎 (Emotion Engine)

> 用拟人化的情绪维度（愉悦度 P / 唤醒度 A / 支配度 D）实时刻画系统健康状态，
> 让运维人员像"读懂一个人"一样读懂机器。基于 Mehrabian PAD 三维情绪模型。

**版本：V6.4** ｜ **更新：2026-06-22** ｜ **状态：核心管线已修复，项目结构整理完成**

---

## 已修复问题（V6.2 审查于 2026-06-19）

| 缺陷 | 位置 | 修复 |
|------|------|------|
| `oscillation_suppress` 属性未定义 | `quadrant_stabilizer.py` | ✅ 新增参数 + `self.oscillation_suppress` 赋值 |
| EMA 默认值与 V6 训练结果不一致 | `ema_filter.py` | ✅ 改为 `(0.35, 0.60)` |
| `io_congestion` 用累计计数器 | `real_collector.py` | ✅ 改用增量计算 |
| `_thread_cache` 懒初始化脆弱 | `real_collector.py` | ✅ 移到 `__init__` |
| BodySense 管线断裂 | `context_pad.py` | ✅ `compose_pad()` 新增 `body` 参数 |
| `compute_target()` ~80 行重复代码 | `ode_dynamics.py` | ✅ 委托给 `pad_mapping.compute_pad_raw()` |
| `except:` 裸 catch 吞异常 | `template_engine.py` | ✅ 改为 `except (ValueError, OverflowError):` |
| `OutputThrottler` 用步数而非时间 | `template_engine.py` | ✅ 改用 `time.monotonic()` |
| docstring 版本标签混乱 | 多文件 | ✅ 统一为 V6.0/V6.2 |

## ⚠️ 剩余问题

| 问题 | 位置 | 说明 |
|------|------|------|
| `cross_validate.py` 失效 | `cross_validate.py:23` | Stabilizer API 重构后 `hysteresis=` kwarg 已删除 → `TypeError`，待适配 |
| `final_validation.py` 失效 | `final_validation.py:25` | 同上 + `g2011` 结构不匹配，待适配 |
| `main.py` 遗留路径 | `main.py` | 使用 V3/V4 的 `metrics_to_pad()`，未接入 V6 BodySense 管线 |

> **闪烁率数据说明**：原文档引用的 1.11% / 1.43% 加权闪烁率来自现已失效的 `cross_validate.py`，
> 无法复现。下文"防闪烁能力"表中的数值为 2026-06-19 用**新上下文感知管线**（Stabilizer 的
> `oscillation_suppress` bug 临时补丁后）重测的结果，**应以修复后的脚本为最终基准**。

---

## 项目简介

本引擎把机器的运行指标翻译成人类的情绪语言。一台服务器的 CPU 飙高、错误率上升、
响应变慢，在 PAD 空间里会体现为"愉悦度下降、唤醒度上升、支配度下降"——也就是
**焦虑 / 慌乱**。运维看到的不是一堆数字，而是一个有情绪、会波动的"数字生命体"。

核心创新：**用上下文修正 PAD 映射**。同样的 CPU=90%，在"安静系统突然变忙"和
"已过载且错误频发"两种上下文下，对应完全不同的情绪状态（兴奋 vs 恐慌）。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│  采集层 (5 层 / 58 原始指标)        real_collector.py             │
│  L1 CPU/内存 │ L2 网络/进程 │ L3 磁盘/IO │ L4 业务指标 │ L5 温度 │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  语义信号层 (NEW V6)               semantic_signals.py           │
│  从原始指标抽取"上下文"：overload / contradiction / clean / …     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  上下文感知 PAD 映射 (NEW V6)      context_pad.py + pad_model.py │
│  根据语义上下文调整 P/A/D 映射权重，输出 [-1,1] 的连续情绪值       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  平滑层 EMA + 稳定层 象限稳定器                                    │
│  ema_filter.py (自适应指数平滑)  +  quadrant_stabilizer.py        │
│  (上下文自适应死区 + 惯性 + 震荡抑制*)                             │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  连续动态演化 (ODE)                v6_continuous.py               │
│  PAD 状态在时间轴上按 ODE 连续演化，避免突变                       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
              8 象限情绪标签 (calm_happy / panic / …)
```

> *\* 震荡抑制已于 V6.2 修复。*

---

## 核心模块清单

| 文件 | 职责 | 状态 |
|------|------|------|
| `real_collector.py` | 5 层指标采集（58 原始 + 29 派生） | ✅ |
| `semantic_signals.py` | **新**：从指标抽取语义上下文（overload/contradiction/clean 等） | ✅ |
| `context_pad.py` | **新**：上下文感知的 PAD 映射计算 | ✅ |
| `pad_model.py` | PAD 状态、8 象限分类、健康分计算 | ✅ |
| `pad_mapping.py` | PAD 映射底层算子（hysteresis/矛盾检测/波动率） | ✅ V6.1 已恢复 |
| `ode_dynamics.py` | PAD 连续演化 ODE（τ: P=60,A=25,D=40,V=45,F=600,T=90,C=180） | ✅ |
| `ema_filter.py` | 自适应 EMA 平滑（V6 参数：α_slow=0.35, α_fast=0.60） | ✅ |
| `quadrant_stabilizer.py` | 象限稳定器（上下文自适应死区 + 惯性 + 震荡抑制） | ✅ |
| `l4_metrics.py` / `l4_proxy.py` | L4 业务指标采集与代理 | ✅ |
| `l5_temp.py` | L5 温度/硬件采集 | ✅ |
| `plutchik.py` | Plutchik 8 基本情绪配色 | ✅ |
| `template_engine.py` | 情绪报告渲染 | ✅ |
| `v6_continuous.py` | V6 连续动态主程序（含 error/latency 语义信号代理） | ✅ |
| `v6_live_test.py` | 实时采集测试入口 | ✅ |
| `data_audit.py` | 数据集审计（行数/范围/缺失检查） | ✅ |
| `cross_validate.py` | 跨数据集验证（⚠️ 失效） | ❌ |
| `final_validation.py` | 最终验证（⚠️ 失效） | ❌ |
| `train_ema.py` / `train_ema_full.py` | EMA 参数训练 | ✅ |

---

## 数据集

| 数据集 | 来源 | 行数 | 说明 |
|--------|------|------|------|
| `v6_live_data.csv` | 本机实时采集 | **1,320** | 含 `sig_*` 语义信号列，新管线实际运行数据 |
| `data/google_metrics_cache.json` | Google 2019 (Borg) | **50,000** | 数据中心真实负载 |
| `data/google_2011.json` | Google 2011 (Borg) | 100,000 | `[cpu, mem]` 二元组；CPU 均值极低（~1.5%），数据偏静，闪烁率不具代表性 |
| **合计** | | **151,320** | |

> 数据集审计可运行 `python data_audit.py`（正常）。

---

## 防闪烁能力（2026-06-19 重测）

> ⚠️ 下列数值用新管线重测；Stabilizer 的 `oscillation_suppress` bug 用临时补丁绕过后测得。
> **待修复 cross_validate.py / final_validation.py 后，以脚本输出为最终基准。**

| 数据集 | 行数 | 闪烁率 |
|--------|------|--------|
| 本机实时 | 1,320 | ~0.00% |
| Google 2019 | 50,000 | ~0.00% |
| Google 2011 | 100,000 | ~1.0% |
| **加权平均** | **151,320** | **~0.68%** |

防抖机制（按设计）：上下文自适应死区 → 惯性滤波 → 震荡抑制（*此分支当前有 bug*）→ 象限滞回已移除。

---

## 指标统计

| 类别 | 数量 |
|------|------|
| 原始指标（5 层） | **58** |
| 派生指标 | **29** |
| 合计 | 87 |

各层原始指标分布：L1 CPU/内存=21 ｜ L2 网络/进程=6 ｜ L3 磁盘/IO=17 ｜ L4 业务=8 ｜ L5 温度/硬件=6（共 58，不含 timestamp）。

---

## 快速开始

```bash
# 实时采集 + 情绪推理
python v6_live_test.py

# 连续动态演化主程序
python v6_continuous.py

# 数据集审计
python data_audit.py

# 运行 scripts/ 或 tests/ 下的脚本（需从项目根目录执行）
PYTHONPATH=. python scripts/demo_extreme.py
PYTHONPATH=. python tests/test_full_pipeline.py
```

> `cross_validate.py` 与 `final_validation.py` 当前因 Stabilizer API 变更失效，运行会报 `TypeError: __init__() got an unexpected keyword argument 'hysteresis'`。

---

## 变更记录

### V6.4 — 2026-06-22（本次）
- **Kalman 滤波器**：新增 `kalman_filter.py`，ODE-Kalman 融合滤波器，将 V→A 耦合显式编码在状态转移矩阵 F 中，从根本上消除 lag1 自相关。
  - 支持 NIS 自适应 Q 调整
  - `--kalman` 参数启用，替代 EMA+Stabilizer
  - 残差分析工具 `scripts/compare_residuals.py` 用于 ODE vs Kalman 对比

### V6.3 — 2026-06-21
- **项目整理**：临时调试脚本移至 ，测试脚本移至 ，根目录从 ~80 文件精简至 ~40 文件。
- 删除误创建的  文件夹。
- 更新版本号至 V6.3。

### V6.2 — 2026-06-19
- **修复 P0**：`quadrant_stabilizer.py` 新增 `oscillation_suppress` 属性，震荡检测不再崩溃。
- **修复 P0**：`template_engine.py` 裸 `except:` 改为具体异常类型。
- **修复 P1**：`ema_filter.py` 默认参数改为 V6 训练值 `(0.35, 0.60)`。
- **修复 P1**：`real_collector.py` `io_congestion` 改用增量计算；`_thread_cache` 移到 `__init__`。
- **修复 P1**：`context_pad.py` `compose_pad()` 新增 `body` 参数，打通 BodySense → PAD 管线。
- **修复 P1**：`ode_dynamics.py` `compute_target()` 委托给 `pad_mapping.compute_pad_raw()`，消除 ~80 行重复代码。
- **修复 P2**：`template_engine.py` `OutputThrottler` 改用 `time.monotonic()` 真实时间。
- **修复 P2**：多文件 docstring 版本标签统一为 V6.0。

### V6.1 — 2026-06-19
- 恢复 `pad_mapping.py` 至正确版本（原工作区文件编码损坏导致 `import` 失败）。
- 新增"已知代码缺陷"表，修正指标统计、数据集行数、闪烁率重测。
- 补充新管线架构说明。

### V6.0 — 架构升级（此前）
- 引入上下文感知 PAD 映射（`context_pad.py`）。
- 引入语义信号层（`semantic_signals.py`）。
- `v6_continuous.py` 增加 error/latency 语义信号代理采集。
- Stabilizer 重构：移除滞回，改为上下文自适应死区 + 惯性。
