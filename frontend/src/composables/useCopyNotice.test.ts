import { describe, expect, it, vi } from 'vitest'
import { useCopyNotice } from './useCopyNotice'

const manualTimers = () => {
  const callbacks: Array<() => void> = []
  return {
    callbacks,
    schedule: (callback: () => void) => {
      callbacks.push(callback)
      return callbacks.length as unknown as ReturnType<typeof setTimeout>
    },
    cancelSchedule: vi.fn(),
  }
}

describe('useCopyNotice', () => {
  it('marks the button that copied and lets the mark go after a moment', async () => {
    const timers = manualTimers()
    const notice = useCopyNotice(timers)
    const write = vi.fn().mockResolvedValue(undefined)

    await expect(notice.copy('prompt', write)).resolves.toBe(true)
    expect(write).toHaveBeenCalledOnce()
    expect(notice.copiedKey.value).toBe('prompt')

    timers.callbacks[0]!()
    expect(notice.copiedKey.value).toBe('')
  })

  it('moves the mark to the latest button and keeps it for the full moment', async () => {
    const timers = manualTimers()
    const notice = useCopyNotice(timers)

    await notice.copy('prompt', () => Promise.resolve())
    await notice.copy('url', () => Promise.resolve())
    expect(timers.cancelSchedule).toHaveBeenCalledOnce()
    expect(notice.copiedKey.value).toBe('url')

    // 前一颗按钮的定时器迟到也不收走新的标记。
    timers.callbacks[0]!()
    expect(notice.copiedKey.value).toBe('url')
  })

  it('reports a failed copy without marking anything', async () => {
    const onError = vi.fn()
    const notice = useCopyNotice({ onError })

    await expect(notice.copy('prompt', () => Promise.reject(new Error('denied')))).resolves.toBe(false)
    expect(onError).toHaveBeenCalledOnce()
    expect(notice.copiedKey.value).toBe('')
  })

  it('ignores copies that finish after the page left', async () => {
    const timers = manualTimers()
    const onError = vi.fn()
    const notice = useCopyNotice({ ...timers, onError })
    let finish: () => void = () => {}
    const pending = notice.copy('prompt', () => new Promise<void>((resolve) => { finish = resolve }))

    notice.dispose()
    finish()
    await expect(pending).resolves.toBe(false)
    expect(notice.copiedKey.value).toBe('')
    expect(timers.callbacks).toHaveLength(0)

    await notice.copy('prompt', () => Promise.reject(new Error('late')))
    expect(onError).not.toHaveBeenCalled()
  })

  it('cancels a pending mark on dispose', async () => {
    const timers = manualTimers()
    const notice = useCopyNotice(timers)

    await notice.copy('prompt', () => Promise.resolve())
    notice.dispose()
    expect(notice.copiedKey.value).toBe('')
    expect(timers.cancelSchedule).toHaveBeenCalledOnce()
  })
})
