import type { UTCTimestamp } from 'lightweight-charts'
import type { DailyBar, IntradayBar } from '@/types/market'
import { parseDateUtc, simDayToTime, simSecondsToTime } from '@/utils/simTime'

export interface Bar {
  time: UTCTimestamp
  open: number
  high: number
  low: number
  close: number
  volume: number
  /** 真实历史日：只有收盘价，用线而不是 K 线表示 */
  real: boolean
}

export type BarMode = 'daily' | 'intraday'

function dedupIncreasing(bars: Bar[]): Bar[] {
  const out: Bar[] = []
  for (const b of bars) {
    const last = out[out.length - 1]
    if (last && b.time <= last.time) {
      out[out.length - 1] = b
      continue
    }
    out.push(b)
  }
  return out
}

export function dailyBarsToChart(rows: DailyBar[] | undefined, epoch: number): Bar[] {
  const out: Bar[] = []
  for (const row of rows ?? []) {
    const close = Number(row.close)
    if (!Number.isFinite(close)) continue
    let time: number | null = null
    if (row.real) {
      time = parseDateUtc(row.time)
    } else {
      const day = row.day ?? Number(String(row.time).replace(/^D/i, ''))
      if (Number.isFinite(day) && day > 0) time = simDayToTime(epoch, day)
    }
    if (time == null) continue
    out.push({
      time: time as UTCTimestamp,
      open: Number(row.open ?? close),
      high: Number(row.high ?? close),
      low: Number(row.low ?? close),
      close,
      volume: Number(row.volume ?? 0),
      real: Boolean(row.real),
    })
  }
  out.sort((a, b) => a.time - b.time)
  return dedupIncreasing(out)
}

export function intradayBarsToChart(rows: IntradayBar[] | undefined, epoch: number, daySeconds: number): Bar[] {
  const out: Bar[] = []
  for (const b of rows ?? []) {
    if (!Number.isFinite(b.close)) continue
    out.push({
      time: simSecondsToTime(epoch, b.t, daySeconds),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      volume: b.volume,
      real: false,
    })
  }
  return dedupIncreasing(out)
}
