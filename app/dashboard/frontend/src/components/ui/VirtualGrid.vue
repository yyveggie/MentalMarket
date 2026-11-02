<script setup lang="ts" generic="T extends Record<string, any>">
/**
 * 等高卡片的虚拟滚动网格：只渲染视口内的行（上下各多渲染一行做缓冲）。
 * 1000 个持仓卡片时 DOM 里只有几十个节点，滚动与每秒的状态刷新都不再卡顿。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    items: T[]
    itemHeight: number
    minColWidth: number
    height: number
    keyField: keyof T & string
    gap?: number
  }>(),
  { gap: 4 },
)

defineSlots<{
  item(props: { item: T; index: number }): any
}>()

const container = ref<HTMLElement>()
const width = ref(0)
const scrollTop = ref(0)
let scrollRaf: number | null = null
let resizeObs: ResizeObserver | null = null

const cols = computed(() => Math.max(1, Math.floor((width.value + props.gap) / (props.minColWidth + props.gap))))
const rowHeight = computed(() => props.itemHeight + props.gap)
const rowCount = computed(() => Math.ceil(props.items.length / cols.value))
const totalHeight = computed(() => Math.max(0, rowCount.value * rowHeight.value - props.gap))

const startRow = computed(() => Math.max(0, Math.floor(scrollTop.value / rowHeight.value) - 1))
const endRow = computed(() => Math.min(rowCount.value, Math.ceil((scrollTop.value + props.height) / rowHeight.value) + 1))
const offsetY = computed(() => startRow.value * rowHeight.value)
const visible = computed(() => {
  const start = startRow.value * cols.value
  const end = endRow.value * cols.value
  return props.items.slice(start, end).map((item, i) => ({ item, index: start + i }))
})

function onScroll() {
  if (scrollRaf != null) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null
    scrollTop.value = container.value?.scrollTop ?? 0
  })
}

onMounted(() => {
  if (!container.value) return
  width.value = container.value.clientWidth
  resizeObs = new ResizeObserver(() => {
    width.value = container.value?.clientWidth ?? 0
  })
  resizeObs.observe(container.value)
})

onBeforeUnmount(() => {
  resizeObs?.disconnect()
  if (scrollRaf != null) cancelAnimationFrame(scrollRaf)
})
</script>

<template>
  <div ref="container" class="vgrid" :style="{ height: `${height}px` }" @scroll.passive="onScroll">
    <div class="vgrid-spacer" :style="{ height: `${totalHeight}px` }">
      <div
        class="vgrid-rows"
        :style="{
          transform: `translateY(${offsetY}px)`,
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gap: `${gap}px`,
        }"
      >
        <div
          v-for="entry in visible"
          :key="String(entry.item[keyField])"
          class="vgrid-cell"
          :style="{ height: `${itemHeight}px` }"
        >
          <slot name="item" :item="entry.item" :index="entry.index" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vgrid {
  overflow-y: auto;
  overflow-anchor: none;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-2) transparent;
  position: relative;
}

.vgrid-spacer {
  position: relative;
  width: 100%;
}

.vgrid-rows {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  display: grid;
  will-change: transform;
}

.vgrid-cell {
  min-width: 0;
  overflow: hidden;
}
</style>
