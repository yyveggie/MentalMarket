<script setup lang="ts">
/**
 * 指数成交量：
 * - 左：真实历史日成交额，lightweight-charts 折线（可拖动平移、滚轮缩放，时间轴自动抽稀）
 * - 右：仿真每日成交额，D3 分组柱状图，悬浮显示每根柱子的数值
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { LineSeries, type IChartApi, type ISeriesApi, type MouseEventParams, type Time, type UTCTimestamp } from 'lightweight-charts'
import { useMarketStore } from '@/stores/marketStore'
import { useRafRender } from '@/composables/useRafRender'
import { useLightweightChart } from './pro/useLightweightChart'
import { fmtCn } from '@/utils/formatters'
import { formatDateUtc, parseDateUtc, timeToNumber } from '@/utils/simTime'

const store = useMarketStore()
const COLORS = ['#2962ff', '#0288d1', '#7c4dff', '#ef5350', '#26a69a', '#ff9800', '#78909c', '#5c6bc0', '#00897b', '#e91e63']

const symbols = computed(() => Object.keys(store.indexSeries).sort())
function colorOf(i: number): string {
  return COLORS[i % COLORS.length]
}

// ── 左：历史日值（lightweight-charts） ──
const histContainer = ref<HTMLElement>()
let histChart: IChartApi | null = null
const histLines = new Map<string, ISeriesApi<'Line'>>()
let histFitted = false
const histHoverTime = ref('')
const histHover = ref<Record<string, number | null>>({})

const histData = computed<Record<string, Array<{ time: UTCTimestamp; value: number }>>>(() => {
  const out: Record<string, Array<{ time: UTCTimestamp; value: number }>> = {}
  for (const sym of symbols.value) {
    const pts: Array<{ time: UTCTimestamp; value: number }> = []
    for (const r of store.indexSeries[sym] ?? []) {
      const date = String(r.date ?? '')
      if (date.startsWith('SIM_') || date.startsWith('BASELINE_') || date === 'INIT') continue
      const t = parseDateUtc(date)
      if (t == null) continue
      pts.push({ time: t as UTCTimestamp, value: Number(r.volume ?? 0) })
    }
    pts.sort((a, b) => a.time - b.time)
    const dedup: typeof pts = []
    for (const p of pts) {
      if (dedup.length && dedup[dedup.length - 1].time === p.time) dedup[dedup.length - 1] = p
      else dedup.push(p)
    }
    out[sym] = dedup
  }
  return out
})

const histLegend = computed(() =>
  symbols.value.map((sym, i) => {
    const arr = histData.value[sym] ?? []
    const last = arr.length ? arr[arr.length - 1].value : null
    const hovered = histHover.value[sym]
    return { sym, color: colorOf(i), value: hovered === undefined ? last : hovered }
  }),
)

useLightweightChart(histContainer, {
  options: () => ({
    localization: {
      priceFormatter: (v: number) => fmtCn(v, 0),
      timeFormatter: (time: Time) => {
        const t = timeToNumber(time)
        return t == null ? '' : formatDateUtc(t, 'full')
      },
    },
    timeScale: { timeVisible: false, rightOffset: 2 },
    rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.05 } },
  }),
  build: (chart) => {
    histChart = chart
    chart.subscribeCrosshairMove(onHistCrosshair)
    syncHist()
  },
})

function onHistCrosshair(param: MouseEventParams) {
  const t = timeToNumber(param.time)
  if (t == null) {
    histHoverTime.value = ''
    histHover.value = {}
    return
  }
  histHoverTime.value = formatDateUtc(t, 'full')
  const vals: Record<string, number | null> = {}
  for (const [sym, s] of histLines.entries()) {
    const d = param.seriesData.get(s) as { value?: number } | undefined
    vals[sym] = d?.value ?? null
  }
  histHover.value = vals
}

function syncHist() {
  if (!histChart) return
  const wanted = new Set(symbols.value)
  for (const [sym, s] of [...histLines.entries()]) {
    if (!wanted.has(sym)) {
      histChart.removeSeries(s)
      histLines.delete(sym)
    }
  }
  symbols.value.forEach((sym, i) => {
    let s = histLines.get(sym)
    if (!s) {
      s = histChart!.addSeries(LineSeries, {
        color: colorOf(i),
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: true,
      })
      histLines.set(sym, s)
    }
    s.setData(histData.value[sym] ?? [])
  })
  if (!histFitted && symbols.value.some((sym) => (histData.value[sym] ?? []).length > 1)) {
    histChart.timeScale().fitContent()
    histFitted = true
  }
}

const scheduleHist = useRafRender(syncHist, { el: () => histContainer.value })
watch(histData, scheduleHist)

// ── 右：仿真每日成交量（D3 分组柱 + 悬浮提示） ──
const volumeSimSvg = ref<SVGSVGElement>()
const simWrap = ref<HTMLElement>()
const tip = ref({ show: false, x: 0, y: 0, flip: false, title: '', value: '', color: '' })
const M = { top: 34, right: 8, bottom: 22, left: 52 }

type AxisSel = d3.Selection<SVGGElement, unknown, null, undefined>
function styleAxis(g: AxisSel) {
  g.selectAll('text').style('fill', 'var(--chart-text)').style('font-size', '10px')
  g.selectAll('line,path').style('stroke', 'var(--chart-grid)')
}

function renderVolumeSim() {
  if (!volumeSimSvg.value) return
  const svg = d3.select(volumeSimSvg.value)
  svg.selectAll('*').remove()

  const seriesMap = store.indexSeries
  const syms = symbols.value
  if (!syms.length) return

  const tdSec = store.tradingDaySeconds || 3600

  const dailyBySymbol: Record<string, Map<number, number>> = {}
  for (const s of syms) {
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
  if (iW <= 0 || iH <= 0) return
  const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)

  const dayLabels = days.map((d) => `D${d}`)
  const x0 = d3.scaleBand().domain(dayLabels).range([0, iW]).padding(0.15)
  const x1 = d3.scaleBand().domain(syms).range([0, x0.bandwidth()]).padding(0.05)

  const maxVol = Math.max(1, ...syms.flatMap((s) => days.map((d) => dailyBySymbol[s]?.get(d) ?? 0)))
  const y = d3.scaleLinear().domain([0, maxVol * 1.1]).range([iH, 0])

  g.append('g').attr('transform', `translate(0,${iH})`)
    .call(d3.axisBottom(x0).tickValues(
      dayLabels.filter((_, i) => i % Math.max(1, Math.ceil(dayLabels.length / 15)) === 0),
    ))
    .call(styleAxis)
  g.append('g').call(d3.axisLeft(y).ticks(5).tickFormat((d) => fmtCn(Number(d), 0)))
    .call(styleAxis)

  const wrapEl = simWrap.value
  for (let si = 0; si < syms.length; si++) {
    const s = syms[si]
    const dayMap = dailyBySymbol[s] ?? new Map<number, number>()
    const color = colorOf(si)
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
        .style('cursor', 'crosshair')
        .on('mousemove', function (event: MouseEvent) {
          d3.select(this).attr('opacity', 1)
          if (!wrapEl) return
          const [px, py] = d3.pointer(event, wrapEl)
          const flip = px > wrapEl.clientWidth * 0.6
          tip.value = { show: true, x: flip ? px - 12 : px + 12, flip, y: py - 10, title: `${s} · D${day}`, value: fmtCn(vol, 2), color }
        })
        .on('mouseleave', function () {
          d3.select(this).attr('opacity', 0.8)
          tip.value.show = false
        })
    }
  }

  const legendG = g.append('g').attr('transform', `translate(0, -20)`)
  for (let i = 0; i < syms.length; i++) {
    const xOff = (i % 5) * 62
    const yOff = Math.floor(i / 5) * 13
    legendG.append('rect').attr('x', xOff).attr('y', yOff - 6).attr('width', 10).attr('height', 8)
      .attr('fill', colorOf(i)).attr('opacity', 0.8).attr('rx', 1)
    legendG.append('text').attr('x', xOff + 13).attr('y', yOff + 3)
      .attr('fill', colorOf(i)).attr('font-size', '10px').attr('font-family', 'monospace')
      .text(syms[i])
  }
}

const scheduleSim = useRafRender(renderVolumeSim, { el: () => volumeSimSvg.value })
let resizeObs: ResizeObserver | null = null
onMounted(() => {
  renderVolumeSim()
  if (volumeSimSvg.value) {
    resizeObs = new ResizeObserver(() => scheduleSim())
    resizeObs.observe(volumeSimSvg.value)
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.indexSeries, scheduleSim)
</script>

<template>
  <div class="card bv-card">
    <div class="card-title">指数成交量 <small class="scope">左：真实历史日成交额（拖动平移、滚轮缩放） · 右：仿真每日成交额（按指数拆分，悬浮看数值）</small></div>
    <div class="volume-split">
      <div class="split-block">
        <div class="split-title">历史日值 <span v-if="histHoverTime" class="hover-time">{{ histHoverTime }}</span></div>
        <div class="hist-legend">
          <span v-for="row in histLegend" :key="row.sym" class="lg-item">
            <i class="lg-dot" :style="{ background: row.color }" />{{ row.sym }}
            <b>{{ row.value == null ? '-' : fmtCn(row.value, 0) }}</b>
          </span>
        </div>
        <div ref="histContainer" class="hist-canvas" />
      </div>
      <div ref="simWrap" class="split-block sim-wrap">
        <div class="split-title">仿真每日成交量</div>
        <svg ref="volumeSimSvg" class="chart-svg split-svg" />
        <div v-show="tip.show" class="bar-tip" :style="{ left: `${tip.x}px`, top: `${tip.y}px`, transform: tip.flip ? 'translateX(-100%)' : 'none' }">
          <i class="lg-dot" :style="{ background: tip.color }" />{{ tip.title }} <b>{{ tip.value }}</b>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bv-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.scope {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-dim);
  margin-left: 6px;
}

.volume-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.split-block {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.split-title {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-sans);
  height: 16px;
  white-space: nowrap;
}

.hover-time {
  margin-left: 8px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.hist-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  height: 30px;
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.lg-item b {
  color: var(--heading);
  font-weight: 600;
  margin-left: 2px;
}

.lg-dot {
  display: inline-block;
  width: 8px;
  height: 3px;
  border-radius: 1px;
  margin-right: 3px;
  vertical-align: middle;
}

.hist-canvas {
  width: 100%;
  height: 250px;
  min-width: 0;
}

.sim-wrap {
  position: relative;
}

.chart-svg {
  width: 100%;
  min-height: 120px;
}

.split-svg {
  height: 284px;
}

.bar-tip {
  position: absolute;
  pointer-events: none;
  z-index: 5;
  padding: 4px 8px;
  border-radius: 4px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text);
  white-space: nowrap;
}

.bar-tip b {
  color: var(--heading);
  margin-left: 4px;
}
</style>
