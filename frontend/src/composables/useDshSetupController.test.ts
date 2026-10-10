import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDshSetupController } from './useDshSetupController'
import type { DshMcpTokenResponse, McpTokenMetadata } from '@/services/mcp/mcpTokenApi'

// 没注入 fetchMcpTokens 的用例也不能触网：连接检测用的令牌列表默认换成空表。
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()
  return { ...actual, fetchMcpTokens: vi.fn().mockResolvedValue([]) }
})

const readyResult = (token: string, reused = false): DshMcpTokenResponse => ({
  token,
  reused,
  token_metadata: {
    id: 21,
    token_hint: 'aigc_mcp_abc...wxyz',
    scopes: ['projects:favorites:read'],
    client_type: 'other',
    client_label: 'dsh-aigc-radar',
    expires_at: null,
    revoked_at: null,
  },
})

const recoveryRequiredError = () => ({
  isAxiosError: true,
  response: { status: 409, data: { detail: { code: 'dsh_token_recovery_required', message: 'legacy' } } },
})

const axiosError = (status: number) => ({ isAxiosError: true, response: { status } })

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('useDshSetupController', () => {
  it('ensures one token and folds it into a single install line with safe quoting', async () => {
    const ensureDshMcpToken = vi.fn().mockResolvedValue(readyResult("aigc_mcp_ab'cd"))
    const controller = useDshSetupController({ ensureDshMcpToken })

    expect(await controller.ensure()).toBe(true)
    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(controller.phase.value).toBe('ready')
    expect(controller.tokenReused.value).toBe(false)
    const line = controller.installLine.value
    expect(line.startsWith('dsh plugin --profile web add dsh-aigc-radar && printf ')).toBe(true)
    expect(line).toContain('"        mcpToken: \'aigc_mcp_ab\'\'cd\'"')
    expect(line.endsWith('> ~/.dsh/profiles/web/cordis.patch.yml')).toBe(true)
  })

  it('dedupes concurrent ensure calls and short-circuits once ready', async () => {
    const gate = deferred<DshMcpTokenResponse>()
    const ensureDshMcpToken = vi.fn().mockReturnValue(gate.promise)
    const controller = useDshSetupController({ ensureDshMcpToken })

    const first = controller.ensure()
    const second = controller.ensure()
    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(controller.phase.value).toBe('loading')

    gate.resolve(readyResult('aigc_mcp_shared'))
    expect(await first).toBe(true)
    expect(await second).toBe(true)

    // ready 后重复 ensure（重新进入向导/步骤往返）不再请求
    expect(await controller.ensure()).toBe(true)
    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(controller.installLine.value).toContain('aigc_mcp_shared')
  })

  it('maps 503 to the unavailable key and retries after generic failures', async () => {
    const ensureDshMcpToken = vi.fn()
      .mockRejectedValueOnce(axiosError(503))
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(readyResult('aigc_mcp_retry'))
    const controller = useDshSetupController({ ensureDshMcpToken })

    expect(await controller.ensure()).toBe(false)
    expect(controller.phase.value).toBe('error')
    expect(controller.error.value).toBe('dsh.wizard.tokenUnavailable')
    expect(controller.installLine.value).toBe('')

    expect(await controller.ensure()).toBe(false)
    expect(controller.error.value).toBe('mcp.tokenCreateFailed')

    expect(await controller.ensure()).toBe(true)
    expect(controller.phase.value).toBe('ready')
    expect(controller.installLine.value).toContain('aigc_mcp_retry')
    expect(ensureDshMcpToken).toHaveBeenCalledTimes(3)
  })

  it('surfaces legacy hash-only tokens as an explicit recovery state', async () => {
    const ensureDshMcpToken = vi.fn().mockRejectedValue(recoveryRequiredError())
    const rotateDshMcpToken = vi.fn().mockResolvedValue(readyResult('aigc_mcp_rotated'))
    const controller = useDshSetupController({ ensureDshMcpToken, rotateDshMcpToken })

    expect(await controller.ensure()).toBe(false)
    expect(controller.phase.value).toBe('recovery')
    expect(controller.token.value).toBe('')
    expect(controller.installLine.value).toBe('')

    expect(await controller.rotate()).toBe(true)
    expect(rotateDshMcpToken).toHaveBeenCalledOnce()
    expect(controller.phase.value).toBe('ready')
    expect(controller.installLine.value).toContain('aigc_mcp_rotated')
  })

  it('rotate reports failures without leaking the old token', async () => {
    const ensureDshMcpToken = vi.fn().mockResolvedValue(readyResult('aigc_mcp_old'))
    const rotateDshMcpToken = vi.fn().mockRejectedValue(new Error('boom'))
    const controller = useDshSetupController({ ensureDshMcpToken, rotateDshMcpToken })

    await controller.ensure()
    expect(controller.phase.value).toBe('ready')

    expect(await controller.rotate()).toBe(false)
    expect(controller.phase.value).toBe('error')
    expect(controller.error.value).toBe('mcp.tokenCreateFailed')
    // rotate 开始即清空旧 token：失败也不回退展示旧凭证，也不再盯着旧 token 的连接
    expect(controller.token.value).toBe('')
    expect(controller.installLine.value).toBe('')
    expect(controller.connection.status.value).toBe('idle')
  })

  it('clears the in-memory token on auth loss and ignores late responses', async () => {
    const gate = deferred<DshMcpTokenResponse>()
    const ensureDshMcpToken = vi.fn().mockReturnValue(gate.promise)
    const controller = useDshSetupController({ ensureDshMcpToken })

    const pending = controller.ensure()
    expect(controller.phase.value).toBe('loading')

    controller.clearToken()
    gate.resolve(readyResult('aigc_mcp_late'))
    expect(await pending).toBe(false)

    // 迟到响应不得回填凭证
    expect(controller.token.value).toBe('')
    expect(controller.phase.value).toBe('idle')
    expect(controller.installLine.value).toBe('')

    // 清空后再次 ensure 走新请求（不受失效在途请求影响）
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_fresh'))
    expect(await controller.ensure()).toBe(true)
    expect(controller.installLine.value).toContain('aigc_mcp_fresh')
    expect(ensureDshMcpToken).toHaveBeenCalledTimes(2)
  })

  it('starts a fresh request when signing back in before the stale one settles', async () => {
    const stale = deferred<DshMcpTokenResponse>()
    const ensureDshMcpToken = vi.fn()
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce(readyResult('aigc_mcp_fresh'))
    const controller = useDshSetupController({ ensureDshMcpToken })

    const pending = controller.ensure()
    // 登出后马上又登录：旧请求还没回来，新的 ensure 不能等它作废后的 false。
    controller.clearToken()
    expect(await controller.ensure()).toBe(true)
    expect(ensureDshMcpToken).toHaveBeenCalledTimes(2)
    expect(controller.installLine.value).toContain('aigc_mcp_fresh')

    stale.resolve(readyResult('aigc_mcp_stale'))
    expect(await pending).toBe(false)
    expect(controller.installLine.value).toContain('aigc_mcp_fresh')
  })

  it('dispose drops the token and blocks late refills', async () => {
    const gate = deferred<DshMcpTokenResponse>()
    const ensureDshMcpToken = vi.fn().mockReturnValue(gate.promise)
    const controller = useDshSetupController({ ensureDshMcpToken })

    const pending = controller.ensure()
    controller.dispose()
    gate.resolve(readyResult('aigc_mcp_late'))
    expect(await pending).toBe(false)
    expect(controller.token.value).toBe('')

    // dispose 后的任何调用都不再触网
    expect(await controller.ensure()).toBe(false)
    expect(await controller.rotate()).toBe(false)
    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
  })

  it('never renders a command without a ready token', () => {
    const controller = useDshSetupController({ ensureDshMcpToken: vi.fn() })
    expect(controller.phase.value).toBe('idle')
    expect(controller.installLine.value).toBe('')
    // 裸安装命令仍可用于说明性展示（不含凭证）
    expect(controller.command.value).toBe('dsh plugin --profile web add dsh-aigc-radar')
  })

  it('keeps the github fallback method compatible with the composite line', async () => {
    const ensureDshMcpToken = vi.fn().mockResolvedValue(readyResult('aigc_mcp_gh'))
    const controller = useDshSetupController({ ensureDshMcpToken })
    controller.selectedMethod.value = 'github'
    await controller.ensure()
    expect(controller.installLine.value.startsWith('dsh plugin --profile web add github:Kaixxrua/dsh-aigc-radar && printf ')).toBe(true)
    expect(controller.installLine.value).toContain("mcpToken: 'aigc_mcp_gh'")
  })
})

describe('useDshSetupController connection watch', () => {
  beforeEach(() => { vi.useFakeTimers({ now: Date.parse('2026-10-05T12:00:00Z') }) })
  afterEach(() => { vi.useRealTimers() })

  const tokenRow = (lastUsedAt: string | null, id = 21): McpTokenMetadata => ({ ...readyResult('').token_metadata, id, last_used_at: lastUsedAt })

  it('waits for a fresh token to be used and then reports it connected', async () => {
    const fetchMcpTokens = vi.fn().mockResolvedValue([tokenRow(null)])
    const controller = useDshSetupController({ ensureDshMcpToken: vi.fn().mockResolvedValue(readyResult('aigc_mcp_new')), fetchMcpTokens })

    await controller.ensure()
    expect(controller.connection.status.value).toBe('waiting')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchMcpTokens).toHaveBeenCalledOnce()
    expect(controller.connection.status.value).toBe('waiting')

    fetchMcpTokens.mockResolvedValue([tokenRow('2026-10-05T12:00:04Z')])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(controller.connection.status.value).toBe('connected')
    expect(controller.connection.fresh.value).toBe(true)
    controller.dispose()
  })

  it('shows a reused token as connected before, without polling', async () => {
    const fetchMcpTokens = vi.fn()
    const reused: DshMcpTokenResponse = { ...readyResult('aigc_mcp_old', true), token_metadata: tokenRow('2026-10-02T08:00:00Z') }
    const controller = useDshSetupController({ ensureDshMcpToken: vi.fn().mockResolvedValue(reused), fetchMcpTokens })

    await controller.ensure()
    expect(controller.connection.status.value).toBe('connected')
    expect(controller.connection.fresh.value).toBe(false)
    expect(controller.connection.lastUsedAt.value).toBe('2026-10-02T08:00:00Z')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMcpTokens).not.toHaveBeenCalled()
    controller.dispose()
  })

  it('follows the new token after a rotate and lets go when the session ends', async () => {
    const fetchMcpTokens = vi.fn().mockResolvedValue([tokenRow(null, 22)])
    const controller = useDshSetupController({
      ensureDshMcpToken: vi.fn().mockResolvedValue(readyResult('aigc_mcp_old')),
      rotateDshMcpToken: vi.fn().mockResolvedValue({ ...readyResult('aigc_mcp_new'), token_metadata: tokenRow(null, 22) }),
      fetchMcpTokens,
    })

    await controller.ensure()
    await controller.rotate()
    expect(controller.connection.status.value).toBe('waiting')
    // 列表里只剩新 token 22：盯的是新的那枚，所以仍在等，而不是报「已失效」
    await vi.advanceTimersByTimeAsync(3_000)
    expect(controller.connection.status.value).toBe('waiting')

    controller.clearToken()
    expect(controller.connection.status.value).toBe('idle')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMcpTokens).toHaveBeenCalledOnce()
  })
})
