<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'

const store = useMarketStore()
const broadSvg = ref<SVGSVGElement>()
const volumeHistSvg = ref<SVGSVGElement>()
const volumeSimSvg = ref<SVGSVGElement>()

const M = { top: 12, right: 8, bottom: 22, left: 45 }
const COLORS = ['#2962ff', '#0288d1', '#7c4dff', '#ef5350', '#26a69a', '#ff9800', '#78909c', '#5c6bc0', '#00897b', '#e91e63']

function renderBroad() {
  if (!broadSvg.value) return
  const svg = d3.select(broadSvg.value)
  svg.selectAll('*').remove()

  const data = store.broadIndexSeries
  if (data.length < 2) return

  const rect = broadSvg.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const iW = w - M.left - M.right, iH = h - M.top - M.bottom
  const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)

  const prices = data.map((d) => d.close)
  const dates = data.map((d) => d.date)
  const x = d3.scalePoint().domain(dates).range([0, iW])
  const ext = d3.extent(prices) as [number, number]
  const pad = (ext[1] - ext[0]) * 0.05 || 1
  const y = d3.scaleLinear().domain([ext[0] - pad, ext[1] + pad]).range([iH, 0])

  const isUp = prices[prices.length - 1] >= prices[0]
  const color = isUp ? '#ef5350' : '#26a69a'

  g.append('g').attr('transform', `translate(0,${iH})`)
    .call(d3.axisBottom(x).tickValues(dates.filter((_, i) => i % Math.max(1, Math.floor(dates.length / 8)) === 0))
      .tickFormat((d) => { const s = String(d); return s.length > 10 ? s.slice(-6) : s }))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))
  g.append('g').call(d3.axisLeft(y).ticks(5))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  const area = d3.area<{ date: string; close: number }>().x((d) => x(d.date) ?? 0)
    .y0(iH).y1((d) => y(d.close)).curve(d3.curveMonotoneX)
  const line = d3.line<{ date: string; close: number }>().x((d) => x(d.date) ?? 0)
    .y((d) => y(d.close)).curve(d3.curveMonotoneX)

  g.append('path').datum(data).attr('fill', color).attr('opacity', 0.06).attr('d', area)
  g.append('path').datum(data).attr('fill', 'none').attr('stroke', color).attr('stroke-width', 1.5).attr('d', line)

  const last = data[data.length - 1]
  g.append('text').attr('x', iW - 2).attr('y', y(last.close) - 6)
    .attr('text-anchor', 'end').attr('fill', color).attr('font-size', '10px').attr('font-weight', 'bold').attr('font-family', 'monospace')
    .text(last.close.toFixed(2))
}

function renderVolumeHistory() {
  if (!volumeHistSvg.value) return
  const svg = d3.select(volumeHistSvg.value)
  svg.selectAll('*').remove()

  const seriesMap = store.indexSeries
  const symbols = Object.keys(seriesMap).sort()
  if (!symbols.length) return

  const rect = volumeHistSvg.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const iW = w - M.left - M.right, iH = h - M.top - M.bottom
  const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)

  const rowsBySymbol: Record<string, Array<{ date: string; volume: number }>> = {}
  for (const s of symbols) {
    rowsBySymbol[s] = (seriesMap[s] ?? [])
      .filter((r) => !String(r.date).startsWith('SIM_'))
      .map((r) => ({ date: String(r.date), volume: r.volume ?? 0 }))
  }

  const firstNonEmpty = symbols.find((s) => (rowsBySymbol[s] ?? []).length > 0)
  if (!firstNonEmpty) return
  const dates = (rowsBySymbol[firstNonEmpty] ?? []).map((r) => r.date)
  if (!dates.length) return

  const x = d3.scalePoint().domain(dates).range([0, iW])
  const allVols = symbols.flatMap((s) => (rowsBySymbol[s] ?? []).map((r) => r.volume ?? 0))
  const yMax = Math.max(1, ...allVols)
  const y = d3.scaleLinear().domain([0, yMax * 1.1]).range([iH, 0])

  g.append('g').attr('transform', `translate(0,${iH})`)
    .call(d3.axisBottom(x).tickValues(dates.filter((_, i) => i % Math.max(1, Math.floor(dates.length / 8)) === 0))
      .tickFormat((d) => { const s = String(d); return s.length > 10 ? s.slice(-6) : s }))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))
  g.append('g').call(d3.axisLeft(y).ticks(5))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  const line = d3.line<{ date: string; volume: number }>().x((d) => x(d.date) ?? 0).y((d) => y(d.volume)).curve(d3.curveMonotoneX)

  for (let i = 0; i < symbols.length; i++) {
    const rows = rowsBySymbol[symbols[i]] ?? []
    if (!rows.length) continue
    g.append('path').datum(rows).attr('fill', 'none').attr('stroke', COLORS[i % COLORS.length])
      .attr('stroke-width', 1).attr('opacity', 0.8).attr('d', line)
  }

  const legendG = g.append('g').attr('transform', `translate(0, -4)`)
  for (let i = 0; i < symbols.length; i++) {
    const xOff = i * 55
    legendG.append('line').attr('x1', xOff).attr('x2', xOff + 12).attr('y1', 0).attr('y2', 0)
      .attr('stroke', COLORS[i % COLORS.length]).attr('stroke-width', 1.5)
    legendG.append('text').attr('x', xOff + 15).attr('y', 3)
      .attr('fill', COLORS[i % COLORS.length]).attr('font-size', '8px').attr('font-family', 'monospace')
      .text(symbols[i])
  }
}

function renderVolumeSim() {
  if (!volumeSimSvg.value) return
  const svg = d3.select(volumeSimSvg.value)
  svg.selectAll('*').remove()

  const seriesMap = store.indexSeries
  const symbols = Object.keys(seriesMap).sort()
  if (!symbols.length) return

  const tdSec = store.tradingDaySeconds || 3600

  const dailyBySymbol: Record<string, Map<number, number>> = {}
  for (const s of symbols) {
    const dayMap = new Map<number, number>()
    for (const r of seriesMap[s] ?? []) {
      const dateStr = String(r.date)
      if (!dateStr.startsWith('SIM_')) continue
      const tMatch = dateStr.match(/T(\d+)$/)
      if (!tMatch) continue
      const simTime = parseInt(tMatch[1])
      const day = Math.floor(simTime / tdSec) + 1
      const vol = r.volume ?? 0
      const prev = dayMap.get(day) ?? 0
      if (vol > prev) dayMap.set(day, vol)
    }
    dailyBySymbol[s] = dayMap
  }

  const allDays = new Set<number>()
  for (const dayMap of Object.values(dailyBySymbol)) {
    for (const d of dayMap.keys()) allDays.add(d)
  }
  const days = Array.from(allDays).sort((a, b) => a - b)
  if (!days.length) return

  const rect = volumeSimSvg.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const iW = w - M.left - M.right, iH = h - M.top - M.bottom
  const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)

  const dayLabels = days.map((d) => `D${d}`)
  const x0 = d3.scaleBand().domain(dayLabels).range([0, iW]).padding(0.15)
  const x1 = d3.scaleBand().domain(symbols).range([0, x0.bandwidth()]).padding(0.05)

  const maxVol = Math.max(1, ...symbols.flatMap((s) => days.map((d) => dailyBySymbol[s]?.get(d) ?? 0)))
  const y = d3.scaleLinear().domain([0, maxVol * 1.1]).range([iH, 0])

  g.append('g').attr('transform', `translate(0,${iH})`)
    .call(d3.axisBottom(x0).tickValues(
      dayLabels.filter((_, i) => i % Math.max(1, Math.ceil(dayLabels.length / 15)) === 0),
    ))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))
  g.append('g').call(d3.axisLeft(y).ticks(5))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  for (let si = 0; si < symbols.length; si++) {
    const s = symbols[si]
    const dayMap = dailyBySymbol[s] ?? new Map()
    const color = COLORS[si % COLORS.length]
    for (const day of days) {
      const vol = dayMap.get(day) ?? 0
      if (vol <= 0) continue
      g.append('rect')
        .attr('x', (x0(`D${day}`) ?? 0) + (x1(s) ?? 0))
        .attr('y', y(vol))
        .attr('width', x1.bandwidth())
        .attr('height', iH - y(vol))
        .attr('fill', color)
        .attr('opacity', 0.8)
    }
  }

  const legendG = g.append('g').attr('transform', `translate(0, -4)`)
  for (let i = 0; i < symbols.length; i++) {
    const xOff = i * 55
    legendG.append('rect').attr('x', xOff).attr('y', -6).attr('width', 10).attr('height', 8)
      .attr('fill', COLORS[i % COLORS.length]).attr('opacity', 0.8).attr('rx', 1)
    legendG.append('text').attr('x', xOff + 13).attr('y', 3)
      .attr('fill', COLORS[i % COLORS.length]).attr('font-size', '8px').attr('font-family', 'monospace')
      .text(symbols[i])
  }
}

function renderAll() {
  renderBroad()
  renderVolumeHistory()
  renderVolumeSim()
}

let resizeObs: ResizeObserver | null = null
onMounted(() => {
  renderAll()
  const targets = [broadSvg.value, volumeHistSvg.value, volumeSimSvg.value].filter(Boolean) as SVGSVGElement[]
  if (targets.length) {
    resizeObs = new ResizeObserver(() => renderAll())
    targets.forEach((t) => resizeObs!.observe(t))
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch([() => store.broadIndexSeries, () => store.indexSeries], renderAll, { deep: true })
</script>

<template>
  <div class="bv-row">
    <div class="card">
      <div class="card-title">大盘走势</div>
      <svg ref="broadSvg" class="chart-svg" />
    </div>
    <div class="card">
      <div class="card-title">指数成交量（拆分）</div>
      <div class="volume-split">
        <div class="split-block">
          <div class="split-title">历史日值</div>
          <svg ref="volumeHistSvg" class="chart-svg split-svg" />
        </div>
        <div class="split-block">
          <div class="split-title">仿真每日成交量</div>
          <svg ref="volumeSimSvg" class="chart-svg split-svg" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bv-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.chart-svg {
  width: 100%;
  height: 160px;
}

.volume-split {
  display: grid;
  grid-template-rows: auto auto;
  gap: 8px;
}

.split-block {
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 4px;
}

.split-title {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-sans);
}

.split-svg {
  height: 120px;
}
</style>
