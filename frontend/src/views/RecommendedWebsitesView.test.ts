import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import RecommendedWebsitesView from './RecommendedWebsitesView.vue'
import RecommendedWebsiteEditor from '@/components/websites/RecommendedWebsiteEditor.vue'
import * as api from '@/services/site/recommendedWebsiteApi'
import { __resetRecommendedWebsitesSnapshotForTest } from '@/composables/recommendedWebsitesSnapshot'

const authBox = vi.hoisted(() => ({ current: null as null | { isAdmin: boolean; status?: string } }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authBox.current }))
vi.mock('@/services/site/recommendedWebsiteApi', () => ({
  fetchRecommendedWebsites: vi.fn(), createRecommendedWebsite: vi.fn(),
  updateRecommendedWebsite: vi.fn(), deleteRecommendedWebsite: vi.fn(),
}))

const example = { id: 1, title: 'Example', url: 'https://example.com/', description: 'My recommendation', category: 'Tools', sort_order: 0, created_at: '2026-09-10T00:00:00Z', updated_at: '2026-09-10T00:00:00Z' }
const mountPage = async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/websites', component: { template: '<div />' } }, { path: '/projects', component: { template: '<div />' } },
  ] })
  await router.push('/websites')
  const wrapper = mount(RecommendedWebsitesView, { global: { plugins: [router, i18n] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  __resetRecommendedWebsitesSnapshotForTest()
  authBox.current = reactive({ isAdmin: false })
  i18n.global.locale.value = 'zh-CN'
  vi.mocked(api.fetchRecommendedWebsites).mockResolvedValue([])
  vi.mocked(api.createRecommendedWebsite).mockResolvedValue(example)
})

describe('standalone website recommendations', () => {
  it('shows a genuine empty public list, the two destinations and no admin controls', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('h1').text()).toBe('站长推荐')
    expect(wrapper.text()).toContain('还没有推荐网站')
    expect(wrapper.find('.website-tabs a[aria-current="page"]').attributes('href')).toBe('/websites')
    expect(wrapper.find('.website-tabs a[href="/projects?source=website"]').exists()).toBe(true)
    expect(wrapper.find('.website-header button').exists()).toBe(false)
    expect(wrapper.findComponent(RecommendedWebsiteEditor).exists()).toBe(false)
    wrapper.unmount()
  })

  it('tells visitors beside the tabs, in one line, that their own collection needs a login', async () => {
    authBox.current = reactive({ isAdmin: false, status: 'anonymous' })
    vi.mocked(api.fetchRecommendedWebsites).mockResolvedValue([example])
    const wrapper = await mountPage()
    expect(wrapper.find('.website-tabs-row--with-login .website-tabs-login').text()).toContain('跟着账号走')
    expect(wrapper.findAll('.website-card')).toHaveLength(1)
    wrapper.unmount()
  })

  it('renders direct external links and filters by the recommendation text', async () => {
    vi.mocked(api.fetchRecommendedWebsites).mockResolvedValue([example])
    const wrapper = await mountPage()
    const link = wrapper.find('.website-card h2 a')
    expect(link.attributes('href')).toBe('https://example.com/')
    expect(link.attributes('rel')).toContain('noopener')
    await wrapper.find('input[type="search"]').setValue('does not exist')
    expect(wrapper.findAll('.website-card')).toHaveLength(0)
    expect(wrapper.text()).toContain('没有找到符合条件的网站')
    wrapper.unmount()
  })

  it('shows the stored site logo and falls back to the monogram when it cannot load', async () => {
    vi.mocked(api.fetchRecommendedWebsites).mockResolvedValue([
      { ...example, icon_url: '/api/media/site/' + 'a'.repeat(32) + '.webp' },
      { ...example, id: 2, title: 'Other', url: 'https://other.example/' },
    ])
    const wrapper = await mountPage()
    const [withIcon, withoutIcon] = wrapper.findAll('.website-monogram')
    expect(withIcon!.find('img').attributes('src')).toBe('/api/media/site/' + 'a'.repeat(32) + '.webp')
    expect(withoutIcon!.find('img').exists()).toBe(false)
    expect(withoutIcon!.text()).toBe('O')
    await withIcon!.find('img').trigger('error')
    expect(wrapper.findAll('.website-monogram')[0]!.find('img').exists()).toBe(false)
    expect(wrapper.findAll('.website-monogram')[0]!.text()).toBe('E')
    wrapper.unmount()
  })

  it('lets admins publish a manually entered website and hides the editor on role loss', async () => {
    authBox.current!.isAdmin = true
    const wrapper = await mountPage()
    await wrapper.find('.website-header button').trigger('click')
    const editor = wrapper.findComponent(RecommendedWebsiteEditor)
    expect(editor.exists()).toBe(true)
    editor.vm.$emit('save', { title: example.title, url: example.url, description: example.description, category: example.category, sort_order: 0 })
    await flushPromises()
    expect(api.createRecommendedWebsite).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.website-card')).toHaveLength(1)
    expect(wrapper.findComponent(RecommendedWebsiteEditor).exists()).toBe(false)
    await wrapper.find('.website-header button').trigger('click')
    authBox.current!.isAdmin = false
    await flushPromises()
    expect(wrapper.findComponent(RecommendedWebsiteEditor).exists()).toBe(false)
    expect(wrapper.find('.website-card__actions').exists()).toBe(false)
    wrapper.unmount()
  })
})
