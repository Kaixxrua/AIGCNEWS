import { describe, expect, it, vi } from 'vitest'
import {
  FALLBACK_ENTRY_ORIGIN,
  buildFallbackEntryUrl,
  createFallbackEntryState,
  isNetworkLevelFailure,
  isPrimaryEntryHost,
} from './fallbackEntry'

const networkError = { code: 'ERR_NETWORK', message: 'Network Error' }

type Probe = (url: string) => Promise<boolean>

function stateFor(hostname: string, { online = true, probe = (async () => true) as Probe } = {}) {
  const redirect = vi.fn()
  const probeMock = vi.fn(probe)
  const state = createFallbackEntryState({
    hostname: () => hostname,
    online: () => online,
    currentPath: () => '/xboard?tab=hot#top',
    probe: probeMock,
    redirect,
  })
  return { state, redirect, probe: probeMock }
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('fallback entry', () => {
  it('points the backup entry at the all-lines Tokyo mirror', () => {
    expect(FALLBACK_ENTRY_ORIGIN).toBe('https://aigcradar.online')
    expect(buildFallbackEntryUrl('/xboard?tab=hot#top')).toBe('https://aigcradar.online/xboard?tab=hot#top')
    expect(buildFallbackEntryUrl('papers')).toBe('https://aigcradar.online/papers')
  })

  it('only treats response-less ERR_NETWORK failures as network-level', () => {
    expect(isNetworkLevelFailure(networkError)).toBe(true)
    expect(isNetworkLevelFailure({ code: 'ERR_CANCELED' })).toBe(false)
    expect(isNetworkLevelFailure({ code: 'ECONNABORTED' })).toBe(false)
    expect(isNetworkLevelFailure({ code: 'ERR_NETWORK', response: { status: 502 } })).toBe(false)
    expect(isNetworkLevelFailure(null)).toBe(false)
  })

  it('limits fallback to the primary production hostnames', () => {
    expect(isPrimaryEntryHost('aigcnews.cn')).toBe(true)
    expect(isPrimaryEntryHost('www.aigcnews.cn')).toBe(true)
    expect(isPrimaryEntryHost('aigcradar.online')).toBe(false)
    expect(isPrimaryEntryHost('localhost')).toBe(false)
  })

  it('redirects to the mirror when the primary site never loaded and the mirror is reachable', async () => {
    const { state, redirect, probe } = stateFor('aigcnews.cn')
    state.recordFailure(networkError)
    await settle()
    expect(probe).not.toHaveBeenCalled()
    state.recordFailure(networkError)
    state.recordFailure(networkError)
    await settle()
    expect(probe).toHaveBeenCalledOnce()
    expect(probe.mock.calls[0]![0]).toMatch(/^https:\/\/aigcradar\.online\/favicon\.svg\?probe=\d+$/)
    expect(redirect).toHaveBeenCalledExactlyOnceWith('https://aigcradar.online/xboard?tab=hot#top')
    expect(state.shouldOffer.value).toBe(false)
  })

  it('never redirects after the site has loaded; offers a dismissible notice instead', async () => {
    const { state, redirect } = stateFor('www.aigcnews.cn')
    state.recordResponse()
    state.recordFailure(networkError)
    state.recordFailure(networkError)
    await settle()
    expect(redirect).not.toHaveBeenCalled()
    expect(state.shouldOffer.value).toBe(true)
    state.dismiss()
    expect(state.shouldOffer.value).toBe(false)
  })

  it('neither redirects nor offers when the mirror is unreachable too', async () => {
    const { state, redirect } = stateFor('aigcnews.cn', { probe: async () => false })
    state.recordFailure(networkError)
    state.recordFailure(networkError)
    await settle()
    expect(redirect).not.toHaveBeenCalled()
    expect(state.shouldOffer.value).toBe(false)
  })

  it('cancels the redirect when the primary site recovers during the probe', async () => {
    let finishProbe: (reachable: boolean) => void = () => {}
    const { state, redirect } = stateFor('aigcnews.cn', {
      probe: () => new Promise<boolean>((resolve) => { finishProbe = resolve }),
    })
    state.recordFailure(networkError)
    state.recordFailure(networkError)
    state.recordResponse()
    finishProbe(true)
    await settle()
    expect(redirect).not.toHaveBeenCalled()
    expect(state.shouldOffer.value).toBe(false)
  })

  it('resets the failure streak on any HTTP response, including errors', async () => {
    const { state, redirect, probe } = stateFor('aigcnews.cn')
    state.recordFailure(networkError)
    state.recordFailure({ response: { status: 500 } })
    state.recordFailure(networkError)
    await settle()
    expect(probe).not.toHaveBeenCalled()
    expect(redirect).not.toHaveBeenCalled()
  })

  it('ignores cancellations and timeouts in the streak', async () => {
    const { state, probe } = stateFor('aigcnews.cn')
    state.recordFailure(networkError)
    state.recordFailure({ code: 'ERR_CANCELED' })
    state.recordFailure({ code: 'ECONNABORTED' })
    await settle()
    expect(probe).not.toHaveBeenCalled()
  })

  it('stays inert on the mirror itself and while offline', async () => {
    for (const { state, redirect, probe } of [stateFor('aigcradar.online'), stateFor('aigcnews.cn', { online: false })]) {
      state.recordFailure(networkError)
      state.recordFailure(networkError)
      await settle()
      expect(probe).not.toHaveBeenCalled()
      expect(redirect).not.toHaveBeenCalled()
      expect(state.shouldOffer.value).toBe(false)
    }
  })
})
