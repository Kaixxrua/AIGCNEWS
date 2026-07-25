import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  MCP_PROTOCOL_VERSION,
  MCP_TEST_TIMEOUT_MS,
  performPublicMcpHandshake,
  type McpHandshakeFetch,
} from './mcpHandshake'

function response(body: string, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => body }
}

describe('public MCP handshake contract', () => {
  afterEach(() => vi.useRealTimers())

  it('uses initialize id 1, initialized without id, then tools/list id 2', async () => {
    const requests: Array<{ input: string; init: RequestInit }> = []
    const fetchImpl: McpHandshakeFetch = vi.fn(async (input, init) => {
      requests.push({ input, init })
      const body = JSON.parse(String(init.body))
      return response(JSON.stringify(body.method === 'tools/list'
        ? { jsonrpc: '2.0', id: 2, result: { tools: [{ name: 'search_papers', description: 'public' }] } }
        : { jsonrpc: '2.0', ...(body.id === undefined ? {} : { id: body.id }), result: {} }))
    })
    const onPhase = vi.fn()

    const tools = await performPublicMcpHandshake('https://example.test/api/mcp', { fetch: fetchImpl, onPhase })

    expect(requests.map(({ init }) => JSON.parse(String(init.body)))).toEqual([
      { jsonrpc: '2.0', method: 'initialize', id: 1, params: { protocolVersion: MCP_PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'aigc-news-connect-page', version: '1.0.0' } } },
      { jsonrpc: '2.0', method: 'notifications/initialized' },
      { jsonrpc: '2.0', method: 'tools/list', id: 2, params: {} },
    ])
    expect(requests.every(({ input }) => input === 'https://example.test/api/mcp')).toBe(true)
    expect(requests[0]!.init.headers).toEqual({
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
      'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
    })
    expect(tools).toHaveLength(1)
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
    const fetchImpl: McpHandshakeFetch = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init.body))
      return request.method === 'tools/list' ? response(body) : response('{}')
    })
    await expect(performPublicMcpHandshake('https://example.test/api/mcp', { fetch: fetchImpl })).resolves.toEqual([])
  })

  it.each([
    ['HTTP errors', () => response('denied', 403), 'HTTP 403'],
    ['JSON-RPC object errors', () => response('{"jsonrpc":"2.0","id":1,"error":{"message":"rpc denied"}}'), 'rpc denied'],
    ['JSON-RPC string errors', () => response('{"jsonrpc":"2.0","id":1,"error":"rpc failed"}'), 'rpc failed'],
  ])('maps %s and marks the running phase', async (_label, makeResponse, message) => {
    const onPhase = vi.fn()
    await expect(performPublicMcpHandshake('https://example.test/api/mcp', {
      fetch: vi.fn(async () => makeResponse()),
      onPhase,
    })).rejects.toThrow(message)
    expect(onPhase.mock.calls[onPhase.mock.calls.length - 1]).toEqual(['initialize', 'error'])
  })

  it('rejects an invalid tools/list result and marks that phase as error', async () => {
    const onPhase = vi.fn()
    const fetchImpl: McpHandshakeFetch = vi.fn(async (_input, init) => {
      const request = JSON.parse(String(init.body))
      return response(JSON.stringify(request.method === 'tools/list'
        ? { jsonrpc: '2.0', id: 2, result: {} }
        : { jsonrpc: '2.0', result: {} }))
    })

    await expect(performPublicMcpHandshake('https://example.test/api/mcp', { fetch: fetchImpl, onPhase }))
      .rejects.toThrow('tools/list 未返回有效的工具列表。')
    expect(onPhase.mock.calls.slice(-2)).toEqual([
      ['tools/list', 'running'],
      ['tools/list', 'error'],
    ])
  })

  it('aborts a request after 15 seconds and clears its timer', async () => {
    vi.useFakeTimers()
    const fetchImpl: McpHandshakeFetch = vi.fn((_input, init) => new Promise<Pick<Response, 'ok' | 'status' | 'text'>>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const promise = performPublicMcpHandshake('https://example.test/api/mcp', { fetch: fetchImpl })
    const rejection = expect(promise).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(MCP_TEST_TIMEOUT_MS)
    await rejection
    expect(vi.getTimerCount()).toBe(0)
  })

  it('never sends a private token or writes it to public sinks', async () => {
    const sentinel = 'sentinel-private-token'
    const requests: RequestInit[] = []
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem')
    const consoleSpy = vi.spyOn(console, 'log')
    const fetchImpl: McpHandshakeFetch = vi.fn(async (_input, init) => {
      requests.push(init)
      const request = JSON.parse(String(init.body))
      return response(request.method === 'tools/list'
        ? '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}'
        : '{}')
    })

    await performPublicMcpHandshake('https://example.test/api/mcp', { fetch: fetchImpl })

    expect(JSON.stringify(requests)).not.toContain(sentinel)
    expect(JSON.stringify(storageSpy.mock.calls)).not.toContain(sentinel)
    expect(JSON.stringify(consoleSpy.mock.calls)).not.toContain(sentinel)
    expect(document.body.textContent).not.toContain(sentinel)
    storageSpy.mockRestore()
    consoleSpy.mockRestore()
  })
})
