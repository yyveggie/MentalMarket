<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const tip = '计划遵循率 = 行动与计划意图一致的决策数 / 有明确计划的决策总数\n计划意图通过关键词匹配识别 (买入/卖出/持有)\n\n支持按 ToM 阶层筛选查看'

const selectedTom = ref<string>('all')
const tomOptions = ['all', '0', '1', '2'] as const
const tomLabels: Record<string, string> = { all: '全部', '0': 'ToM0', '1': 'ToM1', '2': 'ToM2' }
const tomColors: Record<string, string> = { all: '', '0': '#78909c', '1': '#0288d1', '2': '#7c4dff' }

function countersFor(tom: string) {
  if (tom === 'all') return store.planStats
  return store.planStats.by_tom?.[tom] ?? { total: 0, adhered: 0, deviated: 0 }
}

const current = computed(() => countersFor(selectedTom.value))

const planAdherence = computed(() => {
  const judged = current.value.adhered + current.value.deviated
  return judged > 0 ? (current.value.adhered / judged * 100).toFixed(1) : null
})
</script>

<template>
  <div class="card">
    <div class="card-title">计划执行追踪
      <span class="info-btn" @mouseenter="showTip('pe')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'pe'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="tom-tabs">
      <button
        v-for="opt in tomOptions" :key="opt"
        :class="['tom-tab', { active: selectedTom === opt }]"
        :style="selectedTom === opt && tomColors[opt] ? { borderColor: tomColors[opt], color: tomColors[opt] } : {}"
        @click="selectedTom = opt"
      >{{ tomLabels[opt] }}</button>
    </div>
    <div class="stat-grid">
      <div class="stat-item">
        <span class="stat-label">计划遵循率</span>
        <span class="stat-value" :style="{ color: planAdherence && parseFloat(planAdherence) > 50 ? '#26a69a' : '#ef5350' }">{{ planAdherence ?? '-' }}<small v-if="planAdherence">%</small></span>
      </div>
      <div class="stat-item"><span class="stat-label">遵循</span><span class="stat-value num" style="color: #26a69a">{{ current.adhered }}</span></div>
      <div class="stat-item"><span class="stat-label">偏离</span><span class="stat-value num" style="color: #ef5350">{{ current.deviated }}</span></div>
      <div class="stat-item"><span class="stat-label">有计划决策</span><span class="stat-value num">{{ current.total }}</span></div>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';

.tom-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}
.tom-tab {
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 600;
  border: 1.5px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.tom-tab:hover {
  border-color: var(--text-dim);
  color: var(--text);
}
.tom-tab.active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(var(--accent-rgb, 66, 165, 245), 0.08);
}
</style>
