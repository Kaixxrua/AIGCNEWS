import { describe, expect, it } from 'vitest'
import { isApplePlatform, isQuickSearchHotkey } from './quickSearchHotkey'

const key = (init: KeyboardEventInit) => new KeyboardEvent('keydown', { cancelable: true, ...init })

describe('quick search hotkey', () => {
  it('uses ⌘K on Apple devices and Ctrl+K elsewhere', () => {
    expect(isQuickSearchHotkey(key({ key: 'k', metaKey: true }), true)).toBe(true)
    expect(isQuickSearchHotkey(key({ key: 'k', ctrlKey: true }), true)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'k', ctrlKey: true }), false)).toBe(true)
    expect(isQuickSearchHotkey(key({ key: 'k', metaKey: true }), false)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'K', ctrlKey: true }), false)).toBe(true)
  })

  it('ignores other chords, composition and keys already handled', () => {
    expect(isQuickSearchHotkey(key({ key: 'k' }), false)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'k', ctrlKey: true, shiftKey: true }), false)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'k', ctrlKey: true, altKey: true }), false)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'k', ctrlKey: true, metaKey: true }), false)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'j', ctrlKey: true }), false)).toBe(false)
    expect(isQuickSearchHotkey(key({ key: 'k', ctrlKey: true, isComposing: true }), false)).toBe(false)
    const handled = key({ key: 'k', ctrlKey: true })
    handled.preventDefault()
    expect(isQuickSearchHotkey(handled, false)).toBe(false)
  })

  it('finds K by its physical key on non-Latin layouts', () => {
    expect(isQuickSearchHotkey(key({ key: 'л', code: 'KeyK', ctrlKey: true }), false)).toBe(true)
    expect(isQuickSearchHotkey(key({ key: 'л', code: 'KeyL', ctrlKey: true }), false)).toBe(false)
  })

  it('treats Macs, iPhones and iPads as Apple devices', () => {
    expect(isApplePlatform({ platform: 'MacIntel', userAgent: '' })).toBe(true)
    expect(isApplePlatform({ platform: 'iPad', userAgent: '' })).toBe(true)
    expect(isApplePlatform({ platform: '', userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' })).toBe(true)
    expect(isApplePlatform({ platform: 'Win32', userAgent: 'Mozilla/5.0 (Windows NT 10.0)' })).toBe(false)
    expect(isApplePlatform({ platform: 'Linux x86_64', userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' })).toBe(false)
  })
})
