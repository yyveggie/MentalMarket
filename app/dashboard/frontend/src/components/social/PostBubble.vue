<script setup lang="ts">
import { computed } from 'vue'
import type { SocialPost } from '@/types/market'
import { fmt } from '@/utils/formatters'

const props = defineProps<{
  post: SocialPost
  highlight?: boolean
}>()

const sourceBadge = computed(() => {
  switch (props.post.source) {
    case 'news': return { label: '新闻', class: 'badge-news' }
    case 'retweet': return { label: '转发', class: 'badge-retweet' }
    case 'agent_fud': return { label: 'FUD', class: 'badge-fud' }
    default: return null
  }
})

const isHot = computed(() => props.post.likes - (props.post.dislikes || 0) + props.post.retweet_count * 3 >= 5)
const isSystem = computed(() => props.post.agent_id === -1)
const showEngagement = computed(() => props.post.source !== 'news')
const DEFAULT_TRADING_DAY_SECONDS = 3600

const tradingDayDisplay = computed(() => {
  const td = Number(props.post.trading_day)
  if (Number.isFinite(td) && td > 0) {
    return `交易日${Math.floor(td)}`
  }
  const ts = Number(props.post.timestamp)
  if (Number.isFinite(ts) && ts >= 0) {
    return `交易日${Math.floor(ts / DEFAULT_TRADING_DAY_SECONDS) + 1}`
  }
  return '交易日未知'
})
</script>

<template>
  <div
    class="post-bubble"
    :class="{
      'hot-glow': isHot,
      highlight,
    }"
  >
    <div class="post-header">
      <span class="post-author" :class="isSystem ? 'system' : ''">
        {{ isSystem ? '📢 系统' : `A${post.agent_id}` }}
      </span>
      <span v-if="sourceBadge" class="badge" :class="sourceBadge.class">
        {{ sourceBadge.label }}
      </span>
      <span class="post-time">{{ tradingDayDisplay }}</span>
      <span class="post-time">T={{ fmt(post.timestamp, 1) }}</span>
    </div>

    <div class="post-content">{{ post.content }}</div>

    <div class="post-footer">
      <span v-if="showEngagement" class="stat">❤️ {{ post.likes }}</span>
      <span v-if="showEngagement" class="stat">👎 {{ post.dislikes || 0 }}</span>
      <span v-if="showEngagement" class="stat">🔁 {{ post.retweet_count }}</span>
      <span v-if="post.original_post_id" class="stat">📎 #{{ post.original_post_id }}</span>
    </div>
  </div>
</template>

<style scoped>
.post-bubble {
  padding: 10px 12px;
  transition: background var(--transition);
  animation: fade-in 0.3s ease;
}

.post-bubble:hover {
  background: rgba(41, 98, 255, 0.03);
}

.post-bubble.hot-glow {
  border-left: 2px solid var(--accent-3);
}

.post-bubble.highlight {
  background: rgba(41, 98, 255, 0.04);
}

.post-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
}

.post-author {
  font-weight: 700;
  color: var(--heading);
}

.post-author.system {
  color: var(--accent-3);
}

.post-time {
  color: var(--text-dim);
}

.post-content {
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
  word-break: break-all;
  margin-bottom: 6px;
}

.post-footer {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

.stat {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.badge-retweet {
  background: rgba(72, 219, 251, 0.08);
  color: var(--accent-2);
}

.badge-fud {
  background: var(--down-soft);
  color: var(--down);
}
</style>
