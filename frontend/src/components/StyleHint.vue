<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * 风格开关下方的一次性气泡：告诉人可以换成简洁版，给「换成简洁版」和「知道了」两个按钮。不抢焦点、不挡页面：
 * 点别处、按 Esc、开关滚出视野都算关掉。位置跟着开关走（首页的报头会随页面滚动）。
 */
const props = defineProps<{ anchor: HTMLElement | null }>()
const emit = defineEmits<{ switch: []; dismiss: [] }>()
const { t } = useI18n()

const card = ref<HTMLElement | null>(null)
const position = ref({ top: 0, left: 0, tail: 0 })
let frame = 0

const GAP = 12
const MARGIN = 8
// 尖角离卡片右缘的距离：卡片往开关左下方展开，开关在报头右端，往右没地方。
const TAIL_FROM_RIGHT = 28

function place() {
  frame = 0
  const anchor = props.anchor
  const el = card.value
  if (!anchor || !el) return
  const rect = anchor.getBoundingClientRect()
  if (!anchor.isConnected || rect.width === 0 || rect.bottom <= 0 || rect.top >= window.innerHeight) {
    emit('dismiss')
    return
  }
  const width = el.offsetWidth
  const center = rect.left + rect.width / 2
  const left = Math.max(MARGIN, Math.min(center - width + TAIL_FROM_RIGHT, window.innerWidth - width - MARGIN))
  position.value = { top: rect.bottom + GAP, left, tail: Math.max(16, Math.min(center - left, width - 16)) }
}
const schedule = () => { if (!frame) frame = requestAnimationFrame(place) }

function onPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  // 按开关本身由开关处理（换版并关掉提示）。
  if (card.value?.contains(target) || props.anchor?.contains(target)) return
  emit('dismiss')
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('dismiss')
}

onMounted(async () => {
  await nextTick()
  place()
  window.addEventListener('resize', schedule)
  window.addEventListener('scroll', schedule, { capture: true, passive: true })
  document.addEventListener('pointerdown', onPointerDown, true)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  window.removeEventListener('resize', schedule)
  window.removeEventListener('scroll', schedule, { capture: true })
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    ref="card"
    class="style-hint"
    role="dialog"
    aria-modal="false"
    aria-labelledby="style-hint-title"
    aria-describedby="style-hint-body"
    :style="{ top: `${position.top}px`, left: `${position.left}px`, '--style-hint-tail': `${position.tail}px` }"
  >
    <p id="style-hint-title" class="style-hint__title">{{ t('appStyle.hintTitle') }}</p>
    <p id="style-hint-body" class="style-hint__body">{{ t('appStyle.hintBody') }}</p>
    <div class="style-hint__actions">
      <button type="button" class="btn-primary style-hint__switch" @click="emit('switch')">{{ t('appStyle.hintSwitch') }}</button>
      <button type="button" class="btn-ghost style-hint__dismiss" @click="emit('dismiss')">{{ t('appStyle.hintDismiss') }}</button>
    </div>
  </div>
</template>

<style scoped>
/* 只在漫画版出现，用漫画的笔墨：纸面、硬描边、实心偏移投影，尖角指着开关。 */
.style-hint {
  position: fixed;
  z-index: 110; /* 压过报头（100），尖角要搭在报头下缘上 */
  width: min(300px, calc(100vw - 16px));
  box-sizing: border-box;
  padding: 14px 16px;
  color: var(--ink);
  background: var(--paper-raised);
  border: 2px solid var(--hard-ink);
  border-radius: var(--control-radius);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  transform-origin: var(--style-hint-tail) 0;
}
.style-hint::before {
  content: '';
  position: absolute;
  top: -8px;
  left: calc(var(--style-hint-tail) - 7px);
  width: 12px;
  height: 12px;
  background: var(--paper-raised);
  border-top: 2px solid var(--hard-ink);
  border-left: 2px solid var(--hard-ink);
  transform: rotate(45deg);
}
.style-hint__title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  line-height: 1.35;
}
.style-hint__body {
  margin: 6px 0 0;
  color: var(--ink-secondary);
  font-size: 13.5px;
  line-height: 1.6;
}
.style-hint__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.style-hint__actions :is(.btn-primary, .btn-ghost) {
  padding: 6px 12px;
  font-size: 13px;
}
</style>
