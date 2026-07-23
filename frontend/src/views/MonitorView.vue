<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '../services/api'
import { useAuthStore } from '../stores/authStore'
import McpServerConfigPanel from '../components/monitor/McpServerConfigPanel.vue'
import MonitorAdminActionControls from '../components/monitor/MonitorAdminActionControls.vue'
import MonitorIngestionControls from '../components/monitor/MonitorIngestionControls.vue'
import MonitorTaskPanel from '../components/monitor/MonitorTaskPanel.vue'
import ProviderConfigPanel from '../components/monitor/ProviderConfigPanel.vue'
import { useMonitorController } from '../composables/useMonitorController'
import {
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
const errorMsg        = ref('')
const successMsg      = ref('')

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

const {
  syncing,
  generatingBriefing,
  clearingCache,
  targetDate,
  maxTargetDate,
  ingestingByDate,
  ingestingSource,
  clearing,
  showClearConfirm,
  ingestSingleSource,
  generateAllBriefings,
  clearDashboardCache,
  syncDataNow,
  ingestByDate,
  clearAllData,
} = useMonitorController({
  isTaskRunning,
  errorMsg,
  successMsg,
  clearMessages,
  fetchTasks,
  refreshData,
})

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
        <MonitorAdminActionControls
          v-if="authStore.isAdmin"
          v-model:show-clear-confirm="showClearConfirm"
          :syncing="syncing"
          :task-running="isTaskRunning"
          :generating-briefing="generatingBriefing"
          :clearing-cache="clearingCache"
          :clearing="clearing"
          @sync="syncDataNow"
          @generate-briefings="generateAllBriefings"
          @clear-dashboard-cache="clearDashboardCache"
          @clear-all-data="clearAllData"
        />
      </div>
    </div>

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

    <!-- Admin 专属：采集控制 -->
    <MonitorIngestionControls
      v-if="authStore.isAdmin"
      v-model:target-date="targetDate"
      :max-target-date="maxTargetDate"
      :ingesting-by-date="ingestingByDate"
      :ingesting-source="ingestingSource"
      @ingest-by-date="ingestByDate"
      @ingest-source="ingestSingleSource"
    />

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
