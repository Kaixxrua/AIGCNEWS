import { mount } from '@vue/test-utils'
import { defineComponent, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import { showToast } from '@/composables/useToast'
import { forgetSavedItems, SAVED_ITEMS, useSavedItems, type SavedItems } from './useSavedItems'

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

interface Note { text: string }
const isNote = (data: unknown): data is Note => !!data && typeof data === 'object' && typeof (data as Note).text === 'string'

const use = (list = 'notes'): SavedItems<Note> => {
  let saved: SavedItems<Note> | undefined
  mount(defineComponent({
    setup() {
      saved = useSavedItems({ list, accept: isNote })
      return () => null
    },
  }), { global: { plugins: [i18n] } })
  return saved!
}
const stored = (list = 'notes') => JSON.parse(localStorage.getItem(`saved_items_${list}`) ?? 'null')
const toasts = () => vi.mocked(showToast).mock.calls.map(([message]) => message)

beforeEach(() => {
  localStorage.clear()
  forgetSavedItems()
  vi.mocked(showToast).mockClear()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('useSavedItems', () => {
  it('收下一条连内容存在本机，最近收的在前；再按一下取消', () => {
    const saved = use()
    expect(saved.toggle('a', { text: '第一条' })).toBe('saved')
    expect(saved.toggle('b', { text: '第二条' })).toBe('saved')
    expect(saved.has('a')).toBe(true)
    expect(saved.count.value).toBe(2)
    expect(saved.entries.value.map((entry) => entry.id)).toEqual(['b', 'a'])
    expect(stored().map((entry: { id: string; data: Note }) => [entry.id, entry.data.text])).toEqual([['b', '第二条'], ['a', '第一条']])

    expect(saved.toggle('a', { text: '第一条' })).toBe('removed')
    expect(saved.has('a')).toBe(false)
    expect(stored().map((entry: { id: string }) => entry.id)).toEqual(['b'])
  })

  it('存下的是收下那一刻的快照，后来改了原条目也不跟着变', () => {
    const saved = use()
    const note = reactive({ text: '原文' })
    saved.toggle('a', note)
    note.text = '改过'
    expect(saved.entries.value[0]!.data.text).toBe('原文')
    expect(stored()[0].data.text).toBe('原文')
  })

  it('读本机存着的：坏了的整份、内容不对的条与重复的标识都丢掉', () => {
    localStorage.setItem('saved_items_notes', JSON.stringify([
      { id: 'a', at: 2, data: { text: '好的' } },
      { id: 'b', at: 1, data: { words: '缺正文' } },
      { id: 'a', at: 0, data: { text: '重复' } },
      { id: '', at: 0, data: { text: '没有标识' } },
      'nonsense',
    ]))
    expect(use().entries.value.map((entry) => [entry.id, entry.data.text])).toEqual([['a', '好的']])

    forgetSavedItems()
    localStorage.setItem('saved_items_notes', '{not json')
    expect(use().count.value).toBe(0)
  })

  it('同一列表各处共用一份，不同列表互不相干', () => {
    const wall = use()
    const detail = use()
    const other = use('others')
    detail.toggle('a', { text: '在详情里收的' })
    expect(wall.has('a')).toBe(true)
    expect(other.has('a')).toBe(false)
  })

  it('头一回收藏时说一句只存在本机，之后不再说', () => {
    const saved = use()
    saved.toggle('a', { text: '一' })
    saved.toggle('b', { text: '二' })
    expect(toasts()).toEqual([i18n.global.t('saved.hint')])
    expect(localStorage.getItem(SAVED_ITEMS.hintKey)).toBe('1')
  })

  it(`满 ${SAVED_ITEMS.limit} 条就不再收，说一句；取消照常`, () => {
    localStorage.setItem(SAVED_ITEMS.hintKey, '1')
    localStorage.setItem('saved_items_notes', JSON.stringify(
      Array.from({ length: SAVED_ITEMS.limit }, (_, index) => ({ id: `n${index}`, at: index, data: { text: String(index) } })),
    ))
    const saved = use()
    expect(saved.toggle('extra', { text: '多出来的' })).toBe('full')
    expect(saved.has('extra')).toBe(false)
    expect(toasts()).toEqual([i18n.global.t('saved.full', { limit: SAVED_ITEMS.limit })])
    expect(saved.toggle('n0', { text: '0' })).toBe('removed')
    expect(saved.toggle('extra', { text: '多出来的' })).toBe('saved')
  })

  it('别的标签页收了、取消了，这里跟着换', () => {
    const saved = use()
    saved.toggle('a', { text: '这里收的' })
    localStorage.setItem('saved_items_notes', JSON.stringify([{ id: 'z', at: 9, data: { text: '那边收的' } }]))
    window.dispatchEvent(new StorageEvent('storage', { key: 'saved_items_notes' }))
    expect(saved.entries.value.map((entry) => entry.id)).toEqual(['z'])
    window.dispatchEvent(new StorageEvent('storage', { key: 'saved_items_other' }))
    expect(saved.entries.value.map((entry) => entry.id)).toEqual(['z'])
  })

  it('本机存不进去时收藏只在这次有效，说一句，也不再跟着别的标签页换', () => {
    localStorage.setItem(SAVED_ITEMS.hintKey, '1')
    const saved = use()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(saved.toggle('a', { text: '存不进去' })).toBe('saved')
    expect(saved.toggle('b', { text: '还是存不进去' })).toBe('saved')
    expect(saved.entries.value.map((entry) => entry.id)).toEqual(['b', 'a'])
    expect(toasts()).toEqual([i18n.global.t('saved.volatile')])
    window.dispatchEvent(new StorageEvent('storage', { key: 'saved_items_notes' }))
    expect(saved.count.value).toBe(2)
  })
})
