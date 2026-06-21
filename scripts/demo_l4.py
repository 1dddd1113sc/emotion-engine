"""
L4 端到端验证 — 模拟服务 + 采集器

1. 启动一个模拟 HTTP 服务（带 Prometheus 埋点）
2. 采集器从 /metrics 拉取 L4 数据
3. 送入体感系统

运行：python demo_l4.py
"""
import os
import sys, io, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def start_mock_service(port=9100):
    """模拟一个带 Prometheus 埋点的 HTTP 服务"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from l4_metrics import L4Metrics
    import random

    l4 = L4Metrics(port=port)
    l4.start_metrics_server(port=port)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            with l4.track("POST", self.path):
                # 模拟不同延迟和错误
                delay = random.expovariate(1.0 / 0.05)  # 平均 50ms
                time.sleep(min(delay, 0.5))

                if random.random() < 0.05:  # 5% 5xx
                    l4.record_error("internal_error")
                    raise Exception("模拟内部错误")

                if random.random() < 0.02:  # 2% 超时
                    l4.record_timeout()
                    raise TimeoutError("模拟超时")

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        def do_GET(self):
            if self.path == '/metrics':
                # Prometheus 采集端点 — 由 prometheus_client 自动处理
                pass
            else:
                with l4.track("GET", self.path):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'ok')

        def log_message(self, format, *args):
            pass  # 静默日志

    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"[Demo] 模拟服务启动: http://localhost:{port}")
    print(f"[Demo] Prometheus metrics: http://localhost:{port}/metrics")
    server.serve_forever()


def run_collector():
    """采集器侧 — 从 Prometheus 拉取 L4 数据"""
    from real_collector import RealMetricCollector, format_metrics
    from body_sense import BodySenseManager

    print("\n[Demo] 等待服务启动...")
    time.sleep(2)

    # 带 L4 URL 初始化采集器
    c = RealMetricCollector(interval=1.0, l4_url="http://localhost:9100")
    mgr = BodySenseManager()

    print("[Demo] 开始采集（按 Ctrl+C 停止）\n")

    count = 0
    try:
        for i in range(30):
            r, d = c.collect_once()
            count += 1

            # 体感集成（含 L4）
            body = mgr.update(
                load_signal=r.cpu_percent / 100.0,
                cpu_overwork=d.cpu_overwork,
                freq_throttle=d.freq_throttle,
                ctx_switches_rate=d.ctx_switches_rate,
                listen_backlog=d.listen_backlog,
                close_wait_ratio=d.close_wait_ratio,
                disk_io_latency_ms=d.disk_io_latency_ms,
                disk_queue_depth=r.disk_queue_depth,
                thermal_stress=d.thermal_stress,
                disk_usage=r.disk_usage_c,
                swap_percent=r.swap_percent,
                mem_available_gb=r.mem_available_gb,
            )

            # L4 状态
            l4_status = "N/A"
            if r.error_rate is not None:
                l4_status = (f"err={r.error_rate:.1f}% "
                            f"5xx={r.http_5xx_rate:.1f}% "
                            f"p99={r.response_p99_ms:.0f}ms "
                            f"rps={r.throughput_rps:.1f}")

            print(f"[{count:03d}] {format_metrics(r, d)}")
            print(f"      L4: {l4_status}")
            print(f"      体感: 疲劳={body.fatigue:.3f} 紧绷={body.tension:.3f} "
                  f"舒适={body.comfort:.2f} 耗竭={body.exhaustion_risk:.3f}")
            print()

            time.sleep(1)

    except KeyboardInterrupt:
        pass

    print(f"\n[Demo] 采集结束，共 {count} 次")


def generate_traffic(port=9100, duration=35):
    """模拟请求流量"""
    import urllib.request
    import random

    time.sleep(3)  # 等服务启动
    print(f"[Demo] 开始模拟流量 ({duration}s)...")

    end = time.time() + duration
    count = 0
    while time.time() < end:
        try:
            req = urllib.request.Request(
                f"http://localhost:{port}/chat",
                method='POST',
                data=b'{"prompt":"hello"}',
                headers={'Content-Type': 'application/json'},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        count += 1
        time.sleep(random.uniform(0.05, 0.2))  # 5-20 RPS

    print(f"[Demo] 流量结束，发送 {count} 请求")


if __name__ == "__main__":
    print("=" * 60)
    print("  L4 Prometheus 端到端验证")
    print("=" * 60)
    print()
    print("  3 个线程：")
    print("  1. 模拟服务（带 Prometheus 埋点）")
    print("  2. 采集器（拉取 /metrics → 体感系统）")
    print("  3. 流量生成器（模拟请求）")
    print()

    # 启动服务（后台线程）
    t_server = threading.Thread(target=start_mock_service, daemon=True)
    t_server.start()

    # 启动流量（后台线程）
    t_traffic = threading.Thread(target=generate_traffic, daemon=True)
    t_traffic.start()

    # 采集器在主线程
    run_collector()
