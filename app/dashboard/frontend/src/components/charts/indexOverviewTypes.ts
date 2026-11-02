/** 指数总览卡片数据（由 IndexOverview 计算，IndexCard 展示） */
export interface IndexCardData {
  symbol: string
  price: number
  pctChg: number
  volume: number
  high: number
  low: number
  realHigh: number
  realLow: number
  simHigh: number
  simLow: number
  normHigh: number
  normLow: number
  closedDays: number
  closedMask: boolean[]
  realSparklineRaw: Array<number | null>
  simSparklineRaw: Array<number | null>
  normRealSparkline: Array<number | null>
  normSimSparkline: Array<number | null>
  predictionSameDayAccuracyPct: number | null
  predictionSameDaySampleCount: number
  predictionForward1AccuracyPct: number | null
  predictionForward1SampleCount: number
  predictionAccuracyPct: number | null
  predictionSampleCount: number
  volatilityFitPct: number | null
  fitSampleCount: number
  qlike: number | null
  logRmse: number | null
  mzAlpha: number | null
  mzBeta: number | null
  mzR2: number | null
  mzWaldChi2: number | null
  mzPValue: number | null
  mzSampleCount: number
  firstDate: string | null
  lastDate: string | null
}
