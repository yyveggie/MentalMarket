<script setup lang="ts">
import { ref, computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmtCn, fmtPct } from '@/utils/formatters'

const store = useMarketStore()

type SortKey = 'return_pct' | 'wealth' | 'trade_count' | 'total_pnl'
const activeTab = ref<SortKey>('return_pct')

const TABS: { key: SortKey; label: string }[] = [
  { key: 'return_pct', label: '收益率' },
  { key: 'wealth', label: '总财富' },
  { key: 'total_pnl', label: '已实现盈亏' },
  { key: 'trade_count', label: '交易次数' },
]

interface Row {
  agent_id: number
  tom_level: number
  value: number
}

// 优先用服务端算好的排行榜（行情工作区不必拉取全部持仓）；没有时从本地持仓计算
const board = computed<{ total: number; top: Row[]; bottom: Row[] }>(() => {
  const key = activeTab.value
  const lb = store.leaderboard?.by_key?.[key]
  if (lb) return { total: store.leaderboard?.total ?? 0, top: lb.top, bottom: lb.bottom }
  const agents = store.holdings.filter((a) => a.agent_id > 0)
  const rows: Row[] = agents.map((a) => ({ agent_id: a.agent_id, tom_level: a.tom_level, value: Number(a[key] ?? 0) }))
  rows.sort((a, b) => b.value - a.value)
  return {
    total: rows.length,
    top: rows.slice(0, 10),
    bottom: rows.length > 10 ? rows.slice(-10).reverse() : [],
  }
})

function displayVal(v: number, key: SortKey): string {
  if (key === 'return_pct') return fmtPct(v)
  if (key === 'wealth' || key === 'total_pnl') return fmtCn(v, 2)
  return String(v)
}

function valClass(v: number, key: SortKey): string {
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
          <span class="arrow arrow-up">▲</span> 前 10
        </div>
        <div v-for="(a, i) in board.top" :key="a.agent_id" class="rank-row">
          <span class="rank-num">{{ i + 1 }}</span>
          <span class="agent-id">A{{ a.agent_id }}</span>
          <span class="badge" :class="`badge-tom${a.tom_level}`">T{{ a.tom_level }}</span>
          <span class="rank-val" :class="valClass(a.value, activeTab)">{{ displayVal(a.value, activeTab) }}</span>
        </div>
      </div>

      <div v-if="board.bottom.length" class="board-col">
        <div class="col-header">
          <span class="arrow arrow-down">▼</span> 后 10
        </div>
        <div v-for="(a, i) in board.bottom" :key="a.agent_id" class="rank-row bottom-row">
          <span class="rank-num">{{ board.total - 9 + i }}</span>
          <span class="agent-id">A{{ a.agent_id }}</span>
          <span class="badge" :class="`badge-tom${a.tom_level}`">T{{ a.tom_level }}</span>
          <span class="rank-val" :class="valClass(a.value, activeTab)">{{ displayVal(a.value, activeTab) }}</span>
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
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.board-col {
  min-width: 0;
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
  font-size: 12px;
  font-variant-numeric: tabular-nums;
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
  font-size: 12px;
  text-align: right;
  min-width: 0;
  flex-shrink: 1;
  white-space: nowrap;
}
</style>
