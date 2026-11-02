/**
 * 仿真时间 ↔ 图表时间轴映射。
 *
 * - 真实历史日：直接用日期（UTC 00:00 的时间戳）。
 * - 仿真日 n：epoch + (n-1) 天；盘中时刻把一个仿真日连续映射到 09:30 → 15:00（不建模午休）。
 * - epoch 取仿真起始日期（config.market_indices.start_date），保证历史段与仿真段在同一条时间轴上连续。
 */
import { TickMarkType, type Time, type UTCTimestamp } from 'lightweight-charts'

export const SESSION_OPEN_SEC = 9.5 * 3600
export const SESSION_LENGTH_SEC = 5.5 * 3600
const DAY_SEC = 86400
// A 股时段（当日秒数）：09:15-09:25 开盘集合竞价，09:30 连续竞价，14:57-15:00 收盘集合竞价
const OPEN_CALL_START = 9 * 3600 + 15 * 60
const OPEN_CALL_END = 9 * 3600 + 25 * 60
const CONT_START = SESSION_OPEN_SEC
const CLOSE_CALL_START = 14 * 3600 + 57 * 60
const SESSION_END = 15 * 3600

let sessionOpenSec = 0
let sessionCloseSec = 0

/** 由看板状态注入集合竞价时长（仿真秒）；两者为 0 时退化为连续映射 09:30 → 15:00 */
export function configureSession(openSec: number, closeSec: number): void {
  sessionOpenSec = Math.max(0, Number(openSec) || 0)
  sessionCloseSec = Math.max(0, Number(closeSec) || 0)
}

/** 仿真日内秒 → 当日钟表秒（分段线性：开盘竞价 / 连续竞价 / 收盘竞价） */
export function simSecOfDayToClockSec(secInDay: number, daySeconds: number): number {
  const d = Math.max(1e-6, daySeconds)
  const x = Math.min(d, Math.max(0, secInDay))
  const o = Math.min(sessionOpenSec, d / 2)
  const c = Math.min(sessionCloseSec, d / 2)
  if (o <= 0 && c <= 0) return SESSION_OPEN_SEC + (x / d) * SESSION_LENGTH_SEC
  if (o > 0 && x < o) return OPEN_CALL_START + (x / o) * (OPEN_CALL_END - OPEN_CALL_START)
  const contEnd = d - c
  if (c > 0 && x >= contEnd) return CLOSE_CALL_START + ((x - contEnd) / c) * (SESSION_END - CLOSE_CALL_START)
  const contClockEnd = c > 0 ? CLOSE_CALL_START : SESSION_END
  const span = Math.max(1e-6, contEnd - o)
  return CONT_START + ((x - o) / span) * (contClockEnd - CONT_START)
}
const FALLBACK_EPOCH = Date.UTC(2030, 0, 1) / 1000

export function parseDateUtc(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null
  const m = String(dateStr).trim().match(/^(\d{4})[-/]?(\d{2})[-/]?(\d{2})/)
  if (!m) return null
  const t = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 1000
  return Number.isFinite(t) ? t : null
}

export function simEpochFromDate(dateStr: string | null | undefined): number {
  return parseDateUtc(dateStr) ?? FALLBACK_EPOCH
}

export function simDayToTime(epoch: number, day: number): UTCTimestamp {
  return (epoch + (Math.max(1, Math.floor(day)) - 1) * DAY_SEC) as UTCTimestamp
}

export function simSecondsToTime(epoch: number, simSeconds: number, daySeconds: number): UTCTimestamp {
  const d = Math.max(1e-6, daySeconds)
  const day = Math.floor(simSeconds / d) + 1
  const secInDay = simSeconds - (day - 1) * d
  return (epoch + (day - 1) * DAY_SEC + simSecOfDayToClockSec(secInDay, d)) as UTCTimestamp
}

export function timeToNumber(time: Time | undefined | null): number | null {
  if (time == null) return null
  if (typeof time === 'number') return time
  if (typeof time === 'string') return parseDateUtc(time)
  if (typeof time === 'object') return Date.UTC(time.year, time.month - 1, time.day) / 1000
  return null
}

export function isSimTime(epoch: number, t: number): boolean {
  return t >= epoch - 1
}

export function simDayOfTime(epoch: number, t: number): number {
  return Math.floor((t - epoch) / DAY_SEC + 1e-9) + 1
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

export function clockOfTime(epoch: number, t: number): string {
  const secOfDay = (((t - epoch) % DAY_SEC) + DAY_SEC) % DAY_SEC
  // 分桶边界是浮点运算得到的，按"最近一分钟"取整，避免 10.999 分被截成 10 分而出现重复刻度
  const totalMin = Math.round(secOfDay / 60)
  const hh = Math.floor(totalMin / 60)
  const mm = totalMin % 60
  return `${pad2(hh)}:${pad2(mm)}`
}

export function formatDateUtc(t: number, style: 'full' | 'md' | 'ym' | 'y' = 'full'): string {
  const d = new Date(t * 1000)
  const y = d.getUTCFullYear()
  const m = pad2(d.getUTCMonth() + 1)
  const day = pad2(d.getUTCDate())
  if (style === 'y') return String(y)
  if (style === 'ym') return `${y}-${m}`
  if (style === 'md') return `${m}-${day}`
  return `${y}-${m}-${day}`
}

/** 十字光标/图例用：仿真段 "D3 10:47"，历史段 "2023-06-13" */
export function formatChartTime(epoch: number, t: number, withClock: boolean): string {
  if (isSimTime(epoch, t)) {
    const day = simDayOfTime(epoch, t)
    return withClock ? `D${day} ${clockOfTime(epoch, t)}` : `D${day}`
  }
  return formatDateUtc(t, 'full')
}

/** 时间轴刻度：仿真段按 D 编号（盘中刻度显示 HH:MM），历史段按日期 */
export function makeTickMarkFormatter(epoch: number) {
  return (time: Time, tickMarkType: TickMarkType): string | null => {
    const t = timeToNumber(time)
    if (t == null) return null
    if (isSimTime(epoch, t)) {
      if (tickMarkType === TickMarkType.Time || tickMarkType === TickMarkType.TimeWithSeconds) {
        return clockOfTime(epoch, t)
      }
      return `D${simDayOfTime(epoch, t)}`
    }
    if (tickMarkType === TickMarkType.Year) return formatDateUtc(t, 'y')
    if (tickMarkType === TickMarkType.Month) return formatDateUtc(t, 'ym')
    return formatDateUtc(t, 'md')
  }
}

export function makeTimeFormatter(epoch: number, withClock: boolean) {
  return (time: Time): string => {
    const t = timeToNumber(time)
    return t == null ? '' : formatChartTime(epoch, t, withClock)
  }
}

/** 仿真秒 → "D3 10:47"（顶栏等处通用） */
export function describeSimClock(simSeconds: number, daySeconds: number): string {
  const d = Math.max(1e-6, daySeconds)
  const day = Math.floor(simSeconds / d) + 1
  const secInDay = simSeconds - (day - 1) * d
  const totalMin = Math.round(simSecOfDayToClockSec(secInDay, d) / 60)
  return `D${day} ${pad2(Math.floor(totalMin / 60))}:${pad2(totalMin % 60)}`
}
