<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip } from '@/composables/useTooltip'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const bias = computed(() => store.biasStats)
const tip = '按 Agent 当前持仓未实现盈亏分类行为\n亏损时统计持有/卖出/买入的比例\n盈利时同理，反映损失厌恶和处置效应\n\n支持按 ToM 阶层筛选查看'

const selectedTom = ref<string>('all')
const tomOptions = ['all', '0', '1', '2'] as const
const tomLabels: Record<string, string> = { all: '全部', '0': 'ToM0', '1': 'ToM1', '2': 'ToM2' }
const tomColors: Record<string, string> = { all: '', '0': '#78909c', '1': '#0288d1', '2': '#7c4dff' }

function countersFor(tom: string) {
  if (tom === 'all') {
    return {
      loss_hold: bias.value.loss_hold,
      loss_sell: bias.value.loss_sell,
      loss_buy: bias.value.loss_buy,
      gain_hold: bias.value.gain_hold,
      gain_sell: bias.value.gain_sell,
      gain_buy: bias.value.gain_buy,
    }
  }
  const byTom = bias.value.loss_gain_by_tom?.[tom]
  if (!byTom) return { loss_hold: 0, loss_sell: 0, loss_buy: 0, gain_hold: 0, gain_sell: 0, gain_buy: 0 }
  return byTom
}

const currentCounters = computed(() => countersFor(selectedTom.value))
const lossTotal = computed(() => currentCounters.value.loss_hold + currentCounters.value.loss_sell + currentCounters.value.loss_buy)
const gainTotal = computed(() => currentCounters.value.gain_hold + currentCounters.value.gain_sell + currentCounters.value.gain_buy)
const lossHoldPct = computed(() => lossTotal.value > 0 ? (currentCounters.value.loss_hold / lossTotal.value * 100).toFixed(1) : null)
const lossSellPct = computed(() => lossTotal.value > 0 ? (currentCounters.value.loss_sell / lossTotal.value * 100).toFixed(1) : null)
const gainSellPct = computed(() => gainTotal.value > 0 ? (currentCounters.value.gain_sell / gainTotal.value * 100).toFixed(1) : null)
const gainHoldPct = computed(() => gainTotal.value > 0 ? (currentCounters.value.gain_hold / gainTotal.value * 100).toFixed(1) : null)
</script>

<template>
  <div class="card">
    <div class="card-title">损失厌恶分析
      <span class="info-btn" @mouseenter="showTip('la')" @mouseleave="hideTip">❕</span>
      <div v-if="activeTooltip === 'la'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="tom-tabs">
      <button
        v-for="opt in tomOptions" :key="opt"
        :class="['tom-tab', { active: selectedTom === opt }]"
        :style="selectedTom === opt && tomColors[opt] ? { borderColor: tomColors[opt], color: tomColors[opt] } : {}"
        @click="selectedTom = opt"
      >{{ tomLabels[opt] }}</button>
    </div>
    <div class="loss-aversion">
      <div class="la-section">
        <div class="la-header" style="color: #ef5350">亏损时行为 <span class="la-count">({{ lossTotal }}次)</span></div>
        <div class="la-bars">
          <div class="la-row"><span class="la-label">死扛不卖</span><div class="la-bar-bg"><div class="la-bar" :style="{ width: (lossHoldPct ?? 0) + '%', background: '#ef5350' }" /></div><span class="la-pct">{{ lossHoldPct ?? '-' }}%</span></div>
          <div class="la-row"><span class="la-label">割肉止损</span><div class="la-bar-bg"><div class="la-bar" :style="{ width: (lossSellPct ?? 0) + '%', background: '#ff9800' }" /></div><span class="la-pct">{{ lossSellPct ?? '-' }}%</span></div>
        </div>
      </div>
      <div class="la-section">
        <div class="la-header" style="color: #26a69a">盈利时行为 <span class="la-count">({{ gainTotal }}次)</span></div>
        <div class="la-bars">
          <div class="la-row"><span class="la-label">落袋为安</span><div class="la-bar-bg"><div class="la-bar" :style="{ width: (gainSellPct ?? 0) + '%', background: '#26a69a' }" /></div><span class="la-pct">{{ gainSellPct ?? '-' }}%</span></div>
          <div class="la-row"><span class="la-label">继续持有</span><div class="la-bar-bg"><div class="la-bar" :style="{ width: (gainHoldPct ?? 0) + '%', background: '#0288d1' }" /></div><span class="la-pct">{{ gainHoldPct ?? '-' }}%</span></div>
        </div>
      </div>
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
.la-count {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-dim);
  margin-left: 4px;
}
</style>
