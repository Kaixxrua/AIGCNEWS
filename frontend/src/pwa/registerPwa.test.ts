import { readFileSync } from 'node:fs'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { registerSW } = vi.hoisted(() => ({ registerSW: vi.fn() }))

vi.mock('virtual:pwa-register', () => ({ registerSW }))

import { registerPwa } from './registerPwa'

const viteConfig = readFileSync(`${process.cwd()}/vite.config.ts`, 'utf8')

describe('registerPwa', () => {
  beforeEach(() => {
    registerSW.mockReset()
    vi.useFakeTimers()
    vi.spyOn(document, 'readyState', 'get').mockReturnValue('complete')
    vi.stubGlobal('requestIdleCallback', undefined)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('leaves the first navigation free of precache traffic and still auto-updates', () => {
    registerPwa()
    vi.advanceTimersByTime(9999)
    expect(registerSW).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(registerSW).toHaveBeenCalledOnce()
    expect(registerSW).toHaveBeenCalledWith(expect.objectContaining({ immediate: true }))
    expect(registerSW.mock.calls[0]?.[0]).not.toHaveProperty('onNeedRefresh')
  })

  it('starts the grace period after load, even when the document takes a long time', () => {
    vi.spyOn(document, 'readyState', 'get').mockReturnValue('loading')
    registerPwa()
    vi.advanceTimersByTime(30_000)
    expect(registerSW).not.toHaveBeenCalled()
    window.dispatchEvent(new Event('load'))
    vi.advanceTimersByTime(9999)
    expect(registerSW).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    window.dispatchEvent(new Event('load'))
    vi.runAllTimers()
    expect(registerSW).toHaveBeenCalledOnce()
  })

  it('uses bounded idle scheduling when the browser supports it', () => {
    const idle = vi.fn()
    vi.stubGlobal('requestIdleCallback', idle)
    registerPwa()
    vi.advanceTimersByTime(10_000)
    expect(registerSW).not.toHaveBeenCalled()
    expect(idle).toHaveBeenCalledWith(expect.any(Function), { timeout: 5000 })
    idle.mock.calls[0]![0]()
    expect(registerSW).toHaveBeenCalledOnce()
  })

  it('builds the service worker to activate updates automatically', () => {
    expect(viteConfig).toContain("registerType: 'autoUpdate'")
    expect(viteConfig).toContain('skipWaiting: true')
    expect(viteConfig).toContain('clientsClaim: true')
  })
})
