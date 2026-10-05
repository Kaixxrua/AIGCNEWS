import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { readLandingSource, sendVisitBeacon } from './visitBeacon'

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

describe('429 landing source', () => {
  beforeEach(() => {
    transport.post.mockReset()
    sessionStorage.clear()
    localStorage.clear()
  })

  it('reads every tag the MCP and REST 429 messages carry', () => {
    for (const side of ['mcp', 'api']) {
      for (const kind of ['anon', 'daily', 'monthly']) {
        const ref = `${side}-429-${kind}`
        expect(readLandingSource({ pathname: '/membership', search: `?ref=${ref}` })).toEqual({ ref, path: '/membership' })
      }
    }
  })

  it('tolerates punctuation or text a client glued onto the link', () => {
    for (const search of ['?ref=mcp-429-anon.', '?ref=mcp-429-anon%E3%80%82', '?ref=mcp-429-anon%E5%BC%80%E9%80%9A', '?ref=%20mcp-429-anon%20']) {
      expect(readLandingSource({ pathname: '/mcp', search })).toEqual({ ref: 'mcp-429-anon', path: '/mcp' })
    }
  })

  it('ignores missing, unknown or look-alike tags', () => {
    for (const search of ['', '?utm_source=x', '?ref=', '?ref=mcp-429', '?ref=mcp-429-anonymous', '?ref=mcp-429-anon_x', '?ref=MCP-429-ANON', '?ref=x-mcp-429-anon']) {
      expect(readLandingSource({ pathname: '/mcp', search })).toBeNull()
    }
  })

  it('caps the reported path at the backend field limit', () => {
    const source = readLandingSource({ pathname: `/${'x'.repeat(400)}`, search: '?ref=api-429-daily' })
    expect(source?.path).toHaveLength(256)
  })

  it('sends the landing with the visit and skips the daily guard for it', async () => {
    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })
    sendVisitBeacon()
    await flush()

    sendVisitBeacon({ pathname: '/mcp', search: '?ref=mcp-429-anon' })
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(2)
    const visitorId = localStorage.getItem('aigc:anonymous-visitor-id')
    expect(transport.post.mock.calls[1]).toEqual([
      '/dashboard/visit',
      { visitor_id: visitorId, landing_ref: 'mcp-429-anon', landing_path: '/mcp' },
    ])
  })

  it('keeps the plain daily guard when the address carries no known tag', async () => {
    transport.post.mockResolvedValue({ data: { today_visits: 1, total_visits: 1 } })
    sendVisitBeacon({ pathname: '/mcp', search: '?ref=newsletter' })
    await flush()
    sendVisitBeacon({ pathname: '/mcp', search: '?ref=newsletter' })
    await flush()

    expect(transport.post).toHaveBeenCalledTimes(1)
    expect(transport.post.mock.calls[0]?.[1]).toEqual({ visitor_id: localStorage.getItem('aigc:anonymous-visitor-id') })
  })
})
