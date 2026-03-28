/** Agent 持仓 & 状态 */
export interface AgentHolding {
  agent_id: number
  tom_level: number
  cash: number
  total_shares: number
  wealth: number
  initial_asset: number
  return_pct: number
  trade_count: number
  decision_count: number
  total_pnl: number
  positions: Record<string, number>
  current_positions_text: string
  index_holdings: string[]
  reasoning_text: string
}

/** Agent 决策记录 */
export interface Decision {
  decision_id?: string
  sim_time: number
  agent_id: number
  tom_level: number
  reasoning: string
  action: string
  tool_trace: ToolCall[]
  action_executed: ActionExecuted
}

export interface ActionExecuted {
  action?: string
  symbol?: string
  decision_scope?: string
  price?: number
  quantity?: number
  status?: string
  tool_trace?: ToolCall[]
}

export interface ToolCall {
  name: string
  args: Record<string, unknown>
  result: Record<string, unknown>
}

/** 社交帖子 */
export interface SocialPost {
  post_id: number
  agent_id: number
  content: string
  timestamp: number
  trading_day: number
  source: 'agent' | 'news' | 'retweet' | 'agent_tool' | 'agent_fud'
  likes: number
  dislikes: number
  retweet_count: number
  original_post_id?: number
}

/** L2 盘口档位 */
export interface L2Level {
  price: number
  quantity: number
}

export interface L2Attribution {
  price: number
  quantity: number
  orders: Array<{ agent_id: number; quantity: number }>
}

/** CDA 订单簿数据 */
export interface CDAData {
  last_price: number | null
  spread: number | null
  bids: L2Level[]
  asks: L2Level[]
  bids_attribution: L2Attribution[]
  asks_attribution: L2Attribution[]
  recent_trades: TradeRecord[]
}

/** 成交记录 */
export interface TradeRecord {
  sim_time: number
  symbol: string
  price: number
  quantity: number
  buyer_id: number
  seller_id: number
  aggressor: 'bid' | 'ask'
}

/** 正在思考的 Agent */
export interface ThinkingAgent {
  agent_id: number
  phase: 'thinking' | 'decided' | 'scheduled'
  sim_time?: number
}

/** 活跃状态 */
export interface ActiveState {
  thinking: ThinkingAgent[]
  scheduled: ThinkingAgent[]
  running_agent_ids: number[]
  recent_decisions: Decision[]
  recent_tools: ToolCall[]
}

/** ToM 等级汇总 */
export interface TomLevelSummary {
  count: number
  avg_wealth: number
  total_wealth: number
  median_wealth: number
  min_wealth: number
  max_wealth: number
  avg_initial_asset?: number
  avg_return_pct: number
  roi_pct?: number
  avg_pnl: number
  positive_return_ratio: number
  win_rate_trade_pct?: number
  total_trades: number
  gini_coefficient?: number
  top10_wealth_share?: number
  avg_trades_per_agent: number
}

/** 大盘信息 */
export interface BroadMarket {
  name: string
  value: number | null
  pct_chg: number | null
  up_count: number
  down_count: number
  flat_count: number
  total: number
  volume: number
}

/** 技术指标 */
export interface TechnicalIndicator {
  samples: number
  last_price: number | null
  sma_5: number | null
  sma_20: number | null
  ema_5: number | null
  ema_20: number | null
  rsi_14: number | null
  momentum_10: number | null
  volatility: number | null
}

/** 市场微观结构 */
export interface MarketMicro {
  volume: number
  buy_volume: number
  sell_volume: number
  buy_sell_ratio: number
  turnover_rate: number
  vwap: number | null
  volatility: number | null
  spread: number | null
  trade_count: number
}

/** 指数快照行 */
export interface IndexRow {
  symbol: string
  date: string
  close: number
  volume: number
  pct_chg: number
}

/** 价格趋势点 */
export interface PriceTrendPoint {
  t: number
  p: number
}

/** 情绪趋势点 */
export interface SentimentPoint {
  t: number
  s: number
}

/** 偏离度趋势点 */
export interface DeviationPoint {
  t: number
  d: number
}

/** 信心趋势点 */
export interface ConfidencePoint {
  t: number
  c: number
}

/** 指标汇总 */
export interface Metrics {
  window_seconds: number
  total_agents: number
  unique_decision_agents_10s: number
  unique_order_agents_10s: number
  completed_trade_agents: number
  completed_decision_agents: number
  broad_market: BroadMarket
}

/** 行为偏差统计 */
export interface BiasStats {
  sell_gain: number
  sell_loss: number
  herding: number
  contrarian: number
  overconfident: number
  total: number
  loss_hold: number
  loss_sell: number
  loss_buy: number
  gain_hold: number
  gain_sell: number
  gain_buy: number
  disposition_effect: number
  lottery_preference: number
  underdiversified: number
  loss_aversion: number
  loss_gain_by_tom: Record<string, { loss_hold: number; loss_sell: number; loss_buy: number; gain_hold: number; gain_sell: number; gain_buy: number }>
  bubble_flag: boolean
  avg_confidence: number | null
  avg_deviation_pct: number | null
  confidence_price_correlation: number | null
  bubble_phase: string
  polarization_index: number | null
  extreme_ratio: number | null
  echo_chamber_index: number | null
  homophily_excess: number | null
}

/** 信息传播统计 */
export interface CascadeStats {
  total: number
  has_news: number
  total_perceived: number
  following_authors: number
  by_tom?: Record<string, { total: number; has_news: number; total_perceived: number; following_authors: number }>
}

/** 流动性统计（按 ToM 阶层） */
export type LiquidityStats = Record<string, { maker: number; taker: number }>

/** 计划执行统计 */
export interface PlanStats {
  total: number
  adhered: number
  deviated: number
  by_tom?: Record<string, { total: number; adhered: number; deviated: number }>
}

/** 单日按 ToM 的偏差比率快照（与 server._snapshot_bias_trend 一致） */
export interface BiasTrendTomSlice {
  disposition: number
  overconfidence: number
  underdiversified: number
  lottery: number
  herding: number
  total: number
}

export interface BiasTrendPoint {
  day: number
  tom0: BiasTrendTomSlice
  tom1: BiasTrendTomSlice
  tom2: BiasTrendTomSlice
}

/** 完整状态 payload（后端 _build_state 返回结构） */
export interface MarketState {
  server_time: number
  sim_time: number
  trading_day: number
  trading_day_seconds: number
  metrics: Metrics
  index_snapshot: IndexRow[]
  index_series: Record<string, IndexRow[]>
  broad_index_series: IndexRow[]
  active: ActiveState
  holdings: AgentHolding[]
  social_hot: SocialPost[]
  social_latest: SocialPost[]
  social_news: SocialPost[]
  tom_summary: Record<string, TomLevelSummary>
  technical_indicators: Record<string, TechnicalIndicator>
  price_trend: Record<string, PriceTrendPoint[]>
  sentiment_trend: SentimentPoint[]
  confidence_trend: ConfidencePoint[]
  deviation_trend: DeviationPoint[]
  cda: CDAData
  cda_by_symbol: Record<string, CDAData>
  market_micro: Record<string, MarketMicro>
  social_graph: Record<string, unknown>
  bias_stats: BiasStats
  bias_trends: BiasTrendPoint[]
  cascade_stats: CascadeStats
  liquidity_stats: LiquidityStats
  plan_stats: PlanStats
  mm_subsidy?: { cash_injected: number; cash_absorbed: number; shares_created: number; shares_absorbed: number; trade_count: number }
}

/** WebSocket 消息 */
export type WSMessage =
  | { type: 'full_state'; data: MarketState }
  | { type: 'event_trade'; data: TradeRecord }
  | { type: 'event_decision'; data: IncrementalDecision }

export interface IncrementalDecision {
  sim_time: number
  agent_id: number
  tom_level: number
  action: string
  symbol: string
  decision_scope?: string
  status: string
  price: number
  quantity: number
  tool_trace?: ToolCall[]
  reasoning?: string
}

/** Agent 在 Arena 中的视觉状态 */
export interface AgentVisual {
  id: number
  tomLevel: number
  emotion: 'neutral' | 'happy' | 'worried' | 'thinking' | 'scheming'
  phase: 'idle' | 'thinking' | 'decided' | 'trading'
  lastAction?: string
  wealth: number
  pnlDirection: 'up' | 'down' | 'flat'
}
