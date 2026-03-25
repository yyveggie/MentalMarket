"""生成论文级股票波动仿真图：上方股价带渐变色，下方成交量红绿柱。"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.collections import LineCollection
import datetime

np.random.seed(42)

# ======================== 仿真数据 ========================
n_days = 250
dates = []
d = datetime.date(2023, 1, 3)
while len(dates) < n_days:
    if d.weekday() < 5:
        dates.append(d)
    d += datetime.timedelta(days=1)

mu = 0.0002
sigma = 0.016
returns = np.random.normal(mu, sigma, n_days)

regime_switches = [0, 50, 100, 150, 200, n_days]
regime_drifts = [0.002, -0.0025, 0.0008, -0.0015, 0.0018]
for i, drift in enumerate(regime_drifts):
    start, end = regime_switches[i], regime_switches[i + 1]
    returns[start:end] += drift

price = np.zeros(n_days)
price[0] = 100.0
for i in range(1, n_days):
    price[i] = price[i - 1] * np.exp(returns[i])

price = np.maximum(price, 60)

base_vol = 1_200_000
volume = np.random.lognormal(mean=np.log(base_vol), sigma=0.35, size=n_days).astype(int)
vol_boost = 1.0 + 2.0 * np.clip(np.abs(returns) / sigma - 1.0, 0, 3)
volume = (volume * vol_boost).astype(int)
volume = np.clip(volume, 200_000, 8_000_000)

price_change = np.diff(price, prepend=price[0])

# ======================== 绘图 ========================
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(14, 6.5),
    gridspec_kw={"height_ratios": [3, 1], "hspace": 0.06},
    dpi=300,
)

fig.patch.set_alpha(0.0)
for ax in (ax1, ax2):
    ax.set_facecolor("none")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#666666", labelsize=8.5)

x = np.arange(n_days)

# 上方：价格曲线 + 渐变
cmap = mcolors.LinearSegmentedColormap.from_list(
    "price_grad", ["#3B82F6", "#8B5CF6", "#EC4899"],
)
norm = plt.Normalize(price.min(), price.max())
y_pad = (price.max() - price.min()) * 0.06

points = np.array([x, price]).T.reshape(-1, 1, 2)
segments = np.concatenate([points[:-1], points[1:]], axis=1)
lc = LineCollection(segments, cmap=cmap, norm=norm, linewidths=2.0, alpha=0.95, capstyle="round")
lc.set_array(price[:-1])
ax1.add_collection(lc)

n_bands = 100
p_min = price.min() - y_pad
p_range = price.max() - p_min
for i in range(n_bands):
    frac = i / n_bands
    upper = p_min + (price - p_min) * (1 - frac)
    lower = p_min + (price - p_min) * max(0, 1 - frac - 1.0 / n_bands)
    alpha = 0.18 * (1 - frac) ** 2.5
    color_val = norm(price.mean())
    ax1.fill_between(x, upper, lower, alpha=alpha, color=cmap(color_val), linewidth=0)

sma20 = np.convolve(price, np.ones(20) / 20, mode="valid")
sma_off = n_days - len(sma20)
ax1.plot(x[sma_off:], sma20, color="#94A3B8", linewidth=1.0, linestyle="--", alpha=0.65)

ax1.set_xlim(0, n_days - 1)
ax1.set_ylim(price.min() - y_pad, price.max() + y_pad)
ax1.set_ylabel("")
ax1.set_yticks([])

tick_positions = np.linspace(0, n_days - 1, 10, dtype=int)
ax1.set_xticks(tick_positions)
ax1.set_xticklabels([])

# 下方：成交量柱状图
colors_bar = np.where(price_change >= 0, "#22C55E", "#EF4444")
edge_bar = np.where(price_change >= 0, "#16A34A", "#DC2626")

ax2.bar(x, volume, width=0.7, color=colors_bar, edgecolor=edge_bar, linewidth=0.2, alpha=0.82)

vol_ma = np.convolve(volume, np.ones(10) / 10, mode="valid")
vol_off = n_days - len(vol_ma)
ax2.plot(x[vol_off:], vol_ma, color="#F59E0B", linewidth=1.3, alpha=0.85)

ax2.set_xlim(0, n_days - 1)
ax2.set_ylim(0, volume.max() * 1.12)
ax2.set_ylabel("")
ax2.set_yticks([])

ax2.set_xticks([])
ax2.set_xticklabels([])


output_path = "/Users/mushroom/Desktop/MentalMarket/stock_simulation_chart.png"
fig.savefig(output_path, format="png", bbox_inches="tight", pad_inches=0.15, transparent=True)
plt.close(fig)
print(f"Chart saved to {output_path}")
