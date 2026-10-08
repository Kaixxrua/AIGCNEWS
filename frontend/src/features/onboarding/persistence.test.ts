import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MEMORY_KEY, claimGuest, readProgress, readTerminal, saveProgress, saveTerminal } from './persistence'
import { availableSteps, TOUR_STEPS } from './steps'
import { onboardingEn, onboardingZh } from '@/i18n/locales/onboarding'
import { placeCard, spotlightBox } from './geometry'

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); vi.restoreAllMocks() })

describe('tour memory and account handoff', () => {
  it('claims guest dismissal once, while another account keeps its own state', () => {
    saveTerminal('guest', 'skipped')
    claimGuest('user:7')
    expect(readTerminal('user:7')).toEqual({ status: 'skipped', pending: true })
    claimGuest('user:8')
    expect(readTerminal('user:8')).toBeUndefined()
    expect(readTerminal('guest')).toBeDefined()
    saveTerminal('user:7', 'skipped', false)
    expect(readTerminal('user:7')?.pending).toBe(false)
  })
  it('preserves a newer completion when a stale skip acknowledgement arrives', () => {
    saveTerminal('user:7', 'completed')
    saveTerminal('user:7', 'skipped', false)
    expect(readTerminal('user:7')).toEqual({ status: 'completed', pending: true })
    saveTerminal('user:7', 'completed', false)
    expect(readTerminal('user:7')?.pending).toBe(false)
  })
  it('does not transfer a signed-in dismissal to the next account', () => {
    saveTerminal('user:7', 'completed', false)
    claimGuest('user:8')
    expect(readTerminal('user:8')).toBeUndefined()
    expect(readTerminal('guest')).toBeDefined()
  })
  it('resumes only the same owner and sanitizes return locations', () => {
    saveProgress('guest', { step: 'projects', returnTo: '/report?date=2026-10-01#intro', manual: false })
    expect(readProgress('guest')?.returnTo).toBe('/report?date=2026-10-01#intro')
    expect(readProgress('user:7')).toBeNull()
    saveProgress('guest', { step: 'home', returnTo: '//evil.example', manual: true })
    expect(readProgress('guest')?.returnTo).toBe('/')
    saveProgress('guest', null)
    expect(readProgress('guest')).toBeNull()
  })
  it('recovers from corrupt data and unavailable storage', () => {
    localStorage.setItem(MEMORY_KEY, '{"users":{"user:7":null}}')
    expect(readTerminal('user:7')).toBeUndefined()
    localStorage.setItem(MEMORY_KEY, '{bad')
    expect(readTerminal('guest')).toBeUndefined()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    saveTerminal('user:99', 'completed')
    expect(readTerminal('user:99')?.status).toBe('completed')
  })
})

it('covers every public section in both languages and removes disabled sections', () => {
  for (const step of TOUR_STEPS) {
    expect(onboardingZh.steps).toHaveProperty(`${step.id}.body`)
    expect(onboardingEn.steps).toHaveProperty(`${step.id}.title`)
    expect(step.route).not.toContain('/monitor')
    expect(step.route).not.toContain('/subscriptions')
    expect(step.targets.length).toBeGreaterThan(0)
  }
  expect(new Set(TOUR_STEPS.map(s => s.id)).size).toBe(TOUR_STEPS.length)
  expect(availableSteps({ x: false, contact: false }).some(s => s.feature)).toBe(false)
})

it('keeps the card in the viewport and away from a small highlighted control', () => {
  for (const [width, height] of [[1024, 640], [1440, 900], [2560, 1440]] as const) {
    const target = { left: width - 100, top: height - 80, width: 64, height: 32 }
    const box = placeCard(target, { width: 432, height: 340 }, width!, height!)
    expect(box.left).toBeGreaterThanOrEqual(16)
    expect(box.top).toBeGreaterThanOrEqual(16)
    expect(box.left + box.width).toBeLessThanOrEqual(width! - 16)
    expect(box.top + box.height).toBeLessThanOrEqual(height! - 16)
    expect(box.top + box.height <= target.top || box.left + box.width <= target.left).toBe(true)
  }
  expect(spotlightBox({ left: -100, top: -100, width: 10, height: 10 }, 1024, 640)).toBeNull()
})
