<script setup lang="ts">
/** 多标的对比：每个标的一条收盘价线，默认以视窗首根为 100 归一化，可切换涨跌幅 / 原始价格。 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import {
  LineSeries,
  PriceScaleMode,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useMarketStore } from '@/stores/marketStore'
import { formatChartTime, makeTickMarkFormatter, makeTimeFormatter, simEpochFromDate, timeToNumber } from '@/utils/simTime'
import { useLightweightChart } from './useLightweightChart'
import { dailyBarsToChart, intradayBarsToChart, type Bar, type BarMode } from './barSource'

type CompareMode = 'indexed' | 'percent' | 'normal'

const props = withDefaults(
  defineProps<{
    symbols: string[]
    mode: BarMode
    height?: number
    title?: string
    showControls?: boolean
  }>(),
  { height: 260, title: '对比', showControls: true },
)

const PALETTE = ['#2962ff', '#ef5350', '#26a69a', '#ff9800', '#7c4dff', '#0288d1', '#e91e63', '#00897b', '#5c6bc0', '#78909c']
const MODES: Array<{ key: CompareMode; label: string }> = [
  { key: 'indexed', label: '归一100' },
  { key: 'percent', label: '涨跌%' },
  { key: 'normal', label: '价格' },
]

const store = useMarketStore()
const container = ref<HTMLElement>()
const compareMode = ref<CompareMode>('indexed')
const epoch = computed(() => simEpochFromDate(store.simStartDate))
const withClock = computed(() => props.mode === 'intraday')

const seriesData = computed<Record<string, Bar[]>>(() => {
  void store.barsVersion
  const out: Record<string, Bar[]> = {}
  for (const sym of props.symbols) {
    out[sym] =
      props.mode === 'daily'
        ? dailyBarsToChart(store.dailyBars[sym], epoch.value).filter((b) => !b.real)
        : intradayBarsToChart(store.intradayBars[sym], epoch.value, store.tradingDaySeconds)
  }
  return out
})

let chartApi: IChartApi | null = null
const lines = new Map<string, ISeriesApi<'Line'>>()
let fitted = false
let rafHandle: number | null = null

const hoverTime = ref('')
const hoverValues = ref<Record<string, number | null>>({})

const legendRows = computed(() =>
  props.symbols.map((sym, i) => {
    const arr = seriesData.value[sym] ?? []
    const last = arr.length ? arr[arr.length - 1].close : null
    const hovered = hoverValues.value[sym]
    return { sym, color: PALETTE[i % PALETTE.length], value: hovered ?? last }
  }),
)

const { getChart } = useLightweightChart(container, {
  options: () => ({
    localization: { timeFormatter: makeTimeFormatter(epoch.value, withClock.value) },
    timeScale: { tickMarkFormatter: makeTickMarkFormatter(epoch.value), timeVisible: withClock.value, secondsVisible: false },
  }),
  build: (chart) => {
    chartApi = chart
    chart.subscribeCrosshairMove(onCrosshair)
    syncSeries()
    applyMode()
  },
})

function onCrosshair(param: MouseEventParams) {
  const t = timeToNumber(param.time)
  if (t == null) {
    hoverTime.value = ''
    hoverValues.value = {}
    return
  }
  hoverTime.value = formatChartTime(epoch.value, t, withClock.value)
  const vals: Record<string, number | null> = {}
  for (const [sym, s] of lines.entries()) {
    const d = param.seriesData.get(s) as { value?: number } | undefined
    vals[sym] = d?.value ?? null
  }
  hoverValues.value = vals
}

function applyMode() {
  const mode =
    compareMode.value === 'indexed'
      ? PriceScaleMode.IndexedTo100
      : compareMode.value === 'percent'
        ? PriceScaleMode.Percentage
        : PriceScaleMode.Normal
  chartApi?.priceScale('right').applyOptions({ mode })
}

function syncSeries() {
  if (!chartApi) return
  const wanted = new Set(props.symbols)
  for (const [sym, s] of [...lines.entries()]) {
    if (!wanted.has(sym)) {
      chartApi.removeSeries(s)
      lines.delete(sym)
    }
  }
  props.symbols.forEach((sym, i) => {
    let s = lines.get(sym)
    if (!s) {
      s = chartApi!.addSeries(LineSeries, {
        color: PALETTE[i % PALETTE.length],
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
        title: sym,
        crosshairMarkerVisible: true,
      })
      lines.set(sym, s)
    }
    const data = (seriesData.value[sym] ?? []).map((b) => ({ time: b.time as UTCTimestamp, value: b.close }))
    s.setData(data)
  })
  if (!fitted && props.symbols.some((sym) => (seriesData.value[sym] ?? []).length > 1)) {
    chartApi.timeScale().fitContent()
    fitted = true
  }
}

function schedule() {
  if (rafHandle != null) cancelAnimationFrame(rafHandle)
  rafHandle = requestAnimationFrame(() => {
    rafHandle = null
    syncSeries()
  })
}

watch(seriesData, schedule)
watch(() => props.symbols, () => { fitted = false; schedule() })
watch(compareMode, applyMode)
watch(epoch, (e) => {
  getChart()?.applyOptions({
    localization: { timeFormatter: makeTimeFormatter(e, withClock.value) },
    timeScale: { tickMarkFormatter: makeTickMarkFormatter(e) },
  })
})

onBeforeUnmount(() => {
  if (rafHandle != null) cancelAnimationFrame(rafHandle)
})
</script>

<template>
  <div class="cmp">
    <div class="cmp-head">
      <div class="cmp-legend">
        <span class="cmp-title">{{ title }}</span>
        <span v-if="hoverTime" class="cmp-time">{{ hoverTime }}</span>
        <span v-for="row in legendRows" :key="row.sym" class="cmp-item">
          <i class="cmp-dot" :style="{ background: row.color }" />{{ row.sym }}
          <b>{{ row.value == null ? '-' : row.value.toFixed(2) }}</b>
        </span>
      </div>
      <div v-if="showControls" class="cmp-controls">
        <button
          v-for="m in MODES"
          :key="m.key"
          class="kc-btn"
          :class="{ active: compareMode === m.key }"
          @click="compareMode = m.key"
        >{{ m.label }}</button>
        <button class="kc-btn" @click="getChart()?.timeScale().fitContent()">复位</button>
      </div>
    </div>
    <div ref="container" class="cmp-canvas" :style="{ height: `${height}px` }" />
  </div>
</template>

<style scoped>
.cmp {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.cmp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
  min-height: 24px;
}

.cmp-legend {
  display: flex;
  align-items: baseline;
  flex-wrap: nowrap;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.cmp-title {
  font-weight: 700;
  color: var(--heading);
  font-size: 12px;
}

.cmp-time {
  color: var(--text-dim);
}

.cmp-item b {
  color: var(--heading);
  font-weight: 600;
  margin-left: 2px;
}

.cmp-dot {
  display: inline-block;
  width: 8px;
  height: 3px;
  border-radius: 1px;
  margin-right: 3px;
  vertical-align: middle;
}

.cmp-controls {
  display: inline-flex;
  gap: 3px;
}

.kc-btn {
  border: none;
  background: var(--surface-1);
  padding: 2px 7px;
  border-radius: 3px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  cursor: pointer;
}

.kc-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.cmp-canvas {
  width: 100%;
  min-width: 0;
}
</style>
