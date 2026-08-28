import { describe, expect, it, vi } from 'vitest'
import { useDshSetupController } from './useDshSetupController'
import type { DshMcpTokenResponse } from '@/services/mcp/mcpTokenApi'

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

    controller.next()
    expect(controller.step.value).toBe(1)
    controller.previous()
    expect(controller.step.value).toBe(0)
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
    // rotate 开始即清空旧 token：失败也不回退展示旧凭证
    expect(controller.token.value).toBe('')
    expect(controller.installLine.value).toBe('')
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
