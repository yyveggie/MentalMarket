<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt } from '@/utils/formatters'

const store = useMarketStore()
const scrollEl = ref<HTMLElement | null>(null)

const decisions = computed(() =>
  store.recentDecisions.slice(-30).reverse(),
)

watch(decisions, () => {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = 0
  })
})
</script>

<template>
  <div class="decision-flow card">
    <div v-if="store.thinkingAgents.length" class="thinking-bar">
      思考中: {{ store.thinkingAgents.map((a) => `A${a.agent_id}`).join(', ') }}
    </div>
    <div ref="scrollEl" class="flow-scroll">
      <div
        v-for="d in decisions"
        :key="`${d.agent_id}-${d.sim_time}`"
        class="decision-item"
      >
        <div class="d-header">
          <b>A{{ d.agent_id }}</b>
          <span class="badge" :class="`badge-tom${d.tom_level}`">ToM{{ d.tom_level }}</span>
          <span
            class="badge"
            :class="{
              'badge-buy': d.action?.toLowerCase() === 'buy',
              'badge-sell': d.action?.toLowerCase() === 'sell',
              'badge-hold': d.action?.toLowerCase() === 'hold',
            }"
          >{{ (d.action ?? 'hold').toUpperCase() }}</span>
          <span v-if="d.action_executed?.decision_scope" class="scope-tag">
            {{ d.action_executed.decision_scope }}
          </span>
          <span class="d-time">T={{ fmt(d.sim_time, 1) }}</span>
        </div>
        <div v-if="d.action_executed?.price && d.action_executed.quantity" class="d-detail">
          {{ fmt(d.action_executed.price, 2) }} x {{ d.action_executed.quantity }}
          <span v-if="d.action_executed.status" :class="d.action_executed.status === 'ok' ? 'color-up' : 'color-down'">
            {{ d.action_executed.status === 'ok' ? '✓' : '✗' }}
          </span>
        </div>
        <div v-if="d.reasoning" class="d-mind">
          <span class="mind-tag belief-tag">💭 心智推理</span>
          {{ d.reasoning }}
        </div>
        <div v-if="d.tool_trace?.length" class="d-tools">
          <div v-for="(tool, ti) in d.tool_trace.filter((t: any) => !(t.result?.status === 'failed' && ['follow', 'unfollow'].includes(t.args?.action)))" :key="ti" class="d-tool-item">
            <span class="mind-tag tool-tag">🔧 {{ tool.name }}</span>
            <span v-if="tool.args?.content" class="tool-content">{{ String(tool.args.content) }}</span>
            <span v-else-if="tool.args?.action" class="tool-content">{{ tool.args.action }}{{ tool.args.post_id ? ` #${tool.args.post_id}` : '' }}{{ tool.args.symbol ? ` ${tool.args.symbol}` : '' }}</span>
            <span v-if="tool.result?.status" :class="tool.result.status === 'ok' ? 'color-up' : 'color-down'" class="tool-status">{{ tool.result.status }}</span>
          </div>
        </div>
      </div>
      <div v-if="decisions.length === 0" class="empty"></div>
    </div>
  </div>
</template>

<style scoped>
.decision-flow {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-height: 520px;
}

.thinking-bar {
  padding: 6px 12px;
  background: rgba(41, 98, 255, 0.03);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  font-family: var(--font-mono);
  color: var(--accent);
  font-weight: 600;
  flex-shrink: 0;
}

.flow-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-2) transparent;
}

.decision-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.decision-item:hover {
  background: rgba(41, 98, 255, 0.02);
}

.d-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-family: var(--font-mono);
  font-size: 13px;
}

.d-time {
  color: var(--text-dim);
  font-size: 11px;
}

.scope-tag {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-dim);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0 4px;
}

.d-detail {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.d-mind {
  margin-top: 5px;
  font-size: 11px;
  color: var(--text);
  line-height: 1.45;
  padding: 6px 10px;
  background: var(--surface-1);
  border-radius: 4px;
  border-left: 3px solid var(--accent-2);
}

.mind-tag {
  font-size: 10px;
  font-weight: 700;
  font-family: var(--font-mono);
  margin-right: 4px;
}

.belief-tag { color: var(--accent-2); }
.intent-tag { color: var(--accent); }
.d-mind + .d-mind { margin-top: 3px; }

.d-tools {
  margin-top: 5px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.d-tool-item {
  font-size: 12px;
  padding: 4px 8px;
  background: var(--surface-1);
  border-radius: 4px;
  border-left: 3px solid var(--accent-1);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-tag {
  color: var(--accent-1);
  font-size: 11px;
}

.tool-content {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  word-break: break-word;
}

.tool-status {
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.empty {
  text-align: center;
  color: var(--text-dim);
  padding: 20px;
  font-size: 13px;
}
</style>
