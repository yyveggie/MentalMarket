<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtPct } from '@/utils/formatters'

const store = useMarketStore()
const broadSvg = ref<SVGSVGElement>()

const broad = computed(() => store.broadMarket)
const currentTradingDay = computed(() => Math.max(1, Number(store.tradingDay || 1)))
const includeClosedDaysForMetrics = computed(() => Boolean(store.metrics?.include_closed_days_for_metrics))

type SortKey = 'symbol' | 'pctChg' | 'price' | 'volume'
const sortKey = ref<SortKey>('pctChg')
const sortAsc = ref(false)
const selectedSymbol = ref<string | null>(null)
const broadViewMode = ref<'today' | 'history'>('today')
const broadViewOffset = ref(0)
const broadWindowSize = ref<number | null>(null)
const broadDragPx = ref(0)
const broadVisibleStartDate = ref<string | null>(null)
const broadVisibleEndDate = ref<string | null>(null)

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    sortAsc.value = key === 'symbol'
  }
}

function sortArrow(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortAsc.value ? ' ▲' : ' ▼'
}

const sortOptions = [
  { key: 'symbol' as SortKey, label: '代码' },
  { key: 'pctChg' as SortKey, label: '涨跌' },
  { key: 'price' as SortKey, label: '价格' },
  { key: 'volume' as SortKey, label: '成交量' },
]

function simDateToTradingDay(simDate: string, tradingDaySeconds: number): number | null {
  if (!simDate.startsWith('SIM_')) return null
  const m = simDate.match(/_T(\d+(?:\.\d+)?)$/)
  if (!m) return null
  const simTime = Number(m[1])
  if (!Number.isFinite(simTime)) return null
  return Math.floor(simTime / Math.max(1e-6, tradingDaySeconds)) + 1
}

function firstNonNull(values: Array<number | null>): number | null {
  for (const v of values) {
    if (v !== null && Number.isFinite(v)) return v
  }
  return null
}

function normalizeSeries(values: Array<number | null>, base: number | null): Array<number | null> {
  if (base === null || Math.abs(base) < 1e-12) {
    return values.map(() => null)
  }
  return values.map((v) => (v === null ? null : (v / base) * 100))
}

function sign(v: number): number {
  if (v > 1e-12) return 1
  if (v < -1e-12) return -1
  return 0
}

function pearsonCorr(xs: number[], ys: number[]): number | null {
  const n = Math.min(xs.length, ys.length)
  if (n < 2) return null
  const x = xs.slice(0, n)
  const y = ys.slice(0, n)
  const mx = x.reduce((s, v) => s + v, 0) / n
  const my = y.reduce((s, v) => s + v, 0) / n
  let num = 0
  let dx = 0
  let dy = 0
  for (let i = 0; i < n; i++) {
    const vx = x[i] - mx
    const vy = y[i] - my
    num += vx * vy
    dx += vx * vx
    dy += vy * vy
  }
  if (dx <= 0 || dy <= 0) return null
  return num / Math.sqrt(dx * dy)
}

function mean(values: number[]): number | null {
  if (!values.length) return null
  return values.reduce((s, v) => s + v, 0) / values.length
}

function computeQlike(
  realVar: number[],
  simVar: number[],
  eps = 1e-8,
  upperTailQuantile = 0.95,
): number | null {
  const n = Math.min(realVar.length, simVar.length)
  if (n < 2) return null
  const losses: number[] = []
  for (let i = 0; i < n; i++) {
    const rv = Math.max(eps, realVar[i])
    const hv = Math.max(eps, simVar[i])
    const ratio = rv / hv
    losses.push(ratio - Math.log(ratio) - 1.0)
  }

  if (losses.length >= 5) {
    const sorted = [...losses].sort((a, b) => a - b)
    const q = Math.max(0.5, Math.min(0.999, upperTailQuantile))
    const capIdx = Math.floor((sorted.length - 1) * q)
    const cap = sorted[capIdx]
    for (let i = 0; i < losses.length; i++) {
      if (losses[i] > cap) losses[i] = cap
    }
  }

  return mean(losses)
}

function computeLogRmse(realVar: number[], simVar: number[], eps = 1e-12): number | null {
  const n = Math.min(realVar.length, simVar.length)
  if (n < 2) return null
  const sqErr: number[] = []
  for (let i = 0; i < n; i++) {
    const lr = Math.log(Math.max(eps, realVar[i]))
    const ls = Math.log(Math.max(eps, simVar[i]))
    const e = lr - ls
    sqErr.push(e * e)
  }
  const mse = mean(sqErr)
  return mse === null ? null : Math.sqrt(mse)
}

function computeMincerZarnowitz(realVar: number[], simVar: number[]): {
  alpha: number | null
  beta: number | null
  r2: number | null
  waldChi2: number | null
  pValue: number | null
  n: number
} {
  const n = Math.min(realVar.length, simVar.length)
  if (n < 3) {
    return { alpha: null, beta: null, r2: null, waldChi2: null, pValue: null, n }
  }

  const x = simVar.slice(0, n)
  const y = realVar.slice(0, n)

  const sx = x.reduce((s, v) => s + v, 0)
  const sy = y.reduce((s, v) => s + v, 0)
  const sxx = x.reduce((s, v) => s + v * v, 0)
  const sxy = x.reduce((s, v, i) => s + v * y[i], 0)

  const den = n * sxx - sx * sx
  if (Math.abs(den) <= 1e-18) {
    return { alpha: null, beta: null, r2: null, waldChi2: null, pValue: null, n }
  }

  const beta = (n * sxy - sx * sy) / den
  const alpha = (sy - beta * sx) / n

  const yBar = sy / n
  let sse = 0.0
  let sst = 0.0
  for (let i = 0; i < n; i++) {
    const yHat = alpha + beta * x[i]
    const e = y[i] - yHat
    sse += e * e
    const dy = y[i] - yBar
    sst += dy * dy
  }
  const r2 = sst > 1e-18 ? 1.0 - sse / sst : null

  if (n <= 2) {
    return { alpha, beta, r2, waldChi2: null, pValue: null, n }
  }

  const sigma2 = sse / (n - 2)
  const inv00 = sxx / den
  const inv01 = -sx / den
  const inv10 = -sx / den
  const inv11 = n / den

  const cov00 = sigma2 * inv00
  const cov01 = sigma2 * inv01
  const cov10 = sigma2 * inv10
  const cov11 = sigma2 * inv11

  const c0 = alpha
  const c1 = beta - 1.0

  const covDet = cov00 * cov11 - cov01 * cov10
  if (Math.abs(covDet) <= 1e-24) {
    return { alpha, beta, r2, waldChi2: null, pValue: null, n }
  }

  const ic00 = cov11 / covDet
  const ic01 = -cov01 / covDet
  const ic10 = -cov10 / covDet
  const ic11 = cov00 / covDet
  const waldChi2 = c0 * (ic00 * c0 + ic01 * c1) + c1 * (ic10 * c0 + ic11 * c1)

  const pValue = waldChi2 >= 0 ? Math.exp(-0.5 * waldChi2) : null
  return { alpha, beta, r2, waldChi2, pValue, n }
}

function compactDateLabel(dateStr: string | null | undefined): string {
  if (!dateStr) return '--'
  const s = String(dateStr)
  // "Day N" 格式直接返回
  if (s.startsWith('Day ')) return s
  return s.length >= 10 ? s.slice(5, 10) : s
}

function calendarDateByDay(day: number): string | null {
  const row = store.realCurveCalendar.find((item) => item.day === day)
  return row?.date ?? null
}

function resolveDisplayDate(rawDate: string): string | null {
  const day = simDateToTradingDay(rawDate, store.tradingDaySeconds)
  if (day !== null) {
    const calDate = calendarDateByDay(day)
    if (calDate) return calDate
    return `Day ${day}`
  }
  return rawDate || null
}

function collectClosedSegments(flags: boolean[]): Array<{ start: number; end: number }> {
  const segments: Array<{ start: number; end: number }> = []
  let start = -1
  for (let i = 0; i < flags.length; i++) {
    if (flags[i]) {
      if (start < 0) start = i
    } else if (start >= 0) {
      segments.push({ start, end: i - 1 })
      start = -1
    }
  }
  if (start >= 0) segments.push({ start, end: flags.length - 1 })
  return segments
}

function paintClosedBands(
  g: d3.Selection<SVGGElement, unknown, null, undefined>,
  x: d3.ScaleLinear<number, number>,
  iW: number,
  iH: number,
  pointCount: number,
  flags: boolean[],
) {
  if (pointCount < 2 || flags.length === 0) return
  const segments = collectClosedSegments(flags.slice(0, pointCount))
  if (!segments.length) return

  const step = iW / Math.max(1, pointCount - 1)
  const layer = g.append('g').attr('class', 'closed-bands')
  for (const seg of segments) {
    const x0 = seg.start <= 0 ? 0 : Math.max(0, x(seg.start - 1))
    const x1 = seg.end === pointCount - 1
      ? iW
      : (seg.end <= 0 ? Math.min(iW, step) : Math.min(iW, x(seg.end)))
    if (x1 <= x0) continue
    layer.append('rect')
      .attr('x', x0)
      .attr('y', 0)
      .attr('width', x1 - x0)
      .attr('height', iH)
      .attr('fill', '#cbd5e1')
      .attr('opacity', 0.1)
      .attr('pointer-events', 'none')
  }
}

const indexData = computed(() => {
  const calendarByDay = new Map<number, { date: string; market_status: string }>()
  for (const item of store.realCurveCalendar) {
    if (item.day > 0 && item.date) {
      calendarByDay.set(item.day, { date: item.date, market_status: item.market_status ?? '' })
    }
  }
  const dayByDate = new Map<string, number>()
  for (const [day, item] of calendarByDay.entries()) {
    if (item.date) dayByDate.set(item.date, day)
  }
  const currentDay = currentTradingDay.value

  const symbols = Array.from(new Set([...Object.keys(store.realIndexSeries), ...Object.keys(store.indexSeries)])).filter(s => s !== '__BROAD__')
  const items = symbols.map((symbol) => {
    const simRows = store.indexSeries[symbol] ?? []
    const realRows = store.realIndexSeries[symbol] ?? []

    const simCloseByDay = new Map<number, number>()
    for (const row of simRows) {
      const rawDate = String(row.date ?? '')
      const dayFromSim = simDateToTradingDay(rawDate, store.tradingDaySeconds)
      const day = dayFromSim ?? dayByDate.get(rawDate) ?? null
      const close = Number(row.close)
      if (day !== null && day > 0 && Number.isFinite(close)) {
        simCloseByDay.set(day, close)
      }
    }

    const realByDate = new Map<string, { close: number; isClosed: boolean }>()
    for (const r of realRows) {
      const date = String(r.date ?? '')
      if (!date) continue
      realByDate.set(date, { close: Number(r.close), isClosed: Boolean(r.is_closed) })
    }

    const allRealRows: Array<{ day: number; date: string; close: number; isClosed: boolean }> = []
    const allDays = Array.from(calendarByDay.keys()).sort((a, b) => a - b)
    for (const day of allDays) {
      const cal = calendarByDay.get(day)
      if (!cal) continue
      const real = realByDate.get(cal.date)
      if (!real) continue
      allRealRows.push({ day, date: cal.date, close: real.close, isClosed: real.isClosed })
    }

    const sortedSimEntries = Array.from(simCloseByDay.entries()).sort((a, b) => a[0] - b[0])

    const realSparklineRaw: Array<number | null> = []
    const simSparklineRaw: Array<number | null> = []
    const simSparklineFullRaw: Array<number | null> = []
    let closedDays = 0
    const maxSimDay = sortedSimEntries.length > 0 ? sortedSimEntries[sortedSimEntries.length - 1][0] : 0
    let lastOpenSimForDisplay: number | null = null

    const hasRealCalendar = allRealRows.length > 0

    if (hasRealCalendar) {
      for (const row of allRealRows) {
        realSparklineRaw.push(row.close)
        if (row.isClosed) closedDays += 1
        const simCloseRaw = simCloseByDay.get(row.day) ?? null
        if (!row.isClosed && simCloseRaw !== null) lastOpenSimForDisplay = simCloseRaw
        const simCarryForDisplay = row.isClosed ? lastOpenSimForDisplay : (simCloseRaw ?? lastOpenSimForDisplay)
        simSparklineRaw.push(row.day <= currentDay ? simCarryForDisplay : null)
        simSparklineFullRaw.push(row.day <= maxSimDay ? simCarryForDisplay : null)
      }
    } else {
      for (const [day, close] of sortedSimEntries) {
        simSparklineFullRaw.push(close)
        simSparklineRaw.push(day <= currentDay ? close : null)
      }
    }

    const progressiveRows = allRealRows.filter((row) => row.day <= currentDay)

    const realBase = firstNonNull(realSparklineRaw)
    const simBase = firstNonNull(simSparklineFullRaw)
    const normRealSparkline = normalizeSeries(realSparklineRaw, realBase)
    const normSimSparkline = normalizeSeries(simSparklineFullRaw, simBase)

    const normValid = [...normRealSparkline, ...normSimSparkline].filter((v): v is number => v !== null)
    const normHigh = normValid.length ? Math.max(...normValid) : 101
    const normLow = normValid.length ? Math.min(...normValid) : 99

    const simValid = simSparklineFullRaw.filter((v): v is number => v !== null)
    const realValid = realSparklineRaw.filter((v): v is number => v !== null)
    const allValid = [...realValid, ...simValid]
    const high = allValid.length ? Math.max(...allValid) : 0
    const low = allValid.length ? Math.min(...allValid) : 0
    const realHigh = realValid.length ? Math.max(...realValid) : 0
    const realLow = realValid.length ? Math.min(...realValid) : 0
    const simHigh = simValid.length ? Math.max(...simValid) : 0
    const simLow = simValid.length ? Math.min(...simValid) : 0

    const aligned: Array<[number, number, number]> = []
    for (const row of progressiveRows) {
      const eligible = includeClosedDaysForMetrics.value || !row.isClosed
      if (!eligible) continue
      const simClose = simCloseByDay.get(row.day)
      if (simClose == null) continue
      aligned.push([row.day, row.close, simClose])
    }

    let predictionSameDaySampleCount = 0
    let predictionSameDayMatchCount = 0
    let predictionForward1SampleCount = 0
    let predictionForward1MatchCount = 0
    const realReturns: number[] = []
    const simReturns: number[] = []

    for (let i = 2; i < aligned.length; i++) {
      const [dayPrev2, , simPrev2] = aligned[i - 2]
      const [dayPrev1, realPrev, simPrev1] = aligned[i - 1]
      const [dayCur, realCur] = aligned[i]

      if (!(dayPrev1 === dayPrev2 + 1 && dayCur === dayPrev1 + 1)) continue

      const realDelta = realCur - realPrev
      const simPredDelta = simPrev1 - simPrev2
      const realDir = sign(realDelta)
      const simPredDir = sign(simPredDelta)

      if (realDir === 0 && simPredDir === 0) continue
      if (realDir === simPredDir) predictionForward1MatchCount += 1
      predictionForward1SampleCount += 1
    }

    for (let i = 1; i < aligned.length; i++) {
      const [dayPrev, realPrev, simPrev] = aligned[i - 1]
      const [dayCur, realCur, simCur] = aligned[i]
      if (dayCur !== dayPrev + 1) continue

      const realDelta = realCur - realPrev
      const simDelta = simCur - simPrev

      const realDir = sign(realDelta)
      const simDir = sign(simDelta)
      if (!(realDir === 0 && simDir === 0)) {
        if (realDir === simDir) predictionSameDayMatchCount += 1
        predictionSameDaySampleCount += 1
      }

      const realDen = Math.abs(realPrev) > 1e-9 ? realPrev : 1.0
      const simDen = Math.abs(simPrev) > 1e-9 ? simPrev : 1.0
      realReturns.push(realDelta / realDen)
      simReturns.push(simDelta / simDen)
    }

    const predictionSameDayAccuracyPct = predictionSameDaySampleCount > 0
      ? (predictionSameDayMatchCount / predictionSameDaySampleCount) * 100
      : null

    const predictionForward1AccuracyPct = predictionForward1SampleCount > 0
      ? (predictionForward1MatchCount / predictionForward1SampleCount) * 100
      : null

    const corr = pearsonCorr(realReturns, simReturns)
    const volatilityFitPct = corr === null ? null : (Math.max(-1, Math.min(1, corr)) + 1) * 50

    const realVar = realReturns.map((r) => r * r)
    const simVar = simReturns.map((r) => r * r)
    const qlike = computeQlike(realVar, simVar)
    const logRmse = computeLogRmse(realVar, simVar)
    const mz = computeMincerZarnowitz(realVar, simVar)

    const lastSimRow = simRows[simRows.length - 1]
    const lastReal = realRows[realRows.length - 1]
    const price = (simValid.length ? simValid[simValid.length - 1] : null) ?? lastSimRow?.close ?? lastReal?.close ?? 0
    const pctChg = lastSimRow?.pct_chg ?? 0
    const totalVol = simRows.reduce((s, r) => s + (r.volume ?? 0), 0)
    const firstDate = allRealRows.length > 0
      ? allRealRows[0].date
      : (sortedSimEntries.length > 0 ? `Day ${sortedSimEntries[0][0]}` : null)
    const lastDate = allRealRows.length > 0
      ? allRealRows[allRealRows.length - 1].date
      : (sortedSimEntries.length > 0 ? `Day ${sortedSimEntries[sortedSimEntries.length - 1][0]}` : null)

    return {
      symbol,
      price,
      pctChg,
      volume: totalVol,
      high,
      low,
      realHigh,
      realLow,
      simHigh,
      simLow,
      normHigh,
      normLow,
      closedDays,
      closedMask: allRealRows.map((row) => row.isClosed),
      realSparklineRaw,
      simSparklineRaw: simSparklineFullRaw,
      normRealSparkline,
      normSimSparkline,
      predictionSameDayAccuracyPct,
      predictionSameDaySampleCount,
      predictionForward1AccuracyPct,
      predictionForward1SampleCount,
      predictionAccuracyPct: predictionForward1AccuracyPct,
      predictionSampleCount: predictionForward1SampleCount,
      volatilityFitPct,
      fitSampleCount: realReturns.length,
      qlike,
      logRmse,
      mzAlpha: mz.alpha,
      mzBeta: mz.beta,
      mzR2: mz.r2,
      mzWaldChi2: mz.waldChi2,
      mzPValue: mz.pValue,
      mzSampleCount: mz.n,
      firstDate,
      lastDate,
    }
  })

  const key = sortKey.value
  const dir = sortAsc.value ? 1 : -1
  items.sort((a, b) => {
    const av = a[key] ?? 0
    const bv = b[key] ?? 0
    if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * dir
    return ((av as number) - (bv as number)) * dir
  })
  return items
})

const topIndexData = computed(() => indexData.value.slice(0, 10))
const leftColumnData = computed(() => topIndexData.value.slice(0, 5))
const rightColumnData = computed(() => topIndexData.value.slice(5, 10))

const selectedIndexData = computed(() => {
  if (!selectedSymbol.value) return null
  return indexData.value.find((item) => item.symbol === selectedSymbol.value) ?? null
})

const centerTitle = computed(() => selectedIndexData.value?.symbol ?? (broad.value?.name ?? '大盘(加权)'))
const centerValue = computed(() => selectedIndexData.value?.price ?? broad.value?.value ?? null)
const centerPct = computed(() => selectedIndexData.value?.pctChg ?? broad.value?.pct_chg ?? null)

const broadDateRange = computed(() => {
  const rows = store.realCurveCalendar
    .filter((item) => item.day > 0 && item.date)
    .sort((a, b) => a.day - b.day)
  if (!rows.length) {
    return { start: null as string | null, end: null as string | null }
  }

  const end = rows[rows.length - 1].date

  return {
    start: rows[0].date,
    end,
  }
})

const centerStartDate = computed(() => selectedIndexData.value?.firstDate ?? broadDateRange.value.start)
const centerEndDate = computed(() => selectedIndexData.value?.lastDate ?? broadDateRange.value.end)
const visibleStartDate = computed(() => selectedIndexData.value?.firstDate ?? broadVisibleStartDate.value ?? centerStartDate.value)
const visibleEndDate = computed(() => selectedIndexData.value?.lastDate ?? broadVisibleEndDate.value ?? centerEndDate.value)

function toggleCenterSymbol(symbol: string) {
  selectedSymbol.value = selectedSymbol.value === symbol ? null : symbol
}

function isCenterSymbol(symbol: string): boolean {
  return selectedSymbol.value === symbol
}

function onIndexCardKeydown(event: KeyboardEvent, symbol: string) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    toggleCenterSymbol(symbol)
  }
}

function resetBroadToToday() {
  broadViewMode.value = 'today'
  broadViewOffset.value = 0
  broadWindowSize.value = null
  broadDragPx.value = 0
  renderCenterChart()
}

function sparklinePoints(prices: Array<number | null>, min: number, max: number): string {
  const points: string[] = []
  const validCount = prices.filter((v): v is number => v !== null).length
  if (validCount < 2) return ''
  const range = max - min
  const isFlat = Math.abs(range) < 1e-12
  for (let i = 0; i < prices.length; i++) {
    const p = prices[i]
    if (p === null) continue
    const x = (i / Math.max(1, prices.length - 1)) * 80
    const y = isFlat ? 11 : 20 - ((p - min) / range) * 18
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return points.join(' ')
}

function renderCenterChart() {
  if (!broadSvg.value) return
  const svg = d3.select(broadSvg.value)
  svg.selectAll('*').remove()

  const rect = broadSvg.value.getBoundingClientRect()
  const w = rect.width, h = rect.height
  const m = { top: 8, right: 10, bottom: 10, left: 10 }
  const iW = w - m.left - m.right, iH = h - m.top - m.bottom
  if (iW <= 0 || iH <= 0) return

  const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`)

  const selected = selectedIndexData.value
  if (selected) {
    broadVisibleStartDate.value = selected.firstDate ?? null
    broadVisibleEndDate.value = selected.lastDate ?? null

    const realSeries = selected.normRealSparkline
    const simSeries = selected.normSimSparkline
    const n = Math.max(realSeries.length, simSeries.length)
      const values = [...realSeries, ...simSeries].filter((v): v is number => v !== null && Number.isFinite(v))
    if (n < 2 || values.length < 2) return

    const x = d3.scaleLinear().domain([0, n - 1]).range([0, iW])
    const ext = d3.extent(values) as [number, number]
    const pad = (ext[1] - ext[0]) * 0.08 || 1
    const y = d3.scaleLinear().domain([ext[0] - pad, ext[1] + pad]).range([iH, 0])

    const closedMask = Array.from({ length: n }, (_, i) => Boolean(selected.closedMask?.[i]))
    paintClosedBands(g, x, iW, iH, n, closedMask)

    const line = d3.line<number | null>()
      .defined((d) => d !== null && Number.isFinite(d))
      .x((_, i) => x(i))
      .y((d) => y(d as number))
      .curve(d3.curveMonotoneX)

      const lineSim = d3.line<number | null>()
        .defined((d) => d !== null && Number.isFinite(d))
        .x((_, i) => x(i))
        .y((d) => y(d as number))
        .curve(d3.curveLinear)

    g.append('path')
      .datum(realSeries)
      .attr('fill', 'none')
      .attr('stroke', '#64748b')
      .attr('stroke-width', 2)
      .attr('d', line)

    g.append('path')
      .datum(simSeries)
      .attr('fill', 'none')
      .attr('stroke', '#ef5350')
      .attr('stroke-width', 2.4)
      .attr('d', lineSim)
    return
  }

  const data = store.broadIndexSeries
  if (!data.length) {
    broadVisibleStartDate.value = null
    broadVisibleEndDate.value = null
    return
  }

  // --- 真实大盘曲线（__BROAD__）对齐 ---
  const realBroadRows = store.realIndexSeries['__BROAD__'] ?? []
  const calendarByDay = new Map<number, { date: string }>()
  for (const item of store.realCurveCalendar) {
    if (item.day > 0 && item.date) calendarByDay.set(item.day, { date: item.date })
  }
  const dayByDate = new Map<string, number>()
  for (const [day, item] of calendarByDay.entries()) {
    if (item.date) dayByDate.set(item.date, day)
  }
  const realCloseByDay = new Map<number, number>()
  for (const r of realBroadRows) {
    const date = String(r.date ?? '')
    const day = dayByDate.get(date)
    const close = Number(r.close)
    if (day != null && Number.isFinite(close)) realCloseByDay.set(day, close)
  }
  const hasRealBroad = realCloseByDay.size > 0

  const prices = data.map((d) => Number(d.close))
  const dateLabels = data.map((d) => resolveDisplayDate(String(d.date ?? '')))
  const dayTags = data.map((d) => simDateToTradingDay(String(d.date ?? ''), store.tradingDaySeconds))

  let todayStart = dayTags.findIndex((d) => d === currentTradingDay.value)
  if (todayStart < 0) {
    const lastKnownDay = [...dayTags].reverse().find((d) => d !== null)
    if (lastKnownDay !== undefined && lastKnownDay !== null) {
      todayStart = dayTags.findIndex((d) => d === lastKnownDay)
    }
  }
  if (todayStart < 0) {
    todayStart = Math.max(0, prices.length - 1)
  }

  const todayWindow = Math.max(8, prices.length - todayStart)
  const baseWindowSize = Math.min(prices.length, todayWindow)
  const windowSize = Math.max(
    8,
    Math.min(
      prices.length,
      broadWindowSize.value ?? baseWindowSize,
    ),
  )
  broadWindowSize.value = windowSize
  const maxOffset = Math.max(0, prices.length - windowSize)

  if (broadViewMode.value === 'today') {
    broadViewOffset.value = 0
  }

  const appliedOffset = broadViewMode.value === 'history'
    ? Math.max(0, Math.min(maxOffset, broadViewOffset.value))
    : 0
  broadViewOffset.value = appliedOffset

  const endIdx = prices.length - 1 - appliedOffset
  const startIdx = Math.max(0, endIdx - windowSize + 1)
  const viewPrices = prices.slice(startIdx, endIdx + 1)
  const viewDates = dateLabels.slice(startIdx, endIdx + 1)

  broadVisibleStartDate.value = viewDates[0] ?? null
  broadVisibleEndDate.value = viewDates[viewDates.length - 1] ?? null

  if (viewPrices.length < 2) return

  if (hasRealBroad) {
    const viewDayTags = dayTags.slice(startIdx, endIdx + 1)
    const simBase = firstNonNull(viewPrices)
    const normSim = normalizeSeries(viewPrices.map(v => v as number | null), simBase)

    const realPricesRaw: Array<number | null> = viewDayTags.map(d => d !== null ? (realCloseByDay.get(d) ?? null) : null)
    const realBase = firstNonNull(realPricesRaw)
    const normReal = normalizeSeries(realPricesRaw, realBase)

    const allVals = [...normSim, ...normReal].filter((v): v is number => v !== null && Number.isFinite(v))
    if (allVals.length < 2) return

    const x = d3.scaleLinear().domain([0, viewPrices.length - 1]).range([0, iW])
    const ext = d3.extent(allVals) as [number, number]
    const pad = (ext[1] - ext[0]) * 0.08 || 1
    const y = d3.scaleLinear().domain([ext[0] - pad, ext[1] + pad]).range([iH, 0])

    const lineReal = d3.line<number | null>()
      .defined(d => d !== null && Number.isFinite(d as number))
      .x((_, i) => x(i)).y(d => y(d as number)).curve(d3.curveLinear)
    const lineSim = d3.line<number | null>()
      .defined(d => d !== null && Number.isFinite(d as number))
      .x((_, i) => x(i)).y(d => y(d as number)).curve(d3.curveLinear)

    g.append('path').datum(normReal).attr('fill', 'none').attr('stroke', '#64748b').attr('stroke-width', 2).attr('d', lineReal)
    g.append('path').datum(normSim).attr('fill', 'none').attr('stroke', '#ef5350').attr('stroke-width', 2.4).attr('d', lineSim)
  } else {
    const x = d3.scaleLinear().domain([0, viewPrices.length - 1]).range([0, iW])
    const ext = d3.extent(viewPrices) as [number, number]
    const pad = (ext[1] - ext[0]) * 0.1 || 1
    const y = d3.scaleLinear().domain([ext[0] - pad, ext[1] + pad]).range([iH, 0])

    const isUp = viewPrices[viewPrices.length - 1] >= viewPrices[0]
    const color = isUp ? '#ef5350' : '#26a69a'

    const area = d3.area<number>()
      .x((_, i) => x(i)).y0(iH).y1((d) => y(d)).curve(d3.curveMonotoneX)
    const line = d3.line<number>()
      .x((_, i) => x(i)).y((d) => y(d)).curve(d3.curveMonotoneX)

    g.append('path').datum(viewPrices).attr('fill', color).attr('opacity', 0.08).attr('d', area)
    g.append('path').datum(viewPrices).attr('fill', 'none').attr('stroke', color).attr('stroke-width', 2).attr('d', line)
  }

  const dragLayer = g.append('rect')
    .attr('x', 0)
    .attr('y', 0)
    .attr('width', iW)
    .attr('height', iH)
    .attr('fill', 'transparent')
    .style('cursor', maxOffset > 0 ? 'grab' : 'default')

  if (maxOffset > 0) {
    const pxPerStep = Math.max(2, iW / Math.max(24, windowSize))
    const dragBehavior = d3.drag<SVGRectElement, unknown>()
      .on('start', () => {
        broadDragPx.value = 0
        broadViewMode.value = 'history'
      })
      .on('drag', (event) => {
        broadViewMode.value = 'history'
        broadDragPx.value += event.dx
        const step = Math.trunc(broadDragPx.value / pxPerStep)
        if (step === 0) return
        broadDragPx.value -= step * pxPerStep
        broadViewOffset.value = Math.max(0, Math.min(maxOffset, broadViewOffset.value + step))
        renderCenterChart()
      })
    dragLayer.call(dragBehavior)
  }

  dragLayer.on('wheel', (event: WheelEvent) => {
    event.preventDefault()
    if (prices.length <= 8) return

    const curWindow = broadWindowSize.value ?? baseWindowSize
    const step = Math.max(2, Math.round(curWindow * 0.08))
    const nextWindow = Math.max(8, Math.min(prices.length, curWindow + (event.deltaY > 0 ? step : -step)))
    if (nextWindow === curWindow) return

    broadViewMode.value = 'history'
    broadWindowSize.value = nextWindow
    const nextMaxOffset = Math.max(0, prices.length - nextWindow)
    broadViewOffset.value = Math.max(0, Math.min(nextMaxOffset, broadViewOffset.value))
    renderCenterChart()
  })
}

let resizeObs: ResizeObserver | null = null
onMounted(() => {
  renderCenterChart()
  if (broadSvg.value) {
    resizeObs = new ResizeObserver(() => renderCenterChart())
    resizeObs.observe(broadSvg.value)
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch(indexData, (items) => {
  if (selectedSymbol.value && !items.some((item) => item.symbol === selectedSymbol.value)) {
    selectedSymbol.value = null
  }
  renderCenterChart()
}, { deep: true })
watch(() => store.broadIndexSeries, renderCenterChart, { deep: true })
watch(selectedSymbol, renderCenterChart)
watch(currentTradingDay, () => {
  if (broadViewMode.value === 'today') {
    broadViewOffset.value = 0
  }
  renderCenterChart()
})
</script>

<template>
  <div class="idx-overview card">
    <div class="panel-head">
      <div class="card-title">{{ centerTitle }}</div>
      <div class="global-fit-pills" v-if="store.metrics">
        <span v-if="store.metrics.prediction_accuracy_same_day_pct != null || store.metrics.prediction_accuracy_pct != null" class="fit-pill">
          🎯 同日 <b>{{ fmt(store.metrics.prediction_accuracy_same_day_pct ?? store.metrics.prediction_accuracy_pct, 1) }}%</b>
          <small v-if="(store.metrics.prediction_same_day_sample_count ?? store.metrics.prediction_sample_count ?? 0) > 0">
            n={{ store.metrics.prediction_same_day_sample_count ?? store.metrics.prediction_sample_count }}
          </small>
        </span>
        <span v-if="store.metrics.prediction_accuracy_forward1_pct != null" class="fit-pill">
          🧭 前瞻1日 <b>{{ fmt(store.metrics.prediction_accuracy_forward1_pct, 1) }}%</b>
          <small v-if="(store.metrics.prediction_forward1_sample_count ?? 0) > 0">n={{ store.metrics.prediction_forward1_sample_count }}</small>
        </span>
        <span v-if="store.metrics.volatility_fit_pct != null" class="fit-pill">
          📈 拟合 <b>{{ fmt(store.metrics.volatility_fit_pct, 1) }}%</b>
        </span>
        <span v-if="store.metrics.volatility_qlike != null" class="fit-pill">
          📐 QL <b>{{ fmt(store.metrics.volatility_qlike, 3) }}</b>
        </span>
        <span v-if="store.metrics.volatility_log_rmse != null" class="fit-pill">
          📏 LR <b>{{ fmt(store.metrics.volatility_log_rmse, 3) }}</b>
        </span>
        <span v-if="store.metrics.mz_beta != null || store.metrics.mz_p_value != null" class="fit-pill">
          🧮 MZ β=<b>{{ store.metrics.mz_beta == null ? '-' : fmt(store.metrics.mz_beta, 3) }}</b>
          p=<b>{{ store.metrics.mz_p_value == null ? '-' : fmt(store.metrics.mz_p_value, 3) }}</b>
        </span>
      </div>
      <div class="panel-actions">

        <button
          v-if="!selectedIndexData"
          class="sort-btn"
          :class="{ active: broadViewMode === 'today' }"
          @click="resetBroadToToday"
        >当日</button>
      </div>
    </div>

    <div class="sort-bar">
      <span class="sort-label">排序</span>
      <button v-for="s in sortOptions" :key="s.key"
        class="sort-btn" :class="{ active: sortKey === s.key }"
        @click="toggleSort(s.key)"
      >{{ s.label }}{{ sortArrow(s.key) }}</button>
      <span class="selection-tip" :class="{ active: !!selectedIndexData }">
        {{ selectedIndexData ? ('已选中 ' + selectedIndexData.symbol + '，再次点击可恢复大盘') : '未选指数，当前显示大盘' }}
      </span>
    </div>

    <div class="top-layout">
      <div class="idx-column">
        <div
          v-for="idx in leftColumnData"
          :key="idx.symbol"
          class="idx-card"
          :class="[
            idx.pctChg > 0 ? 'idx-up' : idx.pctChg < 0 ? 'idx-down' : '',
            { 'idx-selected': isCenterSymbol(idx.symbol) }
          ]"
          role="button"
          tabindex="0"
          @click="toggleCenterSymbol(idx.symbol)"
          @keydown="onIndexCardKeydown($event, idx.symbol)"
        >
          <div class="idx-row-top">
            <span class="idx-sym">{{ idx.symbol }}</span>
            <span class="idx-price">{{ fmt(idx.price, 2) }}</span>
            <span class="idx-chg">
              {{ idx.pctChg > 0 ? '▲' : idx.pctChg < 0 ? '▼' : '─' }}
              {{ idx.pctChg > 0 ? '+' : '' }}{{ idx.pctChg.toFixed(2) }}%
            </span>
          </div>
          <div class="sparkline-wrap chart-only">
            <svg v-if="idx.normRealSparkline.length > 1 || idx.simSparklineRaw.length > 1" class="sparkline" :viewBox="`0 0 80 24`" preserveAspectRatio="none">
              <polyline
                v-if="idx.normRealSparkline.length > 1"
                :points="sparklinePoints(idx.normRealSparkline, idx.normLow, idx.normHigh)"
                fill="none"
                stroke="#64748b"
                stroke-width="1.2"
                stroke-opacity="0.95"
              />
              <polyline
                :points="sparklinePoints(idx.normSimSparkline, idx.normLow, idx.normHigh)"
                fill="none"
                :stroke="idx.normRealSparkline.length > 1 ? '#ef5350' : (idx.pctChg >= 0 ? '#ef5350' : '#26a69a')"
                stroke-width="1.5"
              />
            </svg>
          </div>
          <div class="sparkline-meta text-below">
            <div class="idx-metrics">
              <span>同日 {{ idx.predictionSameDayAccuracyPct == null ? '-' : (idx.predictionSameDayAccuracyPct.toFixed(1) + '%') }}</span>
              <span>前瞻 {{ idx.predictionForward1AccuracyPct == null ? '-' : (idx.predictionForward1AccuracyPct.toFixed(1) + '%') }}</span>
              <span>拟合 {{ idx.volatilityFitPct == null ? '-' : (idx.volatilityFitPct.toFixed(1) + '%') }}</span>
            </div>
            <div class="idx-metrics-sub">
              <span>QL {{ idx.qlike == null ? '-' : idx.qlike.toFixed(3) }}</span>
              <span>LR {{ idx.logRmse == null ? '-' : idx.logRmse.toFixed(3) }}</span>
              <span>MZ β {{ idx.mzBeta == null ? '-' : idx.mzBeta.toFixed(2) }}</span>
              <span>p {{ idx.mzPValue == null ? '-' : idx.mzPValue.toFixed(3) }}</span>
            </div>
              <div class="sparkline-dates">
                <span :title="idx.firstDate ?? ''">{{ compactDateLabel(idx.firstDate) }}</span>
                <span>交易日日期</span>
                <span :title="idx.lastDate ?? ''">{{ compactDateLabel(idx.lastDate) }}</span>
              </div>
          </div>
        </div>
      </div>

      <div class="center-card">
        <div class="broad-top">
          <span v-if="centerValue != null" class="broad-value">{{ fmt(centerValue, 2) }}</span>
          <span
            v-if="centerPct != null"
            class="broad-pct"
            :class="centerPct > 0 ? 'color-up' : centerPct < 0 ? 'color-down' : ''"
          >
            {{ centerPct > 0 ? '▲' : centerPct < 0 ? '▼' : '─' }}
            {{ fmtPct(centerPct) }}
          </span>
        </div>

        <div v-if="selectedIndexData" class="center-stats">
          <span class="center-stat-group center-stat-group-dir">
            <b class="center-stat-tag">方向</b>
            <span>同日 {{ selectedIndexData.predictionSameDayAccuracyPct == null ? '-' : (selectedIndexData.predictionSameDayAccuracyPct.toFixed(1) + '%') }}</span>
            <span>前瞻 {{ selectedIndexData.predictionForward1AccuracyPct == null ? '-' : (selectedIndexData.predictionForward1AccuracyPct.toFixed(1) + '%') }}</span>
            <span>拟合 {{ selectedIndexData.volatilityFitPct == null ? '-' : (selectedIndexData.volatilityFitPct.toFixed(1) + '%') }}</span>
          </span>
          <span class="center-stat-group center-stat-group-vol">
            <b class="center-stat-tag">波动</b>
            <span>QLIKE {{ selectedIndexData.qlike == null ? '-' : selectedIndexData.qlike.toFixed(3) }}</span>
            <span>Log-RMSE {{ selectedIndexData.logRmse == null ? '-' : selectedIndexData.logRmse.toFixed(3) }}</span>
          </span>
          <span class="center-stat-group center-stat-group-mz">
            <b class="center-stat-tag">MZ</b>
            <span>α {{ selectedIndexData.mzAlpha == null ? '-' : selectedIndexData.mzAlpha.toFixed(3) }}</span>
            <span>β {{ selectedIndexData.mzBeta == null ? '-' : selectedIndexData.mzBeta.toFixed(3) }}</span>
            <span>R² {{ selectedIndexData.mzR2 == null ? '-' : selectedIndexData.mzR2.toFixed(3) }}</span>
            <span>p {{ selectedIndexData.mzPValue == null ? '-' : selectedIndexData.mzPValue.toFixed(3) }}</span>
          </span>
          <span v-if="selectedIndexData.fitSampleCount > 0" class="center-stat-group center-stat-group-sample">
            <b class="center-stat-tag">样本</b>
            <span>{{ selectedIndexData.fitSampleCount }}</span>
          </span>
        </div>
        <div v-else-if="broad" class="broad-stats">
          <span class="color-up">涨 {{ broad.up_count }}</span>
          <span class="color-down">跌 {{ broad.down_count }}</span>
          <span>平 {{ broad.flat_count }}</span>
          <span>成交 {{ fmt(broad.volume, 0) }}</span>
          <span>{{ broadViewMode === 'today' ? '拖动回看，滚轮缩放，点当日回最新' : '历史回看中（可继续拖动/缩放）' }}</span>
        </div>
        <svg ref="broadSvg" class="broad-chart" />
          <div class="center-dates">
            <span :title="visibleStartDate ?? ''">{{ compactDateLabel(visibleStartDate) }}</span>
            <span>交易日日期</span>
            <span :title="visibleEndDate ?? ''">{{ compactDateLabel(visibleEndDate) }}</span>
          </div>
      </div>

      <div class="idx-column">
        <div
          v-for="idx in rightColumnData"
          :key="idx.symbol"
          class="idx-card"
          :class="[
            idx.pctChg > 0 ? 'idx-up' : idx.pctChg < 0 ? 'idx-down' : '',
            { 'idx-selected': isCenterSymbol(idx.symbol) }
          ]"
          role="button"
          tabindex="0"
          @click="toggleCenterSymbol(idx.symbol)"
          @keydown="onIndexCardKeydown($event, idx.symbol)"
        >
          <div class="idx-row-top">
            <span class="idx-sym">{{ idx.symbol }}</span>
            <span class="idx-price">{{ fmt(idx.price, 2) }}</span>
            <span class="idx-chg">
              {{ idx.pctChg > 0 ? '▲' : idx.pctChg < 0 ? '▼' : '─' }}
              {{ idx.pctChg > 0 ? '+' : '' }}{{ idx.pctChg.toFixed(2) }}%
            </span>
          </div>
          <div class="sparkline-wrap chart-only">
            <svg v-if="idx.normRealSparkline.length > 1 || idx.simSparklineRaw.length > 1" class="sparkline" :viewBox="`0 0 80 24`" preserveAspectRatio="none">
              <polyline
                v-if="idx.normRealSparkline.length > 1"
                :points="sparklinePoints(idx.normRealSparkline, idx.normLow, idx.normHigh)"
                fill="none"
                stroke="#64748b"
                stroke-width="1.2"
                stroke-opacity="0.95"
              />
              <polyline
                :points="sparklinePoints(idx.normSimSparkline, idx.normLow, idx.normHigh)"
                fill="none"
                :stroke="idx.normRealSparkline.length > 1 ? '#ef5350' : (idx.pctChg >= 0 ? '#ef5350' : '#26a69a')"
                stroke-width="1.5"
              />
            </svg>
          </div>
          <div class="sparkline-meta text-below">
            <div class="idx-metrics">
              <span>同日 {{ idx.predictionSameDayAccuracyPct == null ? '-' : (idx.predictionSameDayAccuracyPct.toFixed(1) + '%') }}</span>
              <span>前瞻 {{ idx.predictionForward1AccuracyPct == null ? '-' : (idx.predictionForward1AccuracyPct.toFixed(1) + '%') }}</span>
              <span>拟合 {{ idx.volatilityFitPct == null ? '-' : (idx.volatilityFitPct.toFixed(1) + '%') }}</span>
            </div>
            <div class="idx-metrics-sub">
              <span>QL {{ idx.qlike == null ? '-' : idx.qlike.toFixed(3) }}</span>
              <span>LR {{ idx.logRmse == null ? '-' : idx.logRmse.toFixed(3) }}</span>
              <span>MZ β {{ idx.mzBeta == null ? '-' : idx.mzBeta.toFixed(2) }}</span>
              <span>p {{ idx.mzPValue == null ? '-' : idx.mzPValue.toFixed(3) }}</span>
            </div>
              <div class="sparkline-dates">
                <span :title="idx.firstDate ?? ''">{{ compactDateLabel(idx.firstDate) }}</span>
                <span>交易日日期</span>
                <span :title="idx.lastDate ?? ''">{{ compactDateLabel(idx.lastDate) }}</span>
              </div>
          </div>
        </div>
      </div>

      <div v-if="indexData.length === 0" class="idx-empty">暂无指数数据</div>
    </div>
  </div>
</template>

<style scoped>
.idx-overview {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.global-fit-pills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.fit-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  font-family: var(--font-mono);
  background: var(--surface-1);
  color: var(--text-muted);
  white-space: nowrap;
}

.fit-pill b {
  color: var(--heading);
}

.fit-pill small {
  font-size: 9px;
  opacity: 0.7;
}

.panel-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.broad-top {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
}

.broad-value {
  font-size: 16px;
  font-weight: 800;
  color: var(--heading);
  font-family: var(--font-mono);
}

.broad-pct {
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.broad-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  margin-bottom: 6px;
}

.broad-chart {
  width: 100%;
  flex: 1 1 auto;
  min-height: 0;
  height: auto;
}

.sort-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.mode-switch {
  display: inline-flex;
  gap: 4px;
}

.selection-tip {
  margin-left: auto;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-dim);
}

.selection-tip.active {
  color: var(--accent);
}

.sort-label {
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-sans);
  margin-right: 4px;
}

.sort-btn {
  border: none;
  background: var(--surface-1);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}

.sort-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.sort-btn:hover:not(.active) {
  background: var(--surface-2);
}

.top-layout {
  display: grid;
  grid-template-columns: minmax(170px, 0.68fr) minmax(760px, 3.2fr) minmax(170px, 0.68fr);
  gap: 10px;
  align-items: stretch;
}

.idx-column {
  display: grid;
  grid-template-columns: 1fr;
  gap: 7px;
}

.center-card {
  background: var(--surface-0);
  border-radius: var(--radius-lg);
  padding: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.idx-card {
  padding: 8px 9px;
  border-radius: var(--radius);
  font-family: var(--font-mono);
  background: var(--surface-1);
  cursor: pointer;
  border: 1px solid transparent;
  transition: transform 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
}

.idx-card:hover {
  transform: translateY(-1px);
  border-color: var(--border);
}

.idx-card:focus-visible {
  outline: none;
  border-color: var(--accent);
}

.idx-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent);
}

.idx-up {
  background: var(--up-soft);
}

.idx-down {
  background: var(--down-soft);
}

.idx-row-top {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 3px;
}

.idx-sym {
  font-size: 13px;
  font-weight: 700;
  color: var(--heading);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70px;
}

.idx-price {
  font-size: 20px;
  font-weight: 800;
  color: var(--heading);
}

.idx-chg {
  font-size: 11px;
  font-weight: 700;
  margin-left: auto;
}

.idx-up .idx-chg { color: var(--up); }
.idx-down .idx-chg { color: var(--down); }

.sparkline {
  width: 100%;
  height: 32px;
  margin: 2px 0 0;
}

.sparkline-wrap {
  margin-top: 1px;
}

.sparkline-meta {
  margin-top: 3px;
}

.chart-only {
  padding-bottom: 2px;
}

.text-below {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sparkline-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 0;
  line-height: 1.2;
  font-size: 8px;
  color: var(--text-dim);
}

.idx-metrics {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 0;
  line-height: 1.2;
  font-size: 9px;
  color: var(--text-muted);
}

.idx-metrics-sub {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 2px;
  line-height: 1.2;
  font-size: 9px;
  color: var(--text-dim);
}

.center-stats {
  display: flex;
  flex-wrap: nowrap;
  gap: 0;
  margin-bottom: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow-x: auto;
}

.center-stat-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border-left: 1px dashed var(--border);
}

.center-stat-group:first-child {
  border-left: none;
  padding-left: 0;
}

.center-stat-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1.1;
  color: var(--heading);
  background: var(--surface-1);
}

.center-stat-group-dir .center-stat-tag {
  background: color-mix(in srgb, var(--accent) 16%, var(--surface-1));
}

.center-stat-group-vol .center-stat-tag {
  background: color-mix(in srgb, #ef5350 13%, var(--surface-1));
}

.center-stat-group-mz .center-stat-tag {
  background: color-mix(in srgb, #64748b 16%, var(--surface-1));
}

.sparkline-dates,
.center-dates {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 3px;
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--text-dim);
}

.sparkline-dates span:nth-child(2),
.center-dates span:nth-child(2) {
  opacity: 0.85;
}

.dot {
  display: inline-block;
  width: 6px;
  height: 2px;
  vertical-align: middle;
  margin-right: 3px;
}

.dot.real {
  background: #64748b;
}

.dot.sim {
  background: #ef5350;
}

.idx-empty {
  grid-column: 1 / -1;
  color: var(--text-dim);
  font-size: 11px;
  padding: 12px;
  text-align: center;
}

@media (max-width: 1500px) {
  .top-layout {
    grid-template-columns: minmax(160px, 0.64fr) minmax(620px, 2.6fr) minmax(160px, 0.64fr);
  }
}

@media (max-width: 1200px) {
  .top-layout {
    grid-template-columns: 1fr;
  }

  .idx-column {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .selection-tip {
    width: 100%;
    margin-left: 0;
  }
}

@media (max-width: 640px) {
  .idx-column {
    grid-template-columns: 1fr;
  }

  .broad-chart {
    height: 200px;
  }
}
</style>
