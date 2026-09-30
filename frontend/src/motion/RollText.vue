<script setup lang="ts">
import { onBeforeUpdate, onUpdated, ref } from 'vue'
import { morphSize, sizeOf, type Size } from './morph'

/**
 * 滚动换字：value 变了时旧内容沿 direction 滚出、新内容从另一侧滚入，用于计价牌、计数、按钮文案一类的短内容。
 * 旧内容离场时脱离文档流叠在原处，新内容立即占位，外框宽度随之平滑过渡（morph=false 时交给外层，比如整颗按钮的 v-morph）。
 * 默认显示 value；也可以用插槽放带样式的内容，此时 value 只是“换没换”的判据。
 */
const props = withDefaults(defineProps<{
  value: string | number
  /** 1：新内容自下而上滚入（数值变大、往后切换）；-1：自上而下。 */
  direction?: 1 | -1
  /** 入场延迟（ms），同一次切换里几处换字错开先后。 */
  delay?: number
  morph?: boolean
}>(), { direction: 1, delay: 0, morph: true })

const root = ref<HTMLElement | null>(null)
let before: Size | null = null

onBeforeUpdate(() => {
  before = props.morph && root.value ? sizeOf(root.value) : null
})

onUpdated(() => {
  // 换字期间自己按窗口裁切（见样式），过渡不必再另加裁切。
  if (before && root.value) morphSize(root.value, before, { delay: props.delay, clip: false })
  before = null
})
</script>

<template>
  <span
    ref="root"
    class="roll-text"
    :class="{ 'roll-text--morph': morph }"
    :style="{ '--roll-dir': direction, '--roll-delay': `${delay}ms` }"
  >
    <Transition name="roll-text">
      <span :key="value" class="roll-text-value"><slot>{{ value }}</slot></span>
    </Transition>
  </span>
</template>

<style scoped>
.roll-text {
  position: relative;
  display: inline-flex;
  white-space: nowrap;
}

.roll-text-value {
  display: inline-flex;
  align-items: baseline;
}

/* 换字期间只在自己的框里滚（像计数器的窗口），不压到上下相邻的内容；外框宽度跟着过渡时连右缘一起裁，
   新内容随外框展开露出来。 */
.roll-text:has(> .roll-text-enter-active, > .roll-text-leave-active) {
  clip-path: inset(-0.15em -100vmax);
}

.roll-text--morph:has(> .roll-text-enter-active, > .roll-text-leave-active) {
  clip-path: inset(-0.15em -3px);
}

/* 旧内容一出发就淡掉，新内容晚一拍显形、位移带弹簧落定：两者只在一瞬间交叠，不会叠成重影。 */
.roll-text-enter-active {
  transition:
    opacity 200ms var(--motion-ease-out) calc(var(--roll-delay) + 40ms),
    translate 520ms var(--motion-spring) var(--roll-delay);
}

.roll-text-leave-active {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  transition:
    opacity 130ms var(--motion-ease-out),
    translate 260ms var(--motion-ease-out);
}

.roll-text-enter-from {
  opacity: 0;
  translate: 0 calc(var(--roll-dir) * 60%);
}

.roll-text-leave-to {
  opacity: 0;
  translate: 0 calc(var(--roll-dir) * -60%);
}
</style>
