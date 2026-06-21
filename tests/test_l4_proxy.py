"""L4 代理端到端验证"""
import sys, threading, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http.server import HTTPServer, BaseHTTPRequestHandler
import random

# 1. 模拟 llama-server
class MockLlama(BaseHTTPRequestHandler):
    def do_POST(self):
        time.sleep(random.uniform(0.01, 0.05))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"response":"hello"}')
    def log_message(self, *a): pass

t1 = threading.Thread(target=lambda: HTTPServer(('127.0.0.1', 18080), MockLlama).serve_forever(), daemon=True)
t1.start()

# 2. L4 代理
from l4_proxy import ProxyHandler
from http.server import HTTPServer as PHTTPServer
ProxyHandler.target = 'http://127.0.0.1:18080'
t2 = threading.Thread(target=lambda: PHTTPServer(('127.0.0.1', 18001), ProxyHandler).serve_forever(), daemon=True)
t2.start()

time.sleep(1)

# 3. 通过代理发请求
print('--- 10 requests through proxy ---')
for i in range(10):
    req = urllib.request.Request(
        'http://127.0.0.1:18001/v1/chat',
        method='POST',
        data=b'{"prompt":"hi"}',
        headers={'Content-Type': 'application/json'},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    print(f'  [{i}] status={resp.status}')

time.sleep(0.5)

# 4. 采集 L4
from l4_metrics import L4Collector
c = L4Collector('http://127.0.0.1:18001')
snap = c.scrape()
print()
print('--- L4 result ---')
print(f'total:      {snap.total_requests}')
print(f'error_rate: {snap.error_rate:.1f}%')
print(f'p50:        {snap.latency_p50*1000:.0f}ms')
print(f'p99:        {snap.latency_p99*1000:.0f}ms')
print(f'avg:        {snap.latency_avg*1000:.0f}ms')

# 5. 接入采集器
from real_collector import RealMetricCollector
from body_sense import BodySenseManager
collector = RealMetricCollector(interval=0.5, l4_url='http://127.0.0.1:18001')
r, d = collector.collect_once()
mgr = BodySenseManager()
body = mgr.update(
    load_signal=r.cpu_percent / 100.0,
    cpu_overwork=d.cpu_overwork,
    disk_io_latency_ms=d.disk_io_latency_ms,
    disk_usage=r.disk_usage_c,
    swap_percent=r.swap_percent,
    mem_available_gb=r.mem_available_gb,
)
print()
print('--- body sense (with L4) ---')
print(f'fatigue:    {body.fatigue:.3f}')
print(f'tension:    {body.tension:.3f}')
print(f'comfort:    {body.comfort:.2f}')
if r.error_rate is not None:
    print(f'L4 error:   {r.error_rate:.1f}%')
    print(f'L4 p99:     {r.response_p99_ms:.0f}ms')
else:
    print('L4:         no data (expected on 2nd collect)')

import os; os._exit(0)
