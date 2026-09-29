<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronRight } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

/* 桌面漫画版的编号目录：点击滚到对应小节，滚动时高亮读到的小节。只看正文流里的小节——
   吸顶侧栏里的小节始终可见，点它只闪一下提示位置，不参与滚动高亮。 */
const props = defineProps<{ root: HTMLElement | null; items: { id: string; label: string }[] }>()
const { t } = useI18n()
const nav = ref<HTMLElement | null>(null)
const active = ref(props.items[0]?.id ?? '')
const READING_LINE = 96
let frame = 0
let settle = 0
let locked = false

const sectionOf = (id: string) => document.getElementById(id)
const inFlow = (el: HTMLElement) => {
  const aside = el.closest<HTMLElement>('.legal-aside')
  return !aside || getComputedStyle(aside).position !== 'sticky'
}

const update = () => {
  frame = 0
  const root = props.root
  if (locked || !root || nav.value?.offsetParent == null) return
  const line = root.getBoundingClientRect().top + READING_LINE
  const atEnd = root.scrollTop > 0 && root.scrollTop + root.clientHeight >= root.scrollHeight - 2
  let first = ''
  let current = ''
  for (const item of props.items) {
    const el = sectionOf(item.id)
    if (!el || !inFlow(el)) continue
    first ||= item.id
    if (atEnd || el.getBoundingClientRect().top <= line) current = item.id
  }
  if (current || first) active.value = current || first
}
const schedule = () => {
  if (locked) {
    window.clearTimeout(settle)
    settle = window.setTimeout(() => { locked = false }, 140)
    return
  }
  if (!frame) frame = window.requestAnimationFrame(update)
}

const flash = (el: HTMLElement) => {
  el.classList.remove('is-flash')
  void el.offsetWidth
  el.classList.add('is-flash')
  window.setTimeout(() => el.classList.remove('is-flash'), 900)
}
const go = (id: string) => {
  const el = sectionOf(id)
  const root = props.root
  if (!el || !root) return
  active.value = id
  if (!inFlow(el)) return flash(el)
  locked = true
  schedule()
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const top = root.scrollTop + el.getBoundingClientRect().top - root.getBoundingClientRect().top - 16
  root.scrollTo({ top, behavior: reduced ? 'auto' : 'smooth' })
}

watch(() => props.root, (next, previous) => {
  previous?.removeEventListener('scroll', schedule)
  next?.addEventListener('scroll', schedule, { passive: true })
  schedule()
}, { immediate: true })
onMounted(() => window.addEventListener('resize', schedule, { passive: true }))
onBeforeUnmount(() => {
  props.root?.removeEventListener('scroll', schedule)
  window.removeEventListener('resize', schedule)
  window.cancelAnimationFrame(frame)
  window.clearTimeout(settle)
})
</script>

<template>
  <nav ref="nav" class="legal-toc" :aria-label="t('legal.toc')">
    <p class="legal-toc__title" aria-hidden="true">{{ t('legal.toc') }}</p>
    <ol>
      <li v-for="(item, index) in items" :key="item.id">
        <a :href="`#${item.id}`" :aria-current="active === item.id ? 'location' : undefined" @click.prevent="go(item.id)">
          <span class="legal-toc__no">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="legal-toc__label">{{ item.label }}</span>
          <ChevronRight v-if="active === item.id" aria-hidden="true" />
        </a>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
/* 目录只在桌面漫画版展示（comic-pages.css）；窄屏按原样顺读。 */
.legal-toc{display:none}
</style>
