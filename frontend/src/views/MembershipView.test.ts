import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MembershipView from './MembershipView.vue'
import type { SiteContactPage } from '@/services/site/contactPageApi'

const authBox = vi.hoisted(() => ({ isMember: false, isLoggedIn: false }))
const configBox = vi.hoisted(() => ({ current: null as null | { value: SiteContactPage } }))
const paymentBox = vi.hoisted(() => ({ listPlans: vi.fn() }))

vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authBox }))
vi.mock('@/services/payments/paymentApi', () => ({ paymentApi: paymentBox }))

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
        title: 'vip',
        subtitle: '解锁更高的 MCP 调用额度与个人网页不限量收藏。',
        guest: {
          name: 'guest',
          price: '¥0',
          note: '无需注册，打开即用',
          features: {
            browse: '浏览榜单、论文与项目库',
            mcpAnonymous: 'MCP 匿名额度：每 24 小时 30 次',
            rss: 'RSS 订阅',
            briefing: '简报邮件订阅',
            website: '个人网页收藏',
            uiCopy: 'UI 灵感库复制源码与提示词',
          },
        },
        free: {
          name: 'free',
          price: '¥0',
          currentPlan: '当前默认方案',
          register: '免费注册',
          includedInMember: '已包含在会员权益中',
          features: {
            tracking: '1 条追踪规则',
            mcpFree: 'MCP/API 共用：每 24 小时 60 次 + 每 30 天 1,200 次',
            websiteFree: '滚动 24 小时最多添加 3 个个人网页收藏',
            uiCopyFree: 'UI 灵感库每天复制 5 次，源码与提示词共用',
            briefingFree: '简报订阅全部 8 个日报模块',
            rssFree: 'RSS 每日综合简报与简报速览订阅',
          },
        },
        member: {
          name: 'vip',
          badge: '推荐',
          priceMonthlyPeriod: '/ 月',
          priceYearlyPeriod: '/ 年',
          yearlySavings: '年付省 {amount}',
          yearlyDiscount: '-{percent}%',
          billMonthly: '按月付',
          billYearly: '按年付',
          priceLoading: '价格加载中',
          priceFailed: '价格没加载出来',
          priceRetry: '重试',
          priceUnavailable: '价格请联系咨询',
          features: {
            mcpMember: 'MCP/API 共用：每 24 小时 400 次 + 每 30 天 8,000 次',
            websiteMember: '个人网页收藏添加不限量',
            uiCopyMember: 'UI 灵感库复制不限次',
            tracking: '10 条关键词或项目追踪',
            mcpTracking: '在 AI 客户端里经 MCP 读取自己的追踪结果',
            personalDigest: '每日个人简报',
            surgeAlerts: '关注的关键词热度飙升时，在简报里提醒',
            historyExport: '导出最近 90 天个人简报（CSV / JSON）',
          },
        },
        currentMember: '当前已是 vip',
        cta: '联系开通',
        ctaOnline: '立即开通',
        ctaOnlineHint: '在线支付：支付成功后权益立即生效。',
        ctaHint: '在线支付接入中：先联系我们开通，确认后立即生效。',
        ctaMailSubject: 'AIGC News vip 开通咨询',
        memberNote: '感谢支持！vip 权益已生效。',
      },
    },
    // 英文只钉定价区所需键（其余键缺失时按 key 渲染，不影响金额断言）
    'en-US': {
      membership: {
        member: {
          priceMonthlyPeriod: '/ month',
          priceYearlyPeriod: '/ year',
          yearlySavings: 'Save {amount} yearly',
          yearlyDiscount: '-{percent}%',
          billMonthly: 'Bill monthly',
          billYearly: 'Bill yearly',
          priceUnavailable: 'Contact us for pricing',
        },
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

/* RouterLink 未注册时 Vue 3.5 会把它渲染成注释节点，stubs 拦截不到未解析组件；
   用 global.components 直接注册桩，RouterLinkStub 才会真正渲染并可被 findComponent 断言。 */
const mountView = () =>
  mount(MembershipView, {
    global: { plugins: [i18n], components: { RouterLink: RouterLinkStub } },
  })

const livePlans = (monthlyCents: number, yearlyCents: number) => ({
  plans: [
    { code: 'member_monthly', tier: 'member', amount_cents: monthlyCents, currency: 'CNY', months: 1 },
    { code: 'member_yearly', tier: 'member', amount_cents: yearlyCents, currency: 'CNY', months: 12 },
  ],
  channels: [],
})
// 支付总开关关闭时 /api/payments/* 整组 404。
const paymentsOff = () => Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } })

beforeEach(() => {
  authBox.isMember = false
  authBox.isLoggedIn = false
  configBox.current!.value = { ...configBox.current!.value, enabled: false }
  paymentBox.listPlans.mockReset().mockResolvedValue(livePlans(990, 8880))
  i18n.global.locale.value = 'zh-CN'
})

describe('MembershipView', () => {
  it('renders the tier comparison with commercial pricing structure', async () => {
    const wrapper = mountView()
    await flushPromises()
    const text = wrapper.text()

    expect(text).toContain('vip')
    expect(text).toContain('free')
    expect(text).toContain('guest')
    // 大字号金额 + 周期后缀拆分 + 年付锚定 + 节省标（都按 plans 接口价）
    expect(text).toContain('¥9.9')
    expect(text).toContain('/ 月')
    expect(text).toContain('¥88.8 / 年')
    expect(text).toContain('年付省 ¥30')
    expect(text).toContain('推荐')
    expect(text).toContain('免费注册')
    expect(text).toContain('无需注册，打开即用')
    expect(text).toContain('浏览榜单、论文与项目库')
    expect(text).toContain('MCP 匿名额度：每 24 小时 30 次')
    expect(text).toContain('MCP/API 共用：每 24 小时 60 次 + 每 30 天 1,200 次')
    expect(text).toContain('MCP/API 共用：每 24 小时 400 次 + 每 30 天 8,000 次')
    expect(text).toContain('滚动 24 小时最多添加 3 个个人网页收藏')
    expect(text).toContain('个人网页收藏添加不限量')
    expect(text).toContain('UI 灵感库每天复制 5 次，源码与提示词共用')
    expect(text).toContain('UI 灵感库复制不限次')
    // 简报/RSS 已并入免费档：免费档含全部 8 模块与双 RSS，会员卡只保留工具权益
    expect(text).toContain('简报订阅全部 8 个日报模块')
    expect(text).toContain('RSS 每日综合简报与简报速览订阅')
    expect(text).toContain('RSS 订阅')
  })

  it('marks excluded features with ✗ so tiers do not read as all-checkmarks', () => {
    const wrapper = mountView()
    const cards = wrapper.findAll('.tier-card')
    expect(cards).toHaveLength(3)

    const guestCard = wrapper.get('.tier-card--guest')
    const freeCard = wrapper.get('.tier-card--free')
    const memberCard = wrapper.get('.tier-card--member')
    if (!guestCard || !freeCard || !memberCard) throw new Error('tier cards missing')
    // guest：RSS / 简报 / 网页收藏 / UI 灵感库复制四项排除；free 与 vip 均无排除项
    expect(guestCard.findAll('.tier-feature--excluded')).toHaveLength(4)
    expect(freeCard.findAll('.tier-feature--excluded')).toHaveLength(0)
    expect(memberCard.findAll('.tier-feature--excluded')).toHaveLength(0)

    // guest 的 RSS 行必须是 ✗（排除态），与免费/vip 的 ✓ 形成区分
    const guestRows = guestCard.findAll('.tier-features li')
    const guestRssRow = guestRows.find((row) => row.text().includes('RSS 订阅'))
    expect(guestRssRow?.classes()).toContain('tier-feature--excluded')
    expect(guestRssRow?.find('.tier-x').exists()).toBe(true)
    expect(guestRssRow?.find('.tier-check').exists()).toBe(false)

    const freeRows = freeCard.findAll('.tier-features li')
    const freeRssRow = freeRows.find((row) => row.text().includes('RSS 每日综合简报'))
    expect(freeRssRow?.classes()).not.toContain('tier-feature--excluded')
    expect(freeRssRow?.find('.tier-check').exists()).toBe(true)

    // VIP 展示个人追踪和个人简报，公共 RSS 仍属于免费权益
    expect(memberCard.findAll('.tier-check')).toHaveLength(8)
    expect(memberCard.text()).not.toContain('RSS')
    expect(memberCard.text()).toContain('10 条关键词或项目追踪')
    expect(memberCard.text()).toContain('每日个人简报')
    expect(memberCard.text()).toContain('经 MCP 读取自己的追踪结果')
    expect(memberCard.text()).toContain('关注的关键词热度飙升时，在简报里提醒')
    expect(memberCard.text()).toContain('导出最近 90 天个人简报（CSV / JSON）')
    expect(memberCard.text()).not.toContain('后续 vip 权益')

    // 排除项图标总数 = guest 的 4 项
    expect(wrapper.findAll('.tier-x')).toHaveLength(4)

    // 免费档：网页上就能用到的权益在前，MCP/API 额度挪到后面
    expect(freeCard.findAll('.tier-features li').map((row) => row.text())).toEqual([
      '1 条追踪规则',
      '滚动 24 小时最多添加 3 个个人网页收藏',
      'UI 灵感库每天复制 5 次，源码与提示词共用',
      'MCP/API 共用：每 24 小时 60 次 + 每 30 天 1,200 次',
      '简报订阅全部 8 个日报模块',
      'RSS 每日综合简报与简报速览订阅',
    ])
  })

  it('links the in-card CTA to the online checkout when plans are available', async () => {
    const wrapper = mountView()
    await flushPromises()

    const link = wrapper.find('.tier-card--member').findComponent(RouterLinkStub)
    expect(link.exists()).toBe(true)
    expect(link.props('to')).toEqual({ path: '/membership/checkout', query: { plan: 'monthly' } })
    expect(link.text()).toContain('立即开通')
    expect(link.classes()).toContain('tier-cta')
  })

  it('links the in-card CTA to the contact page when payments are off and the site page is enabled', async () => {
    paymentBox.listPlans.mockRejectedValue(paymentsOff())
    configBox.current!.value = { ...configBox.current!.value, enabled: true }
    const wrapper = mountView()
    await flushPromises()

    const link = wrapper.find('.tier-card--member').findComponent(RouterLinkStub)
    expect(link.exists()).toBe(true)
    expect(link.props('to')).toBe('/contact')
    expect(link.classes()).toContain('tier-cta')
  })

  it('falls back to a mailto CTA when payments are off and the contact page is disabled', async () => {
    paymentBox.listPlans.mockRejectedValue(paymentsOff())
    const wrapper = mountView()
    await flushPromises()

    const anchor = wrapper.find('a.tier-cta')
    expect(anchor.exists()).toBe(true)
    expect(anchor.attributes('href')).toContain('mailto:kaixxrua@gmail.com')
    expect(anchor.attributes('href')).toContain(encodeURIComponent('AIGC News vip 开通咨询'))
  })

  it('shows the active-member state instead of the CTA for members', () => {
    authBox.isMember = true
    const wrapper = mountView()

    expect(wrapper.find('.tier-badge').text()).toBe('当前已是 vip')
    expect(wrapper.text()).toContain('感谢支持！vip 权益已生效。')
    expect(wrapper.find('a.tier-cta').exists()).toBe(false)
    expect(wrapper.find('.tier-card--member').findComponent(RouterLinkStub).exists()).toBe(false)
  })

  it('marks the member card with the recommended badge for non-members', () => {
    const wrapper = mountView()

    expect(wrapper.find('.tier-badge').text()).toBe('推荐')
  })

  it('updates the online checkout query when billing switches to yearly', async () => {
    const wrapper = mountView()
    await flushPromises()
    const button = wrapper.find('.tier-card--member .tier-billing-btn')
    await button.trigger('click')
    const link = wrapper.find('.tier-card--member').findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({ path: '/membership/checkout', query: { plan: 'yearly' } })
  })

  it('toggles the member price between monthly and yearly billing', async () => {
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')
    const button = memberCard.find('.tier-billing-btn')
    const amount = () => memberCard.find('.tier-price-amount').text()
    const period = () => memberCard.find('.tier-price-period').text()
    const yearlyLine = () => memberCard.find('.tier-price-yearly').text()

    // 默认月付：大价 ¥9.9/月，副行年付锚定，按钮指向年付并带 -25% 折扣标
    expect(button.text()).toContain('按年付')
    expect(button.find('.tier-billing-tag').text()).toBe('-25%')
    expect(button.attributes('aria-pressed')).toBe('false')
    expect(amount()).toBe('¥9.9')
    expect(period()).toBe('/ 月')
    expect(yearlyLine()).toContain('¥88.8 / 年')
    expect(yearlyLine()).toContain('年付省 ¥30')

    // 切到年付：大价换 ¥88.8/年，副行回指月付，节省标常驻；降级按钮不带折扣标
    await button.trigger('click')
    expect(button.text()).toBe('按月付')
    expect(button.find('.tier-billing-tag').exists()).toBe(false)
    expect(button.attributes('aria-pressed')).toBe('true')
    expect(amount()).toBe('¥88.8')
    expect(period()).toBe('/ 年')
    expect(yearlyLine()).toContain('¥9.9/ 月')
    expect(yearlyLine()).toContain('年付省 ¥30')

    // 再切回月付，折扣标回来
    await button.trigger('click')
    expect(button.text()).toContain('按年付')
    expect(button.find('.tier-billing-tag').text()).toBe('-25%')
    expect(amount()).toBe('¥9.9')
    expect(period()).toBe('/ 月')
  })

  it('holds the price place while plans load instead of flashing a default price', async () => {
    let answer: (value: ReturnType<typeof livePlans>) => void = () => {}
    paymentBox.listPlans.mockReturnValue(new Promise((resolve) => { answer = resolve }))
    const wrapper = mountView()
    const memberCard = wrapper.find('.tier-card--member')

    // 加载中：只画一块占位（读屏只读「价格加载中」），占位里没有任何金额，样式失效也露不出旧价
    const placeholder = memberCard.find('.tier-price-amount--pending')
    expect(placeholder.exists()).toBe(true)
    expect(placeholder.attributes('aria-hidden')).toBe('true')
    expect(placeholder.text()).not.toMatch(/\d/)
    expect(memberCard.find('.tier-price .sr-only').text()).toBe('价格加载中')
    // 计费按钮先在；折扣标、锚点、省钱标按同样的措辞隐形占住宽高（金额拿 00.0 顶上），价格到了版面不跳
    expect(memberCard.find('.tier-billing-btn').exists()).toBe(true)
    const pendingTag = memberCard.find('.tier-billing-tag')
    expect(pendingTag.classes()).toContain('tier-billing-tag--pending')
    expect(pendingTag.attributes('aria-hidden')).toBe('true')
    expect(pendingTag.text()).toBe('-00%')
    expect(memberCard.find('.tier-price-anchor--pending').attributes('aria-hidden')).toBe('true')
    expect(memberCard.find('.tier-price-anchor--pending').text()).toBe('00.0 / 年')
    const pendingSlip = memberCard.find('.tier-savings')
    expect(pendingSlip.classes()).toContain('tier-savings--pending')
    expect(pendingSlip.attributes('aria-hidden')).toBe('true')
    expect(pendingSlip.text()).toBe('年付省 00.0')
    // 不出任何真实或默认的价：没有货币符号，也没有旧价的数字
    expect(memberCard.text()).not.toMatch(/[¥$]/)
    for (const stale of ['19', '159', '9.9', '88.8']) expect(memberCard.text()).not.toContain(stale)
    // 开通按钮照常指向收银台，不在加载中先闪一下「联系开通」
    expect(memberCard.findComponent(RouterLinkStub).props('to')).toEqual({ path: '/membership/checkout', query: { plan: 'monthly' } })

    answer(livePlans(990, 8880))
    await flushPromises()
    expect(memberCard.find('.tier-price-amount--pending').exists()).toBe(false)
    expect(memberCard.find('.tier-price-amount').text()).toBe('¥9.9')
    expect(memberCard.find('.tier-billing-tag--pending').exists()).toBe(false)
    expect(memberCard.find('.tier-billing-tag').text()).toBe('-25%')
    expect(memberCard.find('.tier-savings--pending').exists()).toBe(false)
    expect(memberCard.find('.tier-savings').text()).toBe('年付省 ¥30')
  })

  it('offers a retry when plans fail to load, then shows the live price', async () => {
    paymentBox.listPlans.mockRejectedValueOnce(new Error('Network Error'))
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')

    // 没加载出来：一句说明 + 重试，不报价、不留计费按钮与年付锚点行
    expect(memberCard.find('.tier-price-note').text()).toContain('价格没加载出来')
    expect(memberCard.find('.tier-price-amount').exists()).toBe(false)
    expect(memberCard.find('.tier-billing-btn').exists()).toBe(false)
    expect(memberCard.find('.tier-price-yearly').exists()).toBe(false)
    expect(memberCard.text()).not.toContain('¥')
    // 支付并没关：开通仍走收银台（收银台会自己再拉一次套餐）
    expect(memberCard.findComponent(RouterLinkStub).props('to')).toEqual({ path: '/membership/checkout', query: { plan: 'monthly' } })
    expect(memberCard.find('.tier-cta-hint').text()).toBe('在线支付：支付成功后权益立即生效。')

    await memberCard.find('.tier-price-retry').trigger('click')
    await flushPromises()
    expect(paymentBox.listPlans).toHaveBeenCalledTimes(2)
    expect(memberCard.find('.tier-price-note').exists()).toBe(false)
    expect(memberCard.find('.tier-price-amount').text()).toBe('¥9.9')
    expect(memberCard.find('.tier-price-yearly').text()).toContain('¥88.8 / 年')
  })

  it('quotes no price and falls back to contact when payments are off', async () => {
    paymentBox.listPlans.mockRejectedValue(paymentsOff())
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')

    expect(memberCard.find('.tier-price-note').text()).toBe('价格请联系咨询')
    expect(memberCard.find('.tier-price-retry').exists()).toBe(false)
    expect(memberCard.find('.tier-billing-btn').exists()).toBe(false)
    expect(memberCard.find('.tier-price-yearly').exists()).toBe(false)
    expect(memberCard.text()).not.toContain('¥')
    expect(memberCard.find('a.tier-cta').text()).toBe('联系开通')
    expect(memberCard.find('.tier-cta-hint').text()).toBe('在线支付接入中：先联系我们开通，确认后立即生效。')
  })

  it('computes the member card amounts and discount from live plan data', async () => {
    // 管理员在监控页调价后：金额/锚定/节省/折扣全部由 plans 价自算
    paymentBox.listPlans.mockResolvedValue(livePlans(2500, 20000))
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')

    expect(memberCard.find('.tier-price-amount').text()).toBe('¥25')
    const yearlyLine = memberCard.find('.tier-price-yearly').text()
    expect(yearlyLine).toContain('¥200 / 年')
    expect(yearlyLine).toContain('年付省 ¥100')
    expect(memberCard.find('.tier-billing-tag').text()).toBe('-33%')

    // 切到年付态：大价与回指锚点同样跟随生效价
    await memberCard.find('.tier-billing-btn').trigger('click')
    expect(memberCard.find('.tier-price-amount').text()).toBe('¥200')
    expect(memberCard.find('.tier-price-period').text()).toBe('/ 年')
    expect(memberCard.find('.tier-price-yearly').text()).toContain('¥25/ 月')
  })

  it('hides the savings pill and discount badge when yearly is not cheaper', async () => {
    // 年付 ≥ 月付×12 时折扣非正：省钱 pill 与折扣标一起隐藏，不渲染「-0%」
    paymentBox.listPlans.mockResolvedValue(livePlans(1900, 22800))
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')

    expect(memberCard.find('.tier-savings').exists()).toBe(false)
    expect(memberCard.find('.tier-billing-tag').exists()).toBe(false)
    expect(memberCard.find('.tier-price-yearly').text()).toContain('¥228 / 年')
  })

  it('quotes no price in English when the catalog has no USD plans', async () => {
    // 英文界面只卖美元套餐：目录里只有人民币套餐时不报价（不拿人民币价或默认价顶上），开通走联系兜底
    i18n.global.locale.value = 'en-US'
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')

    expect(memberCard.find('.tier-price-note').text()).toBe('Contact us for pricing')
    expect(memberCard.find('.tier-price-amount').exists()).toBe(false)
    expect(memberCard.text()).not.toContain('$')
    expect(memberCard.find('a.tier-cta').exists()).toBe(true)
    expect(memberCard.findComponent(RouterLinkStub).exists()).toBe(false)
  })

  it('renders the live USD catalog in English', async () => {
    // 管理员调整美元价后，英文界面按 USD 套餐码拣价（CNY 行不影响）
    i18n.global.locale.value = 'en-US'
    paymentBox.listPlans.mockResolvedValue({
      plans: [
        { code: 'member_monthly', tier: 'member', amount_cents: 1900, currency: 'CNY', months: 1 },
        { code: 'member_yearly', tier: 'member', amount_cents: 15900, currency: 'CNY', months: 12 },
        { code: 'member_monthly_usd', tier: 'member', amount_cents: 550, currency: 'USD', months: 1 },
        { code: 'member_yearly_usd', tier: 'member', amount_cents: 4200, currency: 'USD', months: 12 },
      ],
      channels: [],
    })
    const wrapper = mountView()
    await flushPromises()
    const memberCard = wrapper.find('.tier-card--member')

    expect(memberCard.find('.tier-price-amount').text()).toBe('$5.5')
    expect(memberCard.find('.tier-price-yearly').text()).toContain('$42 / year')
  })
})
