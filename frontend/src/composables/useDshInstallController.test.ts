import { describe, expect, it, vi } from 'vitest'
import { useDshInstallController } from './useDshInstallController'

describe('useDshInstallController', () => {
  it('copies every install method and falls back to npm', async () => {
    const copy = vi.fn().mockResolvedValue(undefined)
    const controller = useDshInstallController({ copy })

    await controller.copyDshInstallCommand('npm')
    await controller.copyDshInstallCommand('github')
    await controller.copyDshInstallCommand('unknown' as any)

    expect(copy.mock.calls.map(([value]) => value)).toEqual([
      'dsh plugin --profile web add dsh-aigc-radar',
      'dsh plugin --profile web add github:Kaixxrua/dsh-aigc-radar',
      'dsh plugin --profile web add dsh-aigc-radar',
    ])
    expect(controller.copiedKey.value).toBe('dsh-install-npm')
    await controller.copyValue('dsh-patch', 'secret patch')
    expect(copy).toHaveBeenLastCalledWith('secret patch')
    expect(controller.copiedKey.value).toBe('dsh-patch')
    controller.dispose()
  })

  it('clears copied feedback and cancels it on dispose', async () => {
    let callback: (() => void) | undefined
    const cancelSchedule = vi.fn()
    const controller = useDshInstallController({
      copy: vi.fn().mockResolvedValue(undefined),
      schedule: (next) => { callback = next; return 7 as any },
      cancelSchedule,
    })

    await controller.copyDshInstallCommand('github')
    expect(controller.copiedKey.value).toBe('dsh-install-github')
    callback?.()
    expect(controller.copiedKey.value).toBe('')

    await controller.copyDshInstallCommand('npm')
    controller.dispose()
    expect(controller.copiedKey.value).toBe('')
    expect(cancelSchedule).toHaveBeenCalled()
  })

  it('reports copy failures without setting copied state', async () => {
    const onCopyError = vi.fn()
    const controller = useDshInstallController({
      copy: vi.fn().mockRejectedValue(new Error('denied')),
      onCopyError,
    })

    await controller.copyDshInstallCommand('npm')
    expect(onCopyError).toHaveBeenCalledOnce()
    expect(controller.copiedKey.value).toBe('')
  })
})
