<script setup lang="ts">
/**
 * 本版工具：桌面内页有报眉时，页面把自己的筛选、切换、刷新交给它，传送进报眉中间那一栏（LayoutView 的
 * #masthead-page-tools），页面里就不必再单占一行。full 放不下就试 compact；两档都放不下（窄桌面、长语言）或根本
 * 没有报眉（手机、首页、联系页）时，工具原样留在页面里。
 *
 * 放不放得下在报眉里量：放一个看不见的替身，逐档挂上 data-folio 读它的自然宽度，与空位比。量法与工具此刻在
 * 哪儿无关，不会放进去又被挤出来、来回跳。进出报眉时滑入滑出；整页离开时留一个替身在原处滑走。
 */
import { computed, inject, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import {
  FOLIO_TOOLS_AVAILABLE,
  FOLIO_TOOLS_LEVELS,
  FOLIO_TOOLS_TARGET_ID,
  type FolioToolsLevel,
} from '@/features/navigation/folioTools'
import { canAnimate } from '@/motion/motion'
import { slideIn, slideOut } from '@/motion/presence'

defineSlots<{ default(props: { level: FolioToolsLevel | null }): unknown }>()

const target = `#${FOLIO_TOOLS_TARGET_ID}`
const SHIFT = { y: -8 }

const available = inject(FOLIO_TOOLS_AVAILABLE, ref(false))
const box = ref<HTMLElement | null>(null)
// 先当放得下：首屏直接画进报眉，挂载后量过不合适再换档或挪回页面，都在同一帧里，不闪。
const fit = ref<FolioToolsLevel | null>('full')
// KeepAlive 缓存的页面切走后，传送出去的工具不会跟着页面收起，得自己从报眉里撤下。
const live = ref(true)
const level = computed(() => (available.value ? fit.value : null))
const placed = computed(() => level.value !== null)

/** 不能交互、读屏跳过、不带 id 的复制品：量宽的替身和离场的替身都用它。 */
function standIn(node: HTMLElement): HTMLElement {
  const copy = node.cloneNode(true) as HTMLElement
  for (const el of [copy, ...copy.querySelectorAll('[id]')]) el.removeAttribute('id')
  copy.inert = true
  copy.setAttribute('aria-hidden', 'true')
  return copy
}

function measure() {
  const node = box.value
  const slot = document.getElementById(FOLIO_TOOLS_TARGET_ID)
  const room = slot?.clientWidth
  // 报眉没排版时量不出空位，维持现状。
  if (!available.value || !node?.isConnected || !slot || !room) return
  // 替身是新元素、关掉了过渡，换档立即生效；直接给真身换属性，过渡会让读到的还是换档前的尺寸。
  const probe = standIn(node)
  probe.removeAttribute('style')
  probe.setAttribute('data-folio-probe', '')
  slot.append(probe)
  let next: FolioToolsLevel | null = null
  for (const candidate of FOLIO_TOOLS_LEVELS) {
    probe.setAttribute('data-folio', candidate)
    if (probe.offsetWidth <= room) {
      next = candidate
      break
    }
  }
  probe.remove()
  fit.value = next
}

// 尺寸变化攒到下一帧再量：在 ResizeObserver 回调里直接挪动盒子会触发浏览器的观察循环告警。
let frame = 0
function remeasure() {
  if (frame || typeof requestAnimationFrame !== 'function') return
  frame = requestAnimationFrame(() => {
    frame = 0
    measure()
  })
}

let resizes: ResizeObserver | undefined
let watched: HTMLElement | null = null
function watchBox(node: HTMLElement | null) {
  if (watched) resizes?.unobserve(watched)
  watched = node
  if (node) resizes?.observe(node)
}

onMounted(() => {
  if (typeof ResizeObserver === 'function') {
    resizes = new ResizeObserver(remeasure)
    const slot = document.getElementById(FOLIO_TOOLS_TARGET_ID)
    if (slot) resizes.observe(slot)
  }
  watchBox(box.value)
  measure()
  // 网页字体到齐前量的宽度不作数。
  void document.fonts?.ready.then(measure)
})

watch(box, (node) => {
  watchBox(node)
  measure()
}, { flush: 'post' })
watch(available, measure, { flush: 'post' })

onActivated(() => { live.value = true })
onDeactivated(() => { live.value = false })

const inFolio = (el: Element) => el.hasAttribute('data-folio')

function enter(el: Element, done: () => void) {
  if (inFolio(el)) slideIn(el, done, SHIFT)
  else done()
}

function leave(el: Element, done: () => void) {
  if (inFolio(el)) slideOut(el, done, SHIFT)
  else done()
}

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame)
  resizes?.disconnect()
  // 整页卸载时 Vue 直接摘掉报眉里的工具、不播离场；留一个替身在原处滑走，和页面的淡出同步。
  const node = box.value
  if (!node?.isConnected || !inFolio(node) || !canAnimate(node)) return
  const ghost = standIn(node)
  Object.assign(ghost.style, {
    position: 'absolute',
    left: `${node.offsetLeft}px`,
    top: `${node.offsetTop}px`,
    width: `${node.offsetWidth}px`,
    margin: '0',
  })
  node.after(ghost)
  slideOut(ghost, () => ghost.remove(), SHIFT)
})
</script>

<template>
  <Teleport defer :to="target" :disabled="!placed">
    <Transition :css="false" appear @enter="enter" @leave="leave">
      <div v-if="live || !placed" ref="box" class="folio-tools" :data-folio="level ?? undefined">
        <slot :level="level" />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 报眉里按内容定宽、不折行：空位不够时整组换档或挪回页面，而不是被挤扁。 */
.folio-tools[data-folio] {
  flex: none;
  width: max-content;
}

/* 量宽的替身：不占位、看不见（插进去量完当场摘掉，不会画出来）。 */
.folio-tools[data-folio-probe] {
  position: absolute;
  top: 0;
  right: 0;
  visibility: hidden;
}

.folio-tools[data-folio-probe],
.folio-tools[data-folio-probe] :deep(*) {
  transition: none !important;
  animation: none !important;
}
</style>
