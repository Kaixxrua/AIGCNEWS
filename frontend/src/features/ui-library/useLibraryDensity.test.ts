import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { DENSITY_KEY, useLibraryDensity } from './useLibraryDensity'

describe('useLibraryDensity', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('starts as cards and remembers the contact sheet', async () => {
    const { density, contactSheet, toggle } = useLibraryDensity(ref(true))
    expect(density.value).toBe('cards')
    expect(contactSheet.value).toBe(false)
    toggle()
    await nextTick()
    expect(contactSheet.value).toBe(true)
    expect(localStorage.getItem(DENSITY_KEY)).toBe('sheet')
    expect(useLibraryDensity(ref(true)).density.value).toBe('sheet')
    toggle()
    await nextTick()
    expect(localStorage.getItem(DENSITY_KEY)).toBe('cards')
  })

  it('ignores unknown stored values', () => {
    localStorage.setItem(DENSITY_KEY, 'poster')
    expect(useLibraryDensity(ref(true)).density.value).toBe('cards')
  })

  it('keeps the contact sheet to desktop widths', () => {
    localStorage.setItem(DENSITY_KEY, 'sheet')
    const desktop = ref(false)
    const { density, contactSheet } = useLibraryDensity(desktop)
    expect(density.value).toBe('sheet')
    expect(contactSheet.value).toBe(false)
    desktop.value = true
    expect(contactSheet.value).toBe(true)
  })

  it('still toggles when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const { density, toggle } = useLibraryDensity(ref(true))
    expect(density.value).toBe('cards')
    toggle()
    await nextTick()
    expect(density.value).toBe('sheet')
  })
})
