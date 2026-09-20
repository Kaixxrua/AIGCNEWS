import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
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
    expect(heat.text()).toContain('65.4')
    await heat.setProps({ score: NaN })
    expect(heat.text()).toContain('—')
  })
})
