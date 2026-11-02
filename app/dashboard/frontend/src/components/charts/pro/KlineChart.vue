<script setup lang="ts">
/**
 * 行情主图：K 线（仿真段）+ 收盘价线（真实历史段）+ MA5/MA20，成交量副图，可选 RSI / MACD 副图。
 * 数据来自 store.dailyBars / store.intradayBars；1 Hz 全量状态到达时优先走 series.update 的增量路径。
 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useMarketStore } from '@/stores/marketStore'
import { fmtCn } from '@/utils/formatters'
import {
  formatChartTime,
  makeTickMarkFormatter,
  makeTimeFormatter,
  simEpochFromDate,
  timeToNumber,
} from '@/utils/simTime'
import { readChartTheme, useLightweightChart, withAlpha, type ChartTheme } from './useLightweightChart'
import { dailyBarsToChart, intradayBarsToChart, type Bar, type BarMode } from './barSource'
import { macd, rsi, sma, type Num } from './indicators'

export type PriceMode = 'normal' | 'log' | 'indexed' | 'percent'
export type SubIndicator = 'none' | 'rsi' | 'macd'
export interface OverlayPoint {
  time: number
  value: number
}

const props = withDefaults(
  defineProps<{
    symbol: string
    mode: BarMode
    /** 像素高度，或 'fill' 表示在 flex 列容器内撑满剩余高度 */
    height?: number | 'fill'
    title?: string
    overlay?: OverlayPoint[] | null
    overlayLabel?: string
    defaultPriceMode?: PriceMode
    defaultSub?: SubIndicator
    showControls?: boolean
  }>(),
  {
    height: 320,
    title: undefined,
    overlay: null,
    overlayLabel: '真实',
    defaultPriceMode: 'normal',
    defaultSub: 'rsi',
    showControls: true,
  },
)

const PRICE_MODES: Array<{ key: PriceMode; label: string; title: string }> = [
  { key: 'normal', label: '价格', title: '线性价格坐标' },
  { key: 'log', label: '对数', title: '对数价格坐标' },
  { key: 'indexed', label: '归一100', title: '以视窗首根为 100 归一化' },
  { key: 'percent', label: '涨跌%', title: '相对视窗首根的涨跌幅' },
]
const SUBS: Array<{ key: SubIndicator; label: string }> = [
  { key: 'none', label: '无' },
  { key: 'rsi', label: 'RSI14' },
  { key: 'macd', label: 'MACD' },
]
const MODE_MAP: Record<PriceMode, PriceScaleMode> = {
  normal: PriceScaleMode.Normal,
  log: PriceScaleMode.Logarithmic,
  indexed: PriceScaleMode.IndexedTo100,
  percent: PriceScaleMode.Percentage,
}
const MA5_COLOR = '#f5a623'
const MA20_COLOR = '#7c4dff'
const SIGNAL_COLOR = '#f5a623'

const store = useMarketStore()
const container = ref<HTMLElement>()
const priceMode = ref<PriceMode>(props.defaultPriceMode)
const subIndicator = ref<SubIndicator>(props.defaultSub)

const epoch = computed(() => simEpochFromDate(store.simStartDate))
const withClock = computed(() => props.mode === 'intraday')

const bars = computed<Bar[]>(() => {
  void store.barsVersion
  if (props.mode === 'daily') return dailyBarsToChart(store.dailyBars[props.symbol], epoch.value)
  return intradayBarsToChart(store.intradayBars[props.symbol], epoch.value, store.tradingDaySeconds)
})

// ── 图表对象（非响应式） ──
let chartApi: IChartApi | null = null
let theme: ChartTheme = readChartTheme()
let candles: ISeriesApi<'Candlestick'> | null = null
let realLine: ISeriesApi<'Line'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let ma5: ISeriesApi<'Line'> | null = null
let ma20: ISeriesApi<'Line'> | null = null
let overlaySeries: ISeriesApi<'Line'> | null = null
let subSeries: ISeriesApi<SeriesType>[] = []
let markers: ISeriesMarkersPluginApi<Time> | null = null

let lastLen = 0
let lastFirst: number | null = null
let fitted = false
let rafHandle: number | null = null
let timeIndex = new Map<number, number>()

// ── 图例（随十字光标） ──
const legend = ref({
  time: '',
  real: false,
  open: null as number | null,
  high: null as number | null,
  low: null as number | null,
  close: null as number | null,
  chg: null as number | null,
  chgPct: null as number | null,
  volume: null as number | null,
  ma5: null as number | null,
  ma20: null as number | null,
  sub: '' as string,
})
const chgClass = computed(() => {
  const c = legend.value.chg
  if (c == null || Math.abs(c) < 1e-12) return 'color-flat'
  return c > 0 ? 'color-up' : 'color-down'
})

function f2(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? '-' : v.toFixed(2)
}
function signed(v: number | null): string {
  if (v == null) return '-'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}`
}
function signedPct(v: number | null): string {
  if (v == null) return '-'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

// ── 构建 ──
const { getChart } = useLightweightChart(container, {
  options: () => ({
    localization: { timeFormatter: makeTimeFormatter(epoch.value, withClock.value) },
    timeScale: {
      tickMarkFormatter: makeTickMarkFormatter(epoch.value),
      timeVisible: withClock.value,
      secondsVisible: false,
    },
  }),
  build: (chart, th) => {
    chartApi = chart
    theme = th
    candles = chart.addSeries(
      CandlestickSeries,
      {
        upColor: th.up,
        downColor: th.down,
        borderVisible: false,
        wickUpColor: th.up,
        wickDownColor: th.down,
        priceLineVisible: true,
        lastValueVisible: true,
      },
      0,
    )
    realLine = chart.addSeries(
      LineSeries,
      { color: th.muted, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false },
      0,
    )
    ma5 = chart.addSeries(
      LineSeries,
      { color: MA5_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false },
      0,
    )
    ma20 = chart.addSeries(
      LineSeries,
      { color: MA20_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false },
      0,
    )
    volume = chart.addSeries(
      HistogramSeries,
      { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
      1,
    )
    chart.panes()[1]?.setHeight(70)
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.25, bottom: 0 } })
    ensureSubPane()
    ensureOverlay()
    applyPriceMode()
    chart.subscribeCrosshairMove(onCrosshair)
    applyData(true)
  },
  onTheme: (th) => {
    theme = th
    candles?.applyOptions({ upColor: th.up, downColor: th.down, wickUpColor: th.up, wickDownColor: th.down })
    realLine?.applyOptions({ color: th.muted })
    overlaySeries?.applyOptions({ color: th.muted })
    applyData(true)
  },
})

function onCrosshair(param: MouseEventParams) {
  updateLegend(param)
}

// ── 副图 ──
function clearSub() {
  if (!chartApi) return
  for (const s of subSeries) {
    try {
      chartApi.removeSeries(s)
    } catch {
      /* 已被移除 */
    }
  }
  subSeries = []
  try {
    if (chartApi.panes().length > 2) chartApi.removePane(2)
  } catch {
    /* 面板已随 series 移除 */
  }
}

function ensureSubPane() {
  clearSub()
  if (!chartApi) return
  if (subIndicator.value === 'rsi') {
    const s = chartApi.addSeries(
      LineSeries,
      { color: theme.accent, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'RSI14' },
      2,
    )
    s.createPriceLine({ price: 70, color: theme.up, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: '' })
    s.createPriceLine({ price: 30, color: theme.down, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: '' })
    subSeries = [s]
  } else if (subIndicator.value === 'macd') {
    const hist = chartApi.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, 2)
    const line = chartApi.addSeries(
      LineSeries,
      { color: theme.accent, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'MACD' },
      2,
    )
    const signal = chartApi.addSeries(
      LineSeries,
      { color: SIGNAL_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: 'Signal' },
      2,
    )
    subSeries = [hist, line, signal]
  }
  if (subSeries.length) chartApi.panes()[2]?.setHeight(80)
}

// ── 真实曲线叠加（预测拟合模式） ──
function ensureOverlay() {
  if (!chartApi) return
  const pts = props.overlay
  if (pts && pts.length) {
    if (!overlaySeries) {
      overlaySeries = chartApi.addSeries(
        LineSeries,
        {
          color: theme.muted,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: true,
          title: props.overlayLabel,
        },
        0,
      )
    }
    const data: Array<{ time: UTCTimestamp; value: number }> = []
    let lastT = -Infinity
    for (const p of [...pts].sort((a, b) => a.time - b.time)) {
      if (!Number.isFinite(p.value)) continue
      if (p.time <= lastT) {
        data[data.length - 1] = { time: p.time as UTCTimestamp, value: p.value }
        continue
      }
      data.push({ time: p.time as UTCTimestamp, value: p.value })
      lastT = p.time
    }
    overlaySeries.setData(data)
  } else if (overlaySeries) {
    try {
      chartApi.removeSeries(overlaySeries)
    } catch {
      /* noop */
    }
    overlaySeries = null
  }
}

function applyPriceMode() {
  candles?.priceScale().applyOptions({ mode: MODE_MAP[priceMode.value] })
}

// ── 数据 ──
interface SubData {
  rsi?: Num[]
  macd?: ReturnType<typeof macd>
}

function computeSub(closes: number[]): SubData {
  if (subIndicator.value === 'rsi') return { rsi: rsi(closes, 14) }
  if (subIndicator.value === 'macd') return { macd: macd(closes, 12, 26, 9) }
  return {}
}

function toCandle(b: Bar) {
  return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }
}

function volumeColor(b: Bar): string {
  const up = b.close >= b.open
  return withAlpha(up ? theme.up : theme.down, b.real ? 0.28 : 0.55)
}

function toVolume(b: Bar) {
  return { time: b.time, value: b.volume, color: volumeColor(b) }
}

function linePoint(time: UTCTimestamp, v: Num) {
  return v == null || !Number.isFinite(v) ? { time } : { time, value: v }
}

function histPoint(time: UTCTimestamp, v: Num) {
  if (v == null || !Number.isFinite(v)) return { time }
  return { time, value: v, color: withAlpha(v >= 0 ? theme.up : theme.down, 0.6) }
}

function setSubData(all: Bar[], sub: SubData) {
  if (sub.rsi && subSeries[0]) {
    subSeries[0].setData(all.map((b, i) => linePoint(b.time, sub.rsi![i])))
  } else if (sub.macd && subSeries.length === 3) {
    subSeries[0].setData(all.map((b, i) => histPoint(b.time, sub.macd!.hist[i])))
    subSeries[1].setData(all.map((b, i) => linePoint(b.time, sub.macd!.macd[i])))
    subSeries[2].setData(all.map((b, i) => linePoint(b.time, sub.macd!.signal[i])))
  }
}

function updateSubPoint(all: Bar[], i: number, sub: SubData) {
  const b = all[i]
  if (sub.rsi && subSeries[0]) {
    subSeries[0].update(linePoint(b.time, sub.rsi[i]))
  } else if (sub.macd && subSeries.length === 3) {
    subSeries[0].update(histPoint(b.time, sub.macd.hist[i]))
    subSeries[1].update(linePoint(b.time, sub.macd.macd[i]))
    subSeries[2].update(linePoint(b.time, sub.macd.signal[i]))
  }
}

function updateMarkers(all: Bar[]) {
  if (!candles) return
  const firstSim = props.mode === 'daily' ? all.find((b) => !b.real) : undefined
  const hasReal = all.some((b) => b.real)
  const list = firstSim && hasReal
    ? [{ time: firstSim.time as Time, position: 'belowBar' as const, color: theme.accent, shape: 'arrowUp' as const, text: '仿真起点' }]
    : []
  if (!markers) markers = createSeriesMarkers(candles, list)
  else markers.setMarkers(list)
}

function applyData(force = false) {
  if (!chartApi || !candles || !realLine || !volume || !ma5 || !ma20) return
  const all = bars.value
  if (!all.length) {
    candles.setData([])
    realLine.setData([])
    volume.setData([])
    ma5.setData([])
    ma20.setData([])
    for (const s of subSeries) s.setData([])
    lastLen = 0
    lastFirst = null
    timeIndex = new Map()
    updateLegend(null)
    return
  }

  const closes = all.map((b) => b.close)
  const m5 = sma(closes, 5)
  const m20 = sma(closes, 20)
  const sub = computeSub(closes)

  const incremental =
    !force && lastLen > 0 && all.length >= lastLen && all.length - lastLen <= 1 && all[0].time === lastFirst

  if (incremental) {
    const idxs = all.length === lastLen ? [all.length - 1] : [all.length - 2, all.length - 1]
    for (const i of idxs) {
      if (i < 0) continue
      const b = all[i]
      if (b.real) realLine.update({ time: b.time, value: b.close })
      else candles.update(toCandle(b))
      volume.update(toVolume(b))
      ma5.update(linePoint(b.time, m5[i]))
      ma20.update(linePoint(b.time, m20[i]))
      updateSubPoint(all, i, sub)
      timeIndex.set(b.time, i)
    }
  } else {
    candles.setData(all.filter((b) => !b.real).map(toCandle))
    realLine.setData(all.filter((b) => b.real).map((b) => ({ time: b.time, value: b.close })))
    volume.setData(all.map(toVolume))
    ma5.setData(all.map((b, i) => linePoint(b.time, m5[i])))
    ma20.setData(all.map((b, i) => linePoint(b.time, m20[i])))
    setSubData(all, sub)
    updateMarkers(all)
    timeIndex = new Map(all.map((b, i) => [b.time as number, i]))
    if (!fitted) {
      chartApi.timeScale().fitContent()
      fitted = true
    }
  }
  lastLen = all.length
  lastFirst = all[0].time
  cachedMa = { m5, m20, sub }
  updateLegend(null)
}

let cachedMa: { m5: Num[]; m20: Num[]; sub: SubData } = { m5: [], m20: [], sub: {} }

function updateLegend(param: MouseEventParams | null) {
  const all = bars.value
  if (!all.length) {
    legend.value = { ...legend.value, time: '', close: null, open: null, high: null, low: null, chg: null, chgPct: null, volume: null, ma5: null, ma20: null, sub: '' }
    return
  }
  let idx = all.length - 1
  const t = param ? timeToNumber(param.time) : null
  if (t != null) {
    const found = timeIndex.get(t)
    if (found != null) idx = found
    else return
  }
  const b = all[idx]
  const prevClose = idx > 0 ? all[idx - 1].close : b.open
  const chg = b.close - prevClose
  const chgPct = Math.abs(prevClose) > 1e-12 ? (chg / prevClose) * 100 : null
  let subText = ''
  if (cachedMa.sub.rsi) {
    const v = cachedMa.sub.rsi[idx]
    subText = v == null ? '' : `RSI ${v.toFixed(1)}`
  } else if (cachedMa.sub.macd) {
    const mv = cachedMa.sub.macd.macd[idx]
    const sv = cachedMa.sub.macd.signal[idx]
    if (mv != null && sv != null) subText = `MACD ${mv.toFixed(3)} / ${sv.toFixed(3)}`
  }
  legend.value = {
    time: formatChartTime(epoch.value, b.time, withClock.value),
    real: b.real,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    chg,
    chgPct,
    volume: b.volume,
    ma5: cachedMa.m5[idx] ?? null,
    ma20: cachedMa.m20[idx] ?? null,
    sub: subText,
  }
}

function schedule(force = false) {
  if (rafHandle != null) cancelAnimationFrame(rafHandle)
  rafHandle = requestAnimationFrame(() => {
    rafHandle = null
    applyData(force)
  })
}

function resetView() {
  getChart()?.timeScale().fitContent()
}

watch(bars, () => schedule(false))
watch(
  () => props.symbol,
  () => {
    fitted = false
    lastLen = 0
    schedule(true)
  },
)
watch(
  () => props.mode,
  () => {
    const chart = getChart()
    if (chart) {
      chart.applyOptions({
        localization: { timeFormatter: makeTimeFormatter(epoch.value, withClock.value) },
        timeScale: { tickMarkFormatter: makeTickMarkFormatter(epoch.value), timeVisible: withClock.value },
      })
    }
    fitted = false
    schedule(true)
  },
)
watch(epoch, (e) => {
  getChart()?.applyOptions({
    localization: { timeFormatter: makeTimeFormatter(e, withClock.value) },
    timeScale: { tickMarkFormatter: makeTickMarkFormatter(e) },
  })
  fitted = false
  schedule(true)
})
watch(priceMode, applyPriceMode)
watch(
  () => props.defaultPriceMode,
  (m) => {
    priceMode.value = m
  },
)
watch(subIndicator, () => {
  ensureSubPane()
  schedule(true)
})
watch(
  () => props.overlay,
  () => ensureOverlay(),
)

onBeforeUnmount(() => {
  if (rafHandle != null) cancelAnimationFrame(rafHandle)
})
</script>

<template>
  <div class="kline">
    <div class="kline-head">
      <div class="kline-legend">
        <span class="lg-title">{{ title ?? symbol }}</span>
        <span class="lg-time">{{ legend.time }}</span>
        <template v-if="legend.close != null">
          <template v-if="!legend.real">
            <span>开 <b>{{ f2(legend.open) }}</b></span>
            <span>高 <b>{{ f2(legend.high) }}</b></span>
            <span>低 <b>{{ f2(legend.low) }}</b></span>
          </template>
          <span>收 <b :class="chgClass">{{ f2(legend.close) }}</b></span>
          <span :class="chgClass">{{ signed(legend.chg) }} ({{ signedPct(legend.chgPct) }})</span>
          <span>量 <b>{{ fmtCn(legend.volume) }}</b></span>
          <span class="lg-ma5">MA5 {{ f2(legend.ma5) }}</span>
          <span class="lg-ma20">MA20 {{ f2(legend.ma20) }}</span>
          <span v-if="legend.sub" class="lg-sub">{{ legend.sub }}</span>
          <span v-if="legend.real" class="lg-real">历史收盘价</span>
        </template>
        <span v-else class="lg-empty">暂无数据</span>
      </div>
      <div v-if="showControls" class="kline-controls">
        <button
          v-for="m in PRICE_MODES"
          :key="m.key"
          class="kc-btn"
          :class="{ active: priceMode === m.key }"
          :title="m.title"
          @click="priceMode = m.key"
        >{{ m.label }}</button>
        <span class="kc-sep" />
        <button
          v-for="s in SUBS"
          :key="s.key"
          class="kc-btn"
          :class="{ active: subIndicator === s.key }"
          @click="subIndicator = s.key"
        >{{ s.label }}</button>
        <span class="kc-sep" />
        <button class="kc-btn" title="回到全览" @click="resetView">复位</button>
      </div>
    </div>
    <div
      ref="container"
      class="kline-canvas"
      :class="{ 'kline-fill': height === 'fill' }"
      :style="height === 'fill' ? undefined : { height: `${height}px` }"
    />
  </div>
</template>

<style scoped>
.kline {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.kline:has(.kline-fill) {
  flex: 1 1 auto;
  min-height: 0;
}

.kline-fill {
  flex: 1 1 auto;
  min-height: 280px;
}

.kline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
  min-height: 24px;
}

.kline-legend {
  display: flex;
  align-items: baseline;
  flex-wrap: nowrap;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.kline-legend b {
  color: var(--heading);
  font-weight: 600;
}

.lg-title {
  font-weight: 700;
  color: var(--heading);
  font-size: 12px;
}

.lg-time {
  color: var(--text-dim);
}

.lg-ma5 { color: #f5a623; }
.lg-ma20 { color: #7c4dff; }
.lg-sub { color: var(--accent); }

.lg-real,
.lg-empty {
  color: var(--text-dim);
  font-size: 10px;
}

.kline-controls {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
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
  transition: all 0.12s;
}

.kc-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.kc-btn:hover:not(.active) {
  background: var(--surface-2);
}

.kc-sep {
  width: 1px;
  height: 12px;
  background: var(--border-light);
  margin: 0 3px;
}

.kline-canvas {
  width: 100%;
  min-width: 0;
  position: relative;
}
</style>
