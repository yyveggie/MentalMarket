<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtPct, fmtCn } from '@/utils/formatters'
import { simEpochFromDate, simDayToTime } from '@/utils/simTime'
import KlineChart, { type OverlayPoint } from './pro/KlineChart.vue'
import IndexCard from './IndexCard.vue'
import EventTicker from './EventTicker.vue'
import type { IndexCardData } from './indexOverviewTypes'

const store = useMarketStore()

const broad = computed(() => store.broadMarket)
const currentTradingDay = computed(() => Math.max(1, Number(store.tradingDay || 1)))
const includeClosedDaysForMetrics = computed(() => Boolean(store.metrics?.include_closed_days_for_metrics))

type SortKey = 'symbol' | 'pctChg' | 'price' | 'volume'
const sortKey = ref<SortKey>('pctChg')
const sortAsc = ref(false)
const selectedSymbol = ref<string | null>(null)

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

const indexData = computed<IndexCardData[]>(() => {
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
  const items: IndexCardData[] = symbols.map((symbol) => {
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

const centerSymbol = computed(() => selectedSymbol.value ?? '__BROAD__')
const centerTitle = computed(() => selectedIndexData.value?.symbol ?? (broad.value?.name ?? '大盘(加权)'))
const centerValue = computed(() => selectedIndexData.value?.price ?? broad.value?.value ?? null)
const centerPct = computed(() => selectedIndexData.value?.pctChg ?? broad.value?.pct_chg ?? null)

// 预测拟合模式：把真实指数按交易日映射到仿真日的时间轴上，叠加在 K 线主图里（归一化坐标下可直接对比）
const epoch = computed(() => simEpochFromDate(store.simStartDate))
const realOverlay = computed<OverlayPoint[] | null>(() => {
  const realRows = store.realIndexSeries[centerSymbol.value] ?? []
  if (!realRows.length) return null
  const dayByDate = new Map<string, number>()
  for (const c of store.realCurveCalendar) {
    if (c.day > 0 && c.date) dayByDate.set(c.date, c.day)
  }
  const pts: OverlayPoint[] = []
  for (const r of realRows) {
    if (r.is_closed) continue
    const day = dayByDate.get(String(r.date ?? ''))
    const v = Number(r.close)
    if (day == null || !Number.isFinite(v)) continue
    pts.push({ time: simDayToTime(epoch.value, day), value: v })
  }
  pts.sort((a, b) => a.time - b.time)
  return pts.length ? pts : null
})

// ── 市场宽度 + 指数涨跌热力条（填充中心卡片下方） ──
const heatRows = computed(() => {
  const items = [...indexData.value].sort((a, b) => b.pctChg - a.pctChg)
  const maxAbs = Math.max(0.01, ...items.map((i) => Math.abs(i.pctChg)))
  return items.map((i) => ({
    symbol: i.symbol,
    pctChg: i.pctChg,
    volume: i.volume,
    width: (Math.abs(i.pctChg) / maxAbs) * 100,
    selected: isCenterSymbol(i.symbol),
  }))
})

const breadth = computed(() => {
  const items = indexData.value
  const up = items.filter((i) => i.pctChg > 0).length
  const down = items.filter((i) => i.pctChg < 0).length
  const flat = items.length - up - down
  const avgPct = items.length ? items.reduce((s, i) => s + i.pctChg, 0) / items.length : null
  const totalVolume = items.reduce((s, i) => s + (i.volume || 0), 0)
  const broadBars = store.dailyBars['__BROAD__'] ?? []
  const last = broadBars[broadBars.length - 1]
  const prev = broadBars[broadBars.length - 2]
  let amplitude: number | null = null
  if (last && !last.real && last.high != null && last.low != null) {
    const base = prev?.close ?? last.open ?? null
    if (base) amplitude = ((last.high - last.low) / base) * 100
  }
  const best = heatRows.value[0] ?? null
  const worst = heatRows.value[heatRows.value.length - 1] ?? null
  return { up, down, flat, total: items.length, upPct: items.length ? (up / items.length) * 100 : 50, avgPct, totalVolume, amplitude, best, worst }
})

function toggleCenterSymbol(symbol: string) {
  selectedSymbol.value = selectedSymbol.value === symbol ? null : symbol
}

function isCenterSymbol(symbol: string): boolean {
  return selectedSymbol.value === symbol
}

watch(indexData, (items) => {
  if (selectedSymbol.value && !items.some((item) => item.symbol === selectedSymbol.value)) {
    selectedSymbol.value = null
  }
})
</script>

<template>
  <div class="idx-overview card">
    <div class="panel-head">
      <div class="card-title">{{ centerTitle }}</div>
      <div class="global-fit-pills" v-if="store.metrics">
        <span v-if="store.metrics.prediction_accuracy_same_day_pct != null || store.metrics.prediction_accuracy_pct != null" class="fit-pill" title="同日方向准确率">
          同日 <b>{{ fmt(store.metrics.prediction_accuracy_same_day_pct ?? store.metrics.prediction_accuracy_pct, 1) }}%</b>
          <small v-if="(store.metrics.prediction_same_day_sample_count ?? store.metrics.prediction_sample_count ?? 0) > 0">
            n={{ store.metrics.prediction_same_day_sample_count ?? store.metrics.prediction_sample_count }}
          </small>
        </span>
        <span v-if="store.metrics.prediction_accuracy_forward1_pct != null" class="fit-pill" title="前瞻 1 日方向准确率">
          前瞻1日 <b>{{ fmt(store.metrics.prediction_accuracy_forward1_pct, 1) }}%</b>
          <small v-if="(store.metrics.prediction_forward1_sample_count ?? 0) > 0">n={{ store.metrics.prediction_forward1_sample_count }}</small>
        </span>
        <span v-if="store.metrics.volatility_fit_pct != null" class="fit-pill" title="波动拟合度">
          拟合 <b>{{ fmt(store.metrics.volatility_fit_pct, 1) }}%</b>
        </span>
        <span v-if="store.metrics.volatility_qlike != null" class="fit-pill" title="QLIKE 波动损失">
          QLIKE <b>{{ fmt(store.metrics.volatility_qlike, 3) }}</b>
        </span>
        <span v-if="store.metrics.volatility_log_rmse != null" class="fit-pill" title="对数方差 RMSE">
          Log-RMSE <b>{{ fmt(store.metrics.volatility_log_rmse, 3) }}</b>
        </span>
        <span v-if="store.metrics.mz_beta != null || store.metrics.mz_p_value != null" class="fit-pill" title="Mincer-Zarnowitz 回归">
          MZ β=<b>{{ store.metrics.mz_beta == null ? '-' : fmt(store.metrics.mz_beta, 3) }}</b>
          p=<b>{{ store.metrics.mz_p_value == null ? '-' : fmt(store.metrics.mz_p_value, 3) }}</b>
        </span>
      </div>
    </div>

    <div class="sort-bar">
      <span class="sort-label">排序</span>
      <button v-for="s in sortOptions" :key="s.key"
        class="sort-btn" :class="{ active: sortKey === s.key }"
        @click="toggleSort(s.key)"
      >{{ s.label }}{{ sortArrow(s.key) }}</button>
      <EventTicker class="sort-ticker" />
      <span class="selection-tip" :class="{ active: !!selectedIndexData }">
        {{ selectedIndexData ? ('已选中 ' + selectedIndexData.symbol + '，再次点击可恢复大盘') : '未选指数，当前显示大盘' }}
      </span>
    </div>

    <div class="top-layout">
      <div class="idx-column">
        <IndexCard
          v-for="idx in leftColumnData"
          :key="idx.symbol"
          :idx="idx"
          :selected="isCenterSymbol(idx.symbol)"
          @select="toggleCenterSymbol"
        />
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
          <span v-if="realOverlay" class="broad-hint">灰线为真实指数，仿真段为 K 线；归一化坐标下可直接对比</span>
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
          <span>成交 {{ fmtCn(broad.volume) }}</span>
          <span>拖动平移，滚轮缩放，复位回到全览</span>
        </div>

        <KlineChart
          :symbol="centerSymbol"
          mode="daily"
          height="fill"
          :title="centerTitle"
          :overlay="realOverlay"
          overlay-label="真实指数"
          :default-price-mode="realOverlay ? 'indexed' : 'normal'"
          default-sub="rsi"
        />

        <div v-if="indexData.length" class="market-strip">
          <div class="breadth">
            <div class="breadth-title">市场宽度</div>
            <div class="breadth-bar" :title="`上涨 ${breadth.up} / 下跌 ${breadth.down} / 平 ${breadth.flat}`">
              <i class="b-up" :style="{ width: `${breadth.upPct}%` }" />
              <i class="b-down" />
            </div>
            <div class="breadth-stats">
              <span><b class="color-up">{{ breadth.up }}</b> 涨</span>
              <span><b class="color-down">{{ breadth.down }}</b> 跌</span>
              <span><b>{{ breadth.flat }}</b> 平</span>
            </div>
            <div class="breadth-kv">
              <span class="k">平均涨跌</span>
              <span class="v" :class="breadth.avgPct == null ? '' : breadth.avgPct > 0 ? 'color-up' : breadth.avgPct < 0 ? 'color-down' : ''">{{ breadth.avgPct == null ? '-' : fmtPct(breadth.avgPct) }}</span>
              <span class="k">成交额</span>
              <span class="v">{{ fmtCn(breadth.totalVolume) }}</span>
              <span class="k" title="当日大盘 (最高 − 最低) / 前收">大盘振幅</span>
              <span class="v">{{ breadth.amplitude == null ? '-' : breadth.amplitude.toFixed(2) + '%' }}</span>
              <span class="k">领涨</span>
              <span class="v color-up">{{ breadth.best ? `${breadth.best.symbol} ${fmtPct(breadth.best.pctChg)}` : '-' }}</span>
              <span class="k">领跌</span>
              <span class="v color-down">{{ breadth.worst ? `${breadth.worst.symbol} ${fmtPct(breadth.worst.pctChg)}` : '-' }}</span>
            </div>
          </div>

          <div class="heat">
            <div class="heat-title">指数涨跌热力 <small>按当日涨跌幅排序，点击切换主图</small></div>
            <div class="heat-grid">
              <div
                v-for="h in heatRows"
                :key="h.symbol"
                class="heat-row"
                :class="{ selected: h.selected }"
                role="button"
                tabindex="0"
                @click="toggleCenterSymbol(h.symbol)"
                @keydown.enter.prevent="toggleCenterSymbol(h.symbol)"
              >
                <span class="heat-sym">{{ h.symbol }}</span>
                <span class="heat-track">
                  <i
                    class="heat-bar"
                    :class="h.pctChg >= 0 ? 'hb-up' : 'hb-down'"
                    :style="{ width: `${Math.max(2, h.width / 2)}%`, [h.pctChg >= 0 ? 'left' : 'right']: '50%' }"
                  />
                </span>
                <span class="heat-pct" :class="h.pctChg > 0 ? 'color-up' : h.pctChg < 0 ? 'color-down' : 'color-flat'">{{ fmtPct(h.pctChg) }}</span>
                <span class="heat-vol" :title="'仿真累计成交额'">{{ fmtCn(h.volume) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="idx-column">
        <IndexCard
          v-for="idx in rightColumnData"
          :key="idx.symbol"
          :idx="idx"
          :selected="isCenterSymbol(idx.symbol)"
          @select="toggleCenterSymbol"
        />
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

.broad-top {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  height: 22px;
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

.broad-hint {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-dim);
}

.broad-stats {
  display: flex;
  flex-wrap: nowrap;
  white-space: nowrap;
  overflow: hidden;
  height: 18px;
  gap: 10px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  margin-bottom: 6px;
}

.sort-bar {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
  min-height: 24px;
}

.sort-ticker {
  margin: 0 10px;
}

.selection-tip {
  margin-left: 0;
  flex-shrink: 0;
  white-space: nowrap;
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
  min-width: 0;
  height: 100%;
}

/* ── 市场宽度 + 热力条 ── */
.market-strip {
  display: grid;
  grid-template-columns: minmax(200px, 0.9fr) minmax(0, 2.1fr);
  gap: 14px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.breadth-title,
.heat-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--heading);
  margin-bottom: 6px;
}

.heat-title small {
  font-size: 9px;
  font-weight: 400;
  color: var(--text-dim);
  margin-left: 6px;
}

.breadth-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--down-soft);
}

.breadth-bar .b-up {
  display: block;
  height: 100%;
  background: var(--up);
  opacity: 0.75;
  transition: width 0.3s ease;
}

.breadth-bar .b-down {
  display: block;
  flex: 1;
  height: 100%;
  background: var(--down);
  opacity: 0.75;
}

.breadth-stats {
  display: flex;
  gap: 12px;
  margin: 6px 0 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.breadth-stats b {
  color: var(--heading);
  font-weight: 700;
}

.breadth-kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 8px;
  font-size: 10px;
}

.breadth-kv .k {
  color: var(--text-dim);
}

.breadth-kv .v {
  color: var(--heading);
  font-weight: 600;
  text-align: right;
  white-space: nowrap;
}

.heat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px 16px;
}

.heat-row {
  display: grid;
  grid-template-columns: 44px 1fr 56px 56px;
  align-items: center;
  gap: 6px;
  padding: 2px 4px;
  border-radius: 3px;
  font-size: 10px;
  cursor: pointer;
  border: 1px solid transparent;
}

.heat-row:hover {
  background: var(--surface-1);
}

.heat-row.selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.heat-sym {
  font-weight: 700;
  color: var(--heading);
}

.heat-track {
  position: relative;
  height: 8px;
  background: var(--surface-2);
  border-radius: 2px;
  overflow: hidden;
}

.heat-track::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-light);
}

.heat-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  transition: width 0.3s ease;
}

.hb-up { background: var(--up); opacity: 0.8; }
.hb-down { background: var(--down); opacity: 0.8; }

.heat-pct {
  text-align: right;
  font-weight: 600;
}

.heat-vol {
  text-align: right;
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
}
</style>
