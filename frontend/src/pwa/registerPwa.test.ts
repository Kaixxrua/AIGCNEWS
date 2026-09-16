import { readFileSync } from 'node:fs'

import { beforeEach, describe, expect, it, vi } from 'vitest'

const { registerSW } = vi.hoisted(() => ({ registerSW: vi.fn() }))

vi.mock('virtual:pwa-register', () => ({ registerSW }))

import { registerPwa } from './registerPwa'

const viteConfig = readFileSync(`${process.cwd()}/vite.config.ts`, 'utf8')

describe('registerPwa', () => {
  beforeEach(() => {
    registerSW.mockReset()
  })

  it('registers the service worker immediately without a manual refresh prompt', () => {
    registerPwa()

    expect(registerSW).toHaveBeenCalledOnce()
    expect(registerSW).toHaveBeenCalledWith(expect.objectContaining({ immediate: true }))
    expect(registerSW.mock.calls[0]?.[0]).not.toHaveProperty('onNeedRefresh')
  })

  it('builds the service worker to activate updates automatically', () => {
    expect(viteConfig).toContain("registerType: 'autoUpdate'")
    expect(viteConfig).toContain('skipWaiting: true')
    expect(viteConfig).toContain('clientsClaim: true')
  })
})
