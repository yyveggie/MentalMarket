<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const bias = computed(() => store.biasStats)

const phaseLabel = computed(() => {
  if (!bias.value.bubble_flag) return '无'
  return bias.value.bubble_phase === 'inflating' ? '膨胀中' : '收缩中'
})

const corrPct = computed(() =>
  bias.value.confidence_price_correlation !== null
    ? (bias.value.confidence_price_correlation * 100).toFixed(0)
    : null,
)
</script>

<template>
  <div class="card">
    <div class="card-title">泡沫检测
      <span class="info-btn" @mouseenter="showTip('bb')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'bb'" class="custom-tooltip">基于信心与价格偏离度的相关性检测自我实现预言式泡沫，相关系数越高泡沫信号越强</div>
    </div>
    <div class="metric-center">
      <span class="metric-value" :style="{ color: bias.bubble_flag ? '#f44336' : '#26a69a' }">
        {{ phaseLabel }}
      </span>
      <span class="metric-desc">泡沫状态</span>
    </div>
    <div class="metric-footer">
      <span v-if="corrPct !== null">信心-价格相关 {{ corrPct }}%</span>
      <span v-if="bias.avg_confidence !== null">平均信心 {{ bias.avg_confidence.toFixed(2) }}</span>
      <span v-if="bias.avg_deviation_pct !== null">平均偏离 {{ bias.avg_deviation_pct.toFixed(2) }}%</span>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';

.metric-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
}
.metric-value {
  font-size: 32px;
  font-weight: 800;
  font-family: var(--font-mono);
  line-height: 1.1;
}
.metric-desc {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 4px;
}
.metric-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  padding-top: 8px;
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}
</style>
