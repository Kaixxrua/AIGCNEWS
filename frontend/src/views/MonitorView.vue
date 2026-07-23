<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../services/api'
import { useAuthStore } from '../stores/authStore'
import { AlertTriangle } from 'lucide-vue-next'
import McpServerConfigPanel from '../components/monitor/McpServerConfigPanel.vue'
import MonitorTaskPanel from '../components/monitor/MonitorTaskPanel.vue'
import ProviderConfigPanel from '../components/monitor/ProviderConfigPanel.vue'
import {
  SOURCE_LIST,
  createEmptyMcpForm,
  type McpServerConfig,
  type McpServerForm,
  type PagedResult,
  type ProviderConfig,
  type ProviderForm,
  type SchedulerStatus,
  type Task,
} from '../features/monitor/monitorViewModel'

const authStore = useAuthStore()

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

const providerConfig = ref<ProviderConfig | null>(null)
const providerForm = ref<ProviderForm>({
  provider: 'openai' as 'openai' | 'anthropic',
  base_url: '',
  model_name: '',
  api_key: '',
  clear_api_key: false,
})
const loadingProviderConfig = ref(false)
const savingProviderConfig = ref(false)

const mcpServers = ref<McpServerConfig[]>([])
const mcpForm = ref<McpServerForm>(createEmptyMcpForm())
const loadingMcpServers = ref(false)
const savingMcpServer = ref(false)
const testingMcpServerId = ref<number | null>(null)
const deletingMcpServerId = ref<number | null>(null)

const ingestingSource = ref<string | null>(null)
const clearing        = ref(false)
const showClearConfirm = ref(false)

const isTaskRunning = computed(() => tasks.value.length > 0 && tasks.value[0]?.status === 'running')
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

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
    <ProviderConfigPanel
      v-if="authStore.isAdmin"
      :config="providerConfig"
      :form="providerForm"
      :loading="loadingProviderConfig"
      :saving="savingProviderConfig"
      @save="saveProviderConfig"
    />

    <!-- Admin 专属：MCP Server 配置 -->
    <McpServerConfigPanel
      v-if="authStore.isAdmin"
      v-model:form="mcpForm"
      :servers="mcpServers"
      :loading="loadingMcpServers"
      :saving="savingMcpServer"
      :testing-server-id="testingMcpServerId"
      :deleting-server-id="deletingMcpServerId"
      @refresh="fetchMcpServers"
      @reset="resetMcpForm"
      @edit="editMcpServer"
      @save="saveMcpServer"
      @test="testMcpServer"
      @delete="deleteMcpServer"
    />

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

    <MonitorTaskPanel
      :is-admin="authStore.isAdmin"
      :scheduler-status="schedulerStatus"
      :tasks="tasks"
      :total="total"
      :page="page"
      :total-pages="totalPages"
      :loading="loading"
      @go-page="goPage"
    />
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
