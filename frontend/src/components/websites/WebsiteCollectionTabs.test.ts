import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { messages } from '@/i18n'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { __resetRecommendedWebsitesSnapshotForTest, rememberRecommendedWebsites } from '@/composables/recommendedWebsitesSnapshot'
import { fetchRecommendedWebsites, type RecommendedWebsite } from '@/services/site/recommendedWebsiteApi'
import { useAuthStore, type AuthStatus } from '@/stores/authStore'
import WebsiteCollectionTabs from './WebsiteCollectionTabs.vue'

// 网页栏目的两个标签：游客点「我的网页收藏」先弹登录；站长推荐还空着时，收藏页上把它藏起来（管理员除外）。
vi.mock('@/services/site/recommendedWebsiteApi', () => ({ fetchRecommendedWebsites: vi.fn() }))

const site: RecommendedWebsite = {
  id: 1, title: 'Example', url: 'https://example.com/', description: 'Why', category: 'Tools', sort_order: 10,
  created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
}
const PERSONAL = '/projects?source=website'
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages, missingWarn: false, fallbackWarn: false })
const mounted: VueWrapper[] = []

const mountTabs = async (active: 'recommended' | 'personal', status: AuthStatus, role: 'user' | 'admin' = 'user') => {
  const auth = useAuthStore()
  auth.status = status
  auth.user = status === 'authenticated' ? { user_id: 1, email: 'a@b.c', role, membership_tier: 'free' } : null
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/websites', component: { template: '<div />' } },
    { path: '/projects', component: { template: '<div />' } },
  ] })
  await router.push(active === 'recommended' ? '/websites' : PERSONAL)
  await router.isReady()
  const wrapper = mount(WebsiteCollectionTabs, { props: { active }, global: { plugins: [router, i18n] } })
  mounted.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}
const tabs = (wrapper: VueWrapper) => wrapper.findAll('.website-tabs a').map((tab) => tab.text())
const personalTab = (wrapper: VueWrapper) => wrapper.get(`.website-tabs a[href="${PERSONAL}"]`)

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(fetchRecommendedWebsites).mockReset().mockResolvedValue([site])
  __resetRecommendedWebsitesSnapshotForTest()
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  useLoginPrompt().closeLoginPrompt()
  useLoginPrompt().consumeLoginRedirect()
})

describe('WebsiteCollectionTabs', () => {
  it('tells visitors on the editor picks, in one line, why their own collection needs a sign-in', async () => {
    const { wrapper, router } = await mountTabs('recommended', 'anonymous')

    expect(wrapper.classes()).toContain('website-tabs-row--with-login')
    expect(wrapper.get('.website-tabs-login').text()).toContain('「我的网页收藏」')
    expect(tabs(wrapper)).toEqual(['站长推荐', '我的网页收藏'])

    await personalTab(wrapper).trigger('click')
    await flushPromises()
    expect(useLoginPrompt().isOpen.value).toBe(true)
    expect(useLoginPrompt().redirectTarget.value).toBe(PERSONAL)
    expect(router.currentRoute.value.fullPath).toBe('/websites')

    useLoginPrompt().closeLoginPrompt()
    await wrapper.get('.website-tabs-login button').trigger('click')
    expect(useLoginPrompt().isOpen.value).toBe(true)
    expect(fetchRecommendedWebsites).not.toHaveBeenCalled()
  })

  it('takes signed-in users straight to their collection', async () => {
    const { wrapper, router } = await mountTabs('recommended', 'authenticated')

    expect(wrapper.find('.website-tabs-login').exists()).toBe(false)
    expect(wrapper.classes()).not.toContain('website-tabs-row--with-login')
    await personalTab(wrapper).trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe(PERSONAL)
    expect(useLoginPrompt().isOpen.value).toBe(false)
  })

  it.each(['initializing', 'authenticated'] as const)('adds no login line while the visitor is %s', async (status) => {
    const { wrapper } = await mountTabs('recommended', status)
    expect(wrapper.find('.website-tabs-login').exists()).toBe(false)
  })

  it('leaves the sign-in to the collection page itself', async () => {
    const { wrapper } = await mountTabs('personal', 'anonymous')
    expect(wrapper.find('.website-tabs-login').exists()).toBe(false)
    expect(wrapper.get('[aria-current="page"]').text()).toBe('我的网页收藏')
  })

  it('looks the picks up from the collection page and hides their tab once they come back empty', async () => {
    vi.mocked(fetchRecommendedWebsites).mockResolvedValue([])
    const { wrapper } = await mountTabs('personal', 'authenticated')

    expect(fetchRecommendedWebsites).toHaveBeenCalledOnce()
    expect(tabs(wrapper)).toEqual(['我的网页收藏'])
  })

  it('keeps the picks tab while the list is unknown or has entries', async () => {
    vi.mocked(fetchRecommendedWebsites).mockRejectedValue(new Error('offline'))
    const unknown = await mountTabs('personal', 'anonymous')
    expect(tabs(unknown.wrapper)).toEqual(['站长推荐', '我的网页收藏'])

    rememberRecommendedWebsites([site])
    const known = await mountTabs('personal', 'authenticated')
    expect(tabs(known.wrapper)).toEqual(['站长推荐', '我的网页收藏'])
  })

  it('keeps an empty picks tab for admins, who add the entries', async () => {
    rememberRecommendedWebsites([])
    const { wrapper } = await mountTabs('personal', 'authenticated', 'admin')

    expect(tabs(wrapper)).toEqual(['站长推荐', '我的网页收藏'])
    expect(fetchRecommendedWebsites).not.toHaveBeenCalled()
  })

  it('keeps the picks tab on the picks page even while it is empty', async () => {
    rememberRecommendedWebsites([])
    const { wrapper } = await mountTabs('recommended', 'anonymous')

    expect(wrapper.get('[aria-current="page"]').text()).toBe('站长推荐')
  })
})
