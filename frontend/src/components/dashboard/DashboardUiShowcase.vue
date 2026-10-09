<script setup lang="ts">
import { computed, onActivated, onDeactivated, ref, watch } from 'vue'
import { useDocumentVisibility, useElementVisibility, usePreferredReducedMotion } from '@vueuse/core'
import { ArrowUpRight, ChevronLeft, ChevronRight, Pause, Play, Sparkles } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { selectUiShowcase, type UiShowcaseItem } from '@/features/dashboard/uiShowcase'

const props = defineProps<{ items: UiShowcaseItem[] }>()
const { t, locale } = useI18n()
const element = ref<HTMLElement>()
const visible = useElementVisibility(element)
const visibility = useDocumentVisibility()
const motion = usePreferredReducedMotion()
const active = ref(true)
const paused = ref(false)
const selectedId = ref('')
const lastTemplateKey = 'aigcnews:ui-showcase:last'
const failedClips = ref<string[]>([])
const failedPosters = ref<string[]>([])
const slides = computed(() => selectUiShowcase(props.items).filter(slide => !failedPosters.value.includes(slide.id)))
const index = computed(() => Math.max(0, slides.value.findIndex(slide => slide.id === selectedId.value)))
const current = computed(() => slides.value[index.value])
const language = computed(() => locale.value.startsWith('zh') ? 'zh' : 'en')
const name = computed(() => current.value?.name[language.value] ?? t('dashboard.editorial.explore'))
const text = computed(() => language.value === 'zh'
  ? { featured: '精选动效', previous: '上一个模板', next: '下一个模板', pause: '暂停动效', play: '播放动效', open: '查看模板', carousel: '精选 UI 模板' }
  : { featured: 'IN THE SPOTLIGHT', previous: 'Previous template', next: 'Next template', pause: 'Pause animation', play: 'Play animation', open: 'Explore template', carousel: 'Featured UI templates' })
const playing = computed(() => active.value && visible.value && visibility.value === 'visible' && motion.value !== 'reduce' && !paused.value)

function select(id: string) {
  selectedId.value = id
  try { localStorage.setItem(lastTemplateKey, id) } catch { /* Storage is optional. */ }
}
function randomize() {
  if (!slides.value.length) return
  let previous = selectedId.value
  try { previous ||= localStorage.getItem(lastTemplateKey) ?? '' } catch { /* Storage is optional. */ }
  const alternatives = slides.value.filter(slide => slide.id !== previous)
  const candidates = alternatives.length ? alternatives : slides.value
  select(candidates[Math.floor(Math.random() * candidates.length)]!.id)
}
function step(direction: number) {
  const length = slides.value.length
  if (length) select(slides.value[(index.value + direction + length) % length]!.id)
}
function mediaError(event: Event) {
  const media = event.currentTarget as HTMLVideoElement | HTMLImageElement
  if (!media.dataset.id) return
  const failed = media.tagName === 'VIDEO' ? failedClips : failedPosters
  failed.value = [...failed.value, media.dataset.id]
}
// Choose once after the catalog arrives; background updates keep a valid selection.
watch(slides, value => {
  if (active.value && !value.some(slide => slide.id === selectedId.value)) randomize()
}, { immediate: true })
onActivated(() => {
  if (active.value) return // KeepAlive also activates on the initial mount.
  active.value = true
  randomize()
})
onDeactivated(() => { active.value = false })
</script>

<template>
  <section ref="element" class="ui-inspiration" :aria-label="text.carousel" aria-roledescription="carousel">
    <RouterLink :to="current ? { name: 'ui-library', params: { id: current.id } } : { name: 'ui-library' }"
      class="ui-inspiration__art" :aria-label="`${text.open} · ${name}`">
      <Transition name="ui-showcase">
        <div v-if="current" :key="current.id" class="ui-inspiration__preview" :style="{ '--preview-scale': current.scale }">
          <video v-if="playing && !failedClips.includes(current.id)" :data-id="current.id" :src="current.item.clip_url"
            :poster="current.item.poster_url" :aria-label="name" autoplay muted loop playsinline preload="metadata" @error="mediaError" />
          <img v-else :data-id="current.id" :src="current.item.poster_url" :alt="name" loading="lazy" @error="mediaError" />
        </div>
        <span v-else class="ui-inspiration__fallback"><Sparkles :size="40" aria-hidden="true" /><span>UI / {{ t('dashboard.editorial.explore') }}</span></span>
      </Transition>
      <span class="ui-inspiration__shade" aria-hidden="true" />
      <div class="ui-inspiration__caption"><span>{{ text.featured }}</span><strong>{{ name }}</strong></div>
    </RouterLink>
    <RouterLink :to="{ name: 'ui-library' }" class="ui-inspiration__heading">
      <span>{{ t('dashboard.editorial.inspiration') }}</span><ArrowUpRight :size="17" aria-hidden="true" />
    </RouterLink>
    <div v-if="current" class="ui-inspiration__footer">
      <span class="ui-inspiration__position"><b>{{ String(index + 1).padStart(2, '0') }}</b><span>/ {{ String(slides.length).padStart(2, '0') }}</span></span>
      <div v-if="slides.length > 1" class="ui-inspiration__controls">
        <button type="button" :aria-label="text.previous" @click="step(-1)"><ChevronLeft :size="16" aria-hidden="true" /></button>
        <button v-if="motion !== 'reduce'" type="button" :aria-label="paused ? text.play : text.pause" @click="paused = !paused"><Play v-if="paused" :size="13" aria-hidden="true" /><Pause v-else :size="13" aria-hidden="true" /></button>
        <button type="button" :aria-label="text.next" @click="step(1)"><ChevronRight :size="16" aria-hidden="true" /></button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ui-inspiration { position:relative;isolation:isolate;container:ui-showcase / size;min-height:var(--ui-showcase-min-height,180px);overflow:hidden;border:1.5px solid var(--rule-strong);border-radius:7px;background:#10141b;color:#fff; }
.ui-inspiration__art,.ui-inspiration__preview,.ui-inspiration__shade,.ui-inspiration__fallback { position:absolute;inset:0; }
.ui-inspiration__art { color:inherit; }
.ui-inspiration__preview { overflow:hidden; }
.ui-inspiration__preview video,.ui-inspiration__preview img { width:100%;height:100%;object-fit:cover;transform:scale(var(--preview-scale,1)); }
.ui-inspiration__shade { background:linear-gradient(180deg,#050810a6,transparent 35%,#05081038 50%,#050810ed 100%);pointer-events:none; }
.ui-inspiration__heading { min-height:24px;position:absolute;top:10px;left:12px;right:12px;display:flex;align-items:center;justify-content:space-between;gap:8px;color:#fff;font-size:14px;font-weight:850;text-shadow:0 1px 6px #000; }
.ui-inspiration__heading svg { flex-shrink:0; }
.ui-inspiration__caption { position:absolute;left:13px;right:13px;bottom:51px;display:flex;flex-direction:column;gap:3px;text-shadow:0 2px 12px #000; }
.ui-inspiration__caption > span { color:#d4f98b;font-size:9px;font-weight:750;letter-spacing:.15em; }
.ui-inspiration__caption strong { overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:20px;line-height:1.3;font-weight:850; }
.ui-inspiration__footer { position:absolute;bottom:8px;left:13px;right:10px;display:flex;align-items:center;justify-content:space-between;gap:8px;pointer-events:none; }
.ui-inspiration__position { display:flex;align-items:baseline;gap:6px;font-variant-numeric:tabular-nums; }
.ui-inspiration__position b { font-size:16px; }
.ui-inspiration__position > span { color:#d1d5dc;font-size:10px; }
.ui-inspiration__controls { display:flex;gap:4px;pointer-events:auto; }
.ui-inspiration__controls button { display:grid;place-items:center;width:32px;height:32px;border:1px solid #ffffff40;border-radius:50%;background:#0a0f1a88;color:#fff;cursor:pointer;transition:background .18s; }
.ui-inspiration__controls button:hover { background:#ffffff30; }
.ui-inspiration__controls button:focus-visible,.ui-inspiration a:focus-visible { outline:2px solid #d4f98b;outline-offset:-3px; }
.ui-inspiration__fallback { display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding-bottom:45px;background:radial-gradient(ellipse at 80% 15%,#32696080,transparent 65%),radial-gradient(ellipse at 10% 100%,#394c7780,transparent 70%),#10141b;color:#d4f98b;font-size:11px; }
.ui-showcase-enter-active,.ui-showcase-leave-active { transition:opacity .55s ease; }
.ui-showcase-enter-from,.ui-showcase-leave-to { opacity:0; }
@container ui-showcase (max-height:150px) {
  .ui-inspiration__caption { bottom:13px;right:122px; }
  .ui-inspiration__caption strong { font-size:16px; }
  .ui-inspiration__caption > span,.ui-inspiration__position { display:none; }
  .ui-inspiration__footer { justify-content:flex-end; }
}
@media (max-width:1023px) {
  .ui-inspiration { min-height:230px; }
  .ui-inspiration__controls button { width:44px;height:44px; }
  .ui-inspiration__caption { bottom:65px; }
  .ui-inspiration__heading { min-height:44px;top:0; }
}
@media (prefers-reduced-motion:reduce) { .ui-showcase-enter-active,.ui-showcase-leave-active { transition:none; } }
</style>
