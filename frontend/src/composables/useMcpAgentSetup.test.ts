import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { MCP_OAUTH_ENDPOINT } from '@/features/mcp/mcpOAuth'
import type { McpInstallCode, McpInstallCodePurpose, McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import { AGENT_COPIED_AT_KEY, useMcpAgentSetup, type McpAgentSetupOptions } from './useMcpAgentSetup'

const NOW = Date.parse('2026-10-09T08:00:00Z')
const FIRST_CODE = 'aigc_ic_FirstCode_0123456789abcdefghijklmnopqrstu'
const SECOND_CODE = 'aigc_ic_SecondCode_0123456789abcdefghijklmnopqrst'

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

const issued = (code: string): McpInstallCode => ({ code, purpose: 'mcp', expires_in: 600 })
const issueMock = () => vi.fn<(purpose: McpInstallCodePurpose) => Promise<McpInstallCode>>()

const mountSetup = (overrides: Partial<Omit<McpAgentSetupOptions, 'signedIn'>> & { signedIn?: boolean } = {}) => {
  const signedIn = ref(overrides.signedIn ?? false)
  const storage = overrides.storage === undefined ? memoryStorage() : overrides.storage
  const fetchMcpTokens = vi.fn<() => Promise<McpTokenMetadata[]>>().mockResolvedValue([token()])
  const write = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
  const writeSensitive = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
  const issueInstallCode = issueMock()
    .mockResolvedValueOnce(issued(FIRST_CODE))
    .mockResolvedValue(issued(SECOND_CODE))
  const agent = useMcpAgentSetup({
    locale: () => 'zh-CN',
    manualPageUrl: () => 'https://aigcnews.cn/mcp',
    write,
    writeSensitive,
    issueInstallCode,
    fetchMcpTokens,
    now: () => Date.now(),
    connectionWatch: { visibility: { hidden: () => false, subscribe: () => () => {} } },
    ...overrides,
    storage,
    signedIn,
  })
  return { agent, signedIn, storage, fetchMcpTokens, write, writeSensitive, issueInstallCode }
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMcpAgentSetup', () => {
  it('lets a guest copy the token-free prompt without polling anything', async () => {
    const { agent, write, writeSensitive, issueInstallCode, fetchMcpTokens, storage } = mountSetup()

    await expect(agent.copyPrompt()).resolves.toBe(true)
    expect(write).toHaveBeenCalledWith(agent.prompt.value)
    expect(writeSensitive).not.toHaveBeenCalled()
    expect(issueInstallCode).not.toHaveBeenCalled()
    expect(agent.prompt.value).not.toContain(COMMAND_TOKEN_SLOT)
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
    const { agent, storage, fetchMcpTokens, issueInstallCode } = mountSetup({
      signedIn: true,
      writeSensitive: () => Promise.reject(new Error('denied')),
      copyNotice: { onError },
    })
    await vi.advanceTimersByTimeAsync(0)

    await expect(agent.copyPrompt()).resolves.toBe(false)
    expect(onError).toHaveBeenCalledOnce()
    expect(agent.connection.status.value).toBe('idle')
    expect(fetchMcpTokens).not.toHaveBeenCalled()
    expect((storage as ReturnType<typeof memoryStorage>).items.size).toBe(0)
    // 没复制出去的码不作废，下一次点击接着用。
    expect(issueInstallCode).toHaveBeenCalledOnce()
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

  describe('install codes', () => {
    it('copies a signed-in reader’s prompt with the prefetched code through the sensitive clipboard', async () => {
      const { agent, write, writeSensitive, issueInstallCode } = mountSetup({ signedIn: true })
      expect(issueInstallCode).toHaveBeenCalledWith('mcp')
      expect(agent.installCodeReady.value).toBe(false)

      await vi.advanceTimersByTimeAsync(0)
      expect(agent.installCodeReady.value).toBe(true)
      // 页面上只有占位，真码只在复制出去的文本里。
      expect(agent.prompt.value).toContain(COMMAND_TOKEN_SLOT)
      expect(agent.prompt.value).not.toContain(FIRST_CODE)

      await expect(agent.copyPrompt()).resolves.toBe(true)
      expect(write).not.toHaveBeenCalled()
      expect(writeSensitive).toHaveBeenCalledWith(agent.prompt.value.split(COMMAND_TOKEN_SLOT).join(FIRST_CODE))
    })

    it('hands every copy a fresh code', async () => {
      const { agent, writeSensitive, issueInstallCode } = mountSetup({ signedIn: true })
      await vi.advanceTimersByTimeAsync(0)

      await agent.copyPrompt()
      expect(issueInstallCode).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(0)
      await agent.copyPrompt()

      expect(writeSensitive.mock.calls[0]![0]).toContain(FIRST_CODE)
      expect(writeSensitive.mock.calls[1]![0]).toContain(SECOND_CODE)
      expect(writeSensitive.mock.calls[1]![0]).not.toContain(FIRST_CODE)
    })

    it('falls back to the prompt without a code when none can be issued, and retries on the next copy', async () => {
      const issueInstallCode = issueMock().mockRejectedValueOnce(new Error('503')).mockResolvedValue(issued(SECOND_CODE))
      const { agent, write, writeSensitive } = mountSetup({ signedIn: true, issueInstallCode })
      await vi.advanceTimersByTimeAsync(0)
      expect(agent.installCodeReady.value).toBe(false)
      // 预览与复制出去的一致：都不带安装码那一步。
      expect(agent.prompt.value).not.toContain(COMMAND_TOKEN_SLOT)
      expect(agent.prompt.value).toContain('改用 https://aigcnews.cn/mcp 页面里的「手动配置」')
      const preview = agent.prompt.value

      await expect(agent.copyPrompt()).resolves.toBe(true)
      expect(writeSensitive).not.toHaveBeenCalled()
      expect(write).toHaveBeenCalledWith(preview)

      await vi.advanceTimersByTimeAsync(0)
      expect(issueInstallCode).toHaveBeenCalledTimes(2)
      expect(agent.installCodeReady.value).toBe(true)
      await agent.copyPrompt()
      expect(writeSensitive.mock.calls[0]![0]).toContain(SECOND_CODE)
    })

    it('copies without a code while the first one is still on its way', async () => {
      const { agent, write, writeSensitive } = mountSetup({ signedIn: true })

      await agent.copyPrompt()
      expect(writeSensitive).not.toHaveBeenCalled()
      expect(write.mock.calls[0]![0]).not.toContain('aigc_ic_')
    })

    it('drops the code when the reader signs out', async () => {
      const { agent, signedIn, write, issueInstallCode } = mountSetup({ signedIn: true })
      await vi.advanceTimersByTimeAsync(0)

      signedIn.value = false
      await vi.advanceTimersByTimeAsync(0)
      expect(agent.installCodeReady.value).toBe(false)
      expect(agent.prompt.value).not.toContain(COMMAND_TOKEN_SLOT)
      await agent.copyPrompt()
      expect(write.mock.calls[0]![0]).not.toContain(FIRST_CODE)
      expect(issueInstallCode).toHaveBeenCalledOnce()
    })
  })
})
