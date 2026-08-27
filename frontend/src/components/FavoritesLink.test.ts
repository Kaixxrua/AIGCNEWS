import { createApp } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FavoritesLink from './FavoritesLink.vue'
import i18n, { setAppLocale } from '@/i18n'
import {
  addMyToolWebsite,
  fetchMyProjectCollection,
  removeMyToolWebsite,
} from '@/services/projects/projectApi'
import { showToast } from '@/composables/useToast'

const { requestLoginSpy, authBox } = vi.hoisted(() => ({
  requestLoginSpy: vi.fn(),
  authBox: { current: null as null | { isLoggedIn: boolean } },
}))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  if (!authBox.current) authBox.current = reactive({ isLoggedIn: false })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useLoginPrompt', () => ({
  useLoginPrompt: () => ({ requestLogin: requestLoginSpy }),
}))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/dashboard' }) }))
vi.mock('@/services/projects/projectApi', () => ({
  addMyToolWebsite: vi.fn(),
  fetchMyProjectCollection: vi.fn(),
  removeMyToolWebsite: vi.fn(),
}))

const addMock = vi.mocked(addMyToolWebsite)
const collectionMock = vi.mocked(fetchMyProjectCollection)
const removeMock = vi.mocked(removeMyToolWebsite)
const toastMock = vi.mocked(showToast)

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

let unmount: (() => void) | undefined

const mountButton = () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(FavoritesLink)
  app.use(i18n)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host.querySelector('button') as HTMLButtonElement
}

describe('FavoritesLink（收藏本站开关）', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
    authBox.current!.isLoggedIn = false
    collectionMock.mockResolvedValue({ items: [] } as never)
    addMock.mockResolvedValue({ status: 'succeeded', message: '', duplicate: false, item: { website_id: 7 } } as never)
    removeMock.mockResolvedValue({ status: 'succeeded', message: '', deleted: true, website_id: 7 } as never)
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    vi.clearAllMocks()
  })

  it('未登录点击只弹登录，不调用任何收藏 API', async () => {
    const button = mountButton()
    await flush()
    button.click()
    await flush()
    expect(requestLoginSpy).toHaveBeenCalledWith('/dashboard')
    expect(addMock).not.toHaveBeenCalled()
    expect(removeMock).not.toHaveBeenCalled()
  })

  it('未登录点击后完成登录，自动执行收藏', async () => {
    const button = mountButton()
    await flush()
    button.click()
    await flush()
    authBox.current!.isLoggedIn = true
    await flush()
    await flush()
    expect(addMock).toHaveBeenCalledWith(window.location.origin)
    expect(toastMock).toHaveBeenCalledWith('已收藏本站，可到项目库「我的网页」查看')
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })

  it('登录且本站未收藏：点击加入收藏并反馈位置', async () => {
    authBox.current!.isLoggedIn = true
    const button = mountButton()
    await flush()
    expect(button.getAttribute('aria-pressed')).toBe('false')
    button.click()
    await flush()
    await flush()
    expect(addMock).toHaveBeenCalledWith(window.location.origin)
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })

  it('登录且本站已收藏（含 www 前缀归一）：点击移出收藏', async () => {
    authBox.current!.isLoggedIn = true
    collectionMock.mockResolvedValue({
      items: [{ website_id: 42, url: `http://www.${window.location.hostname}/` }],
    } as never)
    const button = mountButton()
    await flush()
    await flush()
    expect(button.getAttribute('aria-pressed')).toBe('true')
    button.click()
    await flush()
    await flush()
    expect(removeMock).toHaveBeenCalledWith(42)
    expect(toastMock).toHaveBeenCalledWith('已取消收藏本站')
    expect(button.getAttribute('aria-pressed')).toBe('false')
  })

  it('收藏接口返回 duplicate 时提示已在收藏中', async () => {
    authBox.current!.isLoggedIn = true
    addMock.mockResolvedValue({ status: 'succeeded', message: '', duplicate: true, item: { website_id: 9 } } as never)
    const button = mountButton()
    await flush()
    button.click()
    await flush()
    await flush()
    expect(toastMock).toHaveBeenCalledWith('本站已在你的收藏中')
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })
})
