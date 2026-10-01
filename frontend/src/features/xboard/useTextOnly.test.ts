import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { TEXT_ONLY_KEY, useTextOnly } from './useTextOnly'

describe('useTextOnly', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('starts with media shown and remembers text only', async () => {
    const { preferred, textOnly, toggle } = useTextOnly(ref(true))
    expect(preferred.value).toBe(false)
    expect(textOnly.value).toBe(false)
    toggle()
    await nextTick()
    expect(textOnly.value).toBe(true)
    expect(localStorage.getItem(TEXT_ONLY_KEY)).toBe('1')
    expect(useTextOnly(ref(true)).textOnly.value).toBe(true)
    toggle()
    await nextTick()
    expect(localStorage.getItem(TEXT_ONLY_KEY)).toBe('0')
  })

  it('ignores unknown stored values', () => {
    localStorage.setItem(TEXT_ONLY_KEY, 'yes')
    expect(useTextOnly(ref(true)).preferred.value).toBe(false)
  })

  it('keeps text only to desktop widths', () => {
    localStorage.setItem(TEXT_ONLY_KEY, '1')
    const desktop = ref(false)
    const { preferred, textOnly } = useTextOnly(desktop)
    expect(preferred.value).toBe(true)
    expect(textOnly.value).toBe(false)
    desktop.value = true
    expect(textOnly.value).toBe(true)
  })

  it('still toggles when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const { textOnly, toggle } = useTextOnly(ref(true))
    expect(textOnly.value).toBe(false)
    toggle()
    await nextTick()
    expect(textOnly.value).toBe(true)
  })
})
