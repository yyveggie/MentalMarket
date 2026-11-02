<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtPct } from '@/utils/formatters'
import { describeSimClock } from '@/utils/simTime'
import { replay } from '@/composables/useReplay'

const store = useMarketStore()

const isDark = ref(false)
function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}
onMounted(() => {
  const saved = localStorage.getItem('theme')
  if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    isDark.value = true
    document.documentElement.setAttribute('data-theme', 'dark')
  }
})

const broad = computed(() => store.broadMarket)
const broadClass = computed(() => {
  const pct = broad.value?.pct_chg
  if (pct == null) return ''
  return pct > 0 ? 'color-up' : pct < 0 ? 'color-down' : ''
})
const clock = computed(() => describeSimClock(store.simTime, store.tradingDaySeconds))
const phaseLabel = computed(() => {
  const p = store.session?.phase
  if (p === 'open_call') return '开盘集合竞价'
  if (p === 'close_call') return '收盘集合竞价'
  return ''
})
const thinkingCount = computed(() => store.metrics?.thinking_count ?? store.thinkingAgents.length)
const m = computed(() => store.metrics)

// 行情跑马灯：各指数 代码 / 最新价 / 涨跌幅；内容复制两份做无缝循环
const tickerItems = computed(() =>
  [...store.indexSnapshot]
    .sort((a, b) => a.symbol.localeCompare(b.symbol))
    .map((r) => ({
      symbol: r.symbol,
      price: Number(r.close),
      pct: Number(r.pct_chg ?? 0),
    })),
)
const tickerLoop = computed(() => (tickerItems.value.length ? [...tickerItems.value, ...tickerItems.value] : []))
const tickerDuration = computed(() => `${Math.max(20, tickerItems.value.length * 4)}s`)
</script>

<template>
  <header class="header">
    <div class="header-left">
      <span class="brand">MentalMarket</span>
      <span class="conn-dot" :class="store.connected ? 'on' : 'off'" />
      <span class="conn-label">{{ replay.active ? '回放' : store.connected ? '实时' : '离线' }}</span>
      <span class="clock" :title="`仿真时间 T=${fmt(store.simTime, 0)}s`">{{ clock }}</span>
      <span v-if="phaseLabel" class="phase" title="集合竞价期间订单只收集不撮合，结束时以单一价格集中成交">{{ phaseLabel }}</span>
      <span v-if="broad" class="broad" :class="broadClass">
        <span class="broad-name">{{ broad.name }}</span>
        <b v-if="broad.value != null">{{ fmt(broad.value, 2) }}</b>
        <span>{{ fmtPct(broad.pct_chg) }}</span>
        <span class="breadth"><em class="color-up">▲{{ broad.up_count }}</em> <em class="color-down">▼{{ broad.down_count }}</em></span>
      </span>
    </div>

    <div class="ticker" :class="{ empty: !tickerLoop.length }">
      <div v-if="tickerLoop.length" class="ticker-track" :style="{ animationDuration: tickerDuration }">
        <span v-for="(t, i) in tickerLoop" :key="`${t.symbol}-${i}`" class="tk">
          <span class="tk-sym">{{ t.symbol }}</span>
          <span class="tk-px" :class="t.pct > 0 ? 'color-up' : t.pct < 0 ? 'color-down' : ''">{{ fmt(t.price, 2) }}</span>
          <span class="tk-pct" :class="t.pct > 0 ? 'color-up' : t.pct < 0 ? 'color-down' : 'color-flat'">{{ fmtPct(t.pct) }}</span>
        </span>
      </div>
      <span v-else class="ticker-empty">等待行情数据</span>
    </div>

    <div class="sys" :title="'系统状态：完成推理/成交的 Agent 数、思考中的数量，以及最近窗口内的决策与挂单人数'">
      <span>推理 <b>{{ m?.completed_decision_agents ?? 0 }}</b>/{{ store.totalAgents }}</span>
      <span>成交 <b>{{ m?.completed_trade_agents ?? 0 }}</b>/{{ store.totalAgents }}</span>
      <span>思考中 <b>{{ thinkingCount }}</b></span>
      <span>决策 <b>{{ m?.unique_decision_agents_10s ?? 0 }}</b>/{{ m?.window_seconds ?? 10 }}s</span>
      <span>挂单 <b>{{ m?.unique_order_agents_10s ?? 0 }}</b>/{{ m?.window_seconds ?? 10 }}s</span>
    </div>

    <button class="theme-toggle" @click="toggleTheme" :title="isDark ? '切换亮色模式' : '切换暗色模式'">
      <svg v-if="isDark" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
      <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
    </button>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 6px 20px;
  background: var(--surface-0);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 50;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  font-variant-numeric: tabular-nums;
  min-height: 42px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  font-family: var(--font-mono);
}

.brand {
  font-size: 14px;
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--heading);
  font-family: var(--font-sans);
}

.conn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.conn-dot.on {
  background: var(--up);
  box-shadow: 0 0 5px var(--up);
  animation: pulse-glow 2s ease-in-out infinite;
}

.conn-dot.off {
  background: var(--down);
  box-shadow: 0 0 5px var(--down);
}

.conn-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-dim);
}

.clock {
  font-size: 12px;
  font-weight: 700;
  color: var(--heading);
  padding: 2px 8px;
  border-radius: 3px;
  background: var(--surface-1);
  margin-left: 4px;
}

.broad {
  display: inline-flex;
  align-items: baseline;
  white-space: nowrap;
  gap: 6px;
  font-size: 12px;
  padding-left: 10px;
  border-left: 1px solid var(--border-light);
}

.broad-name {
  color: var(--text-muted);
  font-size: 11px;
}

.broad b {
  font-size: 13px;
  font-weight: 800;
}

.breadth {
  font-size: 10px;
  color: var(--text-dim);
}

.breadth em {
  font-style: normal;
}

/* ── 跑马灯 ── */
.ticker {
  flex: 1;
  min-width: 120px;
  overflow: hidden;
  position: relative;
  height: 24px;
  mask-image: linear-gradient(to right, transparent, #000 4%, #000 96%, transparent);
}

.ticker-track {
  position: absolute;
  top: 0;
  left: 0;
  display: inline-flex;
  align-items: center;
  height: 100%;
  white-space: nowrap;
  animation-name: ticker-scroll;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
  will-change: transform;
}

.ticker:hover .ticker-track {
  animation-play-state: paused;
}

@keyframes ticker-scroll {
  from { transform: translateX(0); }
  to { transform: translateX(-50%); }
}

.tk {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 0 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  border-right: 1px solid var(--border);
}

.tk-sym {
  font-weight: 700;
  color: var(--heading);
}

.tk-px {
  font-weight: 600;
}

.tk-pct {
  font-size: 11px;
}

.ticker-empty {
  font-size: 11px;
  color: var(--text-dim);
  line-height: 24px;
  padding-left: 12px;
}

/* ── 系统状态（右侧小字） ── */
.sys {
  display: inline-flex;
  gap: 10px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
  flex-shrink: 0;
}

.sys b {
  color: var(--text-muted);
  font-weight: 600;
}

.theme-toggle {
  width: 26px;
  height: 26px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface-1);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
}

.theme-toggle:hover {
  background: var(--surface-2);
  color: var(--heading);
}

@media (max-width: 1100px) {
  .sys { display: none; }
}

.phase {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 3px;
  color: var(--accent-3);
  background: rgba(255, 152, 0, 0.14);
  white-space: nowrap;
}
</style>
