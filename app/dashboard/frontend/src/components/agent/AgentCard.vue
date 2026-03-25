<script setup lang="ts">
import { computed } from 'vue'
import type { AgentHolding } from '@/types/market'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, emotionEmoji, fmtCompact, pnlClass } from '@/utils/formatters'

const props = defineProps<{
  agent: AgentHolding
}>()

const store = useMarketStore()

const visual = computed(() => store.agentVisuals.get(props.agent.agent_id))
const tomBadgeClass = computed(() => `badge-tom${props.agent.tom_level}`)

const wealthChange = computed(() => {
  const w = props.agent.wealth
  const c = props.agent.cash
  if (w > c * 1.05) return 'up'
  if (w < c * 0.95) return 'down'
  return 'flat'
})
</script>

<template>
  <div class="agent-card" :class="{ thinking: visual?.phase === 'thinking' }">
    <div class="card-left">
      <div class="avatar" :class="tomBadgeClass">
        <span class="avatar-emoji">{{ emotionEmoji(visual?.emotion ?? 'neutral') }}</span>
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
      </div>

      <div class="card-stats">
        <span class="stat-item">
          💰 <b :class="`color-${wealthChange}`">{{ fmtCompact(agent.wealth) }}</b>
        </span>
        <span class="stat-item">
          💵 {{ fmtCompact(agent.cash) }}
        </span>
        <span class="stat-item">
          📦 {{ agent.total_shares }}
        </span>
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
  padding: 10px 12px;
  background: var(--surface-0);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--transition);
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
  width: 38px;
  height: 38px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid currentColor;
  background: var(--surface-2);
}

.avatar-emoji {
  font-size: 18px;
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
}

.agent-id {
  font-weight: 700;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--heading);
}

.card-stats {
  display: flex;
  gap: 10px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.stat-item b {
  font-weight: 700;
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
