/** 数值格式化：默认 2 位小数（价格、比率）；数量请用 fmtInt，百分比请用 fmtPct */
export function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null || Number.isNaN(v)) return '-'
  return Number(v).toFixed(decimals)
}

export function fmtInt(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  return Math.round(Number(v)).toLocaleString('en-US')
}

/** A 股惯例的万/亿单位：8422719 → 842.3万，1.2e8 → 1.20亿 */
export function fmtCn(v: number | null | undefined, decimals = 1): string {
  if (v == null || Number.isNaN(v)) return '-'
  const a = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(2)}亿`
  if (a >= 1e4) return `${sign}${(a / 1e4).toFixed(decimals)}万`
  return `${sign}${a.toFixed(0)}`
}

export function fmtSimTime(t: number): string {
  if (t >= 3600) return `${(t / 3600).toFixed(1)}h`
  if (t >= 60) return `${(t / 60).toFixed(1)}m`
  return `${t.toFixed(1)}s`
}

/** 金额紧凑格式：统一 A 股惯例 万/亿，保留两位小数（旧名保留兼容） */
export function fmtCompact(v: number): string {
  return fmtCn(v, 2)
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

export function tomEmoji(level: number): string {
  return `T${level}`
}

export function tomLabel(level: number): string {
  return `ToM${level}`
}

/** Agent 状态的文字标签（替代 emoji） */
export function emotionLabel(emotion: string): string {
  const map: Record<string, string> = {
    neutral: '观望',
    happy: '看多',
    worried: '看空',
    thinking: '推理中',
    scheming: '策略中',
  }
  return map[emotion] ?? '观望'
}

export function emotionEmoji(emotion: string): string {
  return emotionLabel(emotion)
}

export function pnlClass(v: number): string {
  if (v > 0) return 'color-up'
  if (v < 0) return 'color-down'
  return 'color-flat'
}

export function esc(s: string): string {
  const el = document.createElement('div')
  el.textContent = s
  return el.innerHTML
}

/** 后端决策里的 action 可能是枚举字符串（"Action.SELL"）或纯小写；统一成 buy / sell / hold */
export function normalizeAction(raw: unknown): 'buy' | 'sell' | 'hold' {
  const s = String(raw ?? 'hold').toLowerCase()
  const tail = s.includes('.') ? s.split('.').pop() ?? s : s
  return tail === 'buy' || tail === 'sell' ? tail : 'hold'
}
