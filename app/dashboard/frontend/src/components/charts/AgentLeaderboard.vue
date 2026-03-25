<script setup lang="ts">
import { ref, computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmtCompact, fmtPct } from '@/utils/formatters'

const store = useMarketStore()

type SortKey = 'return_pct' | 'wealth' | 'trade_count' | 'total_pnl'
const activeTab = ref<SortKey>('return_pct')

const TABS: { key: SortKey; label: string }[] = [
  { key: 'return_pct', label: '收益率' },
  { key: 'wealth', label: '总财富' },
  { key: 'total_pnl', label: '已实现盈亏' },
  { key: 'trade_count', label: '交易次数' },
]

const ranked = computed(() => {
  const agents = [...store.holdings].filter((a) => a.agent_id > 0)
  const key = activeTab.value
  agents.sort((a, b) => (b[key] ?? 0) - (a[key] ?? 0))
  return agents
})

const topN = computed(() => ranked.value.slice(0, 10))
const bottomN = computed(() => {
  const r = ranked.value
  if (r.length <= 10) return []
  return r.slice(-10).reverse()
})

function displayVal(agent: any, key: SortKey): string {
  const v = agent[key] ?? 0
  if (key === 'return_pct') return fmtPct(v)
  if (key === 'wealth' || key === 'total_pnl') return fmtCompact(v)
  return String(v)
}

function valClass(agent: any, key: SortKey): string {
  const v = agent[key] ?? 0
  if (key === 'trade_count') return ''
  if (v > 0) return 'color-up'
  if (v < 0) return 'color-down'
  return 'color-flat'
}
</script>

<template>
  <div class="card leaderboard">
    <div class="card-title">Agent 排行榜</div>

    <div class="tab-bar">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="board-split">
      <div class="board-col">
        <div class="col-header">
          <span class="arrow arrow-up">▲</span> Top 10
        </div>
        <div v-for="(a, i) in topN" :key="a.agent_id" class="rank-row">
          <span class="rank-num">{{ i + 1 }}</span>
          <span class="agent-id">A{{ a.agent_id }}</span>
          <span class="badge" :class="`badge-tom${a.tom_level}`">T{{ a.tom_level }}</span>
          <span class="rank-val" :class="valClass(a, activeTab)">{{ displayVal(a, activeTab) }}</span>
        </div>
      </div>

      <div v-if="bottomN.length" class="board-col">
        <div class="col-header">
          <span class="arrow arrow-down">▼</span> Bottom 10
        </div>
        <div v-for="(a, i) in bottomN" :key="a.agent_id" class="rank-row bottom-row">
          <span class="rank-num">{{ ranked.length - 9 + i }}</span>
          <span class="agent-id">A{{ a.agent_id }}</span>
          <span class="badge" :class="`badge-tom${a.tom_level}`">T{{ a.tom_level }}</span>
          <span class="rank-val" :class="valClass(a, activeTab)">{{ displayVal(a, activeTab) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.leaderboard {
  min-width: 0;
}

.tab-bar {
  display: flex;
  gap: 2px;
  margin-bottom: 12px;
  background: var(--surface-1);
  border-radius: 4px;
  padding: 2px;
}

.tab-btn {
  flex: 1;
  padding: 4px 8px;
  border: none;
  background: none;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-sans);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn.active {
  background: var(--surface-0);
  color: var(--accent);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.tab-btn:hover:not(.active) {
  color: var(--text);
}

.board-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.col-header {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.arrow-up { color: var(--up); font-size: 10px; }
.arrow-down { color: var(--down); font-size: 10px; }

.rank-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 3px;
  font-size: 11px;
  transition: background 0.1s;
}

.rank-row:hover {
  background: var(--surface-1);
}

.rank-num {
  width: 20px;
  text-align: right;
  color: var(--text-dim);
  font-size: 10px;
  font-family: var(--font-mono);
  flex-shrink: 0;
}

.agent-id {
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--heading);
  min-width: 32px;
  flex-shrink: 0;
}

.rank-val {
  margin-left: auto;
  font-weight: 700;
  font-family: var(--font-mono);
  font-size: 11px;
  flex-shrink: 0;
}
</style>
