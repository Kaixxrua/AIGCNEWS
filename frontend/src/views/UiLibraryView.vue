<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDocumentVisibility, useMediaQuery, useNow } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, Grid3x3, Pause, Play, Search, SlidersHorizontal, X } from 'lucide-vue-next'
import UiTemplateDialog from '@/features/ui-library/UiTemplateDialog.vue'
import UiTemplateCard from '@/features/ui-library/UiTemplateCard.vue'
import UiIconCard from '@/features/ui-library/UiIconCard.vue'
import UiIconDialog from '@/features/ui-library/UiIconDialog.vue'
import UiMcpRecommendation from '@/features/ui-library/UiMcpRecommendation.vue'
import { useLibraryDensity } from '@/features/ui-library/useLibraryDensity'
import { loadCatalogWithMeta, loadIconSets, recentlyAdded, searchIcons, searchTemplates, type UiIcon, type UiIconSet, type UiLanguage, type UiTemplate } from '@/features/ui-library/catalog'
import { uiLibraryMessages } from '@/features/ui-library/messages'
import '@/features/ui-library/library.css'
import { provideUiLibraryAccount, type Ranking } from '@/features/ui-library/useUiLibraryAccount'
import { libraryKinds, styleTags, browseMaterials, resolveLibraryKind, type LibraryKind } from '@/features/ui-library/taxonomy'

import { categoryGroups } from '@/features/ui-library/taxonomyData'
import { vIndicator } from '@/motion/indicator'
import { vSwap } from '@/motion/swap'
import { usePageHead } from '@/seo/pageHead'

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
const iconMode = computed(() => kind.value === 'icon')
const iconCount = ref(0)
const iconSets = ref<UiIconSet[]>([])
const iconsLoading = ref(false)
const iconsFailed = ref(false)
const iconProvider = computed(() => readQuery('set'))
const iconTotal = computed(() => iconSets.value.reduce((total, set) => total + set.icons.length, 0) || iconCount.value)
const setsByProvider = computed(() => new Map(iconSets.value.map(set => [set.provider_id, set])))
const filteredIcons = computed(() => iconMode.value ? searchIcons(iconSets.value, query.value, iconProvider.value, style.value) : [])
const iconSetRows = computed(() => iconSets.value.map(set => ({ key: set.provider_id, label: set.provider, count: set.icons.length })))
const availableIconStyles = computed(() => {
  const counts = new Map<string, number>()
  for (const set of iconSets.value) {
    if (iconProvider.value && set.provider_id !== iconProvider.value) continue
    for (const icon of set.icons) counts.set(icon.style, (counts.get(icon.style) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([key, count]) => ({ key, count }))
})
const selectedIcon = ref<UiIcon | null>(null)
const kindCount = (key: string) => key === 'icon' ? iconTotal.value : browseMaterials(items.value, key as LibraryKind).length
function iconSetOf(icon: UiIcon): UiIconSet {
  const set = setsByProvider.value.get(icon.id.slice(0, icon.id.indexOf(':')))
  if (!set) throw new Error('Icon without a set: ' + icon.id)
  return set
}
const availableCategoryGroups = computed(() => categoryGroups
  .filter(group => kind.value === 'all' || kind.value === group.kind || (kind.value === 'block' && group.kind === 'component'))
  .map(group => ({ ...group, label: lang.value === 'zh' ? group.zh : group.en,
    entries: group.rows.map(([key, zh, en]) => ({ key, label: lang.value === 'zh' ? zh : en, english: en, count: browseMaterials(kindItems.value, group.kind, key).length })).filter(row => row.count),
  })).filter(group => group.entries.length))
const availableStyles = computed(() => styleTags.map(([key, zh, en]) => ({ key, label: lang.value === 'zh' ? zh : en, count: browseMaterials(kindItems.value, 'all', '', key).length })).filter(row => row.count))
const now = useNow({ interval: 60_000 })
const ranking = computed<Ranking>(() => ['new', 'daily', 'weekly', 'monthly', 'liked'].includes(readQuery('rank')) ? readQuery('rank') as Ranking : 'all')
// 联系表只在桌面生效：一排更多、只看静态缩略图（几十个预览不同时解码，点开详情再播放）。
const desktop = useMediaQuery('(min-width: 1024px)')
const { density, contactSheet, toggle: toggleDensity } = useLibraryDensity(desktop)
// 换了素材类型、用途、风格、榜单、图标集或切换联系表时，结果网格整批依次浮现；搜索框逐字输入不重播。
const gridKey = computed(() => [kind.value, category.value, style.value, ranking.value, framework.value, iconProvider.value, density.value].join('|'))
const account = provideUiLibraryAccount(lang, ranking, async () => { if (selected.value) await close(); selectedIcon.value = null })
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
// 地址里的素材 id 不在目录里（目录已加载成功）。
const missingItem = computed(() => Boolean(route.params.id) && !selected.value && !loading.value && !failed.value)
// 打开的素材用它的名称和简介做标题与描述；素材不存在时这个地址不让搜索引擎收录。
usePageHead(() => {
  if (selected.value) return { title: selected.value.name[lang.value], description: selected.value.description[lang.value] }
  return missingItem.value ? { noindex: true } : null
})
const visibleLimit = ref(96)
const visibleItems = computed(() => filtered.value.slice(0, visibleLimit.value))
const resultCount = computed(() => iconMode.value ? filteredIcons.value.length : filtered.value.length)
watch([query, category, framework, ranking, kind, style, iconProvider], () => { visibleLimit.value = 96 })
const sourceCount = computed(() => new Set(items.value.map(item => item.provider)).size)
const hasFilters = computed(() => Boolean(query.value || category.value || framework.value || style.value || iconProvider.value))
const visibility = useDocumentVisibility()
const autoplay = ref(true)
const previewsEnabled = computed(() => autoplay.value && !contactSheet.value && visibility.value === 'visible' && !selected.value)
let trigger: HTMLElement | null = null
let catalogGeneration = 0
let iconGeneration = 0
async function refresh() {
  const generation = ++catalogGeneration
  loading.value = true
  failed.value = false
  try {
    const bundle = await loadCatalogWithMeta(controller.signal, account.isAdmin.value)
    if (generation !== catalogGeneration || controller.signal.aborted) return
    items.value = bundle.items
    iconCount.value = bundle.iconCount
  }
  catch { if (generation === catalogGeneration && !controller.signal.aborted) { failed.value = true; items.value = [] } }
  finally { if (generation === catalogGeneration) loading.value = false }
}
async function loadIcons() {
  const generation = ++iconGeneration
  iconsLoading.value = true
  iconsFailed.value = false
  try {
    const sets = await loadIconSets(controller.signal, account.isAdmin.value)
    if (generation === iconGeneration && !controller.signal.aborted) iconSets.value = sets
  }
  catch { if (generation === iconGeneration && !controller.signal.aborted) { iconsFailed.value = true; iconSets.value = [] } }
  finally { if (generation === iconGeneration) iconsLoading.value = false }
}
watch(iconMode, active => { if (active && !iconSets.value.length && !iconsLoading.value) void loadIcons() }, { immediate: true })
// 登录身份改变时立即清掉管理员目录；迟到的旧请求不能把废弃素材带回普通用户界面。
watch(account.isAdmin, () => {
  catalogGeneration++
  iconGeneration++
  items.value = []
  iconSets.value = []
  iconCount.value = 0
  iconsLoading.value = false
  iconsFailed.value = false
  selectedIcon.value = null
  void refresh()
  if (iconMode.value) void loadIcons()
})
function setFilter(key: string, value: string) {
  void router.replace({ query: { ...route.query, ...(['category', 'style', 'framework', 'set'].includes(key) ? { kind: kind.value } : {}), [key]: value || undefined } })
}
function setKind(value: LibraryKind) {
  void router.replace({ query: { ...route.query, kind: value, category: undefined, style: undefined, rank: undefined, set: undefined } })
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
function openIcon(icon: UiIcon, event: Event) {
  trigger = event.currentTarget as HTMLElement
  selectedIcon.value = icon
}
async function closeIcon() {
  selectedIcon.value = null
  await nextTick()
  trigger?.focus()
}
onMounted(refresh)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <section class="view-container ui-library">
    <header class="ui-library__header">
      <div><p class="ui-library__eyebrow">AIGC RADAR / UI</p><h1 class="comic-title">{{ text.title }}</h1><p>{{ text.subtitle }}</p></div>
      <RouterLink to="/mcp" class="ui-library__mcp">{{ text.mcp }}<ArrowUpRight :size="16" aria-hidden="true" /></RouterLink>
    </header>
    <!-- 指挥栏：桌面上搜索、框架与素材类型并成一行，放不下时类型折到下一行；手机与平板上这一层不存在（display: contents） -->
    <div class="ui-library__command">
      <div class="ui-library__toolbar">
        <label class="ui-library__search"><Search :size="19" aria-hidden="true" /><input type="search" :value="query" :placeholder="text.search" :aria-label="text.search" @input="setFilter('q', ($event.target as HTMLInputElement).value)" /><span class="ui-library__search-count" aria-live="polite">{{ resultCount }} {{ text.result }}</span></label>
        <label v-if="!iconMode" class="ui-library__framework"><SlidersHorizontal :size="16" aria-hidden="true" /><select :value="framework" :aria-label="text.frameworks" @change="setFilter('framework', ($event.target as HTMLSelectElement).value)"><option value="">{{ text.frameworks }}</option><option value="html">HTML / Tailwind</option><option value="react">React</option><option value="vue">Vue / Nuxt</option><option value="css">CSS / Themes</option></select></label>
      </div>
      <nav v-indicator="{ active: '[aria-pressed=true]', flip: true }" class="ui-library__kinds" :aria-label="lang === 'zh' ? '素材类型' : 'Material types'"><button v-for="[key, zh, en] in libraryKinds" :key="key" type="button" :aria-pressed="kind === key" @click="setKind(key)">{{ lang === 'zh' ? zh : en }}<span>{{ kindCount(key) }}</span></button><button type="button" class="ui-library__all-kinds" :aria-pressed="kind === 'all'" @click="setKind('all')">{{ lang === 'zh' ? '全部素材' : 'All materials' }}<span>{{ items.length }}</span></button></nav>
    </div>
    <div class="ui-library__body">
      <aside class="ui-library__sidebar">
        <nav v-if="iconMode" v-indicator="'.active'" :aria-label="text.iconSets">
          <p class="ui-library__group-title">{{ text.iconSets }}</p>
          <button type="button" :class="{ active: !iconProvider }" :aria-pressed="!iconProvider" @click="setFilter('set', '')">{{ text.all }}<span>{{ iconTotal }}</span></button>
          <button v-for="row in iconSetRows" :key="row.key" type="button" :class="{ active: iconProvider === row.key }" :aria-pressed="iconProvider === row.key" @click="setFilter('set', row.key)">{{ row.label }}<span>{{ row.count }}</span></button>
        </nav>
        <nav v-else-if="kind !== 'theme'" v-indicator="'.active'" :aria-label="text.categories">
          <p class="ui-library__group-title">{{ lang === 'zh' ? '按用途浏览' : 'Browse by purpose' }}</p>
          <button type="button" :class="{ active: !category }" :aria-pressed="!category" @click="setFilter('category', '')">{{ text.all }}<span>{{ kindItems.length }}</span></button>
          <template v-for="group in availableCategoryGroups" :key="group.key">
            <p class="ui-library__group-title">{{ group.label }}</p>
            <button v-for="row in group.entries" :key="row.key" type="button" :title="row.english" :class="{ active: category === row.key }" :aria-pressed="category === row.key" @click="setFilter('category', row.key)">{{ row.label }}<span>{{ row.count }}</span></button>
          </template>
        </nav>
        <nav v-if="iconMode && availableIconStyles.length" v-indicator="'.active'" :aria-label="text.iconStyles"><p class="ui-library__group-title">{{ text.iconStyles }}</p><button v-for="row in availableIconStyles" :key="row.key" type="button" :class="{ active: style === row.key }" :aria-pressed="style === row.key" @click="setFilter('style', style === row.key ? '' : row.key)">{{ row.key }}<span>{{ row.count }}</span></button></nav>
        <nav v-else-if="!iconMode && availableStyles.length" v-indicator="'.active'" :aria-label="lang === 'zh' ? '设计风格' : 'Design styles'"><p class="ui-library__group-title">{{ lang === 'zh' ? '设计风格' : 'Design styles' }}</p><button v-for="row in availableStyles" :key="row.key" type="button" :class="{ active: style === row.key }" :aria-pressed="style === row.key" @click="setFilter('style', style === row.key ? '' : row.key)">{{ row.label }}<span>{{ row.count }}</span></button></nav>
        <div class="ui-library__aside-note"><p>{{ iconMode ? iconSets.length : sourceCount }} {{ iconMode ? text.iconSets : text.sources }} · {{ iconMode ? iconTotal : items.length }} {{ iconMode ? text.icons : text.works }}</p><p>{{ text.provenance }}</p></div>
        <UiMcpRecommendation :lang="lang" />
      </aside>
      <div class="ui-library__main">
        <div v-if="!iconMode" class="ui-library__rankbar"><nav v-indicator="{ active: '[aria-pressed=true]', flip: true, pop: true }" :aria-label="lang === 'zh' ? '素材排行榜' : 'Library rankings'"><button v-for="[key, label] in rankOptions" :key="key" type="button" :aria-pressed="ranking === key" @click="setFilter('rank', key === 'all' ? '' : key)">{{ label }}</button></nav><span>{{ ranking === 'new' ? (lang === 'zh' ? '最近 24 小时首次入库 · 按入库时间' : 'First added in the last 24h · Newest first') : (lang === 'zh' ? '滚动 24 小时 / 7 天 / 30 天 · 按爱心' : 'Rolling 24h / 7d / 30d · By likes') }}</span></div>
        <div class="ui-library__quota"><span>{{ account.quotaText.value }}</span><RouterLink to="/membership">{{ lang === 'zh' ? '了解 VIP' : 'Explore VIP' }}</RouterLink></div>
        <p v-if="account.loadError.value" class="ui-library__account-error" role="status">{{ lang === 'zh' ? '热度暂时无法加载' : 'Popularity is temporarily unavailable' }} <button @click="account.refresh">{{ text.retry }}</button></p>
        <div class="ui-library__results"><span aria-live="polite">{{ resultCount }} {{ text.result }}</span><span v-if="!iconMode" class="ui-library__autoplay-hint">{{ text.autoplayHint }}</span><button v-if="!iconMode && !contactSheet" type="button" class="ui-library__playback" :aria-pressed="autoplay" :title="`${autoplay ? text.pauseAll : text.playAll} · ${text.autoplayHint}`" @click="autoplay = !autoplay"><Pause v-if="autoplay" :size="14" aria-hidden="true" /><Play v-else :size="14" aria-hidden="true" /><span class="ui-library__tool-label">{{ autoplay ? text.pauseAll : text.playAll }}</span></button><button v-if="!iconMode" type="button" class="ui-library__density" :aria-pressed="density === 'sheet'" :title="text.contactSheetHint" @click="toggleDensity"><Grid3x3 :size="15" aria-hidden="true" /><span class="ui-library__tool-label">{{ text.contactSheet }}</span></button><button v-if="hasFilters" type="button" class="ui-library__clear" @click="router.replace({ query: {} })"><X :size="14" aria-hidden="true" />{{ text.clear }}</button></div>
        <template v-if="iconMode">
          <div v-if="iconsLoading" class="ui-library__grid" :aria-label="text.loading" aria-busy="true"><div v-for="n in 6" :key="n" class="ui-library__skeleton" /></div>
          <div v-else-if="iconsFailed" class="ui-library__empty" role="alert"><p>{{ text.loadError }}</p><button type="button" @click="loadIcons">{{ text.retry }}</button></div>
          <div v-else-if="!filteredIcons.length" class="ui-library__empty"><Search :size="30" aria-hidden="true" /><h2>{{ text.emptyIcons }}</h2><p>{{ text.emptyIconsHint }}</p><button type="button" @click="router.replace({ query: { kind: 'icon' } })">{{ text.clear }}</button></div>
          <div v-else v-swap="{ key: gridKey, stagger: true }" class="ui-library__icon-grid">
            <UiIconCard v-for="icon in filteredIcons.slice(0, visibleLimit)" :key="icon.id" :icon="icon" :set="iconSetOf(icon)" :lang="lang" @open="openIcon(icon, $event)" @visibility="icon.deprecated = $event" />
          </div>
          <div v-if="filteredIcons.length > visibleLimit" class="ui-library__load-more"><button type="button" @click="visibleLimit += 96">{{ lang === 'zh' ? '加载更多' : 'Load more' }} · {{ Math.min(visibleLimit, filteredIcons.length) }} / {{ filteredIcons.length }}</button></div>
        </template>
        <template v-else>
          <div v-if="loading" class="ui-library__grid" :aria-label="text.loading" aria-busy="true"><div v-for="n in 6" :key="n" class="ui-library__skeleton" /></div>
          <div v-else-if="failed" class="ui-library__empty" role="alert"><p>{{ text.loadError }}</p><button type="button" @click="refresh">{{ text.retry }}</button></div>
          <div v-else-if="!filtered.length" class="ui-library__empty"><Search :size="30" aria-hidden="true" /><h2>{{ ranking === 'new' ? text.emptyNew : text.empty }}</h2><p>{{ ranking === 'new' ? text.emptyNewHint : text.emptyHint }}</p><button type="button" @click="router.replace({ query: {} })">{{ text.clear }}</button></div>
          <div v-else v-swap="{ key: gridKey, stagger: true }" class="ui-library__grid" :data-density="density">
            <UiTemplateCard v-for="item in visibleItems" :key="item.id" :item="item" :lang="lang" :preview-enabled="previewsEnabled" @open="open(item, $event)" @visibility="item.deprecated = $event" />
          </div>
          <div v-if="filtered.length > visibleLimit" class="ui-library__load-more"><button type="button" @click="visibleLimit += 96">{{ lang === 'zh' ? '加载更多' : 'Load more' }} · {{ visibleItems.length }} / {{ filtered.length }}</button></div>
        </template>
      </div>
    </div>
    <UiTemplateDialog v-if="selected" :key="selected.id" :item="selected" :lang="lang" @close="close" />
    <UiIconDialog v-if="selectedIcon" :key="selectedIcon.id" :icon="selectedIcon" :set="iconSetOf(selectedIcon)" :lang="lang" @close="closeIcon" />
    <div v-if="missingItem" class="ui-library__not-found" role="alert">{{ text.notFound }} <button type="button" @click="close">{{ text.back }}</button></div>
  </section>
</template>
