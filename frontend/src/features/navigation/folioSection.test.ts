import { describe, expect, it } from 'vitest'
import { folioSection } from './folioSection'
import { NAV_ITEMS } from './navigationModel'

describe('folioSection', () => {
  it('letters the dock sections in dock order, the homepage being A', () => {
    expect(NAV_ITEMS[0]?.to).toBe('/')
    expect(folioSection('/projects', {}, 'github-projects')).toEqual({ key: 'projects', edition: 'B' })
    expect(folioSection('/ui-library/abc', {}, 'ui-library')).toEqual({ key: 'uiLibrary', edition: 'C' })
    expect(folioSection('/report', {}, 'report')).toEqual({ key: 'report', edition: 'E' })
    expect(folioSection('/x', {}, 'x-board')).toEqual({ key: 'xboard', edition: 'F' })
  })

  it('gives the website collection its own section on either of its addresses', () => {
    expect(folioSection('/projects', { source: 'website' }, 'github-projects')).toEqual({ key: 'websites', edition: 'D' })
    expect(folioSection('/websites', {}, 'recommended-websites')).toEqual({ key: 'websites', edition: 'D' })
  })

  it('names pages outside the dock without a letter', () => {
    expect(folioSection('/papers/p1/read', {}, 'paper-read')).toEqual({ key: 'paper', edition: null })
    expect(folioSection('/privacy', {}, 'privacy')).toEqual({ key: 'privacy', edition: null })
  })

  it('has no section for the homepage or unknown pages', () => {
    expect(folioSection('/', {}, 'dashboard')).toBeNull()
    expect(folioSection('/register', {}, 'register')).toBeNull()
  })
})
