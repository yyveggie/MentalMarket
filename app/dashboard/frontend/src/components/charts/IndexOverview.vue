<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtPct } from '@/utils/formatters'

const store = useMarketStore()
const broadSvg = ref<SVGSVGElement>()

const broad = computed(() => store.broadMarket)

type SortKey = 'symbol' | 'pctChg' | 'price' | 'volume' | 'volatility'
const sortKey = ref<SortKey>('pctChg')
const sortAsc = ref(false)

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    sortAsc.value = key === 'symbol'
  }
}

function sortArrow(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortAsc.value ? ' ▲' : ' ▼'
}

const sortOptions = [
  { key: 'symbol' as SortKey, label: '代码' },
  { key: 'pctChg' as SortKey, label: '涨跌' },
  { key: 'price' as SortKey, label: '价格' },
  { key: 'volume' as SortKey, label: '成交量' },
  { key: 'volatility' as SortKey, label: '波动' },
]

const indexData = computed(() => {
  const indicators = store.technicalIndicators
  const items = Object.entries(store.indexSeries)
    .map(([symbol, rows]) => {
      const last = rows[rows.length - 1]
      const pctChg = last?.pct_chg ?? 0
      const prices = rows.map((r) => r.close)
      const high = prices.length ? Math.max(...prices) : 0
      const low = prices.length ? Math.min(...prices) : 0
      const totalVol = rows.reduce((s, r) => s + (r.volume ?? 0), 0)
      const ind = indicators[symbol]
      return {
        symbol,
        price: last?.close ?? 0,
        pctChg,
        volume: totalVol,
        high,
        low,
        rsi: ind?.rsi_14 ?? null,
        volatility: ind?.volatility ?? null,
        sparkline: prices.slice(-30),
      }
    })

  const key = sortKey.value
  const dir = sortAsc.value ? 1 : -1
  items.sort((a, b) => {
    const av = a[key] ?? 0
    const bv = b[key] ?? 0
    if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * dir
    return ((av as number) - (bv as number)) * dir
  })
  return items
})

function sparklinePoints(prices: number[]): string {
  if (prices.length < 2) return ''
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const range = max - min || 1
  return prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * 80
    const y = 20 - ((p - min) / range) * 18
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function renderBroadChart() {
  if (!broadSvg.value) return
  const svg = d3.select(broadSvg.value)
  svg.selectAll('*').remove()

  const data = store.broadIndexSeries
  if (!data.length) return

  const rect = broadSvg.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const m = { top: 4, right: 4, bottom: 4, left: 4 }
  const iW = w - m.left - m.right, iH = h - m.top - m.bottom
  const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`)

  const prices = data.map((d) => d.close)
  const x = d3.scaleLinear().domain([0, prices.length - 1]).range([0, iW])
  const ext = d3.extent(prices) as [number, number]
  const pad = (ext[1] - ext[0]) * 0.1 || 1
  const y = d3.scaleLinear().domain([ext[0] - pad, ext[1] + pad]).range([iH, 0])

  const isUp = prices[prices.length - 1] >= prices[0]
  const color = isUp ? '#ef5350' : '#26a69a'

  const area = d3.area<number>()
    .x((_, i) => x(i))
    .y0(iH)
    .y1((d) => y(d))
    .curve(d3.curveMonotoneX)

  const line = d3.line<number>()
    .x((_, i) => x(i))
    .y((d) => y(d))
    .curve(d3.curveMonotoneX)

  g.append('path').datum(prices).attr('fill', color).attr('opacity', 0.08).attr('d', area)
  g.append('path').datum(prices).attr('fill', 'none').attr('stroke', color).attr('stroke-width', 1.2).attr('d', line)

  const dot = g.append('circle').attr('r', 3).attr('fill', color).style('display', 'none')
  const tipG = svg.append('g').style('display', 'none').attr('pointer-events', 'none')
  const tipBg = tipG.append('rect').attr('fill', 'var(--surface-0)').attr('stroke', 'var(--border)').attr('rx', 3).attr('opacity', 0.95)
  const tipTxt = tipG.append('text').attr('font-size', '9px').attr('font-family', 'var(--font-mono)').attr('fill', 'var(--text)').attr('x', 5).attr('y', 13)

  svg.append('rect').attr('x', m.left).attr('y', m.top).attr('width', iW).attr('height', iH).attr('fill', 'transparent')
    .on('mousemove', (event: MouseEvent) => {
      const [mx] = d3.pointer(event)
      const idx = Math.round(x.invert(mx - m.left))
      const clamped = Math.max(0, Math.min(prices.length - 1, idx))
      const px = prices[clamped]
      dot.attr('cx', x(clamped)).attr('cy', y(px)).style('display', null)
      tipTxt.text(px.toFixed(2))
      tipBg.attr('width', 60).attr('height', 18)
      const tipX = mx + 15 + 60 > rect.width ? mx - 70 : mx + 15
      tipG.attr('transform', `translate(${tipX},${m.top + 2})`).style('display', null)
    })
    .on('mouseleave', () => { dot.style('display', 'none'); tipG.style('display', 'none') })
}

let resizeObs: ResizeObserver | null = null
onMounted(() => {
  renderBroadChart()
  if (broadSvg.value) {
    resizeObs = new ResizeObserver(() => renderBroadChart())
    resizeObs.observe(broadSvg.value)
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.broadIndexSeries, renderBroadChart, { deep: true })
</script>

<template>
  <div class="idx-overview card">
    <div class="card-title" style="grid-column: 1 / -1">{{ broad?.name ?? '大盘指数' }}</div>
    <!-- Broad market card -->
    <div class="broad-card">
      <div class="broad-top">
        <span v-if="broad?.value != null" class="broad-value">{{ fmt(broad.value, 2) }}</span>
        <span
          v-if="broad?.pct_chg != null"
          class="broad-pct"
          :class="broad.pct_chg > 0 ? 'color-up' : broad.pct_chg < 0 ? 'color-down' : ''"
        >
          {{ broad.pct_chg > 0 ? '▲' : broad.pct_chg < 0 ? '▼' : '─' }}
          {{ fmtPct(broad.pct_chg) }}
        </span>
      </div>
      <div v-if="broad" class="broad-stats">
        <span class="color-up">涨 {{ broad.up_count }}</span>
        <span class="color-down">跌 {{ broad.down_count }}</span>
        <span>平 {{ broad.flat_count }}</span>
        <span>成交 {{ fmt(broad.volume, 0) }}</span>
      </div>
      <svg ref="broadSvg" class="broad-chart" />
    </div>

    <!-- Index cards -->
    <div class="idx-cards">
      <div class="sort-bar">
        <span class="sort-label">排序</span>
        <button v-for="s in sortOptions" :key="s.key"
          class="sort-btn" :class="{ active: sortKey === s.key }"
          @click="toggleSort(s.key)"
        >{{ s.label }}{{ sortArrow(s.key) }}</button>
      </div>
      <div
        v-for="idx in indexData"
        :key="idx.symbol"
        class="idx-card"
        :class="idx.pctChg > 0 ? 'idx-up' : idx.pctChg < 0 ? 'idx-down' : ''"
      >
        <div class="idx-row-top">
          <span class="idx-sym">{{ idx.symbol }}</span>
          <span class="idx-price">{{ fmt(idx.price, 2) }}</span>
          <span class="idx-chg">
            {{ idx.pctChg > 0 ? '▲' : idx.pctChg < 0 ? '▼' : '─' }}
            {{ idx.pctChg > 0 ? '+' : '' }}{{ idx.pctChg.toFixed(2) }}%
          </span>
        </div>
        <svg v-if="idx.sparkline.length > 1" class="sparkline" :viewBox="`0 0 80 20`" preserveAspectRatio="none">
          <polyline
            :points="sparklinePoints(idx.sparkline)"
            fill="none"
            :stroke="idx.pctChg >= 0 ? '#ef5350' : '#26a69a'"
            stroke-width="1.2"
          />
        </svg>
        <div class="idx-detail-grid">
          <div class="idx-cell"><span class="idx-lbl">高</span><span class="idx-val">{{ fmt(idx.high, 2) }}</span></div>
          <div class="idx-cell"><span class="idx-lbl">低</span><span class="idx-val">{{ fmt(idx.low, 2) }}</span></div>
          <div class="idx-cell"><span class="idx-lbl">量</span><span class="idx-val">{{ fmt(idx.volume, 0) }}</span></div>
          <div class="idx-cell"><span class="idx-lbl">RSI</span><span class="idx-val">{{ idx.rsi != null ? fmt(idx.rsi, 1) : '-' }}</span></div>
          <div class="idx-cell"><span class="idx-lbl">波动</span><span class="idx-val">{{ idx.volatility != null ? (idx.volatility * 100).toFixed(1) + '%' : '-' }}</span></div>
        </div>
      </div>
      <div v-if="indexData.length === 0" class="idx-empty"></div>
    </div>
  </div>
</template>

<style scoped>
.idx-overview {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
}

.broad-card {
  background: var(--surface-0);
  border-radius: var(--radius-lg);
  padding: 8px 10px;
}

.broad-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 3px;
}

.broad-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--heading);
  font-family: var(--font-sans);
}

.broad-value {
  font-size: 16px;
  font-weight: 800;
  color: var(--heading);
  font-family: var(--font-mono);
}

.broad-pct {
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.broad-stats {
  display: flex;
  gap: 8px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  margin-bottom: 4px;
}

.broad-chart {
  width: 100%;
  height: 50px;
}

.sort-bar {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 2px;
}

.sort-label {
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-sans);
  margin-right: 4px;
}

.sort-btn {
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

.sort-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.sort-btn:hover:not(.active) {
  background: var(--surface-2);
}

.idx-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  background: var(--surface-0);
  border-radius: var(--radius-lg);
}

.idx-card {
  padding: 8px 10px;
  border-radius: var(--radius);
  font-family: var(--font-mono);
  background: var(--surface-1);
}

.idx-up {
  background: var(--up-soft);
}

.idx-down {
  background: var(--down-soft);
}

.idx-row-top {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 3px;
}

.idx-sym {
  font-size: 10px;
  font-weight: 700;
  color: var(--heading);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70px;
}

.idx-price {
  font-size: 13px;
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
  height: 18px;
  margin: 2px 0;
}

.idx-detail-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 2px;
  margin-top: 2px;
}

.idx-cell {
  text-align: center;
}

.idx-lbl {
  display: block;
  font-size: 8px;
  color: var(--text-dim);
}

.idx-val {
  display: block;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.idx-empty {
  grid-column: 1 / -1;
  color: var(--text-dim);
  font-size: 11px;
  padding: 12px;
  text-align: center;
}

@media (max-width: 960px) {
  .idx-overview {
    grid-template-columns: 1fr;
  }
}
</style>
