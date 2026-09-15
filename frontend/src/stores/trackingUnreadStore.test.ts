import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia'
import { nextTick, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { trackingApi } from '@/services/tracking/trackingApi'
import { useTrackingUnreadStore } from './trackingUnreadStore'
import type { TrackingUnread } from '@/features/tracking/trackingModel'

const { account } = vi.hoisted(() => ({ account: { value: {} as { token: string; userId: number; isLoggedIn: boolean } } }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => account.value }))
vi.mock('@/services/tracking/trackingApi', () => ({ trackingApi: { unread: vi.fn(), markRead: vi.fn() } }))
const status = (latest: number, read = 0): TrackingUnread => ({
  latest_digest_id: latest, last_read_digest_id: read, unread: latest > read,
})
let pinia: Pinia
const settle = async () => { await Promise.resolve(); await nextTick() }
beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  Object.defineProperty(document, 'hidden', { value: false, configurable: true })
  account.value = reactive({ token: 'test-a', userId: 1, isLoggedIn: true })
  pinia = createPinia()
  setActivePinia(pinia)
  vi.mocked(trackingApi.unread).mockResolvedValue(status(10))
  vi.mocked(trackingApi.markRead).mockImplementation(async (id) => status(10, id))
})
afterEach(() => {
  disposePinia(pinia)
  vi.useRealTimers()
  Reflect.deleteProperty(document, 'hidden')
})

describe('tracking unread notifications', () => {
  it('restores server state on mount and clears only after a successful exact receipt', async () => {
    const store = useTrackingUnreadStore()
    await settle()
    expect(store.hasUnread).toBe(true)
    await store.markRead(10)
    expect(trackingApi.markRead).toHaveBeenCalledWith(10)
    expect(store.hasUnread).toBe(false)
    await store.markRead(10)
    expect(trackingApi.markRead).toHaveBeenCalledTimes(1)
  })
  it('retains the red dot after failures and allows a receipt retry', async () => {
    const store = useTrackingUnreadStore()
    await settle()
    vi.mocked(trackingApi.markRead).mockRejectedValueOnce(new Error('offline'))
    await store.markRead(10)
    expect(store.hasUnread).toBe(true)
    vi.mocked(trackingApi.unread).mockRejectedValueOnce(new Error('offline'))
    await store.refresh()
    expect(store.hasUnread).toBe(true)
    await store.markRead(10)
    expect(store.hasUnread).toBe(false)
  })
  it('does not resurrect a read dot from a stale poll, but retains a newly arrived issue', async () => {
    const store = useTrackingUnreadStore()
    await settle()
    let finish!: (value: TrackingUnread) => void
    vi.mocked(trackingApi.unread).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const poll = store.refresh()
    await store.markRead(10)
    finish(status(10))
    await poll
    expect(store.hasUnread).toBe(false)
    vi.mocked(trackingApi.unread).mockResolvedValueOnce(status(11, 10))
    await store.refresh()
    expect(store.hasUnread).toBe(true)
    await store.markRead(10)
    expect(store.hasUnread).toBe(true)
  })
  it('ignores another account’s late requests and stops polling on logout', async () => {
    let finish!: (value: TrackingUnread) => void
    vi.mocked(trackingApi.unread).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const store = useTrackingUnreadStore()
    account.value.isLoggedIn = false
    finish(status(100))
    await settle()
    expect(store.hasUnread).toBe(false)
    await vi.advanceTimersByTimeAsync(120_000)
    expect(trackingApi.unread).toHaveBeenCalledTimes(1)
    vi.mocked(trackingApi.unread).mockResolvedValue(status(0))
    account.value.userId = 2
    account.value.token = 'test-b'
    account.value.isLoggedIn = true
    await settle()
    expect(store.hasUnread).toBe(false)
  })
  it('polls only visible authenticated pages and refreshes when returning', async () => {
    const store = useTrackingUnreadStore()
    await settle()
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    await vi.advanceTimersByTimeAsync(60_000)
    await store.markRead(10)
    expect(trackingApi.unread).toHaveBeenCalledTimes(1)
    expect(trackingApi.markRead).not.toHaveBeenCalled()
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(trackingApi.unread).toHaveBeenCalledTimes(2)
  })
})
