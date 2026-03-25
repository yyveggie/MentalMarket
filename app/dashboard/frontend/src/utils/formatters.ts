/** 格式化数值，null/NaN 返回 '-' */
export function fmt(v: number | null | undefined, decimals = 4): string {
  if (v == null || Number.isNaN(v)) return '-'
  return Number(v).toFixed(decimals)
}

/** 格式化仿真时间 */
export function fmtSimTime(t: number): string {
  if (t >= 3600) return `${(t / 3600).toFixed(1)}h`
  if (t >= 60) return `${(t / 60).toFixed(1)}m`
  return `${t.toFixed(1)}s`
}

/** 格式化大数字（K/M） */
export function fmtCompact(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return v.toFixed(0)
}

/** 格式化百分比 */
export function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

/** 根据 ToM 等级返回表情 */
export function tomEmoji(level: number): string {
  return ['🔵', '🟢', '🟣'][level] ?? '⚪'
}

/** 根据 ToM 等级返回标签 */
export function tomLabel(level: number): string {
  return `ToM${level}`
}

/** Agent 情绪对应的表情符号 */
export function emotionEmoji(emotion: string): string {
  const map: Record<string, string> = {
    neutral: '😐',
    happy: '😊',
    worried: '😰',
    thinking: '🤔',
    scheming: '😈',
  }
  return map[emotion] ?? '😐'
}

/** 涨跌颜色 class */
export function pnlClass(v: number): string {
  if (v > 0) return 'color-up'
  if (v < 0) return 'color-down'
  return 'color-flat'
}

/** HTML 转义 */
export function esc(s: string): string {
  const el = document.createElement('div')
  el.textContent = s
  return el.innerHTML
}
