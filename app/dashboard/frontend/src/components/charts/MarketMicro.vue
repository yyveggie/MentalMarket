<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtPct, pnlClass } from '@/utils/formatters'

const store = useMarketStore()

const rows = computed(() => {
  return Object.entries(store.marketMicro)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([symbol, m]) => ({
      symbol,
      volume: m.volume,
      buyVol: m.buy_volume,
      sellVol: m.sell_volume,
      bsRatio: m.buy_sell_ratio,
      turnover: m.turnover_rate,
      vwap: m.vwap,
      volatility: m.volatility,
      spread: m.spread,
      tradeCount: m.trade_count,
    }))
})
</script>

<template>
  <div class="card">
    <div class="card-title">市场微观结构</div>
    <div class="micro-scroll">
      <table class="micro-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>成交量</th>
            <th>买量</th>
            <th>卖量</th>
            <th>买卖比</th>
            <th>换手率</th>
            <th>VWAP</th>
            <th>波动率</th>
            <th>价差</th>
            <th>笔数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.symbol">
            <td class="sym-cell">{{ r.symbol }}</td>
            <td>{{ r.volume }}</td>
            <td class="color-up">{{ r.buyVol }}</td>
            <td class="color-down">{{ r.sellVol }}</td>
            <td
              :class="{
                'color-up': r.bsRatio > 1.2,
                'color-down': r.bsRatio < 0.8,
              }"
              style="font-weight: 600"
            >
              {{ r.bsRatio?.toFixed(2) ?? '-' }}
            </td>
            <td>{{ r.turnover != null ? (r.turnover * 100).toFixed(2) + '%' : '-' }}</td>
            <td>{{ r.vwap?.toFixed(2) ?? '-' }}</td>
            <td>{{ r.volatility != null ? (r.volatility * 100).toFixed(2) + '%' : '-' }}</td>
            <td>{{ r.spread?.toFixed(2) ?? '-' }}</td>
            <td>{{ r.tradeCount }}</td>
          </tr>
          <tr v-if="rows.length === 0">
            <td colspan="10"></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.micro-scroll {
  overflow-x: auto;
}

.micro-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: var(--font-mono);
}

.micro-table th,
.micro-table td {
  padding: 5px 6px;
  text-align: right;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
}

.micro-table th:first-child,
.micro-table td:first-child {
  text-align: left;
}

.micro-table th {
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

.micro-table tr:nth-child(even) td {
  background: rgba(255, 255, 255, 0.015);
}

.micro-table tr:hover td {
  background: rgba(41, 98, 255, 0.03);
}

.sym-cell {
  font-weight: 600;
  color: var(--heading);
}
</style>
