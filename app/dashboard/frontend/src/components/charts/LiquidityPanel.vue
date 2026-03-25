<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const liquidity = computed(() => store.liquidityStats)
const tomLabels: Record<number, string> = { 0: 'ToM0', 1: 'ToM1', 2: 'ToM2' }
const tomColors: Record<number, string> = { 0: '#78909c', 1: '#0288d1', 2: '#7c4dff' }
const tip = '挂单 (Maker) = 提前挂在订单簿上被动成交的一方\n吃单 (Taker) = 主动发起成交的一方'
</script>

<template>
  <div class="card">
    <div class="card-title">流动性供给
      <span class="info-btn" @mouseenter="showTip('l')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'l'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="liq-list">
      <div v-for="level in [0, 1, 2]" :key="level" class="liq-row">
        <span class="liq-label" :style="{ color: tomColors[level] }">{{ tomLabels[level] }}</span>
        <div class="liq-bars">
          <div class="liq-bar-wrap"><span class="liq-tag">挂单</span><span class="liq-num">{{ (liquidity[String(level)]?.maker ?? 0).toLocaleString() }}</span></div>
          <div class="liq-bar-wrap"><span class="liq-tag">吃单</span><span class="liq-num">{{ (liquidity[String(level)]?.taker ?? 0).toLocaleString() }}</span></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';
</style>
