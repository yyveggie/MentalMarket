<script setup lang="ts">
import { computed } from 'vue'
import { useMarketStore } from '@/stores/marketStore'
import PostBubble from './PostBubble.vue'

const store = useMarketStore()

const latestPosts = computed(() =>
  store.socialLatest.filter((p) => p.source !== 'news'),
)

const hotPosts = computed(() =>
  store.socialHot.filter((p) => p.source !== 'news'),
)

const newsPosts = computed(() => store.socialNews)
</script>

<template>
  <div class="feed-row">
    <!-- 最新帖子 -->
    <div class="feed-col">
      <div class="feed-header">最新帖子</div>
      <div class="feed-scroll">
        <PostBubble
          v-for="post in latestPosts"
          :key="post.post_id"
          :post="post"
        />
        <div v-if="latestPosts.length === 0" class="empty"></div>
      </div>
    </div>

    <!-- 热门帖子 -->
    <div class="feed-col">
      <div class="feed-header">热门帖子</div>
      <div class="feed-scroll">
        <PostBubble
          v-for="post in hotPosts"
          :key="post.post_id"
          :post="post"
        />
        <div v-if="hotPosts.length === 0" class="empty"></div>
      </div>
    </div>

    <!-- 新闻动态 -->
    <div class="feed-col">
      <div class="feed-header">新闻动态</div>
      <div class="feed-scroll">
        <PostBubble
          v-for="post in newsPosts"
          :key="post.post_id"
          :post="post"
        />
        <div v-if="newsPosts.length === 0" class="empty"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feed-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  height: 100%;
}

.feed-col {
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg);
  background: var(--surface-0);
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
}

.feed-header {
  padding: 16px 16px 12px;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  color: var(--heading);
  letter-spacing: 0;
  flex-shrink: 0;
}

.feed-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-2) transparent;
}

.empty {
  text-align: center;
  color: var(--text-dim);
  padding: 20px;
  font-size: 12px;
}

</style>
