<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useWebSocket } from '@/composables/useWebSocket'
import { replay, replayAvailable } from '@/composables/useReplay'
import ReplayBar from '@/components/layout/ReplayBar.vue'
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
import CollapseTransition from '@/components/layout/CollapseTransition.vue'
import AgentCard from '@/components/agent/AgentCard.vue'
import VirtualGrid from '@/components/ui/VirtualGrid.vue'
import DecisionFlow from '@/components/agent/DecisionFlow.vue'
import AgentLeaderboard from '@/components/charts/AgentLeaderboard.vue'
import AnalyticsPanel from '@/components/charts/AnalyticsPanel.vue'

const store = useMarketStore()
const { connect, disconnect, subscribe } = useWebSocket()

const sidePanelOpen = ref(false)
const selectedAgentId = ref<number | null>(null)

// ── 可折叠 Section ──
const STORAGE_KEY = 'mm-collapsed-sections'
type SectionKey = 'index' | 'holdings' | 'decisions' | 'broad' | 'sentiment' | 'social' | 'social-graph' | 'tom' | 'orderbook' | 'micro' | 'bias'

function loadCollapsed(): Set<SectionKey> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw) as SectionKey[])
  } catch {}
  return new Set()
}
function saveCollapsed(s: Set<SectionKey>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...s]))
}

const SECTION_DEFS: Array<{ key: SectionKey; label: string }> = [
  { key: 'index' as SectionKey, label: '市场概览' },
  { key: 'holdings' as SectionKey, label: '持仓总览' },
  { key: 'decisions' as SectionKey, label: '决策流' },
  { key: 'broad' as SectionKey, label: '指数成交量 / 排行榜' },
  { key: 'sentiment' as SectionKey, label: '情绪 / 偏离度' },
  { key: 'social' as SectionKey, label: '社交信息流' },
  { key: 'social-graph' as SectionKey, label: '社交网络 / KOL' },
  { key: 'tom' as SectionKey, label: 'ToM 分析' },
  { key: 'orderbook' as SectionKey, label: '订单簿' },
  { key: 'micro' as SectionKey, label: '微观结构 / 技术指标' },
  { key: 'bias' as SectionKey, label: '行为偏差分析' },
]

const collapsedSections = ref<Set<SectionKey>>(loadCollapsed())

// ── 工作区 Tab：把 11 个区块分成几组，避免单页 1 万多像素的长滚动 ──
type Workspace = 'all' | 'market' | 'trading' | 'agents' | 'social' | 'research'
const WORKSPACES: Array<{ key: Workspace; label: string; sections: SectionKey[] }> = [
  { key: 'market', label: '行情', sections: ['index', 'broad'] },
  { key: 'trading', label: '交易', sections: ['orderbook', 'micro'] },
  { key: 'agents', label: 'Agent', sections: ['holdings', 'decisions'] },
  { key: 'social', label: '社交', sections: ['social', 'social-graph'] },
  { key: 'research', label: '研究', sections: ['tom', 'sentiment', 'bias'] },
  { key: 'all', label: '全部', sections: [] },
]
const WS_KEY = 'mm-workspace'
// ?present=1：演示/录屏模式，隐藏导航条与区块开关，只保留顶栏和内容（配合 ?ws= 与 &only=index 使用）
const presentMode = new URLSearchParams(location.search).get('present') === '1'
const onlySections = (new URLSearchParams(location.search).get('only') ?? '').split(',').map((x) => x.trim()).filter(Boolean)
const workspace = ref<Workspace>(((): Workspace => {
  try {
    // 支持 ?ws=agents 这样的链接直达某个工作区
    const fromUrl = new URLSearchParams(location.search).get('ws') as Workspace | null
    if (fromUrl && WORKSPACES.some((w) => w.key === fromUrl)) return fromUrl
    if (replayAvailable()) return 'all' // 回放页面默认展示全部区块
    const raw = localStorage.getItem(WS_KEY) as Workspace | null
    if (raw && WORKSPACES.some((w) => w.key === raw)) return raw
  } catch {}
  return 'market'
})())
const WORKSPACE_TOPICS: Record<Workspace, string[]> = {
  market: ['market'],
  trading: ['market'],
  agents: ['agents'],
  social: ['social'],
  research: ['research', 'agents'],
  all: ['market', 'agents', 'social', 'research'],
}
// 只向服务端订阅当前工作区需要的主题，减少每秒推送的数据量
watch(workspace, (w) => subscribe(WORKSPACE_TOPICS[w] ?? WORKSPACE_TOPICS.all), { immediate: true })

function setWorkspace(key: Workspace) {
  workspace.value = key
  try { localStorage.setItem(WS_KEY, key) } catch {}
  document.querySelector('.main')?.scrollTo({ top: 0 })
}
// 顶栏区块开关：只列出当前工作区包含的区块
const visibleSectionDefs = computed(() => SECTION_DEFS.filter((d) => showSection(d.key)))

function showSection(key: SectionKey): boolean {
  if (onlySections.length) return onlySections.includes(key)
  if (workspace.value === 'all') return true
  const ws = WORKSPACES.find((w) => w.key === workspace.value)
  return ws ? ws.sections.includes(key) : true
}

// ── 交易大厅（像素小人）默认关闭，作为演示模式开关 ──
const ARENA_KEY = 'mm-demo-arena'
const arenaEnabled = ref<boolean>((() => { try { return localStorage.getItem(ARENA_KEY) === '1' } catch { return false } })())
function toggleArena() {
  arenaEnabled.value = !arenaEnabled.value
  try { localStorage.setItem(ARENA_KEY, arenaEnabled.value ? '1' : '0') } catch {}
}
function toggleSection(key: SectionKey) {
  if (collapsedSections.value.has(key)) {
    collapsedSections.value.delete(key)
  } else {
    collapsedSections.value.add(key)
  }
  saveCollapsed(collapsedSections.value)
}
function isSectionOpen(key: SectionKey) {
  return !collapsedSections.value.has(key)
}

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
    <ReplayBar v-if="replay.active" />

    <nav v-if="!presentMode" class="section-nav">
      <button
        v-for="w in WORKSPACES"
        :key="w.key"
        class="nav-pill"
        :class="{ active: workspace === w.key }"
        @click="setWorkspace(w.key)"
      >{{ w.label }}</button>
      <div class="section-chips">
        <button
          v-for="d in visibleSectionDefs"
          :key="d.key"
          class="chip-btn"
          :class="{ off: !isSectionOpen(d.key) }"
          :title="isSectionOpen(d.key) ? '点击隐藏该区块' : '点击显示该区块'"
          @click="toggleSection(d.key)"
        >{{ d.label }}</button>
      </div>
    </nav>

    <main class="main" :class="{ present: presentMode, replay: replay.active }">
      <!-- 0. 市场概览：大盘 + 指数 -->
      <section id="sec-index" v-show="showSection('index')">
        <CollapseTransition :show="isSectionOpen('index')">
          <div class="section-body">
            <IndexOverview />
          </div>
        </CollapseTransition>
      </section>

      <!-- 1. 持仓总览 -->
      <section id="sec-holdings" v-show="showSection('holdings')">
        <CollapseTransition :show="isSectionOpen('holdings')">
          <div class="section-body">
          <div class="card pulse-holdings">
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
              <div class="toolbar-group">
                <button class="toolbar-btn" :class="{ active: arenaEnabled }" :title="'显示/隐藏像素化交易大厅（演示用）'" @click="toggleArena">演示模式</button>
                <span class="holdings-count">{{ filteredHoldings.length }}/{{ store.holdings.length }}</span>
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
            <TradingArena v-if="arenaEnabled" @agent-click="onAgentClick" />
            <div v-if="filteredHoldings.length > 0" class="holdings-section">
              <VirtualGrid
                :items="filteredHoldings"
                :item-height="88"
                :min-col-width="260"
                :gap="4"
                :height="300"
                key-field="agent_id"
              >
                <template #item="{ item }">
                  <AgentCard :agent="item" @click="onAgentClick(item.agent_id)" />
                </template>
              </VirtualGrid>
            </div>
            </div>
          </div>
        </CollapseTransition>
      </section>

      <!-- 1.5 决策流 -->
      <section id="sec-decisions" v-show="showSection('decisions')">
        <CollapseTransition :show="isSectionOpen('decisions')">
          <div class="section-body">
            <DecisionFlow />
          </div>
        </CollapseTransition>
      </section>

      <!-- 2. 大盘走势 + 指数成交量 | 排行榜 -->
      <section v-show="showSection('broad')">
        <CollapseTransition :show="isSectionOpen('broad')">
          <div class="section-body grid-volume-board">
            <BroadVolumeCharts />
            <AgentLeaderboard />
          </div>
        </CollapseTransition>
      </section>

      <!-- 3. 情绪/信心 + 偏离度/大盘 -->
      <section id="sec-sentiment" v-show="showSection('sentiment')">
        <CollapseTransition :show="isSectionOpen('sentiment')">
          <div class="section-body grid-2">
            <SentimentChart />
            <DeviationChart />
          </div>
        </CollapseTransition>
      </section>

      <!-- 3. 社交信息流 -->
      <section id="sec-social" v-show="showSection('social')">
        <CollapseTransition :show="isSectionOpen('social')">
          <div class="section-body social-section">
            <SocialFeed />
          </div>
        </CollapseTransition>
      </section>

      <!-- 3.5 社交网络图谱 + KOL 列表 -->
      <section v-show="showSection('social-graph')">
        <CollapseTransition :show="isSectionOpen('social-graph')">
          <div class="section-body grid-3-1">
            <SocialNetwork />
            <KolPanel />
          </div>
        </CollapseTransition>
      </section>

      <!-- 4. ToM 分析 -->
      <section id="sec-tom" v-show="showSection('tom')">
        <CollapseTransition :show="isSectionOpen('tom')">
          <div class="section-body">
            <TomAnalytics />
          </div>
        </CollapseTransition>
      </section>

      <!-- 4. 订单簿（含价格走势） -->
      <section id="sec-orderbook" v-show="showSection('orderbook')">
        <CollapseTransition :show="isSectionOpen('orderbook')">
          <div class="section-body">
            <OrderBook />
          </div>
        </CollapseTransition>
      </section>

      <!-- 5. 微观结构 + 技术指标 -->
      <section id="sec-micro" v-show="showSection('micro')">
        <CollapseTransition :show="isSectionOpen('micro')">
          <div class="section-body grid-2">
            <MarketMicro />
            <TechnicalIndicators />
          </div>
        </CollapseTransition>
      </section>

      <!-- 6. 深度分析面板 -->
      <section id="sec-bias" v-show="showSection('bias')">
        <CollapseTransition :show="isSectionOpen('bias')">
          <div class="section-body">
            <AnalyticsPanel />
          </div>
        </CollapseTransition>
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
  /* 页面内各区块高度已固定，关闭滚动锚定，避免内部列表更新时视口被浏览器"纠正" */
  overflow-anchor: none;
}

.main > section {
  margin-bottom: 14px;
}

.main.present {
  padding: 10px 16px;
  overflow: hidden;
}

.main.replay {
  padding-bottom: 72px; /* 给底部回放控制条留位置 */
}

.section-chips {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-left: auto;
  padding-left: 12px;
  border-left: 1px solid var(--border-light);
}

.chip-btn {
  border: 1px solid transparent;
  background: var(--accent-soft);
  color: var(--accent);
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 10px;
  font-family: var(--font-mono);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.12s;
}

.chip-btn.off {
  background: transparent;
  color: var(--text-dim);
  border-color: var(--border-light);
  text-decoration: line-through;
}

.chip-btn:hover {
  border-color: var(--accent);
}

.section-nav .nav-pill.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

/* ── 可折叠 Section ── */
.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.section-header:hover {
  background: var(--surface-1);
}

.section-chevron {
  display: inline-block;
  font-size: 12px;
  color: var(--text-muted);
  transition: transform 0.2s;
}

.section-chevron.collapsed {
  transform: rotate(-90deg);
}

.section-title {
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text);
  letter-spacing: 0.3px;
}

.section-header .holdings-count {
  margin-left: auto;
}

.section-body {
  margin-top: 0;
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
  align-items: start;
}

/* 成交量图 + 排行榜：排行榜两列各 10 行，至少 460px 才不截断 */
.grid-volume-board {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(460px, 34%);
  gap: 16px;
  align-items: start;
}

.grid-volume-board > * {
  min-width: 0;
}

.grid-volume-board > :last-child {
  max-height: 560px;
  overflow-y: auto;
  scrollbar-width: thin;
}

/* 右侧列表类卡片（排行榜 / KOL）限高滚动，条目数变化不撑高整行 */
.grid-3-1 > :last-child {
  max-height: 560px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.section-nav {
  display: flex;
  align-items: center;
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
  border: none;
  background: none;
  padding: 5px 14px;
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
