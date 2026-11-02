import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import {
  ColorType,
  CrosshairMode,
  createChart,
  type ChartOptions,
  type DeepPartial,
  type IChartApi,
} from 'lightweight-charts'

export interface ChartTheme {
  bg: string
  text: string
  grid: string
  axis: string
  up: string
  down: string
  accent: string
  muted: string
  heading: string
  font: string
}

/** 从 theme.css 的 CSS 变量读取图表配色，亮/暗主题切换时重新读取 */
export function readChartTheme(): ChartTheme {
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => (cs.getPropertyValue(name) || '').trim() || fallback
  return {
    bg: v('--surface-0', '#ffffff'),
    text: v('--chart-text', '#787b86'),
    grid: v('--chart-grid', '#e0e3eb'),
    axis: v('--chart-axis', '#b2b5be'),
    up: v('--up', '#ef5350'),
    down: v('--down', '#26a69a'),
    accent: v('--accent', '#2962ff'),
    muted: v('--text-muted', '#787b86'),
    heading: v('--heading', '#131722'),
    font: v('--font-mono', 'SF Mono, Menlo, Consolas, monospace'),
  }
}

/** #rrggbb → rgba(r,g,b,alpha)；非十六进制原样返回 */
export function withAlpha(color: string, alpha: number): string {
  const m = color.trim().match(/^#([0-9a-f]{6})$/i)
  if (!m) return color
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

export function themeChartOptions(th: ChartTheme): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: th.bg },
      textColor: th.text,
      fontFamily: th.font,
      fontSize: 11,
      panes: { separatorColor: th.grid, separatorHoverColor: withAlpha(th.accent, 0.15), enableResize: false },
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: th.grid },
      horzLines: { color: th.grid },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: th.axis, labelBackgroundColor: th.accent, width: 1 },
      horzLine: { color: th.axis, labelBackgroundColor: th.accent, width: 1 },
    },
    rightPriceScale: { borderColor: th.grid, scaleMargins: { top: 0.08, bottom: 0.05 } },
    timeScale: { borderColor: th.grid, rightOffset: 3, minBarSpacing: 2 },
  }
}

interface UseChartArgs {
  build: (chart: IChartApi, theme: ChartTheme) => void
  onTheme?: (theme: ChartTheme) => void
  options?: () => DeepPartial<ChartOptions>
}

/**
 * 创建/销毁 lightweight-charts 实例，自适应容器尺寸，并在 data-theme 切换时重新应用配色。
 */
export function useLightweightChart(container: Ref<HTMLElement | undefined>, args: UseChartArgs) {
  let chart: IChartApi | null = null
  let themeObserver: MutationObserver | null = null

  onMounted(() => {
    if (!container.value) return
    const theme = readChartTheme()
    chart = createChart(container.value, {
      autoSize: true,
      ...themeChartOptions(theme),
      ...(args.options?.() ?? {}),
    })
    args.build(chart, theme)

    themeObserver = new MutationObserver(() => {
      if (!chart) return
      const next = readChartTheme()
      chart.applyOptions(themeChartOptions(next))
      args.onTheme?.(next)
    })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  })

  onBeforeUnmount(() => {
    themeObserver?.disconnect()
    themeObserver = null
    chart?.remove()
    chart = null
  })

  return {
    getChart: () => chart,
  }
}
