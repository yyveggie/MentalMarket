<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtPct } from '@/utils/formatters'

const store = useMarketStore()
const wealthSvg = ref<SVGSVGElement>()
const returnSvg = ref<SVGSVGElement>()
const quantileSvg = ref<SVGSVGElement>()
const distSvg = ref<SVGSVGElement>()

const TOM_COLORS = ['#78909c', '#0288d1', '#7c4dff']
const TOM_LABELS = ['ToM 0', 'ToM 1', 'ToM 2']
const TOM_NAMES = ['ToM0', 'ToM1', 'ToM2']
const MARGIN = { top: 12, right: 8, bottom: 22, left: 40 }

const tomData = computed(() => {
  return [0, 1, 2].map((level) => {
    const t = store.tomSummary[String(level)]
    return {
      level,
      count: t?.count ?? 0,
      avgWealth: t?.avg_wealth ?? 0,
      totalWealth: t?.total_wealth ?? 0,
      medianWealth: t?.median_wealth ?? 0,
      minWealth: t?.min_wealth ?? 0,
      maxWealth: t?.max_wealth ?? 0,
      avgReturn: t?.avg_return_pct ?? 0,
      avgPnl: t?.avg_pnl ?? 0,
      profitRatio: t?.positive_return_ratio ?? 0,
      totalTrades: t?.total_trades ?? 0,
      avgTrades: t?.avg_trades_per_agent ?? 0,
      gini: t?.gini_coefficient ?? 0,
      top10Share: t?.top10_wealth_share ?? 0,
    }
  })
})

function renderBar(
  svgEl: SVGSVGElement | undefined,
  values: number[],
  formatFn: (v: number) => string = (v) => v.toFixed(0),
  colorFn?: (v: number, i: number) => string,
) {
  if (!svgEl) return
  const svg = d3.select(svgEl)
  svg.selectAll('*').remove()
  const rect = svgEl.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const iW = w - MARGIN.left - MARGIN.right, iH = h - MARGIN.top - MARGIN.bottom
  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  const x = d3.scaleBand().domain(TOM_LABELS).range([0, iW]).padding(0.3)
  const yMax = Math.max(1, ...values.map(Math.abs))
  const y = d3.scaleLinear().domain([-yMax * 0.05, yMax * 1.15]).range([iH, 0])

  g.append('g').attr('transform', `translate(0,${iH})`).call(d3.axisBottom(x))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))
  g.append('g').call(d3.axisLeft(y).ticks(4).tickFormat((d) => formatFn(d as number)))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  g.append('line').attr('x1', 0).attr('x2', iW).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', '#2a2f38')

  g.selectAll('.bar').data(values).join('rect')
    .attr('x', (_, i) => x(TOM_LABELS[i])!)
    .attr('y', (d) => y(Math.max(0, d)))
    .attr('width', x.bandwidth())
    .attr('height', (d) => Math.abs(y(0) - y(d)))
    .attr('rx', 2)
    .attr('fill', (d, i) => colorFn ? colorFn(d, i) : TOM_COLORS[i])
    .attr('opacity', 0.7)

  g.selectAll('.lbl').data(values).join('text')
    .attr('x', (_, i) => x(TOM_LABELS[i])! + x.bandwidth() / 2)
    .attr('y', (d) => y(Math.max(0, d)) - 3)
    .attr('text-anchor', 'middle').attr('fill', '#ccc9c1').attr('font-size', '9px').attr('font-family', 'monospace')
    .text((d) => formatFn(d))
}

function renderDist(svgEl: SVGSVGElement | undefined) {
  if (!svgEl) return
  const svg = d3.select(svgEl)
  svg.selectAll('*').remove()
  const rect = svgEl.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const r = Math.min(w, h) / 2 - 8
  const g = svg.append('g').attr('transform', `translate(${w / 2},${h / 2})`)
  const counts = tomData.value.map((d) => d.count)
  const total = d3.sum(counts)
  if (total === 0) {
    return
    return
  }
  const pie = d3.pie<number>().sort(null)(counts)
  const arc = d3.arc<d3.PieArcDatum<number>>().innerRadius(r * 0.55).outerRadius(r)

  g.selectAll('path').data(pie).join('path')
    .attr('d', arc as any)
    .attr('fill', (_, i) => TOM_COLORS[i])
    .attr('opacity', 0.7)
    .attr('stroke', '#e0e3eb')
    .attr('stroke-width', 1)

  g.selectAll('.label').data(pie).join('text')
    .attr('transform', (d) => `translate(${(arc as any).centroid(d)})`)
    .attr('text-anchor', 'middle').attr('fill', '#ccc9c1').attr('font-size', '9px').attr('font-family', 'monospace')
    .text((d) => d.data > 0 ? String(d.data) : '')

  g.append('text').attr('text-anchor', 'middle').attr('fill', '#8a877e').attr('font-size', '10px').attr('font-family', 'monospace')
    .attr('dy', '0.35em').text(`${total}`)
}

function renderAll() {
  const td = tomData.value
  renderBar(wealthSvg.value, td.map((d) => d.avgWealth))
  renderBar(returnSvg.value, td.map((d) => d.avgReturn), (v) => `${v.toFixed(1)}%`,
    (v, i) => v >= 0 ? TOM_COLORS[i] : '#26a69a')
  renderBar(quantileSvg.value, td.map((d) => d.medianWealth))
  renderDist(distSvg.value)
}

let resizeObs: ResizeObserver | null = null

onMounted(() => {
  renderAll()
  const targets = [wealthSvg, returnSvg, quantileSvg, distSvg].map((r) => r.value).filter(Boolean) as SVGSVGElement[]
  if (targets.length) {
    resizeObs = new ResizeObserver(() => renderAll())
    targets.forEach((t) => resizeObs!.observe(t))
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.tomSummary, renderAll, { deep: true })
</script>

<template>
  <div class="card">
    <div class="card-title">ToM 分析</div>

    <!-- Charts: 4 columns -->
    <div class="chart-row">
      <div class="chart-cell">
        <div class="chart-label">分布</div>
        <svg ref="distSvg" class="chart-svg" />
      </div>
      <div class="chart-cell">
        <div class="chart-label">平均财富</div>
        <svg ref="wealthSvg" class="chart-svg" />
      </div>
      <div class="chart-cell">
        <div class="chart-label">平均收益率</div>
        <svg ref="returnSvg" class="chart-svg" />
      </div>
      <div class="chart-cell">
        <div class="chart-label">中位财富</div>
        <svg ref="quantileSvg" class="chart-svg" />
      </div>
    </div>

    <!-- Performance table -->
    <div class="perf-table-wrap">
      <table class="perf-table">
        <thead>
          <tr>
            <th>ToM</th>
            <th>人数</th>
            <th>平均财富</th>
            <th>中位数</th>
            <th>最小</th>
            <th>最大</th>
            <th>平均收益率</th>
            <th>已实现盈亏</th>
            <th>盈利率</th>
            <th>基尼系数</th>
            <th>Top10%占比</th>
            <th>总交易</th>
            <th>人均交易</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in tomData" :key="d.level">
            <td>
              <span class="badge" :class="`badge-tom${d.level}`">ToM{{ d.level }}</span>
              {{ TOM_NAMES[d.level] }}
            </td>
            <td>{{ d.count }}</td>
            <td style="font-weight:600">{{ fmt(d.avgWealth, 0) }}</td>
            <td>{{ fmt(d.medianWealth, 0) }}</td>
            <td>{{ fmt(d.minWealth, 0) }}</td>
            <td>{{ fmt(d.maxWealth, 0) }}</td>
            <td :class="d.avgReturn > 0 ? 'color-up' : d.avgReturn < 0 ? 'color-down' : ''" style="font-weight:600">
              {{ fmtPct(d.avgReturn) }}
            </td>
            <td :class="d.avgPnl > 0 ? 'color-up' : d.avgPnl < 0 ? 'color-down' : ''">
              {{ fmt(d.avgPnl, 0) }}
            </td>
            <td :class="d.profitRatio >= 50 ? 'color-up' : 'color-down'">
              {{ d.profitRatio.toFixed(1) }}%
            </td>
            <td :class="d.gini > 0.4 ? 'color-down' : ''">{{ d.gini.toFixed(3) }}</td>
            <td :class="d.top10Share > 0.3 ? 'color-down' : ''">{{ (d.top10Share * 100).toFixed(1) }}%</td>
            <td>{{ d.totalTrades }}</td>
            <td>{{ d.avgTrades.toFixed(1) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.chart-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  margin-bottom: 8px;
}

.chart-cell {
  text-align: center;
}

.chart-label {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-dim);
  font-family: var(--font-mono);
  text-transform: uppercase;
  margin-bottom: 2px;
}

.chart-svg {
  width: 100%;
  height: 120px;
}

.perf-table-wrap {
  overflow-x: auto;
  border-top: 1px solid var(--border);
  padding-top: 6px;
}

.perf-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: var(--font-mono);
}

.perf-table th,
.perf-table td {
  padding: 4px 6px;
  text-align: right;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
}

.perf-table th:first-child,
.perf-table td:first-child {
  text-align: left;
}

.perf-table th {
  background: var(--surface-1);
  color: var(--accent);
  font-weight: 600;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.perf-table tr:hover td {
  background: rgba(41, 98, 255, 0.02);
}
</style>
