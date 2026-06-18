"""
L4 代理 — 在任意 HTTP 服务前加 Prometheus 埋点

零侵入：不改目标服务代码，不改客户端代码
用法：
  python l4_proxy.py --target http://127.0.0.1:8080 --port 8001

之后客户端访问 http://localhost:8001 代替原来的地址
Prometheus metrics 自动暴露在 http://localhost:8001/metrics
"""
import argparse
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST,
)

# === Prometheus 指标 ===
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total requests',
    ['method', 'path', 'status'],
)
REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'Request latency',
    ['method', 'path'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
ACTIVE_REQUESTS = Gauge(
    'http_active_requests',
    'Currently active requests',
)
REQUEST_BODY_SIZE = Histogram(
    'http_request_body_bytes',
    'Request body size',
    buckets=[100, 1000, 10000, 100000, 1000000],
)
RESPONSE_BODY_SIZE = Histogram(
    'http_response_body_bytes',
    'Response body size',
    buckets=[100, 1000, 10000, 100000, 1000000, 10000000],
)


class ProxyHandler(BaseHTTPRequestHandler):
    """反向代理 + Prometheus 埋点"""

    target: str = ""  # 类变量，由 main() 设置

    def do_GET(self):
        if self.path == '/metrics':
            self._serve_metrics()
        else:
            self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")

    def do_DELETE(self):
        self._proxy("DELETE")

    def _serve_metrics(self):
        """暴露 Prometheus metrics"""
        data = generate_latest()
        self.send_response(200)
        self.send_header('Content-Type', CONTENT_TYPE_LATEST)
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, method: str):
        """转发请求到目标服务，同时记录指标"""
        ACTIVE_REQUESTS.inc()
        start = time.time()
        status_code = "502"
        path_label = self.path.split('?')[0]  # 去掉 query string

        try:
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None
            REQUEST_BODY_SIZE.observe(content_length)

            # 构造转发请求
            target_url = f"{self.target}{self.path}"
            req = urllib.request.Request(
                target_url,
                data=body,
                method=method,
                headers={k: v for k, v in self.headers.items()
                         if k.lower() not in ('host',)},
            )

            # 转发
            with urllib.request.urlopen(req, timeout=120) as resp:
                status_code = str(resp.status)
                response_body = resp.read()

                # 发送响应
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(response_body)
                RESPONSE_BODY_SIZE.observe(len(response_body))

        except urllib.error.HTTPError as e:
            status_code = str(e.code)
            response_body = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response_body)
            RESPONSE_BODY_SIZE.observe(len(response_body))

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            status_code = "502"
            error_msg = f'{{"error":"proxy error: {e}"}}'
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(error_msg.encode())

        except Exception as e:
            status_code = "500"
            error_msg = f'{{"error":"{e}"}}'
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(error_msg.encode())

        finally:
            elapsed = time.time() - start
            REQUEST_COUNT.labels(method=method, path=path_label, status=status_code).inc()
            REQUEST_LATENCY.labels(method=method, path=path_label).observe(elapsed)
            ACTIVE_REQUESTS.dec()

            # 控制台日志
            elapsed_ms = elapsed * 1000
            tag = "[OK]" if status_code.startswith("2") else "[ERR]"
            print(f"  {tag} {method} {self.path} -> {status_code} ({elapsed_ms:.0f}ms)",
                  flush=True)

    def log_message(self, format, *args):
        pass  # 静默默认日志，用自己的格式


def main():
    parser = argparse.ArgumentParser(description="L4 Prometheus 代理")
    parser.add_argument("--target", "-t", required=True,
                        help="目标服务地址，如 http://127.0.0.1:8080")
    parser.add_argument("--port", "-p", type=int, default=8001,
                        help="代理监听端口 (默认 8001)")
    parser.add_argument("--host", "-a", default="127.0.0.1",
                        help="绑定地址 (默认 127.0.0.1)")
    args = parser.parse_args()

    ProxyHandler.target = args.target.rstrip("/")

    server = HTTPServer((args.host, args.port), ProxyHandler)

    print(f"L4 Prometheus Proxy")
    print(f"  Proxy:   http://{args.host}:{args.port}")
    print(f"  Target:  {args.target}")
    print(f"  Metrics: http://{args.host}:{args.port}/metrics")
    print()
    print(f"  Client -> http://{args.host}:{args.port} (instead of {args.target})")
    print(f"  Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n代理已停止")
        server.server_close()


if __name__ == "__main__":
    main()
