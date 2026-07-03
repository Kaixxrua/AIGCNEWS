<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchGitHubProjectCategories,
  fetchGitHubProjects,
  type GitHubProjectCategory,
  type GitHubProjectItem,
  type GitHubProjectSort,
} from '../services/api'

const categories = ref<GitHubProjectCategory[]>([])
const projects = ref<GitHubProjectItem[]>([])
const selectedCategory = ref('all')
const searchQuery = ref('')
const debouncedQuery = ref('')
const sort = ref<GitHubProjectSort>('stars')
const page = ref(1)
const pageSize = ref(24)
const total = ref(0)
const loading = ref(false)
const categoriesLoading = ref(false)
const errorMsg = ref('')
const currentRequestId = ref(0)
let searchTimer: number | undefined

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const hasPrev = computed(() => page.value > 1)
const hasNext = computed(() => page.value < totalPages.value)
const activeCategory = computed(() => categories.value.find((item) => item.slug === selectedCategory.value))

const repoName = (repo: GitHubProjectItem) => {
  const name = repo.full_name || repo.title || String(repo.repo_id ?? '')
  return name.trim()
}

const repoUrl = (repo: GitHubProjectItem) => {
  if (repo.url) return repo.url
  if (repo.full_name) return `https://github.com/${repo.full_name}`
  return ''
}

const displayTags = (repo: GitHubProjectItem) => {
  const result: string[] = []
  if (repo.category_name) result.push(repo.category_name)
  for (const tag of repo.tags ?? []) {
    const clean = String(tag).trim()
    if (clean && !result.includes(clean)) result.push(clean)
    if (result.length >= 5) break
  }
  if (result.length < 5 && repo.language && !result.includes(repo.language)) {
    result.push(repo.language)
  }
  return result.length ? result : ['AI 项目']
}

const formatCount = (value: GitHubProjectItem['stars']) => {
  const numeric = Number(value ?? 0)
  if (!Number.isFinite(numeric)) return '0'

  return new Intl.NumberFormat('en', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(numeric)
}

const loadCategories = async () => {
  categoriesLoading.value = true
  try {
    const data = await fetchGitHubProjectCategories()
    categories.value = data.items.length ? data.items : [{ slug: 'all', name: '全部', count: 0 }]
  } catch (error) {
    console.error('Failed to load GitHub project categories:', error)
    categories.value = [{ slug: 'all', name: '全部', count: 0 }]
  } finally {
    categoriesLoading.value = false
  }
}

const loadProjects = async () => {
  const requestId = currentRequestId.value + 1
  currentRequestId.value = requestId
  loading.value = true
  errorMsg.value = ''

  try {
    const data = await fetchGitHubProjects({
      category: selectedCategory.value === 'all' ? '' : selectedCategory.value,
      q: debouncedQuery.value.trim(),
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
    })
    if (requestId !== currentRequestId.value) return
    projects.value = data.items
    total.value = data.total
  } catch (error) {
    if (requestId !== currentRequestId.value) return
    console.error('Failed to load GitHub projects:', error)
    errorMsg.value = 'GitHub 项目库暂时加载失败，请稍后重试。'
    projects.value = []
    total.value = 0
  } finally {
    if (requestId === currentRequestId.value) {
      loading.value = false
    }
  }
}

const resetAndLoad = () => {
  page.value = 1
  loadProjects()
}

const selectCategory = (slug: string) => {
  if (selectedCategory.value === slug) return
  selectedCategory.value = slug
}

const goPage = (nextPage: number) => {
  const target = Math.max(1, Math.min(totalPages.value, nextPage))
  if (target === page.value) return
  page.value = target
  loadProjects()
}

watch(searchQuery, (value) => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    debouncedQuery.value = value
  }, 280)
})

watch([selectedCategory, debouncedQuery, sort], resetAndLoad)

onMounted(() => {
  loadCategories()
  loadProjects()
})
</script>

<template>
  <div class="projects-page">
    <section class="projects-hero glass-card">
      <div class="projects-hero__text">
        <p class="projects-kicker">PROJECT COLLECTION</p>
        <h1>GitHub 项目库</h1>
        <p>像收藏夹一样浏览历史数据库中 stars &gt; 500 的 AI 开源项目，已自动分类并生成中文短描述。</p>
      </div>

      <div class="projects-hero__stats" aria-label="项目库统计">
        <span>{{ total }} 个项目</span>
        <span>Stars &gt; 500</span>
        <span>{{ activeCategory?.name || '全部分类' }}</span>
      </div>
    </section>

    <section class="projects-toolbar glass-card">
      <div class="projects-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          v-model="searchQuery"
          class="input"
          type="search"
          placeholder="搜索项目名、中文描述、语言或标签"
        />
      </div>

      <label class="projects-sort">
        <span>排序</span>
        <select v-model="sort">
          <option value="stars">Stars 优先</option>
          <option value="updated">最近更新</option>
          <option value="recent">最近收录</option>
          <option value="name">名称</option>
        </select>
      </label>
    </section>

    <section class="projects-categories" aria-label="项目分类筛选">
      <button
        v-for="category in categories"
        :key="category.slug"
        type="button"
        class="projects-category"
        :class="selectedCategory === category.slug ? 'tab-active' : 'tab-inactive'"
        :disabled="categoriesLoading"
        @click="selectCategory(category.slug)"
      >
        <span>{{ category.name }}</span>
        <small>{{ category.count }}</small>
      </button>
    </section>

    <section v-if="errorMsg" class="glass-card border border-red-200/70 bg-red-50/70 p-5 text-sm text-red-700">
      {{ errorMsg }}
    </section>

    <section v-if="loading" class="projects-grid" aria-label="GitHub 项目加载中">
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
      <h2>{{ searchQuery || selectedCategory !== 'all' ? '没有找到匹配项目' : '项目库正在回填 AI 分类' }}</h2>
      <p>{{ searchQuery || selectedCategory !== 'all' ? '试试清空关键词或切换分类。' : '等后台富化任务生成中文描述和分类后，这里会展示 stars > 500 的历史项目。' }}</p>
    </section>

    <section v-else class="projects-grid" aria-label="GitHub 项目列表">
      <article
        v-for="(repo, index) in projects"
        :key="repo.repo_id ?? repo.full_name ?? index"
        class="project-card glass-card card-hover stagger-enter"
        :style="{ animationDelay: `${Math.min(index, 12) * 36}ms` }"
      >
        <div class="project-card__pin" aria-hidden="true" />

        <header class="project-card__header">
          <h2 :title="repoName(repo)">{{ repoName(repo) }}</h2>
          <a
            v-if="repoUrl(repo)"
            class="project-card__link"
            :href="repoUrl(repo)"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="打开 GitHub 仓库"
          >
            GitHub
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M7 17L17 7" />
              <path d="M9 7h8v8" />
            </svg>
          </a>
        </header>

        <p class="project-card__description">
          {{ repo.description_zh || repo.description || '这个项目暂时没有中文简介。' }}
        </p>

        <div class="project-card__tags" aria-label="分类标签">
          <span
            v-for="tag in displayTags(repo)"
            :key="tag"
            class="badge-default"
          >
            {{ tag }}
          </span>
        </div>

        <footer class="project-card__stats" aria-label="GitHub 指标">
          <span>
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="m12 2.2 2.9 5.88 6.5.94-4.7 4.58 1.1 6.47L12 17.02l-5.8 3.05 1.1-6.47-4.7-4.58 6.5-.94L12 2.2Z" />
            </svg>
            {{ formatCount(repo.stars) }} stars
          </span>
          <span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="6" cy="5" r="2" />
              <circle cx="18" cy="5" r="2" />
              <circle cx="12" cy="19" r="2" />
              <path d="M6 7v3a5 5 0 0 0 5 5h1" />
              <path d="M18 7v3a5 5 0 0 1-5 5h-1" />
              <path d="M12 15v2" />
            </svg>
            {{ formatCount(repo.forks) }} forks
          </span>
        </footer>
      </article>
    </section>

    <nav v-if="total > pageSize && !loading" class="projects-pagination glass-card" aria-label="项目分页">
      <p>第 {{ page }} / {{ totalPages }} 页 · {{ total }} 个项目</p>
      <div>
        <button class="btn-secondary" :disabled="!hasPrev" @click="goPage(page - 1)">上一页</button>
        <button class="btn-secondary" :disabled="!hasNext" @click="goPage(page + 1)">下一页</button>
      </div>
    </nav>
  </div>
</template>

<style scoped>
.projects-page {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 24px 24px 96px;
}

.projects-page::before {
  content: '';
  position: fixed;
  inset: auto 14% 10% auto;
  width: 320px;
  height: 320px;
  pointer-events: none;
  background:
    radial-gradient(circle at 30% 30%, rgba(6, 182, 212, 0.10), transparent 62%),
    radial-gradient(circle at 70% 70%, rgba(68, 64, 60, 0.07), transparent 58%);
  filter: blur(28px);
  opacity: 0.8;
}

.projects-hero {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  overflow: hidden;
  margin-bottom: 16px;
  padding: 26px;
}

.projects-hero::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.46;
  background-image:
    linear-gradient(rgba(168, 162, 158, 0.09) 1px, transparent 1px),
    linear-gradient(90deg, rgba(168, 162, 158, 0.09) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(90deg, transparent, #000 18%, #000 82%, transparent);
}

.projects-hero__text {
  position: relative;
  z-index: 1;
  max-width: 660px;
}

.projects-kicker {
  margin-bottom: 8px;
  color: #0891b2;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.projects-hero h1,
.empty-state h2 {
  font-family: 'Playfair Display', serif;
  color: #292524;
  line-height: 1;
}

.projects-hero h1 {
  font-size: clamp(34px, 5vw, 58px);
  font-weight: 600;
  letter-spacing: -0.04em;
}

.projects-hero p:not(.projects-kicker),
.empty-state p:not(.projects-kicker) {
  margin-top: 12px;
  color: #78716c;
  font-size: 14px;
  line-height: 1.8;
}

.projects-hero__stats {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 280px;
}

.projects-hero__stats span {
  border-radius: 999px;
  padding: 8px 12px;
  color: #57534e;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(168, 162, 158, 0.20);
  font-size: 12px;
  font-weight: 700;
}

.projects-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
  padding: 14px;
}

.projects-search {
  position: relative;
  flex: 1;
}

.projects-search svg {
  position: absolute;
  left: 16px;
  top: 50%;
  z-index: 1;
  width: 17px;
  height: 17px;
  color: #a8a29e;
  transform: translateY(-50%);
}

.projects-search :deep(.input) {
  padding-left: 44px;
}

.projects-sort {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #78716c;
  font-size: 12px;
  font-weight: 700;
}

.projects-sort select {
  border-radius: 999px;
  padding: 10px 34px 10px 14px;
  color: #44403c;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(168, 162, 158, 0.25);
  outline: none;
}

.projects-categories {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
  overflow-x: auto;
  padding-bottom: 3px;
}

.projects-category {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 700;
  transition: all 160ms ease;
}

.projects-category small {
  font-size: 11px;
  opacity: 0.68;
}

.projects-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.project-card {
  position: relative;
  display: flex;
  min-height: 248px;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
  padding: 22px;
}

.project-card::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.88), transparent 42%),
    radial-gradient(circle at 14% 0%, rgba(6, 182, 212, 0.09), transparent 34%);
  opacity: 0.92;
}

.project-card > * {
  position: relative;
  z-index: 1;
}

.project-card__pin {
  position: absolute;
  top: 14px;
  right: 16px;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #06b6d4;
  box-shadow: 0 0 0 5px rgba(6, 182, 212, 0.09);
}

.project-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding-right: 14px;
}

.project-card__header h2 {
  color: #292524;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: -0.02em;
  overflow-wrap: anywhere;
}

.project-card__link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  border-radius: 999px;
  padding: 6px 10px;
  color: #0891b2;
  background: rgba(6, 182, 212, 0.08);
  border: 1px solid rgba(6, 182, 212, 0.18);
  font-size: 12px;
  font-weight: 700;
  transition: all 160ms ease;
}

.project-card__link:hover {
  color: #0e7490;
  background: rgba(6, 182, 212, 0.13);
  transform: translateY(-1px);
}

.project-card__link svg {
  width: 13px;
  height: 13px;
}

.project-card__description {
  display: -webkit-box;
  min-height: 60px;
  overflow: hidden;
  color: #57534e;
  font-size: 14px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.project-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.project-card__stats {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px dashed rgba(168, 162, 158, 0.24);
  color: #78716c;
  font-size: 12px;
  font-weight: 700;
}

.project-card__stats span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.project-card__stats svg {
  width: 14px;
  height: 14px;
  color: #a16207;
}

.project-card--skeleton {
  min-height: 248px;
  animation: pulse 1.5s ease-in-out infinite;
}

.empty-state {
  padding: 42px;
  text-align: center;
}

.empty-state h2 {
  font-size: 34px;
  font-weight: 600;
}

.projects-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding: 14px 16px;
}

.projects-pagination p {
  color: #78716c;
  font-size: 13px;
  font-weight: 700;
}

.projects-pagination div {
  display: flex;
  gap: 8px;
}

@media (max-width: 720px) {
  .projects-page {
    padding: 16px 16px 96px;
  }

  .projects-hero,
  .projects-toolbar,
  .projects-pagination {
    align-items: flex-start;
    flex-direction: column;
  }

  .projects-hero {
    padding: 22px;
  }

  .projects-hero__stats {
    justify-content: flex-start;
    max-width: none;
  }

  .projects-toolbar,
  .projects-search,
  .projects-sort,
  .projects-sort select {
    width: 100%;
  }

  .project-card__header {
    flex-direction: column;
    padding-right: 0;
  }
}
</style>
