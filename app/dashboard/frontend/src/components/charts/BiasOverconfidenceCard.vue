<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const svgRef = ref<SVGSVGElement>()

const TOM_COLORS: Record<number, string> = { 0: '#78909c', 1: '#0288d1', 2: '#7c4dff' }
const TOM_LABELS: Record<number, string> = { 0: 'T0', 1: 'T1', 2: 'T2' }
const MARGIN = { top: 14, right: 36, bottom: 22, left: 32 }
const BIAS_KEY = 'overconfidence' as const

const hasData = computed(() => store.biasTrends.length > 0)

const activeToms = computed(() => {
  const pts = store.biasTrends
  if (!pts.length) return []
  const toms: number[] = []
  for (const tom of [0, 1, 2] as const) {
    const key = `tom${tom}` as 'tom0' | 'tom1' | 'tom2'
    if (pts.some(p => p[key].total > 0)) toms.push(tom)
  }
  return toms
})

const latestValues = computed(() => {
  const pts = store.biasTrends
  if (!pts.length) return null
  const last = pts[pts.length - 1]
  const result: Record<number, number> = {}
  for (const tom of activeToms.value) {
    const key = `tom${tom}` as 'tom0' | 'tom1' | 'tom2'
    result[tom] = last[key][BIAS_KEY]
  }
  return result
})

const fallbackPct = computed(() => {
  const b = store.biasStats
  return b.total > 0 ? (b.overconfident / b.total * 100).toFixed(1) : null
})

function render() {
  if (!svgRef.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const data = store.biasTrends
  if (!data.length) return

  const toms = activeToms.value
  if (!toms.length) return

  const rect = svgRef.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const iw = w - MARGIN.left - MARGIN.right
  const ih = h - MARGIN.top - MARGIN.bottom
  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  const xDomain = d3.extent(data, d => d.day) as [number, number]
  const allVals: number[] = []
  for (const tom of toms) {
    const key = `tom${tom}` as 'tom0' | 'tom1' | 'tom2'
    for (const d of data) allVals.push(d[key][BIAS_KEY])
  }
  const yMax = Math.max(d3.max(allVals) ?? 10, 5)
  const x = d3.scaleLinear().domain(xDomain).range([0, iw])
  const y = d3.scaleLinear().domain([0, yMax * 1.1]).range([ih, 0])

  g.append('g').attr('transform', `translate(0,${ih})`)
    .call(d3.axisBottom(x).ticks(Math.min(data.length, 6)).tickFormat(d => `D${d}`))
    .call(g => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call(g => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  g.append('g')
    .call(d3.axisLeft(y).ticks(4).tickFormat(d => `${d}%`))
    .call(g => g.selectAll('text').attr('fill', '#787b86').style('font-size', '8px'))
    .call(g => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  g.selectAll('.grid-line').data(y.ticks(4)).join('line')
    .attr('x1', 0).attr('x2', iw).attr('y1', d => y(d)).attr('y2', d => y(d))
    .attr('stroke', '#e0e3eb').attr('stroke-dasharray', '2,3')

  for (const tom of toms) {
    const key = `tom${tom}` as 'tom0' | 'tom1' | 'tom2'
    const line = d3.line<typeof data[0]>().x(d => x(d.day)).y(d => y(d[key][BIAS_KEY])).curve(d3.curveMonotoneX)
    g.append('path').datum(data).attr('fill', 'none').attr('stroke', TOM_COLORS[tom]).attr('stroke-width', 1.5).attr('d', line)
    const last = data[data.length - 1]
    g.append('text').attr('x', iw + 3).attr('y', y(last[key][BIAS_KEY]))
      .attr('fill', TOM_COLORS[tom]).attr('font-size', '8px').attr('font-family', 'monospace').attr('dominant-baseline', 'middle')
      .text(TOM_LABELS[tom])
  }
}

let resizeObs: ResizeObserver | null = null
onMounted(() => { render(); if (svgRef.value) { resizeObs = new ResizeObserver(() => render()); resizeObs.observe(svgRef.value) } })
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.biasTrends, render, { deep: true })
</script>

<template>
  <div class="card">
    <div class="card-title">过度自信
      <span class="info-btn" @mouseenter="showTip('oc')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'oc'" class="custom-tooltip">日内换手率超过阈值的决策占比，反映交易者频繁交易的过度自信倾向</div>
      <span v-if="latestValues" class="latest-val">
        <span v-for="tom in activeToms" :key="tom" :style="{ color: TOM_COLORS[tom] }">{{ latestValues[tom] }}%</span>
      </span>
    </div>
    <template v-if="hasData">
      <svg ref="svgRef" class="bias-chart" />
    </template>
    <div v-else class="no-data">
      <span class="no-data-value" :style="{ color: fallbackPct && parseFloat(fallbackPct) > 10 ? '#ff9800' : '' }">
        {{ fallbackPct ?? '-' }}<small v-if="fallbackPct">%</small>
      </span>
      <span class="no-data-desc">高换手率决策占比（累计）</span>
      <span class="no-data-hint">趋势图将在第二个交易日开始显示</span>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';
.bias-chart { width: 100%; height: 140px; }
.latest-val { margin-left: auto; display: flex; gap: 8px; font-size: 10px; font-family: var(--font-mono); font-weight: 600; }
.no-data { display: flex; flex-direction: column; align-items: center; padding: 16px 0; }
.no-data-value { font-size: 28px; font-weight: 800; color: var(--heading); font-family: var(--font-mono); line-height: 1.1; }
.no-data-value small { font-size: 14px; font-weight: 500; }
.no-data-desc { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.no-data-hint { font-size: 9px; color: var(--text-muted); margin-top: 8px; }
</style>
