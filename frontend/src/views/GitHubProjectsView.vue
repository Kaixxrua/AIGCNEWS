<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { AppLocale } from '@/i18n'
import type {
  GitHubProjectItem,
  GitHubProjectSort,
  ManualToolWebsitePayload,
  ProjectScope,
  ProjectViewSource,
  ToolWebsiteUpdatePayload,
} from '@/services/projects/projectApi'
import router from '@/router'
import { useAuthStore } from '@/stores/authStore'
import ProjectResultCard from '@/components/projects/ProjectResultCard.vue'
import ToolWebsiteAddDialog from '@/components/projects/ToolWebsiteAddDialog.vue'
import ToolWebsiteEditDialog from '@/components/projects/ToolWebsiteEditDialog.vue'
import ProjectFiltersPanel from '@/components/projects/ProjectFiltersPanel.vue'
import ProjectPagination from '@/components/projects/ProjectPagination.vue'
import { useProjectCatalogController } from '@/composables/useProjectCatalogController'
import { defaultProjectSortForQuery, useProjectRouteState } from '@/composables/useProjectRouteState'
import {
  canEditWebsiteProject,
  canFavoriteProject,
  canRecommendProject,
  isWebsite,
  localizedCategoryName,
  projectKey,
  projectLogoKey,
  type ProjectChip,
} from '@/features/projects/projectPresentation'

defineOptions({ name: 'GitHubProjectsView' })
const { locale, t } = useI18n()
const categoryLabel = (item: Parameters<typeof localizedCategoryName>[0]) => localizedCategoryName(item, locale.value as AppLocale)
const authStore = useAuthStore()
const route = useRoute()
const source = ref<ProjectViewSource>('all')
const selectedScope = ref<ProjectScope>('all')
const selectedCategory = ref('all')
const selectedSubcategory = ref('all')
const searchQuery = ref('')
const debouncedQuery = ref('')
const selectedLanguage = ref('')
const selectedTag = ref('')
const sort = ref<GitHubProjectSort>('stars')
const sortIsExplicit = ref(false)
const page = ref(1)
const pageJump = ref('')
const addDialogOpen = ref(false)
const editDialogOpen = ref(false)
const editTarget = ref<GitHubProjectItem | null>(null)
const VIEW_REFRESH_INTERVAL = 60_000
let hasActivatedOnce = false
let searchTimer: number | undefined

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean }

const { applyRouteState, currentProjectsRedirect, endStateBatch, isApplyingRouteState, isReplacingRoute, replaceRouteFromState } = useProjectRouteState(route, router, {
  source, selectedScope, selectedCategory, selectedSubcategory, searchQuery, debouncedQuery, selectedLanguage, selectedTag, sort, page,
})

const controller = useProjectCatalogController({
  routeState: { source, selectedScope, selectedCategory, selectedSubcategory, searchQuery, debouncedQuery, selectedLanguage, selectedTag, sort, page },
  t,
  isLoggedIn: () => authStore.isLoggedIn,
  isAdmin: () => authStore.isAdmin,
  currentRedirect: currentProjectsRedirect,
  navigateToLogin: async (redirect) => { await router.push({ path: '/login', query: { redirect } }) },
  replaceRouteFromState,
})

const {
  addToolError, addingTool, categories, categoriesLoading, deletingWebsiteId, editError, errorMsg,
  favoriteBusyKey, isMyCollection, isPersonalView, isViewActive, lastSuccessfulFetchAt, loadCategories,
  loadProjects, loadTaxonomy, loading, pageSize, personalTags, projects, recommendBusyKey,
  recommendProject, refreshReads, removeToolWebsite, requiresPersonalLogin, savingEdit, successMsg, tagsLoading,
  taxonomy, taxonomyLoading, toggleFavorite, total,
} = controller
const sourceOptions = computed<SourceOption[]>(() => [
  { value: 'all', label: t('projects.source.allLabel'), hint: t('projects.source.allHint') },
  { value: 'website', label: t('projects.source.websiteLabel'), hint: t('projects.source.websiteHint'), authOnly: true },
  { value: 'favorites', label: t('projects.source.favoritesLabel'), hint: t('projects.source.favoritesHint'), authOnly: true },
])
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const hasPrev = computed(() => page.value > 1)
const hasNext = computed(() => page.value < totalPages.value)
const scopeCategories = computed(() => categories.value.filter((item) => item.kind === 'scope'))
const allScope = computed(() => scopeCategories.value.find((item) => item.scope === 'all' || item.slug === 'all'))
const recommendedScope = computed(() => scopeCategories.value.find((item) => item.scope === 'recommended' || item.slug === 'recommended'))
const todayScope = computed(() => scopeCategories.value.find((item) => item.scope === 'today' || item.slug === 'today'))
const semanticCategories = computed(() => categories.value.filter((item) => (item.kind ?? 'category') === 'category'))
const activeCategory = computed(() => semanticCategories.value.find((item) => item.slug === selectedCategory.value))
const visibleSubcategories = computed(() => activeCategory.value?.children ?? [])
const activeSubcategory = computed(() => visibleSubcategories.value.find((item) => item.slug === selectedSubcategory.value))
const isWebsiteOnlyView = computed(() => source.value === 'website')
const sourceLabel = computed(() => sourceOptions.value.find((item) => item.value === source.value)?.label ?? t('projects.all'))
const personalLoginCopy = computed(() => isWebsiteOnlyView.value
  ? { kicker: t('projects.loginWebsiteKicker'), title: t('projects.loginWebsiteTitle'), description: t('projects.loginWebsiteDescription') }
  : { kicker: t('projects.loginFavoritesKicker'), title: t('projects.loginFavoritesTitle'), description: t('projects.loginFavoritesDescription') })
const starsBadgeLabel = computed(() => source.value === 'all' ? t('projects.starsThresholdBadge') : '')
const activeFilterLabel = computed(() => {
  if (selectedTag.value) return t('projects.filterTag', { tag: selectedTag.value })
  if (selectedLanguage.value) return t('projects.filterLanguage', { language: selectedLanguage.value })
  if (isPersonalView.value) return t('projects.noTagFilter')
  if (selectedScope.value === 'recommended') return categoryLabel(recommendedScope.value) || t('projects.recommended')
  if (selectedScope.value === 'today') return categoryLabel(todayScope.value) || t('projects.today')
  if (activeCategory.value && activeSubcategory.value) return `${categoryLabel(activeCategory.value)} / ${categoryLabel(activeSubcategory.value)}`
  if (activeCategory.value) return categoryLabel(activeCategory.value)
  return t('projects.allCategories')
})
const hasActiveFilter = computed(() => selectedScope.value !== 'all' || selectedCategory.value !== 'all' || selectedSubcategory.value !== 'all' || !!selectedLanguage.value || !!selectedTag.value)

const brokenLogoKeys = ref<Set<string>>(new Set())
const loadedLogoKeys = ref<Set<string>>(new Set())
const isWebsiteLogoLoaded = (repo: GitHubProjectItem) => {
  const key = projectLogoKey(repo)
  return Boolean(key && loadedLogoKeys.value.has(key))
}
const markWebsiteLogoLoaded = (repo: GitHubProjectItem) => {
  const key = projectLogoKey(repo)
  if (key && !loadedLogoKeys.value.has(key)) loadedLogoKeys.value = new Set([...loadedLogoKeys.value, key])
}
const hideBrokenLogo = (repo: GitHubProjectItem) => {
  const key = projectLogoKey(repo)
  if (!key) return
  brokenLogoKeys.value = new Set([...brokenLogoKeys.value, key])
  if (loadedLogoKeys.value.has(key)) {
    const nextLoadedKeys = new Set(loadedLogoKeys.value)
    nextLoadedKeys.delete(key)
    loadedLogoKeys.value = nextLoadedKeys
  }
}
const canFavorite = canFavoriteProject
const canRecommendCard = (repo: GitHubProjectItem) => canRecommendProject(repo, authStore.isAdmin)
const canEditCard = (repo: GitHubProjectItem) => canEditWebsiteProject(repo, isWebsiteOnlyView.value)

const resetAndLoad = () => {
  if (isApplyingRouteState.value) return
  page.value = 1
  void replaceRouteFromState()
  void loadProjects()
}
const resetScopeToAll = () => { selectedScope.value = 'all' }
const changeSource = (nextSource: ProjectViewSource) => {
  if (source.value === nextSource) return
  isApplyingRouteState.value = true
  source.value = nextSource
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  page.value = 1
  sortIsExplicit.value = false
  sort.value = defaultProjectSortForQuery(selectedScope.value, nextSource, debouncedQuery.value)
  endStateBatch()
  void replaceRouteFromState(true)
  void refreshReads()
}
const selectScope = (scopeValue: ProjectScope) => {
  if (selectedScope.value === scopeValue && selectedCategory.value === 'all' && selectedSubcategory.value === 'all' && !selectedLanguage.value) return
  selectedScope.value = scopeValue
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  sortIsExplicit.value = false
  sort.value = defaultProjectSortForQuery(scopeValue, source.value, debouncedQuery.value)
}
const clearLanguageFilter = () => { if (selectedLanguage.value) selectedLanguage.value = '' }
const selectPersonalTag = (tag: string) => {
  const cleanTag = tag.trim()
  if (!cleanTag || selectedTag.value === cleanTag) return
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = cleanTag
  page.value = 1
}
const clearPersonalTag = () => { if (selectedTag.value) { selectedTag.value = ''; page.value = 1 } }
const selectCategory = (slug: string) => {
  if (selectedScope.value === 'all' && selectedCategory.value === slug && selectedSubcategory.value === 'all') return
  resetScopeToAll()
  selectedCategory.value = slug
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
}
const selectSubcategory = (slug: string) => {
  if (selectedSubcategory.value === slug) return
  resetScopeToAll()
  selectedSubcategory.value = slug
  selectedLanguage.value = ''
  selectedTag.value = ''
}
const handleChipClick = (chip: ProjectChip) => {
  page.value = 1
  if (chip.type === 'subcategory') {
    resetScopeToAll(); selectedCategory.value = chip.categorySlug || selectedCategory.value; selectedSubcategory.value = chip.value; selectedLanguage.value = ''; selectedTag.value = ''; searchQuery.value = ''; debouncedQuery.value = ''; return
  }
  if (chip.type === 'category') {
    resetScopeToAll(); selectedCategory.value = chip.value; selectedSubcategory.value = 'all'; selectedLanguage.value = ''; selectedTag.value = ''; searchQuery.value = ''; debouncedQuery.value = ''; return
  }
  if (chip.type === 'language') {
    if (source.value === 'website') { source.value = 'all'; void loadCategories() }
    resetScopeToAll(); selectedCategory.value = 'all'; selectedSubcategory.value = 'all'; selectedLanguage.value = chip.value; selectedTag.value = ''; searchQuery.value = ''; debouncedQuery.value = ''; return
  }
  if (chip.type === 'tag' && isPersonalView.value) { searchQuery.value = ''; debouncedQuery.value = ''; selectPersonalTag(chip.value); return }
  resetScopeToAll(); selectedCategory.value = 'all'; selectedSubcategory.value = 'all'; selectedLanguage.value = ''; selectedTag.value = ''; searchQuery.value = chip.value; debouncedQuery.value = chip.value
}
const goPage = (nextPage: number) => {
  const target = Math.max(1, Math.min(totalPages.value, nextPage))
  pageJump.value = ''
  if (target === page.value) return
  page.value = target
  void replaceRouteFromState()
  void loadProjects()
}
const jumpToPage = () => {
  const parsed = Number(pageJump.value)
  if (!Number.isFinite(parsed) || parsed < 1) { pageJump.value = ''; return }
  goPage(Math.floor(parsed))
}
watch(searchQuery, (value) => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { debouncedQuery.value = value }, 280)
})
watch(debouncedQuery, (value) => {
  if (!sortIsExplicit.value) {
    sort.value = defaultProjectSortForQuery(selectedScope.value, source.value, value)
  }
})

const goToPersonalLogin = () => { router.push({ path: '/login', query: { redirect: currentProjectsRedirect() } }) }
const openAddDialog = () => {
  if (!authStore.isLoggedIn) { router.push({ path: '/login', query: { redirect: '/projects?source=website' } }); return }
  addToolError.value = ''
  addDialogOpen.value = true
  void loadTaxonomy()
}
const closeAddDialog = () => { if (!addingTool.value) { addDialogOpen.value = false; addToolError.value = '' } }
const openEditDialog = (repo: GitHubProjectItem) => {
  if (!canEditCard(repo)) return
  editTarget.value = repo
  editError.value = ''
  editDialogOpen.value = true
  void loadTaxonomy()
}
const closeEditDialog = () => {
  if (savingEdit.value) return
  editDialogOpen.value = false
  editError.value = ''
  editTarget.value = null
}
const submitEditWebsite = async (websiteId: string | number, payload: ToolWebsiteUpdatePayload) => {
  if (!await controller.submitEditWebsite(websiteId, payload)) return
  editDialogOpen.value = false
  editTarget.value = null
}
const submitToolWebsite = async (request: string | ManualToolWebsitePayload) => {
  if (await controller.submitToolWebsite(request)) addDialogOpen.value = false
}

watch([selectedScope, selectedCategory, selectedSubcategory, selectedLanguage, selectedTag, debouncedQuery, sort], resetAndLoad)
watch(() => route.query, () => {
  if (!isViewActive.value || route.name !== 'github-projects' || isReplacingRoute.value) return
  const hadSort = Boolean(String(route.query.sort ?? '').trim())
  if (applyRouteState()) {
    sortIsExplicit.value = hadSort
    void refreshReads()
  }
})
watch(() => authStore.isLoggedIn, (loggedIn) => {
  if (!loggedIn) {
    controller.handleLogout()
    if (isPersonalView.value) { addDialogOpen.value = false; editDialogOpen.value = false; editTarget.value = null; return }
  }
  void refreshReads()
})
const stopViewReads = () => {
  if (searchTimer) { window.clearTimeout(searchTimer); searchTimer = undefined }
  controller.deactivate()
}
onMounted(() => {
  const hadSort = Boolean(String(route.query.sort ?? '').trim())
  if (applyRouteState()) {
    sortIsExplicit.value = hadSort
    void refreshReads()
  }
})
onActivated(() => {
  controller.activate()
  if (!hasActivatedOnce) { hasActivatedOnce = true; return }
  if (searchQuery.value !== debouncedQuery.value) searchTimer = window.setTimeout(() => { debouncedQuery.value = searchQuery.value }, 280)
  if (Date.now() - lastSuccessfulFetchAt.value >= VIEW_REFRESH_INTERVAL) {
    void refreshReads({ clearSuccess: false, preserveContent: true })
  }
})
onDeactivated(stopViewReads)
onBeforeUnmount(stopViewReads)
</script>

<template>
  <div class="projects-page">
    <section class="projects-hero glass-card">
      <div class="projects-hero__text">
        <p class="projects-kicker">AI TOOL ATLAS</p>
        <h1>{{ t('navigation.projects') }}</h1>
        <p>{{ t('projects.publicLibrary') }}</p>
      </div>

      <div class="projects-hero__side">
        <div class="projects-hero__stats" :aria-label="t('projects.results', { count: total })">
          <span>{{ t('projects.results', { count: total }) }}</span>
          <span>{{ sourceLabel }}</span>
          <span v-if="starsBadgeLabel">{{ starsBadgeLabel }}</span>
          <span>{{ activeFilterLabel }}</span>
        </div>
        <button
          v-if="isWebsiteOnlyView && !requiresPersonalLogin"
          type="button"
          class="projects-add-btn"
          :title="isMyCollection && !authStore.isLoggedIn ? t('projects.loginAction') : ''"
          @click="openAddDialog"
        >
          <span>＋</span>
          {{ t('projects.addWebsite') }}
        </button>
      </div>
    </section>

    <ProjectFiltersPanel
      v-model:search-query="searchQuery"
      v-model:sort="sort"
      :source-options="sourceOptions"
      :source="source"
      :requires-personal-login="requiresPersonalLogin"
      :selected-language="selectedLanguage"
      :selected-scope="selectedScope"
      :is-website-only-view="isWebsiteOnlyView"
      :is-personal-view="isPersonalView"
      :categories-loading="categoriesLoading"
      :tags-loading="tagsLoading"
      :all-scope="allScope"
      :recommended-scope="recommendedScope"
      :today-scope="todayScope"
      :semantic-categories="semanticCategories"
      :active-category="activeCategory"
      :visible-subcategories="visibleSubcategories"
      :selected-category="selectedCategory"
      :selected-subcategory="selectedSubcategory"
      :personal-tags="personalTags"
      :selected-tag="selectedTag"
      @update:sort="sortIsExplicit = true"
      @change-source="changeSource"
      @clear-language="clearLanguageFilter"
      @select-scope="selectScope"
      @select-category="selectCategory"
      @select-subcategory="selectSubcategory"
      @select-personal-tag="selectPersonalTag"
      @clear-personal-tag="clearPersonalTag"
    />

    <section v-if="successMsg && !requiresPersonalLogin" class="projects-toast projects-toast--success glass-card">
      {{ successMsg }}
    </section>

    <section v-if="requiresPersonalLogin" class="projects-login-prompt glass-card" aria-labelledby="personal-login-title">
      <div class="projects-login-prompt__mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <rect x="4" y="10" width="16" height="11" rx="3" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" />
          <path d="M12 14v3" />
        </svg>
      </div>
      <div class="projects-login-prompt__copy">
        <p class="projects-kicker">{{ personalLoginCopy.kicker }}</p>
        <h2 id="personal-login-title">{{ personalLoginCopy.title }}</h2>
        <p>{{ personalLoginCopy.description }}</p>
        <div class="projects-login-prompt__notes" :aria-label="t('projects.loginFeatures')">
          <span>{{ t(isWebsiteOnlyView ? 'projects.privateShelf' : 'projects.favoriteSync') }}</span>
          <span>{{ t('projects.tagOrganization') }}</span>
          <span>{{ t('projects.crossDevice') }}</span>
        </div>
      </div>
      <button type="button" class="projects-login-prompt__action" @click="goToPersonalLogin">
        {{ t('projects.loginAction') }}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h14" />
          <path d="m14 7 5 5-5 5" />
        </svg>
      </button>
    </section>

    <template v-else>
    <section v-if="errorMsg" class="projects-toast projects-toast--error glass-card">
      {{ errorMsg }}
    </section>

    <section v-if="loading" class="projects-grid" :aria-label="t('common.loading')">
      <article v-for="index in 9" :key="index" class="project-card project-card--skeleton glass-card">
        <div class="h-4 w-2/3 rounded-full bg-stone-200/80" />
        <div class="space-y-2">
          <div class="h-3 w-full rounded-full bg-stone-100" />
          <div class="h-3 w-4/5 rounded-full bg-stone-100" />
          <div class="h-3 w-3/5 rounded-full bg-stone-100" />
        </div>
        <div class="flex flex-wrap gap-2">
          <div class="h-6 w-20 rounded-full bg-stone-100" />
          <div class="h-6 w-16 rounded-full bg-stone-100" />
        </div>
        <div class="mt-auto h-9 rounded-full bg-stone-100" />
      </article>
    </section>

    <section v-else-if="projects.length === 0 && !errorMsg" class="empty-state glass-card">
      <p class="projects-kicker">EMPTY COLLECTION</p>
      <h2>{{ t(searchQuery || hasActiveFilter ? 'projects.emptyMatchTitle' : isWebsiteOnlyView ? 'projects.emptyWebsiteTitle' : source === 'favorites' ? 'projects.emptyFavoritesTitle' : 'projects.emptyLibraryTitle') }}</h2>
      <p>{{ t(searchQuery || hasActiveFilter ? 'projects.emptyMatchHint' : isWebsiteOnlyView ? 'projects.emptyWebsiteHint' : source === 'favorites' ? 'projects.emptyFavoritesHint' : 'projects.emptyLibraryHint') }}</p>
    </section>

    <section v-else class="projects-grid" :aria-label="t('navigation.projects')">
      <ProjectResultCard
        v-for="(repo, index) in projects"
        :key="projectKey(repo)"
        :repo="repo"
        :index="index"
        :is-personal-view="isPersonalView"
        :can-favorite="canFavorite(repo)"
        :can-recommend="canRecommendCard(repo)"
        :can-edit="canEditCard(repo)"
        :show-delete="isPersonalView && isWebsite(repo)"
        :is-logged-in="authStore.isLoggedIn"
        :favorite-busy="favoriteBusyKey === projectKey(repo)"
        :favorite-actions-busy="Boolean(favoriteBusyKey)"
        :recommend-busy="recommendBusyKey === projectKey(repo)"
        :recommend-actions-busy="Boolean(recommendBusyKey)"
        :saving-edit="savingEdit && editTarget?.website_id === repo.website_id"
        :deleting="deletingWebsiteId === repo.website_id"
        :logo-loaded="isWebsiteLogoLoaded(repo)"
        :logo-broken="brokenLogoKeys.has(projectLogoKey(repo))"
        :sort="sort"
        :scope="selectedScope"
        @chip-click="handleChipClick"
        @favorite="toggleFavorite"
        @recommend="recommendProject"
        @edit="openEditDialog"
        @delete="removeToolWebsite"
        @logo-loaded="markWebsiteLogoLoaded"
        @logo-broken="hideBrokenLogo"
      />
    </section>

    <ProjectPagination
      v-if="total > pageSize && !loading"
      v-model:page-jump="pageJump"
      :page="page"
      :total-pages="totalPages"
      :total="total"
      :has-prev="hasPrev"
      :has-next="hasNext"
      @go-page="goPage"
      @jump-to-page="jumpToPage"
    />
    </template>

    <ToolWebsiteAddDialog
      :open="addDialogOpen"
      :active="isViewActive"
      :is-my-collection="isMyCollection"
      :taxonomy="taxonomy"
      :taxonomy-loading="taxonomyLoading"
      :busy="addingTool"
      :error="addToolError"
      @close="closeAddDialog"
      @submit-auto="submitToolWebsite"
      @submit-manual="submitToolWebsite"
    />
    <ToolWebsiteEditDialog
      :open="editDialogOpen"
      :active="isViewActive"
      :target="editTarget"
      :taxonomy="taxonomy"
      :taxonomy-loading="taxonomyLoading"
      :busy="savingEdit"
      :error="editError"
      @close="closeEditDialog"
      @submit="submitEditWebsite"
    />
  </div>
</template>

<style scoped>
.projects-page {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 24px 24px 96px;
  color: var(--projects-accent);
  background: var(--projects-paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.projects-page :deep(.glass-card) {
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  backdrop-filter: none;
}

.projects-hero {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  overflow: hidden;
  margin-bottom: 16px;
  padding: 18px 20px;
}

.projects-hero::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.22;
  background-image:
    linear-gradient(rgb(var(--stone-400-rgb) / 0.09) 1px, transparent 1px),
    linear-gradient(90deg, rgb(var(--stone-400-rgb) / 0.09) 1px, transparent 1px);
  background-size: 28px 28px;
}

.projects-hero__text {
  position: relative;
  z-index: 1;
  max-width: 660px;
}

.projects-kicker {
  margin-bottom: 8px;
  color: var(--projects-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.projects-kicker::before {
  content: '■';
  margin-right: 8px;
  color: var(--projects-acid);
  -webkit-text-stroke: 1px var(--projects-accent);
}

.projects-hero h1,
.empty-state h2,
.projects-login-prompt__copy h2 {
  color: var(--projects-accent);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-weight: 900;
  letter-spacing: -0.055em;
}

.projects-hero h1 {
  font-size: clamp(30px, 4vw, 48px);
  line-height: 1;
}

.projects-hero p:not(.projects-kicker),
.empty-state p:not(.projects-kicker) {
  margin-top: 12px;
  color: rgb(var(--stone-500-rgb));
  font-size: 14px;
  line-height: 1.8;
}

.projects-hero__side {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 12px;
}

.projects-hero__stats {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 300px;
}

.projects-hero__stats span {
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  padding: 8px 12px;
  color: rgb(var(--stone-600-rgb));
  background: var(--projects-paper-light);
  font-size: 12px;
  font-weight: 700;
}

.projects-add-btn {
  display: inline-flex;
  min-height: var(--projects-control-height);
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  padding: 0 16px;
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: transform 160ms ease, box-shadow 160ms ease, opacity 160ms ease, background 160ms ease;
}

.projects-add-btn:hover {
  color: var(--projects-paper-light);
  background: var(--projects-accent);
}

.projects-add-btn span {
  font-size: 16px;
  line-height: 1;
}

.projects-add-btn:disabled {
  cursor: wait;
  opacity: 0.68;
  transform: none;
}

.projects-login-prompt {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 24px;
  min-height: 250px;
  overflow: hidden;
  padding: 34px;
  background: var(--projects-paper-light);
}

.projects-login-prompt::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.52;
  background-image:
    linear-gradient(rgb(var(--stone-400-rgb) / 0.10) 1px, transparent 1px),
    linear-gradient(90deg, rgb(var(--stone-400-rgb) / 0.10) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(90deg, #000, transparent 72%);
}

.projects-login-prompt > * {
  position: relative;
  z-index: 1;
}

.projects-login-prompt__mark {
  display: grid;
  width: 74px;
  height: 74px;
  place-items: center;
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 4px 4px 0 var(--shadow-hard);
}

.projects-login-prompt__mark svg {
  width: 32px;
  height: 32px;
}

.projects-login-prompt__copy {
  max-width: 660px;
}

.projects-login-prompt__copy h2 {
  font-size: clamp(28px, 4vw, 42px);
  line-height: 1.08;
}

.projects-login-prompt__copy > p:not(.projects-kicker) {
  max-width: 620px;
  margin-top: 12px;
  color: rgb(var(--stone-500-rgb));
  font-size: 14px;
  line-height: 1.8;
}

.projects-login-prompt__notes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.projects-login-prompt__notes span {
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  padding: 6px 10px;
  color: rgb(var(--stone-600-rgb));
  background: var(--projects-paper-light);
  font-size: 11px;
  font-weight: 800;
}

.projects-login-prompt__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: var(--projects-control-height);
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  padding: 0 19px;
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
  transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.projects-login-prompt__action:hover {
  color: var(--projects-paper-light);
  background: var(--projects-accent);
}

.projects-login-prompt__action svg {
  width: 16px;
  height: 16px;
}

.projects-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.project-card--skeleton {
  position: relative;
  display: flex;
  min-height: 248px;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
  padding: 22px;
  animation: pulse 1.5s ease-in-out infinite;
}

.project-card--skeleton::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgb(var(--card-rgb) / 0.88), transparent 42%),
    radial-gradient(circle at 14% 0%, rgb(var(--stone-400-rgb) / 0.10), transparent 34%);
  opacity: 0.92;
}

.empty-state {
  padding: 42px;
  text-align: center;
}

.empty-state h2 {
  font-size: 34px;
  line-height: 1;
}

.projects-toast {
  margin: -2px 0 14px;
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 700;
}

.projects-toast--success,
.projects-toast--error {
  color: rgb(var(--stone-700-rgb));
  background: rgb(var(--card-rgb) / 0.82);
  border: 1px solid rgb(var(--stone-400-rgb) / 0.24);
  border-left-width: 3px;
}

.projects-toast--success {
  border-left-color: var(--projects-success);
}

.projects-toast--error {
  border-left-color: var(--projects-error);
}

@media (max-width: 720px) {
  .projects-page {
    padding: 16px 16px 96px;
  }

  .projects-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .projects-hero,
  .projects-login-prompt {
    align-items: flex-start;
    flex-direction: column;
  }

  .projects-hero {
    padding: 18px;
  }

  .projects-login-prompt {
    grid-template-columns: 1fr;
    min-height: 0;
    padding: 26px 22px;
  }

  .projects-login-prompt__mark {
    width: 62px;
    height: 62px;
    border-radius: 22px;
  }

  .projects-login-prompt__action {
    width: 100%;
  }

  .projects-hero__stats {
    justify-content: flex-start;
    max-width: none;
  }

  .projects-hero__side {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .projects-page *, .projects-page *::before, .projects-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
