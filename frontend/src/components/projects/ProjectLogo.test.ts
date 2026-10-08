import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ProjectLogo from './ProjectLogo.vue'
import ProjectHeat from './ProjectHeat.vue'
import i18n from '@/i18n'

describe('project identity and heat', () => {
  it('tries a same-origin owner avatar before the initial when artwork fails', async () => {
    const logo = mount(ProjectLogo, { props: { logo: '/api/projects/github/logo/acme/demo', repositoryUrl: 'https://github.com/acme/demo', name: 'Demo' } })
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/acme/demo')
    await logo.get('img').trigger('error')
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/acme/demo?avatar=true')
    await logo.get('img').trigger('error')
    expect(logo.find('img').exists()).toBe(false)
    expect(logo.text()).toBe('D')
    await logo.setProps({ logo: '/api/projects/github/logo/acme/next' })
    expect(logo.get('img').attributes('src')).toContain('/acme/next')
  })
  it('resolves a local cache URL when the ranking has no image URL', () => {
    const logo = mount(ProjectLogo, { props: { repositoryUrl: 'https://github.com/acme/demo', name: 'Demo' } })
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/acme/demo')
  })
  it('replaces a wordmark with the owner avatar and backs transparent marks with a contrasting plate', async () => {
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
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/acme/wordmark?avatar=true')
    expect(logo.text()).toBe('A')

    getContext.mockReturnValue(pixel([60, 60, 60, 255]) as never)
    await load(logo, 128, 128)
    expect(logo.get('img').classes()).toContain('loaded')
    expect(logo.text()).toBe('')

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
  it('falls back for a completely transparent image and ignores events from a replaced image', async () => {
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      canvas: {}, drawImage: () => {}, getImageData: () => ({ data: new Uint8ClampedArray(24 * 24 * 4) }),
    } as never)
    const logo = mount(ProjectLogo, { props: { repositoryUrl: 'https://github.com/acme/demo', name: 'Demo' } })
    const old = logo.get('img')
    Object.defineProperties(old.element, { naturalWidth: { value: 128 }, naturalHeight: { value: 128 } })
    await old.trigger('load')
    expect(logo.get('img').attributes('src')).toContain('?avatar=true')
    await old.trigger('error')
    await old.trigger('load')
    expect(logo.get('img').attributes('src')).toContain('?avatar=true')
    expect(logo.get('img').classes()).not.toContain('loaded')
    await logo.get('img').trigger('error')
    await logo.setProps({ repositoryUrl: 'https://github.com/new-owner/next' })
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/new-owner/next')
    await logo.get('img').trigger('error')
    expect(logo.get('img').attributes('src')).toBe('/api/projects/github/logo/new-owner/next?avatar=true')
    getContext.mockRestore()
  })
  it('shows the initial without requesting a logo for a repository that is gone', () => {
    const logo = mount(ProjectLogo, { props: { logo: '/api/projects/github/logo/acme/demo', repositoryUrl: 'https://github.com/acme/demo', name: 'Demo', unavailable: true } })
    expect(logo.find('img').exists()).toBe(false)
    expect(logo.text()).toBe('D')
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
