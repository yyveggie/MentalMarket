import { ref, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import type { WSMessage } from '@/types/market'

const RECONNECT_DELAY = 2000
const HEARTBEAT_INTERVAL = 15000

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

  function connect() {
    cleanup()

    ws = new WebSocket(getWsUrl())

    ws.onopen = () => {
      store.connected = true
      reconnectCount.value = 0
      startHeartbeat()
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        switch (msg.type) {
          case 'full_state':
            store.applyFullState(msg.data)
            break
          case 'event_trade':
            store.applyTradeEvent(msg.data)
            break
          case 'event_decision':
            store.applyDecisionEvent(msg.data)
            break
        }
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
    store.connected = false
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

  return { connect, disconnect, reconnectCount }
}
