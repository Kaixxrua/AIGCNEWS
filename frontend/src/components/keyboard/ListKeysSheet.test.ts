import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ListKeysSheet from './ListKeysSheet.vue'
import { i18n } from '@/i18n'

let wrapper: VueWrapper | null = null

const mountSheet = (open: boolean) => {
  wrapper = mount(ListKeysSheet, {
    props: { open, actions: { open: 'Open', save: 'Save' } },
    global: { plugins: [i18n] },
    attachTo: document.body,
  })
  return wrapper
}

const sheet = () => document.querySelector('.list-keys-sheet')

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('ListKeysSheet', () => {
  it('closes on a click outside it', async () => {
    const sheetWrapper = mountSheet(false)
    await sheetWrapper.setProps({ open: true })
    expect(sheet()).not.toBeNull()

    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    expect(sheetWrapper.emitted('update:open')).toEqual([[false]])
  })

  it('still closes on a click outside when ? was pressed before it finished loading', () => {
    const sheetWrapper = mountSheet(true)
    expect(sheet()).not.toBeNull()

    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    expect(sheetWrapper.emitted('update:open')).toEqual([[false]])
  })
})
