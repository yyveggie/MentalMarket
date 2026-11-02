<script setup lang="ts">
/** 流动性供给：各 ToM 阶层作为挂单方（Maker）与吃单方（Taker）的成交次数，以及 Maker 占比。 */
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'
import { fmtInt } from '@/utils/formatters'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const tip = '挂单 (Maker) = 提前挂在订单簿上、被动成交的一方，为市场提供流动性\n吃单 (Taker) = 主动发起成交的一方，消耗流动性\nMaker 占比 = 挂单 / (挂单 + 吃单)，越高说明该阶层越倾向于提供流动性'

interface Row {
  level: string
  label: string
  color: string
  maker: number
  taker: number
  makerRatio: number
  share: number
}

const rows = computed<Row[]>(() => {
  const defs = [
    { level: '0', label: 'ToM0', color: '#78909c' },
    { level: '1', label: 'ToM1', color: '#0288d1' },
    { level: '2', label: 'ToM2', color: '#7c4dff' },
  ]
  const grand = defs.reduce((s, d) => {
    const v = store.liquidityStats[d.level]
    return s + (v?.maker ?? 0) + (v?.taker ?? 0)
  }, 0)
  return defs.map((d) => {
    const v = store.liquidityStats[d.level] ?? { maker: 0, taker: 0 }
    const sum = v.maker + v.taker
    return {
      ...d,
      maker: v.maker,
      taker: v.taker,
      makerRatio: sum > 0 ? v.maker / sum : 0,
      share: grand > 0 ? sum / grand : 0,
    }
  })
})

const totals = computed(() => {
  const maker = rows.value.reduce((s, r) => s + r.maker, 0)
  const taker = rows.value.reduce((s, r) => s + r.taker, 0)
  return { maker, taker, ratio: maker + taker > 0 ? maker / (maker + taker) : 0 }
})
</script>

<template>
  <div class="card">
    <div class="card-title">流动性供给
      <span class="info-btn" @mouseenter="showTip('l')" @mouseleave="hideTip">i</span>
      <div v-if="activeTooltip === 'l'" class="custom-tooltip">{{ tip }}</div>
    </div>

    <div class="liq-summary">
      <div class="ls-item">
        <span class="ls-label">挂单成交</span>
        <span class="ls-value">{{ fmtInt(totals.maker) }}</span>
      </div>
      <div class="ls-item">
        <span class="ls-label">吃单成交</span>
        <span class="ls-value">{{ fmtInt(totals.taker) }}</span>
      </div>
      <div class="ls-item">
        <span class="ls-label">Maker 占比</span>
        <span class="ls-value">{{ (totals.ratio * 100).toFixed(1) }}<small>%</small></span>
      </div>
    </div>

    <div class="liq-table">
      <div class="lt-head">
        <span class="lt-label">阶层</span>
        <span class="lt-bar">挂单 / 吃单 构成</span>
        <span class="lt-num">挂单</span>
        <span class="lt-num">吃单</span>
        <span class="lt-num">Maker</span>
        <span class="lt-num">成交份额</span>
      </div>
      <div v-for="r in rows" :key="r.level" class="lt-row">
        <span class="lt-label" :style="{ color: r.color }">{{ r.label }}</span>
        <span class="lt-bar">
          <i class="stack">
            <b class="mk" :style="{ width: `${r.makerRatio * 100}%`, background: r.color }" />
            <b class="tk" :style="{ width: `${(1 - r.makerRatio) * 100}%`, background: r.color }" />
          </i>
        </span>
        <span class="lt-num">{{ fmtInt(r.maker) }}</span>
        <span class="lt-num">{{ fmtInt(r.taker) }}</span>
        <span class="lt-num">{{ (r.makerRatio * 100).toFixed(1) }}%</span>
        <span class="lt-num dim">{{ (r.share * 100).toFixed(1) }}%</span>
      </div>
    </div>
    <div class="liq-legend"><i class="sw solid" />挂单 (Maker)<i class="sw light" />吃单 (Taker)</div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';

.liq-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.ls-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  background: var(--surface-1);
  border-radius: 4px;
}

.ls-label {
  font-size: 10px;
  color: var(--text-muted);
}

.ls-value {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 700;
  color: var(--heading);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.ls-value small {
  font-size: 11px;
  font-weight: 500;
  margin-left: 1px;
}

.liq-table {
  display: flex;
  flex-direction: column;
  font-variant-numeric: tabular-nums;
}

.lt-head,
.lt-row {
  display: grid;
  grid-template-columns: 48px minmax(80px, 1.4fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border);
}

.lt-head {
  font-size: 10px;
  color: var(--text-dim);
  padding-top: 0;
}

.lt-row:last-child {
  border-bottom: none;
}

.lt-label {
  font-size: 12px;
  font-weight: 700;
}

.lt-num {
  text-align: right;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--heading);
}

.lt-num.dim {
  color: var(--text-muted);
  font-weight: 500;
}

.lt-head .lt-num {
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 400;
  color: var(--text-dim);
}

.stack {
  display: flex;
  width: 100%;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--surface-2);
}

.stack b {
  display: block;
  height: 100%;
  transition: width 0.3s ease;
}

.stack .mk {
  opacity: 0.85;
}

.stack .tk {
  opacity: 0.3;
}

.liq-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 10px;
  color: var(--text-dim);
}

.liq-legend .sw {
  display: inline-block;
  width: 14px;
  height: 6px;
  border-radius: 3px;
  background: var(--text-muted);
  margin-left: 10px;
}

.liq-legend .sw:first-child {
  margin-left: 0;
}

.liq-legend .sw.solid {
  opacity: 0.85;
}

.liq-legend .sw.light {
  opacity: 0.3;
}
</style>
