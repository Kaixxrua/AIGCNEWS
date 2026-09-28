import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ProjectLogo from './ProjectLogo.vue'
import ProjectHeat from './ProjectHeat.vue'
import i18n from '@/i18n'

describe('project identity and heat', () => {
  it('uses stored artwork and falls back to initials without external requests', async () => {
    const logo = mount(ProjectLogo, { props: { logo: '/api/projects/github/logo/acme/demo', repositoryUrl: 'https://github.com/acme/demo', name: 'Demo' } })
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/acme/demo')
    await logo.get('img').trigger('error')
    expect(logo.text()).toBe('D')
    await logo.setProps({ logo: '/api/projects/github/logo/acme/next' })
    expect(logo.get('img').attributes('src')).toContain('/acme/next')
  })
  it('resolves a local cache URL when the ranking has no image URL', () => {
    const logo = mount(ProjectLogo, { props: { repositoryUrl: 'https://github.com/acme/demo', name: 'Demo' } })
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/acme/demo')
  })
  it('replaces a wordmark with the initial and backs transparent marks with a contrasting plate', async () => {
    const pixel = (rgba: number[]) => ({
      canvas: {}, drawImage: () => {},
      getImageData: () => ({ data: new Uint8ClampedArray(Array.from({ length: 24 * 24 }, (_, i) => i % 2 ? rgba : [0, 0, 0, 0]).flat()) }),
    })
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
    const load = async (logo: ReturnType<typeof mount>, width: number, height: number) => {
      const img = logo.get('img')
      Object.defineProperties(img.element, { naturalWidth: { value: width, configurable: true }, naturalHeight: { value: height, configurable: true } })
      await img.trigger('load')
    }
    const logo = mount(ProjectLogo, { props: { logo: '/api/projects/github/logo/acme/wordmark', name: 'Acme' } })
    await load(logo, 256, 47)
    expect(logo.find('img').exists()).toBe(false)
    expect(logo.text()).toBe('A')

    getContext.mockReturnValue(pixel([255, 255, 255, 255]) as never)
    await logo.setProps({ logo: '/api/projects/github/logo/acme/white-mark' })
    await load(logo, 128, 128)
    expect(logo.classes()).toContain('project-logo--dark')
    expect(logo.get('img').classes()).toContain('loaded')

    getContext.mockReturnValue(pixel([20, 60, 160, 255]) as never)
    await logo.setProps({ logo: '/api/projects/github/logo/acme/blue-mark' })
    expect(logo.classes()).not.toContain('project-logo--dark')
    await load(logo, 100, 110)
    expect(logo.classes()).toContain('project-logo--light')
    getContext.mockRestore()
  })
  it('does not trust arbitrary logo hosts', () => {
    const logo = mount(ProjectLogo, { props: { logo: 'https://evil.example/logo', name: 'Demo' } })
    expect(logo.find('img').exists()).toBe(false)
  })
  it('distinguishes missing growth snapshots from a real zero score', async () => {
    const heat = mount(ProjectHeat, { props: { score: 0, available: false }, global: { plugins: [i18n] } })
    expect(heat.text()).toContain('—')
    await heat.setProps({ available: true })
    expect(heat.text()).toContain('0.0')
    await heat.setProps({ score: 65.37 })
    expect(heat.text()).toContain('88.4')
    await heat.setProps({ score: NaN })
    expect(heat.text()).toContain('—')
  })
})
