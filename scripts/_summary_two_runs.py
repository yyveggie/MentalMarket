#!/usr/bin/env python3
"""输出两个实验的平均指标。"""
import json

runs = {
    'tom07': 'output/拟合度报告_20260329_005147_tom07_tom12_tom21_预测拟合.json',
    'tom01': 'output/拟合度报告_20260329_150251_tom01_tom11_tom21_预测拟合.json',
}

data = {}
for name, path in runs.items():
    with open(path) as f:
        data[name] = json.load(f)['overall']

print(f"{'指标':<22s}  {'tom07':>8s}  {'tom01':>8s}  {'平均':>8s}")
print('-' * 54)
for key, label in [
    ('same_day_acc', '同日准确率 (%)'),
    ('forward1_acc', '前瞻1日准确率 (%)'),
    ('fit_pct', '拟合度 (Pearson×100)'),
    ('rmse', 'RMSE'),
    ('r_squared', 'R²'),
]:
    v07 = data['tom07'][key]
    v01 = data['tom01'][key]
    avg = (v07 + v01) / 2
    if key == 'rmse':
        print(f'{label:<22s}  {v07:8.4f}  {v01:8.4f}  {avg:8.4f}')
    elif key == 'r_squared':
        print(f'{label:<22s}  {v07:8.3f}  {v01:8.3f}  {avg:8.3f}')
    else:
        print(f'{label:<22s}  {v07:8.1f}  {v01:8.1f}  {avg:8.1f}')
