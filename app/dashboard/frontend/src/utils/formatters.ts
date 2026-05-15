export function fmt(v: number | null | undefined, decimals = 4): string {
  if (v == null || Number.isNaN(v)) return '-'
  return Number(v).toFixed(decimals)
}

export function fmtSimTime(t: number): string {
  if (t >= 3600) return `${(t / 3600).toFixed(1)}h`
  if (t >= 60) return `${(t / 60).toFixed(1)}m`
  return `${t.toFixed(1)}s`
}

export function fmtCompact(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return v.toFixed(0)
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

export function tomEmoji(level: number): string {
  return ['🔵', '🟢', '🟣'][level] ?? '⚪'
}

export function tomLabel(level: number): string {
  return `ToM${level}`
}

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
