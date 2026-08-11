import { describe, expect, it } from 'vitest'

import {
  getTabBoardStatus,
  tabBoardStatusHint,
} from './dashboardViewModel'

describe('tab board status projection (PR6)', () => {
  const sourceStatus = {
    arxiv: { is_finalized: false, is_embargoed: true, day_boundary: 'PT', finalize_hour: 17 },
    github: { is_finalized: true, is_embargoed: false, day_boundary: 'CST', finalize_hour: 1 },
    x: { is_finalized: false, is_embargoed: false, day_boundary: 'CST', finalize_hour: 1 },
  }

  it('maps wire fields per tab and tolerates missing entries', () => {
    expect(getTabBoardStatus(sourceStatus, 'arxiv')).toEqual({
      isFinalized: false, isEmbargoed: true, dayBoundary: 'PT', finalizeHour: 17, isDisabled: false,
    })
    expect(getTabBoardStatus(sourceStatus, 'github')).toEqual({
      isFinalized: true, isEmbargoed: false, dayBoundary: 'CST', finalizeHour: 1, isDisabled: false,
    })
    expect(getTabBoardStatus(sourceStatus, 'news')).toBeNull()
    expect(getTabBoardStatus(undefined, 'arxiv')).toBeNull()
    expect(getTabBoardStatus({}, 'arxiv')).toBeNull()
  })

  it('defaults partial wire entries to collecting without a finalize hour', () => {
    expect(getTabBoardStatus({ x: {} }, 'x')).toEqual({
      isFinalized: false, isEmbargoed: false, dayBoundary: '', finalizeHour: null, isDisabled: false,
    })
  })

  it('passes through the additive is_disabled wire marker', () => {
    expect(getTabBoardStatus({ x: { is_disabled: true } }, 'x')).toEqual({
      isFinalized: false, isEmbargoed: false, dayBoundary: '', finalizeHour: null, isDisabled: true,
    })
  })

  it('renders finalized / finalizing / collecting hints', () => {
    const translate = (key: string, params?: Record<string, unknown>) =>
      params ? `${key}:${String(params.time)}` : key

    expect(tabBoardStatusHint(getTabBoardStatus(sourceStatus, 'github')!, translate)).toBe('dashboard.tabFinalized')
    expect(tabBoardStatusHint(getTabBoardStatus(sourceStatus, 'arxiv')!, translate)).toBe('dashboard.tabFinalizing:17:00')
    expect(tabBoardStatusHint(getTabBoardStatus(sourceStatus, 'x')!, translate)).toBe('dashboard.tabCollecting')
  })
})
