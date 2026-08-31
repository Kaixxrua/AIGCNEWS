import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { sendVisitBeacon } from './visitBeacon'

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

describe('visit beacon (daily anonymous visitor semantics)', () => {
  beforeEach(() => {
    transport.post.mockReset()
    sessionStorage.clear()
    localStorage.clear()
  })

  it('creates and persists one anonymous ID while guarding repeated sends', async () => {
    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })

    sendVisitBeacon()
    await flush()
    sendVisitBeacon()
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(1)
    const call = transport.post.mock.calls[0]
    expect(call).toBeDefined()
    const path = call?.[0]
    const body = call?.[1] as { visitor_id?: string } | undefined
    expect(path).toBe('/dashboard/visit')
    expect(body?.visitor_id).toMatch(/^[A-Za-z0-9_-]{16,128}$/)
    expect(localStorage.getItem('aigc:anonymous-visitor-id')).toBe(body?.visitor_id)
  })

  it('does not set the guard when the post fails, so a later entry retries', async () => {
    transport.post.mockRejectedValueOnce(new Error('backend down'))
    sendVisitBeacon()
    await flush()

    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })
    sendVisitBeacon()
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(2)
  })

  it('reuses the same anonymous ID after the daily guard expires', async () => {
    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })
    sendVisitBeacon()
    await flush()
    const visitorId = localStorage.getItem('aigc:anonymous-visitor-id')
    sessionStorage.clear()

    sendVisitBeacon()
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(2)
    expect(transport.post.mock.calls[1]?.[1]).toEqual({ visitor_id: visitorId })
  })

  it('stays silent when storage is unavailable', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })

    sendVisitBeacon()
    await flush()

    expect(transport.post).not.toHaveBeenCalled()
    getItem.mockRestore()
  })
})
