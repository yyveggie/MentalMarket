<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt } from '@/utils/formatters'
import { describeSimClock } from '@/utils/simTime'
import type { AuctionResult, CallAuctionInfo, L2Level, TradeRecord } from '@/types/market'
import KlineChart from './pro/KlineChart.vue'
import CompareChart from './pro/CompareChart.vue'

const store = useMarketStore()
const TICK_SIZE = 0.01
const L2_ROWS = 10   // 固定渲染档位数：档位数随盘口变化时面板高度不再跳动

// ── 盘中行情图：单标的分钟 K 线，或全部标的归一化对比 ──
const chartView = ref<'kline' | 'compare'>('kline')
const chartSymbol = ref<string>('')
const chartSymbols = computed(() => {
  const syms = new Set<string>([...store.symbols, ...Object.keys(store.intradayBars)])
  return [...syms].sort()
})
watch(
  chartSymbols,
  (syms) => {
    if (!syms.length) return
    if (!chartSymbol.value || !syms.includes(chartSymbol.value)) chartSymbol.value = syms[0]
  },
  { immediate: true },
)

// ── 订单簿 ──
interface L2Row {
  bid: L2Level | null
  ask: L2Level | null
  bidCum: number
  askCum: number
  bidCumPct: number
  askCumPct: number
}

interface TapeRow {
  key: string
  time: string
  price: number
  quantity: number
  side: 'bid' | 'ask'
  dir: 'up' | 'down' | 'flat'
}

interface SymbolEntry {
  symbol: string
  lastPrice: number | null
  bid1: number | null
  ask1: number | null
  mid: number | null
  spread: number | null
  spreadTicks: number | null
  spreadBps: number | null
  bidDepth: number
  askDepth: number
  imbalance: number | null
  phase: string
  inCall: boolean
  auction: CallAuctionInfo | null
  lastAuction: AuctionResult | null
  rows: L2Row[]
  trades: TapeRow[]
}

const TAPE_ROWS = 8

function padTape(rows: TapeRow[]): TapeRow[] {
  const out = rows.slice(0, TAPE_ROWS)
  while (out.length < TAPE_ROWS) {
    out.push({ key: `pad-${out.length}`, time: '', price: NaN, quantity: 0, side: 'bid', dir: 'flat' })
  }
  return out
}

function buildTape(trades: TradeRecord[]): TapeRow[] {
  const recent = trades.slice(-(TAPE_ROWS + 1))
  const out: TapeRow[] = []
  for (let i = recent.length - 1; i >= 0; i--) {
    const t = recent[i]
    const older = i > 0 ? recent[i - 1] : null
    const dir: TapeRow['dir'] = older == null || Math.abs(t.price - older.price) < 1e-9 ? 'flat' : t.price > older.price ? 'up' : 'down'
    out.push({
      key: `${t.sim_time}|${t.price}|${t.quantity}|${t.buyer_id}|${t.seller_id}`,
      time: describeSimClock(t.sim_time, store.tradingDaySeconds).split(' ')[1] ?? '',
      price: t.price,
      quantity: t.quantity,
      side: t.aggressor === 'bid' ? 'bid' : 'ask',
      dir,
    })
  }
  return padTape(out)
}

const symbolEntries = computed<SymbolEntry[]>(() => {
  return Object.entries(store.cdaBySymbol)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([symbol, cda]) => {
      const bids = cda.bids ?? []
      const asks = cda.asks ?? []
      const n = Math.max(bids.length, asks.length)

      const rows: L2Row[] = []
      let bidCum = 0
      let askCum = 0
      for (let i = 0; i < n; i++) {
        const bid = bids[i] ?? null
        const ask = asks[i] ?? null
        if (bid) bidCum += bid.quantity
        if (ask) askCum += ask.quantity
        rows.push({ bid, ask, bidCum: bid ? bidCum : 0, askCum: ask ? askCum : 0, bidCumPct: 0, askCumPct: 0 })
      }
      const maxCum = Math.max(1, bidCum, askCum)
      for (const r of rows) {
        r.bidCumPct = (r.bidCum / maxCum) * 100
        r.askCumPct = (r.askCum / maxCum) * 100
      }
      while (rows.length < L2_ROWS) {
        rows.push({ bid: null, ask: null, bidCum: 0, askCum: 0, bidCumPct: 0, askCumPct: 0 })
      }

      const bid1 = bids[0]?.price ?? null
      const ask1 = asks[0]?.price ?? null
      const mid = bid1 != null && ask1 != null ? (bid1 + ask1) / 2 : null
      const spread = bid1 != null && ask1 != null ? ask1 - bid1 : (cda.spread ?? null)
      const spreadTicks = spread != null ? Math.round(spread / TICK_SIZE) : null
      const spreadBps = spread != null && mid ? (spread / mid) * 10000 : null
      const bidDepth = bidCum
      const askDepth = askCum
      const imbalance = bidDepth + askDepth > 0 ? (bidDepth - askDepth) / (bidDepth + askDepth) : null

      return {
        symbol,
        lastPrice: cda.last_price,
        bid1,
        ask1,
        mid,
        spread,
        spreadTicks,
        spreadBps,
        bidDepth,
        askDepth,
        imbalance,
        phase: cda.phase ?? 'continuous',
        inCall: (cda.phase ?? 'continuous') !== 'continuous',
        auction: cda.call_auction ?? null,
        lastAuction: cda.last_auction ?? null,
        rows,
        trades: buildTape(cda.recent_trades ?? []),
      }
    })
})

// ── 价格变动闪烁（0.3s） ──
const priceFlash = ref<Record<string, 'up' | 'down'>>({})
const tapeFlash = ref<Record<string, boolean>>({})
const prevPrice = new Map<string, number>()
const prevTradeKey = new Map<string, string>()
const timers = new Map<string, number>()

function pulse(kind: 'p' | 't', symbol: string, dir: 'up' | 'down' | null) {
  const id = `${kind}:${symbol}`
  const existing = timers.get(id)
  if (existing != null) window.clearTimeout(existing)
  if (kind === 'p' && dir) priceFlash.value[symbol] = dir
  if (kind === 't') tapeFlash.value[symbol] = true
  timers.set(
    id,
    window.setTimeout(() => {
      if (kind === 'p') delete priceFlash.value[symbol]
      else delete tapeFlash.value[symbol]
      timers.delete(id)
    }, 320),
  )
}

watch(symbolEntries, (entries) => {
  for (const e of entries) {
    const p = e.lastPrice
    const prev = prevPrice.get(e.symbol)
    if (p != null && prev != null && Math.abs(p - prev) > 1e-9) pulse('p', e.symbol, p > prev ? 'up' : 'down')
    if (p != null) prevPrice.set(e.symbol, p)

    const newest = e.trades[0]?.key ?? ''
    const prevKey = prevTradeKey.get(e.symbol)
    if (newest && prevKey !== undefined && prevKey !== newest) pulse('t', e.symbol, null)
    prevTradeKey.set(e.symbol, newest)
  }
})

onBeforeUnmount(() => {
  for (const id of timers.values()) window.clearTimeout(id)
  timers.clear()
})

function imbalanceClass(v: number | null): string {
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

    <div class="price-trend-section">
      <div class="pt-toolbar">
        <div class="card-title" style="margin-bottom:0">盘中行情</div>
        <div class="pt-tabs">
          <button class="pt-btn" :class="{ active: chartView === 'kline' }" @click="chartView = 'kline'">分钟K线</button>
          <button class="pt-btn" :class="{ active: chartView === 'compare' }" @click="chartView = 'compare'">多标的对比</button>
        </div>
        <div v-if="chartView === 'kline'" class="pt-tabs pt-symbols">
          <button
            v-for="s in chartSymbols"
            :key="s"
            class="pt-btn"
            :class="{ active: chartSymbol === s }"
            @click="chartSymbol = s"
          >{{ s }}</button>
        </div>
      </div>
      <KlineChart
        v-if="chartView === 'kline' && chartSymbol"
        :symbol="chartSymbol"
        mode="intraday"
        :height="240"
        default-sub="none"
      />
      <CompareChart
        v-else-if="chartView === 'compare'"
        :symbols="chartSymbols"
        mode="intraday"
        :height="240"
        title="盘中对比"
      />
    </div>

    <div v-if="symbolEntries.length === 0" class="empty-hint">暂无盘口数据</div>

    <div class="ob-grid">
      <div v-for="entry in symbolEntries" :key="entry.symbol" class="ob-panel">
        <div class="ob-header">
          <span class="ob-symbol">{{ entry.symbol }}</span>
          <span
            v-if="entry.lastPrice != null"
            class="ob-price"
            :class="priceFlash[entry.symbol] ? `flash-${priceFlash[entry.symbol]}` : ''"
          >{{ fmt(entry.lastPrice, 2) }}</span>
          <span v-if="entry.inCall" class="ob-phase">{{ entry.phase === 'open_call' ? '开盘竞价' : '收盘竞价' }}</span>
          <span v-else class="ob-mid" :title="'中间价 = (买一 + 卖一) / 2'">中 {{ entry.mid == null ? '-' : fmt(entry.mid, 3) }}</span>
          <span
            v-if="entry.lastAuction && entry.lastAuction.price != null"
            class="ob-auc"
            :title="`最近一次集合竞价：成交 ${entry.lastAuction.volume}，未匹配 买 ${entry.lastAuction.bid_unmatched} / 卖 ${entry.lastAuction.ask_unmatched}`"
          >{{ entry.lastAuction.kind === 'open' ? '开' : '收' }} {{ fmt(entry.lastAuction.price, 2) }}</span>
        </div>

        <div class="ob-metrics">
          <div v-if="entry.inCall" class="m m-call" :title="'集合竞价虚拟参考价：按成交量最大原则计算的单一成交价；匹配量为该价可成交数量'">
            <span class="k">虚拟参考价</span>
            <span class="v">
              <template v-if="entry.auction">
                <em class="call-px">{{ fmt(entry.auction.price, 2) }}</em>
                <small>匹配 {{ entry.auction.volume }} · 未匹配 <i class="color-up">买{{ entry.auction.bid_unmatched }}</i> / <i class="color-down">卖{{ entry.auction.ask_unmatched }}</i></small>
              </template>
              <template v-else>未交叉</template>
            </span>
          </div>
          <div v-else class="m">
            <span class="k">买一 / 卖一</span>
            <span class="v"><em class="color-up">{{ entry.bid1 == null ? '-' : fmt(entry.bid1, 2) }}</em> / <em class="color-down">{{ entry.ask1 == null ? '-' : fmt(entry.ask1, 2) }}</em></span>
          </div>
          <div class="m" :title="'价差 = 卖一 − 买一；bp 以中间价为基准'">
            <span class="k">价差</span>
            <span class="v">
              <template v-if="entry.spread != null">
                {{ fmt(entry.spread, 2) }}
                <small>{{ entry.spreadTicks }}tick · {{ entry.spreadBps == null ? '-' : entry.spreadBps.toFixed(1) }}bp</small>
              </template>
              <template v-else>-</template>
            </span>
          </div>
          <div class="m m-imb" :title="'失衡度 = (买盘深度 − 卖盘深度) / 总深度，正值买盘更厚'">
            <span class="k">失衡度</span>
            <span class="v" :class="imbalanceClass(entry.imbalance)">{{ pctSigned(entry.imbalance) }}</span>
            <div class="imb-bar" :title="`买盘 ${entry.bidDepth} / 卖盘 ${entry.askDepth}`">
              <i class="imb-bid" :style="{ width: `${entry.bidDepth + entry.askDepth > 0 ? (entry.bidDepth / (entry.bidDepth + entry.askDepth)) * 100 : 50}%` }" />
              <i class="imb-ask" />
            </div>
            <span class="k depth">{{ entry.bidDepth }} / {{ entry.askDepth }}</span>
          </div>
        </div>

        <div class="ob-body">
          <div class="l2">
            <div class="l2-head">
              <span class="color-up">买量</span>
              <span class="color-up">买价</span>
              <span class="color-down">卖价</span>
              <span class="color-down">卖量</span>
            </div>
            <div v-for="(row, i) in entry.rows" :key="i" class="l2-row">
              <div class="l2-side l2-bid">
                <i class="l2-bar" :style="{ width: `${row.bidCumPct}%` }" />
                <span class="l2-q" :title="row.bid ? `累计买盘 ${row.bidCum}` : ''">{{ row.bid?.quantity ?? '' }}</span>
                <span class="l2-p">{{ row.bid ? fmt(row.bid.price, 2) : '' }}</span>
              </div>
              <div class="l2-side l2-ask">
                <i class="l2-bar" :style="{ width: `${row.askCumPct}%` }" />
                <span class="l2-p">{{ row.ask ? fmt(row.ask.price, 2) : '' }}</span>
                <span class="l2-q" :title="row.ask ? `累计卖盘 ${row.askCum}` : ''">{{ row.ask?.quantity ?? '' }}</span>
              </div>
            </div>
          </div>

          <div class="trades-section">
            <div class="tape-head">
              <span>时间</span><span>价格</span><span>数量</span><span>方向</span>
            </div>
            <div
              v-for="(t, i) in entry.trades"
              :key="t.key"
              class="tape-row"
              :class="[Number.isNaN(t.price) ? 'tape-pad' : t.side === 'bid' ? 'trade-buy' : 'trade-sell', { 'tape-flash': i === 0 && tapeFlash[entry.symbol] }]"
            >
              <template v-if="!Number.isNaN(t.price)">
                <span class="t-time">{{ t.time }}</span>
                <span class="t-price" :class="t.dir === 'up' ? 'color-up' : t.dir === 'down' ? 'color-down' : ''">
                  {{ fmt(t.price, 2) }}<i class="t-arrow">{{ t.dir === 'up' ? '▲' : t.dir === 'down' ? '▼' : '' }}</i>
                </span>
                <span class="t-qty">{{ t.quantity }}</span>
                <span class="t-side">{{ t.side === 'bid' ? '买' : '卖' }}</span>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.price-trend-section {
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}

.pt-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.pt-tabs {
  display: inline-flex;
  gap: 3px;
  flex-wrap: wrap;
}

.pt-symbols {
  margin-left: auto;
}

.pt-btn {
  border: none;
  background: var(--surface-1);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}

.pt-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.pt-btn:hover:not(.active) {
  background: var(--surface-2);
}

.ob-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  grid-auto-flow: row;
  gap: 6px;
}

.empty-hint {
  text-align: center;
  color: var(--text-dim);
  padding: 16px;
  font-size: 12px;
}

.ob-panel {
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface-1);
  min-width: 0;
  font-variant-numeric: tabular-nums;
}

.ob-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 10px 2px;
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  height: 30px;
  box-sizing: border-box;
}

.ob-symbol {
  font-weight: 700;
  font-size: 12px;
  color: var(--heading);
}

.ob-price {
  font-size: 15px;
  font-weight: 700;
  color: var(--heading);
  padding: 0 4px;
  border-radius: 3px;
  transition: background 0.3s ease-out;
}

.ob-mid {
  font-size: 10px;
  color: var(--text-dim);
  margin-left: auto;
}

/* 价格变动闪烁：红涨绿跌，0.3s 淡出 */
.ob-phase {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  color: var(--accent-3);
  background: rgba(255, 152, 0, 0.14);
  white-space: nowrap;
}

.ob-auc {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}

.m-call .v small i {
  font-style: normal;
}

.call-px {
  color: var(--accent-3);
}

@keyframes flash-up {
  from { background: rgba(239, 83, 80, 0.45); }
  to { background: transparent; }
}
@keyframes flash-down {
  from { background: rgba(38, 166, 154, 0.45); }
  to { background: transparent; }
}
.flash-up { animation: flash-up 0.3s ease-out; }
.flash-down { animation: flash-down 0.3s ease-out; }

.ob-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px 10px;
  padding: 2px 10px 6px;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
}

.ob-metrics .m.m-imb {
  grid-column: 1 / -1;
  flex-direction: row;
  align-items: center;
  gap: 6px;
}

.ob-metrics .m.m-imb .v {
  min-width: 38px;
  text-align: right;
}

.ob-metrics .m.m-imb .imb-bar {
  flex: 1;
  min-width: 40px;
}

.ob-metrics .m.m-imb .depth {
  font-size: 9px;
  white-space: nowrap;
}

.ob-metrics .m {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.ob-metrics .k {
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
}

.ob-metrics .v {
  font-size: 12px;
  color: var(--heading);
  font-weight: 600;
  white-space: nowrap;
}

.ob-metrics .v em {
  font-style: normal;
}

.ob-metrics .v small {
  font-size: 9px;
  font-weight: 400;
  color: var(--text-dim);
  margin-left: 3px;
}

.imb-bar {
  display: flex;
  height: 5px;
  border-radius: 2px;
  overflow: hidden;
  background: var(--down-soft);
}

.imb-bid {
  display: block;
  height: 100%;
  background: var(--up);
  opacity: 0.55;
  transition: width 0.3s ease;
}

.imb-ask {
  display: block;
  flex: 1;
  height: 100%;
  background: var(--down);
  opacity: 0.55;
}

.ob-body {
  overflow: hidden;
  overflow-anchor: none;
}

/* ── L2 深度 ── */
.l2 {
  font-size: 12px;
  font-family: var(--font-mono);
}

.l2-head {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  font-size: 9px;
  font-weight: 600;
  padding: 4px 6px;
  position: sticky;
  top: 0;
  background: var(--surface-1);
  z-index: 1;
}

.l2-head span {
  text-align: right;
}

.l2-head span:nth-child(1),
.l2-head span:nth-child(3) {
  text-align: left;
}

.l2-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
}

.l2-side {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 3px 6px;
  overflow: hidden;
  height: 22px;
  box-sizing: border-box;
}

.l2-bar {
  position: absolute;
  top: 1px;
  bottom: 1px;
  opacity: 0.16;
  transition: width 0.25s ease;
  pointer-events: none;
}

.l2-bid .l2-bar {
  right: 0;
  background: var(--up);
}

.l2-ask .l2-bar {
  left: 0;
  background: var(--down);
}

.l2-side span {
  position: relative;
  z-index: 1;
}

.l2-bid .l2-q { text-align: left; color: var(--up); font-weight: 600; }
.l2-bid .l2-p { text-align: right; color: var(--up); }
.l2-ask .l2-p { text-align: left; color: var(--down); }
.l2-ask .l2-q { text-align: right; color: var(--down); font-weight: 600; }

/* ── 成交明细 ── */
.trades-section {
  margin-top: 8px;
  border-top: 1px solid var(--border);
  padding-top: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
}

.tape-head,
.tape-row {
  display: grid;
  grid-template-columns: 1.1fr 1.3fr 1fr 0.6fr;
  padding: 2px 6px;
  align-items: center;
  height: 20px;
  box-sizing: border-box;
}

.tape-pad {
  background: transparent;
}

.tape-head {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-dim);
}

.tape-head span,
.tape-row span {
  text-align: right;
}

.tape-head span:first-child,
.tape-row .t-time {
  text-align: left;
}

.tape-row {
  border-radius: 2px;
}

.trade-buy { background: var(--up-soft); }
.trade-sell { background: var(--down-soft); }

.trade-buy .t-side { color: var(--up); font-weight: 700; }
.trade-sell .t-side { color: var(--down); font-weight: 700; }

.t-time { color: var(--text-dim); }
.t-qty { color: var(--text-muted); }

.t-price {
  color: var(--heading);
  font-weight: 600;
}

.t-arrow {
  font-style: normal;
  font-size: 8px;
  margin-left: 2px;
}

@keyframes tape-flash {
  from { box-shadow: inset 0 0 0 100px rgba(41, 98, 255, 0.25); }
  to { box-shadow: none; }
}
.tape-flash { animation: tape-flash 0.3s ease-out; }
</style>
