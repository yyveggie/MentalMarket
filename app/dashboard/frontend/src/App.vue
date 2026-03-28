<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useWebSocket } from '@/composables/useWebSocket'
import HeaderBar from '@/components/layout/HeaderBar.vue'
import SidePanel from '@/components/layout/SidePanel.vue'
import TradingArena from '@/components/arena/TradingArena.vue'
import DeviationChart from '@/components/charts/DeviationChart.vue'
import OrderBook from '@/components/charts/OrderBook.vue'
import TomAnalytics from '@/components/charts/TomAnalytics.vue'
import SentimentChart from '@/components/charts/SentimentChart.vue'
import MarketMicro from '@/components/charts/MarketMicro.vue'
import TechnicalIndicators from '@/components/charts/TechnicalIndicators.vue'
import IndexOverview from '@/components/charts/IndexOverview.vue'
import BroadVolumeCharts from '@/components/charts/BroadVolumeCharts.vue'
import SocialFeed from '@/components/social/SocialFeed.vue'
import SocialNetwork from '@/components/social/SocialNetwork.vue'
import KolPanel from '@/components/social/KolPanel.vue'
import AgentCard from '@/components/agent/AgentCard.vue'
import DecisionFlow from '@/components/agent/DecisionFlow.vue'
import AgentLeaderboard from '@/components/charts/AgentLeaderboard.vue'
import AnalyticsPanel from '@/components/charts/AnalyticsPanel.vue'

const store = useMarketStore()
const { connect, disconnect } = useWebSocket()

const sidePanelOpen = ref(false)
const selectedAgentId = ref<number | null>(null)

type HoldingSort = 'agent_id' | 'wealth' | 'return_pct' | 'trade_count'
const holdingSort = ref<HoldingSort>('agent_id')
const holdingSortAsc = ref(true)
const holdingTomFilter = ref<number | null>(null)

const holdingSortOptions = [
  { key: 'agent_id' as HoldingSort, label: 'ID' },
  { key: 'wealth' as HoldingSort, label: '财富' },
  { key: 'return_pct' as HoldingSort, label: '收益率' },
  { key: 'trade_count' as HoldingSort, label: '交易' },
]

const holdingMetricHints = [
  { key: 'avgWealth', label: '财富（平均）', tip: '该 ToM 组所有智能体当前总财富（现金+持仓市值）的平均值。' },
  { key: 'avgReturn', label: '收益率（平均）', tip: '该 ToM 组智能体收益率的平均值。单个收益率=（当前财富-初始资产）/初始资产。' },
  { key: 'roiPct', label: 'ROI', tip: '组级 ROI = （该组总财富-该组总初始资产）/该组总初始资产。' },
  { key: 'winRate', label: '胜率', tip: '胜率 = 盈利交易数 / (盈利交易数 + 亏损交易数) × 100%' },
  { key: 'positiveReturnRatio', label: '正收益比', tip: '正收益比占比 = 收益率大于 0 的人数 / 该组总人数。' },
  { key: 'totalTrades', label: '交易', tip: '该 ToM 组累计成交笔数总和。' },
  { key: 'buyCount', label: '买', tip: '最近一次已执行动作为买入（buy）的智能体数量。' },
  { key: 'sellCount', label: '卖', tip: '最近一次已执行动作为卖出（sell）的智能体数量。' },
  { key: 'thinkingCount', label: '思考', tip: '当前处于思考状态（正在推理/决策）的智能体数量。' },
]

function toggleHoldingSort(key: HoldingSort) {
  if (holdingSort.value === key) {
    holdingSortAsc.value = !holdingSortAsc.value
  } else {
    holdingSort.value = key
    holdingSortAsc.value = key === 'agent_id'
  }
}

const filteredHoldings = computed(() => {
  let list = [...store.holdings]
  if (holdingTomFilter.value !== null) {
    list = list.filter((a) => a.tom_level === holdingTomFilter.value)
  }
  const key = holdingSort.value
  const dir = holdingSortAsc.value ? 1 : -1
  list.sort((a, b) => ((a[key] ?? 0) - (b[key] ?? 0)) * dir)
  return list
})

function onAgentClick(agentId: number) {
  selectedAgentId.value = agentId
  sidePanelOpen.value = true
}

function closeSidePanel() {
  sidePanelOpen.value = false
  selectedAgentId.value = null
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(() => connect())
onUnmounted(() => disconnect())
</script>

<template>
  <div class="shell">
    <HeaderBar />

    <nav class="section-nav">
      <a class="nav-pill" href="#sec-index" @click.prevent="scrollTo('sec-index')">指数</a>
      <a class="nav-pill" href="#sec-holdings" @click.prevent="scrollTo('sec-holdings')">持仓</a>
      <a class="nav-pill" href="#sec-sentiment" @click.prevent="scrollTo('sec-sentiment')">情绪</a>
      <a class="nav-pill" href="#sec-social" @click.prevent="scrollTo('sec-social')">社交</a>
      <a class="nav-pill" href="#sec-tom" @click.prevent="scrollTo('sec-tom')">ToM</a>
      <a class="nav-pill" href="#sec-orderbook" @click.prevent="scrollTo('sec-orderbook')">订单簿</a>
      <a class="nav-pill" href="#sec-micro" @click.prevent="scrollTo('sec-micro')">微观</a>
      <a class="nav-pill" href="#sec-bias" @click.prevent="scrollTo('sec-bias')">偏差</a>
    </nav>

    <main class="main">
      <!-- 0. 市场概览：大盘 + 指数 -->
      <section id="sec-index">
        <IndexOverview />
      </section>

      <!-- 1. 持仓总览 -->
      <section id="sec-holdings">
        <div class="card pulse-holdings">
          <div class="card-title">
            持仓总览
            <span class="holdings-count">{{ filteredHoldings.length }}/{{ store.holdings.length }}</span>
          </div>
          <div class="holdings-toolbar">
            <div class="toolbar-group">
              <span class="toolbar-label">排序</span>
              <button v-for="s in holdingSortOptions" :key="s.key"
                class="toolbar-btn" :class="{ active: holdingSort === s.key }"
                @click="toggleHoldingSort(s.key)"
              >{{ s.label }}{{ holdingSort === s.key ? (holdingSortAsc ? ' ▲' : ' ▼') : '' }}</button>
            </div>
            <div class="toolbar-group">
              <span class="toolbar-label">ToM</span>
              <button class="toolbar-btn" :class="{ active: holdingTomFilter === null }" @click="holdingTomFilter = null">全部</button>
              <button v-for="t in [0, 1, 2]" :key="t" class="toolbar-btn" :class="{ active: holdingTomFilter === t, [`tom${t}-btn`]: true }" @click="holdingTomFilter = holdingTomFilter === t ? null : t">T{{ t }}</button>
            </div>
            <div class="toolbar-group metric-help-group">
              <span v-for="item in holdingMetricHints" :key="item.key" class="toolbar-help-item">
                <span class="toolbar-help-label">{{ item.label }}</span>
                <span class="help-icon" tabindex="0" aria-label="指标解释">?
                  <span class="help-pop">{{ item.tip }}</span>
                </span>
              </span>
            </div>
          </div>
          <TradingArena @agent-click="onAgentClick" />
          <div v-if="filteredHoldings.length > 0" class="holdings-section">
            <div class="holdings-grid-compact">
              <AgentCard
                v-for="agent in filteredHoldings"
                :key="agent.agent_id"
                :agent="agent"
                @click="onAgentClick(agent.agent_id)"
              />
            </div>
          </div>
        </div>
      </section>

      <!-- 1.5 决策流 -->
      <section id="sec-decisions">
        <DecisionFlow />
      </section>

      <!-- 2. 大盘走势 + 指数成交量 | 排行榜 -->
      <section class="grid-3-1">
        <BroadVolumeCharts />
        <AgentLeaderboard />
      </section>

      <!-- 3. 情绪/信心 + 偏离度/大盘 -->
      <section id="sec-sentiment" class="grid-2">
        <SentimentChart />
        <DeviationChart />
      </section>

      <!-- 3. 社交信息流 -->
      <section id="sec-social" class="social-section">
        <SocialFeed />
      </section>

      <!-- 3.5 社交网络图谱 + KOL 列表 -->
      <section class="grid-3-1">
        <SocialNetwork />
        <KolPanel />
      </section>

      <!-- 4. ToM 分析 -->
      <section id="sec-tom">
        <TomAnalytics />
      </section>

      <!-- 4. 订单簿（含价格走势） -->
      <section id="sec-orderbook">
        <OrderBook />
      </section>

      <!-- 5. 微观结构 + 技术指标 -->
      <section id="sec-micro" class="grid-2">
        <MarketMicro />
        <TechnicalIndicators />
      </section>

      <!-- 6. 深度分析面板 -->
      <section id="sec-bias">
        <AnalyticsPanel />
      </section>
    </main>

    <SidePanel
      :open="sidePanelOpen"
      :agent-id="selectedAgentId"
      @close="closeSidePanel"
    />
  </div>
</template>

<style scoped>
.shell {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  position: relative;
}

.main {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.main > section {
  margin-bottom: 16px;
}

.pulse-holdings {
  padding: 16px;
  overflow: hidden;
}

.holdings-count {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

.holdings-toolbar {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 3px;
}

.toolbar-label {
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-sans);
  margin-right: 4px;
}

.toolbar-btn {
  border: none;
  background: var(--surface-1);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}

.toolbar-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.toolbar-btn:hover:not(.active) {
  background: var(--surface-2);
}

.toolbar-btn.tom0-btn.active { background: var(--tom0-bg); color: var(--tom0); }
.toolbar-btn.tom1-btn.active { background: var(--tom1-bg); color: var(--tom1); }
.toolbar-btn.tom2-btn.active { background: var(--tom2-bg); color: var(--tom2); }

.metric-help-group {
  margin-left: auto;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-help-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.toolbar-help-label {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.help-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border: 1px solid var(--border);
  border-radius: 50%;
  font-size: 10px;
  line-height: 1;
  color: var(--text-dim);
  cursor: help;
  outline: none;
}

.help-pop {
  position: absolute;
  left: 50%;
  top: calc(100% + 8px);
  transform: translateX(-50%);
  min-width: 220px;
  max-width: 320px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text);
  font-size: 11px;
  font-family: var(--font-sans);
  line-height: 1.35;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  z-index: 30;
}

.help-icon:hover .help-pop,
.help-icon:focus .help-pop {
  opacity: 1;
  visibility: visible;
}

.holdings-section {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.ob-row > :first-child {
  min-width: 0;
}

.holdings-grid-compact {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 4px;
  max-height: 280px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-2) transparent;
}

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.grid-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
}

.grid-3 > * {
  min-width: 0;
  overflow: hidden;
}

.social-section {
  height: 400px;
}
.social-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
  height: 100%;
}
.social-grid > * {
  overflow-y: auto;
}

.holdings-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 280px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.empty-msg {
  text-align: center;
  color: var(--text-dim);
  padding: 20px;
  font-size: 12px;
}

.grid-3-1 {
  display: grid;
  grid-template-columns: 3fr 1fr;
  gap: 16px;
}

.section-nav {
  display: flex;
  gap: 2px;
  padding: 4px 20px;
  background: var(--surface-0);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.section-nav::-webkit-scrollbar { display: none; }

.nav-pill {
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--text-muted);
  text-decoration: none;
  white-space: nowrap;
  transition: all 0.15s;
  cursor: pointer;
}

.nav-pill:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

@media (max-width: 960px) {
  .grid-2, .grid-3, .grid-3-1 {
    grid-template-columns: 1fr;
  }
  .metric-help-group {
    margin-left: 0;
  }
  .arena-box {
    height: 300px;
  }
  .social-section {
    height: 280px;
  }
}
</style>
