<script setup lang="ts">
/**
 * 市场事件流跑马灯：逐笔成交、集合竞价结果、Agent 成交回报、新闻、交易阶段切换。
 * 用 rAF 连续平移而不是 CSS 动画：新事件追加到队尾时不会让整条带子跳回起点。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtInt } from '@/utils/formatters'
import { describeSimClock } from '@/utils/simTime'

interface TickItem {
  key: string
  t: number
  kind: 'buy' | 'sell' | 'auction' | 'news' | 'phase' | 'agent'
  head: string
  body: string
}

const props = withDefaults(defineProps<{ speed?: number; maxItems?: number }>(), { speed: 42, maxItems: 60 })

const store = useMarketStore()
const wrap = ref<HTMLElement>()
const track = ref<HTMLElement>()
const queue = ref<TickItem[]>([])
const seen = new Set<string>()
let offset = 0
let raf: number | null = null
let lastTs = 0
const paused = ref(false)

function clock(t: number): string {
  return describeSimClock(t, store.tradingDaySeconds).split(' ')[1] ?? ''
}

/** 从各数据源收集最新事件（按仿真时间升序），只保留没见过的 */
const incoming = computed<TickItem[]>(() => {
  const out: TickItem[] = []
  for (const [sym, cda] of Object.entries(store.cdaBySymbol)) {
    for (const tr of (cda.recent_trades ?? []).slice(-8)) {
      const buy = tr.aggressor === 'bid'
      out.push({
        key: `t:${sym}:${tr.sim_time}:${tr.price}:${tr.quantity}:${tr.buyer_id}:${tr.seller_id}`,
        t: tr.sim_time,
        kind: buy ? 'buy' : 'sell',
        head: sym,
        body: `${fmt(tr.price, 2)} ×${fmtInt(tr.quantity)} ${buy ? '买' : '卖'}`,
      })
    }
  }
  for (const a of store.session?.auctions ?? []) {
    if (a.price == null) continue
    out.push({
      key: `a:${a.symbol}:${a.sim_time}:${a.kind}`,
      t: a.sim_time,
      kind: 'auction',
      head: a.kind === 'open' ? '开盘竞价' : '收盘竞价',
      body: `${a.symbol} ${fmt(a.price, 2)} 成交${fmtInt(a.volume)}`,
    })
  }
  for (const d of store.recentDecisions.slice(-40)) {
    const ae = d.action_executed ?? {}
    const act = String(ae.action ?? '')
    if ((act !== 'buy' && act !== 'sell') || ae.status !== 'ok') continue
    const filled = Number(ae.filled_quantity ?? 0)
    out.push({
      key: `d:${d.decision_id ?? `${d.agent_id}:${d.sim_time}`}`,
      t: d.sim_time,
      kind: 'agent',
      head: `A${d.agent_id}·T${d.tom_level}`,
      body: `${act === 'buy' ? '买入' : '卖出'} ${ae.symbol ?? ''} ${fmtInt(Number(ae.quantity ?? 0))}@${fmt(Number(ae.price ?? 0), 2)}${filled > 0 ? ` 成${fmtInt(filled)}` : ' 挂单'}`,
    })
  }
  for (const p of store.socialNews.slice(-6)) {
    const text = String(p.content ?? '').replace(/\s+/g, ' ').trim()
    if (!text) continue
    out.push({
      key: `n:${p.post_id}`,
      t: p.timestamp,
      kind: 'news',
      head: '新闻',
      body: text.length > 48 ? `${text.slice(0, 48)}…` : text,
    })
  }
  const phase = store.session?.phase
  if (phase && phase !== 'continuous') {
    const day = Math.floor(store.simTime / Math.max(1e-6, store.tradingDaySeconds)) + 1
    out.push({
      key: `p:${phase}:${day}`,
      t: store.simTime,
      kind: 'phase',
      head: phase === 'open_call' ? '开盘集合竞价' : '收盘集合竞价',
      body: `D${day} 只收单不撮合`,
    })
  }
  out.sort((a, b) => a.t - b.t)
  return out
})

watch(
  incoming,
  (items) => {
    let added = 0
    for (const it of items) {
      if (seen.has(it.key)) continue
      seen.add(it.key)
      queue.value.push(it)
      added++
    }
    if (added) {
      // 队列上限：从队头丢弃（队头正是已经滚过去的旧事件）
      while (queue.value.length > props.maxItems) {
        queue.value.shift()
        offset = Math.min(0, offset)
      }
      if (seen.size > 2000) {
        const keep = new Set(queue.value.map((q) => q.key))
        seen.clear()
        for (const k of keep) seen.add(k)
      }
    }
  },
  { immediate: true },
)

function step(ts: number) {
  raf = requestAnimationFrame(step)
  if (!track.value || !wrap.value) return
  const dt = lastTs ? Math.min(0.1, (ts - lastTs) / 1000) : 0
  lastTs = ts
  if (paused.value || queue.value.length === 0) return
  const contentW = track.value.scrollWidth
  const viewW = wrap.value.clientWidth
  if (contentW <= viewW) {
    // 内容不足一屏：靠右停住，不滚
    offset = 0
    track.value.style.transform = 'translateX(0)'
    return
  }
  offset -= props.speed * dt
  const first = track.value.firstElementChild as HTMLElement | null
  if (first && -offset >= first.offsetWidth + 1) {
    // 队头完全滚出视口：移除并把位移补回来，画面不跳
    offset += first.offsetWidth
    queue.value.shift()
  }
  track.value.style.transform = `translateX(${offset}px)`
}

onMounted(() => {
  raf = requestAnimationFrame(step)
})
onBeforeUnmount(() => {
  if (raf != null) cancelAnimationFrame(raf)
})
</script>

<template>
  <div
    ref="wrap"
    class="evt"
    title="市场事件流：逐笔成交 / 集合竞价 / Agent 成交回报 / 新闻，悬停暂停"
    @mouseenter="paused = true"
    @mouseleave="paused = false"
  >
    <div ref="track" class="evt-track">
      <span v-for="it in queue" :key="it.key" class="evt-item" :class="`k-${it.kind}`">
        <i class="evt-time">{{ clock(it.t) }}</i>
        <b class="evt-head">{{ it.head }}</b>
        <span class="evt-body">{{ it.body }}</span>
      </span>
    </div>
    <span v-if="!queue.length" class="evt-empty">等待市场事件</span>
  </div>
</template>

<style scoped>
.evt {
  flex: 1;
  min-width: 160px;
  height: 22px;
  overflow: hidden;
  position: relative;
  mask-image: linear-gradient(to right, transparent, #000 3%, #000 97%, transparent);
}

.evt-track {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
  will-change: transform;
}

.evt-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 0 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  border-right: 1px solid var(--border);
}

.evt-time {
  font-style: normal;
  font-size: 10px;
  color: var(--text-dim);
}

.evt-head {
  font-weight: 700;
  color: var(--heading);
}

.k-buy .evt-body { color: var(--up); }
.k-sell .evt-body { color: var(--down); }
.k-auction .evt-head,
.k-phase .evt-head { color: var(--accent-3); }
.k-agent .evt-head { color: var(--accent); }
.k-news .evt-body { color: var(--text-muted); }

.evt-empty {
  font-size: 10px;
  color: var(--text-dim);
  line-height: 22px;
  padding-left: 8px;
}
</style>
