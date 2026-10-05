import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import NotFoundView from './NotFoundView.vue'

const mountAt = async (path: string) => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:any(.*)', component: { template: '<div />' } }] })
  await router.push(path)
  const wrapper = mount(NotFoundView, { global: { plugins: [router, i18n] } })
  return { router, wrapper }
}

beforeEach(() => { i18n.global.locale.value = 'zh-CN' })
afterEach(() => {
  window.history.replaceState(null, '')
  i18n.global.locale.value = 'zh-CN'
})

describe('not-found page', () => {
  it('says the page does not exist, shows the address as typed and links home and to the sections', async () => {
    const { wrapper } = await mountAt('/%E6%97%A7%E7%89%88/a?x=1')
    expect(wrapper.find('h1').text()).toBe('页面不存在')
    expect(wrapper.find('.not-found__path code').text()).toBe('/旧版/a')
    expect(wrapper.find('.not-found__action--home').attributes('href')).toBe('/')
    expect(wrapper.find('.not-found__action--home').text()).toBe('回到首页')
    const sections = wrapper.findAll('.not-found__section')
    expect(sections.map((link) => link.attributes('href'))).toEqual(['/projects', '/report', '/ui-library', '/mcp'])
    expect(sections.map((link) => link.text())).toEqual(['projects', 'report', 'uiLibrary', 'mcp'].map((key) => i18n.global.t(`masthead.sections.${key}`)))
    sections.forEach((link) => expect(link.text()).not.toContain('masthead.'))
    wrapper.unmount()
  })

  it('keeps an address it cannot decode as it is', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { wrapper } = await mountAt('/bad%E0')
    expect(wrapper.find('.not-found__path code').text()).toBe('/bad%E0')
    wrapper.unmount()
    vi.restoreAllMocks()
  })

  it('offers to go back only when the visitor came from another page of the site', async () => {
    const direct = await mountAt('/no-such-page')
    expect(direct.wrapper.find('button').exists()).toBe(false)
    direct.wrapper.unmount()

    window.history.replaceState({ back: '/projects' }, '')
    const { router, wrapper } = await mountAt('/no-such-page')
    const back = vi.spyOn(router, 'back').mockImplementation(() => {})
    await wrapper.find('button').trigger('click')
    expect(back).toHaveBeenCalledOnce()
    expect(wrapper.find('button').text()).toBe('返回上一页')
    wrapper.unmount()
  })

  it('speaks English', async () => {
    i18n.global.locale.value = 'en-US'
    const { wrapper } = await mountAt('/no-such-page')
    expect(wrapper.find('h1').text()).toBe('Page not found')
    expect(wrapper.find('.not-found__action--home').text()).toBe('Back to home')
    expect(wrapper.find('.not-found__sections-label').text()).toBe('Or head to a section')
    wrapper.unmount()
  })
})
