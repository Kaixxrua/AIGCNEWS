import { mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MembershipView from './MembershipView.vue'
import type { SiteContactPage } from '@/services/site/contactPageApi'

const authBox = vi.hoisted(() => ({ isMember: false }))
const configBox = vi.hoisted(() => ({ current: null as null | { value: SiteContactPage } }))

vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authBox }))

vi.mock('@/composables/useContactPageConfig', async () => {
  const { ref } = await import('vue')
  if (!configBox.current) {
    configBox.current = ref<SiteContactPage>({
      enabled: false,
      navLabel: '',
      title: '',
      subtitle: '',
      serviceCards: [],
      contactEntries: [],
      bodyMarkdown: '',
      updatedAt: null,
    })
  }
  return { useContactPageConfig: () => ({ contactPageConfig: configBox.current }) }
})

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      membership: {
        title: '会员',
        subtitle: '解锁更高的 MCP 调用额度与全部简报模块。',
        free: {
          name: '免费版',
          price: '¥0',
          currentPlan: '当前默认方案',
          features: {
            mcpAnonymous: 'MCP 匿名调用 100 次/天',
            mcpFree: '注册并创建令牌后 3,000 次/月',
            briefingFree: '简报订阅 1 个日报模块',
          },
        },
        member: {
          name: '会员',
          badge: '推荐',
          priceMonthly: '¥19',
          priceMonthlyPeriod: '/ 月',
          priceYearly: '¥129 / 年',
          priceYearlyAmount: '¥129',
          priceYearlyPeriod: '/ 年',
          yearlySavings: '年付省 ¥99',
          yearlyDiscount: '-43%',
          billMonthly: '按月付',
          billYearly: '按年付',
          features: {
            mcpMember: 'MCP 调用 100,000 次/月',
            briefingMember: '简报订阅全部 8 个模块',
            support: '优先支持与后续会员权益',
          },
        },
        currentMember: '当前已是会员',
        cta: '联系开通',
        ctaHint: '在线支付接入中：先联系我们开通，确认后立即生效。',
        ctaMailSubject: 'AIGC News 会员开通咨询',
        memberNote: '感谢支持！会员权益已生效。',
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

const mountView = () =>
  mount(MembershipView, {
    global: { plugins: [i18n], stubs: { RouterLink: RouterLinkStub } },
  })

beforeEach(() => {
  authBox.isMember = false
  configBox.current!.value = { ...configBox.current!.value, enabled: false }
})

describe('MembershipView', () => {
  it('renders the tier comparison with commercial pricing structure', () => {
    const wrapper = mountView()
    const text = wrapper.text()

    expect(text).toContain('会员')
    expect(text).toContain('免费版')
    // 大字号金额 + 周期后缀拆分 + 年付锚定 + 节省标
    expect(text).toContain('¥19')
    expect(text).toContain('/ 月')
    expect(text).toContain('¥129 / 年')
    expect(text).toContain('年付省 ¥99')
    expect(text).toContain('推荐')
    expect(text).toContain('当前默认方案')
    expect(text).toContain('MCP 调用 100,000 次/月')
    expect(text).toContain('简报订阅 1 个日报模块')
    expect(text).toContain('简报订阅全部 8 个模块')
  })

  it('links the in-card CTA to the contact page when the site page is enabled', () => {
    configBox.current!.value = { ...configBox.current!.value, enabled: true }
    const wrapper = mountView()

    const link = wrapper.findComponent(RouterLinkStub)
    expect(link.exists()).toBe(true)
    expect(link.props('to')).toBe('/contact')
    expect(link.classes()).toContain('tier-cta')
  })

  it('falls back to a mailto CTA when the contact page is disabled', () => {
    const wrapper = mountView()

    const anchor = wrapper.find('a.tier-cta')
    expect(anchor.exists()).toBe(true)
    expect(anchor.attributes('href')).toContain('mailto:kaixxrua@gmail.com')
    expect(anchor.attributes('href')).toContain(encodeURIComponent('AIGC News 会员开通咨询'))
  })

  it('shows the active-member state instead of the CTA for members', () => {
    authBox.isMember = true
    const wrapper = mountView()

    expect(wrapper.find('.tier-badge').text()).toBe('当前已是会员')
    expect(wrapper.text()).toContain('感谢支持！会员权益已生效。')
    expect(wrapper.find('a.tier-cta').exists()).toBe(false)
    expect(wrapper.findComponent(RouterLinkStub).exists()).toBe(false)
  })

  it('marks the member card with the recommended badge for non-members', () => {
    const wrapper = mountView()

    expect(wrapper.find('.tier-badge').text()).toBe('推荐')
  })

  it('toggles the member price between monthly and yearly billing', async () => {
    const wrapper = mountView()
    const memberCard = wrapper.find('.tier-card--member')
    const button = memberCard.find('.tier-billing-btn')
    const amount = () => memberCard.find('.tier-price-amount').text()
    const period = () => memberCard.find('.tier-price-period').text()
    const yearlyLine = () => memberCard.find('.tier-price-yearly').text()

    // 默认月付：大价 ¥19/月，副行年付锚定，按钮指向年付并带 -43% 折扣标
    expect(button.text()).toContain('按年付')
    expect(button.find('.tier-billing-tag').text()).toBe('-43%')
    expect(button.attributes('aria-pressed')).toBe('false')
    expect(amount()).toBe('¥19')
    expect(period()).toBe('/ 月')
    expect(yearlyLine()).toContain('¥129 / 年')
    expect(yearlyLine()).toContain('年付省 ¥99')

    // 切到年付：大价换 ¥129/年，副行回指月付，节省标常驻；降级按钮不带折扣标
    await button.trigger('click')
    expect(button.text()).toBe('按月付')
    expect(button.find('.tier-billing-tag').exists()).toBe(false)
    expect(button.attributes('aria-pressed')).toBe('true')
    expect(amount()).toBe('¥129')
    expect(period()).toBe('/ 年')
    expect(yearlyLine()).toContain('¥19/ 月')
    expect(yearlyLine()).toContain('年付省 ¥99')

    // 再切回月付，折扣标回来
    await button.trigger('click')
    expect(button.text()).toContain('按年付')
    expect(button.find('.tier-billing-tag').text()).toBe('-43%')
    expect(amount()).toBe('¥19')
    expect(period()).toBe('/ 月')
  })
})
