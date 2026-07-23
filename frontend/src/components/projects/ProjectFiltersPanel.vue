<script setup lang="ts">
import type {
  GitHubProjectCategory,
  GitHubProjectSort,
  GitHubProjectTag,
  ProjectScope,
  ProjectViewSource,
} from '../../services/api'

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean }

const props = defineProps<{
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
  selectScope: [scope: ProjectScope]
  selectCategory: [slug: string]
  selectSubcategory: [slug: string]
  selectPersonalTag: [tag: string]
  clearPersonalTag: []
}>()
</script>

<template>
  <section class="projects-toolbar glass-card">
    <div class="projects-source-tabs" aria-label="来源筛选">
      <button v-for="item in sourceOptions" :key="item.value" type="button" class="projects-source-tab" :class="source === item.value ? 'projects-source-tab--active' : ''" @click="emit('changeSource', item.value)">
        <strong>{{ item.label }}</strong>
        <small>{{ item.hint }}</small>
      </button>
    </div>

    <div v-if="!requiresPersonalLogin" class="projects-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input :value="searchQuery" class="input" type="search" placeholder="搜索项目名、网站、中文描述、语言或标签" @input="emit('update:searchQuery', ($event.target as HTMLInputElement).value)" />
      <button v-if="selectedLanguage" type="button" class="projects-search__filter" @click="emit('clearLanguage')">{{ selectedLanguage }} ×</button>
    </div>

    <label v-if="!requiresPersonalLogin" class="projects-sort">
      <span>排序</span>
      <select :value="sort" :disabled="selectedScope === 'today'" @change="emit('update:sort', ($event.target as HTMLSelectElement).value as GitHubProjectSort)">
        <option v-if="!isWebsiteOnlyView" value="hot">{{ selectedScope === 'today' ? '热度前 50' : '热度优先' }}</option>
        <option value="stars">Stars 优先</option>
        <option value="updated">最近更新</option>
        <option value="recent">最近收录</option>
        <option value="name">名称</option>
      </select>
    </label>
  </section>

  <section v-if="!requiresPersonalLogin && !isPersonalView" class="projects-category-panel glass-card" aria-label="项目分类筛选">
    <div class="projects-categories" aria-label="一级分类筛选">
      <button type="button" class="projects-category projects-category--scope" :class="selectedScope === 'all' && selectedCategory === 'all' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'all')"><span>{{ allScope?.name || '全部' }}</span><small>{{ allScope?.count ?? 0 }}</small></button>
      <button type="button" class="projects-category projects-category--recommend" :class="selectedScope === 'recommended' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'recommended')"><span>{{ recommendedScope?.name || '站长推荐' }}</span><small>{{ recommendedScope?.count ?? 0 }}</small></button>
      <button type="button" class="projects-category projects-category--today" :class="selectedScope === 'today' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectScope', 'today')"><span>{{ todayScope?.name || '今日暴涨' }}</span><small>{{ todayScope?.count ?? 0 }}</small></button>
      <button v-for="category in semanticCategories" :key="category.slug" type="button" class="projects-category" :class="selectedScope === 'all' && selectedCategory === category.slug ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectCategory', category.slug)"><span>{{ category.name }}</span><small>{{ category.count }}</small></button>
    </div>
    <div v-if="visibleSubcategories.length" class="projects-subcategories" aria-label="二级分类筛选">
      <span class="projects-subcategories__label">{{ activeCategory?.name }} · 二级分类</span>
      <button type="button" class="projects-category projects-category--sub" :class="selectedSubcategory === 'all' ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectSubcategory', 'all')"><span>全部</span><small>{{ activeCategory?.count ?? 0 }}</small></button>
      <button v-for="subcategory in visibleSubcategories" :key="subcategory.slug" type="button" class="projects-category projects-category--sub" :class="selectedSubcategory === subcategory.slug ? 'tab-active' : 'tab-inactive'" :disabled="categoriesLoading" @click="emit('selectSubcategory', subcategory.slug)"><span>{{ subcategory.name }}</span><small>{{ subcategory.count }}</small></button>
    </div>
  </section>

  <section v-else-if="!requiresPersonalLogin && (personalTags.length || selectedTag)" class="projects-category-panel projects-tag-panel glass-card" aria-label="个人标签筛选">
    <div class="projects-categories" aria-label="个人标签筛选">
      <button v-for="tag in personalTags" :key="tag.label" type="button" class="projects-category projects-category--tag" :class="selectedTag === tag.label ? 'tab-active' : 'tab-inactive'" :disabled="tagsLoading" @click="emit('selectPersonalTag', tag.label)"><span>{{ tag.label }}</span><small>{{ tag.count }}</small></button>
      <button v-if="selectedTag" type="button" class="projects-category projects-category--sub" :disabled="tagsLoading" @click="emit('clearPersonalTag')">清除标签</button>
    </div>
  </section>
</template>

<style scoped>
.projects-toolbar { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; padding: 14px; }
.projects-source-tabs { display: flex; gap: 8px; flex-shrink: 0; }
.projects-source-tab { display: flex; flex-direction: column; gap: 2px; min-width: 94px; border: 1px solid #11110f; border-radius: 4px; padding: 9px 12px; color: #78716c; background: var(--projects-paper-light); box-shadow: none; text-align: left; transition: all 160ms ease; }
.projects-source-tab strong { color: #44403c; font-size: 13px; }
.projects-source-tab small { font-size: 10px; opacity: .72; }
.projects-source-tab:hover { border-color: #11110f; color: #11110f; background: var(--projects-acid-soft); transform: none; }
.projects-source-tab--active { border-color: #11110f; color: #11110f; background: var(--projects-acid); box-shadow: inset 0 0 0 1px #11110f; transform: none; }
.projects-source-tab--active strong { color: #11110f; }
.projects-search { position: relative; flex: 1; }
.projects-search svg { position: absolute; left: 16px; top: 50%; z-index: 1; width: 17px; height: 17px; color: #a8a29e; transform: translateY(-50%); }
.projects-search .input { padding-left: 44px; border: 1px solid #11110f; border-radius: 4px; background: var(--projects-paper-light); box-shadow: none; }
.projects-search .input:focus { border-color: #11110f; box-shadow: 0 0 0 3px var(--projects-acid); }
.projects-search__filter { position: absolute; right: 10px; top: 50%; z-index: 2; transform: translateY(-50%); border: 1px solid #11110f; border-radius: 4px; padding: 5px 9px; color: var(--projects-warm); background: var(--projects-paper-light); box-shadow: none; font-size: 11px; font-weight: 800; }
.projects-sort { display: inline-flex; align-items: center; gap: 8px; color: #78716c; font-size: 12px; font-weight: 700; }
.projects-sort select { border: 1px solid #11110f; border-radius: 4px; padding: 10px 34px 10px 14px; color: #44403c; background: var(--projects-paper-light); box-shadow: none; outline: none; }
.projects-category-panel { position: relative; display: grid; gap: 12px; overflow: hidden; margin-bottom: 18px; padding: 14px; }
.projects-category-panel::before { content: ''; position: absolute; inset: 0; pointer-events: none; opacity: .22; mask-image: none; background: radial-gradient(circle at 10% 10%, var(--projects-warm-soft), transparent 26%), radial-gradient(circle at 88% 0%, var(--projects-accent-soft), transparent 30%); }
.projects-category-panel > * { position: relative; z-index: 1; }
.projects-categories, .projects-subcategories { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 3px; }
.projects-subcategories { align-items: center; padding-top: 11px; border-top: 1px solid #11110f; }
.projects-subcategories__label { flex-shrink: 0; border: 1px solid #11110f; border-radius: 4px; padding: 7px 10px; color: #78716c; background: var(--projects-paper-light); box-shadow: none; font-size: 11px; font-weight: 800; letter-spacing: .04em; }
.projects-category { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; border-radius: 4px; padding: 8px 12px; font-size: 13px; font-weight: 700; transition: all 160ms ease; }
.projects-category--scope, .projects-category--recommend, .projects-category--today { box-shadow: inset 0 0 0 1px rgba(168, 162, 158, .18); }
.projects-category--sub { padding: 7px 11px; font-size: 12px; }
.projects-category small { font-size: 11px; opacity: .68; }
.projects-category:hover, .projects-category:focus-visible, :deep(.tab-inactive:hover) { border-color: #11110f; color: #11110f; background: var(--projects-acid-soft); transform: none; }
:deep(.tab-active) { border-color: #11110f; color: #11110f; background: var(--projects-acid); box-shadow: inset 0 0 0 1px #11110f; transform: none; }
:deep(.tab-inactive) { border: 1px solid #11110f; border-radius: 4px; background: var(--projects-paper-light); }

@media (max-width: 720px) {
  .projects-toolbar { align-items: flex-start; flex-direction: column; }
  .projects-toolbar, .projects-source-tabs, .projects-search, .projects-sort, .projects-sort select { width: 100%; }
  .projects-source-tabs { overflow-x: auto; }
}
</style>
