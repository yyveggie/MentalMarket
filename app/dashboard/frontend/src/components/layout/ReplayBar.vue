<script setup lang="ts">
/** 离线回放控制条：播放 / 暂停、倍速、进度、重播。仅在打包的回放页面里出现。 */
import { computed } from 'vue'
import { replay, replayToggle, replaySetSpeed, replaySpeeds, replayRestart, formatClock } from '@/composables/useReplay'

const progress = computed(() => (replay.duration > 0 ? Math.min(100, (replay.elapsed / replay.duration) * 100) : 0))
</script>

<template>
  <div class="rp" :class="{ err: !!replay.error }">
    <template v-if="replay.error">
      <span class="rp-tag">回放</span>
      <span class="rp-err">{{ replay.error }}</span>
    </template>
    <template v-else-if="!replay.ready">
      <span class="rp-tag">回放</span>
      <span class="rp-dim">正在解码录制数据…</span>
    </template>
    <template v-else>
      <span class="rp-tag">回放</span>
      <button class="rp-btn main" :title="replay.playing ? '暂停' : '播放'" @click="replay.ended ? replayRestart() : replayToggle()">
        <svg v-if="replay.ended" viewBox="0 0 16 16" width="12" height="12"><path d="M8 3a5 5 0 1 0 4.5 2.8" fill="none" stroke="currentColor" stroke-width="1.8" /><path d="M12.6 1.8v3.6H9" fill="none" stroke="currentColor" stroke-width="1.8" /></svg>
        <svg v-else-if="replay.playing" viewBox="0 0 16 16" width="12" height="12"><rect x="3" y="2.5" width="3.5" height="11" fill="currentColor" /><rect x="9.5" y="2.5" width="3.5" height="11" fill="currentColor" /></svg>
        <svg v-else viewBox="0 0 16 16" width="12" height="12"><path d="M4 2.5v11l9-5.5z" fill="currentColor" /></svg>
      </button>
      <div class="rp-progress" :title="`${replay.index} / ${replay.total} 条消息`">
        <i :style="{ width: `${progress}%` }" />
      </div>
      <span class="rp-clock">{{ formatClock(replay.elapsed) }} / {{ formatClock(replay.duration) }}</span>
      <span class="rp-speeds">
        <button
          v-for="s in replaySpeeds()"
          :key="s"
          class="rp-btn"
          :class="{ active: replay.speed === s }"
          @click="replaySetSpeed(s)"
        >{{ s }}×</button>
      </span>
      <button class="rp-btn" title="从头重播" @click="replayRestart()">重播</button>
      <span v-if="replay.title" class="rp-title">{{ replay.title }}</span>
    </template>
  </div>
</template>

<style scoped>
.rp {
  position: fixed;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  z-index: 200;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 999px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.rp.err {
  color: var(--down);
}

.rp-tag {
  font-weight: 700;
  color: var(--accent-3);
  letter-spacing: 0.04em;
}

.rp-dim {
  color: var(--text-dim);
}

.rp-err {
  max-width: 480px;
  white-space: normal;
}

.rp-btn {
  border: none;
  background: var(--surface-1);
  color: var(--text-muted);
  padding: 3px 8px;
  border-radius: 999px;
  font-family: inherit;
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.rp-btn:hover {
  color: var(--text);
}

.rp-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

.rp-btn.main {
  width: 26px;
  height: 26px;
  padding: 0;
  background: var(--accent);
  color: #fff;
}

.rp-progress {
  position: relative;
  width: 220px;
  height: 5px;
  border-radius: 3px;
  background: var(--surface-2);
  overflow: hidden;
}

.rp-progress i {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}

.rp-clock {
  color: var(--text-muted);
}

.rp-speeds {
  display: inline-flex;
  gap: 3px;
}

.rp-title {
  color: var(--text-dim);
  padding-left: 6px;
  border-left: 1px solid var(--border);
}
</style>
