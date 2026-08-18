import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MCP_PROMO_DISMISSED_STORAGE_KEY } from '@/features/mcp/mcpExamplePrompts'
import { MCP_PROMO_DISMISS_WEEK_MS, useMcpPromoDismissed } from './useMcpPromoDismissed'

describe('useMcpPromoDismissed', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('starts visible when nothing is stored', () => {
    const { dismissed } = useMcpPromoDismissed()
    expect(dismissed.value).toBe(false)
  })

  it('dismiss only hides for the current session without persisting', () => {
    const { dismissed, dismiss } = useMcpPromoDismissed()
    dismiss()

    expect(dismissed.value).toBe(true)
    expect(window.localStorage.getItem(MCP_PROMO_DISMISSED_STORAGE_KEY)).toBeNull()
  })

  it('dismissForWeek persists an expiry seven days out', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-18T12:00:00Z'))
    const { dismissed, dismissForWeek } = useMcpPromoDismissed()
    dismissForWeek()

    expect(dismissed.value).toBe(true)
    expect(window.localStorage.getItem(MCP_PROMO_DISMISSED_STORAGE_KEY)).toBe(
      String(Date.parse('2026-08-18T12:00:00Z') + MCP_PROMO_DISMISS_WEEK_MS),
    )
  })

  it('reads back a stored dismissal that has not expired', () => {
    window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, String(Date.now() + 1000))
    const { dismissed } = useMcpPromoDismissed()
    expect(dismissed.value).toBe(true)
  })

  it('shows the card again once the stored dismissal expires', () => {
    window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, String(Date.now() - 1000))
    const { dismissed } = useMcpPromoDismissed()
    expect(dismissed.value).toBe(false)
  })

  it('treats the legacy permanent dismissal marker as expired', () => {
    window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, '1')
    const { dismissed } = useMcpPromoDismissed()
    expect(dismissed.value).toBe(false)
  })

  it('ignores unrelated stored values', () => {
    window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, 'yes')
    const { dismissed } = useMcpPromoDismissed()
    expect(dismissed.value).toBe(false)
  })

  it('falls back to visible when storage reads throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied')
    })
    const { dismissed } = useMcpPromoDismissed()
    expect(dismissed.value).toBe(false)
  })

  it('keeps the in-memory dismissal when storage writes throw', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied')
    })
    const { dismissed, dismissForWeek } = useMcpPromoDismissed()

    expect(() => dismissForWeek()).not.toThrow()
    expect(dismissed.value).toBe(true)
  })
})
