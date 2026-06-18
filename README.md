# 计算机情绪引擎 V6 — 项目文档

> 最后更新：2026-06-18 | 版本：V6.0

---

## 项目概述

让计算机系统像人一样感知自身状态，输出细腻的情感表达。

## 架构

五层感官 → PAD 映射 → EMA 平滑 → 防闪烁 → ODE 动力 → 7 维情感

```
L1 计算记忆 (Fatigue) ──┐
L2 吞吐排队 (Stress)  ──┤
L3 传导IO (Flow)      ──┼── PAD映射 → EMA → Stabilizer → ODE → 情绪
L4 业务表现 (Confusion)─┤
L5 物理硬件 (终极Fatigue)─┘
```

## 指标统计

| 层 | 原始 | 派生 | 可用 | 数据源 |
|----|------|------|------|--------|
| L1 | 16 | 5 | ✅ 全部 | psutil |
| L2 | 7 | 4 | ✅ 全部 | psutil |
| L3 | 15 | 9 | ✅ 全部 | psutil + WMI |
| L4 | 8 | 2 | ⚠️ 需注入 | Prometheus |
| L5 | 7 | 2 | ⚠️ CPU需管理员 | nvidia-smi + LHM |
| **合计** | **53** | **22** | **45/13 None** | |

## 防闪烁效果（真实数据验证）

| 数据集 | 行数 | EMA only | + Stabilizer | 改善 |
|--------|------|----------|-------------|------|
| 本机实时 | 4,974 | 1.02% | 0.20% | -80% |
| Google 2019 | 10,000 | 48.43% | 1.57% | -97% |
| Google 2011 | 100,000 | 0.00% | 0.00% | — |
| **加权平均** | **114,974** | **4.3%** | **0.6%** | **-86%** |

## 文件清单

```
emotion-engine/
├── real_collector.py          # 五层指标采集器
├── body_sense.py              # 体感系统
├── pad_mapping.py             # PAD 映射公式
├── pad_model.py               # PAD 模型
├── ode_dynamics.py            # ODE 动力系统
├── ema_filter.py              # EMA 滤波器
├── quadrant_stabilizer.py     # 防闪烁控制器
├── l4_metrics.py              # Prometheus 采集
├── l4_proxy.py                # HTTP 代理
├── l5_temp.py                 # 温度采集
├── plutchik.py                # 情绪轮分类
├── template_engine.py         # 表达引擎
├── train_ema.py               # EMA 训练脚本
├── train_ema_full.py          # 完整训练
├── v6_continuous.py           # 持续采集
├── v6_live_test.py            # 单次测试
├── v6_report.html             # 可视化报告
├── data/                      # 真实数据缓存
│   ├── google_metrics_cache.json    # Google 2019 (50K)
│   └── google_2011.json             # Google 2011 (100K)
└── v6_live_data.csv           # 本机实时数据
```

## 桌面快捷方式

| 名称 | 功能 |
|------|------|
| 启动温度监控 | LHM 管理员启动（读 CPU 温度） |
| V6 持续采集 | 后台 1 秒/次采集 |
| V6 情绪引擎测试 | 30 秒单次测试 |
| V6 测试报告 | HTML 可视化 |
| V6 实时数据 | Excel 打开 CSV |

## 已知限制

| 项目 | 状态 | 说明 |
|------|------|------|
| CPU 温度 | 需管理员 | LHM DLL 读取，非管理员返回 None |
| L4 业务数据 | 需外部服务 | 需启动 HTTP 服务 + l4_proxy |
| load_average | Windows 不支持 | Linux/macOS 自动启用 |
| syscalls 计数 | 可能溢出 | 已加负值归零保护 |
| 风扇转速 | Windows 不可用 | 需 OpenHardwareMonitor |

## 变更记录

### V6.0 (2026-06-18)
- 五层感官架构实现
- QuadrantStabilizer 防闪烁控制器
- Prometheus L4 接入框架
- LHM 温度采集
- 真实数据训练验证
- 项目文档更新

### V5.0 (2026-06-17)
- 初始版本
- PAD 映射 + ODE 动力系统
- EMA 滤波器
- Plutchik 情绪轮
- 黑盒/压力测试
