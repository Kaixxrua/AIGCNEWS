import { computed, ref, type ComputedRef } from 'vue'
import { monitorApi, type MonitorApi } from '../services/monitor/monitorApi'
import {
  createEmptyMcpForm, createMcpForm, createProviderForm, removeMcpServer, replaceMcpServer, upsertMcpServer,
  type McpServerConfig, type SourceKey,
} from '../features/monitor/monitorModel'

interface MonitorPageControllerOptions {
  isAdmin: ComputedRef<boolean>
  api?: MonitorApi
  schedule?: (callback: () => void, delay: number) => unknown
  confirm?: (message: string) => boolean
  now?: () => Date
}

const detail = (error: any) => error?.response?.data?.detail || String(error)

export const useMonitorPageController = ({
  isAdmin,
  api = monitorApi,
  schedule = (callback, delay) => setTimeout(callback, delay),
  confirm = (message) => window.confirm(message),
  now = () => new Date(),
}: MonitorPageControllerOptions) => {
  const tasks = ref<Awaited<ReturnType<MonitorApi['fetchTasks']>>['items']>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(10)
  const schedulerStatus = ref<Awaited<ReturnType<MonitorApi['fetchSchedulerStatus']>> | null>(null)
  const loading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const providerConfig = ref<Awaited<ReturnType<MonitorApi['fetchProviderConfig']>> | null>(null)
  const providerForm = ref(createProviderForm())
  const loadingProviderConfig = ref(false)
  const savingProviderConfig = ref(false)
  const mcpServers = ref<McpServerConfig[]>([])
  const mcpForm = ref(createEmptyMcpForm())
  const loadingMcpServers = ref(false)
  const savingMcpServer = ref(false)
  const testingMcpServerId = ref<number | null>(null)
  const deletingMcpServerId = ref<number | null>(null)
  const syncing = ref(false)
  const generatingBriefing = ref(false)
  const clearingCache = ref(false)
  const today = now().toISOString().slice(0, 10)
  const targetDate = ref(today)
  const maxTargetDate = today
  const ingestingByDate = ref(false)
  const ingestingSource = ref<SourceKey | null>(null)
  const clearing = ref(false)
  const showClearConfirm = ref(false)
  const isTaskRunning = computed(() => tasks.value.length > 0 && tasks.value[0]?.status === 'running')
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const clearMessages = () => { errorMsg.value = ''; successMsg.value = '' }

  const fetchTasks = async () => {
    try {
      const data = await api.fetchTasks(page.value, pageSize.value)
      tasks.value = data.items
      total.value = data.total
    } catch (error) { console.error('Failed to fetch tasks', error) }
  }
  const fetchSchedulerStatus = async () => {
    try { schedulerStatus.value = await api.fetchSchedulerStatus() }
    catch (error) { console.error('Failed to fetch scheduler status', error) }
  }
  const fetchProviderConfig = async () => {
    if (!isAdmin.value) return
    loadingProviderConfig.value = true
    try {
      providerConfig.value = await api.fetchProviderConfig()
      providerForm.value = createProviderForm(providerConfig.value)
    } catch (error) { console.error('Failed to fetch provider config', error) }
    finally { loadingProviderConfig.value = false }
  }
  const fetchMcpServers = async () => {
    if (!isAdmin.value) return
    loadingMcpServers.value = true
    try { mcpServers.value = await api.fetchMcpServers() }
    catch (error) { console.error('Failed to fetch MCP servers', error) }
    finally { loadingMcpServers.value = false }
  }
  const refreshData = async () => {
    loading.value = true
    await Promise.all([fetchTasks(), fetchSchedulerStatus(), fetchProviderConfig(), fetchMcpServers()])
    loading.value = false
  }
  const goPage = async (nextPage: number) => {
    if (nextPage < 1 || nextPage > totalPages.value) return
    page.value = nextPage
    await fetchTasks()
  }
  const saveProviderConfig = async () => {
    if (savingProviderConfig.value) return
    clearMessages(); savingProviderConfig.value = true
    try {
      providerConfig.value = await api.saveProviderConfig(providerForm.value)
      providerForm.value.api_key = ''; providerForm.value.clear_api_key = false
      successMsg.value = '模型服务配置已保存。新建模型实例时会自动使用最新配置。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingProviderConfig.value = false }
  }
  const resetMcpForm = () => { mcpForm.value = createEmptyMcpForm() }
  const editMcpServer = (server: McpServerConfig) => { clearMessages(); mcpForm.value = createMcpForm(server) }
  const saveMcpServer = async () => {
    if (savingMcpServer.value) return
    clearMessages()
    const form = mcpForm.value
    if (!form.server_key.trim()) { errorMsg.value = '请填写 MCP Server 标识。'; return }
    if (!form.display_name.trim()) { errorMsg.value = '请填写 MCP Server 名称。'; return }
    if (!form.url.trim()) { errorMsg.value = '请填写 MCP Server URL。'; return }
    savingMcpServer.value = true
    try {
      mcpServers.value = upsertMcpServer(mcpServers.value, await api.saveMcpServer(form))
      resetMcpForm(); successMsg.value = 'MCP Server 配置已保存。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingMcpServer.value = false }
  }
  const testMcpServer = async (server: McpServerConfig) => {
    if (testingMcpServerId.value) return
    clearMessages()
    if (!server.enabled) { errorMsg.value = '该 MCP Server 已停用，请先启用后再测试。'; return }
    testingMcpServerId.value = server.id
    try {
      const result = await api.testMcpServer(server.id)
      mcpServers.value = replaceMcpServer(mcpServers.value, result.server)
      const message = result.message || 'MCP Server 测试完成。'
      if (String(result.status || '').toLowerCase() === 'success') successMsg.value = message
      else errorMsg.value = message || 'MCP Server 测试失败。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { testingMcpServerId.value = null }
  }
  const deleteMcpServer = async (server: McpServerConfig) => {
    if (deletingMcpServerId.value || !confirm(`确定删除 MCP Server「${server.display_name || server.server_key}」吗？`)) return
    clearMessages(); deletingMcpServerId.value = server.id
    try {
      const result = await api.deleteMcpServer(server.id)
      mcpServers.value = removeMcpServer(mcpServers.value, server.id)
      if (mcpForm.value.id === server.id) resetMcpForm()
      successMsg.value = result.message || 'MCP Server 配置已删除。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { deletingMcpServerId.value = null }
  }
  const delayedRefresh = (secondDelay: number) => { schedule(fetchTasks, 1000); schedule(fetchTasks, secondDelay) }
  const ingestSingleSource = async (source: SourceKey) => {
    if (ingestingSource.value) return
    clearMessages(); ingestingSource.value = source
    try { const result = await api.ingestSource(source); successMsg.value = result.message || `「${source}」采集任务已提交，后台执行中…`; delayedRefresh(4000) }
    catch (error: any) { const status = error?.response?.status; errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? detail(error) || '未知数据源' : detail(error) }
    finally { ingestingSource.value = null }
  }
  const generateAllBriefings = async (forceRegenerate = true) => {
    if (generatingBriefing.value) return
    clearMessages(); generatingBriefing.value = true
    try { const result = await api.generateAllBriefings(forceRegenerate); successMsg.value = result.message || '全维度每日简报生成任务已提交，后台执行中…' }
    catch (error) { errorMsg.value = detail(error) }
    finally { generatingBriefing.value = false }
  }
  const clearDashboardCache = async () => {
    if (clearingCache.value) return
    clearMessages(); clearingCache.value = true
    try { const result = await api.clearDashboardCache(); successMsg.value = result.message || 'Dashboard 缓存已清除，刷新仪表盘即可看到最新数据。' }
    catch (error) { errorMsg.value = detail(error) }
    finally { clearingCache.value = false }
  }
  const syncDataNow = async (force = false) => {
    if (syncing.value || isTaskRunning.value) return
    clearMessages(); syncing.value = true
    try { await api.syncData(force); successMsg.value = force ? '强制采集任务已提交，后台执行中…' : '智能同步任务已提交，后台执行中…'; delayedRefresh(3000) }
    catch (error: any) { errorMsg.value = error?.response?.status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : detail(error) }
    finally { syncing.value = false }
  }
  const ingestByDate = async () => {
    if (ingestingByDate.value) return
    if (!targetDate.value) { errorMsg.value = '请选择目标日期'; return }
    clearMessages(); ingestingByDate.value = true
    try { const result = await api.ingestByDate(targetDate.value); successMsg.value = result.message || `已提交 ${targetDate.value} 的采集任务，后台执行中…`; delayedRefresh(4000) }
    catch (error: any) { const status = error?.response?.status; errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? detail(error) || '日期格式错误' : detail(error) }
    finally { ingestingByDate.value = false }
  }
  const clearAllData = async () => {
    showClearConfirm.value = false; clearMessages(); clearing.value = true
    try { const result = await api.clearAllData(); successMsg.value = result.message || '数据已清空'; await refreshData() }
    catch (error) { errorMsg.value = detail(error) }
    finally { clearing.value = false }
  }

  return {
    tasks, total, page, pageSize, schedulerStatus, loading, errorMsg, successMsg, providerConfig, providerForm,
    loadingProviderConfig, savingProviderConfig, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
    testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing, clearingCache,
    targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm, clearMessages, fetchTasks,
    fetchSchedulerStatus, fetchProviderConfig, fetchMcpServers, refreshData, goPage, saveProviderConfig, resetMcpForm,
    editMcpServer, saveMcpServer, testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings,
    clearDashboardCache, syncDataNow, ingestByDate, clearAllData,
  }
}
