<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../services/api'
import { useAuthStore } from '../stores/authStore'
import { FileText, GitBranch, Triangle, Rocket, Newspaper, AlertTriangle } from 'lucide-vue-next'

const authStore = useAuthStore()

interface Task {
  id: number
  task_name: string
  status: string
  item_count: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
}

interface SchedulerStatus {
  running: boolean
  job_count: number
  jobs: Array<{ id: string; name: string; next_run_time: string | null }>
}

interface PagedResult {
  items: Task[]
  total: number
  page: number
  page_size: number
}

const tasks           = ref<Task[]>([])
const total           = ref(0)
const page            = ref(1)
const pageSize        = ref(10)
const schedulerStatus = ref<SchedulerStatus | null>(null)
const loading         = ref(false)
const syncing         = ref(false)
const generatingBriefing = ref(false)
const clearingCache      = ref(false)
const errorMsg        = ref('')
const successMsg      = ref('')

const targetDate      = ref<string>(new Date().toISOString().slice(0, 10))
const ingestingByDate = ref(false)

interface SourceItem {
  key: string
  label: string
  icon: any
  color: string
  textColor: string
}

const SOURCE_LIST: SourceItem[] = [
  { key: 'arxiv',       label: 'Arxiv 论文',        icon: FileText,   color: 'bg-white',  textColor: 'text-stone-600' },
  { key: 'github',      label: 'GitHub Trending',   icon: GitBranch,  color: 'bg-white',  textColor: 'text-stone-600' },
  { key: 'hackernews',  label: 'Hacker News',       icon: Triangle,   color: 'bg-white',  textColor: 'text-stone-600' },
  { key: 'producthunt', label: 'Product Hunt',      icon: Rocket,     color: 'bg-white',  textColor: 'text-stone-600' },
  { key: 'news',        label: 'Tech News',         icon: Newspaper,  color: 'bg-white',  textColor: 'text-stone-600' },
]

const ingestingSource = ref<string | null>(null)
const clearing        = ref(false)
const showClearConfirm = ref(false)

const isTaskRunning = computed(() => tasks.value.length > 0 && tasks.value[0]?.status === 'running')
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

const formatDate = (val: string | null | undefined): string => {
  if (!val) return '—'
  const d = new Date(val.endsWith('Z') || val.includes('+') ? val : val + 'Z')
  if (isNaN(d.getTime())) return val
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(d)
}

const formatTime = (val: string | null | undefined): string => {
  if (!val) return '—'
  const d = new Date(val.endsWith('Z') || val.includes('+') ? val : val + 'Z')
  if (isNaN(d.getTime())) return val
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(d)
}

const fetchTasks = async () => {
  try {
    const res = await api.get('/monitor/tasks', { params: { page: page.value, page_size: pageSize.value } })
    const data: PagedResult = res.data
    tasks.value = data.items || []
    total.value = data.total || 0
  } catch (e) { console.error('Failed to fetch tasks', e) }
}

const fetchSchedulerStatus = async () => {
  try {
    const res = await api.get('/ops/scheduler/status')
    schedulerStatus.value = res.data
  } catch (e) { console.error('Failed to fetch scheduler status', e) }
}

const refreshData = async () => {
  loading.value = true
  await Promise.all([fetchTasks(), fetchSchedulerStatus()])
  loading.value = false
}

const goPage = async (p: number) => {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  await fetchTasks()
}

const clearMessages = () => { errorMsg.value = ''; successMsg.value = '' }

const ingestSingleSource = async (sourceKey: string) => {
  if (ingestingSource.value) return
  clearMessages()
  ingestingSource.value = sourceKey
  try {
    const res = await api.post('/ops/ingest-source', null, { params: { source: sourceKey, limit: 20 } })
    successMsg.value = res.data?.message || `「${sourceKey}」采集任务已提交，后台执行中…`
    setTimeout(fetchTasks, 1000); setTimeout(fetchTasks, 4000)
  } catch (e: any) {
    const status = e?.response?.status
    errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? e?.response?.data?.detail || '未知数据源' : e?.response?.data?.detail || String(e)
  } finally { ingestingSource.value = null }
}

const generateAllBriefings = async (forceRegenerate = true) => {
  if (generatingBriefing.value) return
  clearMessages()
  generatingBriefing.value = true
  try {
    const res = await api.post('/ops/briefing/generate-all', null, { params: { force_regenerate: forceRegenerate } })
    successMsg.value = res.data?.message || '全维度每日简报生成任务已提交，后台执行中…'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e)
  } finally { generatingBriefing.value = false }
}

const clearDashboardCache = async () => {
  if (clearingCache.value) return
  clearMessages()
  clearingCache.value = true
  try {
    const res = await api.post('/ops/cache/clear-dashboard')
    successMsg.value = res.data?.message || 'Dashboard 缓存已清除，刷新仪表盘即可看到最新数据。'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e)
  } finally { clearingCache.value = false }
}

const syncDataNow = async (force = false) => {
  if (syncing.value || isTaskRunning.value) return
  clearMessages()
  syncing.value = true
  try {
    await api.post('/ops/ingest', { limit: 20, force })
    successMsg.value = force ? '强制采集任务已提交，后台执行中…' : '智能同步任务已提交，后台执行中…'
    setTimeout(fetchTasks, 1000); setTimeout(fetchTasks, 3000)
  } catch (e: any) {
    const status = e?.response?.status
    errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : e?.response?.data?.detail || String(e)
  } finally { syncing.value = false }
}

const ingestByDate = async () => {
  if (ingestingByDate.value) return
  if (!targetDate.value) { errorMsg.value = '请选择目标日期'; return }
  clearMessages()
  ingestingByDate.value = true
  try {
    const res = await api.post('/ops/ingest-by-date', { target_date: targetDate.value, limit: 30 })
    successMsg.value = res.data?.message || `已提交 ${targetDate.value} 的采集任务，后台执行中…`
    setTimeout(fetchTasks, 1000); setTimeout(fetchTasks, 4000)
  } catch (e: any) {
    const status = e?.response?.status
    errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? e?.response?.data?.detail || '日期格式错误' : e?.response?.data?.detail || String(e)
  } finally { ingestingByDate.value = false }
}

const clearAllData = async () => {
  showClearConfirm.value = false
  clearMessages()
  clearing.value = true
  try {
    const res = await api.post('/ops/clear-data')
    successMsg.value = res.data?.message || '数据已清空'
    await refreshData()
  } catch (e: any) { errorMsg.value = e?.response?.data?.detail || String(e) }
  finally { clearing.value = false }
}

onMounted(refreshData)

const STATUS_CONFIG: Record<string, { label: string; dot: string; bg: string; text: string }> = {
  success: { label: '成功',   dot: 'bg-brand-green',  bg: 'bg-green-50',  text: 'text-green-700' },
  failed:  { label: '失败',   dot: 'bg-brand-rose',   bg: 'bg-rose-50',   text: 'text-rose-600' },
  running: { label: '运行中', dot: 'bg-brand-blue',   bg: 'bg-blue-50',   text: 'text-blue-600' },
}

const getStatusConfig = (status: string) =>
  STATUS_CONFIG[status.toLowerCase()] ?? { label: status, dot: 'bg-stone-400', bg: 'bg-stone-50', text: 'text-stone-500' }
</script>

<template>
  <div class="flex h-full flex-col gap-5 overflow-y-auto p-6 pb-20">

    <!-- 页头 -->
    <div class="stagger-enter flex flex-wrap items-center justify-between gap-3 shrink-0">
      <div>
        <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">运维监控</h1>
        <p class="mt-0.5 text-sm text-stone-400">任务历史 · 调度器状态 · 数据管理</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="btn-secondary" :disabled="loading" @click="refreshData">
          <svg class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <!-- Admin 专属：同步 / 强制同步 / 清空数据 -->
        <template v-if="authStore.isAdmin">
          <button class="btn-primary" :disabled="syncing || isTaskRunning" @click="syncDataNow(false)">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            {{ syncing ? '同步中…' : isTaskRunning ? '任务运行中…' : '立即同步' }}
          </button>
          <button class="btn-secondary" :disabled="syncing || isTaskRunning" @click="syncDataNow(true)">强制同步</button>
          <button class="btn-secondary" :disabled="generatingBriefing" @click="generateAllBriefings(true)">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
            {{ generatingBriefing ? '生成中…' : '生成每日简报' }}
          </button>
          <button class="btn-secondary" :disabled="clearingCache" @click="clearDashboardCache" title="清除仪表盘 Redis 缓存，强制下次请求重新读取数据库">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/></svg>
            {{ clearingCache ? '清除中…' : '刷新仪表盘缓存' }}
          </button>
          <button class="btn-danger" :disabled="clearing" @click="showClearConfirm = true">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
            {{ clearing ? '清空中…' : '清空数据' }}
          </button>
        </template>
      </div>
    </div>

    <!-- 确认清空对话框 -->
    <Transition name="modal">
      <div v-if="showClearConfirm" class="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm" style="background: rgba(0,0,0,0.15)" @click.self="showClearConfirm = false">
        <div class="w-full max-w-sm glass-card p-6 animate-slide-up" style="box-shadow: 0 4px 20px rgba(0,0,0,0.06)">
          <div class="mb-4 flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-rose-50">
              <svg class="h-5 w-5 text-rose-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            </div>
            <h3 class="text-base font-semibold text-stone-800 font-serif">确认清空所有数据</h3>
          </div>
          <div class="mb-4 space-y-1.5 text-sm text-stone-500">
            <p>此操作将永久删除：</p>
            <ul class="ml-2 space-y-1 text-stone-400"><li>· SQLite 中所有文档 &amp; 任务记录</li><li>· Milvus 向量索引数据</li></ul>
          </div>
          <p class="mb-5 rounded-2xl bg-rose-50 px-3 py-2 text-xs font-medium text-rose-600 border border-rose-200 flex items-center gap-1.5">
            <AlertTriangle class="h-3.5 w-3.5 shrink-0" />
            此操作不可逆，清空后无法恢复！
          </p>
          <div class="flex gap-2">
            <button class="btn-secondary flex-1 justify-center" @click="showClearConfirm = false">取消</button>
            <button class="btn-danger flex-1 justify-center" @click="clearAllData">确认清空</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 消息提示 -->
    <div v-if="errorMsg" class="shrink-0 glass-card flex items-center justify-between px-5 py-3 text-sm text-rose-600">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 text-rose-400 hover:text-rose-600 transition" @click="errorMsg = ''">
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div v-if="successMsg" class="shrink-0 glass-card flex items-center justify-between px-5 py-3 text-sm text-green-700">
      <span>{{ successMsg }}</span>
      <button class="ml-3 text-green-400 hover:text-green-600 transition" @click="successMsg = ''">
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>

    <!-- Admin 专属：按日期采集 -->
    <div v-if="authStore.isAdmin" class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
      <div class="flex items-center gap-2 mb-3">
        <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        <h3 class="text-sm font-semibold text-stone-700">按日期采集数据</h3>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <div class="flex items-center gap-2">
          <span class="text-xs text-stone-400 shrink-0">目标日期：</span>
          <input v-model="targetDate" type="date" class="input w-auto py-1.5 text-xs" :max="new Date().toISOString().slice(0, 10)" />
        </div>
        <button class="btn-primary" :disabled="ingestingByDate || !targetDate" @click="ingestByDate">
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          {{ ingestingByDate ? '采集中…' : '开始采集' }}
        </button>
        <p class="text-xs text-stone-400">将采集指定日期的 Arxiv 论文、GitHub 项目、HuggingFace 模型及 AI 新闻</p>
      </div>
    </div>

    <!-- Admin 专属：按数据源独立采集 -->
    <div v-if="authStore.isAdmin" class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.15s">
      <div class="flex items-center gap-2 mb-3">
        <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
        <h3 class="text-sm font-semibold text-stone-700">按数据源采集</h3>
        <span class="ml-auto text-2xs text-stone-400">点击任意源独立触发采集，不影响其他源</span>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="src in SOURCE_LIST"
          :key="src.key"
          class="inline-flex items-center gap-1.5 rounded-2xl px-3.5 py-2 text-xs font-medium transition-all
                 border border-stone-200 hover:border-stone-300 hover:shadow-sm active:scale-[0.97]
                 disabled:opacity-40 disabled:cursor-not-allowed"
          :class="[src.color, src.textColor, ingestingSource === src.key ? 'ring-2 ring-offset-1 ring-stone-400/40' : '']"
          :disabled="!!ingestingSource"
          @click="ingestSingleSource(src.key)"
        >
          <component :is="src.icon" class="h-3.5 w-3.5 shrink-0" />
          <span>{{ src.label }}</span>
          <span v-if="ingestingSource === src.key" class="inline-block h-3 w-3 rounded-full border-2 border-stone-300 border-t-stone-600 animate-spin ml-0.5" />
        </button>
      </div>
    </div>

    <!-- 主内容网格：admin 时三列，普通用户时全宽单列 -->
    <div class="grid grid-cols-1 gap-5 shrink-0" :class="authStore.isAdmin ? 'lg:grid-cols-3' : ''">
      <!-- Admin 专属：调度器状态 -->
      <div v-if="authStore.isAdmin" class="stagger-enter glass-card flex flex-col p-5" style="animation-delay: 0.2s; max-height: 560px;">
              <h3 class="mb-4 shrink-0 text-sm font-semibold text-stone-700">调度器状态</h3>
              <div v-if="schedulerStatus" class="flex flex-col min-h-0 flex-1">
                <div class="mb-4 shrink-0 flex items-center gap-2.5">
                  <span class="status-dot" :class="schedulerStatus.running ? 'bg-brand-green animate-[pulseDot_2s_ease-in-out_infinite]' : 'bg-brand-rose'" />
                  <span class="text-sm font-medium text-stone-700">{{ schedulerStatus.running ? '运行中' : '已停止' }}</span>
                  <span class="ml-auto text-xs text-stone-400">{{ schedulerStatus.job_count }} 个任务</span>
                </div>
                <div class="space-y-2 overflow-y-auto">
                  <div v-for="job in schedulerStatus.jobs" :key="job.id" class="rounded-2xl p-3" style="background: rgba(255,255,255,0.6); border: 1px solid rgba(168,162,158,0.15)">
                    <p class="text-xs font-medium text-stone-600">{{ job.name }}</p>
                    <p class="mt-1 text-2xs text-stone-400">下次：{{ job.next_run_time ? formatDate(job.next_run_time) : '未安排' }}</p>
                  </div>
                </div>
              </div>
        <div v-else-if="loading" class="flex items-center gap-2 text-sm text-stone-400">
          <span class="inline-block h-4 w-4 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />加载中…
        </div>
      </div>

      <!-- 最近任务表格：admin 时占 2/3，普通用户时占全宽 -->
      <div class="stagger-enter glass-card overflow-hidden flex flex-col" :class="authStore.isAdmin ? 'lg:col-span-2' : 'lg:col-span-1'" style="animation-delay: 0.3s">
        <div class="flex items-center justify-between px-5 py-3.5 shrink-0" style="border-bottom: 1px solid rgba(168,162,158,0.15)">
          <h3 class="text-sm font-semibold text-stone-700">最近任务</h3>
          <span class="badge bg-white text-stone-500 border border-stone-200">共 {{ total }} 条</span>
        </div>

        <div class="overflow-x-auto flex-1">
          <table class="min-w-full">
            <thead>
              <tr style="border-bottom: 1px solid rgba(168,162,158,0.15); background: rgba(250,250,249,0.5)">
                <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">ID</th>
                <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">任务名称</th>
                <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">状态</th>
                <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">条数</th>
                <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">开始时间</th>
                <th class="px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-stone-400">结束</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loading && !tasks.length">
                <td colspan="6" class="px-4 py-8 text-center text-sm text-stone-400">
                  <span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />
                </td>
              </tr>
              <tr v-else-if="!tasks.length">
                <td colspan="6" class="px-4 py-8 text-center text-sm text-stone-400">暂无任务记录</td>
              </tr>
              <tr
                v-for="task in tasks"
                :key="task.id"
                class="transition-colors hover:bg-stone-50/50"
                :style="tasks.indexOf(task) % 2 !== 0 ? 'background: rgba(250,250,249,0.4)' : ''"
              >
                <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400 font-mono">#{{ task.id }}</td>
                <td class="px-4 py-3 text-xs font-medium text-stone-700 max-w-[200px] truncate">{{ task.task_name }}</td>
                <td class="whitespace-nowrap px-4 py-3">
                  <div class="flex flex-col gap-1">
                    <span class="badge" :class="[getStatusConfig(task.status).bg, getStatusConfig(task.status).text]">
                      <span class="status-dot shrink-0" :class="getStatusConfig(task.status).dot" />
                      {{ getStatusConfig(task.status).label }}
                    </span>
                    <span v-if="task.error_msg" class="max-w-[180px] truncate text-2xs text-rose-500" :title="task.error_msg">{{ task.error_msg }}</span>
                  </div>
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-500 tabular-nums">{{ task.item_count }}</td>
                <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400">{{ formatDate(task.started_at) }}</td>
                <td class="whitespace-nowrap px-4 py-3 text-xs text-stone-400">
                  <span v-if="task.finished_at">{{ formatTime(task.finished_at) }}</span>
                  <span v-else class="text-stone-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="flex items-center justify-between px-5 py-3 shrink-0" style="border-top: 1px solid rgba(168,162,158,0.15)">
          <p class="text-xs text-stone-400">第 {{ page }} / {{ totalPages }} 页 · {{ total }} 条</p>
          <div class="flex items-center gap-1">
            <button class="rounded-full px-2.5 py-1 text-xs font-medium text-stone-400 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page <= 1" @click="goPage(1)">«</button>
            <button class="rounded-full px-3 py-1 text-xs font-medium text-stone-400 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
            <template v-for="p in totalPages" :key="p">
              <button v-if="Math.abs(p - page) <= 2" class="rounded-full px-3 py-1 text-xs font-medium transition" :class="p === page ? 'bg-stone-700 text-white shadow-sm' : 'text-stone-400 hover:bg-stone-100'" @click="goPage(p)">{{ p }}</button>
            </template>
            <button class="rounded-full px-3 py-1 text-xs font-medium text-stone-400 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
            <button class="rounded-full px-2.5 py-1 text-xs font-medium text-stone-400 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page >= totalPages" @click="goPage(totalPages)">»</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
