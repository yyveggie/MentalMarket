import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
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
} from '@/types/market'

export const useMarketStore = defineStore('market', () => {
  // ── Connection ──
  const connected = ref(false)
  const lastUpdateTime = ref(0)

  // ── Core State ──
  const simTime = ref(0)
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
  const sentimentTrend = ref<SentimentPoint[]>([])
  const confidenceTrend = ref<ConfidencePoint[]>([])
  const deviationTrend = ref<DeviationPoint[]>([])
  const indexSeries = ref<Record<string, IndexRow[]>>({})
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

  function applyFullState(state: MarketState) {
    simTime.value = state.sim_time
    tradingDay.value = state.trading_day
    tradingDaySeconds.value = state.trading_day_seconds ?? 3600
    metrics.value = state.metrics
    lastUpdateTime.value = state.server_time

    holdings.value = state.holdings
    thinkingAgents.value = state.active.thinking
    recentDecisions.value = state.active.recent_decisions

    cdaBySymbol.value = state.cda_by_symbol
    priceTrend.value = state.price_trend
    sentimentTrend.value = state.sentiment_trend
    confidenceTrend.value = state.confidence_trend ?? []
    deviationTrend.value = state.deviation_trend
    indexSeries.value = state.index_series
    broadIndexSeries.value = state.broad_index_series
    realIndexSeries.value = state.real_index_series ?? realIndexSeries.value
    realCurveCalendar.value = state.real_curve_calendar ?? realCurveCalendar.value
    marketMicro.value = state.market_micro
    technicalIndicators.value = state.technical_indicators

    tomSummary.value = state.tom_summary
    socialHot.value = state.social_hot
    socialLatest.value = state.social_latest
    socialNews.value = state.social_news ?? []
    socialGraph.value = state.social_graph ?? {}

    biasStats.value = state.bias_stats ?? biasStats.value
    biasTrends.value = state.bias_trends ?? biasTrends.value
    cascadeStats.value = state.cascade_stats ?? cascadeStats.value
    liquidityStats.value = state.liquidity_stats ?? liquidityStats.value
    planStats.value = state.plan_stats ?? planStats.value
    mmSubsidy.value = state.mm_subsidy ?? mmSubsidy.value

    rebuildAgentVisuals()
  }

  function applyTradeEvent(trade: TradeRecord) {
    const sym = trade.symbol.toUpperCase()
    const cda = cdaBySymbol.value[sym]
    if (cda) {
      cda.recent_trades.push(trade)
      if (cda.recent_trades.length > 100) cda.recent_trades.shift()
    }
  }

  function applyDecisionEvent(decision: IncrementalDecision) {
    recentDecisions.value.push({
      sim_time: decision.sim_time,
      agent_id: decision.agent_id,
      tom_level: decision.tom_level,
      action: decision.action,
      reasoning: decision.reasoning ?? '',
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
      vis.phase = 'trading'
      vis.lastAction = decision.action
      vis.emotion = decision.action === 'buy' ? 'happy' : decision.action === 'sell' ? 'worried' : 'neutral'
    }
  }

  function rebuildAgentVisuals() {
    const map = new Map<number, AgentVisual>()
    const thinkingSet = new Set(thinkingAgents.value.map((t) => t.agent_id))

    for (const h of holdings.value) {
      const isThinking = thinkingSet.has(h.agent_id)
      const lastDec = recentDecisions.value
        .slice()
        .reverse()
        .find((d) => d.agent_id === h.agent_id)

      let emotion: AgentVisual['emotion'] = 'neutral'
      if (isThinking) emotion = h.tom_level >= 2 ? 'scheming' : 'thinking'
      else if (lastDec?.action === 'buy') emotion = 'happy'
      else if (lastDec?.action === 'sell') emotion = 'worried'

      map.set(h.agent_id, {
        id: h.agent_id,
        tomLevel: h.tom_level,
        emotion,
        phase: isThinking ? 'thinking' : 'idle',
        lastAction: lastDec?.action,
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
    tradingDay,
    tradingDaySeconds,
    metrics,
    holdings,
    thinkingAgents,
    recentDecisions,
    cdaBySymbol,
    priceTrend,
    sentimentTrend,
    confidenceTrend,
    deviationTrend,
    indexSeries,
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
