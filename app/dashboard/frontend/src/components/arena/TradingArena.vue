<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtCn, emotionLabel } from '@/utils/formatters'

const emit = defineEmits<{
  'agent-click': [agentId: number]
}>()

const store = useMarketStore()

const groups = computed(() => {
  const thinkingSet = new Set(store.thinkingAgents.map((t) => t.agent_id))

  return [0, 1, 2].map((level) => {
    const agents = store.holdings.filter((h) => h.tom_level === level)
    const tom = store.tomSummary[String(level)]
    const buyCount = agents.filter((a) => {
      const vis = store.agentVisuals.get(a.agent_id)
      return vis?.lastAction === 'buy'
    }).length
    const sellCount = agents.filter((a) => {
      const vis = store.agentVisuals.get(a.agent_id)
      return vis?.lastAction === 'sell'
    }).length
    const thinkingCount = agents.filter((a) => thinkingSet.has(a.agent_id)).length

    return {
      level,
      count: agents.length,
      avgWealth: tom?.avg_wealth ?? 0,
      avgReturn: tom?.avg_return_pct ?? 0,
      roiPct: tom?.roi_pct ?? 0,
      winRate: tom?.win_rate_trade_pct ?? 0,
      positiveReturnRatio: tom?.positive_return_ratio ?? 0,
      totalTrades: tom?.total_trades ?? 0,
      buyCount,
      sellCount,
      thinkingCount,
    }
  })
})

const recentActivity = computed(() => {
  return store.recentDecisions.slice(-8).reverse().map((d) => {
    const agent = store.agentById(d.agent_id)
    const vis = store.agentVisuals.get(d.agent_id)
    return {
      agentId: d.agent_id,
      tomLevel: d.tom_level,
      action: (d.action_executed?.action ?? d.action ?? 'hold').toLowerCase(),
      price: d.action_executed?.price,
      quantity: d.action_executed?.quantity,
      simTime: d.sim_time,
      emotion: vis?.emotion ?? 'neutral',
    }
  })
})
</script>

<template>
  <div class="market-pulse">
    <div v-if="store.holdings.length === 0" class="empty-state">
    </div>

    <template v-else>
      <div class="tom-bars">
        <div v-for="g in groups" :key="g.level" class="tom-bar" :class="`tom${g.level}`">
          <div class="bar-header">
            <span class="badge" :class="`badge-tom${g.level}`">ToM{{ g.level }}</span>
            <span class="bar-count">{{ g.count }}人</span>
          </div>
          <div class="bar-stats">
            <div class="bar-stat">
              <span class="bs-label">财富（平均）</span>
              <span class="bs-value">{{ fmtCn(g.avgWealth, 2) }}</span>
            </div>
            <div class="bar-stat">
              <span class="bs-label">收益率（平均）</span>
              <span class="bs-value" :class="g.avgReturn > 0 ? 'color-up' : g.avgReturn < 0 ? 'color-down' : ''">
                {{ g.avgReturn > 0 ? '+' : '' }}{{ g.avgReturn.toFixed(1) }}%
              </span>
            </div>
            <div class="bar-stat">
              <span class="bs-label">ROI</span>
              <span class="bs-value" :class="g.roiPct > 0 ? 'color-up' : g.roiPct < 0 ? 'color-down' : ''">
                {{ g.roiPct > 0 ? '+' : '' }}{{ g.roiPct.toFixed(1) }}%
              </span>
            </div>
            <div class="bar-stat">
              <span class="bs-label">胜率</span>
              <span class="bs-value" :class="g.winRate >= 50 ? 'color-up' : 'color-down'">{{ g.winRate.toFixed(0) }}%</span>
            </div>
            <div class="bar-stat">
              <span class="bs-label">正收益比</span>
              <span class="bs-value" :class="g.positiveReturnRatio >= 50 ? 'color-up' : 'color-down'">{{ g.positiveReturnRatio.toFixed(0) }}%</span>
            </div>
            <div class="bar-stat">
              <span class="bs-label">交易</span>
              <span class="bs-value">{{ g.totalTrades }}</span>
            </div>
            <div class="bar-stat">
              <span class="bs-label color-up">买</span>
              <span class="bs-value color-up">{{ g.buyCount }}</span>
            </div>
            <div class="bar-stat">
              <span class="bs-label color-down">卖</span>
              <span class="bs-value color-down">{{ g.sellCount }}</span>
            </div>
            <div v-if="g.thinkingCount" class="bar-stat">
              <span class="bs-label">思考</span>
              <span class="bs-value" style="color:var(--accent)">{{ g.thinkingCount }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="recentActivity.length" class="recent-strip">
        <span class="recent-label">最近动态</span>
        <div
          v-for="(act, i) in recentActivity"
          :key="i"
          class="act-chip"
          :class="act.action === 'buy' ? 'chip-buy' : act.action === 'sell' ? 'chip-sell' : 'chip-hold'"
          @click="emit('agent-click', act.agentId)"
        >
          <span>{{ emotionLabel(act.emotion) }}</span>
          <span class="chip-id">A{{ act.agentId }}</span>
          <span class="chip-action">{{ act.action === 'buy' ? '▲' : act.action === 'sell' ? '▼' : '─' }}</span>
          <span v-if="act.price" class="chip-detail">{{ fmt(act.price, 2) }}×{{ act.quantity }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.market-pulse {
  height: auto;
  max-height: 220px;
  padding: 8px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-dim);
}

.empty-icon { font-size: 20px; }
.empty-text { font-size: 12px; }

.tom-bars {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin-bottom: 8px;
}

.tom-bar {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px;
}

.bar-header {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 6px;
}

.bar-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
}

.bar-count {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

.bar-stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.bar-stat {
  text-align: center;
  min-width: 40px;
}

.bs-label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.bs-value {
  display: block;
  font-size: 15px;
  font-weight: 700;
  color: var(--heading);
  font-family: var(--font-mono);
}

.recent-strip {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}

.recent-label {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-dim);
  font-family: var(--font-mono);
  text-transform: uppercase;
  margin-right: 4px;
}

.act-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-family: var(--font-mono);
  cursor: pointer;
  border: 1px solid var(--border);
  transition: all 0.15s;
}

.act-chip:hover {
  border-color: var(--accent);
}

.chip-buy { background: var(--up-soft); }
.chip-sell { background: var(--down-soft); }
.chip-hold { background: rgba(255,255,255,0.02); }

.chip-id {
  font-weight: 700;
  color: var(--text-muted);
}

.chip-action {
  font-weight: 700;
}

.chip-buy .chip-action { color: var(--up); }
.chip-sell .chip-action { color: var(--down); }

.chip-detail {
  font-size: 9px;
  color: var(--text-dim);
}
</style>
