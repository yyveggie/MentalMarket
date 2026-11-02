/** 纯函数技术指标：输入收盘价数组，输出与输入等长的序列（不足窗口处为 null）。 */
export type Num = number | null

export function sma(values: number[], period: number): Num[] {
  const n = Math.max(1, Math.floor(period))
  const out: Num[] = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= n) sum -= values[i - n]
    if (i >= n - 1) out[i] = sum / n
  }
  return out
}

export function ema(values: number[], period: number): Num[] {
  const n = Math.max(1, Math.floor(period))
  const k = 2 / (n + 1)
  const out: Num[] = new Array(values.length).fill(null)
  if (values.length < n) return out
  let seed = 0
  for (let i = 0; i < n; i++) seed += values[i]
  let prev = seed / n
  out[n - 1] = prev
  for (let i = n; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

/** Wilder RSI */
export function rsi(values: number[], period = 14): Num[] {
  const n = Math.max(1, Math.floor(period))
  const out: Num[] = new Array(values.length).fill(null)
  if (values.length <= n) return out
  let gain = 0
  let loss = 0
  for (let i = 1; i <= n; i++) {
    const d = values[i] - values[i - 1]
    if (d >= 0) gain += d
    else loss -= d
  }
  let avgGain = gain / n
  let avgLoss = loss / n
  out[n] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  for (let i = n + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1]
    avgGain = (avgGain * (n - 1) + Math.max(0, d)) / n
    avgLoss = (avgLoss * (n - 1) + Math.max(0, -d)) / n
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return out
}

export interface MacdResult {
  macd: Num[]
  signal: Num[]
  hist: Num[]
}

export function macd(values: number[], fast = 12, slow = 26, signalPeriod = 9): MacdResult {
  const fastE = ema(values, fast)
  const slowE = ema(values, slow)
  const line: Num[] = values.map((_, i) => (fastE[i] != null && slowE[i] != null ? (fastE[i] as number) - (slowE[i] as number) : null))
  const firstIdx = line.findIndex((v) => v != null)
  const signal: Num[] = new Array(values.length).fill(null)
  const hist: Num[] = new Array(values.length).fill(null)
  if (firstIdx >= 0) {
    const compact = line.slice(firstIdx) as number[]
    const sig = ema(compact, signalPeriod)
    for (let i = 0; i < compact.length; i++) {
      const s = sig[i]
      if (s == null) continue
      signal[firstIdx + i] = s
      hist[firstIdx + i] = compact[i] - s
    }
  }
  return { macd: line, signal, hist }
}
