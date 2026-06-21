"""分析 stress 采集数据"""
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

df = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v6_live_data_stress.csv'), encoding='utf-8-sig')

print('=' * 60)
print('V6.3 异常注入采集 — 最终数据报告')
print('=' * 60)
print(f'总步数: {len(df)}  场景: {df.scenario.nunique()}  情绪: {df.plutchik.nunique()}  象限: {df.quadrant.nunique()}')
print()

print('=== 情绪分布 ===')
print(df['plutchik'].value_counts().to_string())
print()

print('=== 情绪 x 场景 ===')
print(pd.crosstab(df['scenario'], df['plutchik']).to_string())
print()

print('=== 场景 PAD 均值 ===')
print(df.groupby('scenario')[['pad_p','pad_a','pad_d','fatigue','tension']].mean().round(3).to_string())
print()

print('=== 关键范围 ===')
for col in ['cpu_pct','fatigue','tension','comfort','pad_p','pad_a','pad_d','ode_p','ode_a','ode_d']:
    print(f'  {col}: [{df[col].min():+.3f}, {df[col].max():+.3f}]')