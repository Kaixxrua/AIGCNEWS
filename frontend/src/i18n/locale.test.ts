import { beforeEach, describe, expect, it } from 'vitest'
import { messages } from './index'
import {
  LOCALE_STORAGE_KEY,
  persistAppLocale,
  resolveAppLocale,
  updateDocumentLocale,
} from './locale'

const catalogShape = (value: unknown): unknown => {
  if (!value || typeof value !== 'object') return typeof value
  return Object.fromEntries(
    Object.entries(value).map(([key, child]) => [key, catalogShape(child)]),
  )
}

describe('application locale contract', () => {
  beforeEach(() => localStorage.clear())

  it('prefers a valid persisted locale', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'en-US')
    expect(resolveAppLocale({ storage: localStorage, browserLanguages: ['zh-CN'] })).toBe('en-US')
  })

  it('uses browser Chinese versus non-Chinese preference', () => {
    expect(resolveAppLocale({ storage: localStorage, browserLanguages: ['zh-TW'] })).toBe('zh-CN')
    expect(resolveAppLocale({ storage: localStorage, browserLanguages: ['fr-FR'] })).toBe('en-US')
  })

  it('falls back to Chinese when browser information is unavailable', () => {
    expect(resolveAppLocale({ storage: null, browserLanguages: null })).toBe('zh-CN')
    persistAppLocale('en-US', localStorage)
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en-US')
  })

  it('updates the document language', () => {
    updateDocumentLocale('en-US', document.documentElement)
    expect(document.documentElement.lang).toBe('en-US')
  })

  it('keeps every catalog leaf structurally aligned', () => {
    expect(catalogShape(messages['zh-CN'])).toEqual(catalogShape(messages['en-US']))
  })
})
