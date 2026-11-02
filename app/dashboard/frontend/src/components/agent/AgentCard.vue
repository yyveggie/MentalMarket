<script setup lang="ts">
import { computed } from 'vue'
import type { AgentHolding } from '@/types/market'
import { useMarketStore } from '@/stores/marketStore'
import { emotionLabel, fmtCn, fmtInt, fmtPct } from '@/utils/formatters'

const props = defineProps<{
  agent: AgentHolding
}>()

const store = useMarketStore()

const visual = computed(() => store.agentVisuals.get(props.agent.agent_id))
const tomBadgeClass = computed(() => `badge-tom${props.agent.tom_level}`)
const returnClass = computed(() => {
  const r = props.agent.return_pct ?? 0
  return r > 0 ? 'color-up' : r < 0 ? 'color-down' : 'color-flat'
})
</script>

<template>
  <div class="agent-card" :class="{ thinking: visual?.phase === 'thinking' }">
    <div class="card-left">
      <div class="avatar" :class="tomBadgeClass">
        <span class="avatar-tom">T{{ agent.tom_level }}</span>
      </div>
    </div>

    <div class="card-body">
      <div class="card-top">
        <span class="agent-id">A{{ agent.agent_id }}</span>
        <span class="badge" :class="tomBadgeClass">ToM{{ agent.tom_level }}</span>
        <span
          v-if="visual?.lastAction"
          class="badge"
          :class="{
            'badge-buy': visual.lastAction === 'buy',
            'badge-sell': visual.lastAction === 'sell',
            'badge-hold': visual.lastAction === 'hold',
          }"
        >
          {{ visual.lastAction.toUpperCase() }}
        </span>
        <span class="state-label">{{ emotionLabel(visual?.emotion ?? 'neutral') }}</span>
        <span class="ret" :class="returnClass">{{ fmtPct(agent.return_pct) }}</span>
      </div>

      <div class="card-stats">
        <span class="stat-item"><span class="k">财富</span><b class="v">{{ fmtCn(agent.wealth, 2) }}</b></span>
        <span class="stat-item"><span class="k">现金</span><span class="v">{{ fmtCn(agent.cash, 2) }}</span></span>
        <span class="stat-item"><span class="k">持股</span><span class="v">{{ fmtInt(agent.total_shares) }}</span></span>
      </div>

      <div v-if="agent.current_positions_text" class="card-positions">
        {{ agent.current_positions_text }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-card {
  display: flex;
  gap: 10px;
  height: 88px;
  box-sizing: border-box;
  overflow: hidden;
  padding: 10px 12px;
  background: var(--surface-0);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--transition);
  font-variant-numeric: tabular-nums;
}

.agent-card:hover {
  background: var(--surface-1);
}

.agent-card.thinking {
  box-shadow: 0 0 8px rgba(41, 98, 255, 0.08);
}

.card-left {
  flex-shrink: 0;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid currentColor;
  background: var(--surface-2);
}

.avatar-tom {
  font-size: 12px;
  font-weight: 800;
  font-family: var(--font-mono);
  line-height: 1;
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-top {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 4px;
  min-width: 0;
}

.agent-id {
  font-weight: 700;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--heading);
}

.state-label {
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.ret {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 14px;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.stat-item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  white-space: nowrap;
}

.stat-item .k {
  color: var(--text-dim);
  font-size: 10px;
  white-space: nowrap;
}

.stat-item .v {
  text-align: right;
  white-space: nowrap;
}

.stat-item b {
  font-weight: 700;
  color: var(--heading);
}

.card-positions {
  margin-top: 3px;
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
