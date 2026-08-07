<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import NumberFlow from '@number-flow/vue'

/* 滚筒数字统一封装：滚动与位移动画恰好 2s 完成，沿用 number-flow 默认回弹曲线。
   number-flow 挂载时静态渲染、仅在 value 变化时滚动变化的数字列
   （如 1306→2309 只滚千位与个位），因此：
   - 挂载后同帧把 0 改成目标值，制造首次 0→N 上滚；
   - 之后每次值变化走库原生差位滚动，无变化则完全静止。 */
const props = withDefaults(defineProps<{
  value: number
  grouping?: boolean
}>(), { grouping: false })

const ROLL_EASING = 'linear(0,.005,.019,.039,.066,.096,.129,.165,.202,.24,.278,.316,.354,.39,.426,.461,.494,.526,.557,.586,.614,.64,.665,.689,.711,.731,.751,.769,.786,.802,.817,.831,.844,.856,.867,.877,.887,.896,.904,.912,.919,.925,.931,.937,.942,.947,.951,.955,.959,.962,.965,.968,.971,.973,.976,.978,.98,.981,.983,.984,.986,.987,.988,.989,.99,.991,.992,.992,.993,.994,.994,.995,.995,.996,.996,.9963,.9967,.9969,.9972,.9975,.9977,.9979,.9981,.9982,.9984,.9985,.9987,.9988,.9989,1)'
const rollTiming = { duration: 2000, easing: ROLL_EASING }

const shown = ref(0)

onMounted(() => {
  shown.value = props.value
})

watch(() => props.value, (value) => {
  shown.value = value
})
</script>

<template>
  <NumberFlow
    :value="shown"
    :format="{ useGrouping: grouping }"
    :transform-timing="rollTiming"
    :spin-timing="rollTiming"
  />
</template>
