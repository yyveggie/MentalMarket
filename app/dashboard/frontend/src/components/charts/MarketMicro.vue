<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmtCn } from '@/utils/formatters'

const store = useMarketStore()

// 后端口径：volume/buy/sell 为最近 200 笔成交的股数；换手率 = 该成交量 / 全体 Agent 持股；
// 波动率 = 最近 200 笔逐笔收益率的标准差；价差 = 卖一 − 买一
const rows = computed(() => {
  return Object.entries(store.marketMicro)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([symbol, m]) => {
      const buy = m.buy_volume ?? 0
      const sell = m.sell_volume ?? 0
      const total = buy + sell
      const imbalance = total > 0 ? (buy - sell) / total : null
      const spreadBps = m.spread != null && m.vwap ? (m.spread / m.vwap) * 10000 : null
      return {
        symbol,
        volume: m.volume,
        buyVol: buy,
        sellVol: sell,
        buyPct: total > 0 ? (buy / total) * 100 : 50,
        imbalance,
        turnover: m.turnover_rate,
        vwap: m.vwap,
        volatility: m.volatility,
        spread: m.spread,
        spreadBps,
        tradeCount: m.trade_count,
      }
    })
})

function imbClass(v: number | null): string {
  if (v == null) return ''
  if (v > 0.15) return 'color-up'
  if (v < -0.15) return 'color-down'
  return ''
}

function pctSigned(v: number | null): string {
  if (v == null) return '-'
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(0)}%`
}
</script>

<template>
  <div class="card">
    <div class="card-title">市场微观结构 <small class="scope">口径：每标的最近 200 笔成交</small></div>
    <div class="micro-scroll">
      <table class="micro-table">
        <thead>
          <tr>
            <th>代码</th>
            <th title="最近 200 笔成交的股数合计">成交量(股)</th>
            <th title="主动买入（吃卖单）的股数">主买(股)</th>
            <th title="主动卖出（吃买单）的股数">主卖(股)</th>
            <th title="失衡度 = (主买 − 主卖) / (主买 + 主卖)，正值为买方主导">买卖失衡度</th>
            <th title="最近 200 笔成交量 / 全体 Agent 持股数">换手率</th>
            <th title="成交量加权平均价">VWAP</th>
            <th title="最近 200 笔逐笔收益率的标准差（非年化）">逐笔波动率</th>
            <th title="卖一 − 买一，括号内为相对 VWAP 的基点">价差</th>
            <th title="最近成交笔数（上限 200）">笔数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.symbol">
            <td class="sym-cell">{{ r.symbol }}</td>
            <td>{{ fmtCn(r.volume, 2) }}</td>
            <td class="color-up">{{ fmtCn(r.buyVol, 2) }}</td>
            <td class="color-down">{{ fmtCn(r.sellVol, 2) }}</td>
            <td class="imb-cell">
              <div class="imb-wrap">
                <div class="imb-bar" :title="`主买 ${r.buyPct.toFixed(0)}% / 主卖 ${(100 - r.buyPct).toFixed(0)}%`">
                  <i class="imb-buy" :style="{ width: `${r.buyPct}%` }" />
                  <i class="imb-sell" />
                </div>
                <span class="imb-val" :class="imbClass(r.imbalance)">{{ pctSigned(r.imbalance) }}</span>
              </div>
            </td>
            <td>{{ r.turnover != null ? (r.turnover * 100).toFixed(2) + '%' : '-' }}</td>
            <td>{{ r.vwap?.toFixed(2) ?? '-' }}</td>
            <td>{{ r.volatility != null ? (r.volatility * 100).toFixed(3) + '%' : '-' }}</td>
            <td>
              <template v-if="r.spread != null">
                {{ r.spread.toFixed(2) }}<small v-if="r.spreadBps != null" class="dim"> ({{ r.spreadBps.toFixed(1) }}bp)</small>
              </template>
              <template v-else>-</template>
            </td>
            <td>{{ r.tradeCount }}</td>
          </tr>
          <tr v-if="rows.length === 0">
            <td colspan="10" class="empty">暂无成交</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.scope {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-dim);
  margin-left: 6px;
}

.micro-scroll {
  overflow-x: auto;
}

.micro-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
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
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.2px;
  position: sticky;
  top: 0;
  z-index: 1;
  cursor: help;
}

.micro-table tr:hover td {
  background: rgba(41, 98, 255, 0.03);
}

.sym-cell {
  font-weight: 600;
  color: var(--heading);
}

.imb-cell {
  min-width: 120px;
}

.imb-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
}

.imb-bar {
  display: flex;
  width: 70px;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
}

.imb-buy {
  display: block;
  height: 100%;
  background: var(--up);
  opacity: 0.7;
  transition: width 0.3s ease;
}

.imb-sell {
  display: block;
  flex: 1;
  height: 100%;
  background: var(--down);
  opacity: 0.7;
}

.imb-val {
  min-width: 36px;
  font-weight: 600;
}

.dim {
  color: var(--text-dim);
  font-size: 9px;
}

.empty {
  text-align: center;
  color: var(--text-dim);
  padding: 12px;
}
</style>
