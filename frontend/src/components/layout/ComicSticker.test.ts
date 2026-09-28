import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ComicSticker from './ComicSticker.vue'

describe('ComicSticker', () => {
  it.each(['corner', 'shout', 'peel'] as const)('keeps the %s sticker out of the accessibility tree', variant => {
    const wrapper = mount(ComicSticker, { props: { variant, text: 'Create freely!' } })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.classes()).toContain(`comic-sticker--${variant}`)
    expect(wrapper.get('img').attributes('alt')).toBe('')
  })

  it.each([
    ['corner', '/assets/comic/tear-corner.webp', '720', '406'],
    ['shout', '/assets/comic/tear-rip.webp', '900', '229'],
    ['peel', '/assets/comic/tear-peel.webp', '720', '720'],
  ] as const)('paints the %s tear at its intrinsic size so it cannot shift layout', (variant, src, width, height) => {
    const image = mount(ComicSticker, { props: { variant } }).get('img')
    expect(image.attributes()).toMatchObject({ src, width, height, loading: 'lazy' })
  })

  it('letters the localized slogan into the rip, pinned to its opening', () => {
    const wrapper = mount(ComicSticker, { props: { variant: 'shout', text: ' 让创造更自由！ ' } })
    expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 900 229')
    const texts = wrapper.findAll('text')
    expect(new Set(texts.map(t => t.text()))).toEqual(new Set(['让创造更自由！']))
    for (const text of texts) expect(Number(text.attributes('textLength'))).toBeLessThanOrEqual(380)
  })

  it('leaves the rip blank without a slogan, and letters only the rip', () => {
    expect(mount(ComicSticker, { props: { variant: 'shout', text: '  ' } }).find('svg').exists()).toBe(false)
    expect(mount(ComicSticker, { props: { variant: 'corner', text: 'Create freely!' } }).find('svg').exists()).toBe(false)
    expect(mount(ComicSticker, { props: { variant: 'peel', text: 'Create freely!' } }).find('svg').exists()).toBe(false)
  })
})
