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

interface ProviderConfig {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key_configured: boolean
  api_key_masked: string | null
  updated_at: string | null
}

interface McpToolSummary {
  name: string
  description: string
}

interface McpServerConfig {
  id: number
  server_key: string
  display_name: string
  description: string
  url: string
  transport: 'streamable_http' | string
  auth_type: 'none' | 'bearer' | string
  auth_token_configured: boolean
  auth_token_masked: string | null
  enabled: boolean
  last_test_status: string
  last_test_message: string
  last_test_at: string | null
  tools: McpToolSummary[]
  created_at: string | null
  updated_at: string | null
}

interface McpServerForm {
  id: number | null
  server_key: string
  display_name: string
  description: string
  url: string
  auth_type: 'none' | 'bearer'
  auth_token: string
  clear_auth_token: boolean
  enabled: boolean
}

const providerConfig = ref<ProviderConfig | null>(null)
const providerForm = ref({
  provider: 'openai' as 'openai' | 'anthropic',
  base_url: '',
  model_name: '',
  api_key: '',
  clear_api_key: false,
})
const loadingProviderConfig = ref(false)
const savingProviderConfig = ref(false)

const createEmptyMcpForm = (): McpServerForm => ({
  id: null,
  server_key: '',
  display_name: '',
  description: '',
  url: '',
  auth_type: 'none',
  auth_token: '',
  clear_auth_token: false,
  enabled: true,
})

const mcpServers = ref<McpServerConfig[]>([])
const mcpForm = ref<McpServerForm>(createEmptyMcpForm())
const loadingMcpServers = ref(false)
const savingMcpServer = ref(false)
const testingMcpServerId = ref<number | null>(null)
const deletingMcpServerId = ref<number | null>(null)
const mcpFormMode = computed(() => (mcpForm.value.id ? 'edit' : 'create'))

const MCP_TEST_SCOPE = [
  { title: 'initialize', description: '协商协议版本与客户端信息' },
  { title: 'initialized', description: '发送初始化完成通知' },
  { title: 'tools/list', description: '只读取工具清单，不执行工具' },
]

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

const fetchProviderConfig = async () => {
  if (!authStore.isAdmin) return
  loadingProviderConfig.value = true
  try {
    const res = await api.get('/ops/provider-config')
    providerConfig.value = res.data
    providerForm.value.provider = res.data?.provider || 'openai'
    providerForm.value.base_url = res.data?.base_url || ''
    providerForm.value.model_name = res.data?.model_name || ''
    providerForm.value.api_key = ''
    providerForm.value.clear_api_key = false
  } catch (e) { console.error('Failed to fetch provider config', e) }
  finally { loadingProviderConfig.value = false }
}

const fetchMcpServers = async () => {
  if (!authStore.isAdmin) return
  loadingMcpServers.value = true
  try {
    const res = await api.get('/ops/mcp-servers')
    mcpServers.value = Array.isArray(res.data?.items) ? res.data.items : []
  } catch (e) { console.error('Failed to fetch MCP servers', e) }
  finally { loadingMcpServers.value = false }
}

const saveProviderConfig = async () => {
  if (savingProviderConfig.value) return
  clearMessages()
  savingProviderConfig.value = true
  try {
    const res = await api.put('/ops/provider-config', {
      provider: providerForm.value.provider,
      base_url: providerForm.value.base_url,
      model_name: providerForm.value.model_name,
      api_key: providerForm.value.api_key || null,
      clear_api_key: providerForm.value.clear_api_key,
    })
    providerConfig.value = res.data
    providerForm.value.api_key = ''
    providerForm.value.clear_api_key = false
    successMsg.value = '模型服务配置已保存。新建模型实例时会自动使用最新配置。'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e)
  } finally { savingProviderConfig.value = false }
}

const resetMcpForm = () => {
  mcpForm.value = createEmptyMcpForm()
}

const editMcpServer = (server: McpServerConfig) => {
  clearMessages()
  mcpForm.value = {
    id: server.id,
    server_key: server.server_key,
    display_name: server.display_name,
    description: server.description || '',
    url: server.url,
    auth_type: server.auth_type === 'bearer' ? 'bearer' : 'none',
    auth_token: '',
    clear_auth_token: false,
    enabled: server.enabled,
  }
}

const saveMcpServer = async () => {
  if (savingMcpServer.value) return
  clearMessages()
  const form = mcpForm.value
  if (!form.server_key.trim()) { errorMsg.value = '请填写 MCP Server 标识。'; return }
  if (!form.display_name.trim()) { errorMsg.value = '请填写 MCP Server 名称。'; return }
  if (!form.url.trim()) { errorMsg.value = '请填写 MCP Server URL。'; return }

  savingMcpServer.value = true
  try {
    const payload = {
      server_key: form.server_key,
      display_name: form.display_name,
      description: form.description,
      url: form.url,
      transport: 'streamable_http',
      auth_type: form.auth_type,
      auth_token: form.auth_token || null,
      clear_auth_token: form.clear_auth_token,
      enabled: form.enabled,
    }
    const res = form.id
      ? await api.put(`/ops/mcp-servers/${form.id}`, payload)
      : await api.post('/ops/mcp-servers', payload)
    const saved: McpServerConfig = res.data
    const index = mcpServers.value.findIndex((item) => item.id === saved.id)
    if (index >= 0) mcpServers.value.splice(index, 1, saved)
    else mcpServers.value = [saved, ...mcpServers.value]
    resetMcpForm()
    successMsg.value = 'MCP Server 配置已保存。'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e)
  } finally { savingMcpServer.value = false }
}

const testMcpServer = async (server: McpServerConfig) => {
  if (testingMcpServerId.value) return
  clearMessages()
  if (!server.enabled) {
    errorMsg.value = '该 MCP Server 已停用，请先启用后再测试。'
    return
  }
  testingMcpServerId.value = server.id
  try {
    const res = await api.post(`/ops/mcp-servers/${server.id}/test`, null, { timeout: 30_000 })
    const updated = res.data?.server
    if (updated) {
      const index = mcpServers.value.findIndex((item) => item.id === updated.id)
      if (index >= 0) mcpServers.value.splice(index, 1, updated)
    }
    const status = String(res.data?.status || '').toLowerCase()
    const message = res.data?.message || 'MCP Server 测试完成。'
    if (status === 'success') successMsg.value = message
    else errorMsg.value = message || 'MCP Server 测试失败。'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e)
  } finally { testingMcpServerId.value = null }
}

const deleteMcpServer = async (server: McpServerConfig) => {
  if (deletingMcpServerId.value) return
  const confirmed = window.confirm(`确定删除 MCP Server「${server.display_name || server.server_key}」吗？`)
  if (!confirmed) return
  clearMessages()
  deletingMcpServerId.value = server.id
  try {
    const res = await api.delete(`/ops/mcp-servers/${server.id}`)
    mcpServers.value = mcpServers.value.filter((item) => item.id !== server.id)
    if (mcpForm.value.id === server.id) resetMcpForm()
    successMsg.value = res.data?.message || 'MCP Server 配置已删除。'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || String(e)
  } finally { deletingMcpServerId.value = null }
}

const refreshData = async () => {
  loading.value = true
  await Promise.all([fetchTasks(), fetchSchedulerStatus(), fetchProviderConfig(), fetchMcpServers()])
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
  succeeded: { label: '成功', dot: 'bg-brand-green', bg: 'bg-green-50', text: 'text-green-700' },
  failed:  { label: '失败',   dot: 'bg-brand-rose',   bg: 'bg-rose-50',   text: 'text-rose-600' },
  running: { label: '运行中', dot: 'bg-brand-blue',   bg: 'bg-blue-50',   text: 'text-blue-600' },
  unknown: { label: '未测试', dot: 'bg-stone-300', bg: 'bg-stone-50', text: 'text-stone-500' },
}

const getStatusConfig = (status: string) =>
  STATUS_CONFIG[(status || 'unknown').toLowerCase()] ?? { label: status, dot: 'bg-stone-400', bg: 'bg-stone-50', text: 'text-stone-500' }

const getMcpTransportLabel = (transport: string) => {
  if ((transport || '').toLowerCase() === 'streamable_http') return 'Streamable HTTP'
  return transport || '未知传输'
}

const getMcpAuthLabel = (authType: string) => {
  if ((authType || '').toLowerCase() === 'bearer') return 'Bearer Token'
  return '无需鉴权'
}

const getMcpServerInitial = (server: McpServerConfig) => {
  const value = (server.display_name || server.server_key || 'M').trim()
  return value.slice(0, 1).toUpperCase()
}
</script>

<template>
  <div class="monitor-view flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">

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

    <!-- Admin 专属：模型服务配置 -->
    <div v-if="authStore.isAdmin" class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.08s">
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20"/><path d="M2 12h20"/><circle cx="12" cy="12" r="4"/></svg>
        <h3 class="text-sm font-semibold text-stone-700">模型服务配置</h3>
        <span v-if="providerConfig?.api_key_configured" class="badge bg-green-50 text-green-700 border border-green-100">Key: {{ providerConfig.api_key_masked }}</span>
        <span v-else class="badge bg-stone-50 text-stone-400 border border-stone-200">未配置 Key</span>
        <span v-if="providerConfig?.updated_at" class="ml-auto text-2xs text-stone-400">更新于 {{ formatDate(providerConfig.updated_at) }}</span>
      </div>

      <div class="grid grid-cols-1 gap-3 lg:grid-cols-[150px_minmax(220px,1fr)_minmax(180px,0.8fr)_minmax(220px,1fr)_auto] lg:items-end">
        <label class="block">
          <span class="mb-1 block text-xs text-stone-400">Provider</span>
          <select v-model="providerForm.provider" class="input w-full py-2 text-xs" :disabled="loadingProviderConfig || savingProviderConfig">
            <option value="openai">OpenAI 兼容</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs text-stone-400">Base URL</span>
          <input v-model.trim="providerForm.base_url" type="url" class="input w-full py-2 text-xs" placeholder="https://api.example.com/v1" autocomplete="off" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs text-stone-400">模型</span>
          <input v-model.trim="providerForm.model_name" type="text" class="input w-full py-2 text-xs" placeholder="例如 claude-opus-4-8" autocomplete="off" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs text-stone-400">API Key</span>
          <input v-model="providerForm.api_key" type="password" class="input w-full py-2 text-xs" placeholder="留空则保留当前密钥" autocomplete="new-password" />
        </label>
        <button class="btn-primary justify-center" :disabled="savingProviderConfig || loadingProviderConfig" @click="saveProviderConfig">
          {{ savingProviderConfig ? '保存中…' : '保存配置' }}
        </button>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-stone-400">
        <label class="inline-flex items-center gap-1.5">
          <input v-model="providerForm.clear_api_key" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" />
          清空当前 API Key
        </label>
        <span>本页只保存一套模型配置，每次保存会覆盖上次配置；API Key 不会回显完整密钥。</span>
      </div>
    </div>

    <!-- Admin 专属：MCP Server 配置 -->
    <div v-if="authStore.isAdmin" class="stagger-enter glass-card shrink-0 overflow-hidden p-0" style="animation-delay: 0.1s">
      <div class="relative border-b border-stone-200/60 bg-gradient-to-br from-white/80 via-cyan-50/35 to-stone-50/70 p-5">
        <div class="pointer-events-none absolute right-6 top-4 hidden font-mono text-[52px] font-black leading-none text-cyan-100/70 md:block">MCP</div>
        <div class="relative flex flex-wrap items-start justify-between gap-3">
          <div class="max-w-3xl">
            <div class="flex flex-wrap items-center gap-2">
              <span class="flex h-8 w-8 items-center justify-center rounded-2xl border border-cyan-100 bg-white/80 text-cyan-700 shadow-sm">
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>
              </span>
              <h3 class="text-sm font-semibold text-stone-700">MCP Server 集成</h3>
              <span class="badge border border-stone-200 bg-white/80 text-stone-500">{{ mcpServers.length }} 个配置</span>
              <span class="badge border border-cyan-100 bg-cyan-50 text-cyan-700">Streamable HTTP</span>
            </div>
            <p class="mt-2 text-xs leading-5 text-stone-500">集中保存外部 MCP Server 连接信息，用于后续工具发现与智能工作流接入。当前仅支持 HTTP / Streamable HTTP；测试流程只做握手与工具清单读取，不执行任意工具。</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <span v-for="item in MCP_TEST_SCOPE" :key="item.title" class="rounded-full border border-white/80 bg-white/70 px-3 py-1 text-2xs text-stone-500 shadow-sm">
                <span class="font-mono text-cyan-700">{{ item.title }}</span>
                <span class="ml-1 text-stone-400">{{ item.description }}</span>
              </span>
            </div>
          </div>
          <button class="btn-secondary px-3.5 py-2 text-xs" :disabled="loadingMcpServers" @click="fetchMcpServers">
            <span class="inline-block h-3 w-3 rounded-full border-2 border-stone-200 border-t-stone-500" :class="loadingMcpServers ? 'animate-spin' : ''" />
            刷新 MCP
          </button>
        </div>
      </div>

      <div class="grid gap-4 p-5 xl:grid-cols-[minmax(320px,0.95fr)_minmax(420px,1.25fr)]">
        <div class="rounded-[22px] border border-stone-200/70 bg-white/60 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
          <div class="mb-3 flex items-start justify-between gap-2">
            <div>
              <h4 class="text-xs font-semibold uppercase tracking-widest text-stone-400">{{ mcpFormMode === 'edit' ? '编辑 Server' : '新增 Server' }}</h4>
              <p class="mt-1 text-2xs text-stone-400">Key 会自动按后端规则规范为小写字母、数字、下划线或短横线。</p>
            </div>
            <button v-if="mcpFormMode === 'edit'" class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-400 hover:text-stone-700" @click="resetMcpForm">取消编辑</button>
          </div>
          <div class="space-y-3">
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label class="block">
                <span class="mb-1 block text-xs text-stone-400">标识 Key</span>
                <input v-model.trim="mcpForm.server_key" class="input w-full py-2 text-xs font-mono" placeholder="github" autocomplete="off" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-stone-400">显示名称</span>
                <input v-model.trim="mcpForm.display_name" class="input w-full py-2 text-xs" placeholder="GitHub MCP" autocomplete="off" />
              </label>
            </div>
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">Server URL</span>
              <input v-model.trim="mcpForm.url" type="url" class="input w-full py-2 text-xs font-mono" placeholder="https://example.com/mcp" autocomplete="off" />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs text-stone-400">说明</span>
              <textarea v-model.trim="mcpForm.description" class="input min-h-[82px] rounded-[18px] py-2 text-xs" placeholder="这个 MCP Server 提供哪些工具 / 适合什么场景" />
            </label>
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-[150px_minmax(0,1fr)]">
              <label class="block">
                <span class="mb-1 block text-xs text-stone-400">鉴权方式</span>
                <select v-model="mcpForm.auth_type" class="input w-full py-2 text-xs">
                  <option value="none">无需鉴权</option>
                  <option value="bearer">Bearer Token</option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1 flex items-center justify-between text-xs text-stone-400">
                  <span>Token</span>
                  <span v-if="mcpForm.auth_type === 'bearer'" class="text-2xs text-stone-300">只写入，不回显</span>
                </span>
                <input v-model="mcpForm.auth_token" type="password" class="input w-full py-2 text-xs" :disabled="mcpForm.auth_type === 'none'" placeholder="留空则保留当前 Token" autocomplete="new-password" />
              </label>
            </div>
            <div class="rounded-2xl border border-stone-200/70 bg-stone-50/70 px-3 py-2">
              <div class="flex flex-wrap items-center gap-3 text-xs text-stone-500">
                <label class="inline-flex items-center gap-1.5">
                  <input v-model="mcpForm.enabled" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" />
                  启用此 Server
                </label>
                <label v-if="mcpFormMode === 'edit'" class="inline-flex items-center gap-1.5">
                  <input v-model="mcpForm.clear_auth_token" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="mcpForm.auth_type === 'none'" />
                  清空当前 Token
                </label>
              </div>
              <p class="mt-1 text-2xs text-stone-400">Bearer Token 会以密文形式保存；列表中仅显示脱敏值。</p>
            </div>
            <button class="btn-primary w-full justify-center" :disabled="savingMcpServer" @click="saveMcpServer">
              {{ savingMcpServer ? '保存中…' : mcpFormMode === 'edit' ? '保存 MCP Server' : '新增 MCP Server' }}
            </button>
          </div>
        </div>

        <div class="min-h-[260px] rounded-[22px] border border-stone-200/70 bg-white/45 p-4">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 class="text-xs font-semibold uppercase tracking-widest text-stone-400">Server Registry</h4>
              <p class="mt-1 text-2xs text-stone-400">测试成功后会缓存最多 20 个工具名称与描述。</p>
            </div>
            <span v-if="loadingMcpServers && mcpServers.length" class="inline-flex items-center gap-1 text-2xs text-stone-400">
              <span class="inline-block h-3 w-3 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />同步中
            </span>
          </div>
          <div v-if="loadingMcpServers && !mcpServers.length" class="flex h-full min-h-[180px] items-center justify-center gap-2 text-sm text-stone-400">
            <span class="inline-block h-4 w-4 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />加载 MCP Server…
          </div>
          <div v-else-if="!mcpServers.length" class="flex h-full min-h-[180px] flex-col items-center justify-center rounded-[18px] border border-dashed border-stone-200 bg-white/55 text-center text-sm text-stone-400">
            <p class="font-medium text-stone-500">暂无 MCP Server 配置</p>
            <p class="mt-1 text-xs">添加后可在这里测试连接并查看可用工具。</p>
          </div>
          <div v-else class="space-y-3">
            <div v-for="server in mcpServers" :key="server.id" class="rounded-[20px] border border-stone-200/70 bg-white/75 p-3 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
              <div class="flex flex-wrap items-start gap-3">
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-stone-200 bg-gradient-to-br from-white to-cyan-50 font-serif text-base font-semibold text-cyan-700">
                  {{ getMcpServerInitial(server) }}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <p class="truncate text-sm font-semibold text-stone-700">{{ server.display_name }}</p>
                    <span class="badge border" :class="[getStatusConfig(server.last_test_status).bg, getStatusConfig(server.last_test_status).text]">
                      <span class="status-dot" :class="getStatusConfig(server.last_test_status).dot" />
                      {{ getStatusConfig(server.last_test_status).label }}
                    </span>
                    <span v-if="!server.enabled" class="badge border border-stone-200 bg-stone-50 text-stone-400">已停用</span>
                    <span v-if="server.auth_token_configured" class="badge border border-green-100 bg-green-50 text-green-700">Token: {{ server.auth_token_masked }}</span>
                  </div>
                  <p class="mt-1 truncate font-mono text-2xs text-stone-400">{{ server.server_key }} · {{ server.url }}</p>
                  <div class="mt-2 flex flex-wrap gap-1.5 text-2xs">
                    <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">{{ getMcpTransportLabel(server.transport) }}</span>
                    <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">{{ getMcpAuthLabel(server.auth_type) }}</span>
                    <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-500">工具 {{ server.tools?.length || 0 }}</span>
                    <span v-if="server.last_test_at" class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-stone-400">{{ formatDate(server.last_test_at) }}</span>
                  </div>
                  <p v-if="server.description" class="mt-2 line-clamp-2 text-xs leading-5 text-stone-500">{{ server.description }}</p>
                </div>
                <div class="flex shrink-0 flex-wrap gap-1.5">
                  <button class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-500 hover:bg-stone-50" @click="editMcpServer(server)">编辑</button>
                  <button
                    class="rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="!!testingMcpServerId || !server.enabled"
                    :title="server.enabled ? '执行 initialize / initialized / tools/list' : 'Server 已停用，请先启用后测试'"
                    @click="testMcpServer(server)"
                  >
                    {{ testingMcpServerId === server.id ? '测试中…' : '测试' }}
                  </button>
                  <button class="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50" :disabled="!!deletingMcpServerId" @click="deleteMcpServer(server)">删除</button>
                </div>
              </div>
              <div v-if="server.last_test_message" class="mt-3 rounded-2xl border px-3 py-2 text-xs leading-5" :class="server.last_test_status === 'success' ? 'border-green-100 bg-green-50 text-green-700' : 'border-rose-100 bg-rose-50 text-rose-600'">
                {{ server.last_test_message }}
                <span v-if="server.last_test_at" class="ml-1 opacity-70">· {{ formatDate(server.last_test_at) }}</span>
              </div>
              <div v-if="server.tools?.length" class="mt-3 flex flex-wrap gap-1.5">
                <span v-for="tool in server.tools" :key="`${server.id}-${tool.name}`" class="badge border border-stone-200 bg-stone-50 text-stone-600" :title="tool.description || tool.name">{{ tool.name }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Admin 专属：按日期采集 -->
    <div v-if="authStore.isAdmin" class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.13s">
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
    <div v-if="authStore.isAdmin" class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.16s">
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
            <button class="rounded-full px-2.5 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page <= 1" @click="goPage(1)">«</button>
            <button class="rounded-full px-3 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
            <template v-for="p in totalPages" :key="p">
              <button v-if="Math.abs(p - page) <= 2" class="rounded-full px-3 py-1 text-xs font-medium transition" :class="p === page ? 'bg-accent text-accent-ink border border-ink shadow-sm' : 'text-stone-500 hover:bg-accent-soft hover:text-ink'" @click="goPage(p)">{{ p }}</button>
            </template>
            <button class="rounded-full px-3 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
            <button class="rounded-full px-2.5 py-1 text-xs font-medium text-stone-400 hover:bg-accent-soft disabled:opacity-30 disabled:cursor-not-allowed transition" :disabled="page >= totalPages" @click="goPage(totalPages)">»</button>
          </div>
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
