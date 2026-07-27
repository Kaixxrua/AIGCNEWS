import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../services/http/apiClient', () => ({ api }))

import { useMonitorController } from './useMonitorController'

const createController = (running = false) => {
  const errorMsg = ref('old error')
  const successMsg = ref('old success')
  const fetchTasks = vi.fn(async () => undefined)
  const refreshData = vi.fn(async () => undefined)
  const controller = useMonitorController({
    isTaskRunning: computed(() => running),
    errorMsg,
    successMsg,
    clearMessages: () => { errorMsg.value = ''; successMsg.value = '' },
    fetchTasks,
    refreshData,
  })
  return { controller, errorMsg, successMsg, fetchTasks, refreshData }
}

describe('Monitor page action contract', () => {
  beforeEach(() => {
    api.post.mockReset()
    vi.useFakeTimers()
  })

  it('preserves source/date ingestion request shapes and delayed task refreshes', async () => {
    api.post.mockResolvedValue({ data: {} })
    const { controller, successMsg, fetchTasks } = createController()

    await controller.ingestSingleSource('github')
    expect(api.post).toHaveBeenCalledWith('/ops/ingest-source', null, { params: { source: 'github', limit: 20 } })
    expect(successMsg.value).toContain('github')
    await vi.advanceTimersByTimeAsync(999)
    expect(fetchTasks).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchTasks).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchTasks).toHaveBeenCalledTimes(2)

    controller.targetDate.value = '2026-07-20'
    await controller.ingestByDate()
    expect(api.post).toHaveBeenLastCalledWith('/ops/ingest-by-date', { target_date: '2026-07-20', limit: 30 })
  })

  it('preserves normal/forced sync body, guards, messages, and refresh timing', async () => {
    api.post.mockResolvedValue({ data: {} })
    const normal = createController()
    await normal.controller.syncDataNow(false)
    expect(api.post).toHaveBeenCalledWith('/ops/ingest', { limit: 20, force: false })
    expect(normal.successMsg.value).toBe('智能同步任务已提交，后台执行中…')
    await vi.advanceTimersByTimeAsync(1000)
    expect(normal.fetchTasks).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(normal.fetchTasks).toHaveBeenCalledTimes(2)

    await normal.controller.syncDataNow(true)
    expect(api.post).toHaveBeenLastCalledWith('/ops/ingest', { limit: 20, force: true })
    expect(normal.successMsg.value).toBe('强制采集任务已提交，后台执行中…')

    const blocked = createController(true)
    await blocked.controller.syncDataNow()
    expect(api.post).toHaveBeenCalledTimes(2)
  })

  it('preserves operation endpoints, defaults, error mapping, and loading reset', async () => {
    api.post.mockResolvedValueOnce({ data: {} }).mockResolvedValueOnce({ data: {} })
    const { controller, successMsg } = createController()
    await controller.generateAllBriefings()
    expect(api.post).toHaveBeenCalledWith('/ops/briefing/generate-all', null, { params: { force_regenerate: true } })
    expect(successMsg.value).toContain('简报生成任务')
    await controller.clearDashboardCache()
    expect(api.post).toHaveBeenLastCalledWith('/ops/cache/clear-dashboard')

    api.post.mockRejectedValueOnce({ response: { status: 409 } })
    const failed = createController()
    await failed.controller.ingestSingleSource('arxiv')
    expect(failed.errorMsg.value).toBe('当前已有任务正在运行，请等待完成后再试。')
    expect(failed.controller.ingestingSource.value).toBeNull()

    failed.controller.targetDate.value = ''
    await failed.controller.ingestByDate()
    expect(failed.errorMsg.value).toBe('请选择目标日期')
  })

  it('preserves destructive clear state, endpoint, response message, and refresh order', async () => {
    let resolve!: (value: { data: { message: string } }) => void
    api.post.mockReturnValue(new Promise((done) => { resolve = done }))
    const { controller, successMsg, refreshData } = createController()
    controller.showClearConfirm.value = true

    const pending = controller.clearAllData()
    expect(controller.showClearConfirm.value).toBe(false)
    expect(controller.clearing.value).toBe(true)
    expect(api.post).toHaveBeenCalledWith('/ops/clear-data')
    expect(refreshData).not.toHaveBeenCalled()
    resolve({ data: { message: '已删除' } })
    await pending
    expect(successMsg.value).toBe('已删除')
    expect(refreshData).toHaveBeenCalledOnce()
    expect(controller.clearing.value).toBe(false)
  })
})
