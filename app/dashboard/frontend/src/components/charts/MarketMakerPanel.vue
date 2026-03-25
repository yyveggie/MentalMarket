<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const tip = '做市商(agent_id=0)的隐含补贴统计\n现金注入 = Agent卖出时做市商"凭空支付"的现金\n现金吸收 = Agent买入时做市商"凭空收到"的现金\n净补贴 = 注入 - 吸收，正值说明市场是正和'

const mm = computed(() => store.mmSubsidy)
const netSubsidy = computed(() => mm.value.cash_injected - mm.value.cash_absorbed)
const netShares = computed(() => mm.value.shares_created - mm.value.shares_absorbed)

function fmt(v: number): string {
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toFixed(0)
}
</script>

<template>
  <div class="card">
    <div class="card-title">做市商补贴
      <span class="info-btn" @mouseenter="showTip('mm')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'mm'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="stat-grid">
      <div class="stat-item">
        <span class="stat-label">净现金补贴</span>
        <span class="stat-value num" :style="{ color: netSubsidy > 0 ? '#ef5350' : '#26a69a' }">{{ fmt(netSubsidy) }}</span>
        <span class="stat-desc">{{ netSubsidy > 0 ? '正和（市场被补贴）' : '负和或零和' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">净股票创造</span>
        <span class="stat-value num" :style="{ color: netShares > 0 ? '#ff9800' : '#26a69a' }">{{ fmt(netShares) }}</span>
        <span class="stat-desc">凭空创造的股票数</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">现金注入</span>
        <span class="stat-value num">{{ fmt(mm.cash_injected) }}</span>
        <span class="stat-desc">Agent卖给做市商获得</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">现金吸收</span>
        <span class="stat-value num">{{ fmt(mm.cash_absorbed) }}</span>
        <span class="stat-desc">Agent从做市商买入支付</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">做市商成交笔数</span>
        <span class="stat-value num">{{ mm.trade_count.toLocaleString() }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';
</style>
