# 五层感官架构 — 指标分类与缺失分析

> V6 实现完成 | 2026-06-18

---

## 总览

```
┌─────────────────────────────────────────────────────┐
│                   🧠 大脑 (Brain)                     │
│         ODE 动力系统 · PAD 映射 · 表达生成              │
│         消费全部 5 层输出 → 7 维情感状态                 │
└────────┬──────┬──────┬──────┬──────┬─────────────────┘
         │      │      │      │      │
    ┌────▼───┐┌─▼────┐┌▼────┐┌▼────┐┌▼─────┐
    │  L1    ││ L2   ││ L3  ││ L4  ││ L5   │
    │计算记忆││吞吐  ││传导 ││业务 ││物理  │
    │Fatigue ││Stress││Flow ││Flow ││Fatigue│
    └────────┘└──────┘└─────┘└─────┘└──────┘
```

| 层 | 名称 | 支撑情绪 | 情绪含义 |
|----|------|----------|----------|
| L1 | 计算与记忆层 | Fatigue | "我已经累了"——长时间高负载的累积消耗 |
| L2 | 吞吐与排队层 | Stress | "我快撑不住了"——请求堆积、排队堵塞 |
| L3 | 传导与IO层 | Stress + Flow | "卡/顺"——数据流动的阻塞与通畅 |
| L4 | 业务表现层 | Flow / Confusion | "我在做事/我搞砸了"——业务结果好坏 |
| L5 | 物理硬件层 | Fatigue (终极) | "身体不行了"——物理层面的不可逆损耗 |

---

## L1 · 计算与记忆层 → Fatigue（疲劳度 / 累）

**生理类比：** 大脑皮层 + 海马体。CPU 是算力（思考），内存是工作记忆（记住正在做什么）。
**情绪输出：** 疲劳度 [0, 1]。累的感觉来得慢、走得慢（τ=600s 半衰期）。

### 已有指标 ✅

| 指标 | 来源 | 用途 | 状态 |
|------|------|------|------|
| `cpu_percent` | psutil | 主负载信号 | ✅ 直接可用 |
| `cpu_per_core` | psutil | 核间均衡（不均衡=某区域过劳） | ✅ 直接可用 |
| `mem_percent` | psutil | 工作记忆占用 | ✅ 直接可用 |
| `mem_available_gb` | psutil | 记忆余量 | ✅ 直接可用 |
| `cpu_user` | psutil | 有效思考时间 | ✅ 直接可用 |
| `cpu_system` | psutil | 系统开销时间 | ✅ 直接可用 |
| `cpu_idle` | psutil | 空闲时间 | ✅ 直接可用 |
| `ctx_switches_rate` | psutil (派生) | 思维切换频率 | ✅ 已接入体感 |
| `syscalls_rate` | psutil (派生) | 指令执行频率 | ✅ 已接入体感 |
| `cpu_core_variance` | psutil (派生) | 核间不均衡度 | ✅ 已计算 |

### 缺失指标 ❌

| 指标 | 说明 | 获取方式 | 优先级 |
|------|------|----------|--------|
| `cpu_freq_mhz` | 当前频率（过热降频=被迫放慢思考） | `psutil.cpu_freq()` | 🟡 中 |
| `cpu_freq_ratio` | 当前/最大频率比（降频=体力不支） | 同上 | 🟡 中 |
| `load_average` | 系统负载均值（Linux 可用，Windows 无） | `psutil.get_loadavg()` | 🔴 低（跨平台） |
| `oom_kill_count` | OOM 杀进程次数（记忆耗尽=晕过去） | 日志解析 / Windows事件 | 🔴 高但难 |

### 疲劳度计算模型

```
Fatigue_L1 = EMA_τ600(
    0.4 × cpu_norm +                    # 算力消耗
    0.25 × mem_norm +                   # 记忆压力
    0.15 × max(ctx_fatigue, syscall_fatigue) +  # 思维切换开销
    0.1 × core_imbalance +              # 局部过劳
    0.1 × freq_penalty                  # 降频惩罚（如可获取）
)
```

**可行性：95%**。现有指标覆盖度很高，缺失的 `cpu_freq` 通过 psutil 一行代码补充。OOM 需要额外解析，但非必须。

---

## L2 · 吞吐与排队层 → Stress（压力 / 紧绷）

**生理类比：** 咽喉 + 消化道。请求从外部进来要排队处理，吞吐量是"吃的速度"，队列是"胃里的积压"。
**情绪输出：** Stress [0, 1]。排队长=紧绷，吞吐低=压力大。

### 已有指标 ✅

| 指标 | 来源 | 用途 | 状态 |
|------|------|------|------|
| `conn_established` | psutil | 正在处理的连接（活跃任务） | ✅ 直接可用 |
| `conn_listen` | psutil | 等待接受的连接（排队等候） | ✅ 直接可用 |
| `conn_total` | psutil | 总连接数（总工作量） | ✅ 直接可用 |
| `conn_time_wait` | psutil | 已完成但未释放（消化残留） | ✅ 直接可用 |
| `process_count` | psutil | 进程数（并发工人） | ✅ 直接可用 |
| `process_count_delta` | psutil (派生) | 进程变化率（崩了还是新增） | ✅ 已计算 |
| `close_wait_ratio` | psutil (派生) | 连接泄漏比 | ✅ 已计算 |

### 缺失指标 ❌

| 指标 | 说明 | 获取方式 | 优先级 |
|------|------|----------|--------|
| **`thread_pool_active`** | 线程池活跃数（真正干活的线程） | 需应用层暴露 | 🔴 高 |
| **`thread_pool_queue`** | 线程池排队长度（核心！排队=压力） | 需应用层暴露 | 🔴 高 |
| **`request_queue_depth`** | HTTP/业务请求队列深度 | 需应用层/反向代理暴露 | 🔴 高 |
| `accept_backlog` | TCP accept 队列积压 | `ss -ltn` / Windows 需 WMI | 🟡 中 |
| `context_switch_volatility` | 上下文切换的波动性（不稳定的调度） | 从历史计算 | 🟡 中 |
| `thread_count` | 系统总线程数 | `psutil` 可取 | 🟢 低 |

### 压力计算模型

```
Stress_L2 = clamp(
    0.3 × conn_pressure +          # 连接积压
    0.25 × listen_backlog_norm +    # 排队等候
    0.2 × close_wait_stress +       # 连接泄漏
    0.15 × process_volatility +     # 进程不稳定
    0.1 × thread_queue_norm         # 线程排队（如可获取）
)
```

**可行性：70%**。连接类指标齐全，但**排队深度（核心信号）需要应用层配合**。没有队列深度，"压力"就只能靠连接数间接推算，精度打折。

---

## L3 · 传导与IO层 → Stress & Flow（紧绷与流畅）

**生理类比：** 血管 + 神经。数据在磁盘和网络间流动，像血液在血管里流淌。阻塞=栓塞，通畅=血液循环好。
**情绪输出：** 双向——IO 阻塞→紧绷，IO 通畅→流畅。

### 已有指标 ✅

| 指标 | 来源 | 用途 | 状态 |
|------|------|------|------|
| `disk_read_bytes` | psutil | 磁盘读取量 | ✅ 直接可用 |
| `disk_write_bytes` | psutil | 磁盘写入量 | ✅ 直接可用 |
| `disk_read_count` | psutil | 读取次数 (IOPS) | ✅ 直接可用 |
| `disk_write_count` | psutil | 写入次数 (IOPS) | ✅ 直接可用 |
| `disk_throughput_mbps` | psutil (派生) | 磁盘吞吐 | ✅ 已计算 |
| `net_sent_bytes` | psutil | 网络发送量 | ✅ 直接可用 |
| `net_recv_bytes` | psutil | 网络接收量 | ✅ 直接可用 |
| `net_sent_packets` | psutil | 发送包数 | ✅ 直接可用 |
| `net_recv_packets` | psutil | 接收包数 | ✅ 直接可用 |
| `net_errin/out` | psutil | 网络错误 | ✅ 直接可用 |
| `net_dropin/out` | psutil | 网络丢包 | ✅ 直接可用 |
| `net_throughput_mbps` | psutil (派生) | 网络吞吐 | ✅ 已计算 |
| `net_error_rate` | psutil (派生) | 网络错误率 | ✅ 已计算 |
| `io_congestion` | psutil (派生) | 读写比异常 | ✅ 已计算 |
| `latency_ms` | 外部注入 | 响应延迟 | ✅ 已有 |
| `lat_velocity` | 派生 | 延迟变化率 | ✅ 已有 |

### 缺失指标 ❌

| 指标 | 说明 | 获取方式 | 优先级 |
|------|------|----------|--------|
| **`disk_io_latency_ms`** | 磁盘单次IO延迟（栓塞的直接信号） | 需 `iostat` / perfcounter | 🔴 高 |
| **`disk_queue_depth`** | 磁盘队列深度（IO排队=血管堵了） | 需 perfcounter | 🔴 高 |
| `net_rtt_ms` | 网络往返延迟 | 需主动探测 | 🟡 中 |
| `tcp_retransmit_count` | TCP 重传次数（传输质量） | `psutil.net_io_counters` 部分覆盖 | 🟡 中 |
| `io_wait_percent` | IO 等待占比 | Windows 不支持 | 🔴 N/A |

### 紧绷/流畅计算模型

```
# 紧绷：IO 阻塞
Stress_L3 = clamp(
    0.3 × disk_queue_norm +         # 磁盘排队
    0.25 × io_latency_norm +        # IO 延迟
    0.2 × net_error_stress +        # 网络错误
    0.15 × net_drop_stress +        # 网络丢包
    0.1 × io_congestion              # 读写比异常
)

# 流畅：IO 通畅
Flow_L3 = clamp(
    0.4 × (1 - disk_queue_norm) +   # 磁盘不排队
    0.3 × throughput_health +        # 吞吐健康
    0.2 × (1 - net_error_rate) +    # 网络无错
    0.1 × low_latency_bonus         # 低延迟奖励
)
```

**可行性：75%**。网络指标覆盖良好。**磁盘 IO 延迟和队列深度是关键缺失**，Windows 上需要通过 Performance Counter (`perfmon`) 获取，psutil 不直接支持。可以用 `wmi` 模块或 `subprocess` 调 `typeperf` 作为替代方案。

---

## L4 · 业务表现层 → Flow（流畅）/ Confusion（困惑）

**生理类比：** 嘴巴 + 手。系统的"输出能力"——做事做得好不好、说得对不对。
**情绪输出：** 做得好→流畅（喜悦/自信），做砸了→困惑（惊讶/恐惧）。

### 已有指标 ✅

| 指标 | 来源 | 用途 | 状态 |
|------|------|------|------|
| `error_rate` | 外部注入 | 业务错误率 | ⚠️ 当前靠模拟器注入 |
| `err_velocity` | 派生 | 错误飙升速度 | ✅ 已计算 |
| `err_trend` | 派生 | 错误长期趋势 | ✅ 已计算 |

### 缺失指标 ❌

| 指标 | 说明 | 获取方式 | 优先级 |
|------|------|----------|--------|
| **`http_5xx_rate`** | 服务端错误率（做砸了） | Nginx/Apache 日志、APM | 🔴 高 |
| **`http_4xx_rate`** | 客户端错误率（别人搞错了） | 同上 | 🔴 高 |
| **`response_p99_ms`** | P99 延迟（最慢的那些请求） | APM / Prometheus | 🔴 高 |
| **`response_p50_ms`** | P50 延迟（中位数，代表典型体验） | APM / Prometheus | 🔴 高 |
| **`success_rate`** | 成功率（1 - error_rate） | 计算 | 🟢 低 |
| **`throughput_rps`** | 每秒请求数（做事的速度） | Nginx 日志、APM | 🟡 中 |
| **`timeout_rate`** | 超时率（做一半放弃了） | APM | 🟡 中 |
| **`retry_rate`** | 重试率（不确定做对了没） | APM | 🟡 中 |
| **`cache_hit_rate`** | 缓存命中率（记住了不用重做） | Redis/Memcached stats | 🟡 中 |
| **`error_diversity`** | 错误类型多样性（乱了=困惑） | 日志分类 | 🔴 低（难量化） |

### 流畅/困惑计算模型

```
# 流畅：业务做得好
Flow_L4 = clamp(
    0.4 × success_rate +
    0.25 × (1 - p99_latency_norm) +  # 最慢请求也不慢
    0.2 × throughput_health +          # 请求量健康
    0.15 × cache_hit_bonus             # 缓存命中奖励
)

# 困惑：业务做砸了
Confusion_L4 = clamp(
    0.35 × error_severity +            # 错误严重度
    0.25 × error_diversity +           # 错误种类多=不知道哪错了
    0.2 × timeout_stress +             # 超时=做不完
    0.2 × retry_stress                 # 重试=不确定
)
```

**可行性：40%**。这是**五层中缺口最大的一层**。当前系统只有 `error_rate` 一个业务指标（且靠模拟器注入），其余全部需要接入真实应用层数据。这是架构上必须补齐的——没有业务数据，"困惑"和"流畅"就只能靠系统指标间接猜。

**落地路径：**
1. **短期**：解析 Nginx 访问日志 → 提取 5xx/4xx/响应时间
2. **中期**：接入 Prometheus/Grafana 的 HTTP 指标
3. **长期**：APM 埋点（SkyWalking / OpenTelemetry）

---

## L5 · 物理硬件层 → Fatigue（终极物理疲劳）

**生理类比：** 骨骼 + 皮肤 + 器官老化。软件优化不了的物理极限。
**情绪输出：** 终极 Fatigue [0, 1]。温度高、磁盘老化、电源不稳——这是"身体本身不行了"。

### 已有指标 ✅

| 指标 | 来源 | 用途 | 状态 |
|------|------|------|------|
| `disk_usage_c` | psutil | C盘使用率（骨密度） | ✅ 直接可用 |
| `disk_usage_d` | psutil | D盘使用率 | ✅ 直接可用 |
| `swap_percent` | psutil | Swap 使用（代偿） | ✅ 直接可用 |
| `disk_pressure` | 派生 | 磁盘压力 | ✅ 已计算 |

### 缺失指标 ❌

| 指标 | 说明 | 获取方式 | 优先级 |
|------|------|----------|--------|
| **`cpu_temp`** | CPU 温度（过热=发烧） | `wmi` / OpenHardwareMonitor | 🔴 高 |
| **`cpu_throttle`** | 是否降频（过热被迫减速） | `wmi` / 频率比对 | 🔴 高 |
| **`gpu_temp`** | GPU 温度（如果有） | `wmi` / nvidia-smi | 🟡 中 |
| **`gpu_usage`** | GPU 使用率 | `wmi` / nvidia-smi | 🟡 中 |
| **`disk_health`** | 磁盘 SMART 健康度（老化） | `smartctl` / WMI | 🟡 中 |
| **`disk_bad_sectors`** | 坏道数（骨裂） | SMART | 🟡 中 |
| **`fan_speed`** | 风扇转速（散热能力） | `wmi` / OpenHardwareMonitor | 🟡 中 |
| **`power_status`** | 电源状态（笔记本电池） | `psutil.sensors_battery()` | 🟢 低 |
| **`disk_io_errors`** | 硬件 IO 错误 | SMART / 系统日志 | 🟡 中 |

### 物理疲劳计算模型

```
Fatigue_L5 = clamp(
    0.3 × thermal_stress +           # 温度压力
    0.25 × disk_space_stress +       # 磁盘空间
    0.2 × disk_health_stress +       # 磁盘老化
    0.15 × throttle_penalty +        # 降频惩罚
    0.1 × swap_stress                # Swap 代偿
)
```

**可行性：60%**。温度和风扇在 Windows 上**不是完全不可获取**，只是需要额外工具：
- `wmi` 模块可以读取 `MSAcpi_ThermalZoneTemperature`（需管理员权限）
- 如果装了 OpenHardwareMonitor，可通过它的 WMI 接口读取
- NVIDIA GPU 可通过 `nvidia-smi` 命令行获取
- 磁盘 SMART 可通过 `smartctl`（smartmontools）获取

**最大障碍：** 跨平台一致性差，不同硬件厂商的接口不同。建议做可插拔设计——有数据就用，没数据就跳过。

---

## 全景汇总

### 指标覆盖度

| 层 | 情绪 | 已有 | 缺失 | 覆盖度 | 可行性 |
|----|------|------|------|--------|--------|
| L1 计算记忆 | Fatigue | 10 | 4 | **85%** | 95% |
| L2 吞吐排队 | Stress | 7 | 6 | **54%** | 70% |
| L3 传导IO | Stress+Flow | 16 | 5 | **76%** | 75% |
| L4 业务表现 | Flow/Confusion | 3 | 10 | **23%** | 40% |
| L5 物理硬件 | Fatigue(终极) | 4 | 9 | **31%** | 60% |

### 优先补齐清单

**P0（必须补，否则情绪模型核心缺陷）：**
1. L4: `http_5xx_rate` / `http_4xx_rate` — 没有业务错误，"困惑"情绪无法触发
2. L4: `response_p99_ms` — P50 掩盖了长尾，P99 才是真实痛苦
3. L2: `request_queue_depth` — 排队是"压力"的最直接信号

**P1（重要，提升情绪精度）：**
4. L5: `cpu_temp` + `cpu_throttle` — 温度是物理疲劳的核心信号
5. L3: `disk_io_latency_ms` — IO 延迟是"卡顿"的直接原因
6. L3: `disk_queue_depth` — 磁盘排队是 IO 层压力源

**P2（锦上添花）：**
7. L1: `cpu_freq_ratio` — 降频感知
8. L2: `thread_pool_active` — 线程池利用率
9. L5: `disk_health` — 磁盘老化
10. L5: `gpu_temp` / `gpu_usage` — GPU 加速场景

### 五层 → 7 维情感映射

```
L1 Fatigue ──────────→ F (疲劳) + D↓ (侵蚀控制感)
L2 Stress ───────────→ T (紧绷) + A↑ (唤醒) 
L3 Stress/Flow ──────→ T↑ 或 Flow→P↑+D↑
L4 Flow/Confusion ───→ P↑+D↑ 或 P↓+A↑+D↓
L5 Fatigue(终极) ────→ F↑↑ (不可逆) + C↓ (舒适崩塌)

全部汇聚到 ODE 动力系统 → 7 维情感状态
```

---

## 结论

**方向：✅ 完全正确。** 五层架构比当前 V5 的扁平指标堆砌有本质提升：
1. 每个情绪维度有明确的物理溯源（不是拍脑袋加权）
2. 故障定位时可以直接说"是哪一层出了问题"
3. 符合 AIOps 全栈监控的真实拓扑

**可实现性：综合 75%。** L1/L3 基本就绪，L2/L5 需要少量补充，**L4 是最大短板**——需要接入真实业务数据。

**建议落地顺序：** L1 → L3 → L2 → L5 → L4（从最容易到最难）
