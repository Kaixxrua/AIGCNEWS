import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ComicSticker from './ComicSticker.vue'

describe('ComicSticker', () => {
  it.each(['burst', 'shout', 'label'] as const)('keeps the %s sticker out of the accessibility tree', variant => {
    const wrapper = mount(ComicSticker, { props: { variant }, slots: { default: 'Create freely!' } })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.classes()).toContain(`comic-sticker--${variant}`)
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('prints the localized slogan inside the shout bubble', () => {
    const wrapper = mount(ComicSticker, { props: { variant: 'shout' }, slots: { default: '让创造更自由！' } })
    expect(wrapper.get('.comic-sticker__text').text()).toBe('让创造更自由！')
  })
})
