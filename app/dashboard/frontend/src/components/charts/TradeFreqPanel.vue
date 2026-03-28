<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const tomLabels: Record<number, string> = { 0: 'ToM0', 1: 'ToM1', 2: 'ToM2' }
const tomColors: Record<number, string> = { 0: '#78909c', 1: '#0288d1', 2: '#7c4dff' }
const tip = '按 ToM 阶数统计交易频率\n总交易 = 该阶层所有 Agent 的累计成交笔数\n交易笔数（平均） = 总交易 / Agent 数量'

const tradeFreqByTom = computed(() => {
  const result: Array<{ level: number; count: number; totalDecisions: number; avgPerAgent: number }> = []
  for (let level = 0; level <= 2; level++) {
    const agents = store.holdings.filter((h) => h.tom_level === level)
    if (!agents.length) continue
    const ts = store.tomSummary[String(level)]
    result.push({ level, count: agents.length, totalDecisions: ts?.total_trades ?? 0, avgPerAgent: ts?.avg_trades_per_agent ?? 0 })
  }
  return result
})
</script>

<template>
  <div class="card">
    <div class="card-title">交易频率分析
      <span class="info-btn" @mouseenter="showTip('tf')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'tf'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="wealth-list">
      <div v-for="t in tradeFreqByTom" :key="t.level" class="wealth-row">
        <div class="wealth-header">
          <span class="wealth-label" :style="{ color: tomColors[t.level] }">{{ tomLabels[t.level] }}</span>
          <span class="wealth-count">{{ t.count }} 人</span>
        </div>
        <div class="wealth-bar-bg">
          <div class="wealth-bar" :style="{ width: tradeFreqByTom.length ? ((t.avgPerAgent / Math.max(...tradeFreqByTom.map(w => w.avgPerAgent), 1)) * 100) + '%' : '0%', background: tomColors[t.level] }" />
        </div>
        <div class="wealth-nums">
          <span>总交易 {{ t.totalDecisions.toLocaleString() }}</span>
          <span>交易笔数（平均） {{ t.avgPerAgent.toFixed(1) }} 笔</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';
</style>
