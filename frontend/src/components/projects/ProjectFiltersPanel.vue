<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery, useResizeObserver } from '@vueuse/core'
import { Blocks, Bot, BrainCircuit, ChartNoAxesCombined, Code2, Database, FileText, Flame, FolderKanban, Image, LockKeyhole, Sparkles, TerminalSquare } from 'lucide-vue-next'
import type { AppLocale } from '@/i18n'
import { localizedCategoryName, localizedPersonalTagLabel } from '@/features/projects/projectPresentation'
import { vIndicator } from '@/motion/indicator'
import type {
  GitHubProjectCategory,
  GitHubProjectSort,
  GitHubProjectTag,
  ProjectScope,
  ProjectViewSource,
} from '@/services/projects/projectApi'

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean; scope?: ProjectScope }

const { locale, t } = useI18n()
const label = (item: GitHubProjectCategory | undefined) => localizedCategoryName(item, locale.value as AppLocale)

const categoryIcons = {
  productivity_tools: FileText,
  coding_tools: TerminalSquare,
  agents_automation: Bot,
  ai_apps: Blocks,
  learning_resources: FileText,
  rag_knowledge: Database,
  multimodal_tools: Image,
  models_infra: BrainCircuit,
  data_eval_training: ChartNoAxesCombined,
  security_privacy: LockKeyhole,
  other: FolderKanban,
} as const

const categoryIcon = (slug: string) => categoryIcons[slug as keyof typeof categoryIcons] || Code2

const props = defineProps<{
  catalogLayout?: boolean
  sourceOptions: SourceOption[]
  source: ProjectViewSource
  requiresPersonalLogin: boolean
  searchQuery: string
  selectedLanguage: string
  sort: GitHubProjectSort
  selectedScope: ProjectScope
  isWebsiteOnlyView: boolean
  isPersonalView: boolean
  categoriesLoading: boolean
  tagsLoading: boolean
  allScope?: GitHubProjectCategory
  recommendedScope?: GitHubProjectCategory
  todayScope?: GitHubProjectCategory
  semanticCategories: GitHubProjectCategory[]
  activeCategory?: GitHubProjectCategory
  visibleSubcategories: GitHubProjectCategory[]
  selectedCategory: string
  selectedSubcategory: string
  personalTags: GitHubProjectTag[]
  selectedTag: string
}>()

const emit = defineEmits<{
  'update:searchQuery': [value: string]
  'update:sort': [value: GitHubProjectSort]
  changeSource: [source: ProjectViewSource]
  clearLanguage: []
  selectLanguage: [value: string]
  selectScope: [scope: ProjectScope]
  selectCategory: [slug: string]
  selectSubcategory: [slug: string]
  selectPersonalTag: [tag: string]
  clearPersonalTag: []
}>()
const sortLabel = (key: string) => props.selectedScope === 'today'
  ? t('projects.sortAllOption', { sort: t(key) })
  : t(key)
const changeSort = (event: Event) => {
  const nextSort = (event.target as HTMLSelectElement).value as GitHubProjectSort
  // 今日榜单固定为热度前 50；其他排序先切到全库，再更新排序，避免被今日口径覆盖。
  if (props.selectedScope === 'today' && nextSort !== 'hot') emit('selectScope', 'all')
  emit('update:sort', nextSort)
}
const isMobile = useMediaQuery('(max-width: 767px)')
// 搜索框右端可以挂一个按钮（#search-end）：量出它有多宽，输入框的留白和清空、语言筛选按钮都往左让出这么多。
const searchEnd = ref<HTMLElement | null>(null)
const searchEndWidth = ref(0)
useResizeObserver(searchEnd, ([entry]) => { searchEndWidth.value = Math.ceil(entry?.borderBoxSize?.[0]?.inlineSize ?? entry?.contentRect.width ?? 0) })
</script>

<template>
  <section class="projects-toolbar glass-card" :class="{ 'projects-toolbar--catalog': catalogLayout }">
    <slot name="source-tabs">
    <div v-if="!catalogLayout" v-indicator="'.projects-source-tab--active'" class="projects-source-tabs" :aria-label="t('projects.sourceFilter')">
      <button v-for="item in sourceOptions" :key="item.value" type="button" class="projects-source-tab" :class="source === item.value && (!item.scope || selectedScope === item.scope) ? 'projects-source-tab--active' : ''" :aria-pressed="source === item.value && (!item.scope || selectedScope === item.scope)" :title="item.hint" @click="emit('changeSource', item.value)">
        <strong>{{ item.label }}</strong>
        <small>{{ item.hint }}</small>
      </button>
    </div>
    </slot>

    <div
      v-if="!requiresPersonalLogin"
      class="projects-search"
      :class="{ 'projects-search--filtered': selectedLanguage, 'projects-search--with-end': $slots['search-end'] }"
      :style="searchEndWidth ? { '--search-end': `${searchEndWidth}px` } : undefined"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input :value="searchQuery" class="input" :class="selectedLanguage ? 'projects-search__input--with-filter' : ''" type="search" :aria-label="t('projects.searchPlaceholder')" :placeholder="t(isMobile ? 'projects.mobileSearch' : 'projects.searchPlaceholder')" @input="emit('update:searchQuery', ($event.target as HTMLInputElement).value)" />
      <button
        v-if="searchQuery"
        type="button"
        class="projects-search__clear"
        :class="selectedLanguage ? 'projects-search__clear--with-filter' : ''"
        :aria-label="t('projects.clearSearch')"
        :title="t('projects.clearSearch')"
        @click="emit('update:searchQuery', '')"
      >×</button>
      <button v-if="selectedLanguage" type="button" class="projects-search__filter" @click="emit('clearLanguage')">{{ selectedLanguage }} ×</button>
      <div v-if="$slots['search-end']" ref="searchEnd" class="projects-search__end"><slot name="search-end" /></div>
    </div>

    <label v-if="!requiresPersonalLogin && !isPersonalView" class="projects-sort" :class="{ 'projects-sort--today': selectedScope === 'today' }">
      <span>{{ t('projects.sort') }}</span>
      <select :aria-label="t('projects.sort')" :value="sort" @change="changeSort">
        <option v-if="!isWebsiteOnlyView && !isPersonalView && searchQuery.trim()" value="relevance">{{ sortLabel('projects.sortRelevance') }}</option>
        <option v-if="!isWebsiteOnlyView" value="hot">{{ t(selectedScope === 'today' ? 'projects.sortHotTop' : 'projects.sortHot') }}</option>
        <option value="stars">{{ sortLabel('projects.sortStars') }}</option>
        <option value="updated">{{ sortLabel('projects.sortUpdated') }}</option>
        <option value="recent">{{ sortLabel('projects.sortRecent') }}</option>
        <option value="name">{{ sortLabel('projects.sortName') }}</option>
      </select>
    </label>
  </section>

  <details v-if="!requiresPersonalLogin && !isPersonalView" class="projects-category-panel glass-card" :open="!isMobile" :aria-label="t('projects.categoryFilter')">
    <summary>{{ t('projects.mobileFilters') }}<span>{{ selectedScope === 'screened' ? t('projectAssessment.screened') : selectedScope === 'today' ? t('projects.today') : selectedScope === 'recommended' ? t('projects.recommended') : label(activeCategory) || t('projects.all') }}</span></summary>
    <div v-indicator="'.tab-active'" class="projects-categories" :aria-label="t('projects.primaryCategoryFilter')">
      <button type="button" class="projects-category projects-category--today" :class="selectedScope === 'today' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'today')"><Flame v-if="catalogLayout" :size="16" aria-hidden="true" /><span>{{ t('projects.today') }}</span><small>{{ todayScope?.count ?? 0 }}</small></button>
      <button type="button" class="projects-category projects-category--scope projects-category--screened" :class="selectedScope === 'screened' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'screened')"><span>{{ t('projectAssessment.screened') }}</span></button>
      <button type="button" class="projects-category projects-category--scope" :class="selectedScope === 'all' && selectedCategory === 'all' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'all')"><Blocks v-if="catalogLayout" :size="16" aria-hidden="true" /><span>{{ label(allScope) || t('projects.all') }}</span><small>{{ allScope?.count ?? 0 }}</small></button>
      <button type="button" class="projects-category projects-category--recommend" :class="selectedScope === 'recommended' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'recommended')"><Sparkles v-if="catalogLayout" :size="16" aria-hidden="true" /><span>{{ label(recommendedScope) || t('projects.recommended') }}</span><small>{{ recommendedScope?.count ?? 0 }}</small></button>
      <button v-for="category in semanticCategories" :key="category.slug" type="button" class="projects-category" :class="selectedScope === 'all' && selectedCategory === category.slug ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectCategory', category.slug)"><component :is="categoryIcon(category.slug)" v-if="catalogLayout" :size="16" aria-hidden="true" /><span>{{ label(category) }}</span><small>{{ category.count }}</small></button>
    </div>
    <p v-if="selectedScope === 'screened'" class="projects-screened-note">{{ t('projectAssessment.criteria') }}</p>
    <div v-if="visibleSubcategories.length" v-indicator="'.tab-active'" class="projects-subcategories" :aria-label="t('projects.subcategoryFilter')">
      <span class="projects-subcategories__label">{{ t('projects.subcategory', { category: label(activeCategory) || '' }) }}</span>
      <button type="button" class="projects-category projects-category--sub" :class="selectedSubcategory === 'all' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectSubcategory', 'all')"><span>{{ t('projects.all') }}</span><small>{{ activeCategory?.count ?? 0 }}</small></button>
      <button v-for="subcategory in visibleSubcategories" :key="subcategory.slug" type="button" class="projects-category projects-category--sub" :class="selectedSubcategory === subcategory.slug ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectSubcategory', subcategory.slug)"><span>{{ label(subcategory) }}</span><small>{{ subcategory.count }}</small></button>
    </div>
  </details>

  <section v-else-if="!requiresPersonalLogin && (personalTags.length > 1 || selectedTag)" class="projects-category-panel projects-tag-panel glass-card" :aria-label="t('projects.personalTagFilter')">
    <!-- 标签各自带框（漫画页是手绘框），选中换框不滑块，新选中的标签盖章式弹入。 -->
    <div v-indicator="{ active: '.tab-active', mark: false, pop: true }" class="projects-categories" :aria-label="t('projects.personalTagFilter')">
      <button v-for="tag in personalTags" :key="tag.value" type="button" class="projects-category projects-category--tag" :class="selectedTag === tag.value ? 'tab-active' : 'tab-inactive'" :disabled="tagsLoading" @click="emit('selectPersonalTag', tag.value)"><span>{{ localizedPersonalTagLabel(tag, locale as AppLocale) }}</span><small>{{ tag.count }}</small></button>
      <button v-if="selectedTag" type="button" class="projects-category projects-category--sub" :disabled="tagsLoading" @click="emit('clearPersonalTag')">{{ t('projects.clearTag') }}</button>
    </div>
  </section>
</template>

<style scoped>
.projects-screened-note { margin: 10px 4px; color: var(--ink-secondary); font-size: 12px; line-height: 1.6; }
.projects-category-panel > summary { display: none; }

.projects-toolbar { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; margin-bottom: 12px; padding: 0; border: 0 !important; background: transparent !important; }
.projects-source-tabs { display: flex; min-width: 0; gap: 4px; padding: 3px; border-radius: var(--control-radius); background: var(--paper-muted); }
.projects-source-tab { display: flex; justify-content: center; align-items: center; min-width: 0; min-height: 38px; padding: 4px 12px; border: 1px solid transparent; border-radius: 6px; color: var(--ink-secondary); white-space: nowrap; }
.projects-source-tab strong { font-size: 13px; font-weight: 600; }
.projects-source-tab small { display: none; }
.projects-source-tab--active { color: var(--projects-on-acid); border-color: var(--projects-accent); background: var(--projects-acid); box-shadow: 2px 2px 0 var(--shadow-hard); }
.projects-source-tab:hover { color: var(--ink); }
/* 选中块由 v-indicator 画在 tab 条的 ::before 上，在来源间弹簧滑动；选中项把底让给它。 */
.projects-source-tabs { position: relative; isolation: isolate; }
.projects-source-tabs[data-indicator-mark]::before { z-index: -1; border: 1px solid var(--projects-accent); border-radius: 6px; background: var(--projects-acid); box-shadow: 2px 2px 0 var(--shadow-hard); }
.projects-source-tabs[data-indicator] .projects-source-tab--active { border-color: transparent; background: transparent; box-shadow: none; }
.projects-toolbar :is(button, select):focus-visible, .projects-category:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.projects-search { position: relative; min-width: 0; }
.projects-search > svg { position: absolute; top: 50%; left: 14px; width: 18px; height: 18px; color: var(--ink-muted); transform: translateY(-50%); pointer-events: none; }
.projects-search .input { height: 44px; padding: 0 44px; border: 1px solid var(--ink-muted); border-radius: 6px; background: var(--paper-raised); }
.projects-search .input:focus { border-color: var(--ink); box-shadow: 0 0 0 3px var(--acid-soft); }
.projects-search .input.projects-search__input--with-filter { padding-right: 142px; }
.projects-search .input::-webkit-search-cancel-button { appearance: none; }
.projects-search__clear, .projects-search__filter { position: absolute; top: 50%; right: 4px; display: flex; align-items: center; justify-content: center; height: 36px; min-width: 36px; border-radius: 6px; transform: translateY(-50%); color: var(--ink-secondary); }
.projects-search__clear:hover, .projects-search__filter:hover { background: var(--paper-muted); }
.projects-search__filter { right: 8px; max-width: 96px; padding: 0 8px; overflow: hidden; background: var(--paper-muted); font-size: 12px; white-space: nowrap; text-overflow: ellipsis; }
.projects-search__clear--with-filter { right: 106px; }
/* 搜索框右端的附加按钮：输入框留白、清空与语言筛选按钮都让出它的宽度（--search-end 由脚本量出）。 */
.projects-search__end { position: absolute; top: 50%; right: 5px; display: flex; align-items: center; transform: translateY(-50%); }
/* 按钮按搜索框的宽度收放（@container projects-search），框里没有别的会弹出来的东西，包含不碍事。 */
.projects-search--with-end { container: projects-search / inline-size; }
.projects-search--with-end .input { padding-right: calc(var(--search-end, 0px) + 44px); }
/* 还没输入时没有清空键，占位文字一直排到按钮跟前。 */
.projects-search--with-end .input:not(.projects-search__input--with-filter):placeholder-shown { padding-right: calc(var(--search-end, 0px) + 12px); }
.projects-search--with-end .input.projects-search__input--with-filter { padding-right: calc(var(--search-end, 0px) + 142px); }
.projects-search--with-end .projects-search__clear { right: calc(var(--search-end, 0px) + 9px); }
.projects-search--with-end .projects-search__filter { right: calc(var(--search-end, 0px) + 13px); }
.projects-search--with-end .projects-search__clear--with-filter { right: calc(var(--search-end, 0px) + 111px); }
.projects-sort { display: flex; align-items: center; gap: 8px; color: var(--ink-secondary); font-size: 12px; }
.projects-sort select { min-width: 124px; max-width: 100%; height: 44px; padding: 0 8px; color: var(--ink-secondary); background: var(--paper-raised); border: 1px solid var(--rule); border-radius: var(--control-radius); font-size: 13px; }
.projects-category-panel { display: grid; gap: 8px; margin-bottom: 12px; padding: 0; border: 0 !important; background: transparent !important; }
.projects-categories, .projects-subcategories { display: flex; align-items: center; gap: 6px; min-width: 0; flex-wrap: wrap; overflow: visible; padding: 2px 2px 6px; }
.projects-categories::-webkit-scrollbar, .projects-subcategories::-webkit-scrollbar { display: none; }
.projects-subcategories { border-top: 1px solid var(--rule); padding-top: 8px; }
.projects-subcategories__label { flex-shrink: 0; font-size: 12px; color: var(--ink-secondary); }
.projects-category { display: inline-flex; align-items: center; flex-shrink: 0; gap: 6px; min-height: 36px; padding: 4px 10px; border: 1px solid var(--rule); border-radius: 5px; color: var(--ink-secondary); background: var(--paper-raised); font-size: 13px; font-weight: 550; white-space: nowrap; }
.projects-category small { font-size: 12px; opacity: .8; font-variant-numeric: tabular-nums; }
.projects-category:hover { background: var(--paper-muted); color: var(--ink); }
.projects-category.tab-active, .projects-category.tab-active:hover { color: var(--projects-on-acid); background: var(--projects-acid); border-color: var(--projects-accent); font-weight: 750; box-shadow: 2px 2px 0 var(--shadow-hard); }
@media (max-width: 1023px) {
  .projects-toolbar { grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
  .projects-source-tabs { width: fit-content; max-width: 100%; }
  .projects-sort { grid-column: 2; grid-row: 1; }
  .projects-search { grid-column: 1 / -1; grid-row: 2; }
  .projects-category { min-height: 44px; }
}
@media (max-width: 639px) {
  .projects-sort > span { display: none; }
  .projects-sort select { min-width: 100px; width: 108px; font-size: 12px; }
  .projects-source-tabs { width: 100%; }
  .projects-source-tab { flex: 1 1 0; padding: 4px; }
  .projects-source-tab strong { font-size: 12px; white-space: nowrap; }
  .projects-search .input { font-size: 16px; }
}
@media (max-width: 767px) {
  .projects-toolbar { flex-direction: row; flex-wrap: wrap; gap: 10px; padding: 12px; }
  .projects-source-tabs { flex: 1 0 100%; width: 100%; overflow-x: auto; }
  .projects-source-tab { flex: 1; justify-content: center; }
  .projects-source-tab small { display: none; }
  .projects-search { order: initial; flex: 1 1 0; min-width: 0; }
  .projects-search--filtered { flex-basis: 100%; }
  .projects-search .input { padding-left: 34px; }
  .projects-search svg { left: 12px; }
  .projects-sort { flex: 0 0 108px; width: 108px; }
  .projects-sort select { width: 100%; min-width: 0; padding-left: 8px; padding-right: 24px; font-size: 14px; }
  .projects-sort span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .projects-categories, .projects-subcategories { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
}

@media (max-width: 767px) { .projects-toolbar { display: flex; } .projects-source-tabs { background: transparent; } }
</style>
