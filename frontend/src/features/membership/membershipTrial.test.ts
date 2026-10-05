import { describe, expect, it } from 'vitest'
import {
  TRIAL_DAYS,
  formatTrialEnd,
  trialErrorKey,
  trialOffer,
  type MembershipTrialStatus,
} from './membershipTrial'

const status = (overrides: Partial<MembershipTrialStatus> = {}): MembershipTrialStatus => ({
  days: 7,
  available: false,
  active: false,
  started_at: null,
  expires_at: null,
  ...overrides,
})

const conflict = (detail: unknown) => Object.assign(new Error('Conflict'), { response: { status: 409, data: { detail } } })

describe('membership trial model', () => {
  it('mirrors the backend trial length', () => {
    expect(TRIAL_DAYS).toBe(7)
  })

  it('offers sign-in to guests and nothing until the auth state settles', () => {
    expect(trialOffer('anonymous', null)).toBe('guest')
    expect(trialOffer('initializing', status({ available: true }))).toBe('none')
    expect(trialOffer('degraded', status({ available: true }))).toBe('none')
  })

  it('follows the server status for signed-in users', () => {
    expect(trialOffer('authenticated', null)).toBe('none')
    expect(trialOffer('authenticated', status({ available: true }))).toBe('available')
    expect(trialOffer('authenticated', status({ active: true }))).toBe('active')
    expect(trialOffer('authenticated', status())).toBe('none')
  })

  it('maps the conflict codes and folds every other failure into one message', () => {
    expect(trialErrorKey(conflict('trial_already_used'))).toBe('membership.trial.alreadyUsed')
    expect(trialErrorKey(conflict('already_member'))).toBe('membership.trial.alreadyMember')
    expect(trialErrorKey(conflict('something_new'))).toBe('membership.trial.failed')
    expect(trialErrorKey(Object.assign(new Error('boom'), { response: { status: 500, data: { detail: 'already_member' } } }))).toBe(
      'membership.trial.failed',
    )
    expect(trialErrorKey(new Error('Network Error'))).toBe('membership.trial.failed')
    expect(trialErrorKey(null)).toBe('membership.trial.failed')
  })

  it('formats the trial end to the minute and tolerates missing or broken values', () => {
    const iso = '2026-10-12T12:05:00+00:00'
    const expected = new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(
      Date.parse(iso),
    )

    expect(formatTrialEnd(iso, 'zh-CN')).toBe(expected)
    expect(formatTrialEnd(null, 'zh-CN')).toBe('')
    expect(formatTrialEnd(undefined, 'en-US')).toBe('')
    expect(formatTrialEnd('not a date', 'en-US')).toBe('')
  })
})
