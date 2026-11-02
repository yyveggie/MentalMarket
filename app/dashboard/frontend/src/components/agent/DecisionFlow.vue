<script setup lang="ts">
/**
 * 决策簿（blotter）：左侧是逐行紧凑的决策记录表，右侧是选中记录的完整推理与工具调用。
 * 参考交易终端的成交/订单簿视图，一行一条，推理摘要单行省略，点击行看详情。
 */
import { computed, ref, watch } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { fmt, fmtInt, fmtCn, fmtPct, normalizeAction } from '@/utils/formatters'
import { describeSimClock } from '@/utils/simTime'
import type { Decision } from '@/types/market'

const store = useMarketStore()

type ActionFilter = 'all' | 'buy' | 'sell' | 'hold'
const actionFilter = ref<ActionFilter>('all')
const tomFilter = ref<number | null>(null)
const selectedKey = ref<string | null>(null)
const follow = ref(true) // 跟随最新：有新决策时自动选中最新一条

function keyOf(d: Decision): string {
  return `${d.agent_id}-${d.sim_time}`
}

interface Row {
  key: string
  d: Decision
  clock: string
  action: string
  symbol: string
  scope: string
  price: number | null
  quantity: number | null
  status: string
  ok: boolean | null
  reasoning: string
  toolCount: number
  tools: Array<{ name: string; summary: string; status: string }>
}

function toolSummary(t: any): string {
  const args = t?.args ?? {}
  if (args.content) return String(args.content)
  if (args.action) return `${args.action}${args.post_id ? ` #${args.post_id}` : ''}${args.symbol ? ` ${args.symbol}` : ''}`
  if (args.symbol) return String(args.symbol)
  return ''
}

const rows = computed<Row[]>(() => {
  const list = store.recentDecisions.slice(-80).reverse()
  const out: Row[] = []
  for (const d of list) {
    const ex = d.action_executed ?? {}
    const action = normalizeAction(ex.action ?? d.action)
    if (actionFilter.value !== 'all' && action !== actionFilter.value) continue
    if (tomFilter.value !== null && d.tom_level !== tomFilter.value) continue
    const tools = (d.tool_trace ?? [])
      .filter((t: any) => !(t.result?.status === 'failed' && ['follow', 'unfollow'].includes(t.args?.action)))
      .map((t: any) => ({ name: String(t.name ?? ''), summary: toolSummary(t), status: String(t.result?.status ?? '') }))
    out.push({
      key: keyOf(d),
      d,
      clock: describeSimClock(d.sim_time, store.tradingDaySeconds),
      action,
      symbol: ex.symbol ? String(ex.symbol) : '',
      scope: ex.decision_scope ? String(ex.decision_scope) : '',
      price: ex.price && ex.quantity ? Number(ex.price) : null,
      quantity: ex.price && ex.quantity ? Number(ex.quantity) : null,
      status: ex.status ? String(ex.status) : '',
      ok: ex.status ? ex.status === 'ok' : null,
      reasoning: d.reasoning ?? '',
      toolCount: tools.length,
      tools,
    })
  }
  return out
})

const selected = computed<Row | null>(() => {
  if (!rows.value.length) return null
  const hit = selectedKey.value ? rows.value.find((r) => r.key === selectedKey.value) : null
  return hit ?? rows.value[0]
})

watch(rows, (list) => {
  if (follow.value && list.length) selectedKey.value = list[0].key
})

function select(r: Row) {
  selectedKey.value = r.key
  follow.value = r === rows.value[0]
}

const thinkingIds = computed(() => store.thinkingAgents.map((a) => a.agent_id))
const selectedAgent = computed(() => (selected.value ? store.agentById(selected.value.d.agent_id) : undefined))

/** 选中 Agent 的其他近期决策（时间倒序），用于看它前后是否一致 */
const agentHistory = computed(() => {
  const cur = selected.value
  if (!cur) return []
  const out: Array<{ key: string; clock: string; action: string; symbol: string; px: number | null; qty: number | null; ok: boolean | null; sentiment: number | null }> = []
  for (let i = store.recentDecisions.length - 1; i >= 0 && out.length < 6; i--) {
    const d = store.recentDecisions[i]
    if (d.agent_id !== cur.d.agent_id || keyOf(d) === cur.key) continue
    const ex = d.action_executed ?? {}
    out.push({
      key: keyOf(d),
      clock: describeSimClock(d.sim_time, store.tradingDaySeconds),
      action: normalizeAction(ex.action ?? d.action),
      symbol: ex.symbol ? String(ex.symbol) : '',
      px: ex.price && ex.quantity ? Number(ex.price) : null,
      qty: ex.price && ex.quantity ? Number(ex.quantity) : null,
      ok: ex.status ? ex.status === 'ok' : null,
      sentiment: d.sentiment ?? null,
    })
  }
  return out
})

function sentimentLabel(v: number | null | undefined): string {
  if (v == null) return '-'
  if (v >= 0.5) return '强烈看多'
  if (v >= 0.15) return '偏多'
  if (v > -0.15) return '中性'
  if (v > -0.5) return '偏空'
  return '强烈看空'
}

function actionLabel(a: string): string {
  return a === 'buy' ? '买入' : a === 'sell' ? '卖出' : '观望'
}
</script>

<template>
  <div class="blotter card">
    <div class="blotter-head">
      <div class="head-left">
        <span class="title">决策簿</span>
        <span class="count">{{ rows.length }} 条</span>
        <span v-if="thinkingIds.length" class="thinking">
          思考中
          <span v-for="id in thinkingIds.slice(0, 8)" :key="id" class="chip">A{{ id }}</span>
          <span v-if="thinkingIds.length > 8" class="chip more">+{{ thinkingIds.length - 8 }}</span>
        </span>
      </div>
      <div class="head-right">
        <button v-for="f in (['all', 'buy', 'sell', 'hold'] as ActionFilter[])" :key="f" class="fbtn" :class="{ active: actionFilter === f }" @click="actionFilter = f">
          {{ f === 'all' ? '全部' : actionLabel(f) }}
        </button>
        <span class="sep" />
        <button class="fbtn" :class="{ active: tomFilter === null }" @click="tomFilter = null">ToM 全部</button>
        <button v-for="t in [0, 1, 2]" :key="t" class="fbtn" :class="{ active: tomFilter === t }" @click="tomFilter = tomFilter === t ? null : t">T{{ t }}</button>
        <span class="sep" />
        <button class="fbtn" :class="{ active: follow }" :title="'自动选中最新一条'" @click="follow = !follow">跟随最新</button>
      </div>
    </div>

    <div class="blotter-body">
      <div class="table-wrap">
        <div class="grid-head">
          <span class="c-time">时间</span>
          <span class="c-agent">Agent</span>
          <span class="c-tom">ToM</span>
          <span class="c-act">动作</span>
          <span class="c-sym">标的</span>
          <span class="c-px">价格</span>
          <span class="c-qty">数量</span>
          <span class="c-st">状态</span>
          <span class="c-reason">心智推理</span>
          <span class="c-tools">工具</span>
        </div>
        <div
          v-for="r in rows"
          :key="r.key"
          class="grid-row"
          :class="[`act-${r.action}`, { selected: selected?.key === r.key }]"
          @click="select(r)"
        >
          <span class="c-time">{{ r.clock }}</span>
          <span class="c-agent">A{{ r.d.agent_id }}</span>
          <span class="c-tom"><span class="badge" :class="`badge-tom${r.d.tom_level}`">T{{ r.d.tom_level }}</span></span>
          <span class="c-act"><span class="act" :class="`act-${r.action}`">{{ actionLabel(r.action) }}</span></span>
          <span class="c-sym">{{ r.symbol || (r.scope === 'portfolio' ? '组合' : '-') }}</span>
          <span class="c-px">{{ r.price != null ? fmt(r.price, 2) : '-' }}</span>
          <span class="c-qty">{{ r.quantity != null ? fmtInt(r.quantity) : '-' }}</span>
          <span class="c-st">
            <span v-if="r.ok === true" class="st ok">成交</span>
            <span v-else-if="r.ok === false" class="st fail" :title="r.status">{{ r.status === 'skipped' ? '跳过' : '失败' }}</span>
            <span v-else class="st none">-</span>
          </span>
          <span class="c-reason" :title="r.reasoning">{{ r.reasoning || '—' }}</span>
          <span class="c-tools">{{ r.toolCount || '' }}</span>
        </div>
        <div v-if="rows.length === 0" class="empty">暂无决策</div>
      </div>

      <aside class="detail" v-if="selected">
        <div class="detail-head">
          <span class="detail-agent">A{{ selected.d.agent_id }}</span>
          <span class="badge" :class="`badge-tom${selected.d.tom_level}`">ToM{{ selected.d.tom_level }}</span>
          <span class="act" :class="`act-${selected.action}`">{{ actionLabel(selected.action) }}</span>
          <span v-if="selected.symbol" class="detail-sym">{{ selected.symbol }}</span>
          <span class="detail-time">{{ selected.clock }} · T={{ fmt(selected.d.sim_time, 1) }}</span>
        </div>
        <div v-if="selected.price != null" class="detail-trade">
          <span class="k">委托</span>
          <span class="v">{{ fmt(selected.price, 2) }} × {{ fmtInt(selected.quantity) }}</span>
          <span v-if="selected.ok === true" class="st ok">成交</span>
          <span v-else-if="selected.ok === false" class="st fail">{{ selected.status }}</span>
        </div>
        <div v-if="selectedAgent" class="agent-brief">
          <span><i>财富</i><b>{{ fmtCn(selectedAgent.wealth, 2) }}</b></span>
          <span><i>现金</i><b>{{ fmtCn(selectedAgent.cash, 2) }}</b></span>
          <span><i>持股</i><b>{{ fmtInt(selectedAgent.total_shares) }}</b></span>
          <span><i>收益率</i><b :class="selectedAgent.return_pct > 0 ? 'color-up' : selectedAgent.return_pct < 0 ? 'color-down' : ''">{{ fmtPct(selectedAgent.return_pct) }}</b></span>
          <span><i>交易</i><b>{{ selectedAgent.trade_count }}</b></span>
          <span v-if="selectedAgent.current_positions_text" class="positions"><i>持仓</i><b>{{ selectedAgent.current_positions_text }}</b></span>
        </div>
        <div v-if="selected.d.sentiment != null || selected.d.confidence != null" class="gauges">
          <div class="gauge" :title="'情绪：模型自报的市场看法，-1 看空 ~ +1 看多'">
            <span class="g-k">情绪</span>
            <i class="g-bar diverging"><b :class="(selected.d.sentiment ?? 0) >= 0 ? 'pos' : 'neg'" :style="{ width: `${Math.abs(selected.d.sentiment ?? 0) * 50}%`, left: (selected.d.sentiment ?? 0) >= 0 ? '50%' : `${50 - Math.abs(selected.d.sentiment ?? 0) * 50}%` }" /></i>
            <span class="g-v" :class="(selected.d.sentiment ?? 0) > 0.15 ? 'color-up' : (selected.d.sentiment ?? 0) < -0.15 ? 'color-down' : ''">{{ selected.d.sentiment == null ? '-' : (selected.d.sentiment > 0 ? '+' : '') + selected.d.sentiment.toFixed(2) }} {{ sentimentLabel(selected.d.sentiment) }}</span>
          </div>
          <div class="gauge" :title="'信心：模型对本次决策的把握，0 ~ 1'">
            <span class="g-k">信心</span>
            <i class="g-bar"><b class="conf" :style="{ width: `${Math.max(0, Math.min(1, selected.d.confidence ?? 0)) * 100}%` }" /></i>
            <span class="g-v">{{ selected.d.confidence == null ? '-' : (selected.d.confidence * 100).toFixed(0) + '%' }}</span>
          </div>
        </div>
        <div class="detail-section">
          <div class="section-label">{{ selected.d.tom_level === 2 ? '一阶 + 二阶心智推理' : selected.d.tom_level === 1 ? '一阶心智推理' : '推理' }}</div>
          <p class="reasoning">{{ selected.reasoning || (selected.d.tom_level === 0 ? '（零阶 Agent 不输出心智推理，仅提交情绪与决策）' : '（无推理文本）') }}</p>
        </div>
        <div v-if="selected.tools.length" class="detail-section">
          <div class="section-label">工具调用</div>
          <div v-for="(t, i) in selected.tools" :key="i" class="tool-row">
            <span class="tool-name">{{ t.name }}</span>
            <span class="tool-sum">{{ t.summary }}</span>
            <span v-if="t.status" class="st" :class="t.status === 'ok' ? 'ok' : 'fail'">{{ t.status }}</span>
          </div>
        </div>
        <div v-if="agentHistory.length" class="detail-section">
          <div class="section-label">A{{ selected.d.agent_id }} 最近决策</div>
          <div v-for="h in agentHistory" :key="h.key" class="hist-row" @click="selectedKey = h.key; follow = false">
            <span class="h-time">{{ h.clock }}</span>
            <span class="act" :class="`act-${h.action}`">{{ actionLabel(h.action) }}</span>
            <span class="h-sym">{{ h.symbol || '-' }}</span>
            <span class="h-trade">{{ h.px != null ? `${fmt(h.px, 2)} × ${fmtInt(h.qty ?? 0)}` : '' }}</span>
            <span class="h-sent" :class="(h.sentiment ?? 0) > 0.15 ? 'color-up' : (h.sentiment ?? 0) < -0.15 ? 'color-down' : ''">{{ h.sentiment == null ? '' : (h.sentiment > 0 ? '+' : '') + h.sentiment.toFixed(2) }}</span>
            <span v-if="h.ok === true" class="st ok">成交</span>
            <span v-else-if="h.ok === false" class="st fail">失败</span>
          </div>
        </div>
      </aside>
      <aside class="detail detail-empty" v-else>选择左侧一条决策查看完整推理</aside>
    </div>
  </div>
</template>

<style scoped>
.blotter {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 544px;            /* 固定高度：内部列表每秒变化不影响页面布局 */
  padding: 0;
  font-variant-numeric: tabular-nums;
  overflow-anchor: none;    /* 内部插入新行时不让浏览器以此为滚动锚点而挪动整页 */
}

.blotter-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: nowrap;
  height: 44px;
  box-sizing: border-box;
  padding: 0 14px;
  border-bottom: 1px solid var(--border);
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.title {
  font-size: 13px;
  font-weight: 700;
  color: var(--heading);
}

.count {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

.thinking {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.chip {
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
  font-size: 10px;
}

.chip.more {
  background: var(--surface-1);
  color: var(--text-dim);
}

.head-right {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}

.fbtn {
  border: none;
  background: var(--surface-1);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  cursor: pointer;
}

.fbtn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.sep {
  width: 1px;
  height: 12px;
  background: var(--border-light);
  margin: 0 4px;
}

.blotter-body {
  display: grid;
  grid-template-columns: minmax(0, 1.9fr) minmax(300px, 1fr);
  min-height: 0;
  flex: 1;
}

.table-wrap {
  overflow: auto;
  overflow-anchor: none;
  min-height: 0;
  height: 500px;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-2) transparent;
  border-right: 1px solid var(--border);
}

.grid-head,
.grid-row {
  display: grid;
  grid-template-columns: 84px 48px 50px 52px 56px 64px 64px 48px minmax(0, 1fr) 40px;
  align-items: center;
  column-gap: 8px;
  padding: 0 8px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.grid-head {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface-1);
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10px;
  height: 26px;
}

.grid-row {
  height: 30px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  color: var(--text);
}

.grid-row > span,
.grid-head > span {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.c-time { color: var(--text-dim); }
.c-agent { font-weight: 700; color: var(--heading); }
.c-px, .c-qty, .c-tools { text-align: right; }
.c-reason { color: var(--text-muted); }
.c-tools { color: var(--text-dim); }

.grid-row:hover {
  background: var(--surface-1);
}

.grid-row.selected {
  background: var(--accent-soft);
}

.grid-row.act-buy .c-agent { color: var(--up); }
.grid-row.act-sell .c-agent { color: var(--down); }

.act {
  display: inline-block;
  padding: 0 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
}

.act.act-buy { background: var(--up-soft); color: var(--up); }
.act.act-sell { background: var(--down-soft); color: var(--down); }
.act.act-hold { background: var(--surface-2); color: var(--text-dim); }

.st {
  font-size: 10px;
  font-weight: 600;
}

.st.ok { color: var(--up); }
.st.fail { color: var(--down); }
.st.none { color: var(--text-dim); }

.empty {
  text-align: center;
  color: var(--text-dim);
  padding: 20px;
}

/* ── 详情栏 ── */
.detail {
  padding: 12px 14px;
  overflow-y: auto;
  overflow-anchor: none;
  min-height: 0;
  height: 500px;
  box-sizing: border-box;
  scrollbar-width: thin;
  font-size: 12px;
}

.detail-empty {
  color: var(--text-dim);
  display: flex;
  align-items: center;
  justify-content: center;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-family: var(--font-mono);
  margin-bottom: 8px;
}

.detail-agent {
  font-size: 14px;
  font-weight: 800;
  color: var(--heading);
}

.detail-sym {
  font-weight: 600;
  color: var(--heading);
}

.detail-time {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-dim);
}

.detail-trade {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-family: var(--font-mono);
  padding: 6px 8px;
  background: var(--surface-1);
  border-radius: 4px;
  margin-bottom: 10px;
}

.detail-trade .k {
  font-size: 10px;
  color: var(--text-dim);
}

.detail-trade .v {
  font-weight: 700;
  color: var(--heading);
}

.detail-section + .detail-section {
  margin-top: 10px;
}

.agent-brief {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px 10px;
  margin-bottom: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
}

.agent-brief span {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}

.agent-brief i {
  font-style: normal;
  color: var(--text-dim);
  font-size: 10px;
  white-space: nowrap;
}

.agent-brief b {
  color: var(--heading);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-brief .positions {
  grid-column: 1 / -1;
  justify-content: flex-start;
}

.section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.3px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.reasoning {
  margin: 0;
  line-height: 1.55;
  color: var(--text);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.gauges {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
}

.gauge {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 110px;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.g-k {
  color: var(--text-dim);
  font-size: 10px;
}

.g-bar {
  position: relative;
  display: block;
  height: 6px;
  border-radius: 3px;
  background: var(--surface-2);
  overflow: hidden;
}

.g-bar.diverging::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  width: 1px;
  height: 100%;
  background: var(--border);
}

.g-bar b {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 3px;
}

.g-bar b.pos { background: var(--up); opacity: 0.8; }
.g-bar b.neg { background: var(--down); opacity: 0.8; }
.g-bar b.conf { left: 0; background: var(--accent); opacity: 0.75; }

.g-v {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--heading);
  text-align: right;
  white-space: nowrap;
}

.hist-row {
  display: grid;
  grid-template-columns: 62px 40px 46px minmax(0, 1fr) 44px 34px;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
}

.hist-row:hover {
  background: var(--surface-1);
}

.hist-row:last-child {
  border-bottom: none;
}

.h-time { color: var(--text-dim); font-size: 10px; }
.h-sym { color: var(--heading); font-weight: 600; }
.h-trade { color: var(--text-muted); }
.h-sent { text-align: right; }

.tool-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
}

.tool-name {
  color: var(--accent);
  font-weight: 600;
  flex-shrink: 0;
}

.tool-sum {
  color: var(--text-muted);
  word-break: break-word;
  flex: 1;
}

@media (max-width: 1100px) {
  .blotter-body {
    grid-template-columns: 1fr;
  }

  .table-wrap {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
}
</style>
