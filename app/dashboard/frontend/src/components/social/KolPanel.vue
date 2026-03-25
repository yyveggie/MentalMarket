<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'

const store = useMarketStore()
const graph = computed(() => store.socialGraph || {})
const kolAgents = computed(() => graph.value.kol_agents || [])
const topFollowed = computed(() => graph.value.top_by_followers || [])
const stats = computed(() => ({
  kolCount: graph.value.kol_count ?? 0,
  kolThreshold: graph.value.kol_threshold ?? 0,
}))
</script>

<template>
  <div class="card kol-panel">
    <div class="card-title">KOL & 排行</div>

    <div class="kol-stats">
      <span>{{ stats.kolCount }} 位 KOL</span>
      <span>门槛 ≥{{ stats.kolThreshold }} 粉</span>
    </div>

    <div v-if="kolAgents.length" class="section">
      <div class="section-title">KOL 列表</div>
      <div class="agent-list">
        <div v-for="a in kolAgents" :key="a.agent_id" class="agent-row kol-row">
          <span class="agent-id">A{{ a.agent_id }}</span>
          <span class="badge kol-badge">KOL</span>
          <span class="metric">{{ a.followers }} 粉</span>
          <span class="metric influence">{{ a.influence }}</span>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">粉丝排行 Top 10</div>
      <div class="agent-list">
        <div v-for="(a, idx) in topFollowed.slice(0, 10)" :key="a.agent_id" class="agent-row">
          <span class="rank">{{ idx + 1 }}</span>
          <span class="agent-id">A{{ a.agent_id }}</span>
          <span v-if="a.is_kol" class="badge kol-badge">KOL</span>
          <span class="metric">{{ a.followers }} 粉</span>
          <span class="metric influence">{{ a.influence }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kol-panel {
  overflow-y: auto;
}

.kol-stats {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  margin-bottom: 12px;
}

.section {
  margin-bottom: 12px;
}

.section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.agent-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.agent-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  background: var(--surface-1);
}

.agent-row.kol-row {
  background: rgba(255, 152, 0, 0.08);
}

.rank {
  width: 16px;
  text-align: right;
  color: var(--text-muted);
  font-size: 10px;
}

.agent-id {
  font-weight: 500;
  color: var(--heading);
  min-width: 36px;
}

.kol-badge {
  background: var(--accent-3);
  color: #fff;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 600;
}

.metric {
  font-size: 10px;
  color: var(--text);
  font-family: var(--font-mono);
}

.metric.influence {
  color: var(--accent-2);
  margin-left: auto;
}
</style>
