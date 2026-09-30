import type { Directive } from 'vue'
import { EASE_OUT, canAnimate } from './motion'

/**
 * v-swap：绑定的 key 变了（换了一批内容：切换筛选、翻月、切换计费周期）时，让元素的新内容淡入浮现，
 * 取代原先的瞬间替换。key 为 null/undefined 表示内容还在加载，不播；从加载态回到有值时再播。
 * stagger 让直接子元素依次入场（列表、网格），x/y 是入场时从哪个方向偏移过来（px）。
 */
export interface SwapOptions {
  key: unknown
  x?: number
  y?: number
  stagger?: boolean
}

const SWAP_MS = 340
const STAGGER_MS = 26
// 超出这个数量的子元素不再逐个设动画：长列表首屏以下的项看不见入场，没必要。
const STAGGER_LIMIT = 36

export const vSwap: Directive<HTMLElement, SwapOptions> = {
  updated(el, binding) {
    const { key, x = 0, y = 10, stagger = false } = binding.value
    if (key == null || Object.is(key, binding.oldValue?.key) || !canAnimate(el)) return
    const targets = stagger
      ? Array.from(el.children).filter((child): child is HTMLElement => child instanceof HTMLElement).slice(0, STAGGER_LIMIT)
      : [el]
    targets.forEach((target, index) => {
      for (const running of target.getAnimations()) if (running.id === 'swap') running.cancel()
      const animation = target.animate(
        [{ opacity: 0, translate: `${x}px ${y}px` }, { opacity: 1, translate: '0 0' }],
        { duration: SWAP_MS, delay: stagger ? Math.min(index, 12) * STAGGER_MS : 0, easing: EASE_OUT, fill: 'backwards' },
      )
      animation.id = 'swap'
    })
  },
}
