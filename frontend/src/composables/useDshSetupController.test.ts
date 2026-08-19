import { describe, expect, it, vi } from 'vitest'
import { useDshSetupController } from './useDshSetupController'

describe('useDshSetupController', () => {
  it('lets guests reach a selected command without creating a token', async () => {
    const createMcpToken = vi.fn()
    const controller = useDshSetupController({ createMcpToken })
    controller.selectedMethod.value = 'npm-pinned'
    expect(await controller.next(false, false)).toBe('ok')
    expect(await controller.next(false, false)).toBe('ok')
    expect(controller.step.value).toBe(2)
    expect(controller.installLine.value).toBe('dsh plugin --profile web add dsh-aigc-radar@0.2.0')
    expect(createMcpToken).not.toHaveBeenCalled()
  })

  it('gates account identities and VIP membership before advancing', async () => {
    const controller = useDshSetupController({ createMcpToken: vi.fn() })
    controller.identity.value = 'user'
    expect(await controller.next(false, false)).toBe('login')
    expect(controller.step.value).toBe(0)
    controller.identity.value = 'vip'
    expect(await controller.next(true, false)).toBe('vip')
    expect(controller.step.value).toBe(0)
    expect(await controller.next(true, true)).toBe('ok')
    expect(controller.step.value).toBe(1)
  })

  it('creates one token and folds it into a single install line with safe quoting', async () => {
    const createMcpToken = vi.fn().mockResolvedValue({ token: "aigc_mcp_ab'cd" })
    const controller = useDshSetupController({ createMcpToken })
    controller.identity.value = 'user'
    await controller.next(true, false)
    await controller.next(true, false)
    expect(createMcpToken).toHaveBeenCalledOnce()
    expect(createMcpToken).toHaveBeenCalledWith({ client_type: 'other', client_label: 'dsh-aigc-radar' })
    const line = controller.installLine.value
    expect(line.startsWith('dsh plugin --profile web add dsh-aigc-radar && printf ')).toBe(true)
    expect(line).toContain('"        mcpToken: \'aigc_mcp_ab\'\'cd\'"')
    expect(line.endsWith('> ~/.dsh/profiles/web/cordis.patch.yml')).toBe(true)
    controller.previous()
    await controller.next(true, false)
    expect(createMcpToken).toHaveBeenCalledOnce()
  })

  it('reports token creation failure and retries successfully', async () => {
    const createMcpToken = vi.fn()
      .mockRejectedValueOnce(new Error('failed'))
      .mockResolvedValueOnce({ token: 'aigc_mcp_retry' })
    const controller = useDshSetupController({ createMcpToken })
    controller.identity.value = 'user'
    await controller.next(true, false)
    await controller.next(true, false)
    expect(controller.error.value).toBe('mcp.tokenCreateFailed')
    expect(controller.installLine.value).toBe(controller.command.value)
    expect(await controller.generate()).toBe(true)
    expect(controller.error.value).toBe('')
    expect(controller.installLine.value).toContain('aigc_mcp_retry')
    expect(createMcpToken).toHaveBeenCalledTimes(2)
  })

  it('fast-paths VIP members straight to the install step, only once', () => {
    const controller = useDshSetupController({ createMcpToken: vi.fn() })
    controller.syncAuth(true, false)
    expect(controller.step.value).toBe(0)
    controller.syncAuth(false, true)
    expect(controller.step.value).toBe(0)

    controller.syncAuth(true, true)
    expect(controller.identity.value).toBe('vip')
    expect(controller.step.value).toBe(1)

    // 用户手动返回身份步骤后，不再被强行前推
    controller.previous()
    expect(controller.step.value).toBe(0)
    controller.syncAuth(true, true)
    expect(controller.step.value).toBe(0)
  })
})
