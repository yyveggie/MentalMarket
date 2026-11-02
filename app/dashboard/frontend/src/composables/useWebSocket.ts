import { ref, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import type { WSMessage } from '@/types/market'
import { replay, replayAvailable, startReplay } from '@/composables/useReplay'

const RECONNECT_DELAY = 2000
const HEARTBEAT_INTERVAL = 15000

// 当前订阅的主题（跨重连保持）
let currentTopics: string[] = []
let liveSocket: WebSocket | null = null

function sendSubscribe(reset = false) {
  if (liveSocket?.readyState === WebSocket.OPEN) {
    liveSocket.send(JSON.stringify({ type: 'subscribe', topics: currentTopics, reset }))
  }
}

/** 切换工作区时调用：只接收对应主题的数据 */
export function subscribeTopics(topics: string[]) {
  if (replay.active) return // 回放页面内嵌的是全部主题的数据，无需订阅
  const next = [...topics].sort()
  if (next.join(',') === currentTopics.join(',')) return
  currentTopics = next
  sendSubscribe(false)
}

export function useWebSocket() {
  const store = useMarketStore()
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  const reconnectCount = ref(0)

  function getWsUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/ws`
  }

  /** 实时 WebSocket 与离线回放共用的消息处理 */
  function handleRaw(raw: string) {
    const msg: WSMessage = JSON.parse(raw)
    switch (msg.type) {
      case 'state':
      case 'full_state':
        store.applyFullState(msg.data)
        if (store.resyncNeeded) {
          store.resyncNeeded = false
          if (replay.active) break // 回放无法向服务端要全量，忽略
          ws?.send(JSON.stringify({ type: 'resync' }))
        }
        break
      case 'event_trade':
        store.applyTradeEvent(msg.data)
        break
      case 'event_decision':
        store.applyDecisionEvent(msg.data)
        break
    }
  }

  function connect() {
    cleanup()

    if (replayAvailable()) {
      // 打包的回放页面：不连服务器，按录制的时间线喂消息
      store.connected = true
      void startReplay(handleRaw)
      return
    }

    ws = new WebSocket(getWsUrl())
    liveSocket = ws

    ws.onopen = () => {
      store.connected = true
      reconnectCount.value = 0
      // 重连后服务端会话是新的，客户端本地数据可能已过期：请求全量基线
      store.resetForResync()
      sendSubscribe(true)
      startHeartbeat()
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        handleRaw(event.data)
      } catch (e) {
        console.error('[WS] parse error:', e)
      }
    }

    ws.onclose = () => {
      store.connected = false
      stopHeartbeat()
      scheduleReconnect()
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function disconnect() {
    cleanup()
    ws?.close()
    ws = null
    if (!replay.active) store.connected = false
  }

  function cleanup() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    stopHeartbeat()
  }

  function scheduleReconnect() {
    reconnectCount.value++
    const delay = Math.min(RECONNECT_DELAY * Math.pow(1.5, reconnectCount.value - 1), 30000)
    reconnectTimer = setTimeout(connect, delay)
  }

  function startHeartbeat() {
    heartbeatTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_INTERVAL)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return { connect, disconnect, reconnectCount, subscribe: subscribeTopics }
}
