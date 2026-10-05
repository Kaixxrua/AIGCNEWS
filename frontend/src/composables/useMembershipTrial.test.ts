import { effectScope, nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MembershipTrialApi } from '@/services/membership/membershipTrialApi'
import type { MembershipTrialStatus } from '@/features/membership/membershipTrial'
import { useMembershipTrial } from './useMembershipTrial'

const auth = vi.hoisted(() => ({
  box: null as null | { status: string; userId: number | null; fetchMe: ReturnType<typeof vi.fn> },
}))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  auth.box ??= reactive({ status: 'anonymous', userId: null as number | null, fetchMe: vi.fn() })
  return { useAuthStore: () => auth.box }
})

const status = (overrides: Partial<MembershipTrialStatus> = {}): MembershipTrialStatus => ({
  days: 7,
  available: true,
  active: false,
  started_at: null,
  expires_at: null,
  ...overrides,
})

const activeStatus = status({
  available: false,
  active: true,
  started_at: '2026-10-05T12:00:00+00:00',
  expires_at: '2026-10-12T12:00:00+00:00',
})

const conflict = (detail: string) => Object.assign(new Error('Conflict'), { response: { status: 409, data: { detail } } })

let scope: ReturnType<typeof effectScope> | null = null
const setup = (api: MembershipTrialApi) => {
  scope = effectScope()
  return scope.run(() => useMembershipTrial(api))!
}

const fakeApi = () => ({
  getStatus: vi.fn<MembershipTrialApi['getStatus']>(),
  start: vi.fn<MembershipTrialApi['start']>(),
})

beforeEach(() => {
  auth.box!.status = 'anonymous'
  auth.box!.userId = null
  auth.box!.fetchMe = vi.fn(async () => undefined)
})

afterEach(() => {
  scope?.stop()
  scope = null
})

describe('useMembershipTrial', () => {
  it('offers sign-in to guests without asking the server', async () => {
    const api = fakeApi()
    const trial = setup(api)
    await flushPromises()

    expect(trial.offer.value).toBe('guest')
    expect(api.getStatus).not.toHaveBeenCalled()
  })

  it('shows nothing while auth is still restoring', async () => {
    auth.box!.status = 'initializing'
    const api = fakeApi()
    const trial = setup(api)
    await flushPromises()

    expect(trial.offer.value).toBe('none')
    expect(api.getStatus).not.toHaveBeenCalled()
  })

  it('reads the status once signed in and again for another account', async () => {
    const api = fakeApi()
    api.getStatus.mockResolvedValueOnce(status()).mockResolvedValueOnce(status({ available: false }))
    const trial = setup(api)

    auth.box!.status = 'authenticated'
    auth.box!.userId = 7
    await flushPromises()
    expect(trial.offer.value).toBe('available')

    auth.box!.userId = 8
    await flushPromises()
    expect(api.getStatus).toHaveBeenCalledTimes(2)
    expect(trial.offer.value).toBe('none')
  })

  it('drops a status that arrives after a newer request', async () => {
    let resolveFirst: (value: MembershipTrialStatus) => void = () => undefined
    const api = fakeApi()
    api.getStatus
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce(status({ available: false }))
    auth.box!.status = 'authenticated'
    auth.box!.userId = 7
    const trial = setup(api)

    auth.box!.userId = 8
    await flushPromises()
    resolveFirst(status())
    await flushPromises()

    expect(trial.offer.value).toBe('none')
  })

  it('hides the entry when the status cannot be read', async () => {
    const api = fakeApi()
    api.getStatus.mockRejectedValue(Object.assign(new Error('Not Found'), { response: { status: 404 } }))
    auth.box!.status = 'authenticated'
    auth.box!.userId = 7
    const trial = setup(api)
    await flushPromises()

    expect(trial.offer.value).toBe('none')
  })

  it('starts the trial once and refreshes the signed-in identity', async () => {
    const api = fakeApi()
    api.getStatus.mockResolvedValue(status())
    let finish: (value: MembershipTrialStatus) => void = () => undefined
    api.start.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    auth.box!.status = 'authenticated'
    auth.box!.userId = 7
    const trial = setup(api)
    await flushPromises()

    const first = trial.start()
    void trial.start()
    await nextTick()
    expect(trial.starting.value).toBe(true)
    finish(activeStatus)
    await first

    expect(api.start).toHaveBeenCalledTimes(1)
    expect(trial.offer.value).toBe('active')
    expect(trial.starting.value).toBe(false)
    expect(trial.messageKey.value).toBeNull()
    expect(auth.box!.fetchMe).toHaveBeenCalledTimes(1)
  })

  it('catches up with the server after a conflict', async () => {
    const api = fakeApi()
    api.getStatus.mockResolvedValueOnce(status()).mockResolvedValueOnce(status({ available: false }))
    api.start.mockRejectedValue(conflict('trial_already_used'))
    auth.box!.status = 'authenticated'
    auth.box!.userId = 7
    const trial = setup(api)
    await flushPromises()

    await trial.start()

    expect(trial.messageKey.value).toBe('membership.trial.alreadyUsed')
    expect(api.getStatus).toHaveBeenCalledTimes(2)
    expect(trial.offer.value).toBe('none')
    expect(auth.box!.fetchMe).toHaveBeenCalledTimes(1)
  })

  it('keeps the button for another try after other failures', async () => {
    const api = fakeApi()
    api.getStatus.mockResolvedValue(status())
    api.start.mockRejectedValue(new Error('Network Error'))
    auth.box!.status = 'authenticated'
    auth.box!.userId = 7
    const trial = setup(api)
    await flushPromises()

    await trial.start()

    expect(trial.messageKey.value).toBe('membership.trial.failed')
    expect(trial.offer.value).toBe('available')
    expect(api.getStatus).toHaveBeenCalledTimes(1)
    expect(auth.box!.fetchMe).not.toHaveBeenCalled()
  })

  it('does not start for guests', async () => {
    const api = fakeApi()
    const trial = setup(api)
    await flushPromises()

    await trial.start()

    expect(api.start).not.toHaveBeenCalled()
  })
})
