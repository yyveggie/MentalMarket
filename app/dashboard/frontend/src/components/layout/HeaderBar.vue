<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtSimTime, fmtPct } from '@/utils/formatters'

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
const pctClass = computed(() => {
  const pct = broad.value?.pct_chg
  if (pct == null) return ''
  return pct > 0 ? 'color-up' : pct < 0 ? 'color-down' : ''
})
const arrow = computed(() => {
  const pct = broad.value?.pct_chg
  if (pct == null) return ''
  return pct > 0 ? '▲' : pct < 0 ? '▼' : '─'
})
const thinkingCount = computed(() => store.thinkingAgents.length)
const m = computed(() => store.metrics)
</script>

<template>
  <header class="header">
    <div class="header-left">
      <span class="brand">MentalMarket</span>
      <span class="conn-dot" :class="store.connected ? 'on' : 'off'" />
      <span class="conn-label">{{ store.connected ? '实时' : '离线' }}</span>
    </div>

    <button class="theme-toggle" @click="toggleTheme" :title="isDark ? '切换亮色模式' : '切换暗色模式'">
      {{ isDark ? '☀️' : '🌙' }}
    </button>

    <div class="header-pills">
      <div class="pill">📅 <b>D{{ store.tradingDay }}</b></div>
      <div class="pill">⏱ <b>T={{ fmtSimTime(store.simTime) }}</b></div>

      <div v-if="broad" class="pill" :class="pctClass">
        {{ broad.name }}
        <b v-if="broad.value != null">{{ fmt(broad.value, 1) }}</b>
        <span>{{ arrow }} {{ fmtPct(broad.pct_chg) }}</span>
      </div>

      <div v-if="broad" class="pill">
        <span class="color-up">▲{{ broad.up_count }}</span>
        <span class="color-down">▼{{ broad.down_count }}</span>
        <span>─{{ broad.flat_count }}</span>
      </div>

      <div class="pill">🧪 推理 <b>{{ m?.completed_decision_agents ?? 0 }}</b>/<b>{{ store.totalAgents }}</b></div>
      <div class="pill">🤖 成交 <b>{{ m?.completed_trade_agents ?? 0 }}</b>/<b>{{ store.totalAgents }}</b></div>
      <div class="pill">🧠 思考中 <b>{{ thinkingCount }}</b></div>
      <div class="pill">📝 决策 <b>{{ m?.unique_decision_agents_10s ?? 0 }}</b>/{{ m?.window_seconds ?? 10 }}s</div>
      <div class="pill">💹 挂单 <b>{{ m?.unique_order_agents_10s ?? 0 }}</b>/{{ m?.window_seconds ?? 10 }}s</div>
    </div>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 20px;
  background: var(--surface-0);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 50;
  flex-wrap: wrap;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
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
  font-size: 9px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-dim);
}

.header-pills {
  display: flex;
  gap: 4px;
  flex-wrap: nowrap;
  margin-left: auto;
  overflow-x: auto;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  font-family: var(--font-mono);
  background: var(--surface-1);
  color: var(--text-muted);
  white-space: nowrap;
}

.pill b {
  color: var(--heading);
}

.theme-toggle {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface-1);
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
}

.theme-toggle:hover {
  background: var(--surface-2);
}
</style>
