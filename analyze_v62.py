"""V6.2 管线数据分析"""
import os
import csv

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data_v62.csv')

with open(CSV, 'r', encoding='utf-8-sig') as f:
    all_rows = list(csv.reader(f))

# Skip header
rows = all_rows[1:] if all_rows[0][0] == 'time' else all_rows
print(f'Data rows: {len(rows)}')

# 37列: 0=time,1=step,2=cpu,3=mem,4=swap,5=io_lat,6=cw,7=threads,8=err,9=overwork,10=health,11=cpu_temp,12=gpu_temp,13=thermal,14=sig_err,15=sig_load,16=sig_lat,17=sig_health,18=sig_ctx,19=fatigue,20=tension,21=comfort,22=exhaustion,23=pad_p,24=pad_a,25=pad_d,26=pad_v,27=ode_p,28=ode_a,29=ode_d,30=ode_v,31=ode_f,32=ode_t,33=ode_c,34=plutchik,35=conf,36=quadrant

cpus = [float(r[2]) for r in rows]
mem_pcts = [float(r[3]) for r in rows]
overs = [float(r[9]) for r in rows]
healths = [float(r[10]) for r in rows]
cpu_temps = [float(r[11]) for r in rows]
gpu_temps = [float(r[12]) for r in rows]
fats = [float(r[19]) for r in rows]
tens = [float(r[20]) for r in rows]
comfs = [float(r[21]) for r in rows]
sig_loads = [float(r[15]) for r in rows]

n = len(cpus)

def stats(arr):
    m = sum(arr)/n
    return (min(arr), max(arr), m, (sum((x-m)**2 for x in arr)/n)**0.5)

def corr(x, y):
    mx, my = sum(x)/n, sum(y)/n
    cx = sum((x[i]-mx)*(y[i]-my) for i in range(n))/n
    sx = (sum((v-mx)**2 for v in x)/n)**0.5
    sy = (sum((v-my)**2 for v in y)/n)**0.5
    return cx/(sx*sy) if sx>0 and sy>0 else 0

print()
print('='*70)
print('  V6.2 新管线 - 60步完整统计（干净数据）')
print('='*70)
print(f'  {"指标":<16} {"Min":>8}  {"Max":>8}  {"Avg":>8}  {"Std":>8}  {"Range":>8}')
print(f'  {"-"*16} {"-"*8}  {"-"*8}  {"-"*8}  {"-"*8}  {"-"*8}')

for name, arr, fmt in [
    ('CPU %', cpus, 'f'), ('mem %', mem_pcts, 'f'),
    ('cpu_overwork', overs, 'd'), ('health_score', healths, 'd'),
    ('cpu_temp', cpu_temps, 'f'), ('gpu_temp', gpu_temps, 'f'),
    ('sig_load', sig_loads, 'd'), ('fatigue', fats, 'd'),
    ('tension', tens, 'd'), ('comfort', comfs, 'd'),
]:
    mi, ma, av, sd = stats(arr)
    if fmt == 'f':
        print(f'  {name:<16} {mi:8.1f}  {ma:8.1f}  {av:8.1f}  {sd:8.1f}  {ma-mi:8.1f}')
    else:
        print(f'  {name:<16} {mi:8.3f}  {ma:8.3f}  {av:8.3f}  {sd:8.3f}  {ma-mi:8.3f}')

print()
print(f'  CPU-Fatigue 相关:    {corr(cpus, fats):+.3f}')
print(f'  CPU-Comfort 相关:    {corr(cpus, comfs):+.3f}')
print(f'  Fatigue-Comfort 相关: {corr(fats, comfs):+.3f}')
print(f'  CPU-Tension 相关:    {corr(cpus, tens):+.3f}')