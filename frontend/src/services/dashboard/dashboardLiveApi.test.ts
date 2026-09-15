import { describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))
import { fetchLiveStats } from './dashboardLiveApi'

describe('shared live statistics request', () => {
  it('shares concurrent reads and fetches fresh data after completion', async () => {
    transport.get.mockReset()
    let finish!: (value: { data: { total_documents: number } }) => void
    transport.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const header = fetchLiveStats()
    const board = fetchLiveStats(new AbortController().signal)
    expect(transport.get).toHaveBeenCalledTimes(1)
    finish({ data: { total_documents: 9 } })
    expect(await Promise.all([header, board])).toEqual([{ total_documents: 9 }, { total_documents: 9 }])
    transport.get.mockResolvedValueOnce({ data: { total_documents: 10 } })
    expect(await fetchLiveStats()).toEqual({ total_documents: 10 })
    expect(transport.get).toHaveBeenCalledTimes(2)
  })

  it('cancels one subscriber without canceling the other', async () => {
    let finish!: (value: { data: { total_documents: number } }) => void
    transport.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const controller = new AbortController()
    const board = fetchLiveStats(controller.signal)
    const header = fetchLiveStats()
    const canceled = expect(board).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await canceled
    finish({ data: { total_documents: 9 } })
    expect(await header).toEqual({ total_documents: 9 })
  })

  it('retries after a failed shared request', async () => {
    transport.get.mockRejectedValueOnce(new Error('offline'))
    await expect(fetchLiveStats()).rejects.toThrow('offline')
    transport.get.mockResolvedValueOnce({ data: { total_documents: 11 } })
    expect(await fetchLiveStats()).toEqual({ total_documents: 11 })
  })

  it('does not send an already canceled request', async () => {
    transport.get.mockClear()
    const controller = new AbortController()
    controller.abort()
    await expect(fetchLiveStats(controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(transport.get).not.toHaveBeenCalled()
  })
})
