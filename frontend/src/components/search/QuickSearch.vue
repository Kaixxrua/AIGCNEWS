<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, ref, shallowRef, watch, type Component, type FunctionalComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useEventListener } from '@vueuse/core'
import { ArrowRight, ArrowUpRight, FileText, FolderGit2, History, LayoutTemplate, LoaderCircle, Newspaper, Search } from 'lucide-vue-next'
import { XLogoIcon } from '@/components/icons/XLogoIcon'
import { useQuickSearch } from '@/composables/useQuickSearch'
import { isModalOpen } from '@/features/keyboard/listKeys'
import {
  buildSections,
  highlight,
  highlightTerms,
  isApplePlatform,
  isQuickSearchHotkey,
  matchTemplates,
  parseRecentQueries,
  pushRecentQuery,
  recentSection,
  searchableQuery,
  slimTemplate,
  QUICK_SEARCH_DEBOUNCE_MS,
  QUICK_SEARCH_MAX_CHARS,
  RECENT_QUERIES_KEY,
  type QuickSearchKind,
  type QuickSearchRow,
  type QuickSearchSection,
  type QuickSearchTarget,
  type QuickSearchTemplate,
  type Translate,
} from '@/features/search/quickSearch'
import { loadCatalog } from '@/features/ui-library/catalog'
import type { AppLocale } from '@/i18n'
import { formatLocaleNumber } from '@/i18n/formatters'
import { vIndicator } from '@/motion/indicator'
import { EASE_OUT, canAnimate } from '@/motion/motion'
import { slideIn, slideOut } from '@/motion/presence'
import { fetchQuickSearch, QUICK_SEARCH_LIMIT, type QuickSearchResult } from '@/services/search/searchApi'

/**
 * 站内速查（⌘K）：任何一页按 ⌘K（其余系统 Ctrl+K）或点报眉的放大镜，弹出搜索框，项目、论文、简报、推文、UI 素材一起搜。
 * 结果按类型分组，方向键挑，回车直达，⌘/Ctrl+回车在新标签页打开；推文去 x.com 原帖。
 * 前四组一次请求查齐（/api/search），UI 素材在本地目录里查。打字停一小会儿才发请求，新的一发出旧的即作废，
 * 查过的词记在内存里；新结果到之前先留着上一批。搜索框空着时列出最近搜过的词（存在本机）。
 * 开着时是模态对话框：列表键盘流（j / k 一类）让给它，Tab 不出框，关上后焦点回到打开前的地方。
 */
const props = defineProps<{
  /** 只在桌面宽度（1024px 以上）启用：快捷键不接，按钮也不出。 */
  enabled: boolean
}>()

const { t, locale } = useI18n()
const router = useRouter()
const route = useRoute()
const { open, show, hide } = useQuickSearch()
const apple = isApplePlatform()

const appLocale = computed<AppLocale>(() => (locale.value === 'en-US' ? 'en-US' : 'zh-CN'))
const translate: Translate = (key, named) => (named ? t(key, named) : t(key))

const input = ref<HTMLInputElement | null>(null)
const draft = ref('')
const query = computed(() => searchableQuery(draft.value))

// ── 请求 ───────────────────────────────────────────────────────────────

/** 正显示着的这一批结果是哪个词查出来的；failed 表示整个请求没成。 */
interface Shown { q: string; result: QuickSearchResult | null; failed: boolean }
const shown = shallowRef<Shown | null>(null)
const loading = ref(false)

const CACHE_MAX = 30
const cache = new Map<string, QuickSearchResult>()
const cacheKey = (q: string, lang: AppLocale) => `${lang}\n${q}`
const remember = (key: string, result: QuickSearchResult) => {
  cache.delete(key)
  cache.set(key, result)
  const oldest = cache.keys().next().value
  if (cache.size > CACHE_MAX && oldest !== undefined) cache.delete(oldest)
}

let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | null = null

const cancel = () => {
  clearTimeout(timer)
  controller?.abort()
  controller = null
}

async function request(q: string, lang: AppLocale) {
  const current = new AbortController()
  controller = current
  try {
    const result = await fetchQuickSearch(q, { locale: lang, limit: QUICK_SEARCH_LIMIT, signal: current.signal })
    remember(cacheKey(q, lang), result)
    if (controller === current) shown.value = { q, result, failed: false }
  } catch {
    if (controller === current) shown.value = { q, result: null, failed: true }
  } finally {
    if (controller === current) {
      controller = null
      loading.value = false
    }
  }
}

function search(q: string, { now = false } = {}) {
  cancel()
  if (!q) {
    loading.value = false
    return
  }
  loadTemplates()
  const lang = appLocale.value
  const hit = cache.get(cacheKey(q, lang))
  if (hit) {
    loading.value = false
    shown.value = { q, result: hit, failed: false }
    return
  }
  loading.value = true
  if (now) void request(q, lang)
  else timer = setTimeout(() => void request(q, lang), QUICK_SEARCH_DEBOUNCE_MS)
}

watch([query, appLocale], ([q]) => search(q))

// UI 素材目录约 8 MB：第一次真正搜索时才读，读完只留搜索用得到的字段。读不到（没部署素材库）就不出这一组，下次打开再试。
const templates = shallowRef<QuickSearchTemplate[] | null>(null)
let templatesLoading: Promise<void> | null = null
function loadTemplates() {
  if (templates.value || templatesLoading) return
  templatesLoading = loadCatalog()
    .then((items) => { templates.value = items.map(slimTemplate) })
    .catch(() => { /* 本次不出 UI 素材组 */ })
    .finally(() => { templatesLoading = null })
}

// ── 结果 ───────────────────────────────────────────────────────────────

const recent = ref<string[]>([])
const readRecent = (): string[] => {
  try {
    return parseRecentQueries(localStorage.getItem(RECENT_QUERIES_KEY))
  } catch {
    return []
  }
}
const rememberQuery = (q: string) => {
  recent.value = pushRecentQuery(recent.value, q)
  try {
    localStorage.setItem(RECENT_QUERIES_KEY, JSON.stringify(recent.value))
  } catch {
    // 存不了就只在这次打开期间有效。
  }
}

const templateGroup = computed(() => (shown.value && templates.value ? matchTemplates(templates.value, shown.value.q, QUICK_SEARCH_LIMIT) : null))

const sections = computed<QuickSearchSection[]>(() => {
  if (!query.value) return draft.value.trim() ? [] : recentSection(recent.value)
  const view = shown.value
  if (!view) return []
  return buildSections({ q: view.q, result: view.result, templates: templateGroup.value, failed: view.result?.failed ?? [] }, appLocale.value, translate)
})
const options = computed(() => sections.value.flatMap(section => section.rows))
const indexOf = computed(() => new Map(options.value.map((row, index) => [row.key, index])))
const terms = computed(() => (query.value && shown.value ? highlightTerms(shown.value.q) : []))
const stale = computed(() => Boolean(query.value) && shown.value?.q !== query.value)

const active = ref(0)
const activeRow = computed(() => options.value[active.value] ?? null)
// 换了一批结果（或回到最近搜过的词）就从第一行起；同一批里后到的 UI 素材接在末尾，不动光标。
watch([shown, () => !query.value], () => { active.value = 0 })
watch(options, (rows) => { if (active.value >= rows.length) active.value = Math.max(0, rows.length - 1) })

const optionId = (index: number) => `quick-search-option-${index}`

const searchFailedNotice = computed(() => {
  if (!query.value || !shown.value?.failed) return ''
  return t(templateGroup.value?.items.length ? 'quickSearch.failedPartial' : 'quickSearch.failed')
})

const emptyText = computed(() => {
  if (sections.value.length) return ''
  if (!draft.value.trim()) return t('quickSearch.hint')
  if (!query.value) return t('quickSearch.tooShort')
  if (!shown.value || stale.value) return t('quickSearch.searching')
  if (shown.value.failed) return ''
  return t('quickSearch.noResults', { q: shown.value.q })
})

// 读屏：结果到了念一句有几条、或者没找到。
const status = computed(() => {
  if (!query.value || !shown.value || stale.value) return ''
  if (searchFailedNotice.value) return searchFailedNotice.value
  const count = options.value.filter(row => !row.more).length
  return count ? t('quickSearch.status', { count }) : emptyText.value
})

const GROUP_ICONS: Record<QuickSearchKind, Component> = {
  recent: History,
  projects: FolderGit2,
  papers: FileText,
  briefings: Newspaper,
  tweets: XLogoIcon,
  templates: LayoutTemplate,
}

/** 命中的词逐段标出来，不拼 HTML。 */
const Marked: FunctionalComponent<{ text: string; terms: readonly string[] }> = ({ text, terms: words }) =>
  highlight(text, words).map(part => (part.hit ? h('mark', part.text) : part.text))
Marked.props = ['text', 'terms']

const linkAttrs = (target: QuickSearchTarget) => {
  if (target.type === 'route') return { href: router.resolve(target.to).href, tabindex: -1 }
  if (target.type === 'external') return { href: target.href, tabindex: -1, target: '_blank', rel: 'noopener noreferrer' }
  return {}
}

// ── 操作 ───────────────────────────────────────────────────────────────

let opener: HTMLElement | null = null
let restoreFocus = true

function close(restore = true) {
  restoreFocus = restore
  hide()
}

function move(step: 1 | -1) {
  const count = options.value.length
  if (!count) return
  active.value = (active.value + step + count) % count
  void nextTick(() => document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' }))
}

function choose(row: QuickSearchRow, newTab = false) {
  const { target } = row
  if (target.type === 'query') {
    draft.value = target.q
    input.value?.focus()
    return
  }
  if (shown.value) rememberQuery(shown.value.q)
  if (target.type === 'external') {
    window.open(target.href, '_blank', 'noopener,noreferrer')
    if (!newTab) close()
    return
  }
  if (newTab) {
    window.open(router.resolve(target.to).href, '_blank', 'noopener')
    return
  }
  close(false)
  void router.push(target.to)
}

function onKeydown(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    close()
    return
  }
  // 框里只有搜索框一个能停焦点的地方，Tab 不出框。
  if (event.key === 'Tab') {
    event.preventDefault()
    return
  }
  if (event.altKey || event.shiftKey) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (!options.value.length) return
    event.preventDefault()
    event.stopPropagation()
    move(event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if (event.key !== 'Enter') return
  event.preventDefault()
  event.stopPropagation()
  // 刚改了词、新结果还没到：先别跳到上一批的结果上，马上去查。
  if (stale.value) {
    search(query.value, { now: true })
    return
  }
  const row = activeRow.value
  if (row) choose(row, apple ? event.metaKey : event.ctrlKey)
}

function point(row: QuickSearchRow) {
  const index = indexOf.value.get(row.key)
  if (index !== undefined && index !== active.value) active.value = index
}

function onRowClick(event: MouseEvent, row: QuickSearchRow) {
  const { target } = row
  if (target.type === 'query') {
    choose(row)
    return
  }
  if (shown.value) rememberQuery(shown.value.q)
  // 推文链接自己在新标签页打开；按着 ⌘/Ctrl/Shift 点站内结果也交给浏览器开新标签页或新窗口。
  if (target.type === 'external') {
    close()
    return
  }
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  close(false)
  void router.push(target.to)
}

watch(open, (isOpen) => {
  if (isOpen) {
    const focused = document.activeElement
    opener = focused instanceof HTMLElement && focused !== document.body ? focused : null
    restoreFocus = true
    // 再打开时从第一行起：上次的词还在框里（已选中，直接打字就换掉），光标不停在上次挑到的那一行。
    active.value = 0
    recent.value = readRecent()
    // 上次关上时没查完的词：接着查。
    if (query.value && shown.value?.q !== query.value) search(query.value, { now: true })
    void nextTick(() => {
      input.value?.focus({ preventScroll: true })
      input.value?.select()
    })
    return
  }
  cancel()
  loading.value = false
  if (restoreFocus && opener?.isConnected) opener.focus({ preventScroll: true })
  opener = null
})

watch(() => route.fullPath, () => { if (open.value) close(false) })
watch(() => props.enabled, (on) => { if (!on && open.value) close(false) })

useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (!props.enabled || !isQuickSearchHotkey(event, apple)) return
  // 别的对话框（登录框、推文详情）开着时不叠上去。
  if (!open.value && isModalOpen()) return
  event.preventDefault()
  if (open.value) close()
  else show()
})

onBeforeUnmount(cancel)

// ── 出现与消失 ─────────────────────────────────────────────────────────

const SLIDE = { y: -12 }
const SCRIM_MS = 180

function fadeScrim(root: Element, from: string, to: string, fill: FillMode) {
  const scrim = root.querySelector('.quick-search__scrim')
  if (scrim && canAnimate(scrim)) scrim.animate([{ opacity: from }, { opacity: to }], { duration: SCRIM_MS, easing: EASE_OUT, fill })
}

function onEnter(el: Element, done: () => void) {
  fadeScrim(el, '0', '1', 'backwards')
  const panel = el.querySelector('.quick-search__panel')
  if (panel) slideIn(panel, done, SLIDE)
  else done()
}

function onLeave(el: Element, done: () => void) {
  fadeScrim(el, '1', '0', 'forwards')
  const panel = el.querySelector('.quick-search__panel')
  if (!panel) {
    done()
    return
  }
  // 退场中的面板已经关了：不再算模态框，紧接着再按 ⌘K 能重新打开，列表键位也立刻还给页面。
  panel.removeAttribute('aria-modal')
  slideOut(panel, done, SLIDE)
}
</script>

<template>
  <Teleport to="body">
    <Transition :css="false" @enter="onEnter" @leave="onLeave">
      <div v-if="open" class="quick-search">
        <div class="quick-search__scrim" aria-hidden="true" @click="close()" />
        <div class="quick-search__panel" role="dialog" aria-modal="true" :aria-label="t('quickSearch.title')" @keydown="onKeydown">
          <div class="quick-search__field">
            <Search class="quick-search__glass" :size="18" :stroke-width="2.2" aria-hidden="true" />
            <input
              ref="input"
              v-model="draft"
              class="quick-search__input"
              type="text"
              role="combobox"
              aria-autocomplete="list"
              aria-controls="quick-search-list"
              :aria-expanded="options.length > 0"
              :aria-activedescendant="activeRow ? optionId(active) : undefined"
              :aria-label="t('quickSearch.title')"
              :placeholder="t('quickSearch.placeholder')"
              :maxlength="QUICK_SEARCH_MAX_CHARS * 2"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              enterkeyhint="go"
            >
            <LoaderCircle v-if="loading" class="quick-search__spinner" :size="16" :stroke-width="2.4" aria-hidden="true" />
            <kbd class="quick-search__esc" aria-hidden="true">Esc</kbd>
          </div>

          <div class="quick-search__body">
            <p v-if="searchFailedNotice" class="quick-search__notice">{{ searchFailedNotice }}</p>
            <div
              v-if="sections.length"
              id="quick-search-list"
              v-indicator="{ active: '[aria-selected=true]' }"
              class="quick-search__list"
              :class="{ 'is-stale': stale }"
              role="listbox"
              :aria-label="t('quickSearch.results')"
            >
              <ul
                v-for="section in sections"
                :key="section.kind"
                class="quick-search__group"
                role="group"
                :aria-labelledby="`quick-search-head-${section.kind}`"
              >
                <li :id="`quick-search-head-${section.kind}`" class="quick-search__head" role="presentation">
                  <component :is="GROUP_ICONS[section.kind]" class="quick-search__head-icon" aria-hidden="true" />
                  <span>{{ t(`quickSearch.group.${section.kind}`) }}</span>
                  <span v-if="section.total && section.kind !== 'recent'" class="quick-search__count">{{ formatLocaleNumber(section.total, appLocale) }}</span>
                  <span v-if="section.failed" class="quick-search__failed">{{ t('quickSearch.groupFailed') }}</span>
                </li>
                <li
                  v-for="row in section.rows"
                  :id="optionId(indexOf.get(row.key) ?? -1)"
                  :key="row.key"
                  class="quick-search__option"
                  :class="[`is-${row.kind}`, { 'is-more': row.more }]"
                  role="option"
                  :aria-selected="indexOf.get(row.key) === active"
                  @pointermove="point(row)"
                  @mousedown.prevent
                  @click="onRowClick($event, row)"
                >
                  <component :is="row.target.type === 'query' ? 'span' : 'a'" class="quick-search__link" v-bind="linkAttrs(row.target)">
                    <template v-if="row.more">
                      <span>{{ row.title }}</span>
                      <ArrowRight class="quick-search__arrow" :size="13" :stroke-width="2.4" aria-hidden="true" />
                    </template>
                    <template v-else-if="row.kind === 'recent'">
                      <span class="quick-search__title">{{ row.title }}</span>
                    </template>
                    <template v-else>
                      <span class="quick-search__line">
                        <span class="quick-search__title"><Marked :text="row.title" :terms="terms" /></span>
                        <span v-if="row.meta.length" class="quick-search__meta">{{ row.meta.join(' · ') }}</span>
                        <ArrowUpRight v-if="row.target.type === 'external'" class="quick-search__out" :size="13" :stroke-width="2.4" aria-hidden="true" />
                      </span>
                      <span v-if="row.detail" class="quick-search__detail"><Marked :text="row.detail" :terms="terms" /></span>
                    </template>
                  </component>
                </li>
              </ul>
            </div>
            <p v-else-if="emptyText" class="quick-search__empty">{{ emptyText }}</p>
          </div>

          <footer class="quick-search__foot" aria-hidden="true">
            <span><kbd>↑</kbd><kbd>↓</kbd>{{ t('quickSearch.keys.move') }}</span>
            <span><kbd>↵</kbd>{{ t('quickSearch.keys.open') }}</span>
            <span><kbd>{{ apple ? '⌘' : 'Ctrl' }}</kbd><kbd>↵</kbd>{{ t('quickSearch.keys.newTab') }}</span>
            <span><kbd>Esc</kbd>{{ t('quickSearch.keys.close') }}</span>
          </footer>
          <p class="sr-only" aria-live="polite">{{ status }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 安静但可发现：纸面卡片、硬边框、轻错版阴影，与快捷键表、「收藏本站」引导同一配方；选中行是一枚会滑动的荧光底。 */
.quick-search {
  --quick-search-mark: var(--acid);
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: max(56px, 11vh) 24px 24px;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.quick-search__scrim {
  position: absolute;
  inset: 0;
  background: rgb(0 0 0 / 0.3);
}

.quick-search__panel {
  position: relative;
  z-index: 1;
  display: flex;
  width: min(720px, 100%);
  max-height: min(660px, calc(100vh - max(56px, 11vh) - 32px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--rule-strong);
  border-radius: 10px;
  background: var(--paper-raised);
  box-shadow: 4px 4px 0 var(--shadow-ink-soft);
  color: var(--ink);
}

.quick-search__field {
  display: flex;
  height: 54px;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  padding: 0 14px 0 16px;
  border-bottom: 1px solid var(--rule);
}

.quick-search__glass,
.quick-search__spinner { flex: 0 0 auto; color: var(--ink-muted); }

.quick-search__spinner { animation: quick-search-spin 900ms linear infinite; }

@keyframes quick-search-spin { to { rotate: 360deg; } }

.quick-search__input {
  min-width: 0;
  height: 100%;
  flex: 1 1 auto;
  padding: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-size: 16px;
  font-weight: 600;
}

.quick-search__input::placeholder { color: var(--ink-muted); font-weight: 500; opacity: 1; }

.quick-search__body {
  min-height: 0;
  flex: 1 1 auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 8px 8px;
}

.quick-search__notice,
.quick-search__empty {
  margin: 0;
  padding: 14px 12px 6px;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 20px;
}

.quick-search__empty { padding-bottom: 14px; }

.quick-search__list { position: relative; }

/* 新结果还没到时，上一批淡一点。 */
.quick-search__list.is-stale .quick-search__option { opacity: 0.62; }

.quick-search__list[data-indicator-mark]::before {
  z-index: 0;
  border: 1px solid var(--rule-strong);
  border-radius: 6px;
  background: var(--acid-soft);
  box-shadow: inset 3px 0 0 var(--acid);
}

.quick-search__group {
  margin: 0;
  padding: 0;
  list-style: none;
}

.quick-search__head {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 11px 10px 5px;
  background: var(--paper-raised);
  color: var(--ink-muted);
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: 0.03em;
  line-height: 16px;
}

.quick-search__head-icon { width: 13px; height: 13px; flex: 0 0 auto; }

.quick-search__count { font-variant-numeric: tabular-nums; font-weight: 700; opacity: 0.8; }

.quick-search__failed { margin-left: auto; font-weight: 600; letter-spacing: 0; }

.quick-search__option {
  position: relative;
  z-index: 1;
  border-radius: 6px;
  cursor: pointer;
  scroll-margin: 34px 0 6px;
  transition: opacity 150ms ease;
}

.quick-search__link {
  display: block;
  padding: 7px 12px 8px 14px;
  color: inherit;
  text-decoration: none;
}

.quick-search__line {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 12px;
}

.quick-search__title {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  color: var(--ink);
  font-size: 14px;
  font-weight: 700;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-search__meta {
  max-width: 46%;
  flex: 0 1 auto;
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-search__out { flex: 0 0 auto; align-self: center; color: var(--ink-muted); }

.quick-search__detail {
  display: -webkit-box;
  margin-top: 1px;
  overflow: hidden;
  color: var(--ink-secondary);
  font-size: 12.5px;
  line-height: 18px;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

/* 简报与推文的命中常在正文中段：多给一行上下文。 */
.quick-search__option.is-briefings .quick-search__detail,
.quick-search__option.is-tweets .quick-search__detail { -webkit-line-clamp: 2; }

.quick-search__option.is-more .quick-search__link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-block: 6px;
  color: var(--ink-secondary);
  font-size: 12.5px;
  font-weight: 700;
}

.quick-search__option.is-recent .quick-search__title { font-size: 13.5px; font-weight: 600; }

.quick-search mark {
  padding: 0 1px;
  border-radius: 2px;
  background: linear-gradient(transparent 54%, var(--quick-search-mark) 54%);
  color: inherit;
}

.quick-search__foot {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 16px;
  padding: 8px 14px;
  border-top: 1px solid var(--rule);
  color: var(--ink-muted);
  font-size: 11.5px;
  line-height: 20px;
}

.quick-search__foot span { display: inline-flex; align-items: center; gap: 4px; }
.quick-search__foot kbd + kbd { margin-left: -1px; }

.quick-search kbd {
  display: inline-grid;
  min-width: 20px;
  height: 19px;
  place-items: center;
  padding: 0 5px;
  border: 1px solid var(--rule-strong);
  border-radius: 5px;
  background: var(--paper);
  box-shadow: 0 1.5px 0 var(--rule-strong);
  color: var(--ink);
  font-family: inherit;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.quick-search__esc { flex: 0 0 auto; }

@media (prefers-reduced-motion: reduce) {
  .quick-search__spinner { animation: none; }
  .quick-search__option { transition: none; }
}
</style>

<style>
/* 深色底上亮绿荧光笔会把浅色字的下半截吃掉：改成亮绿字。 */
:root[data-theme='dark'] .quick-search mark { background: none; color: var(--acid); }
</style>
