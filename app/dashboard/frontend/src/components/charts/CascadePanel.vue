<script setup lang="ts">
/** 信息传播链路：按 ToM 阶层的感知统计表（全部 + ToM0/1/2 一屏对照，数值右对齐）。 */
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import { useTooltip, pct } from '@/composables/useTooltip'
import { fmtInt } from '@/utils/formatters'

const store = useMarketStore()
const { activeTooltip, showTip, hideTip } = useTooltip()
const tip = '感知帖数 = 每次决策时 Agent 看到的社交帖子数（平均）\n新闻曝光率 = 感知到新闻帖的决策占比\n关注者帖子 = 来自已关注用户的帖子被看到的累计次数\n感知事件 = 累计决策次数（每次决策记一次感知）'

interface Row {
  key: string
  label: string
  color: string
  avgPerceived: string
  newsExposure: string
  newsRatio: number
  following: number
  total: number
}

const rows = computed<Row[]>(() => {
  const defs = [
    { key: 'all', label: '全部', color: 'var(--heading)' },
    { key: '0', label: 'ToM0', color: '#78909c' },
    { key: '1', label: 'ToM1', color: '#0288d1' },
    { key: '2', label: 'ToM2', color: '#7c4dff' },
  ]
  return defs.map((d) => {
    const c = d.key === 'all'
      ? store.cascadeStats
      : (store.cascadeStats.by_tom?.[d.key] ?? { total: 0, has_news: 0, total_perceived: 0, following_authors: 0 })
    return {
      key: d.key,
      label: d.label,
      color: d.color,
      avgPerceived: c.total > 0 ? (c.total_perceived / c.total).toFixed(1) : '-',
      newsExposure: pct(c.has_news, c.total),
      newsRatio: c.total > 0 ? c.has_news / c.total : 0,
      following: c.following_authors,
      total: c.total,
    }
  })
})
</script>

<template>
  <div class="card">
    <div class="card-title">信息传播链路
      <span class="info-btn" @mouseenter="showTip('c')" @mouseleave="hideTip">i</span>
      <div v-if="activeTooltip === 'c'" class="custom-tooltip">{{ tip }}</div>
    </div>
    <div class="cas-table">
      <div class="cas-head">
        <span class="c-label">阶层</span>
        <span class="c-num">感知帖数</span>
        <span class="c-news">新闻曝光率</span>
        <span class="c-num">关注者帖子</span>
        <span class="c-num">感知事件</span>
      </div>
      <div v-for="r in rows" :key="r.key" class="cas-row" :class="{ total: r.key === 'all' }">
        <span class="c-label" :style="{ color: r.color }">{{ r.label }}</span>
        <span class="c-num">{{ r.avgPerceived }}</span>
        <span class="c-news">
          <i class="news-bar"><b :style="{ width: `${Math.min(100, r.newsRatio * 100)}%` }" /></i>
          <em>{{ r.newsExposure }}</em>
        </span>
        <span class="c-num">{{ fmtInt(r.following) }}</span>
        <span class="c-num">{{ fmtInt(r.total) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import '@/styles/analytics-shared.css';

.cas-table {
  display: flex;
  flex-direction: column;
  font-variant-numeric: tabular-nums;
}

.cas-head,
.cas-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border);
}

.cas-head {
  font-size: 10px;
  color: var(--text-dim);
  padding-top: 0;
}

.cas-row:last-child {
  border-bottom: none;
}

.cas-row.total {
  background: var(--surface-1);
  border-radius: 4px;
}

.c-label {
  font-size: 12px;
  font-weight: 700;
}

.c-num {
  text-align: right;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--heading);
}

.cas-head .c-num,
.cas-head .c-news {
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 400;
  color: var(--text-dim);
  text-align: right;
}

.c-news {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.c-news em {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--heading);
  min-width: 48px;
  text-align: right;
}

.news-bar {
  flex: 1;
  max-width: 90px;
  height: 5px;
  border-radius: 3px;
  background: var(--surface-2);
  overflow: hidden;
}

.news-bar b {
  display: block;
  height: 100%;
  background: var(--accent);
  opacity: 0.7;
  border-radius: 3px;
  transition: width 0.3s ease;
}
</style>
