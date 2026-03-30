<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'

const props = defineProps<{ show: boolean }>()

const wrapperRef = ref<HTMLElement>()
const isAnimating = ref(false)
const innerVisible = ref(props.show)

function expand(el: HTMLElement) {
  isAnimating.value = true
  innerVisible.value = true
  nextTick(() => {
    el.style.overflow = 'hidden'
    el.style.height = '0'
    void el.offsetHeight
    el.style.transition = 'height 0.25s ease, opacity 0.2s ease'
    el.style.opacity = '1'
    el.style.height = el.scrollHeight + 'px'
  })
}

function collapse(el: HTMLElement) {
  isAnimating.value = true
  el.style.overflow = 'hidden'
  el.style.height = el.scrollHeight + 'px'
  void el.offsetHeight
  el.style.transition = 'height 0.25s ease, opacity 0.2s ease'
  el.style.opacity = '0'
  el.style.height = '0'
}

function onTransitionEnd() {
  const el = wrapperRef.value
  if (!el) return
  isAnimating.value = false
  if (props.show) {
    el.style.height = ''
    el.style.overflow = ''
    el.style.opacity = ''
    el.style.transition = ''
  } else {
    innerVisible.value = false
    el.style.height = ''
    el.style.overflow = ''
    el.style.opacity = ''
    el.style.transition = ''
  }
}

watch(() => props.show, (val) => {
  const el = wrapperRef.value
  if (!el) {
    innerVisible.value = val
    return
  }
  if (val) {
    expand(el)
  } else {
    collapse(el)
  }
})

onMounted(() => {
  if (!props.show && wrapperRef.value) {
    wrapperRef.value.style.height = '0'
    wrapperRef.value.style.overflow = 'hidden'
    wrapperRef.value.style.opacity = '0'
    innerVisible.value = false
  }
})
</script>

<template>
  <div ref="wrapperRef" @transitionend.self="onTransitionEnd">
    <div v-show="innerVisible || isAnimating">
      <slot />
    </div>
  </div>
</template>
