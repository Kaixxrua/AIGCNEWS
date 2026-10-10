import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { MCP_OAUTH_ENDPOINT } from '@/features/mcp/mcpOAuth'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import { AGENT_COPIED_AT_KEY, useMcpAgentSetup, type McpAgentSetupOptions } from './useMcpAgentSetup'

const NOW = Date.parse('2026-10-09T08:00:00Z')

const token = (patch: Partial<McpTokenMetadata> = {}): McpTokenMetadata => ({
  id: 1,
  token_hint: 'aigc_mcp_abc...wxyz',
  scopes: [],
  client_type: 'other',
  client_label: 'Old laptop',
  expires_at: null,
  revoked_at: null,
  created_at: '2026-09-01T00:00:00Z',
  last_used_at: '2026-09-02T00:00:00Z',
  ...patch,
})

const memoryStorage = () => {
  const items = new Map<string, string>()
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => { items.set(key, value) },
    removeItem: (key: string) => { items.delete(key) },
  }
}

const iso = (ms: number) => new Date(ms).toISOString()

const mountSetup = (overrides: Partial<Omit<McpAgentSetupOptions, 'signedIn'>> & { signedIn?: boolean } = {}) => {
  const signedIn = ref(overrides.signedIn ?? false)
  const storage = overrides.storage === undefined ? memoryStorage() : overrides.storage
  const fetchMcpTokens = vi.fn<() => Promise<McpTokenMetadata[]>>().mockResolvedValue([token()])
  const write = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
  const agent = useMcpAgentSetup({
    locale: () => 'zh-CN',
    manualPageUrl: () => 'https://aigcnews.cn/mcp',
    write,
    fetchMcpTokens,
    now: () => Date.now(),
    connectionWatch: { visibility: { hidden: () => false, subscribe: () => () => {} } },
    ...overrides,
    storage,
    signedIn,
  })
  return { agent, signedIn, storage, fetchMcpTokens, write }
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMcpAgentSetup', () => {
  it('lets a guest copy the token-free prompt without polling anything', async () => {
    const { agent, write, fetchMcpTokens, storage } = mountSetup()

    await expect(agent.copyPrompt()).resolves.toBe(true)
    expect(write).toHaveBeenCalledWith(agent.prompt.value)
    expect(agent.prompt.value).toContain(MCP_OAUTH_ENDPOINT)
    expect(agent.prompt.value).toContain('https://aigcnews.cn/mcp')
    expect(agent.copiedKey.value).toBe('agent-prompt')
    expect(agent.connection.status.value).toBe('idle')
    expect(fetchMcpTokens).not.toHaveBeenCalled()
    expect((storage as ReturnType<typeof memoryStorage>).items.get(AGENT_COPIED_AT_KEY)).toBe(String(NOW))
  })

  it('follows the prompt locale', () => {
    const { agent } = mountSetup({ locale: () => 'en-US' })

    expect(agent.prompt.value).toMatch(/^Please connect AIGC Radar MCP/)
  })

  it('waits for the token the agent authorizes after the copy, ignoring dsh and manual tokens', async () => {
    const { agent, fetchMcpTokens } = mountSetup({ signedIn: true })
    expect(agent.connection.status.value).toBe('idle')
    expect(fetchMcpTokens).not.toHaveBeenCalled()

    await agent.copyPrompt()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMcpTokens).toHaveBeenCalledTimes(1)
    expect(agent.connection.status.value).toBe('waiting')

    fetchMcpTokens.mockResolvedValue([
      token(),
      token({ id: 2, client_label: 'dsh-aigc-radar', created_at: iso(NOW + 1_000), last_used_at: iso(NOW + 2_000) }),
      token({ id: 3, client_label: 'Manual MCP config', created_at: iso(NOW + 1_000), last_used_at: iso(NOW + 2_000) }),
    ])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(agent.connection.status.value).toBe('waiting')

    fetchMcpTokens.mockResolvedValue([token(), token({ id: 4, client_label: 'Claude Code', created_at: iso(NOW + 4_000), last_used_at: null })])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(agent.connection.status.value).toBe('authorized')
    expect(agent.connection.clientLabel.value).toBe('Claude Code')

    fetchMcpTokens.mockResolvedValue([token(), token({ id: 4, client_label: 'Claude Code', created_at: iso(NOW + 4_000), last_used_at: iso(NOW + 8_000) })])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(agent.connection.status.value).toBe('connected')
    expect(agent.connection.fresh.value).toBe(true)
  })

  it('keeps the same wait when the prompt is copied again, and starts over after a connection', async () => {
    const { agent, fetchMcpTokens } = mountSetup({ signedIn: true })
    await agent.copyPrompt()
    await vi.advanceTimersByTimeAsync(0)

    // 等的时候又复制一次：不重记基线（否则 Agent 刚授权的令牌会被当成旧的），只是重新勤快地查。
    fetchMcpTokens.mockResolvedValue([token(), token({ id: 4, client_label: 'Codex', created_at: iso(NOW + 1_000), last_used_at: null })])
    await agent.copyPrompt()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(agent.connection.status.value).toBe('authorized')

    fetchMcpTokens.mockResolvedValue([token(), token({ id: 4, client_label: 'Codex', created_at: iso(NOW + 1_000), last_used_at: iso(NOW + 5_000) })])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(agent.connection.status.value).toBe('connected')

    // 接好一个再复制：要接下一个客户端，重新开始等，刚连上的那枚算进基线。
    await agent.copyPrompt()
    expect(agent.connection.status.value).toBe('waiting')
    await vi.advanceTimersByTimeAsync(0)
    expect(agent.connection.status.value).toBe('waiting')
  })

  it('picks up a guest copy once the guest signs in on the page', async () => {
    const { agent, signedIn, fetchMcpTokens } = mountSetup()
    await agent.copyPrompt()

    // 游客复制后去授权页登录并同意，客户端已经连上，再回到这页登录。
    await vi.advanceTimersByTimeAsync(90_000)
    fetchMcpTokens.mockResolvedValue([token(), token({ id: 5, client_label: 'Cursor', created_at: iso(NOW + 30_000), last_used_at: iso(NOW + 40_000) })])
    signedIn.value = true
    await vi.advanceTimersByTimeAsync(0)

    expect(agent.connection.status.value).toBe('connected')
    expect(agent.connection.clientLabel.value).toBe('Cursor')
  })

  it('resumes after a reload within half an hour and forgets older copies', async () => {
    const recent = memoryStorage()
    recent.setItem(AGENT_COPIED_AT_KEY, String(NOW - 10 * 60_000))
    const resumed = mountSetup({ signedIn: true, storage: recent })
    await vi.advanceTimersByTimeAsync(0)
    expect(resumed.agent.connection.status.value).toBe('waiting')
    expect(resumed.fetchMcpTokens).toHaveBeenCalledTimes(1)
    resumed.agent.dispose()

    const stale = memoryStorage()
    stale.setItem(AGENT_COPIED_AT_KEY, String(NOW - 31 * 60_000))
    const ignored = mountSetup({ signedIn: true, storage: stale })
    await vi.advanceTimersByTimeAsync(0)
    expect(ignored.agent.connection.status.value).toBe('idle')
    expect(ignored.fetchMcpTokens).not.toHaveBeenCalled()
  })

  it('stops and forgets the copy when the user signs out', async () => {
    const { agent, signedIn, storage, fetchMcpTokens } = mountSetup({ signedIn: true })
    await agent.copyPrompt()
    await vi.advanceTimersByTimeAsync(0)

    signedIn.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(agent.connection.status.value).toBe('idle')
    expect((storage as ReturnType<typeof memoryStorage>).items.has(AGENT_COPIED_AT_KEY)).toBe(false)

    const calls = fetchMcpTokens.mock.calls.length
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMcpTokens).toHaveBeenCalledTimes(calls)

    // 下一个账号登录：没有复制记录，不自动开始等。
    signedIn.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(agent.connection.status.value).toBe('idle')
  })

  it('keeps the copy in memory when session storage is unavailable', async () => {
    const broken = {
      getItem: () => { throw new Error('denied') },
      setItem: () => { throw new Error('denied') },
      removeItem: () => { throw new Error('denied') },
    }
    const { agent, signedIn } = mountSetup({ storage: broken })
    await expect(agent.copyPrompt()).resolves.toBe(true)

    signedIn.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(agent.connection.status.value).toBe('waiting')
  })

  it('reports a failed copy and starts nothing', async () => {
    const onError = vi.fn()
    const { agent, storage, fetchMcpTokens } = mountSetup({
      signedIn: true,
      write: () => Promise.reject(new Error('denied')),
      copyNotice: { onError },
    })

    await expect(agent.copyPrompt()).resolves.toBe(false)
    expect(onError).toHaveBeenCalledOnce()
    expect(agent.connection.status.value).toBe('idle')
    expect(fetchMcpTokens).not.toHaveBeenCalled()
    expect((storage as ReturnType<typeof memoryStorage>).items.size).toBe(0)
  })

  it('stops polling on dispose', async () => {
    const { agent, fetchMcpTokens } = mountSetup({ signedIn: true })
    await agent.copyPrompt()
    await vi.advanceTimersByTimeAsync(0)
    agent.dispose()

    const calls = fetchMcpTokens.mock.calls.length
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMcpTokens).toHaveBeenCalledTimes(calls)
    expect(agent.copiedKey.value).toBe('')
  })
})
