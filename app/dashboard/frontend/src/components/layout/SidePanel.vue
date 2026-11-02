<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, tomLabel, emotionLabel, fmtPct } from '@/utils/formatters'
import ReasoningChain from '@/components/agent/ReasoningChain.vue'

const props = defineProps<{
  open: boolean
  agentId: number | null
}>()

const emit = defineEmits<{
  close: []
}>()

const store = useMarketStore()

const agent = computed(() => {
  if (props.agentId == null) return null
  return store.agentById(props.agentId) ?? null
})

const visual = computed(() => {
  if (props.agentId == null) return null
  return store.agentVisuals.get(props.agentId) ?? null
})

const agentDecisions = computed(() => {
  if (props.agentId == null) return []
  return store.recentDecisions
    .filter((d) => d.agent_id === props.agentId)
    .slice(-20)
    .reverse()
})

const tomClass = computed(() => `badge-tom${agent.value?.tom_level ?? 0}`)
</script>

<template>
  <Transition name="slide">
    <aside v-if="open && agent" class="side-panel">
      <div class="panel-header">
        <div class="agent-avatar" :class="tomClass">
          <span class="avatar-emoji">T{{ agent?.tom_level ?? 0 }}</span>
          <span class="avatar-id">A{{ agent.agent_id }}</span>
        </div>
        <div class="agent-meta">
          <div class="agent-name">
            Agent #{{ agent.agent_id }}
            <span class="badge" :class="tomClass">ToM{{ agent.tom_level }}</span>
          </div>
          <div class="agent-type">{{ tomLabel(agent.tom_level) }}</div>
        </div>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="panel-body">
        <section class="section">
          <h3 class="section-title">财务状况</h3>
          <div class="stat-grid">
            <div class="stat">
              <span class="stat-label">总财富</span>
              <span class="stat-value">{{ fmt(agent.wealth, 0) }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">现金</span>
              <span class="stat-value">{{ fmt(agent.cash, 0) }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">持股</span>
              <span class="stat-value">{{ agent.total_shares }}</span>
            </div>
          </div>
          <div v-if="agent.current_positions_text" class="positions-text">
            持仓 {{ agent.current_positions_text }}
          </div>
        </section>

        <section v-if="agent.tom_level > 0 && agentDecisions.length > 0 && agentDecisions[0].reasoning" class="section">
          <h3 class="section-title">最近心智推理</h3>
          <div class="mind-block">
            <span class="mind-label">{{ agent.tom_level === 2 ? 'tom1 + tom2 reasoning' : 'mental_reasoning' }}</span>
            <p>{{ agentDecisions[0].reasoning }}</p>
          </div>
        </section>

        <section class="section">
          <h3 class="section-title">推理历史</h3>
          <ReasoningChain :decisions="agentDecisions" />
        </section>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.side-panel {
  position: absolute;
  top: 0;
  right: 0;
  width: 380px;
  height: 100%;
  background: var(--surface-0);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  z-index: 60;
  overflow: hidden;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
  flex-shrink: 0;
}

.agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 2px solid currentColor;
  position: relative;
}

.avatar-emoji {
  font-size: 20px;
  line-height: 1;
}

.avatar-id {
  font-size: 8px;
  font-weight: 700;
  font-family: var(--font-mono);
  opacity: 0.7;
}

.agent-meta {
  flex: 1;
}

.agent-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--heading);
  display: flex;
  align-items: center;
  gap: 6px;
}

.agent-type {
  font-size: 11px;
  color: var(--text-dim);
}

.close-btn {
  width: 28px;
  height: 28px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition);
}

.close-btn:hover {
  background: var(--down-soft);
  border-color: var(--down);
  color: var(--down);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.section {
  margin-bottom: 16px;
}

.section-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 8px;
  font-family: var(--font-mono);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.stat {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px;
  text-align: center;
}

.stat-label {
  display: block;
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  margin-bottom: 2px;
}

.stat-value {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: var(--heading);
  font-family: var(--font-mono);
}

.positions-text {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.mind-block {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
  margin-bottom: 6px;
}

.mind-label {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  color: var(--accent-2);
  font-family: var(--font-mono);
  margin-bottom: 3px;
}

.mind-block p {
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
  word-break: break-all;
}
</style>
