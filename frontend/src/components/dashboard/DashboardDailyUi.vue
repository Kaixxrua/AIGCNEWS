<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, Sparkles } from 'lucide-vue-next'
import UiCardFrame from '@/features/ui-library/UiCardFrame.vue'
import UiCardVideo from '@/features/ui-library/UiCardVideo.vue'
import { loadCatalog, recentlyAdded, type UiLanguage, type UiTemplate } from '@/features/ui-library/catalog'

const { locale, t } = useI18n()
const lang = computed<UiLanguage>(() => locale.value.startsWith('en') ? 'en' : 'zh')
const items = ref<UiTemplate[]>([])
const loading = ref(true)
const failed = ref(false)
const previewStates = reactive<Record<string, 'loading' | 'ready' | 'error'>>({})
const controller = new AbortController()
const visibleItems = computed(() => recentlyAdded(items.value).slice(0, 4))

function setPreviewState(id: string, state: 'ready' | 'error') {
  previewStates[id] = state
}

onMounted(async () => {
  try {
    items.value = await loadCatalog(controller.signal)
  } catch {
    if (!controller.signal.aborted) failed.value = true
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => controller.abort())
</script>

<template>
  <section class="daily-ui glass-card" aria-labelledby="daily-ui-title">
    <header class="daily-ui__header">
      <span class="daily-ui__title-wrap">
        <span class="daily-ui__icon"><Sparkles :size="15" aria-hidden="true" /></span>
        <span>
          <strong id="daily-ui-title">{{ t('dashboard.dailyUi.title') }}</strong>
          <small>{{ t('dashboard.dailyUi.subtitle') }}</small>
        </span>
      </span>
      <RouterLink :to="{ name: 'ui-library', query: { rank: 'new' } }" class="daily-ui__all">
        {{ t('dashboard.dailyUi.viewAll') }}<ArrowRight :size="14" aria-hidden="true" />
      </RouterLink>
    </header>

    <div v-if="loading" class="daily-ui__grid" :aria-label="t('dashboard.dailyUi.loading')" aria-busy="true">
      <span v-for="n in 4" :key="n" class="daily-ui__skeleton" />
    </div>
    <p v-else-if="failed" class="daily-ui__status" role="status">{{ t('dashboard.dailyUi.loadFailed') }}</p>
    <p v-else-if="!visibleItems.length" class="daily-ui__status">{{ t('dashboard.dailyUi.empty') }}</p>
    <div v-else class="daily-ui__grid">
      <RouterLink
        v-for="item in visibleItems"
        :key="item.id"
        :to="{ name: 'ui-library', params: { id: item.id }, query: { rank: 'new' } }"
        class="daily-ui__item"
        :aria-label="t('dashboard.dailyUi.open', { name: item.name[lang] })"
      >
        <span class="daily-ui__preview">
          <img :src="item.poster_url" alt="" aria-hidden="true" />
          <UiCardFrame
            v-if="item.preview_kind === 'html' && previewStates[item.id] !== 'error'"
            class="daily-ui__media"
            :class="{ 'is-ready': previewStates[item.id] === 'ready' }"
            :src="item.preview_url"
            :id="item.id"
            :width="item.preview_width"
            :title="item.name[lang]"
            @ready="setPreviewState(item.id, 'ready')"
            @error="setPreviewState(item.id, 'error')"
          />
          <UiCardVideo
            v-else-if="previewStates[item.id] !== 'error'"
            class="daily-ui__media"
            :class="{ 'is-ready': previewStates[item.id] === 'ready' }"
            :src="item.clip_url || `/ui-library/clips/${item.id}.webm`"
            :title="item.name[lang]"
            @ready="setPreviewState(item.id, 'ready')"
            @error="setPreviewState(item.id, 'error')"
          />
        </span>
        <span class="daily-ui__meta">
          <strong>{{ item.name[lang] }}</strong>
          <small>{{ item.provider }}</small>
        </span>
      </RouterLink>
    </div>
  </section>
</template>

<style scoped>
.daily-ui { flex-shrink: 0; padding: 10px 12px 12px; }
.daily-ui__header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }
.daily-ui__title-wrap { display:flex; align-items:center; gap:8px; min-width:0; }
.daily-ui__title-wrap > span:last-child { display:flex; align-items:baseline; gap:8px; min-width:0; }
.daily-ui__title-wrap strong { font-size:13px; white-space:nowrap; }
.daily-ui__title-wrap small, .daily-ui__meta small { color:var(--muted); font-size:10px; }
.daily-ui__icon { display:grid; width:25px; height:25px; flex-shrink:0; place-items:center; border:1px solid var(--ink); border-radius:4px; background:var(--acid); }
.daily-ui__all { display:inline-flex; align-items:center; gap:4px; flex-shrink:0; color:var(--ink); font-size:11px; font-weight:700; text-decoration:none; }
.daily-ui__all:hover { text-decoration:underline; text-underline-offset:3px; }
.daily-ui__grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; }
.daily-ui__item { min-width:0; overflow:hidden; border:1px solid var(--ink); border-radius:4px; color:var(--ink); background:var(--paper); text-decoration:none; transition:transform .15s, box-shadow .15s; }
.daily-ui__item:hover { transform:translateY(-2px); box-shadow:2px 2px 0 var(--shadow-hard); }
.daily-ui__item:focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
.daily-ui__preview { display:block; position:relative; overflow:hidden; aspect-ratio:16/7; background:#0b0e13; }
.daily-ui__preview > img, .daily-ui__media { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.daily-ui__media { opacity:0; pointer-events:none; transition:opacity .2s; }
.daily-ui__media.is-ready { opacity:1; }
.daily-ui__meta { display:flex; align-items:center; justify-content:space-between; gap:6px; padding:6px 8px; }
.daily-ui__meta strong { overflow:hidden; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.daily-ui__meta small { overflow:hidden; flex-shrink:1; text-overflow:ellipsis; white-space:nowrap; }
.daily-ui__skeleton { aspect-ratio:16/8.6; border-radius:4px; background:var(--paper-muted,#e7e9e4); animation:daily-ui-pulse 1.4s ease-in-out infinite; }
.daily-ui__status { margin:0; padding:12px 4px 8px; color:var(--muted); font-size:11px; }
@keyframes daily-ui-pulse { 50% { opacity:.55; } }
@media (max-width: 767px) {
  .daily-ui { margin-top:12px; padding:10px; }
  .daily-ui__title-wrap > span:last-child { display:block; }
  .daily-ui__title-wrap small { display:block; margin-top:2px; }
  .daily-ui__grid { display:flex; overflow-x:auto; scroll-snap-type:x mandatory; padding-bottom:3px; }
  .daily-ui__item, .daily-ui__skeleton { width:240px; flex:0 0 240px; scroll-snap-align:start; }
  .daily-ui__preview { aspect-ratio:16/9; }
}
@media (prefers-reduced-motion: reduce) { .daily-ui__item, .daily-ui__media, .daily-ui__skeleton { animation:none; transition:none; } }
</style>
