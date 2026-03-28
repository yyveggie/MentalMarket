<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip, pct } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const tip = '感知帖数（平均） = 每次决策时 Agent 看到的社交帖子数（平均）\n新闻曝光率 = 感知到新闻帖的决策占比\n关注者帖子 = 来自已关注用户的帖子被看到的累计次数\n\n支持按 ToM 阶层筛选查看'

const selectedTom = ref<string>('all')
const tomOptions = ['all', '0', '1', '2'] as const
const tomLabels: Record<string, string> = { all: '全部', '0': 'ToM0', '1': 'ToM1', '2': 'ToM2' }
const tomColors: Record<string, string> = { all: '', '0': '#78909c', '1': '#0288d1', '2': '#7c4dff' }

function countersFor(tom: string) {
  if (tom === 'all') return store.cascadeStats
  return store.cascadeStats.by_tom?.[tom] ?? { total: 0, has_news: 0, total_perceived: 0, following_authors: 0 }
}

const current = computed(() => countersFor(selectedTom.value))
const avgPerceived = computed(() => current.value.total > 0 ? (current.value.total_perceived / current.value.total).toFixed(1) : '-')
const newsExposure = computed(() => pct(current.value.has_news, current.value.total))
</script>

<template>
  <div class="card">
    <div class="card-title">信息传播链路
      <span class="info-btn" @mouseenter="showTip('c')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'c'" class="custom-tooltip">{{ tip }}</div>
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
      <div class="stat-item"><span class="stat-label">感知帖数（平均）</span><span class="stat-value num">{{ avgPerceived }}</span></div>
      <div class="stat-item"><span class="stat-label">新闻曝光率</span><span class="stat-value">{{ newsExposure }}</span></div>
      <div class="stat-item"><span class="stat-label">关注者帖子</span><span class="stat-value num">{{ current.following_authors.toLocaleString() }}</span><span class="stat-desc">关注人发帖被看到次数</span></div>
      <div class="stat-item"><span class="stat-label">总感知事件</span><span class="stat-value num">{{ current.total.toLocaleString() }}</span></div>
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
