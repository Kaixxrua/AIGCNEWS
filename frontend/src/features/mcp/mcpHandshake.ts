export const MCP_PROTOCOL_VERSION = '2025-06-18'
export const MCP_TEST_TIMEOUT_MS = 15_000

export type McpHandshakePhase = 'initialize' | 'initialized' | 'tools/list'
export type McpHandshakePhaseStatus = 'running' | 'success' | 'error'

export interface McpPublicToolData {
  name?: unknown
  description?: unknown
}

interface JsonRpcData {
  jsonrpc?: string
  id?: string | number | null
  result?: { tools?: unknown }
  error?: { message?: string } | string
}

export type McpHandshakeFetch = (
  input: string,
  init: RequestInit,
) => Promise<Pick<Response, 'ok' | 'status' | 'text'>>

export interface McpHandshakeOptions {
  fetch?: McpHandshakeFetch
  onPhase?: (phase: McpHandshakePhase, status: McpHandshakePhaseStatus) => void
  timeoutMs?: number
}

function protocolHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    Accept: 'application/json, text/event-stream',
    'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
  }
}

function parseResponse(text: string): JsonRpcData {
  const match = text.match(/data:\s*(\{.*\})/)
  const data = JSON.parse(match?.[1] || text || '{}') as JsonRpcData
  if (data.error) {
    throw new Error(typeof data.error === 'string' ? data.error : data.error.message)
  }
  return data
}

async function postMcp(
  endpoint: string,
  method: string,
  params: Record<string, unknown> | undefined,
  id: number | undefined,
  fetchImpl: McpHandshakeFetch,
  timeoutMs: number,
): Promise<JsonRpcData> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(endpoint, {
      method: 'POST',
      headers: protocolHeaders(),
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
    return parseResponse(text)
  } finally {
    window.clearTimeout(timeout)
  }
}

export async function performPublicMcpHandshake(
  endpoint: string,
  options: McpHandshakeOptions = {},
): Promise<unknown[]> {
  const fetchImpl = options.fetch ?? ((input, init) => fetch(input, init))
  const onPhase = options.onPhase ?? (() => undefined)
  const timeoutMs = options.timeoutMs ?? MCP_TEST_TIMEOUT_MS
  let running: McpHandshakePhase = 'initialize'

  try {
    onPhase(running, 'running')
    await postMcp(endpoint, 'initialize', {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: 'aigc-news-connect-page', version: '1.0.0' },
    }, 1, fetchImpl, timeoutMs)
    onPhase(running, 'success')

    running = 'initialized'
    onPhase(running, 'running')
    await postMcp(endpoint, 'notifications/initialized', undefined, undefined, fetchImpl, timeoutMs)
    onPhase(running, 'success')

    running = 'tools/list'
    onPhase(running, 'running')
    const data = await postMcp(endpoint, 'tools/list', {}, 2, fetchImpl, timeoutMs)
    if (!Array.isArray(data.result?.tools)) {
      throw new Error('tools/list 未返回有效的工具列表。')
    }
    onPhase(running, 'success')
    return data.result.tools
  } catch (error) {
    onPhase(running, 'error')
    throw error
  }
}
