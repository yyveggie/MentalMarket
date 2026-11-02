<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { describeSimClock } from '@/utils/simTime'
import { useRafRender } from '@/composables/useRafRender'

const store = useMarketStore()
const svgRef = ref<SVGSVGElement>()

const MARGIN = { top: 15, right: 50, bottom: 25, left: 45 }
const COLOR_SENT = '#ff9800'
const COLOR_CONF = '#2962ff'

function render() {
  if (!svgRef.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const rect = svgRef.value.getBoundingClientRect()
  const width = rect.width, height = rect.height
  const innerW = width - MARGIN.left - MARGIN.right
  const innerH = height - MARGIN.top - MARGIN.bottom
  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  const sentData = store.sentimentTrend
  const confData = store.confidenceTrend
  if (!sentData.length && !confData.length) return

  const allT = [...sentData.map((d) => d.t), ...confData.map((d) => d.t)]
  const xExtent = d3.extent(allT) as [number, number]
  const x = d3.scaleLinear().domain(xExtent).range([0, innerW])
  const ySent = d3.scaleLinear().domain([-1, 1]).range([innerH, 0])

  g.append('g').attr('transform', `translate(0,${innerH})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat((d) => describeSimClock(Number(d), store.tradingDaySeconds)))
    .call((g) => g.selectAll('text').style('fill', 'var(--chart-text)').style('font-size', '10px'))
    .call((g) => g.selectAll('line,path').style('stroke', 'var(--chart-grid)'))

  g.append('g').call(d3.axisLeft(ySent).ticks(5))
    .call((g) => g.selectAll('text').attr('fill', COLOR_SENT).style('font-size', '10px'))
    .call((g) => g.selectAll('line,path').style('stroke', 'var(--chart-grid)'))

  g.append('line').attr('x1', 0).attr('x2', innerW).attr('y1', ySent(0)).attr('y2', ySent(0))
    .style('stroke', 'var(--chart-grid)').attr('stroke-dasharray', '3,3')

  if (sentData.length > 1) {
    const sentArea = d3.area<{ t: number; s: number }>().x((d) => x(d.t)).y0(ySent(0)).y1((d) => ySent(d.s)).curve(d3.curveMonotoneX)
    const sentLine = d3.line<{ t: number; s: number }>().x((d) => x(d.t)).y((d) => ySent(d.s)).curve(d3.curveMonotoneX)
    g.append('path').datum(sentData).attr('fill', 'rgba(255,152,0,0.08)').attr('d', sentArea)
    g.append('path').datum(sentData).attr('fill', 'none').attr('stroke', COLOR_SENT).attr('stroke-width', 1.5).attr('d', sentLine)
  }

  if (confData.length > 1) {
    const confLine = d3.line<{ t: number; c: number }>().x((d) => x(d.t)).y((d) => ySent(d.c)).curve(d3.curveMonotoneX)
    g.append('path').datum(confData).attr('fill', 'none').attr('stroke', COLOR_CONF).attr('stroke-width', 1.5).attr('stroke-dasharray', '6,3').attr('d', confLine)
  }

  const latestSent = sentData.length ? sentData[sentData.length - 1].s : null
  const latestConf = confData.length ? confData[confData.length - 1].c : null
  const val = g.append('g').attr('transform', `translate(6, -2)`)
  const parts: string[] = []
  if (latestSent !== null) parts.push(`情绪 ${latestSent.toFixed(3)}`)
  if (latestConf !== null) parts.push(`信心 ${latestConf.toFixed(3)}`)
  if (parts.length) val.append('text').style('fill', 'var(--chart-text)').attr('font-size', '10px').attr('font-family', 'monospace').text(parts.join(' | '))

  const legend = g.append('g').attr('transform', `translate(${innerW - 130}, -4)`)
  ;[{ label: '情绪指数', color: COLOR_SENT, dash: '' }, { label: '信心指数', color: COLOR_CONF, dash: '6,3' }].forEach((item, i) => {
    const gi = legend.append('g').attr('transform', `translate(${i * 70}, 0)`)
    gi.append('line').attr('x1', 0).attr('x2', 12).attr('y1', 0).attr('y2', 0).attr('stroke', item.color).attr('stroke-width', 1.5).attr('stroke-dasharray', item.dash)
    gi.append('text').attr('x', 15).attr('y', 3).attr('fill', item.color).attr('font-size', '10px').attr('font-family', 'monospace').text(item.label)
  })
}

const scheduleRender = useRafRender(render, { el: () => svgRef.value })
let resizeObs: ResizeObserver | null = null
onMounted(() => { render(); if (svgRef.value) { resizeObs = new ResizeObserver(() => scheduleRender()); resizeObs.observe(svgRef.value) } })
onUnmounted(() => resizeObs?.disconnect())
watch([() => store.sentimentTrend, () => store.confidenceTrend], scheduleRender)
</script>

<template>
  <div class="card">
    <div class="card-title">市场情绪 & 信心</div>
    <svg ref="svgRef" class="chart-svg" />
  </div>
</template>

<style scoped>
.chart-svg { width: 100%; height: 200px; }
</style>
