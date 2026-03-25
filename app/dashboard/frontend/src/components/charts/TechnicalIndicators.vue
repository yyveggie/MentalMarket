<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt } from '@/utils/formatters'

const store = useMarketStore()

const rows = computed(() => {
  return Object.entries(store.technicalIndicators)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([symbol, ind]) => ({
      symbol,
      lastPrice: ind.last_price,
      sma5: ind.sma_5,
      sma20: ind.sma_20,
      ema5: ind.ema_5,
      ema20: ind.ema_20,
      rsi14: ind.rsi_14,
      momentum10: ind.momentum_10,
      volatility: ind.volatility,
      samples: ind.samples,
    }))
})

function rsiClass(rsi: number | null): string {
  if (rsi == null) return ''
  if (rsi > 70) return 'color-down'
  if (rsi < 30) return 'color-up'
  return ''
}

function momClass(mom: number | null): string {
  if (mom == null) return ''
  if (mom > 0) return 'color-up'
  if (mom < 0) return 'color-down'
  return ''
}
</script>

<template>
  <div class="card">
    <div class="card-title">技术指标</div>
    <div class="ind-scroll">
      <table class="ind-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>最新价</th>
            <th>SMA5</th>
            <th>SMA20</th>
            <th>EMA5</th>
            <th>EMA20</th>
            <th>RSI14</th>
            <th>MOM10</th>
            <th>VOL</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.symbol">
            <td class="sym-cell">{{ r.symbol }}</td>
            <td>{{ fmt(r.lastPrice) }}</td>
            <td>{{ fmt(r.sma5) }}</td>
            <td>{{ fmt(r.sma20) }}</td>
            <td>{{ fmt(r.ema5) }}</td>
            <td>{{ fmt(r.ema20) }}</td>
            <td :class="rsiClass(r.rsi14)">{{ fmt(r.rsi14, 1) }}</td>
            <td :class="momClass(r.momentum10)">{{ fmt(r.momentum10) }}</td>
            <td>{{ fmt(r.volatility) }}</td>
          </tr>
          <tr v-if="rows.length === 0">
            <td colspan="9"></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.ind-scroll {
  overflow-x: auto;
}

.ind-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: var(--font-mono);
}

.ind-table th,
.ind-table td {
  padding: 5px 6px;
  text-align: right;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
}

.ind-table th:first-child,
.ind-table td:first-child {
  text-align: left;
}

.ind-table th {
  background: var(--surface-1);
  color: var(--accent);
  font-weight: 600;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  position: sticky;
  top: 0;
  z-index: 1;
}

.ind-table tr:nth-child(even) td {
  background: rgba(255, 255, 255, 0.015);
}

.ind-table tr:hover td {
  background: rgba(41, 98, 255, 0.03);
}

.sym-cell {
  font-weight: 600;
  color: var(--heading);
}
</style>
