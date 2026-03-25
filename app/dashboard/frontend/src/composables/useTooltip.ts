import { ref } from 'vue'

export function useTooltip() {
  const activeTooltip = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | null = null

  function showTip(key: string) {
    if (timer) clearTimeout(timer)
    activeTooltip.value = key
  }

  function hideTip() {
    timer = setTimeout(() => { activeTooltip.value = null }, 150)
  }

  return { activeTooltip, showTip, hideTip }
}

export function pct(a: number, b: number): string {
  if (b <= 0) return '-'
  return ((a / b) * 100).toFixed(1) + '%'
}
