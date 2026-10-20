import { describe, expect, it } from 'vitest'
import { reportPageHead } from './reportPageHead'

describe('briefing issue search metadata', () => {
  it('excludes confirmed missing issues from search results', () => {
    expect(reportPageHead({ date: '2026-10-19' }, 'missing', '每日简报')).toMatchObject({ noindex: true })
  })

  it.each(['loading', 'ready', 'pending', 'failed'] as const)('keeps %s issues eligible and drops tracking query params', state => {
    expect(reportPageHead({ date: '2026-10-20', type: 'github', utm_source: 'google' }, state, '每日简报')).toEqual({
      title: '每日简报 2026-10-20', noindex: false,
      canonicalQuery: { date: '2026-10-20', type: 'github' },
    })
  })

  it('leaves the latest-issue landing page indexable and removes default issue filters', () => {
    expect(reportPageHead({}, 'missing', '每日简报')).toBeNull()
    expect(reportPageHead({ date: 'invalid' }, 'missing', '每日简报')).toBeNull()
    expect(reportPageHead({ date: '2026-10-20', type: 'all' }, 'ready', '每日简报')?.canonicalQuery)
      .toEqual({ date: '2026-10-20', type: null })
  })
})
