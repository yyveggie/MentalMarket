import { configureSession } from '@/utils/simTime'
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { normalizeAction } from '@/utils/formatters'
import type {
  MarketState,
  AgentHolding,
  Decision,
  SocialPost,
  TradeRecord,
  CDAData,
  TomLevelSummary,
  TechnicalIndicator,
  MarketMicro,
  PriceTrendPoint,
  DailyBar,
  IntradayBar,
  SentimentPoint,
  ConfidencePoint,
  DeviationPoint,
  BiasStats,
  BiasTrendPoint,
  CascadeStats,
  LiquidityStats,
  PlanStats,
  IndexRow,
  RealIndexPoint,
  RealCalendarDay,
  ThinkingAgent,
  Metrics,
  BroadMarket,
  IncrementalDecision,
  AgentVisual,
  SeriesDelta,
  Leaderboard,
  SessionInfo,
} from '@/types/market'

export const useMarketStore = defineStore('market', () => {
  // ── Connection ──
  const connected = ref(false)
  const lastUpdateTime = ref(0)

  // ── Core State ──
  const simTime = ref(0)
  const session = ref<SessionInfo | null>(null)
  const tradingDay = ref(1)
  const tradingDaySeconds = ref(3600)
  const metrics = ref<Metrics | null>(null)

  // ── Agent Data ──
  const holdings = ref<AgentHolding[]>([])
  const thinkingAgents = ref<ThinkingAgent[]>([])
  const recentDecisions = ref<Decision[]>([])

  // ── Market Data ──
  const cdaBySymbol = ref<Record<string, CDAData>>({})
  const priceTrend = ref<Record<string, PriceTrendPoint[]>>({})
  // K 线数据：日线（含真实历史段）与盘中分桶 bar；barsVersion 在全量更新和逐笔成交后递增，图表据此增量刷新
  const dailyBars = ref<Record<string, DailyBar[]>>({})
  const intradayBars = ref<Record<string, IntradayBar[]>>({})
  const intradayBarSeconds = ref(0)
  const simStartDate = ref('')
  const barsVersion = ref(0)
  const sentimentTrend = ref<SentimentPoint[]>([])
  const confidenceTrend = ref<ConfidencePoint[]>([])
  const deviationTrend = ref<DeviationPoint[]>([])
  const indexSeries = ref<Record<string, IndexRow[]>>({})
  const indexSnapshot = ref<IndexRow[]>([])
  const leaderboard = ref<Leaderboard | null>(null)
  // 差量锚点对不上时置位，由 WebSocket 层请求全量
  const resyncNeeded = ref(false)
  const broadIndexSeries = ref<IndexRow[]>([])
  const realIndexSeries = ref<Record<string, RealIndexPoint[]>>({})
  const realCurveCalendar = ref<RealCalendarDay[]>([])
  const marketMicro = ref<Record<string, MarketMicro>>({})
  const technicalIndicators = ref<Record<string, TechnicalIndicator>>({})

  // ── ToM ──
  const tomSummary = ref<Record<string, TomLevelSummary>>({})

  // ── Social ──
  const socialHot = ref<SocialPost[]>([])
  const socialLatest = ref<SocialPost[]>([])
  const socialNews = ref<SocialPost[]>([])
  const socialGraph = ref<any>({})

  // ── Analytics ──
  const _emptyLG = () => ({ loss_hold: 0, loss_sell: 0, loss_buy: 0, gain_hold: 0, gain_sell: 0, gain_buy: 0 })
  const biasStats = ref<BiasStats>({ sell_gain: 0, sell_loss: 0, herding: 0, contrarian: 0, overconfident: 0, total: 0, loss_hold: 0, loss_sell: 0, loss_buy: 0, gain_hold: 0, gain_sell: 0, gain_buy: 0, disposition_effect: 0, lottery_preference: 0, underdiversified: 0, loss_aversion: 0, loss_gain_by_tom: { '0': _emptyLG(), '1': _emptyLG(), '2': _emptyLG() }, bubble_flag: false, avg_confidence: null, avg_deviation_pct: null, confidence_price_correlation: null, bubble_phase: 'none', polarization_index: null, extreme_ratio: null, echo_chamber_index: null, homophily_excess: null })
  const cascadeStats = ref<CascadeStats>({ total: 0, has_news: 0, total_perceived: 0, following_authors: 0 })
  const liquidityStats = ref<LiquidityStats>({})
  const planStats = ref<PlanStats>({ total: 0, adhered: 0, deviated: 0 })
  const biasTrends = ref<BiasTrendPoint[]>([])
  const mmSubsidy = ref<{ cash_injected: number; cash_absorbed: number; shares_created: number; shares_absorbed: number; trade_count: number }>({ cash_injected: 0, cash_absorbed: 0, shares_created: 0, shares_absorbed: 0, trade_count: 0 })

  // ── Arena Visuals ──
  const agentVisuals = ref<Map<number, AgentVisual>>(new Map())

  // ── Derived ──
  const symbols = computed(() => Object.keys(cdaBySymbol.value).sort())
  const broadMarket = computed<BroadMarket | null>(() => metrics.value?.broad_market ?? null)
  const totalAgents = computed(() => metrics.value?.total_agents ?? 0)

  function agentById(id: number): AgentHolding | undefined {
    return holdings.value.find((h) => h.agent_id === id)
  }

  /**
   * 追加型序列差量：full 直接替换；否则在锚点之后追加（replace_last 时连锚点行一起替换），再按 limit 截尾。
   * 找不到锚点说明本地数据已过期，返回 null 并由调用方请求全量。
   */
  function applySeriesDelta<T>(current: T[], d: SeriesDelta<T>, ident: (r: T) => unknown): T[] | null {
    if (d.full) return d.limit && d.full.length > d.limit ? d.full.slice(d.full.length - d.limit) : d.full
    const rows = d.rows ?? []
    let idx = -1
    for (let i = current.length - 1; i >= 0; i--) {
      if (ident(current[i]) === d.anchor) {
        idx = i
        break
      }
    }
    if (idx < 0) return null
    const base = d.replace_last ? current.slice(0, idx) : current.slice(0, idx + 1)
    let out = base.concat(rows)
    if (d.limit && out.length > d.limit) out = out.slice(out.length - d.limit)
    return out
  }

  function applyListDelta<T>(target: { value: T[] }, d: SeriesDelta<T> | undefined, ident: (r: T) => unknown) {
    if (!d) return
    const next = applySeriesDelta(target.value, d, ident)
    if (next === null) resyncNeeded.value = true
    else target.value = next
  }

  function applyDictDelta<T>(target: { value: Record<string, T[]> }, deltas: Record<string, SeriesDelta<T>> | undefined, ident: (r: T) => unknown) {
    if (!deltas) return
    const map = { ...target.value }
    let changed = false
    for (const [symbol, d] of Object.entries(deltas)) {
      const next = applySeriesDelta(map[symbol] ?? [], d, ident)
      if (next === null) {
        resyncNeeded.value = true
        continue
      }
      map[symbol] = next
      changed = true
    }
    if (changed) target.value = map
  }

  /** 重连后服务端会话是新的：清空差量基线相关的本地数据，等待全量 */
  function resetForResync() {
    resyncNeeded.value = false
  }

  /** 应用一条状态推送（可能只含订阅主题的字段与差量） */
  function applyFullState(state: MarketState) {
    simTime.value = state.sim_time
    tradingDay.value = state.trading_day
    if (state.trading_day_seconds !== undefined) tradingDaySeconds.value = state.trading_day_seconds
    if (state.session !== undefined) {
      session.value = state.session
      configureSession(state.session.open_call_seconds, state.session.close_call_seconds)
    }
    if (state.metrics !== undefined) metrics.value = state.metrics
    lastUpdateTime.value = state.server_time

    let agentsTouched = false
    if (state.holdings !== undefined) {
      holdings.value = state.holdings
      agentsTouched = true
    } else if (state.holdings_delta) {
      const byId = new Map(holdings.value.map((h) => [h.agent_id, h]))
      for (const h of state.holdings_delta.upsert) byId.set(h.agent_id, h)
      for (const id of state.holdings_delta.remove) byId.delete(id)
      holdings.value = [...byId.values()].sort((a, b) => a.agent_id - b.agent_id)
      agentsTouched = true
    }
    if (state.active) {
      if (state.active.thinking !== undefined) thinkingAgents.value = state.active.thinking
      if (state.active.recent_decisions !== undefined) recentDecisions.value = state.active.recent_decisions
      agentsTouched = true
    }
    if (state.leaderboard !== undefined) leaderboard.value = state.leaderboard

    if (state.cda_by_symbol !== undefined) cdaBySymbol.value = state.cda_by_symbol
    if (state.price_trend !== undefined) priceTrend.value = state.price_trend
    applyDictDelta(priceTrend, state.price_trend_delta, (r) => r.t)

    let barsTouched = false
    if (state.daily_bars !== undefined) {
      dailyBars.value = state.daily_bars
      barsTouched = true
    }
    if (state.daily_bars_delta) {
      applyDictDelta(dailyBars, state.daily_bars_delta, (r) => r.time)
      barsTouched = true
    }
    if (state.intraday_bars !== undefined) {
      intradayBars.value = state.intraday_bars
      barsTouched = true
    }
    if (state.intraday_bars_delta) {
      applyDictDelta(intradayBars, state.intraday_bars_delta, (r) => r.t)
      barsTouched = true
    }
    if (state.intraday_bar_seconds !== undefined) intradayBarSeconds.value = state.intraday_bar_seconds
    if (state.sim_start_date !== undefined) simStartDate.value = state.sim_start_date
    if (barsTouched) barsVersion.value++

    if (state.sentiment_trend !== undefined) sentimentTrend.value = state.sentiment_trend
    applyListDelta(sentimentTrend, state.sentiment_trend_delta, (r) => r.t)
    if (state.confidence_trend !== undefined) confidenceTrend.value = state.confidence_trend
    applyListDelta(confidenceTrend, state.confidence_trend_delta, (r) => r.t)
    if (state.deviation_trend !== undefined) deviationTrend.value = state.deviation_trend
    applyListDelta(deviationTrend, state.deviation_trend_delta, (r) => r.t)

    if (state.index_series !== undefined) indexSeries.value = state.index_series
    applyDictDelta(indexSeries, state.index_series_delta, (r) => r.date)
    if (state.index_snapshot !== undefined) indexSnapshot.value = state.index_snapshot
    if (state.broad_index_series !== undefined) broadIndexSeries.value = state.broad_index_series
    applyListDelta(broadIndexSeries, state.broad_index_series_delta, (r) => r.date)
    if (state.real_index_series !== undefined) realIndexSeries.value = state.real_index_series
    if (state.real_curve_calendar !== undefined) realCurveCalendar.value = state.real_curve_calendar
    if (state.market_micro !== undefined) marketMicro.value = state.market_micro
    if (state.technical_indicators !== undefined) technicalIndicators.value = state.technical_indicators

    if (state.tom_summary !== undefined) tomSummary.value = state.tom_summary
    if (state.social_hot !== undefined) socialHot.value = state.social_hot
    if (state.social_latest !== undefined) socialLatest.value = state.social_latest
    if (state.social_news !== undefined) socialNews.value = state.social_news
    if (state.social_graph !== undefined) socialGraph.value = state.social_graph

    if (state.bias_stats !== undefined) biasStats.value = state.bias_stats
    if (state.bias_trends !== undefined) biasTrends.value = state.bias_trends
    applyListDelta(biasTrends, state.bias_trends_delta, (r) => r.day)
    if (state.cascade_stats !== undefined) cascadeStats.value = state.cascade_stats
    if (state.liquidity_stats !== undefined) liquidityStats.value = state.liquidity_stats
    if (state.plan_stats !== undefined) planStats.value = state.plan_stats
    if (state.mm_subsidy !== undefined) mmSubsidy.value = state.mm_subsidy

    if (agentsTouched) rebuildAgentVisuals()
  }

  function applyTradeEvent(trade: TradeRecord) {
    const sym = trade.symbol.toUpperCase()
    const cda = cdaBySymbol.value[sym]
    if (cda) {
      cda.recent_trades.push(trade)
      if (cda.recent_trades.length > 100) cda.recent_trades.shift()
    }
    // 逐笔成交并入盘中 K 线（与后端 _ingest_trade_bar 同一分桶规则），让 K 线在两次全量推送之间实时跳动
    const barS = intradayBarSeconds.value
    if (barS > 0 && trade.price > 0 && trade.quantity > 0) {
      const bucket = Math.round(Math.floor(trade.sim_time / barS) * barS * 1000) / 1000
      let list = intradayBars.value[sym]
      if (!list) {
        list = []
        intradayBars.value[sym] = list
      }
      const last = list[list.length - 1]
      if (last && last.t >= bucket) {
        last.high = Math.max(last.high, trade.price)
        last.low = Math.min(last.low, trade.price)
        last.close = trade.price
        last.volume += trade.quantity
      } else {
        list.push({ t: bucket, open: trade.price, high: trade.price, low: trade.price, close: trade.price, volume: trade.quantity })
        if (list.length > 600) list.shift()
      }
      barsVersion.value++
    }
  }

  function applyDecisionEvent(decision: IncrementalDecision) {
    recentDecisions.value.push({
      sim_time: decision.sim_time,
      agent_id: decision.agent_id,
      tom_level: decision.tom_level,
      action: decision.action,
      reasoning: decision.reasoning ?? '',
      sentiment: decision.sentiment ?? null,
      confidence: decision.confidence ?? null,
      tool_trace: decision.tool_trace ?? [],
      action_executed: {
        action: decision.action,
        symbol: decision.symbol,
        decision_scope: decision.decision_scope,
        status: decision.status,
        price: decision.price,
        quantity: decision.quantity,
      },
    })
    if (recentDecisions.value.length > 200) recentDecisions.value.shift()

    const vis = agentVisuals.value.get(decision.agent_id)
    if (vis) {
      const act = normalizeAction(decision.action)
      vis.phase = 'trading'
      vis.lastAction = act
      vis.emotion = act === 'buy' ? 'happy' : act === 'sell' ? 'worried' : 'neutral'
    }
  }

  function rebuildAgentVisuals() {
    const map = new Map<number, AgentVisual>()
    const thinkingSet = new Set(thinkingAgents.value.map((t) => t.agent_id))

    // 最近决策按 agent 建一次索引（后写覆盖先写 = 保留最新），避免每个 agent 反向遍历一遍决策流
    const lastDecisionByAgent = new Map<number, Decision>()
    for (const d of recentDecisions.value) lastDecisionByAgent.set(d.agent_id, d)

    for (const h of holdings.value) {
      const isThinking = thinkingSet.has(h.agent_id)
      const lastDec = lastDecisionByAgent.get(h.agent_id)

      const lastAction = lastDec ? normalizeAction(lastDec.action_executed?.action ?? lastDec.action) : undefined
      let emotion: AgentVisual['emotion'] = 'neutral'
      if (isThinking) emotion = h.tom_level >= 2 ? 'scheming' : 'thinking'
      else if (lastAction === 'buy') emotion = 'happy'
      else if (lastAction === 'sell') emotion = 'worried'

      map.set(h.agent_id, {
        id: h.agent_id,
        tomLevel: h.tom_level,
        emotion,
        phase: isThinking ? 'thinking' : 'idle',
        lastAction,
        wealth: h.wealth,
        pnlDirection: h.wealth > h.initial_asset * 1.02 ? 'up' : h.wealth < h.initial_asset * 0.98 ? 'down' : 'flat',
      })
    }
    agentVisuals.value = map
  }

  return {
    connected,
    lastUpdateTime,
    simTime,
    session,
    tradingDay,
    tradingDaySeconds,
    metrics,
    holdings,
    thinkingAgents,
    recentDecisions,
    cdaBySymbol,
    priceTrend,
    dailyBars,
    intradayBars,
    intradayBarSeconds,
    simStartDate,
    barsVersion,
    sentimentTrend,
    confidenceTrend,
    deviationTrend,
    indexSeries,
    indexSnapshot,
    leaderboard,
    resyncNeeded,
    resetForResync,
    broadIndexSeries,
    realIndexSeries,
    realCurveCalendar,
    marketMicro,
    technicalIndicators,
    tomSummary,
    socialHot,
    socialLatest,
    socialNews,
    socialGraph,
    biasStats,
    biasTrends,
    cascadeStats,
    liquidityStats,
    planStats,
    mmSubsidy,
    agentVisuals,
    symbols,
    broadMarket,
    totalAgents,
    agentById,
    applyFullState,
    applyTradeEvent,
    applyDecisionEvent,
  }
})
