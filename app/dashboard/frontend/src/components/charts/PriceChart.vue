<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'

const store = useMarketStore()
const svgRef = ref<SVGSVGElement>()
const selectedSymbol = ref('__all__')

const symbols = computed(() => Object.keys(store.priceTrend).sort())

const MARGIN = { top: 20, right: 40, bottom: 30, left: 50 }
const COLORS = ['#2962ff', '#0288d1', '#7c4dff', '#ef5350', '#26a69a', '#ff9800']

function render() {
  if (!svgRef.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const rect = svgRef.value.getBoundingClientRect()
  const width = rect.width
  const height = rect.height
  const innerW = width - MARGIN.left - MARGIN.right
  const innerH = height - MARGIN.top - MARGIN.bottom

  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  const activeSymbols =
    selectedSymbol.value === '__all__' ? symbols.value : [selectedSymbol.value]

  const allData: Array<{ symbol: string; t: number; p: number }> = []
  for (const sym of activeSymbols) {
    const points = store.priceTrend[sym] ?? []
    for (const pt of points) {
      allData.push({ symbol: sym, t: pt.t, p: pt.p })
    }
  }
  if (!allData.length) return

  const xExtent = d3.extent(allData, (d) => d.t) as [number, number]
  const yExtent = d3.extent(allData, (d) => d.p) as [number, number]
  const yPad = (yExtent[1] - yExtent[0]) * 0.05 || 1

  const x = d3.scaleLinear().domain(xExtent).range([0, innerW])
  const y = d3.scaleLinear().domain([yExtent[0] - yPad, yExtent[1] + yPad]).range([innerH, 0])

  // Axes
  g.append('g')
    .attr('transform', `translate(0,${innerH})`)
    .call(d3.axisBottom(x).ticks(8).tickFormat((d) => `${d}s`))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '9px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  g.append('g')
    .call(d3.axisLeft(y).ticks(6))
    .call((g) => g.selectAll('text').attr('fill', '#787b86').style('font-size', '9px'))
    .call((g) => g.selectAll('line,path').attr('stroke', '#e0e3eb'))

  // Grid
  g.append('g')
    .selectAll('line')
    .data(y.ticks(6))
    .join('line')
    .attr('x1', 0)
    .attr('x2', innerW)
    .attr('y1', (d) => y(d))
    .attr('y2', (d) => y(d))
    .attr('stroke', '#e0e3eb')
    .attr('stroke-dasharray', '2,3')

  // Lines
  const line = d3
    .line<{ t: number; p: number }>()
    .x((d) => x(d.t))
    .y((d) => y(d.p))
    .curve(d3.curveMonotoneX)

  for (let i = 0; i < activeSymbols.length; i++) {
    const sym = activeSymbols[i]
    const points = store.priceTrend[sym] ?? []
    if (!points.length) continue

    g.append('path')
      .datum(points)
      .attr('fill', 'none')
      .attr('stroke', COLORS[i % COLORS.length])
      .attr('stroke-width', 1.5)
      .attr('d', line)

    // 最新价标签
    const last = points[points.length - 1]
    g.append('text')
      .attr('x', x(last.t) + 4)
      .attr('y', y(last.p))
      .attr('fill', COLORS[i % COLORS.length])
      .attr('font-size', '10px')
      .attr('font-family', 'monospace')
      .attr('dominant-baseline', 'middle')
      .text(`${sym} ${last.p.toFixed(2)}`)
  }
}

let resizeObs: ResizeObserver | null = null

onMounted(() => {
  render()
  if (svgRef.value) {
    resizeObs = new ResizeObserver(() => render())
    resizeObs.observe(svgRef.value)
  }
})

onUnmounted(() => {
  resizeObs?.disconnect()
})

watch(() => store.priceTrend, render, { deep: true })
</script>

<template>
  <div class="card">
    <div class="card-title">
      实时价格走势
      <div class="symbol-tabs">
        <button
          :class="['sym-tab', { active: selectedSymbol === '__all__' }]"
          @click="selectedSymbol = '__all__'"
        >
          全部
        </button>
        <button
          v-for="sym in symbols"
          :key="sym"
          :class="['sym-tab', { active: selectedSymbol === sym }]"
          @click="selectedSymbol = sym"
        >
          {{ sym }}
        </button>
      </div>
    </div>
    <svg ref="svgRef" class="chart-svg" />
  </div>
</template>

<style scoped>
.chart-svg {
  width: 100%;
  height: 200px;
}

.symbol-tabs {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

.sym-tab {
  padding: 2px 8px;
  font-size: 9px;
  font-family: var(--font-mono);
  font-weight: 600;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.15s;
}

.sym-tab:hover {
  color: var(--text);
}

.sym-tab.active {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-soft);
}
</style>
