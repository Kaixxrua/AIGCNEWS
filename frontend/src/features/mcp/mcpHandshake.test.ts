import { afterEach, describe, expect, it, vi } from 'vitest'

const MCP_PROTOCOL_VERSION = '2025-06-18'
const MCP_TEST_TIMEOUT_MS = 15_000

type JsonRpcData = {
  jsonrpc?: string
  id?: string | number | null
  result?: { tools?: Array<{ name: string; description: string }> }
  error?: { message?: string } | string
}
type Phase = 'initialize' | 'initialized' | 'tools/list'
type FetchLike = (input: string, init: RequestInit) => Promise<Pick<Response, 'ok' | 'status' | 'text'>>

async function publicHandshakeContract(
  endpoint: string,
  fetchImpl: FetchLike,
  onPhase: (phase: Phase, status: 'running' | 'success' | 'error') => void,
): Promise<JsonRpcData> {
  async function post(method: string, params: Record<string, unknown> | undefined, id: number | undefined) {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), MCP_TEST_TIMEOUT_MS)
    try {
      const response = await fetchImpl(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json, text/event-stream',
          'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
        },
        body: JSON.stringify({
          jsonrpc: '2.0',
          method,
          ...(id === undefined ? {} : { id }),
          ...(params ? { params } : {}),
        }),
        signal: controller.signal,
      })
      const text = await response.text()
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const match = text.match(/data:\s*(\{.*\})/)
      const data = JSON.parse(match?.[1] || text || '{}') as JsonRpcData
      if (data.error) throw new Error(typeof data.error === 'string' ? data.error : data.error.message)
      return data
    } finally {
      window.clearTimeout(timeout)
    }
  }

  let running: Phase = 'initialize'
  try {
    onPhase(running, 'running')
    await post('initialize', { protocolVersion: MCP_PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'aigc-news-connect-page', version: '1.0.0' } }, 1)
    onPhase(running, 'success')
    running = 'initialized'
    onPhase(running, 'running')
    await post('notifications/initialized', undefined, undefined)
    onPhase(running, 'success')
    running = 'tools/list'
    onPhase(running, 'running')
    const data = await post('tools/list', {}, 2)
    onPhase(running, 'success')
    return data
  } catch (error) {
    onPhase(running, 'error')
    throw error
  }
}

function response(body: string, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => body }
}

describe('public MCP handshake contract', () => {
  afterEach(() => vi.useRealTimers())

  it('uses initialize id 1, initialized without id, then tools/list id 2', async () => {
    const requests: Array<{ input: string; init: RequestInit }> = []
    const fetchImpl: FetchLike = vi.fn(async (input, init) => {
      requests.push({ input, init })
      const body = JSON.parse(String(init.body))
      return response(JSON.stringify(body.method === 'tools/list'
        ? { jsonrpc: '2.0', id: 2, result: { tools: [{ name: 'search_papers', description: 'public' }] } }
        : { jsonrpc: '2.0', ...(body.id === undefined ? {} : { id: body.id }), result: {} }))
    })
    const onPhase = vi.fn()

    const result = await publicHandshakeContract('https://example.test/api/mcp', fetchImpl, onPhase)

    expect(requests.map(({ init }) => JSON.parse(String(init.body)))).toEqual([
      { jsonrpc: '2.0', method: 'initialize', id: 1, params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'aigc-news-connect-page', version: '1.0.0' } } },
      { jsonrpc: '2.0', method: 'notifications/initialized' },
      { jsonrpc: '2.0', method: 'tools/list', id: 2, params: {} },
    ])
    expect(requests.every(({ input }) => input === 'https://example.test/api/mcp')).toBe(true)
    expect(requests[0]!.init.headers).toEqual({
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
      'MCP-Protocol-Version': '2025-06-18',
    })
    expect(result.result?.tools).toHaveLength(1)
    expect(onPhase.mock.calls).toEqual([
      ['initialize', 'running'], ['initialize', 'success'],
      ['initialized', 'running'], ['initialized', 'success'],
      ['tools/list', 'running'], ['tools/list', 'success'],
    ])
  })

  it.each([
    ['plain JSON', JSON.stringify({ jsonrpc: '2.0', id: 2, result: { tools: [] } })],
    ['single-line data', 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n\n'],
  ])('parses %s responses', async (_label, body) => {
    const fetchImpl: FetchLike = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init.body))
      return request.method === 'tools/list' ? response(body) : response('{}')
    })
    await expect(publicHandshakeContract('https://example.test/api/mcp', fetchImpl, vi.fn())).resolves.toMatchObject({ result: { tools: [] } })
  })

  it.each([
    ['HTTP errors', () => response('denied', 403), 'HTTP 403'],
    ['JSON-RPC object errors', () => response('{"jsonrpc":"2.0","id":1,"error":{"message":"rpc denied"}}'), 'rpc denied'],
    ['JSON-RPC string errors', () => response('{"jsonrpc":"2.0","id":1,"error":"rpc failed"}'), 'rpc failed'],
  ])('maps %s and marks the running phase', async (_label, makeResponse, message) => {
    const onPhase = vi.fn()
    await expect(publicHandshakeContract('https://example.test/api/mcp', vi.fn(async () => makeResponse()), onPhase)).rejects.toThrow(message)
    expect(onPhase.mock.calls[onPhase.mock.calls.length - 1]).toEqual(['initialize', 'error'])
  })

  it('aborts a request after 15 seconds and clears its timer', async () => {
    vi.useFakeTimers()
    const fetchImpl: FetchLike = vi.fn((_input, init) => new Promise<Pick<Response, 'ok' | 'status' | 'text'>>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const promise = publicHandshakeContract('https://example.test/api/mcp', fetchImpl, vi.fn())
    const rejection = expect(promise).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(15_000)
    await rejection
    expect(vi.getTimerCount()).toBe(0)
  })

  it('never sends a private token or writes it to public sinks', async () => {
    const sentinel = 'sentinel-private-token'
    const requests: RequestInit[] = []
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem')
    const consoleSpy = vi.spyOn(console, 'log')
    const fetchImpl: FetchLike = vi.fn(async (_input, init) => {
      requests.push(init)
      return response('{}')
    })

    await publicHandshakeContract('https://example.test/api/mcp', fetchImpl, vi.fn())

    expect(JSON.stringify(requests)).not.toContain(sentinel)
    expect(JSON.stringify(storageSpy.mock.calls)).not.toContain(sentinel)
    expect(JSON.stringify(consoleSpy.mock.calls)).not.toContain(sentinel)
    expect(document.body.textContent).not.toContain(sentinel)
    storageSpy.mockRestore()
    consoleSpy.mockRestore()
  })
})
