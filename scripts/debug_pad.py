"""调试特定用例的PAD计算"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pad_model import PADState
from ode_dynamics import ODEDynamics, ODEConfig, compute_target

# Test cases that should NOT be alert
test_cases = [
    {"id": "T0019", "cpu": 95.0, "mem": 68.5, "err": 0.15, "lat": 57.0, "expect": "高能良好"},
    {"id": "T0025", "cpu": 51.9, "mem": 43.0, "err": 0.13, "lat": 109.0, "expect": "稳态良好"},
    {"id": "T0069", "cpu": 79.5, "mem": 66.0, "err": 1.99, "lat": 199.0, "expect": "高能良好"},
    {"id": "N_case", "cpu": 38.4, "mem": 47.2, "err": 1.61, "lat": 147.0, "expect": "稳态良好"},
]

for tc in test_cases:
    ode = ODEDynamics(ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0))
    for i in range(20):
        target = compute_target(tc["cpu"], tc["mem"], tc["err"], tc["lat"])
        emo = ode.step(target)
    
    pad = PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()
    print(f"{tc['id']}: CPU={tc['cpu']} ERR={tc['err']} LAT={tc['lat']}")
    print(f"  P={emo.p:.3f} A={emo.a:.3f} D={emo.d:.3f}")
    print(f"  Quadrant: {pad.quadrant.value} (expect: {tc['expect']})")
    print(f"  raw_quadrant: {pad.raw_quadrant}")
    print()
