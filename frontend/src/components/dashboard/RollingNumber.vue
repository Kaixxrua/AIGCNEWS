<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import NumberFlow from '@number-flow/vue'

/* 滚筒数字统一封装：滚动与位移动画恰好 2s 完成，沿用 number-flow 默认回弹曲线。
   number-flow 仅在 value 变化时滚动、挂载时静态渲染，因此：
   - 挂载后同帧把 0 改成目标值，制造首次 0→N 上滚；
   - tick 递增时先静态归零（animated=false 不滚动），再滚回目标值，实现每 10s 一次的重滚。 */
const props = withDefaults(defineProps<{
  value: number
  grouping?: boolean
  tick?: number
}>(), { grouping: false, tick: 0 })

const ROLL_EASING = 'linear(0,.005,.019,.039,.066,.096,.129,.165,.202,.24,.278,.316,.354,.39,.426,.461,.494,.526,.557,.586,.614,.64,.665,.689,.711,.731,.751,.769,.786,.802,.817,.831,.844,.856,.867,.877,.887,.896,.904,.912,.919,.925,.931,.937,.942,.947,.951,.955,.959,.962,.965,.968,.971,.973,.976,.978,.98,.981,.983,.984,.986,.987,.988,.989,.99,.991,.992,.992,.993,.994,.994,.995,.995,.996,.996,.9963,.9967,.9969,.9972,.9975,.9977,.9979,.9981,.9982,.9984,.9985,.9987,.9988,.9989,1)'
const rollTiming = { duration: 2000, easing: ROLL_EASING }

const shown = ref(0)
const animated = ref(true)

const nextFrame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()))

onMounted(() => {
  shown.value = props.value
})

watch(() => props.value, (value) => {
  shown.value = value
})

watch(() => props.tick, async (tick) => {
  if (!tick) return
  animated.value = false
  shown.value = 0
  await nextTick()
  await nextFrame()
  animated.value = true
  shown.value = props.value
})
</script>

<template>
  <NumberFlow
    :value="shown"
    :format="{ useGrouping: grouping }"
    :animated="animated"
    :transform-timing="rollTiming"
    :spin-timing="rollTiming"
  />
</template>
