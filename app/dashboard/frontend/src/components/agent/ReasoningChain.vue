<script setup lang="ts">
import { computed } from 'vue'
import type { Decision } from '@/types/market'
import { fmt } from '@/utils/formatters'

const props = defineProps<{
  decisions: Decision[]
}>()

function actionIcon(action: string): string {
  const a = (action ?? 'hold').toLowerCase()
  if (a === 'buy') return '买'
  if (a === 'sell') return '卖'
  return '持'
}

function toolIcon(name: string): string {
  if (name.includes('trade') || name.includes('plan')) return '计划'
  if (name.includes('social')) return '社交'
  if (name.includes('deception')) return '欺骗'
  return '工具'
}
</script>

<template>
  <div class="reasoning-chain">
    <div v-if="decisions.length === 0" class="empty">
    </div>

    <div
      v-for="(d, i) in decisions"
      :key="`${d.agent_id}-${d.sim_time}-${i}`"
      class="chain-node"
    >
      <div class="node-line">
        <div class="node-dot" :class="d.action?.toLowerCase()">
          {{ actionIcon(d.action ?? 'hold') }}
        </div>
        <div v-if="i < decisions.length - 1" class="node-connector" />
      </div>

      <div class="node-content">
        <div class="node-header">
          <span class="node-time">T={{ fmt(d.sim_time, 1) }}</span>
          <span
            class="badge"
            :class="{
              'badge-buy': d.action?.toLowerCase() === 'buy',
              'badge-sell': d.action?.toLowerCase() === 'sell',
              'badge-hold': d.action?.toLowerCase() === 'hold',
            }"
          >
            {{ (d.action ?? 'hold').toUpperCase() }}
          </span>
          <span v-if="d.action_executed?.price" class="node-trade">
            {{ fmt(d.action_executed.price, 2) }} × {{ d.action_executed.quantity ?? 0 }}
          </span>
        </div>

        <div v-if="d.reasoning" class="node-block belief">
          <span class="block-label">推理</span>
          <p>{{ d.reasoning }}</p>
        </div>

        <div v-if="d.tool_trace?.length" class="node-tools">
          <div v-for="(tool, ti) in d.tool_trace" :key="ti" class="tool-detail">
            <div class="tool-header">
              <span class="badge badge-tool">{{ toolIcon(tool.name) }} {{ tool.name }}</span>
            </div>
            <div v-if="tool.args && Object.keys(tool.args).length" class="tool-body">
              <span class="tool-label">参数</span>
              <div class="tool-kv">
                <span v-for="(val, key) in tool.args" :key="String(key)" class="kv-pair">
                  <em>{{ key }}</em>: {{ typeof val === 'string' ? val : JSON.stringify(val) }}
                </span>
              </div>
            </div>
            <div v-if="tool.result && Object.keys(tool.result).length" class="tool-body tool-result">
              <span class="tool-label">结果</span>
              <span class="kv-pair">{{ typeof tool.result === 'string' ? tool.result : JSON.stringify(tool.result) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reasoning-chain {
  position: relative;
}

.empty {
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  padding: 16px;
}

.chain-node {
  display: flex;
  gap: 10px;
  position: relative;
  padding-bottom: 12px;
}

.node-line {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 24px;
  flex-shrink: 0;
}

.node-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  flex-shrink: 0;
}

.node-connector {
  width: 2px;
  flex: 1;
  background: var(--border);
  margin-top: 2px;
  min-height: 10px;
}

.node-content {
  flex: 1;
  min-width: 0;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  margin-bottom: 4px;
}

.node-time {
  color: var(--text-dim);
}

.node-trade {
  color: var(--text-muted);
}

.node-block {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 8px;
  margin-bottom: 4px;
}

.block-label {
  font-size: 9px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--accent-2);
  display: block;
  margin-bottom: 2px;
}

.node-block p {
  font-size: 11px;
  color: var(--text);
  line-height: 1.4;
  word-break: break-all;
}

.node-block.belief {
  background: var(--surface-1);
}

.node-block.intention {
  background: var(--surface-1);
}

.node-tools {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}

.tool-detail {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 8px;
  font-size: 10px;
}

.tool-header {
  margin-bottom: 3px;
}

.tool-body {
  margin-top: 3px;
  padding-top: 3px;
  border-top: 1px solid var(--border);
}

.tool-result {
  color: var(--text-dim);
}

.tool-label {
  font-size: 9px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--accent-1);
  display: block;
  margin-bottom: 2px;
}

.tool-kv {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.kv-pair {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text);
  word-break: break-all;
  line-height: 1.4;
}

.kv-pair em {
  font-style: normal;
  color: var(--accent-2);
}
</style>
