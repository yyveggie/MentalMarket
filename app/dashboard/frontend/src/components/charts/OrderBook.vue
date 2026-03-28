<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { fmt } from '@/utils/formatters'

const store = useMarketStore()
const priceSvg = ref<SVGSVGElement>()

const PRICE_COLORS = ['#2962ff', '#0288d1', '#7c4dff', '#ef5350', '#26a69a', '#ff9800']

function renderPriceChart() {
  if (!priceSvg.value) return
  const svg = d3.select(priceSvg.value)
  svg.selectAll('*').remove()

  const priceTrend = store.priceTrend
  const symbols = Object.keys(priceTrend).sort()
  if (!symbols.length) return

  const rect = priceSvg.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const m = { top: 10, right: 35, bottom: 20, left: 40 }
  const iW = w - m.left - m.right, iH = h - m.top - m.bottom
  const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`)

  const allData = symbols.flatMap((sym) => (priceTrend[sym] ?? []).map((pt) => ({ t: pt.t, p: pt.p })))
  if (!allData.length) return

  const xE = d3.extent(allData, (d) => d.t) as [number, number]
  const yE = d3.extent(allData, (d) => d.p) as [number, number]
  const yP = (yE[1] - yE[0]) * 0.05 || 1
  const x = d3.scaleLinear().domain(xE).range([0, iW])
  const y = d3.scaleLinear().domain([yE[0] - yP, yE[1] + yP]).range([iH, 0])

  g.append('g').attr('transform', `translate(0,${iH})`).call(d3.axisBottom(x).ticks(6).tickFormat((d) => `${d}s`))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))
  g.append('g').call(d3.axisLeft(y).ticks(5))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  const line = d3.line<{ t: number; p: number }>().x((d) => x(d.t)).y((d) => y(d.p)).curve(d3.curveMonotoneX)

  for (let i = 0; i < symbols.length; i++) {
    const pts = priceTrend[symbols[i]] ?? []
    if (!pts.length) continue
    g.append('path').datum(pts).attr('fill', 'none').attr('stroke', PRICE_COLORS[i % PRICE_COLORS.length]).attr('stroke-width', 1.2).attr('d', line)
    const last = pts[pts.length - 1]
    g.append('text').attr('x', x(last.t) + 3).attr('y', y(last.p)).attr('fill', PRICE_COLORS[i % PRICE_COLORS.length])
      .attr('font-size', '8px').attr('font-family', 'monospace').attr('dominant-baseline', 'middle').text(symbols[i])
  }

  const crosshair = g.append('line').attr('y1', 0).attr('y2', iH).attr('stroke', 'var(--chart-axis)').attr('stroke-width', 0.5).attr('stroke-dasharray', '3,3').style('display', 'none')
  const tooltip = svg.append('g').style('display', 'none').attr('pointer-events', 'none')
  const tooltipBg = tooltip.append('rect').attr('fill', 'var(--surface-0)').attr('stroke', 'var(--border)').attr('rx', 3).attr('opacity', 0.95)
  const tooltipText = tooltip.append('text').attr('font-size', '9px').attr('font-family', 'var(--font-mono)').attr('fill', 'var(--text)')

  svg.append('rect').attr('x', m.left).attr('y', m.top).attr('width', iW).attr('height', iH).attr('fill', 'transparent')
    .on('mousemove', (event: MouseEvent) => {
      const [mx] = d3.pointer(event)
      const t = x.invert(mx - m.left)
      crosshair.attr('x1', mx - m.left).attr('x2', mx - m.left).style('display', null)
      const lines: string[] = [`T=${t.toFixed(0)}s`]
      for (let i = 0; i < symbols.length; i++) {
        const pts = priceTrend[symbols[i]] ?? []
        if (!pts.length) continue
        let closest = pts[0]
        for (const p of pts) { if (Math.abs(p.t - t) < Math.abs(closest.t - t)) closest = p }
        lines.push(`${symbols[i]}: ${closest.p.toFixed(2)}`)
      }
      tooltipText.selectAll('tspan').remove()
      lines.forEach((l, i) => { tooltipText.append('tspan').attr('x', 6).attr('dy', i === 0 ? 12 : 12).text(l) })
      const tipW = 100, tipH = lines.length * 12 + 8
      tooltipBg.attr('width', tipW).attr('height', tipH)
      const tipX = mx + 10 + tipW > w ? mx - tipW - 10 : mx + 10
      tooltip.attr('transform', `translate(${tipX},${m.top + 5})`).style('display', null)
    })
    .on('mouseleave', () => { crosshair.style('display', 'none'); tooltip.style('display', 'none') })
}

let resizeObs: ResizeObserver | null = null
onMounted(() => {
  renderPriceChart()
  if (priceSvg.value) {
    resizeObs = new ResizeObserver(() => renderPriceChart())
    resizeObs.observe(priceSvg.value)
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.priceTrend, renderPriceChart, { deep: true })

const symbolEntries = computed(() => {
  return Object.entries(store.cdaBySymbol)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([symbol, cda]) => {
      const bids = cda.bids ?? []
      const asks = cda.asks ?? []
      const n = Math.max(bids.length, asks.length)
      const maxQty = Math.max(1, ...bids.map((b) => b.quantity), ...asks.map((a) => a.quantity))

      const rows = []
      for (let i = 0; i < n; i++) {
        rows.push({
          bid: bids[i] ?? null,
          ask: asks[i] ?? null,
          bidPct: bids[i] ? (bids[i].quantity / maxQty) * 100 : 0,
          askPct: asks[i] ? (asks[i].quantity / maxQty) * 100 : 0,
        })
      }

      const trades = (cda.recent_trades ?? []).slice(-20).reverse()
      return { symbol, lastPrice: cda.last_price, spread: cda.spread, rows, trades }
    })
})
</script>

<template>
  <div class="card">
    <div class="card-title">订单簿</div>

    <!-- 内嵌价格走势图 -->
    <div class="price-trend-section">
      <svg ref="priceSvg" class="price-svg" />
    </div>

    <div v-if="symbolEntries.length === 0" class="empty-hint"></div>

    <div class="ob-grid">
      <div v-for="entry in symbolEntries" :key="entry.symbol" class="ob-panel">
        <div class="ob-header">
          <span class="ob-symbol">{{ entry.symbol }}</span>
          <span v-if="entry.lastPrice != null" class="ob-price">{{ fmt(entry.lastPrice, 2) }}</span>
          <span v-if="entry.spread != null" class="ob-spread">价差 {{ fmt(entry.spread, 2) }}</span>
        </div>

        <div class="ob-body">
          <table class="l2-table">
            <thead>
              <tr>
                <th class="th-bid">买量</th>
                <th class="th-bid">买价</th>
                <th class="th-ask">卖价</th>
                <th class="th-ask">卖量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in entry.rows" :key="i">
                <td class="td-bid-qty">{{ row.bid?.quantity ?? '' }}</td>
                <td class="td-bid-price">{{ row.bid ? fmt(row.bid.price, 2) : '' }}</td>
                <td class="td-ask-price">{{ row.ask ? fmt(row.ask.price, 2) : '' }}</td>
                <td class="td-ask-qty">{{ row.ask?.quantity ?? '' }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="entry.trades.length" class="trades-section">
            <div class="trades-header">最近成交</div>
            <table class="trades-table">
              <tbody>
                <tr
                  v-for="(t, i) in entry.trades"
                  :key="i"
                  :class="t.aggressor === 'bid' ? 'trade-buy' : 'trade-sell'"
                >
                  <td class="t-price">{{ fmt(t.price, 2) }}</td>
                  <td class="t-qty">{{ t.quantity }}</td>
                  <td class="t-side">{{ t.aggressor === 'bid' ? 'B' : 'S' }}</td>
                </tr>
              </tbody>
            </table>
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

.price-svg {
  width: 100%;
  height: 160px;
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
}

.ob-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
}

.ob-symbol {
  font-weight: 700;
  font-size: 12px;
  color: var(--heading);
}

.ob-price {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent);
}

.ob-spread {
  font-size: 10px;
  color: var(--text-dim);
  margin-left: auto;
}

.ob-body {
  max-height: 280px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.l2-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: var(--font-mono);
}

.l2-table th {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-dim);
  padding: 4px 6px;
  text-align: right;
  position: sticky;
  top: 0;
  background: var(--surface-1);
}

.l2-table td {
  padding: 3px 6px;
  text-align: right;
}

.th-bid { color: var(--up); }
.th-ask { color: var(--down); }
.td-bid-qty { color: var(--up); font-weight: 600; }
.td-bid-price { color: var(--up); }
.td-ask-price { color: var(--down); }
.td-ask-qty { color: var(--down); font-weight: 600; }

.trades-section {
  margin-top: 8px;
  border-top: 1px solid var(--border);
  padding-top: 4px;
}

.trades-header {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-dim);
  padding: 2px 6px;
}

.trades-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 10px;
  font-family: var(--font-mono);
}

.trades-table td {
  padding: 2px 6px;
  text-align: right;
}

.trade-buy .t-price, .trade-buy .t-side { color: var(--up); }
.trade-sell .t-price, .trade-sell .t-side { color: var(--down); }
.t-qty { color: var(--text-muted); }
.t-side { font-weight: 700; width: 12px; }
</style>
