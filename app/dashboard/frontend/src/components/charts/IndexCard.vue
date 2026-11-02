<script setup lang="ts">
import { fmt } from '@/utils/formatters'
import type { IndexCardData } from './indexOverviewTypes'

const props = defineProps<{
  idx: IndexCardData
  selected: boolean
}>()

const emit = defineEmits<{
  (e: 'select', symbol: string): void
}>()

function sparklinePoints(prices: Array<number | null>, min: number, max: number): string {
  const points: string[] = []
  const validCount = prices.filter((v): v is number => v !== null).length
  if (validCount < 2) return ''
  const range = max - min
  const isFlat = Math.abs(range) < 1e-12
  for (let i = 0; i < prices.length; i++) {
    const p = prices[i]
    if (p === null) continue
    const x = (i / Math.max(1, prices.length - 1)) * 80
    const y = isFlat ? 11 : 20 - ((p - min) / range) * 18
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return points.join(' ')
}

function compactDateLabel(dateStr: string | null | undefined): string {
  if (!dateStr) return '--'
  const s = String(dateStr)
  if (s.startsWith('Day ')) return s
  return s.length >= 10 ? s.slice(5, 10) : s
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('select', props.idx.symbol)
  }
}

function pctText(v: number | null): string {
  return v == null ? '-' : `${v.toFixed(1)}%`
}
</script>

<template>
  <div
    class="idx-card"
    :class="[idx.pctChg > 0 ? 'idx-up' : idx.pctChg < 0 ? 'idx-down' : '', { 'idx-selected': selected }]"
    role="button"
    tabindex="0"
    @click="emit('select', idx.symbol)"
    @keydown="onKeydown"
  >
    <div class="idx-row-top">
      <span class="idx-sym">{{ idx.symbol }}</span>
      <span class="idx-price">{{ fmt(idx.price, 2) }}</span>
      <span class="idx-chg">
        {{ idx.pctChg > 0 ? '▲' : idx.pctChg < 0 ? '▼' : '─' }}
        {{ idx.pctChg > 0 ? '+' : '' }}{{ idx.pctChg.toFixed(2) }}%
      </span>
    </div>
    <div class="sparkline-wrap">
      <svg
        v-if="idx.normRealSparkline.length > 1 || idx.simSparklineRaw.length > 1"
        class="sparkline"
        viewBox="0 0 80 24"
        preserveAspectRatio="none"
      >
        <polyline
          v-if="idx.normRealSparkline.length > 1"
          :points="sparklinePoints(idx.normRealSparkline, idx.normLow, idx.normHigh)"
          fill="none"
          stroke="#64748b"
          stroke-width="1.2"
          stroke-opacity="0.95"
        />
        <polyline
          :points="sparklinePoints(idx.normSimSparkline, idx.normLow, idx.normHigh)"
          fill="none"
          :stroke="idx.normRealSparkline.length > 1 ? '#ef5350' : (idx.pctChg >= 0 ? '#ef5350' : '#26a69a')"
          stroke-width="1.5"
        />
      </svg>
    </div>
    <div class="sparkline-meta">
      <div class="idx-metrics">
        <span title="同日方向准确率">同日 {{ pctText(idx.predictionSameDayAccuracyPct) }}</span>
        <span title="前瞻 1 日方向准确率">前瞻 {{ pctText(idx.predictionForward1AccuracyPct) }}</span>
        <span title="波动拟合度（收益相关性映射到 0~100%）">拟合 {{ pctText(idx.volatilityFitPct) }}</span>
      </div>
      <div class="idx-metrics-sub">
        <span title="QLIKE 波动损失（越小越好）">QLIKE {{ idx.qlike == null ? '-' : idx.qlike.toFixed(3) }}</span>
        <span title="对数方差 RMSE（越小越好）">Log-RMSE {{ idx.logRmse == null ? '-' : idx.logRmse.toFixed(3) }}</span>
        <span title="Mincer-Zarnowitz 回归斜率（理想为 1）">MZ β {{ idx.mzBeta == null ? '-' : idx.mzBeta.toFixed(2) }}</span>
        <span title="Wald 检验 p 值">p值 {{ idx.mzPValue == null ? '-' : idx.mzPValue.toFixed(3) }}</span>
      </div>
      <div class="sparkline-dates">
        <span :title="idx.firstDate ?? ''">{{ compactDateLabel(idx.firstDate) }}</span>
        <span>交易日日期</span>
        <span :title="idx.lastDate ?? ''">{{ compactDateLabel(idx.lastDate) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.idx-card {
  padding: 8px 9px;
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  background: var(--surface-1);
  cursor: pointer;
  border: 1px solid transparent;
  transition: transform 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
}

.idx-card:hover {
  transform: translateY(-1px);
  border-color: var(--border);
}

.idx-card:focus-visible {
  outline: none;
  border-color: var(--accent);
}

.idx-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent);
}

.idx-up { background: var(--up-soft); }
.idx-down { background: var(--down-soft); }

.idx-row-top {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 3px;
}

.idx-sym {
  font-size: 13px;
  font-weight: 700;
  color: var(--heading);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70px;
}

.idx-price {
  font-size: 20px;
  font-weight: 800;
  color: var(--heading);
}

.idx-chg {
  font-size: 11px;
  font-weight: 700;
  margin-left: auto;
}

.idx-up .idx-chg { color: var(--up); }
.idx-down .idx-chg { color: var(--down); }

.sparkline {
  width: 100%;
  height: 32px;
  margin: 2px 0 0;
}

.sparkline-wrap {
  margin-top: 1px;
  padding-bottom: 2px;
}

.sparkline-meta {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.idx-metrics,
.idx-metrics-sub {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  line-height: 1.2;
  font-size: 10px;
}

.idx-metrics { color: var(--text-muted); }
.idx-metrics-sub { color: var(--text-dim); margin-top: 2px; }

.sparkline-dates {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 3px;
  font-size: 10px;
  color: var(--text-dim);
}

.sparkline-dates span:nth-child(2) {
  opacity: 0.85;
}
</style>
