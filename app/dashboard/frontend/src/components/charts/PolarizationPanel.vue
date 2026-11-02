<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const bias = computed(() => store.biasStats)
const tip = '极化指数 = 全体 Agent 情绪的标准差\n极端占比 = |sentiment|>0.7 的 Agent 比例\n茧房指数 = 关注者情绪方差的反向(越高越同质)\n同质性偏差 = 同向关注率超出随机基线的部分'
</script>

<template>
  <div class="card">
    <div class="card-title">群体极化与信息茧房
      <span class="info-btn" @mouseenter="showTip('p')" @mouseleave="hideTip">i</span>
      <div v-if="activeTooltip === 'p'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="stat-grid">
      <div class="stat-item">
        <span class="stat-label">极化指数</span>
        <span class="stat-value" :style="{ color: bias.polarization_index !== null && bias.polarization_index > 0.5 ? '#ef5350' : '' }">{{ bias.polarization_index !== null ? bias.polarization_index.toFixed(3) : '-' }}</span>
        <span class="stat-desc">情绪标准差</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">极端占比</span>
        <span class="stat-value" :style="{ color: bias.extreme_ratio !== null && bias.extreme_ratio > 0.3 ? '#ff9800' : '' }">{{ bias.extreme_ratio !== null ? (bias.extreme_ratio * 100).toFixed(1) + '%' : '-' }}</span>
        <span class="stat-desc">|sentiment|>0.7</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">茧房指数</span>
        <span class="stat-value" :style="{ color: bias.echo_chamber_index !== null && bias.echo_chamber_index > 0.8 ? '#e040fb' : '' }">{{ bias.echo_chamber_index !== null ? bias.echo_chamber_index.toFixed(3) : '-' }}</span>
        <span class="stat-desc">信息流同质性</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">同质性偏差</span>
        <span class="stat-value" :style="{ color: bias.homophily_excess !== null && bias.homophily_excess > 0.1 ? '#ff6d00' : '' }">{{ bias.homophily_excess !== null ? (bias.homophily_excess > 0 ? '+' : '') + bias.homophily_excess.toFixed(3) : '-' }}</span>
        <span class="stat-desc">超出随机基线</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';
</style>
