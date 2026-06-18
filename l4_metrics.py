"""
L4 业务表现层 — Prometheus 采集模块

用法（在你的 Python 服务里加 3 行）：
    from l4_metrics import L4Metrics
    l4 = L4Metrics()
    
    # 每个请求
    with l4.track("POST", "/chat"):
        response = handle_request()
    l4.record_error("timeout")  # 出错时

采集器侧：
    from l4_collector import L4Collector
    collector = L4Collector("http://localhost:8000")
    metrics = collector.scrape()  # 拿到所有 L4 指标
"""
from dataclasses import dataclass


@dataclass
class L4MetricsSnapshot:
    """L4 业务指标快照"""
    # 请求计数
    total_requests: float = 0.0
    success_count: float = 0.0
    error_5xx: float = 0.0
    error_4xx: float = 0.0

    # 延迟分位数（秒）
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_avg: float = 0.0

    # 吞吐
    requests_per_second: float = 0.0

    # 错误率
    error_rate: float = 0.0          # 总错误率 (%)
    http_5xx_rate: float = 0.0       # 5xx 率 (%)
    http_4xx_rate: float = 0.0       # 4xx 率 (%)
    timeout_count: float = 0.0       # 超时次数
    timeout_rate: float = 0.0        # 超时率 (%)

    # 业务细分
    error_types: dict[str, float] = None  # 错误类型分布

    def __post_init__(self):
        if self.error_types is None:
            self.error_types = {}


class L4Metrics:
    """
    服务端埋点 — 用 prometheus_client 记录请求指标
    
    在你的服务里这样用：
        from l4_metrics import L4Metrics
        l4 = L4Metrics()  # 启动时初始化一次
        
        # 每个请求
        with l4.track("POST", "/chat"):
            response = handle_request()
        
        # 出错时
        l4.record_error("timeout")
    """
    
    def __init__(self, port: int = 8000):
        """
        参数：
            port: metrics 端口，None 则复用主服务端口
        """
        try:
            from prometheus_client import (
                Counter, Histogram, Gauge, Info,
                start_http_server, REGISTRY,
                CollectorRegistry, multiprocess, values,
            )
            import threading
        except ImportError:
            raise ImportError(
                "需要安装 prometheus_client: pip install prometheus_client"
            )

        # 请求计数
        self.request_count = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'path', 'status'],
        )
        
        # 请求延迟（直方图，自动计算分位数）
        self.request_latency = Histogram(
            'http_request_duration_seconds',
            'Request latency in seconds',
            ['method', 'path'],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        
        # 错误计数（按类型）
        self.error_count = Counter(
            'http_errors_total',
            'Total errors by type',
            ['type'],
        )
        
        # 超时计数
        self.timeout_count = Counter(
            'http_timeouts_total',
            'Total request timeouts',
        )
        
        # 当前活跃请求数
        self.active_requests = Gauge(
            'http_active_requests',
            'Currently active requests',
        )
        
        # 服务信息
        self.service_info = Info(
            'emotion_engine',
            'Emotion engine service info',
        )
        self.service_info.info({
            'version': 'v6',
            'component': 'llm-server',
        })

        self._port = port
        self._started = False
        self._lock = threading.Lock()

    def start_metrics_server(self, port: int | None = None):
        """启动独立的 metrics HTTP 端口"""
        from prometheus_client import start_http_server
        p = port or self._port
        with self._lock:
            if not self._started:
                start_http_server(p)
                self._started = True
                print(f"[L4] Prometheus metrics 已启动: http://localhost:{p}/metrics")

    def track(self, method: str = "GET", path: str = "/"):
        """
        上下文管理器：自动记录请求计数和延迟
        
        用法：
            with l4.track("POST", "/chat"):
                response = handle_request()
        """
        return _RequestTracker(self, method, path)

    def record_error(self, error_type: str = "unknown"):
        """记录一次错误"""
        self.error_count.labels(type=error_type).inc()

    def record_timeout(self):
        """记录一次超时"""
        self.timeout_count.inc()


class _RequestTracker:
    """请求追踪上下文管理器"""
    
    def __init__(self, l4: L4Metrics, method: str, path: str):
        self.l4 = l4
        self.method = method
        self.path = path
        self._status = "200"
    
    def __enter__(self):
        self.l4.active_requests.inc()
        self._timer = self.l4.request_latency.labels(
            method=self.method, path=self.path
        ).time()
        self._timer.__enter__()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._timer.__exit__(exc_type, exc_val, exc_tb)
        self.l4.active_requests.dec()
        
        if exc_type is not None:
            if exc_type is TimeoutError:
                self._status = "504"
                self.l4.record_timeout()
            else:
                self._status = "500"
                self.l4.record_error(exc_type.__name__)
        else:
            self._status = "200"
        
        self.l4.request_count.labels(
            method=self.method,
            path=self.path,
            status=self._status,
        ).inc()
        
        return False  # 不吞异常


class L4Collector:
    """
    采集器侧 — 从 Prometheus /metrics 端点拉取 L4 指标
    
    用法：
        collector = L4Collector("http://localhost:8000")
        snapshot = collector.scrape()
        print(snapshot.error_rate, snapshot.latency_p99)
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._prev_total = 0
        self._prev_time = 0
        self._prev_errors = 0
    
    def scrape(self) -> L4MetricsSnapshot:
        """拉取 /metrics 并解析为 L4 快照"""
        import time
        import urllib.request
        import urllib.error
        
        now = time.time()
        snapshot = L4MetricsSnapshot()
        
        try:
            url = f"{self.base_url}/metrics"
            req = urllib.request.Request(url, headers={'Accept': 'text/plain'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                raw = resp.read().decode('utf-8')
        except (urllib.error.URLError, TimeoutError, OSError):
            return snapshot  # 服务不可用，返回空快照
        
        # 解析 Prometheus 文本格式
        metrics = self._parse_text(raw)
        
        # 请求计数
        total = 0
        s5xx = 0
        s4xx = 0
        for key, value in metrics.items():
            if key.startswith('http_requests_total'):
                total += value
                if 'status="5' in key:
                    s5xx += value
                elif 'status="4' in key:
                    s4xx += value
        
        snapshot.total_requests = total
        snapshot.error_5xx = s5xx
        snapshot.error_4xx = s4xx
        snapshot.success_count = total - s5xx - s4xx
        
        # 错误率
        if total > 0:
            snapshot.error_rate = (s5xx + s4xx) / total * 100
            snapshot.http_5xx_rate = s5xx / total * 100
            snapshot.http_4xx_rate = s4xx / total * 100
        
        # 延迟（从 histogram 的 _sum 和 _count 推算平均值）
        lat_sum = 0.0
        lat_count = 0.0
        for key, value in metrics.items():
            if 'http_request_duration_seconds_sum' in key and '_bucket' not in key:
                lat_sum = value
            if 'http_request_duration_seconds_count' in key and '_bucket' not in key:
                lat_count = value
        if lat_count > 0:
            snapshot.latency_avg = lat_sum / lat_count
        
        # 分位数（从 bucket 推算近似值）
        buckets = {}
        for key, value in metrics.items():
            if 'http_request_duration_seconds_bucket' in key:
                le = self._extract_le(key)
                if le is not None:
                    buckets[le] = buckets.get(le, 0) + value
        
        if buckets and total > 0:
            sorted_buckets = sorted(buckets.items())
            snapshot.latency_p50 = self._percentile(sorted_buckets, 0.50)
            snapshot.latency_p95 = self._percentile(sorted_buckets, 0.95)
            snapshot.latency_p99 = self._percentile(sorted_buckets, 0.99)
        
        # 超时
        for key, value in metrics.items():
            if key.startswith('http_timeouts_total'):
                snapshot.timeout_count = value
                if total > 0:
                    snapshot.timeout_rate = value / total * 100
        
        # 吞吐（RPS）
        if self._prev_time > 0 and now > self._prev_time:
            dt = now - self._prev_time
            d_requests = total - self._prev_total
            snapshot.requests_per_second = max(0, d_requests / dt)
        
        self._prev_total = total
        self._prev_time = now
        
        # 错误类型分布
        for key, value in metrics.items():
            if key.startswith('http_errors_total'):
                etype = self._extract_label(key, 'type')
                if etype:
                    snapshot.error_types[etype] = value
        
        return snapshot
    
    def _parse_text(self, raw: str) -> dict[str, float]:
        """解析 Prometheus 文本格式"""
        metrics = {}
        for line in raw.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(' ', 1)
            if len(parts) == 2:
                try:
                    metrics[parts[0]] = float(parts[1])
                except ValueError:
                    pass
        return metrics
    
    def _extract_le(self, key: str) -> float | None:
        """从 bucket key 提取 le 值"""
        import re
        m = re.search(r'le="([^"]+)"', key)
        if m:
            val = m.group(1)
            if val == '+Inf':
                return float('inf')
            return float(val)
        return None
    
    def _extract_label(self, key: str, label: str) -> str | None:
        """从 metric key 提取指定 label 的值"""
        import re
        m = re.search(rf'{label}="([^"]+)"', key)
        return m.group(1) if m else None
    
    def _percentile(self, sorted_buckets: list, p: float) -> float:
        """从 histogram bucket 近似计算分位数"""
        total = sorted_buckets[-1][1] if sorted_buckets else 0
        if total == 0:
            return 0.0
        target = total * p
        prev_count = 0
        prev_bound = 0
        for bound, count in sorted_buckets:
            if count >= target:
                if count == prev_count:
                    return bound
                ratio = (target - prev_count) / (count - prev_count)
                return prev_bound + ratio * (bound - prev_bound)
            prev_count = count
            prev_bound = bound
        return sorted_buckets[-1][0] if sorted_buckets else 0.0
