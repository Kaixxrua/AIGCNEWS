import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { monitorApi } from '@/services/monitor/monitorApi'
import { useAuthStore } from '@/stores/authStore'
import { useEnrichmentAlertStore } from './enrichmentAlertStore'

vi.mock('@/services/monitor/monitorApi', () => ({
  monitorApi: { fetchGithubEnrichmentStatus: vi.fn() },
}))

const mockedFetchStatus = vi.mocked(monitorApi.fetchGithubEnrichmentStatus)

const makeAdmin = () => {
  const auth = useAuthStore()
  auth.status = 'authenticated'
  auth.user = { user_id: 1, email: 'admin@example.com', role: 'admin' }
  return auth
}

describe('enrichment alert store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    mockedFetchStatus.mockReset()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('stays silent for non-admin users and never polls', async () => {
    const store = useEnrichmentAlertStore()
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000)
    expect(mockedFetchStatus).not.toHaveBeenCalled()
    expect(store.failedCount).toBe(0)
    expect(store.hasFailures).toBe(false)
  })

  it('fetches immediately for admins and raises the alert when failures exist', async () => {
    makeAdmin()
    mockedFetchStatus.mockResolvedValue({ eligible: 100, succeeded: 95, failed: 3, pending: 2 })
    const store = useEnrichmentAlertStore()
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedFetchStatus).toHaveBeenCalledOnce()
    expect(store.failedCount).toBe(3)
    expect(store.hasFailures).toBe(true)
  })

  it('polls every five minutes while admin stays logged in', async () => {
    makeAdmin()
    mockedFetchStatus.mockResolvedValue({ eligible: 100, succeeded: 100, failed: 0, pending: 0 })
    useEnrichmentAlertStore()
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedFetchStatus).toHaveBeenCalledOnce()

    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(mockedFetchStatus).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(mockedFetchStatus).toHaveBeenCalledTimes(3)
  })

  it('clears the alert and stops polling when the admin logs out', async () => {
    const auth = makeAdmin()
    mockedFetchStatus.mockResolvedValue({ eligible: 100, succeeded: 95, failed: 5, pending: 0 })
    const store = useEnrichmentAlertStore()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.failedCount).toBe(5)

    auth.status = 'anonymous'
    auth.user = null
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000)
    expect(store.failedCount).toBe(0)
    expect(store.hasFailures).toBe(false)
    expect(mockedFetchStatus).toHaveBeenCalledOnce()
  })

  it('keeps the last known count through transient fetch failures', async () => {
    makeAdmin()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedFetchStatus.mockResolvedValueOnce({ eligible: 100, succeeded: 95, failed: 4, pending: 1 })
    const store = useEnrichmentAlertStore()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.failedCount).toBe(4)

    mockedFetchStatus.mockRejectedValueOnce(new Error('gateway 503'))
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(store.failedCount).toBe(4)
    consoleError.mockRestore()
  })
})
