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
    ['corner', '/assets/comic/tear-corner-v2.webp', '852', '345'],
    ['shout', '/assets/comic/tear-shout.webp', '1101', '324'],
    ['peel', '/assets/comic/tear-peel.webp', '1100', '713'],
  ] as const)('paints the %s tear at its intrinsic size so it cannot shift layout', (variant, src, width, height) => {
    const image = mount(ComicSticker, { props: { variant } }).get('img')
    expect(image.attributes()).toMatchObject({ src, width, height, loading: 'lazy' })
  })

  it('shows the painted Chinese slogan as it is, with no lettering on top', () => {
    const wrapper = mount(ComicSticker, { props: { variant: 'shout', text: ' 让创造更自由！ ' } })
    expect(wrapper.get('img').attributes('src')).toBe('/assets/comic/tear-shout.webp')
    expect(wrapper.find('svg').exists()).toBe(false)
  })

  it('letters any other slogan onto the blank rip, within the painted slogan\'s span', () => {
    const wrapper = mount(ComicSticker, { props: { variant: 'shout', text: 'Create freely!' } })
    expect(wrapper.get('img').attributes()).toMatchObject({ src: '/assets/comic/tear-shout-blank.webp', width: '1101', height: '324' })
    expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 1101 324')
    const text = wrapper.get('text')
    expect(text.text()).toBe('Create freely!')
    expect(Number(text.attributes('textLength'))).toBeGreaterThan(0)
    expect(Number(text.attributes('textLength'))).toBeLessThanOrEqual(640)
  })

  it('keeps the painted rip without a slogan, and letters only the rip', () => {
    const blank = mount(ComicSticker, { props: { variant: 'shout', text: '  ' } })
    expect(blank.find('svg').exists()).toBe(false)
    expect(blank.get('img').attributes('src')).toBe('/assets/comic/tear-shout.webp')
    expect(mount(ComicSticker, { props: { variant: 'corner', text: 'Create freely!' } }).find('svg').exists()).toBe(false)
    expect(mount(ComicSticker, { props: { variant: 'peel', text: 'Create freely!' } }).find('svg').exists()).toBe(false)
  })
})
