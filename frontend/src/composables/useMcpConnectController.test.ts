import { nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mcpClientOptions } from '@/features/mcp/mcpClientCatalog'
import type { McpHandshakeOptions } from '@/features/mcp/mcpHandshake'
import { MCP_OAUTH_ENDPOINT } from '@/features/mcp/mcpOAuth'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import {
  useMcpConnectController,
  type McpConnectApi,
  type McpConnectHandshake,
} from './useMcpConnectController'

const token = (id: number, label = `client-${id}`): McpTokenMetadata => ({
  id,
  token_hint: `hint-${id}`,
  scopes: ['projects:favorites:read'],
  client_type: 'other',
  client_label: label,
  expires_at: null,
  revoked_at: null,
})

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, reject, resolve }
}

const createApi = (): McpConnectApi => ({
  fetchMcpTokens: vi.fn(async () => []),
  createMcpToken: vi.fn(async () => ({ token: 'secret', token_metadata: token(1), replaced_count: 0 })),
  deleteMcpToken: vi.fn(async (id) => ({ deleted: true, id })),
})

const createController = (overrides: Parameters<typeof useMcpConnectController>[0] = {}) => {
  const api = overrides.api ?? createApi()
  const controller = useMcpConnectController({
    api,
    defaultEndpoint: 'https://example.test/api/mcp',
    isLoggedIn: () => true,
    translate: (key, params) => `${key}${params ? JSON.stringify(params) : ''}`,
    confirm: () => true,
    // 这些用例覆盖手动 Token 流程；浏览器授权版在文件末尾单独测
    authMode: 'token',
    ...overrides,
  })
  return { api, controller }
}

const clientById = (id: string) => mcpClientOptions.find((client) => client.id === id)!

describe('MCP connect controller', () => {
  beforeEach(() => vi.useFakeTimers())

  it('validates endpoint protocols and redirects logged-out setup without creating a token', async () => {
    const navigateToLogin = vi.fn(async () => undefined)
    const { api, controller } = createController({ isLoggedIn: () => false, navigateToLogin })
    controller.endpointUrl.value = 'file:///tmp/mcp'
    expect(controller.endpointWarningKey.value).toBe('mcp.invalidProtocol')
    controller.endpointUrl.value = 'not a url'
    expect(controller.endpointWarningKey.value).toBe('mcp.invalidUrl')
    controller.endpointUrl.value = ''
    expect(controller.normalizedEndpoint.value).toBe('https://example.test/api/mcp')
    await controller.startSetup()
    expect(navigateToLogin).toHaveBeenCalledOnce()
    expect(api.createMcpToken).not.toHaveBeenCalled()
  })

  it('uses a setup snapshot and never publishes a command after an input change', async () => {
    const creation = deferred<Awaited<ReturnType<McpConnectApi['createMcpToken']>>>()
    const api = createApi()
    vi.mocked(api.createMcpToken).mockReturnValue(creation.promise)
    const { controller } = createController({ api })
    controller.clientLabel.value = 'Laptop'
    const pending = controller.startSetup()
    expect(api.createMcpToken).toHaveBeenCalledWith({
      client_type: 'claude',
      client_label: 'Claude Code · Laptop',
    })
    controller.selectedShell.value = 'bash'
    await nextTick()
    creation.resolve({ token: 'plaintext-secret', token_metadata: token(1), replaced_count: 0 })
    await pending
    expect(controller.transientCommand.value).toBe('')
    expect(controller.setupNotice.value).toBeNull()
    expect(controller.tokens.value).toEqual([])
  })

  it('keeps plaintext only in the transient generated command and clears it on changes', async () => {
    const { controller } = createController()
    await controller.startSetup()
    expect(controller.transientCommand.value).toContain('secret')
    expect(JSON.stringify(controller.tokens.value)).not.toContain('secret')
    controller.clientLabel.value = 'changed'
    await nextTick()
    expect(controller.transientCommand.value).toBe('')
  })

  it('makes token loads latest-run-wins', async () => {
    const first = deferred<McpTokenMetadata[]>()
    const second = deferred<McpTokenMetadata[]>()
    const api = createApi()
    vi.mocked(api.fetchMcpTokens).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const { controller } = createController({ api })
    const pendingFirst = controller.loadTokens()
    const pendingSecond = controller.loadTokens()
    second.resolve([token(2)])
    await pendingSecond
    first.resolve([token(1)])
    await pendingFirst
    expect(controller.tokens.value).toEqual([token(2)])
    expect(controller.loadingTokens.value).toBe(false)
  })

  it('does not let a pending load resurrect deleted metadata', async () => {
    const load = deferred<McpTokenMetadata[]>()
    const api = createApi()
    vi.mocked(api.fetchMcpTokens).mockReturnValue(load.promise)
    const { controller } = createController({ api })
    controller.tokens.value = [token(1)]
    const pendingLoad = controller.loadTokens()
    await controller.removeToken(token(1))
    load.resolve([token(1)])
    await pendingLoad
    expect(controller.tokens.value).toEqual([])
  })

  it('preserves metadata when delete is cancelled or fails', async () => {
    const api = createApi()
    const cancelled = useMcpConnectController({ api, isLoggedIn: () => true, confirm: () => false })
    cancelled.tokens.value = [token(1)]
    await cancelled.removeToken(token(1))
    expect(api.deleteMcpToken).not.toHaveBeenCalled()
    expect(cancelled.tokens.value).toHaveLength(1)

    vi.mocked(api.deleteMcpToken).mockRejectedValueOnce(new Error('delete failed'))
    const { controller } = createController({ api })
    controller.tokens.value = [token(1)]
    await controller.removeToken(token(1))
    expect(controller.tokens.value).toHaveLength(1)
    expect(controller.setupError.value).toEqual({ kind: 'literal', message: 'delete failed' })
  })

  it('applies latest-run-wins to public handshakes and ignores stale phase callbacks', async () => {
    const first = deferred<unknown[]>()
    const second = deferred<unknown[]>()
    const callbacks: McpHandshakeOptions[] = []
    const handshake: McpConnectHandshake = vi.fn((_, options) => {
      callbacks.push(options ?? {})
      return callbacks.length === 1 ? first.promise : second.promise
    })
    const { controller } = createController({ handshake })
    const pendingFirst = controller.testPublicHandshake()
    controller.endpointUrl.value = 'https://second.test/api/mcp'
    await nextTick()
    const pendingSecond = controller.testPublicHandshake()
    callbacks[0]?.onPhase?.('initialize', 'error')
    second.resolve([{ name: 'latest', description: 'latest tool' }])
    await pendingSecond
    first.resolve([{ name: 'stale', description: 'stale tool' }])
    await pendingFirst
    expect(controller.discoveryState.value.status).toBe('success')
    expect(controller.displayedPublicTools.value.map((item) => item.name)).toEqual(['latest'])
    expect(controller.testPhases.value[0]?.status).toBe('idle')
  })

  it('invalidates pending completions and clears transient state on dispose', async () => {
    const load = deferred<McpTokenMetadata[]>()
    const api = createApi()
    vi.mocked(api.fetchMcpTokens).mockReturnValue(load.promise)
    const copy = deferred<void>()
    const { controller } = createController({ api, copy: () => copy.promise })
    const pendingLoad = controller.loadTokens()
    controller.transientCommand.value = 'contains-secret'
    const pendingCopy = controller.copyGeneratedCommand()
    controller.dispose()
    load.resolve([token(1)])
    copy.resolve()
    await Promise.all([pendingLoad, pendingCopy])
    expect(controller.tokens.value).toEqual([])
    expect(controller.transientCommand.value).toBe('')
    expect(controller.copiedKey.value).toBe('')
    expect(controller.loadingTokens.value).toBe(false)
  })

  it('expires copied feedback and reports copy failure without exposing copied text', async () => {
    const copy = vi.fn(async () => undefined)
    const { controller } = createController({ copy })
    await controller.copyHostInstruction()
    expect(controller.copiedKey.value).toBe('host-instruction')
    await vi.advanceTimersByTimeAsync(1800)
    expect(controller.copiedKey.value).toBe('')
    copy.mockRejectedValueOnce(new Error('clipboard denied'))
    await controller.copyHostInstruction()
    expect(controller.setupError.value).toEqual({ kind: 'key', key: 'mcp.copyFailed', params: undefined })
    expect(JSON.stringify(controller.setupError.value)).not.toContain('mcp.hostInstruction')
  })

  it('uses revoked-before-expired status precedence with injected time', () => {
    const { controller } = createController({ now: () => new Date('2026-01-02T00:00:00Z') })
    expect(controller.tokenStatus({ ...token(1), expires_at: '2026-01-01T00:00:00Z' })).toBe('expired')
    expect(controller.tokenStatus({ ...token(1), expires_at: '2026-01-01T00:00:00Z', revoked_at: '2025-01-01T00:00:00Z' })).toBe('revoked')
    expect(controller.tokenStatus(token(1))).toBe('valid')
  })

  it('builds a secret-free quick command that tracks client, shell and endpoint', () => {
    const { controller } = createController()

    expect(controller.quickCommand.value).toContain('https://example.test/api/mcp')
    expect(controller.quickCommand.value).not.toContain('Authorization')
    expect(controller.quickCommand.value).not.toContain('Bearer')

    controller.selectedClient.value = 'codex'
    expect(controller.quickCommand.value).toContain('codex mcp add aigc-news --url')
    expect(controller.quickCommand.value).not.toContain('AIGC_NEWS_MCP_TOKEN')

    controller.selectedShell.value = 'powershell'
    expect(controller.quickCommand.value).toContain('2>$null')
    expect(controller.quickCommand.value).not.toContain('$env:AIGC_NEWS_MCP_TOKEN')

    controller.endpointUrl.value = 'https://mcp.other.test/api'
    expect(controller.quickCommand.value).toContain('https://mcp.other.test/api')

    controller.endpointUrl.value = 'not a url'
    expect(controller.quickCommand.value).toBe('')
  })

  it('copies the quick command through the clipboard seam and skips empty commands', async () => {
    const copy = vi.fn(async () => undefined)
    const { controller } = createController({ copy })
    await controller.copyQuickCommand()
    expect(copy).toHaveBeenCalledWith(controller.quickCommand.value)
    expect(controller.copiedKey.value).toBe('quick-command')

    controller.endpointUrl.value = 'not a url'
    await controller.copyQuickCommand()
    expect(copy).toHaveBeenCalledTimes(1)

    copy.mockRejectedValueOnce(new Error('clipboard denied'))
    controller.endpointUrl.value = 'https://example.test/api/mcp'
    await controller.copyQuickCommand()
    expect(controller.setupError.value).toEqual({ kind: 'key', key: 'mcp.copyFailed', params: undefined })
    expect(JSON.stringify(controller.setupError.value)).not.toContain('aigc-news')
  })

  it('copies a natural-language Agent prompt with the selected setup context', async () => {
    const copy = vi.fn(async (_text: string) => undefined)
    const { controller } = createController({ copy })
    controller.selectedShell.value = 'bash'
    controller.transientCommand.value = 'setup-command-with-secret'

    await controller.copyAgentSetupPrompt()

    const prompt = vi.mocked(copy).mock.calls[0]?.[0] ?? ''
    expect(prompt).toContain('mcp.agentSetup.prompt')
    expect(prompt).toContain('Claude Code')
    expect(prompt).toContain('https://example.test/api/mcp')
    expect(prompt).toContain('setup-command-with-secret')
    expect(controller.copiedKey.value).toBe('agent-prompt')

    controller.selectedShell.value = 'powershell'
    await nextTick()
    expect(controller.transientCommand.value).toBe('')
    expect(controller.copiedKey.value).toBe('')
  })

  it('exposes a reactive isLoggedIn state derived from the injected getter', async () => {
    const loggedIn = ref(false)
    const { controller } = createController({ isLoggedIn: () => loggedIn.value })
    expect(controller.isLoggedIn.value).toBe(false)

    loggedIn.value = true
    await nextTick()
    expect(controller.isLoggedIn.value).toBe(true)
  })

  it('forwards requestLogin to the injected navigateToLogin seam', async () => {
    const navigateToLogin = vi.fn(async () => undefined)
    const { controller } = createController({ navigateToLogin })
    await controller.requestLogin()
    expect(navigateToLogin).toHaveBeenCalledOnce()
  })
})

describe('MCP connect controller connection watch', () => {
  beforeEach(() => vi.useFakeTimers({ now: Date.parse('2026-10-05T12:00:00Z') }))
  afterEach(() => vi.useRealTimers())

  it('watches the created token until the client first uses it', async () => {
    const api = createApi()
    vi.mocked(api.fetchMcpTokens).mockResolvedValue([token(1)])
    const { controller } = createController({ api })

    await controller.startSetup()
    expect(controller.connection.status.value).toBe('waiting')
    vi.mocked(api.fetchMcpTokens).mockClear()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(api.fetchMcpTokens).toHaveBeenCalledOnce()
    expect(controller.connection.status.value).toBe('waiting')

    vi.mocked(api.fetchMcpTokens).mockResolvedValue([{ ...token(1), last_used_at: '2026-10-05T12:00:04Z' }])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(controller.connection.status.value).toBe('connected')
    expect(controller.connection.fresh.value).toBe(true)
    expect(controller.connection.lastUsedAt.value).toBe('2026-10-05T12:00:04Z')
  })

  it('looks again quickly after the command is copied', async () => {
    const api = createApi()
    vi.mocked(api.fetchMcpTokens).mockResolvedValue([token(1)])
    const { controller } = createController({ api, copy: vi.fn(async () => undefined) })

    await controller.startSetup()
    await vi.advanceTimersByTimeAsync(600_000)
    expect(controller.connection.status.value).toBe('paused')
    vi.mocked(api.fetchMcpTokens).mockClear()

    await controller.copyGeneratedCommand()
    expect(controller.connection.status.value).toBe('waiting')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(api.fetchMcpTokens).toHaveBeenCalledOnce()
  })

  it('stops watching once the command is invalidated, on sign-out and on dispose', async () => {
    const api = createApi()
    vi.mocked(api.fetchMcpTokens).mockResolvedValue([token(1)])
    const { controller } = createController({ api })

    await controller.startSetup()
    controller.selectedShell.value = controller.selectedShell.value === 'bash' ? 'powershell' : 'bash'
    await nextTick()
    expect(controller.connection.status.value).toBe('idle')

    await controller.startSetup()
    expect(controller.connection.status.value).toBe('waiting')
    controller.clearAuthenticatedState()
    expect(controller.connection.status.value).toBe('idle')

    await controller.startSetup()
    controller.dispose()
    expect(controller.connection.status.value).toBe('idle')
    vi.mocked(api.fetchMcpTokens).mockClear()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(api.fetchMcpTokens).not.toHaveBeenCalled()
  })
})

describe('MCP connect controller browser authorization', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('defaults OAuth-capable clients to browser authorization and leaves token-only clients on tokens', () => {
    const controller = useMcpConnectController({ api: createApi(), isLoggedIn: () => false })
    expect(controller.authMode.value).toBe('oauth')
    expect(controller.oauthCommand.value).toContain(MCP_OAUTH_ENDPOINT)
    expect(controller.oauthCommand.value).toContain('mcp login aigc-news')
    expect(controller.oauthCommand.value).not.toContain('Bearer')

    controller.selectedClient.value = 'cline-roo'
    expect(controller.authMode.value).toBe('token')
    expect(controller.oauthCommand.value).toBe('')
    controller.dispose()
  })

  it('lets guests copy the OAuth command without signing in or creating a token', async () => {
    const copy = vi.fn(async (_text: string) => undefined)
    const navigateToLogin = vi.fn(async () => undefined)
    const { api, controller } = createController({ authMode: 'oauth', copy, isLoggedIn: () => false, navigateToLogin })

    await controller.startSetup()
    expect(navigateToLogin).not.toHaveBeenCalled()
    expect(api.createMcpToken).not.toHaveBeenCalled()

    await controller.copyGeneratedCommand()
    expect(copy).toHaveBeenCalledWith(controller.oauthCommand.value)
    expect(controller.copiedKey.value).toBe('command')
    expect(controller.transientCommand.value).toBe('')
    expect(controller.connection.status.value).toBe('idle')
  })

  it('never issues a token from the page in OAuth mode, even when signed in', async () => {
    const { api, controller } = createController({ authMode: 'oauth' })
    await controller.startSetup()
    expect(api.createMcpToken).not.toHaveBeenCalled()
    expect(controller.transientCommand.value).toBe('')
  })

  it('builds the Agent prompt from the OAuth command and the fixed endpoint', async () => {
    const copy = vi.fn(async (_text: string) => undefined)
    const { controller } = createController({ authMode: 'oauth', copy })
    controller.selectedShell.value = 'bash'
    await nextTick()

    await controller.copyAgentSetupPrompt()

    const prompt = vi.mocked(copy).mock.calls[0]?.[0] ?? ''
    expect(prompt).toContain('mcpOAuthSetup.agentPrompt')
    expect(prompt).toContain('Claude Code')
    expect(prompt).toContain(MCP_OAUTH_ENDPOINT)
    expect(prompt).toContain('claude mcp login aigc-news')
    expect(prompt).not.toContain('https://example.test/api/mcp')
    expect(controller.copiedKey.value).toBe('agent-prompt')
  })

  it('remembers the manual-token choice across clients until browser authorization is picked again', () => {
    const { controller } = createController({ authMode: 'oauth' })
    controller.setAuthMode('token')
    expect(controller.authMode.value).toBe('token')
    controller.selectedClient.value = 'codex'
    expect(controller.authMode.value).toBe('token')
    expect(controller.authModeFor(clientById('cursor'))).toBe('token')

    controller.setAuthMode('oauth')
    expect(controller.authMode.value).toBe('oauth')
    expect(controller.authModeFor(clientById('cline-roo'))).toBe('token')
  })

  it('drops a generated token command when switching to browser authorization', async () => {
    const { api, controller } = createController()
    await controller.startSetup()
    expect(api.createMcpToken).toHaveBeenCalledOnce()
    expect(controller.transientCommand.value).toContain('secret')
    expect(controller.connection.status.value).toBe('waiting')

    controller.setAuthMode('oauth')
    await nextTick()
    expect(controller.transientCommand.value).toBe('')
    expect(controller.connection.status.value).toBe('idle')
  })

  it('clears a stale error when the mode changes', async () => {
    const copy = vi.fn(async () => { throw new Error('clipboard denied') })
    const { controller } = createController({ authMode: 'oauth', copy })
    await controller.copyGeneratedCommand()
    expect(controller.setupError.value).toEqual({ kind: 'key', key: 'mcp.copyFailed', params: undefined })

    controller.setAuthMode('token')
    expect(controller.setupError.value).toBeNull()
  })
})
