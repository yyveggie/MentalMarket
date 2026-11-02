/**
 * 离线回放：打包页面里内嵌了一段录好的 WebSocket 推送流（scripts/record_replay.py 录制、
 * scripts/build_replay.py 打包），这里按原始时间间隔把消息喂给与实时模式相同的处理函数。
 *
 * 数据来源（二选一，由打包脚本写入 window）：
 *   window.__MM_REPLAY_B64__  gzip 压缩后 base64 的 NDJSON（默认，用浏览器自带的 DecompressionStream 解压）
 *   window.__MM_REPLAY_TEXT__ 未压缩的 NDJSON
 */
import { reactive } from 'vue'

interface ReplayFrame {
  t: number
  raw: string
}

declare global {
  interface Window {
    __MM_REPLAY_B64__?: string
    __MM_REPLAY_TEXT__?: string
    __MM_REPLAY_TITLE__?: string
  }
}

export const replay = reactive({
  active: false,
  ready: false,
  playing: false,
  ended: false,
  speed: 1,
  index: 0,
  total: 0,
  elapsed: 0,
  duration: 0,
  error: '',
  title: '',
})

const SPEEDS = [0.5, 1, 2, 4, 8]
let frames: ReplayFrame[] = []
let handler: ((raw: string) => void) | null = null
let timer: ReturnType<typeof setTimeout> | null = null
let lastTick = 0

export function replayAvailable(): boolean {
  return typeof window !== 'undefined' && (!!window.__MM_REPLAY_B64__ || !!window.__MM_REPLAY_TEXT__)
}

async function decodeRecording(): Promise<string> {
  if (window.__MM_REPLAY_TEXT__) return window.__MM_REPLAY_TEXT__
  const b64 = window.__MM_REPLAY_B64__ ?? ''
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('当前浏览器不支持解压内嵌数据，请用 Chrome / Edge / Safari 16.4 及以上打开')
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))
  return await new Response(stream).text()
}

function parseFrames(text: string): ReplayFrame[] {
  const out: ReplayFrame[] = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    try {
      const obj = JSON.parse(line) as { t: number; raw: string }
      if (typeof obj.raw === 'string') out.push({ t: Number(obj.t) || 0, raw: obj.raw })
    } catch {
      /* 跳过损坏行 */
    }
  }
  out.sort((a, b) => a.t - b.t)
  return out
}

function tick() {
  timer = null
  if (!replay.playing) return
  const now = performance.now()
  const dt = ((now - lastTick) / 1000) * replay.speed
  lastTick = now
  replay.elapsed = Math.min(replay.duration, replay.elapsed + dt)
  while (replay.index < frames.length && frames[replay.index].t <= replay.elapsed) {
    try {
      handler?.(frames[replay.index].raw)
    } catch (e) {
      console.error('[replay] frame error', e)
    }
    replay.index++
  }
  if (replay.index >= frames.length) {
    replay.playing = false
    replay.ended = true
    return
  }
  timer = setTimeout(tick, 40)
}

export function replayPlay() {
  if (!replay.ready || replay.ended || replay.playing) return
  replay.playing = true
  lastTick = performance.now()
  if (timer == null) timer = setTimeout(tick, 0)
}

export function replayPause() {
  replay.playing = false
  if (timer != null) {
    clearTimeout(timer)
    timer = null
  }
}

export function replayToggle() {
  if (replay.playing) replayPause()
  else replayPlay()
}

export function replaySetSpeed(v: number) {
  replay.speed = SPEEDS.includes(v) ? v : 1
}

export function replaySpeeds(): number[] {
  return SPEEDS
}

/** 重新播放：页面状态由消息流累积而来，最干净的复位就是重新加载 */
export function replayRestart() {
  location.reload()
}

/** 由 useWebSocket.connect() 在检测到内嵌数据时调用；onMessage 与实时 WebSocket 的处理函数相同 */
export async function startReplay(onMessage: (raw: string) => void): Promise<void> {
  handler = onMessage
  replay.active = true
  replay.title = window.__MM_REPLAY_TITLE__ ?? ''
  try {
    const text = await decodeRecording()
    frames = parseFrames(text)
    if (!frames.length) throw new Error('回放数据为空')
    replay.total = frames.length
    replay.duration = frames[frames.length - 1].t
    replay.ready = true
    replayPlay()
  } catch (e) {
    replay.error = e instanceof Error ? e.message : String(e)
    console.error('[replay]', e)
  }
}

export function formatClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r < 10 ? '0' : ''}${r}`
}
