import { computed } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MonitorApi } from '../services/monitor/monitorApi'
import { useMonitorPageController } from './useMonitorPageController'

const createApi = (): MonitorApi => ({
  fetchTasks: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 10 })),
  fetchSchedulerStatus: vi.fn(async () => ({ running: false, job_count: 0, jobs: [] })),
  fetchProviderConfig: vi.fn(), saveProviderConfig: vi.fn(), fetchMcpServers: vi.fn(async () => []),
  saveMcpServer: vi.fn(), testMcpServer: vi.fn(), deleteMcpServer: vi.fn(), ingestSource: vi.fn(),
  generateAllBriefings: vi.fn(), clearDashboardCache: vi.fn(), syncData: vi.fn(), ingestByDate: vi.fn(), clearAllData: vi.fn(),
})

const createController = (api = createApi(), isAdmin = true) => {
  const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
  const controller = useMonitorPageController({ isAdmin: computed(() => isAdmin), api, schedule, confirm: () => true })
  return { api, schedule, controller }
}

describe('Monitor page controller contract', () => {
  beforeEach(() => vi.useFakeTimers())

  it('does not request provider or MCP configuration for non-admin users', async () => {
    const { api, controller } = createController(createApi(), false)
    await controller.refreshData()
    expect(api.fetchTasks).toHaveBeenCalledWith(1, 10)
    expect(api.fetchSchedulerStatus).toHaveBeenCalledOnce()
    expect(api.fetchProviderConfig).not.toHaveBeenCalled()
    expect(api.fetchMcpServers).not.toHaveBeenCalled()
  })

  it('preserves source/date ingestion payload delegation and delayed refreshes', async () => {
    const { api, controller } = createController()
    vi.mocked(api.ingestSource).mockResolvedValue({})
    vi.mocked(api.ingestByDate).mockResolvedValue({})
    await controller.ingestSingleSource('github')
    expect(api.ingestSource).toHaveBeenCalledWith('github')
    expect(controller.successMsg.value).toContain('github')
    await vi.advanceTimersByTimeAsync(999)
    expect(api.fetchTasks).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(api.fetchTasks).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(api.fetchTasks).toHaveBeenCalledTimes(2)
    controller.targetDate.value = '2026-07-20'
    await controller.ingestByDate()
    expect(api.ingestByDate).toHaveBeenCalledWith('2026-07-20')
  })

  it('preserves normal/forced sync guards, messages, and refresh timing', async () => {
    const { api, controller } = createController()
    vi.mocked(api.syncData).mockResolvedValue({})
    await controller.syncDataNow(false)
    expect(api.syncData).toHaveBeenCalledWith(false)
    expect(controller.successMsg.value).toBe('智能同步任务已提交，后台执行中…')
    await vi.advanceTimersByTimeAsync(3000)
    expect(api.fetchTasks).toHaveBeenCalledTimes(2)
    await controller.syncDataNow(true)
    expect(api.syncData).toHaveBeenLastCalledWith(true)
    expect(controller.successMsg.value).toBe('强制采集任务已提交，后台执行中…')
    controller.tasks.value = [{ id: 1, task_name: 'running', status: 'running', item_count: 0, error_msg: null, started_at: null, finished_at: null }]
    await controller.syncDataNow()
    expect(api.syncData).toHaveBeenCalledTimes(2)
  })

  it('preserves error mapping, validation, loading reset, and destructive refresh order', async () => {
    const { api, controller } = createController()
    vi.mocked(api.ingestSource).mockRejectedValue({ response: { status: 409 } })
    await controller.ingestSingleSource('arxiv')
    expect(controller.errorMsg.value).toBe('当前已有任务正在运行，请等待完成后再试。')
    expect(controller.ingestingSource.value).toBeNull()
    controller.targetDate.value = ''
    await controller.ingestByDate()
    expect(controller.errorMsg.value).toBe('请选择目标日期')

    let resolve!: (value: { message: string }) => void
    vi.mocked(api.clearAllData).mockReturnValue(new Promise((done) => { resolve = done }))
    controller.showClearConfirm.value = true
    const pending = controller.clearAllData()
    expect(controller.showClearConfirm.value).toBe(false)
    expect(controller.clearing.value).toBe(true)
    expect(api.fetchTasks).not.toHaveBeenCalled()
    resolve({ message: '已删除' })
    await pending
    expect(controller.successMsg.value).toBe('已删除')
    expect(api.fetchTasks).toHaveBeenCalledOnce()
    expect(controller.clearing.value).toBe(false)
  })

  it('preserves confirmation branch and immutable list ordering', async () => {
    const api = createApi()
    const confirm = vi.fn(() => false)
    const controller = useMonitorPageController({ isAdmin: computed(() => true), api, confirm })
    const server = { id: 7, server_key: 'docs', display_name: 'Docs', description: '', url: 'https://test', transport: 'streamable_http', auth_type: 'none', auth_token_configured: false, auth_token_masked: null, enabled: true, last_test_status: '', last_test_message: '', last_test_at: null, tools: [], created_at: null, updated_at: null }
    controller.mcpServers.value = [server]
    await controller.deleteMcpServer(server)
    expect(confirm).toHaveBeenCalledOnce()
    expect(api.deleteMcpServer).not.toHaveBeenCalled()
    vi.mocked(api.saveMcpServer).mockResolvedValue({ ...server, id: 8 })
    controller.mcpForm.value = { id: null, server_key: 'new', display_name: 'New', description: '', url: 'https://new', auth_type: 'none', auth_token: '', clear_auth_token: false, enabled: true }
    await controller.saveMcpServer()
    expect(controller.mcpServers.value.map(({ id }) => id)).toEqual([8, 7])
  })
})
