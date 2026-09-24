import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ route: { fullPath: '/xboard?tab=hot' } }))

vi.mock('vue-router', () => ({ useRoute: () => mocks.route }))
vi.mock('@/services/http/fallbackEntry', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/http/fallbackEntry')>()
  return {
    ...actual,
    fallbackEntryState: actual.createFallbackEntryState({
      hostname: () => 'aigcnews.cn',
      online: () => true,
      currentPath: () => '/',
      probe: async () => true,
      redirect: () => {
        throw new Error('a loaded page must not redirect')
      },
    }),
  }
})

import FallbackEntryNotice from './FallbackEntryNotice.vue'
import i18n, { setAppLocale } from '@/i18n'
import { fallbackEntryState } from '@/services/http/fallbackEntry'

let unmount: (() => void) | undefined
const networkError = { code: 'ERR_NETWORK' }

describe('FallbackEntryNotice', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('zh-CN')
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('links the current route to the backup entry when a loaded page loses the network and can be dismissed', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(FallbackEntryNotice)
    app.use(i18n)
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    expect(document.body.querySelector('[role="status"]')).toBeNull()

    fallbackEntryState.recordResponse()
    fallbackEntryState.recordFailure(networkError)
    fallbackEntryState.recordFailure(networkError)
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    const notice = document.body.querySelector('[role="status"]') as HTMLElement
    expect(notice.textContent).toContain('当前网络连不上 AIGC NEWS 主站')
    const link = notice.querySelector('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('https://aigcradar.online/xboard?tab=hot')
    expect(link.textContent).toBe('打开备用入口 aigcradar.online')

    ;(notice.querySelector('button') as HTMLButtonElement).click()
    await nextTick()
    expect(document.body.querySelector('[role="status"]')).toBeNull()
  })
})
