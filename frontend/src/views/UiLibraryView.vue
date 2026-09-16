<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDocumentVisibility, useNow } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, Pause, Play, Search, SlidersHorizontal, X } from 'lucide-vue-next'
import UiTemplateDialog from '@/features/ui-library/UiTemplateDialog.vue'
import UiTemplateCard from '@/features/ui-library/UiTemplateCard.vue'
import UiMcpRecommendation from '@/features/ui-library/UiMcpRecommendation.vue'
import { loadCatalog, recentlyAdded, searchTemplates, type UiLanguage, type UiTemplate } from '@/features/ui-library/catalog'
import { uiLibraryMessages } from '@/features/ui-library/messages'
import '@/features/ui-library/library.css'
import { provideUiLibraryAccount, type Ranking } from '@/features/ui-library/useUiLibraryAccount'
import { libraryKinds, styleTags, browseMaterials, resolveLibraryKind, type LibraryKind } from '@/features/ui-library/taxonomy'

import { categoryGroups } from '@/features/ui-library/taxonomyData'

defineOptions({ name: 'UiLibraryView' })
const route = useRoute()
const router = useRouter()
const { locale } = useI18n()
const lang = computed<UiLanguage>(() => locale.value.startsWith('en') ? 'en' : 'zh')
const text = computed(() => uiLibraryMessages[lang.value])
const items = ref<UiTemplate[]>([])
const loading = ref(true)
const failed = ref(false)
const controller = new AbortController()
const readQuery = (key: string) => typeof route.query[key] === 'string' ? route.query[key] as string : ''
const query = computed(() => readQuery('q'))
const category = computed(() => readQuery('category'))
const framework = computed(() => readQuery('framework'))
const style = computed(() => readQuery('style'))
const kind = computed(() => resolveLibraryKind(readQuery('kind')))
const kindItems = computed(() => browseMaterials(items.value, kind.value))
const availableCategoryGroups = computed(() => categoryGroups
  .filter(group => kind.value === 'all' || kind.value === group.kind || (kind.value === 'block' && group.kind === 'component'))
  .map(group => ({ ...group, label: lang.value === 'zh' ? group.zh : group.en,
    entries: group.rows.map(([key, zh, en]) => ({ key, label: lang.value === 'zh' ? zh : en, english: en, count: browseMaterials(kindItems.value, group.kind, key).length })).filter(row => row.count),
  })).filter(group => group.entries.length))
const availableStyles = computed(() => styleTags.map(([key, zh, en]) => ({ key, label: lang.value === 'zh' ? zh : en, count: browseMaterials(kindItems.value, 'all', '', key).length })).filter(row => row.count))
const now = useNow({ interval: 60_000 })
const ranking = computed<Ranking>(() => ['new', 'daily', 'weekly', 'monthly', 'liked'].includes(readQuery('rank')) ? readQuery('rank') as Ranking : 'all')
const account = provideUiLibraryAccount(lang, ranking, async () => { if (selected.value) await close() })
const rankOptions = computed<[Ranking, string][]>(() => lang.value === 'zh' ? [['all', '全部'], ['new', '今日新增'], ['daily', '今日热榜'], ['weekly', '周榜'], ['monthly', '月榜'], ['liked', '我的喜欢']] : [['all', 'All'], ['new', 'New today'], ['daily', 'Today'], ['weekly', 'Week'], ['monthly', 'Month'], ['liked', 'Liked']])
const filtered = computed(() => {
  const matches = browseMaterials(searchTemplates(items.value, query.value, '', framework.value), kind.value, category.value, style.value)
  if (ranking.value === 'new') return recentlyAdded(matches, now.value.getTime())
  if (ranking.value === 'liked') return matches.filter(item => account.stats.value[item.id]?.liked)
  if (ranking.value !== 'all') return matches.sort((a, b) => (account.stats.value[b.id]?.score ?? 0) - (account.stats.value[a.id]?.score ?? 0))
  if (!query.value) return matches.sort((a, b) => (a.editorial?.position ?? 999) - (b.editorial?.position ?? 999))
  return matches
})
const selected = computed(() => items.value.find(item => item.id === route.params.id))
const visibleLimit = ref(96)
const visibleItems = computed(() => filtered.value.slice(0, visibleLimit.value))
watch([query, category, framework, ranking, kind, style], () => { visibleLimit.value = 96 })
const sourceCount = computed(() => new Set(items.value.map(item => item.provider)).size)
const hasFilters = computed(() => Boolean(query.value || category.value || framework.value || style.value))
const visibility = useDocumentVisibility()
const autoplay = ref(true)
const previewsEnabled = computed(() => autoplay.value && visibility.value === 'visible' && !selected.value)
let trigger: HTMLElement | null = null
async function refresh() {
  loading.value = true
  failed.value = false
  try { items.value = await loadCatalog(controller.signal) }
  catch { if (!controller.signal.aborted) failed.value = true }
  finally { loading.value = false }
}
function setFilter(key: string, value: string) {
  void router.replace({ query: { ...route.query, ...(['category', 'style', 'framework'].includes(key) ? { kind: kind.value } : {}), [key]: value || undefined } })
}
function setKind(value: LibraryKind) {
  void router.replace({ query: { ...route.query, kind: value, category: undefined, style: undefined, rank: undefined } })
}
function open(item: UiTemplate, event: Event) {
  trigger = event.currentTarget as HTMLElement
  void router.push({ name: 'ui-library', params: { id: item.id }, query: route.query })
}
async function close() {
  await router.replace({ name: 'ui-library', params: { id: '' }, query: route.query })
  await nextTick()
  trigger?.focus()
}
onMounted(refresh)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <section class="view-container ui-library">
    <header class="ui-library__header">
      <div><p class="ui-library__eyebrow">AIGC RADAR / UI</p><h1>{{ text.title }}</h1><p>{{ text.subtitle }}</p></div>
      <RouterLink to="/mcp" class="ui-library__mcp">{{ text.mcp }}<ArrowUpRight :size="16" aria-hidden="true" /></RouterLink>
    </header>
    <div class="ui-library__toolbar">
      <label class="ui-library__search"><Search :size="19" aria-hidden="true" /><input type="search" :value="query" :placeholder="text.search" :aria-label="text.search" @input="setFilter('q', ($event.target as HTMLInputElement).value)" /></label>
      <label class="ui-library__framework"><SlidersHorizontal :size="16" aria-hidden="true" /><select :value="framework" :aria-label="text.frameworks" @change="setFilter('framework', ($event.target as HTMLSelectElement).value)"><option value="">{{ text.frameworks }}</option><option value="html">HTML / Tailwind</option><option value="react">React</option><option value="vue">Vue / Nuxt</option><option value="css">CSS / Themes</option></select></label>
    </div>
    <nav class="ui-library__kinds" :aria-label="lang === 'zh' ? '素材类型' : 'Material types'"><button v-for="[key, zh, en] in libraryKinds" :key="key" type="button" :aria-pressed="kind === key" @click="setKind(key)">{{ lang === 'zh' ? zh : en }}<span>{{ browseMaterials(items, key).length }}</span></button><button type="button" class="ui-library__all-kinds" :aria-pressed="kind === 'all'" @click="setKind('all')">{{ lang === 'zh' ? '全部素材' : 'All materials' }}<span>{{ items.length }}</span></button></nav>
    <div class="ui-library__body">
      <aside class="ui-library__sidebar">
        <nav v-if="kind !== 'theme'" :aria-label="text.categories">
          <p class="ui-library__group-title">{{ lang === 'zh' ? '按用途浏览' : 'Browse by purpose' }}</p>
          <button type="button" :class="{ active: !category }" :aria-pressed="!category" @click="setFilter('category', '')">{{ text.all }}<span>{{ kindItems.length }}</span></button>
          <template v-for="group in availableCategoryGroups" :key="group.key">
            <p class="ui-library__group-title">{{ group.label }}</p>
            <button v-for="row in group.entries" :key="row.key" type="button" :title="row.english" :class="{ active: category === row.key }" :aria-pressed="category === row.key" @click="setFilter('category', row.key)">{{ row.label }}<span>{{ row.count }}</span></button>
          </template>
        </nav>
        <nav v-if="availableStyles.length" :aria-label="lang === 'zh' ? '设计风格' : 'Design styles'"><p class="ui-library__group-title">{{ lang === 'zh' ? '设计风格' : 'Design styles' }}</p><button v-for="row in availableStyles" :key="row.key" type="button" :class="{ active: style === row.key }" :aria-pressed="style === row.key" @click="setFilter('style', style === row.key ? '' : row.key)">{{ row.label }}<span>{{ row.count }}</span></button></nav>
        <div class="ui-library__aside-note"><p>{{ sourceCount }} {{ text.sources }} · {{ items.length }} {{ text.works }}</p><p>{{ text.provenance }}</p></div>
        <UiMcpRecommendation :lang="lang" />
      </aside>
      <div class="ui-library__main">
        <div class="ui-library__rankbar"><nav :aria-label="lang === 'zh' ? '素材排行榜' : 'Library rankings'"><button v-for="[key, label] in rankOptions" :key="key" type="button" :aria-pressed="ranking === key" @click="setFilter('rank', key === 'all' ? '' : key)">{{ label }}</button></nav><span>{{ ranking === 'new' ? (lang === 'zh' ? '最近 24 小时首次入库 · 按入库时间' : 'First added in the last 24h · Newest first') : (lang === 'zh' ? '滚动 24 小时 / 7 天 / 30 天 · 按爱心' : 'Rolling 24h / 7d / 30d · By likes') }}</span></div>
        <div class="ui-library__quota"><span>{{ account.quotaText.value }}</span><RouterLink to="/membership">{{ lang === 'zh' ? '了解 VIP' : 'Explore VIP' }}</RouterLink></div>
        <p v-if="account.loadError.value" class="ui-library__account-error" role="status">{{ lang === 'zh' ? '热度暂时无法加载' : 'Popularity is temporarily unavailable' }} <button @click="account.refresh">{{ text.retry }}</button></p>
        <div class="ui-library__results"><span aria-live="polite">{{ filtered.length }} {{ text.result }}</span><span class="ui-library__autoplay-hint">{{ text.autoplayHint }}</span><button type="button" class="ui-library__playback" :aria-pressed="autoplay" @click="autoplay = !autoplay"><Pause v-if="autoplay" :size="14" /><Play v-else :size="14" />{{ autoplay ? text.pauseAll : text.playAll }}</button><button v-if="hasFilters" type="button" @click="router.replace({ query: {} })"><X :size="14" aria-hidden="true" />{{ text.clear }}</button></div>
        <div v-if="loading" class="ui-library__grid" :aria-label="text.loading" aria-busy="true"><div v-for="n in 6" :key="n" class="ui-library__skeleton" /></div>
        <div v-else-if="failed" class="ui-library__empty" role="alert"><p>{{ text.loadError }}</p><button type="button" @click="refresh">{{ text.retry }}</button></div>
        <div v-else-if="!filtered.length" class="ui-library__empty"><Search :size="30" aria-hidden="true" /><h2>{{ ranking === 'new' ? text.emptyNew : text.empty }}</h2><p>{{ ranking === 'new' ? text.emptyNewHint : text.emptyHint }}</p><button type="button" @click="router.replace({ query: {} })">{{ text.clear }}</button></div>
        <div v-else class="ui-library__grid">
          <UiTemplateCard v-for="item in visibleItems" :key="item.id" :item="item" :lang="lang" :enabled="previewsEnabled" @open="open(item, $event)" />
        </div>
        <div v-if="filtered.length > visibleLimit" class="ui-library__load-more"><button type="button" @click="visibleLimit += 96">{{ lang === 'zh' ? '加载更多' : 'Load more' }} · {{ visibleItems.length }} / {{ filtered.length }}</button></div>
      </div>
    </div>
    <UiTemplateDialog v-if="selected" :key="selected.id" :item="selected" :lang="lang" @close="close" />
    <div v-else-if="route.params.id && !loading && !failed" class="ui-library__not-found" role="alert">{{ text.notFound }} <button type="button" @click="close">{{ text.back }}</button></div>
  </section>
</template>
