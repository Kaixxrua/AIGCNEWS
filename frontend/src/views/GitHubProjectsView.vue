<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, watch, type ComponentPublicInstance } from 'vue'
import { useRoute } from 'vue-router'
import { useIntervalFn, useMediaQuery, useResizeObserver } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
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
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import ProjectResultCard from '@/components/projects/ProjectResultCard.vue'
import ProjectChartRow from '@/components/projects/ProjectChartRow.vue'
import { projectPane, projectPeekCard } from '@/components/projects/desktopParts'
import { listKeysSheet } from '@/components/keyboard/desktopParts'
import ToolWebsiteAddDialog from '@/components/projects/ToolWebsiteAddDialog.vue'
import ToolWebsiteEditDialog from '@/components/projects/ToolWebsiteEditDialog.vue'
import WebsiteCollectionTabs from '@/components/websites/WebsiteCollectionTabs.vue'
import ProjectFiltersPanel from '@/components/projects/ProjectFiltersPanel.vue'
import ProjectPagination from '@/components/projects/ProjectPagination.vue'
import ProjectMcpPromo from '@/components/projects/ProjectMcpPromo.vue'
import McpPromptExampleList from '@/components/mcp/McpPromptExampleList.vue'
import { useProjectCatalogController } from '@/composables/useProjectCatalogController'
import { useProjectMasonry } from '@/composables/useProjectMasonry'
import { defaultProjectScopeForQuery, defaultProjectSortForQuery, useProjectRouteState } from '@/composables/useProjectRouteState'
import { useMcpPromoDismissed } from '@/composables/useMcpPromoDismissed'
import { useProjectTrends } from '@/composables/useProjectTrends'
import { useListKeys } from '@/composables/useListKeys'
import { useProjectPeek, useProjectPeekData } from '@/composables/useProjectPeek'
import { useProjectPane } from '@/composables/useProjectPane'
import { READ_MARKS, useReadMarks } from '@/composables/useReadMarks'
import { MCP_EMPTY_STATE_EXAMPLE_IDS, mcpExamplesByIds } from '@/features/mcp/mcpExamplePrompts'
import {
  canEditWebsiteProject,
  canFavoriteProject,
  canRecommendProject,
  isWebsite,
  projectKey,
  projectLogoKey,
  projectUrl,
  type ProjectChip,
} from '@/features/projects/projectPresentation'
import {
  projectChartRanked,
  projectChartShowsMovement,
  projectRankMovement,
  projectTrendKey,
  type ProjectRankMovement,
} from '@/features/projects/projectChart'
import { preloadWhen } from '@/utils/lazyComponent'
import { vReflow } from '@/motion/reflow'
import { vIndicator } from '@/motion/indicator'
import { slideIn, slideOut } from '@/motion/presence'
import { fold, unfold } from '@/motion/fold'

defineOptions({ name: 'GitHubProjectsView' })
const { locale, t } = useI18n()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
const route = useRoute()
const source = ref<ProjectViewSource>('all')
const selectedScope = ref<ProjectScope>(defaultProjectScopeForQuery('all', ''))
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
// 与 dashboard 统计卡片保持同步：收录/下架会改变项目库总数，页面挂起时
// 数字停留在加载时刻的旧值。视图激活且标签页可见时每 30s 静默刷新
// （preserveContent 不闪 loading），节奏比 dashboard 的 10s 缓——列表
// 查询重于纯计数接口，无需更高频。
const SYNC_POLL_INTERVAL = 30_000
let hasActivatedOnce = false
let searchTimer: number | undefined

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean; scope?: ProjectScope }

const { applyRouteState, currentProjectsRedirect, endStateBatch, isApplyingRouteState, isReplacingRoute, replaceRouteFromState, routeStateMatchesRoute } = useProjectRouteState(route, router, {
  source, selectedScope, selectedCategory, selectedSubcategory, searchQuery, debouncedQuery, selectedLanguage, selectedTag, sort, page,
})

const controller = useProjectCatalogController({
  routeState: { source, selectedScope, selectedCategory, selectedSubcategory, searchQuery, debouncedQuery, selectedLanguage, selectedTag, sort, page },
  t,
  isLoggedIn: () => authStore.isLoggedIn,
  ensureAuth: () => authStore.ensureInitialized(),
  isAdmin: () => authStore.isAdmin,
  currentRedirect: currentProjectsRedirect,
  navigateToLogin: async (redirect) => { requestLogin(redirect) },
  replaceRouteFromState,
})

const {
  addToolError, addingTool, categories, categoriesLoading, deletingWebsiteId, editError, errorMsg,
  favoriteBusyKey, isMyCollection, isPersonalView, isViewActive, lastSuccessfulFetchAt, loadCategories,
  loadProjects, loadTaxonomy, loading, pageSize, personalTags, projects, recommendBusyKey,
  recommendProject, refreshReads, removeToolWebsite, requiresPersonalLogin, savingEdit, successMsg, tagsLoading,
  taxonomy, taxonomyLoading, toggleFavorite, total,
} = controller
const websiteQuota = controller.websiteQuota ?? ref(null)
const websiteQuotaLoading = controller.websiteQuotaLoading ?? ref(false)
// 轮询刷新由 onMounted/onActivated 恢复、stopViewReads 暂停；跳过加载中
// 与后台标签页，避免与用户操作触发的请求叠加。
const { pause: pauseSyncPoll, resume: resumeSyncPoll } = useIntervalFn(() => {
  if (!isViewActive.value || route.name !== 'github-projects' || loading.value) return
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  void refreshReads({ clearSuccess: false, preserveContent: true })
}, SYNC_POLL_INTERVAL, { immediate: false })
const sourceOptions = computed<SourceOption[]>(() => [
  { value: 'all', label: source.value === 'website' ? t('recommendedWebsites.title') : t('projects.source.allLabel'), hint: source.value === 'website' ? t('recommendedWebsites.subtitle') : t('projects.source.allHint') },
  { value: 'website', label: t('projects.source.websiteLabel'), hint: t('projects.source.websiteHint'), authOnly: true },
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
const isWebsiteOnlyView = computed(() => source.value === 'website')
const projectsHeroKicker = computed(() => {
  if (source.value === 'website') return t('projects.heroWebsiteKicker')
  if (source.value === 'favorites') return t('projects.heroFavoritesKicker')
  return t('projects.heroLibraryKicker')
})
const pageEl = ref<HTMLElement | null>(null)
const { masonryColumns, masonryGridTemplate, measureGridContentWidth, startGridMeasure, stopGridMeasure } = useProjectMasonry({
  pageEl, projects, locale, isPersonalView, sort, selectedScope, t,
})
// 卡片 aria-describedby 以 index 拼 tooltip id，分列后仍须全局唯一；
// 同时 index<6 的 logo 走 eager 加载，语义保持全局名次而非列内名次。
const projectOrdinal = computed(() => new Map(projects.value.map((repo, index) => [projectKey(repo), index])))
const ordinalOf = (repo: GitHubProjectItem) => projectOrdinal.value.get(projectKey(repo)) ?? 0
// 网页收藏卡片按全局名次轮换四种强调色（与站长推荐页同序、每 8 张一轮）；分列后 nth-child 只知列内名次，故由此下发。
const WEBSITE_CARD_TONES = ['lime', 'cyan', 'purple', 'orange', 'purple', 'orange', 'lime', 'cyan'] as const
const websiteCardToneClass = (repo: GitHubProjectItem) => `project-card--tone-${WEBSITE_CARD_TONES[ordinalOf(repo) % WEBSITE_CARD_TONES.length]}`
const requiresCatalogLogin = controller.requiresCatalogLogin
const personalLoginCopy = computed(() => requiresCatalogLogin.value
  ? { kicker: t('projects.heroLibraryKicker'), title: t('memberContent.loginContinue'), description: t('memberContent.projectsHint') }
  : isWebsiteOnlyView.value
  ? { kicker: t('projects.loginWebsiteKicker'), title: t('projects.loginWebsiteTitle'), description: t('projects.loginWebsiteDescription') }
  : { kicker: t('projects.loginFavoritesKicker'), title: t('projects.loginFavoritesTitle'), description: t('projects.loginFavoritesDescription') })
const websiteQuotaExhausted = computed(() => websiteQuota.value?.unlimited === false && websiteQuota.value.remaining === 0)
// 普通用户的常态提示为带 VIP 跳转的引导文案；其余状态（加载中/会员不限量/
// 额度耗尽）仍是纯文本，websiteQuotaHint 同时供按钮 title 使用。
const websiteQuotaUpsellActive = computed(() => websiteQuota.value?.unlimited === false && (websiteQuota.value.remaining ?? 0) > 0)
const websiteQuotaHint = computed(() => {
  if (websiteQuotaLoading.value && !websiteQuota.value) return t('projects.websiteQuotaLoading')
  if (!websiteQuota.value) return ''
  if (websiteQuota.value.unlimited) return t('projects.websiteQuotaUnlimited')
  if (websiteQuota.value.remaining === 0) {
    const resetAt = websiteQuota.value.reset_at
      ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(websiteQuota.value.reset_at))
      : ''
    return t('projects.websiteQuotaExhausted', { time: resetAt })
  }
  return `${t('projects.websiteQuotaFreeUpsell')}VIP`
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

// 桌面紧凑版面把公共目录排成一张榜单：一行一个项目，描述写全，右边一排对齐的数字和近两周火花线。
// 舒适版面、手机平板和个人收藏仍是原来的卡片。
const isDesktop = useMediaQuery('(min-width: 1024px)')
// 桌面公共项目库固定使用榜单；全站版面密度不改变目录结构。
const chartLayout = computed(() => isDesktop.value && !isPersonalView.value)
const CHART_DAYS = 14
const chartRanked = computed(() => projectChartRanked(sort.value))
const chartMovement = computed(() => projectChartShowsMovement(selectedScope.value))
const { trends: projectTrends, trendFor } = useProjectTrends(() => (chartLayout.value && projects.value.length
  ? { repoIds: projects.value.map(projectTrendKey).filter(Boolean), ranks: chartMovement.value }
  : null))
// 按热度或星标排时编名次（接着上一页往下数）；按更新、收录时间或名称排时名次没有意义，不编。
const chartPosition = (index: number) => (chartRanked.value ? (page.value - 1) * pageSize.value + index + 1 : null)
// 今日热门对照昨天热榜标升降；行情还没到（或取不到）就先不标，不把每一行都当成新上榜。
const chartMovementFor = (repo: GitHubProjectItem, position: number | null): ProjectRankMovement | null => {
  if (!chartMovement.value || position === null || !projectTrends.value?.previous_date) return null
  const trend = trendFor(projectTrendKey(repo))
  return trend ? projectRankMovement(position, trend.previous_rank ?? null) : null
}
const chartReflowKey = computed(() => projects.value.map(projectKey).join('|'))

const resetAndLoad = () => {
  if (isApplyingRouteState.value) return
  page.value = 1
  void replaceRouteFromState()
  void loadProjects()
}
const resetScopeToAll = () => { selectedScope.value = 'all' }
const changeSource = (nextSource: ProjectViewSource) => {
  if (source.value === 'website' && nextSource === 'all') {
    void router.push('/websites')
    return
  }
  if (source.value === nextSource) return
  isApplyingRouteState.value = true
  source.value = nextSource
  selectedScope.value = defaultProjectScopeForQuery(nextSource, debouncedQuery.value)
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
const { dismissed: mcpPromoDismissed, dismiss: dismissMcpPromo, dismissForWeek: dismissMcpPromoForWeek } = useMcpPromoDismissed()
const mcpEmptyStateExamples = mcpExamplesByIds(MCP_EMPTY_STATE_EXAMPLE_IDS)
// 搜索/筛选无结果时空状态已列出同组 MCP 示例，推广卡让位，避免同屏两份相同示例
const showEmptyStateMcp = computed(() => !requiresPersonalLogin.value && !loading.value && !errorMsg.value && projects.value.length === 0 && (!!searchQuery.value || hasActiveFilter.value))
const showMcpPromo = computed(() => source.value === 'all' && !mcpPromoDismissed.value && !requiresPersonalLogin.value && !showEmptyStateMcp.value)
// 榜单版面的页头只留搜索这一行：大标题收起（报眉已经写着「项目库」，读屏照样念得到），「想用自然语言找项目？」这条
// 横幅收成搜索框右端的一个按钮，首次打开项目页时展开搜索框下的示例与接入方式；× 只收起这一块，「本周不再显示」连按钮一起收走。
// 舒适版面、手机平板仍是原来的标题和可展开的横幅。
const askOpen = ref(true)
const askButton = ref<HTMLButtonElement | null>(null)
// 点开的那一块（ProjectMcpPromo）：放焦点、看焦点在不在里面，都对着它的根元素。
const askPanel = ref<ComponentPublicInstance | null>(null)
const askPanelEl = (): HTMLElement | undefined => askPanel.value?.$el
// 展开后焦点移进这一块（读屏念出它的名字，Tab 接着走示例）；Esc 或 × 收起时焦点回到按钮。
const toggleAsk = () => {
  askOpen.value = !askOpen.value
  if (askOpen.value) void nextTick(() => askPanelEl()?.focus({ preventScroll: true }))
}
const closeAsk = () => {
  askOpen.value = false
  askButton.value?.focus()
}
// 焦点在这一块里时 Esc 先收它；排进榜单的 Esc 链里，一按不会连详情栏一起收掉。
const closeAskFromInside = () => {
  if (!askOpen.value || !askPanelEl()?.contains(document.activeElement)) return false
  closeAsk()
  return true
}
watch([chartLayout, showMcpPromo], ([chart, shown]) => {
  if (!chart || !shown) askOpen.value = false
})
// 只有按钮展开的这一块折叠着出入；原来的横幅照旧直接出现、消失。
const isAskPanel = (el: Element) => el.classList.contains('projects-mcp-promo--panel')
const promoEnter = (el: Element, done: () => void) => (isAskPanel(el) ? unfold(el, done) : done())
const promoLeave = (el: Element, done: () => void) => (isAskPanel(el) ? fold(el, done) : done())
// 复刻 handleChipClick 末尾分支：双赋值跳过 280ms 防抖，立即触发站内搜索演示
const runMcpExampleDemo = (query: string) => {
  if (source.value !== 'all') return
  page.value = 1
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  searchQuery.value = query
  debouncedQuery.value = query
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

// 榜单的键盘流与已读淡化，和简报条目、推文墙同一套键位：j / k 在各行之间走，到一页头尾接着翻页；o 在新标签页打开仓库，
// s 收藏（没登录先请登录），x 展开或收起这一行的全部标签。打开过的项目（点项目名、外链图标或按 o）像访问过的链接一样
// 立刻变淡，记在本机，下次进来还是淡的；光是扫过不算，名次天天在变，看过一眼的行不该都淡下去。
const chartRowsEl = ref<HTMLElement | null>(null)
const readMarks = useReadMarks({ list: 'projects', enabled: chartLayout })
// 加载新的一页时榜单先撤下，这时不接键，翻页落下的光标等新的一页画出来再落。
const chartKeys = computed(() => (chartLayout.value && !loading.value ? projects.value.map(projectKey) : []))
const chartRepo = (key: string) => projects.value.find((repo) => projectKey(repo) === key)
const chartRowEl = (key: string) => Array.from(chartRowsEl.value?.querySelectorAll<HTMLElement>('[data-list-key]') ?? []).find((el) => el.dataset.listKey === key)
const visitRepo = (repo: GitHubProjectItem) => readMarks.markOpened(projectKey(repo))
// 哪几行展开了全部标签记在列表上，x 才能替光标那一行开合；换了一批项目时丢掉不在这一批里的。
const openTagRows = ref<ReadonlySet<string>>(new Set())
const setRowTags = (key: string, open: boolean) => {
  const next = new Set(openTagRows.value)
  if (open) next.add(key)
  else next.delete(key)
  openTagRows.value = next
}
watch(chartKeys, (keys) => {
  if (!openTagRows.value.size) return
  const kept = keys.filter((key) => openTagRows.value.has(key))
  if (kept.length !== openTagRows.value.size) openTagRows.value = new Set(kept)
})
// 榜单悬停速览：鼠标在一行上停稳半秒，这一行下面（下面放不下就上面）浮出 README 开头几段、最近一次提交和近 30 天的
// 星标曲线，不用离开列表；卡片开着时这一行留着底色，Esc 先收卡片。网页收藏没有速览。
const chartEl = ref<HTMLElement | null>(null)
const chartRepoId = (key: string) => {
  const repo = chartRepo(key)
  return repo ? projectTrendKey(repo) : ''
}
// README、提交和星标曲线由速览卡片和宽屏详情栏共用一份，在一边看过的换到另一边不再取。
const peekData = useProjectPeekData({ keys: chartKeys, repoOf: chartRepoId })

// 宽屏（1600px 以上）的详情栏：点项目名或行里空白处不跳页，详情在右侧打开，列表留在左边；j / k（或栏里的上一个、下一个）
// 接着看，走到一页头尾接着翻页；o 先打开详情，详情已经是这一行时再按才去 GitHub；Esc 收起。详情栏开着时不再浮速览卡片。
// 在详情栏里停了一秒算扫过（下次进来变淡），去 GitHub 才立刻变淡。
const isWide = useMediaQuery('(min-width: 1600px)')
const paneAvailable = computed(() => isWide.value && chartLayout.value)
const pane = useProjectPane({ available: paneAvailable, keys: chartKeys, pending: loading, repoOf: chartRepoId, data: peekData })
const { target: paneTarget, content: paneContent, curve: paneCurve, direction: paneDirection } = pane
const openPane = (repo: GitHubProjectItem) => pane.open(projectKey(repo))
// 速览卡片与快捷键表只在桌面榜单上出现，详情栏只在宽屏，都单独成包（见各自的 desktopParts.ts），手机不下载；
// 到了用得上的宽度先取回来，要出现时不用等。
const ProjectPeekCard = projectPeekCard.component
const ProjectPane = projectPane.component
const ListKeysSheet = listKeysSheet.component
preloadWhen(chartLayout, projectPeekCard.preload, listKeysSheet.preload)
preloadWhen(paneAvailable, projectPane.preload)
// 换页时榜单先撤下：详情栏留着正在看的项目，等新的一页取到再换。
const paneRepo = shallowRef<GitHubProjectItem | null>(null)
watch([paneTarget, projects], ([target]) => {
  if (!target) paneRepo.value = null
  else paneRepo.value = chartRepo(target.key) ?? paneRepo.value
}, { immediate: true })
// 在整个结果里排第几：接着上一页往下数
const panePosition = computed(() => (pane.index.value < 0 ? null : (page.value - 1) * pageSize.value + pane.index.value + 1))
// 栏里的上一个、下一个：走到这一页头尾时翻页，新的一页取到后接着看它的第一个（往前翻是最后一个）
const stepPane = (direction: 1 | -1) => {
  if (pane.step(direction)) return
  const next = page.value + direction
  if (next < 1 || next > totalPages.value) return
  pane.expectFlip(direction)
  goPage(next)
}
// 详情栏开着时榜单让出右边一栏；栏高跟着页面的可视高度。
const paneShown = ref(false)
watch(paneTarget, (target) => {
  if (target) paneShown.value = true
}, { flush: 'sync' })
const pageHeight = ref(0)
useResizeObserver(pageEl, (entries) => {
  const entry = entries[0]
  if (entry) pageHeight.value = entry.borderBoxSize?.[0]?.blockSize ?? (entry.target as HTMLElement).offsetHeight
})
const paneStyle = computed(() => (pageHeight.value ? { '--projects-view-h': `${Math.round(pageHeight.value)}px` } : undefined))
// 详情从右边推进来、退回去；窗口窄到放不下时直接收，减少动态时直接出现、消失。
// 收起时先按此刻的位置和高度钉住（这一栏不按内容撑高，出了网格就没有自己的高），再撤出网格，榜单当即放宽。
const paneEnter = (el: Element, done: () => void) => slideIn(el, done, { x: 28 })
const paneLeave = (el: Element, done: () => void) => {
  if (paneAvailable.value) {
    const node = el as HTMLElement
    node.style.height = `${node.offsetHeight}px`
    slideOut(el, done, { x: 28 })
    node.style.gridArea = 'auto'
  } else {
    done()
  }
  paneShown.value = false
}
// 榜单让出、收回右边一栏时各行重新折行：正在看（收起时是刚才看）的那一行留在原来的高度，不被挤走。
// 页面还在顶上时跟浏览器的滚动锚定一样不跟：标题和搜索框留在原处，那一行被挤出视野时由光标滚回来。
let paneAnchor: string | null = null
watch(paneShown, () => {
  const scroller = pageEl.value
  const key = paneTarget.value?.key ?? paneAnchor
  const row = key ? chartRowEl(key) : undefined
  if (!scroller || !row || scroller.scrollTop === 0) return
  const top = row.getBoundingClientRect().top
  void nextTick(() => {
    if (row.isConnected) scroller.scrollTop += row.getBoundingClientRect().top - top
  })
})
// 停在一个项目上一秒算扫过它
let paneDwell: ReturnType<typeof setTimeout> | undefined
watch(() => paneTarget.value?.key, (key) => {
  if (key) paneAnchor = key
  clearTimeout(paneDwell)
  paneDwell = key ? setTimeout(() => readMarks.markSeen(key), READ_MARKS.dwellMs) : undefined
})
onBeforeUnmount(() => clearTimeout(paneDwell))

const peek = useProjectPeek({
  enabled: computed(() => chartLayout.value && !paneTarget.value),
  frame: chartEl,
  rows: chartRowsEl,
  keys: chartKeys,
  repoOf: chartRepoId,
  data: peekData,
})
const { target: peekTarget, placement: peekPlace, content: peekContent, curve: peekStars } = peek
const peekRepo = computed(() => (peekTarget.value ? chartRepo(peekTarget.value.key) ?? null : null))
// 卡片从行那边探出来：摆在行下面的往下落，摆在行上面的往上升，收起时原路退回；减少动态时直接出现、消失。
const peekSlide = (el: Element) => ({ y: el.classList.contains('project-peek--above') ? 8 : -8 })
const peekEnter = (el: Element, done: () => void) => slideIn(el, done, peekSlide(el))
const peekLeave = (el: Element, done: () => void) => slideOut(el, done, peekSlide(el))

const listKeys = useListKeys({
  enabled: chartLayout,
  root: chartRowsEl,
  keys: chartKeys,
  open: (key) => {
    if (paneTarget.value?.key !== key && pane.open(key)) return
    const repo = chartRepo(key)
    const url = repo ? projectUrl(repo) : ''
    if (!repo || !url) return
    window.open(url, '_blank', 'noopener')
    visitRepo(repo)
  },
  save: (key) => {
    const repo = chartRepo(key)
    if (repo) void toggleFavorite(repo)
  },
  // 标签不多于榜单先摆出的几个时没有可开合的，不动。
  toggle: (key) => {
    if (chartRowEl(key)?.querySelector('.project-row__chip--more')) setRowTags(key, !openTagRows.value.has(key))
  },
  // 详情栏开着时跟着光标换项目
  reached: (key) => {
    if (paneTarget.value && paneTarget.value.key !== key) pane.open(key)
  },
  escape: () => closeAskFromInside() || pane.close() || peek.close(),
  edge: (direction) => {
    const next = page.value + direction
    if (next < 1 || next > totalPages.value) return false
    pane.expectFlip(direction)
    goPage(next)
    return true
  },
})
const { help: keysHelp, isCursor } = listKeys
// 光标跟着详情栏换项目（点了别的行、用栏里的按钮换）；在栏里按 Esc 或 × 收起时焦点回到那一行，接着用键盘往下读。
watch(() => paneTarget.value?.key, (key, previous) => {
  if (key) {
    if (listKeys.cursor.value !== key) listKeys.setCursor(key, { reveal: true })
  } else if (previous && document.activeElement?.closest('[data-project-pane]')) {
    listKeys.setCursor(previous)
    listKeys.focusCursor()
  }
})

watch(searchQuery, (value) => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    // 搜索意图面向全库：从今日暴涨落地页发起搜索时退出 today 限定
    if (value.trim() && selectedScope.value === 'today') selectedScope.value = 'all'
    debouncedQuery.value = value
  }, 280)
})
watch(debouncedQuery, (value) => {
  if (!sortIsExplicit.value) {
    sort.value = defaultProjectSortForQuery(selectedScope.value, source.value, value)
  }
})

const goToPersonalLogin = () => { requestLogin(currentProjectsRedirect()) }
const openAddDialog = () => {
  if (!authStore.isLoggedIn) { requestLogin('/projects?source=website'); return }
  addToolError.value = ''
  addDialogOpen.value = true
  void Promise.all([loadTaxonomy(), controller.loadWebsiteQuota?.()])
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
// 网页收藏与其余视图的漫画皮肤列宽不同，而切换来源不改页面宽度、ResizeObserver 不会触发：挂上类名后重量一次。
watch(isWebsiteOnlyView, () => { void nextTick(measureGridContentWidth) })
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
    if (authStore.logoutInProgress) return
    if (isPersonalView.value) { addDialogOpen.value = false; editDialogOpen.value = false; editTarget.value = null; return }
  }
  void refreshReads()
}, { flush: 'sync' })
const stopViewReads = () => {
  pauseSyncPoll()
  stopGridMeasure()
  if (searchTimer) { window.clearTimeout(searchTimer); searchTimer = undefined }
  controller.deactivate()
}
onMounted(() => {
  resumeSyncPoll()
  startGridMeasure()
  const hadSort = Boolean(String(route.query.sort ?? '').trim())
  if (applyRouteState()) {
    sortIsExplicit.value = hadSort
    void refreshReads()
  }
})
onActivated(() => {
  resumeSyncPoll()
  startGridMeasure()
  controller.activate()
  if (!hasActivatedOnce) { hasActivatedOnce = true; return }
  // KeepAlive 以 route.path 为 key 复用本实例：挂起期间路由被切走
  // （如 报告页 → 我的网页 /projects?source=website），route.query
  // watcher 在激活前触发被 isViewActive 拦截，须在这里补应用路由状态，
  // 否则 URL 已是新查询而列表仍停留在旧 source 的内容。
  if (route.name === 'github-projects' && !isReplacingRoute.value && !routeStateMatchesRoute()) {
    const hadSort = Boolean(String(route.query.sort ?? '').trim())
    if (applyRouteState()) {
      sortIsExplicit.value = hadSort
      void refreshReads()
      return
    }
  }
  if (searchQuery.value !== debouncedQuery.value) searchTimer = window.setTimeout(() => { debouncedQuery.value = searchQuery.value }, 280)
  if (Date.now() - lastSuccessfulFetchAt.value >= VIEW_REFRESH_INTERVAL) {
    void refreshReads({ clearSuccess: false, preserveContent: true })
  }
})
onDeactivated(stopViewReads)
onBeforeUnmount(stopViewReads)
</script>

<template>
  <div ref="pageEl" class="projects-page" :class="{ 'projects-page--catalog': !isPersonalView, 'projects-page--websites': isWebsiteOnlyView, 'has-pane': paneShown }" :style="paneStyle">
    <section class="projects-hero glass-card" :class="{ 'projects-hero--website': isWebsiteOnlyView, 'projects-hero--quiet': chartLayout }">
      <div class="projects-hero__text">
        <p class="projects-kicker">{{ projectsHeroKicker }}</p>
        <h1 :class="{ 'comic-title': isWebsiteOnlyView }">{{ isWebsiteOnlyView ? t('projects.heroWebsiteKicker') : t('projects.pageTitle') }}</h1>
        <p v-if="!isPersonalView" class="projects-hero__lead">{{ t('projects.heroLibraryLead') }}</p>
        <p v-else-if="isWebsiteOnlyView" class="projects-hero__lead">{{ t('projects.heroWebsiteLead') }}</p>
      </div>

      <div v-if="isWebsiteOnlyView && !requiresPersonalLogin" class="projects-hero__side">
        <div class="projects-website-add">
          <span v-if="websiteQuotaHint" class="projects-website-add__quota">
            <template v-if="websiteQuotaUpsellActive">
              {{ t('projects.websiteQuotaFreeUpsell') }}
              <RouterLink to="/membership" class="projects-website-add__vip">VIP</RouterLink>
            </template>
            <template v-else>{{ websiteQuotaHint }}</template>
          </span>
          <button
            type="button"
            class="projects-add-btn"
            :title="websiteQuotaHint"
            @click="openAddDialog"
          >
            <span>＋</span>
            {{ t('projects.addWebsite') }}
          </button>
        </div>
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
      :catalog-layout="!isPersonalView"
      @select-language="(value) => value ? handleChipClick({ type: 'language', value, label: value }) : clearLanguageFilter()"
      @update:sort="sortIsExplicit = true"
      @change-source="changeSource"
      @clear-language="clearLanguageFilter"
      @select-scope="selectScope"
      @select-category="selectCategory"
      @select-subcategory="selectSubcategory"
      @select-personal-tag="selectPersonalTag"
      @clear-personal-tag="clearPersonalTag"
    >
      <template v-if="isWebsiteOnlyView" #source-tabs><WebsiteCollectionTabs active="personal" /></template>
      <template v-if="chartLayout && showMcpPromo" #search-end>
        <button
          ref="askButton"
          type="button"
          class="projects-ask"
          :aria-expanded="askOpen"
          :aria-controls="askOpen ? 'projects-ask-panel' : undefined"
          :title="t('projects.mcpPromo.title')"
          @click="toggleAsk"
        >
          <span class="projects-ask__mark" aria-hidden="true">✦</span>
          <span class="projects-ask__label">{{ t('projects.mcpPromo.ask') }}</span>
          <svg class="projects-ask__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
      </template>
    </ProjectFiltersPanel>

    <Transition :css="false" @enter="promoEnter" @leave="promoLeave">
      <ProjectMcpPromo
        v-if="showMcpPromo && (!chartLayout || askOpen)"
        ref="askPanel"
        :panel="chartLayout"
        :can-demo="source === 'all'"
        @demo="runMcpExampleDemo"
        @close="chartLayout ? closeAsk() : dismissMcpPromo()"
        @dismiss-week="dismissMcpPromoForWeek"
      />
    </Transition>

    <section v-if="successMsg && !requiresPersonalLogin" class="projects-toast projects-toast--success glass-card">
      {{ successMsg }}
    </section>

    <section v-if="requiresPersonalLogin || requiresCatalogLogin" class="projects-login-prompt glass-card" aria-labelledby="personal-login-title">
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
        <div v-if="!requiresCatalogLogin" class="projects-login-prompt__notes" :aria-label="t('projects.loginFeatures')">
          <span>{{ t(isWebsiteOnlyView ? 'projects.privateShelf' : 'projects.favoriteSync') }}</span>
          <span>{{ t('projects.tagOrganization') }}</span>
          <span>{{ t('projects.crossDevice') }}</span>
        </div>
      </div>
      <button type="button" class="projects-login-prompt__action" @click="goToPersonalLogin">
        {{ t(requiresCatalogLogin ? 'memberContent.loginContinue' : 'projects.loginAction') }}
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

    <SpinnerLoader v-if="loading" class="min-h-[320px]" :aria-label="t('common.loading')" />

    <section v-else-if="projects.length === 0 && !errorMsg" class="empty-state glass-card">
      <p class="projects-kicker">EMPTY COLLECTION</p>
      <h2>{{ t(searchQuery || hasActiveFilter ? 'projects.emptyMatchTitle' : isWebsiteOnlyView ? 'projects.emptyWebsiteTitle' : source === 'favorites' ? 'projects.emptyFavoritesTitle' : 'projects.emptyLibraryTitle') }}</h2>
      <p>{{ t(searchQuery || hasActiveFilter ? 'projects.emptyMatchHint' : isWebsiteOnlyView ? 'projects.emptyWebsiteHint' : source === 'favorites' ? 'projects.emptyFavoritesHint' : 'projects.emptyLibraryHint') }}</p>
      <div v-if="showEmptyStateMcp" class="empty-state__mcp">
        <p class="empty-state__mcp-lead">{{ t('projects.mcpEmpty.lead') }}</p>
        <McpPromptExampleList
          :examples="mcpEmptyStateExamples"
          :mode="source === 'all' ? 'demo-copy' : 'copy-only'"
          layout="chips"
          @demo="runMcpExampleDemo"
        />
      </div>
    </section>

    <section v-else-if="chartLayout" ref="chartEl" class="project-chart" :class="{ 'project-chart--ranked': chartRanked, 'project-chart--curator': authStore.isAdmin }" :aria-label="t('projectChart.label')">
      <div class="project-chart__head" aria-hidden="true">
        <span v-if="chartRanked" class="project-chart__col project-chart__col--rank">{{ t('projectChart.rank') }}</span>
        <span class="project-chart__col project-chart__col--project">{{ t('projectChart.project') }}</span>
        <span class="project-chart__col project-chart__col--stars">{{ t('projectChart.stars') }}</span>
        <span class="project-chart__col project-chart__col--gain">{{ t('projectChart.gain') }}</span>
        <span class="project-chart__col project-chart__col--spark">{{ t('projectChart.trend', { days: projectTrends?.days ?? CHART_DAYS }) }}</span>
        <span class="project-chart__col project-chart__col--heat">{{ t('projectChart.heat') }}</span>
      </div>
      <ol
        ref="chartRowsEl"
        v-reflow="{ key: chartReflowKey }"
        v-indicator="{ active: '.is-cursor', mark: 'after' }"
        class="project-chart__rows"
        role="list"
      >
        <ProjectChartRow
          v-for="(repo, index) in projects"
          :key="projectKey(repo)"
          :class="{ 'is-cursor': isCursor(projectKey(repo)), 'is-read': readMarks.isRead(projectKey(repo)), 'is-peeked': peekTarget?.key === projectKey(repo), 'is-paned': paneTarget?.key === projectKey(repo) }"
          :aria-current="paneTarget?.key === projectKey(repo) ? 'true' : undefined"
          :data-reflow-key="projectKey(repo)"
          :data-list-key="projectKey(repo)"
          :repo="repo"
          :position="chartPosition(index)"
          :movement="chartMovementFor(repo, chartPosition(index))"
          :trend="trendFor(projectTrendKey(repo))"
          :metric-date="projectTrends?.metric_date ?? ''"
          :days="projectTrends?.days ?? CHART_DAYS"
          :can-favorite="canFavorite(repo)"
          :can-recommend="canRecommendCard(repo)"
          :is-logged-in="authStore.isLoggedIn"
          :favorite-busy="favoriteBusyKey === projectKey(repo)"
          :favorite-actions-busy="Boolean(favoriteBusyKey)"
          :recommend-busy="recommendBusyKey === projectKey(repo)"
          :recommend-actions-busy="Boolean(recommendBusyKey)"
          :tags-open="openTagRows.has(projectKey(repo))"
          :opens-pane="paneAvailable"
          @update:tags-open="setRowTags(projectKey(repo), $event)"
          @chip-click="handleChipClick"
          @favorite="toggleFavorite"
          @recommend="recommendProject"
          @visit="visitRepo"
          @open="openPane"
        />
      </ol>
      <Transition :css="false" @enter="peekEnter" @leave="peekLeave">
        <ProjectPeekCard
          v-if="peekTarget && peekRepo && peekPlace && peekContent && peekStars"
          :key="peekTarget.key"
          :repo="peekRepo"
          :repo-id="peekTarget.repoId"
          :content="peekContent"
          :curve="peekStars"
          :placement="peekPlace"
          @visit="visitRepo"
          @pointerenter="peek.hold()"
          @pointerleave="peek.release()"
        />
      </Transition>
    </section>

    <section v-else class="projects-grid" :aria-label="t('navigation.projects')">
      <div
        v-for="(column, columnIndex) in (isPersonalView ? masonryColumns : [projects])"
        :key="columnIndex"
        class="projects-col"
      >
        <ProjectResultCard
          v-for="repo in column"
          :key="projectKey(repo)"
          :class="isWebsiteOnlyView ? websiteCardToneClass(repo) : undefined"
          :repo="repo"
          :catalog-layout="!isPersonalView"
          :index="ordinalOf(repo)"
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
      </div>
    </section>

    <Transition :css="false" @enter="paneEnter" @leave="paneLeave">
      <ProjectPane
        v-if="paneTarget && paneRepo && paneContent && paneCurve"
        :repo="paneRepo"
        :target="paneTarget"
        :content="paneContent"
        :curve="paneCurve"
        :position="panePosition"
        :total="total"
        :direction="paneDirection"
        :can-favorite="canFavorite(paneRepo)"
        :can-recommend="canRecommendCard(paneRepo)"
        :is-logged-in="authStore.isLoggedIn"
        :favorite-busy="favoriteBusyKey === paneTarget.key"
        :favorite-actions-busy="Boolean(favoriteBusyKey)"
        :recommend-busy="recommendBusyKey === paneTarget.key"
        :recommend-actions-busy="Boolean(recommendBusyKey)"
        @close="pane.close()"
        @step="stepPane"
        @retry="pane.retry()"
        @visit="visitRepo"
        @favorite="toggleFavorite"
        @recommend="recommendProject"
        @chip-click="handleChipClick"
      />
    </Transition>

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

    <ListKeysSheet
      v-if="chartLayout"
      v-model:open="keysHelp"
      :actions="{ open: t(paneAvailable ? 'listKeys.projectPane' : 'listKeys.projectOpen'), save: t('listKeys.projectSave'), toggle: t('listKeys.projectTags') }"
    />
    <ToolWebsiteAddDialog
      :open="addDialogOpen"
      :active="isViewActive"
      :is-my-collection="isMyCollection"
      :taxonomy="taxonomy"
      :taxonomy-loading="taxonomyLoading"
      :busy="addingTool"
      :error="addToolError"
      :quota-hint="websiteQuotaHint"
      :quota-exhausted="websiteQuotaExhausted"
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
  width: 100%;
  min-width: 0;
  max-width: 100%;
  height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 16px 24px 24px;
  color: var(--projects-accent);
  background: var(--projects-paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.projects-page :deep(.glass-card) { border: 1px solid var(--rule); border-radius: var(--module-radius); background: var(--projects-paper-light); box-shadow: none; backdrop-filter: none; }

.projects-hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; padding: 0; border: 0 !important; background: transparent !important; }

.projects-hero::after { display: none; }

/* 目录副标题只在桌面漫画版展示（comic-pages.css）。 */
.projects-hero__lead { display: none; }

.projects-hero__text {
  position: relative;
  z-index: 1;
  max-width: 660px;
}

.projects-kicker {
  margin-bottom: 4px;
  color: var(--projects-accent);
  font-size: 10px;
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

.projects-hero h1 { display: flex; align-items: center; gap: 10px; font-size: var(--text-page); font-weight: 800; letter-spacing: -.03em; line-height: 1.3; }
.projects-hero h1::before { content: ''; display: block; width: 10px; height: 26px; border: 1px solid var(--projects-accent); border-radius: 2px; background: var(--projects-acid); box-shadow: 2px 2px 0 var(--shadow-hard); }

/* 网页收藏视图：h1 直接展示「我的网页收藏」，隐藏重复的小 kicker */
.projects-hero .projects-kicker {
  display: none;
}

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
  gap: 8px;
}

.projects-website-add {
  display: flex;
  align-items: center;
  gap: 10px;
}

.projects-website-add__quota {
  max-width: 220px;
  color: rgb(var(--stone-600-rgb));
  font-size: 11px;
  line-height: 1.35;
  text-align: right;
}

.projects-website-add__vip {
  color: var(--projects-accent);
  font-weight: 800;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.projects-website-add__vip:hover {
  background: var(--projects-acid-soft);
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
  white-space: nowrap;
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


/* MCP 推广块（ProjectMcpPromo）的宽度与配色留在页面上：特异度和上面 .glass-card 那条相同，要在同一份样式表里排在它后面才压得过。 */
.projects-page .projects-mcp-promo { width: 100%; min-width: 0; margin-bottom: 18px; border-color: var(--projects-accent); border-radius: 6px; background: var(--projects-acid-soft); }
/* 榜单版面：横幅收成搜索框右端的按钮，点开的那一块在 ProjectMcpPromo 里。 */
.projects-ask { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 7px 0 9px; border: 1px solid var(--projects-accent); border-radius: 4px; background: var(--projects-acid-soft); color: var(--ink); font-size: 13px; font-weight: 800; line-height: 1; white-space: nowrap; cursor: pointer; }
.projects-ask:is(:hover, [aria-expanded='true']) { background: var(--projects-acid); color: var(--projects-on-acid); }
.projects-ask__mark { font-size: 15px; }
.projects-ask__chevron { width: 14px; height: 14px; flex: 0 0 14px; transition: transform 200ms ease; }
.projects-ask[aria-expanded='true'] .projects-ask__chevron { transform: rotate(180deg); }
/* 搜索框窄到放不下占位文字和整个按钮时（英文 1200px 上下），按钮只留星号和箭头，文字留给读屏，悬停看全称。 */
@container projects-search (max-width: 440px) {
  .projects-ask__label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
}
@container projects-search (max-width: 640px) {
  .projects-ask__label:lang(en) { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
}

.projects-grid {
  position: relative;
  display: grid;
  width: 100%;
  min-width: 0;
  grid-template-columns: v-bind(masonryGridTemplate);
  gap: 12px;
  align-items: start;
}

.projects-col {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
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
    padding: 16px;
  }

  .projects-hero,
  .projects-login-prompt {
    align-items: flex-start;
    flex-direction: column;
  }

  .projects-hero {
    padding: 0;
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

  .projects-hero__side {
    width: 100%;
  }
}

/* 窄屏（375px 基准）：在 720px 断点之上再收窄页边距与卡片间距，
   空状态标题收小避免撑破；h1 已有 clamp(18px,…) 兜底，无需再压 */
@media (max-width: 639px) {
  .projects-page {
    padding: 12px;
  }

  .projects-hero {
    padding: 0;
  }

  .projects-grid,
  .projects-col {
    gap: 10px;
  }

  .projects-login-prompt {
    padding: 14px;
  }

  .empty-state {
    padding: 28px 16px;
  }

  .empty-state h2 {
    font-size: 26px;
  }
}

@media (max-width: 767px) {
  .projects-page .projects-hero { padding: 0; border: 0; background: transparent; box-shadow: none; }
  .projects-hero::after { display: none; }
  .projects-hero h1 { font-size: 22px; line-height: 1.3; }
  .projects-hero .projects-kicker { display: none; }
  .projects-mcp-promo { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .projects-page *, .projects-page *::before, .projects-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>

<style src="@/components/projects/projectCatalog.css"></style>
