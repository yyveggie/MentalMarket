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

// RSI 属于信号而非价格变动：超买/超卖统一用琥珀色并加文字标签，不占用涨跌色
function rsiClass(rsi: number | null): string {
  if (rsi == null) return ''
  if (rsi > 70 || rsi < 30) return 'signal'
  return ''
}

function rsiLabel(rsi: number | null): string {
  if (rsi == null) return ''
  if (rsi > 70) return '超买'
  if (rsi < 30) return '超卖'
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
            <th title="5 日简单移动平均">SMA5</th>
            <th title="20 日简单移动平均">SMA20</th>
            <th title="5 日指数移动平均">EMA5</th>
            <th title="20 日指数移动平均">EMA20</th>
            <th title="14 期相对强弱指标，>70 超买，<30 超卖">RSI14</th>
            <th title="10 期动量 = 现价 − 10 期前价格">MOM10</th>
            <th title="收益率标准差（非年化）">波动率</th>
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
            <td :class="rsiClass(r.rsi14)">{{ fmt(r.rsi14, 1) }}<small v-if="rsiLabel(r.rsi14)" class="rsi-tag">{{ rsiLabel(r.rsi14) }}</small></td>
            <td :class="momClass(r.momentum10)">{{ fmt(r.momentum10, 3) }}</td>
            <td>{{ r.volatility != null ? (r.volatility * 100).toFixed(3) + '%' : '-' }}</td>
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
  font-size: 12px;
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
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11px;
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

.signal {
  color: #d98c00;
  font-weight: 600;
}

.rsi-tag {
  margin-left: 4px;
  font-size: 9px;
  padding: 0 4px;
  border-radius: 2px;
  background: rgba(245, 166, 35, 0.15);
  color: #d98c00;
}
</style>
