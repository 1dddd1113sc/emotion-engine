"""调试: compute_target 输出 vs ODE 收敛"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from ode_dynamics import compute_target, ODEDynamics, ODEConfig
from pad_model import PADState

cases = [
    {"id": "T0019", "cpu": 95.0, "mem": 68.5, "err": 0.15, "lat": 57.0},
    {"id": "T0025", "cpu": 51.9, "mem": 43.0, "err": 0.13, "lat": 109.0},
    {"id": "T0069", "cpu": 79.5, "mem": 66.0, "err": 1.99, "lat": 199.0},
    {"id": "N_case", "cpu": 38.4, "mem": 47.2, "err": 1.61, "lat": 147.0},
]

for tc in cases:
    target = compute_target(tc["cpu"], tc["mem"], tc["err"], tc["lat"])
    print(f"{tc['id']}: CPU={tc['cpu']} ERR={tc['err']} LAT={tc['lat']}")
    print(f"  TARGET: P={target.p:.3f} A={target.a:.3f} D={target.d:.3f}")
    
    # ODE 收敛
    ode = ODEDynamics(ODEConfig(tau_p=60, tau_a=25, tau_d=40, noise_scale=0.008, dt=1.0))
    for i in range(20):
        emo = ode.step(target)
    pad = PADState(p=emo.p, a=emo.a, d=emo.d, volatility=emo.v).clamp()
    print(f"  ODE(20): P={emo.p:.3f} A={emo.a:.3f} D={emo.d:.3f} → {pad.quadrant.value}")
    print()
