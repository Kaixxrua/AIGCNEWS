import { afterEach, describe, expect, it } from 'vitest'
import { firstInView, isModalOpen, isTypingTarget, listKeyAction, stepKey, type Span } from './listKeys'

const press = (key: string, init: KeyboardEventInit = {}) => new KeyboardEvent('keydown', { key, cancelable: true, ...init })

describe('listKeyAction', () => {
  it('maps the five letters, Enter, Escape and the question mark', () => {
    expect(['j', 'k', 'o', 's', 'x', 'Enter', 'Escape', '?'].map((key) => listKeyAction(press(key))))
      .toEqual(['next', 'prev', 'open', 'save', 'toggle', 'open', 'escape', 'help'])
    // 大写锁定、全角问号也认；问号本来就要按 Shift。
    expect(listKeyAction(press('J'))).toBe('next')
    expect(listKeyAction(press('？'))).toBe('help')
    expect(listKeyAction(press('?', { shiftKey: true }))).toBe('help')
  })

  it('leaves modified keys, Shift letters, composing input and other keys alone', () => {
    expect(listKeyAction(press('j', { ctrlKey: true }))).toBeNull()
    expect(listKeyAction(press('k', { metaKey: true }))).toBeNull()
    expect(listKeyAction(press('o', { altKey: true }))).toBeNull()
    expect(listKeyAction(press('J', { shiftKey: true }))).toBeNull()
    expect(listKeyAction(press('j', { isComposing: true }))).toBeNull()
    expect(listKeyAction(press('Process', { keyCode: 229 }))).toBeNull()
    expect(listKeyAction(press('a'))).toBeNull()
    expect(listKeyAction(press('ArrowDown'))).toBeNull()
    const handled = press('j')
    handled.preventDefault()
    expect(listKeyAction(handled)).toBeNull()
  })

  it('reads the physical key on non-Latin layouts but trusts the character on Latin ones', () => {
    expect(listKeyAction(press('о', { code: 'KeyJ' }))).toBe('next')
    // Dvorak：物理 S 键打出 o，按字符算「打开」；物理 Z 键打出分号，不是键位。
    expect(listKeyAction(press('o', { code: 'KeyS' }))).toBe('open')
    expect(listKeyAction(press(';', { code: 'KeyZ' }))).toBeNull()
  })
})

describe('isTypingTarget', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('keeps letters for fields, editable areas and menus but not for buttons or checkboxes', () => {
    document.body.innerHTML = `
      <input id="text"><input id="box" type="checkbox"><textarea id="area"></textarea>
      <div contenteditable="true"><span id="rich">x</span></div><div contenteditable="false" id="frozen"></div>
      <div role="listbox"><div id="option" role="option">a</div></div>
      <button id="button">b</button><article id="card" tabindex="-1"></article>`
    const at = (id: string) => document.getElementById(id)
    expect(['text', 'area', 'rich', 'option'].map((id) => isTypingTarget(at(id)))).toEqual([true, true, true, true])
    expect(['box', 'frozen', 'button', 'card'].map((id) => isTypingTarget(at(id)))).toEqual([false, false, false, false])
    expect(isTypingTarget(null)).toBe(false)
    expect(isTypingTarget(window)).toBe(false)
  })
})

describe('isModalOpen', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('sees a rendered modal and ignores one that is not laid out', () => {
    document.body.innerHTML = '<div role="dialog" aria-modal="true"></div>'
    const dialog = document.querySelector('div')!
    // jsdom 不排版：没有盒子就当没开。
    expect(isModalOpen()).toBe(false)
    dialog.getClientRects = () => [{}] as unknown as DOMRectList
    expect(isModalOpen()).toBe(true)
    dialog.setAttribute('aria-modal', 'false')
    expect(isModalOpen()).toBe(false)
  })
})

describe('stepKey', () => {
  it('steps within the list and stops at both ends', () => {
    const keys = ['a', 'b', 'c']
    expect(stepKey(keys, 'a', 1)).toBe('b')
    expect(stepKey(keys, 'b', -1)).toBe('a')
    expect(stepKey(keys, 'c', 1)).toBeNull()
    expect(stepKey(keys, 'a', -1)).toBeNull()
    expect(stepKey(keys, 'gone', 1)).toBeNull()
  })
})

describe('firstInView', () => {
  const boxes: Record<string, Span | null> = {
    above: { top: -400, bottom: -20 },
    cut: { top: -80, bottom: 120 },
    whole: { top: 140, bottom: 360 },
    later: { top: 380, bottom: 600 },
    below: { top: 900, bottom: 1100 },
    hidden: null,
  }
  const box = (key: string) => boxes[key] ?? null
  const view = { top: 0, bottom: 800 }

  it('takes the first item in reading order whose top is in view', () => {
    expect(firstInView(['above', 'hidden', 'cut', 'later', 'whole', 'below'], box, view)).toBe('later')
  })

  it('falls back to a partly visible item, then to nothing', () => {
    expect(firstInView(['above', 'cut', 'below'], box, view)).toBe('cut')
    expect(firstInView(['above', 'below', 'hidden'], box, view)).toBeNull()
  })
})
