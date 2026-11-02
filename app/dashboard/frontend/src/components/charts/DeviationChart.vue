<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { describeSimClock } from '@/utils/simTime'
import { useRafRender } from '@/composables/useRafRender'

const store = useMarketStore()
const svgRef = ref<SVGSVGElement>()

const MARGIN = { top: 15, right: 40, bottom: 25, left: 45 }
const COLOR_DEV = '#ef5350'
const COLOR_BROAD = '#0288d1'

function render() {
  if (!svgRef.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const rect = svgRef.value.getBoundingClientRect()
  const width = rect.width, height = rect.height
  const innerW = width - MARGIN.left - MARGIN.right
  const innerH = height - MARGIN.top - MARGIN.bottom
  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  const devData = store.deviationTrend
  if (!devData.length) return

  const xExtent = d3.extent(devData, (d) => d.t) as [number, number]
  const x = d3.scaleLinear().domain(xExtent).range([0, innerW])

  const devExtent = d3.extent(devData, (d) => d.d) as [number, number]
  const devPad = Math.max(1, (devExtent[1] - devExtent[0]) * 0.1)
  const yDev = d3.scaleLinear().domain([devExtent[0] - devPad, devExtent[1] + devPad]).range([innerH, 0])

  g.append('g').attr('transform', `translate(0,${innerH})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat((d) => describeSimClock(Number(d), store.tradingDaySeconds)))
    .call((g) => g.selectAll('text').style('fill', 'var(--chart-text)').style('font-size', '10px'))
    .call((g) => g.selectAll('line,path').style('stroke', 'var(--chart-grid)'))

  g.append('g').call(d3.axisLeft(yDev).ticks(5).tickFormat((d) => `${(d as number).toFixed(1)}%`))
    .call((g) => g.selectAll('text').style('fill', 'var(--chart-text)').style('font-size', '10px'))
    .call((g) => g.selectAll('line,path').style('stroke', 'var(--chart-grid)'))

  g.append('line').attr('x1', 0).attr('x2', innerW).attr('y1', yDev(0)).attr('y2', yDev(0))
    .style('stroke', 'var(--chart-grid)').attr('stroke-dasharray', '3,3')

  if (devData.length > 1) {
    const devArea = d3.area<{ t: number; d: number }>().x((d) => x(d.t)).y0(yDev(0)).y1((d) => yDev(d.d)).curve(d3.curveMonotoneX)
    const devLine = d3.line<{ t: number; d: number }>().x((d) => x(d.t)).y((d) => yDev(d.d)).curve(d3.curveMonotoneX)
    g.append('path').datum(devData).attr('fill', 'rgba(239,83,80,0.06)').attr('d', devArea)
    g.append('path').datum(devData).attr('fill', 'none').attr('stroke', COLOR_DEV).attr('stroke-width', 1.5).attr('d', devLine)
  }

  const last = devData[devData.length - 1]
  if (last) {
    g.append('text').attr('x', 6).attr('y', -2)
      .style('fill', 'var(--chart-text)').attr('font-size', '10px').attr('font-family', 'monospace')
      .text(`当前偏离 ${last.d > 0 ? '+' : ''}${last.d.toFixed(2)}%`)
  }
}

const scheduleRender = useRafRender(render, { el: () => svgRef.value })
let resizeObs: ResizeObserver | null = null
onMounted(() => { render(); if (svgRef.value) { resizeObs = new ResizeObserver(() => scheduleRender()); resizeObs.observe(svgRef.value) } })
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.deviationTrend, scheduleRender)
</script>

<template>
  <div class="card">
    <div class="card-title">价格偏离度走势</div>
    <svg ref="svgRef" class="chart-svg" />
  </div>
</template>

<style scoped>
.chart-svg { width: 100%; height: 200px; }
</style>
