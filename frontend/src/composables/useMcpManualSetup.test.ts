import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import type { CreateMcpTokenResponse, McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import { useMcpManualSetup, type McpManualSetupOptions } from './useMcpManualSetup'

const NOW = Date.parse('2026-10-09T08:00:00Z')
const SECRET = 'aigc_mcp_manual_secret'

const metadata = (patch: Partial<McpTokenMetadata> = {}): McpTokenMetadata => ({
  id: 9,
  token_hint: 'aigc_mcp_man...cret',
  scopes: [],
  client_type: 'other',
  client_label: 'Manual MCP config',
  expires_at: null,
  revoked_at: null,
  created_at: '2026-10-09T08:00:00Z',
  last_used_at: null,
  ...patch,
})

const created = (patch: Partial<McpTokenMetadata> = {}): CreateMcpTokenResponse => ({
  token: SECRET,
  token_metadata: metadata(patch),
  replaced_count: 0,
})

const httpError = (status: number) => new AxiosError('failed', String(status), undefined, undefined, {
  status,
  statusText: '',
  headers: {},
  config: { headers: new AxiosHeaders() },
  data: {},
})

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

const mountSetup = (overrides: Partial<McpManualSetupOptions> = {}) => {
  const createMcpToken = vi.fn<NonNullable<McpManualSetupOptions['createMcpToken']>>().mockResolvedValue(created())
  const fetchMcpTokens = vi.fn<() => Promise<McpTokenMetadata[]>>().mockResolvedValue([metadata()])
  const write = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
  const manual = useMcpManualSetup({
    endpoint: () => 'https://aigcnews.cn/api/mcp',
    createMcpToken,
    fetchMcpTokens,
    write,
    connectionWatch: { now: () => Date.now(), visibility: { hidden: () => false, subscribe: () => () => {} } },
    ...overrides,
  })
  return { manual, createMcpToken, fetchMcpTokens, write }
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMcpManualSetup', () => {
  it('previews the configuration with a slot and signs nothing until asked', () => {
    const { manual, createMcpToken } = mountSetup()

    expect(manual.phase.value).toBe('idle')
    expect(manual.preview.value).toContain(COMMAND_TOKEN_SLOT)
    expect(manual.preview.value).toContain('https://aigcnews.cn/api/mcp')
    expect(manual.config.value).toBe('')
    expect(createMcpToken).not.toHaveBeenCalled()
  })

  it('signs a labelled token, copies the full configuration and waits for its first use', async () => {
    const { manual, createMcpToken, fetchMcpTokens, write } = mountSetup()

    await expect(manual.generate()).resolves.toBe(true)
    expect(createMcpToken).toHaveBeenCalledWith({ client_type: 'other', client_label: 'Manual MCP config' })
    expect(manual.phase.value).toBe('ready')
    expect(manual.preview.value).not.toContain(SECRET)
    expect(manual.connection.status.value).toBe('waiting')

    await expect(manual.copyConfig()).resolves.toBe(true)
    expect(write).toHaveBeenCalledWith(manual.config.value)
    expect(JSON.parse(write.mock.calls[0]![0]).mcpServers['aigc-news'].headers.Authorization).toBe(`Bearer ${SECRET}`)
    expect(manual.copiedKey.value).toBe('manual-config')

    fetchMcpTokens.mockResolvedValue([metadata({ last_used_at: '2026-10-09T08:00:20Z' })])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(manual.connection.status.value).toBe('connected')
  })

  it('does not copy before a token exists', async () => {
    const { manual, write } = mountSetup()

    await expect(manual.copyConfig()).resolves.toBe(false)
    expect(write).not.toHaveBeenCalled()
  })

  it('maps an expired session and other failures to messages', async () => {
    const expired = mountSetup()
    expired.createMcpToken.mockRejectedValue(httpError(401))
    await expect(expired.manual.generate()).resolves.toBe(false)
    expect(expired.manual.phase.value).toBe('error')
    expect(expired.manual.error.value).toBe('mcp.loginExpired')

    const failing = mountSetup()
    failing.createMcpToken.mockRejectedValue(httpError(500))
    await failing.manual.generate()
    expect(failing.manual.error.value).toBe('mcp.tokenCreateFailed')

    failing.createMcpToken.mockResolvedValue(created())
    await expect(failing.manual.generate()).resolves.toBe(true)
    expect(failing.manual.error.value).toBe('')
  })

  it('drops the token on clear and ignores a response that arrives afterwards', async () => {
    const { manual, createMcpToken } = mountSetup()
    const pending = deferred<CreateMcpTokenResponse>()
    createMcpToken.mockReturnValueOnce(pending.promise)

    const generating = manual.generate()
    expect(manual.phase.value).toBe('creating')
    await expect(manual.generate()).resolves.toBe(false)
    expect(createMcpToken).toHaveBeenCalledOnce()

    manual.clear()
    pending.resolve(created())
    await expect(generating).resolves.toBe(false)
    expect(manual.phase.value).toBe('idle')
    expect(manual.config.value).toBe('')
    expect(manual.connection.status.value).toBe('idle')
  })

  it('forgets everything on dispose', async () => {
    const { manual, fetchMcpTokens } = mountSetup()
    await manual.generate()
    manual.dispose()

    expect(manual.config.value).toBe('')
    const calls = fetchMcpTokens.mock.calls.length
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMcpTokens).toHaveBeenCalledTimes(calls)
    await expect(manual.generate()).resolves.toBe(false)
  })
})
