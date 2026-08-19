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
    expect(controller.command.value).toContain('dsh-aigc-radar@0.2.0')
    expect(controller.patch.value).toBe('')
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

  it('creates one token, safely quotes it in YAML, and reuses it after stepping back', async () => {
    const createMcpToken = vi.fn().mockResolvedValue({ token: "aigc_mcp_ab'cd" })
    const controller = useDshSetupController({ createMcpToken })
    controller.identity.value = 'user'
    await controller.next(true, false)
    await controller.next(true, false)
    expect(createMcpToken).toHaveBeenCalledOnce()
    expect(createMcpToken).toHaveBeenCalledWith({ client_type: 'other', client_label: 'dsh-aigc-radar' })
    expect(controller.patch.value).toContain("mcpToken: 'aigc_mcp_ab''cd'")
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
    expect(controller.token.value).toBe('')
    expect(await controller.generate()).toBe(true)
    expect(controller.error.value).toBe('')
    expect(controller.token.value).toBe('aigc_mcp_retry')
    expect(createMcpToken).toHaveBeenCalledTimes(2)
  })
})
