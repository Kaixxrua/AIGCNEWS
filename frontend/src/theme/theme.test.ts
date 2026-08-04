import { beforeEach, describe, expect, it } from 'vitest'
import {
  applyDocumentTheme,
  installAppTheme,
  persistAppTheme,
  resolveAppTheme,
  setAppTheme,
  THEME_ATTRIBUTE,
  THEME_STORAGE_KEY,
  toggleAppTheme,
  useAppTheme,
} from './index'

describe('application theme contract', () => {
  beforeEach(() => {
    setAppTheme('light')
    localStorage.clear()
  })

  it('prefers a valid persisted theme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    expect(resolveAppTheme({ storage: localStorage, prefersDark: false })).toBe('dark')
  })

  it('ignores an invalid persisted theme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'neon')
    expect(resolveAppTheme({ storage: localStorage, prefersDark: true })).toBe('dark')
    expect(resolveAppTheme({ storage: localStorage, prefersDark: false })).toBe('light')
  })

  it('follows the system preference when nothing is stored', () => {
    expect(resolveAppTheme({ storage: localStorage, prefersDark: true })).toBe('dark')
    expect(resolveAppTheme({ storage: localStorage, prefersDark: false })).toBe('light')
  })

  it('falls back to light when storage and system preference are unavailable', () => {
    expect(resolveAppTheme({ storage: null, prefersDark: null })).toBe('light')
    persistAppTheme('dark', localStorage)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('swallows storage errors when persisting', () => {
    const blockedStorage: Pick<Storage, 'setItem'> = {
      setItem: () => { throw new Error('blocked') },
    }
    expect(() => persistAppTheme('dark', blockedStorage)).not.toThrow()
  })

  it('applies and removes the document theme attribute', () => {
    applyDocumentTheme('dark', document.documentElement)
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe('dark')
    applyDocumentTheme('light', document.documentElement)
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBeNull()
  })

  it('installs the resolved theme onto the document', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    expect(installAppTheme()).toBe('dark')
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe('dark')
    expect(useAppTheme().theme.value).toBe('dark')
  })

  it('toggles between light and dark with persistence', () => {
    expect(toggleAppTheme()).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe('dark')
    expect(toggleAppTheme()).toBe('light')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBeNull()
  })
})
