import { onBeforeUnmount } from 'vue'

interface RafRenderOptions {
  /** 目标元素；不可见（display:none 或尺寸为 0）时跳过重绘，等它重新可见由 ResizeObserver 触发 */
  el?: () => Element | null | undefined
  /** 数据签名；与上次相同则跳过重绘（用于结构不变的图，如社交网络力导向图） */
  signature?: () => unknown
}

/**
 * 把同一帧内的多次重绘请求合并为一次 requestAnimationFrame 回调。
 * 每秒一次的 full_state 会同时替换多份数据，多个 watcher 各自触发时只会重绘一次。
 * 返回的函数可以直接作为 watch 回调使用（忽略传入参数）。
 */
export function useRafRender(render: () => void, options: RafRenderOptions = {}) {
  let handle: number | null = null
  let lastSignature: unknown = Symbol('initial')

  function isVisible(): boolean {
    const el = options.el?.()
    if (!el) return true
    return el.getClientRects().length > 0
  }

  function schedule(): void {
    if (handle != null) return
    handle = requestAnimationFrame(() => {
      handle = null
      if (!isVisible()) return
      if (options.signature) {
        const sig = options.signature()
        if (sig === lastSignature) return
        lastSignature = sig
      }
      render()
    })
  }

  onBeforeUnmount(() => {
    if (handle != null) cancelAnimationFrame(handle)
    handle = null
  })

  return schedule
}
