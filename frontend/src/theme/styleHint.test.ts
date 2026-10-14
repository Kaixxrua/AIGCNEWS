import { describe, expect, it } from 'vitest'
import { STYLE_STORAGE_KEY } from './appStyle'
import { STYLE_HINT_KEY, markStyleHintSeen, styleHintPending } from './styleHint'

const memory = (entries: Record<string, string> = {}) => {
  const values = new Map(Object.entries(entries))
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
  }
}

describe('style hint memory', () => {
  it('is pending only for visitors who never chose a style nor saw the hint', () => {
    expect(styleHintPending(memory())).toBe(true)
    expect(styleHintPending(memory({ [STYLE_STORAGE_KEY]: 'comic' }))).toBe(false)
    expect(styleHintPending(memory({ [STYLE_HINT_KEY]: '1' }))).toBe(false)
  })

  it('remembers the hint once it was seen', () => {
    const storage = memory()
    markStyleHintSeen(storage)
    expect(styleHintPending(storage)).toBe(false)
  })

  it('never offers the hint when storage cannot be read, and tolerates failed writes', () => {
    const broken = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
    }
    expect(styleHintPending(broken)).toBe(false)
    expect(styleHintPending(null)).toBe(false)
    expect(() => markStyleHintSeen(broken)).not.toThrow()
  })
})
