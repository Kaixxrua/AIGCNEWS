import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { messages } from '@/i18n'
import { setAppDensity } from '@/composables/useAppDensity'
import MembershipView from './MembershipView.vue'

// 桌面（≥1024px）三张卡排成一张对比表，手机与平板仍是三张卡；jsdom 没有 matchMedia，按标志切换。
const viewport = vi.hoisted(() => ({ desktop: true }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return {
    ...actual,
    useMediaQuery: (query: string) => (query === '(min-width: 1024px)' ? ref(viewport.desktop) : actual.useMediaQuery(query)),
  }
})

const authBox = vi.hoisted(() => ({ isMember: false }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authBox }))
// 支付总开关关闭：plans 整组 404，vip 卡不报价、开通走联系兜底。
vi.mock('@/services/payments/paymentApi', () => ({
  paymentApi: { listPlans: vi.fn(async () => Promise.reject(Object.assign(new Error('Not Found'), { response: { status: 404 } }))) },
}))
vi.mock('@/composables/useContactPageConfig', async () => {
  const { ref } = await import('vue')
  const contactPageConfig = ref({
    enabled: false, navLabel: '', title: '', subtitle: '', serviceCards: [], contactEntries: [], bodyMarkdown: '', updatedAt: null,
  })
  return { useContactPageConfig: () => ({ contactPageConfig }) }
})

const ROW_NAMES = ['浏览榜单、论文与项目库', '关键词或项目追踪', '每日个人简报', '个人网页收藏', 'UI 灵感库复制', 'MCP/API 额度（共用）', '简报邮件订阅', '简报 RSS 订阅']

const mounted: VueWrapper[] = []
const mountView = () => {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages, missingWarn: false, fallbackWarn: false })
  const wrapper = mount(MembershipView, { global: { plugins: [i18n], components: { RouterLink: RouterLinkStub } } })
  mounted.push(wrapper)
  return wrapper
}
const column = (wrapper: VueWrapper, tier: number) => {
  const card = wrapper.findAll('.tier-card')[tier]
  if (!card) throw new Error(`tier card ${tier} missing`)
  return card.findAll('.tier-features--compare li')
}

beforeEach(() => {
  viewport.desktop = true
  authBox.isMember = false
})

afterEach(() => {
  while (mounted.length) mounted.pop()?.unmount()
  setAppDensity('compact')
  localStorage.clear()
})

describe('MembershipView desktop comparison', () => {
  it('names the rows down the left and gives every plan one cell per row', () => {
    const wrapper = mountView()
    const card = wrapper.get('.membership-card')
    expect(card.classes()).toContain('membership-card--compare')
    expect(card.attributes('style')).toContain('--compare-rows: 8')

    const names = wrapper.get('.tier-rows')
    expect(names.attributes('aria-hidden')).toBe('true')
    expect(names.findAll('.tier-row-label').map((label) => label.text())).toEqual(ROW_NAMES)

    for (const tier of [0, 1, 2]) expect(column(wrapper, tier)).toHaveLength(ROW_NAMES.length)
    expect(column(wrapper, 0).filter((cell) => cell.classes('tier-feature--excluded'))).toHaveLength(6)
    expect(column(wrapper, 1).filter((cell) => cell.classes('tier-feature--excluded'))).toHaveLength(0)
    expect(column(wrapper, 2).filter((cell) => cell.classes('tier-feature--excluded'))).toHaveLength(0)

    expect(column(wrapper, 1)[3]?.find('.tier-cell-line').text()).toBe('滚动 24 小时最多添加 3 个')
    expect(column(wrapper, 1)[4]?.find('.tier-cell-line').text()).toBe('每天 5 次，源码与提示词共用')
    expect(column(wrapper, 2)[4]?.find('.tier-cell-line').text()).toBe('不限次')
    expect(column(wrapper, 2)[5]?.findAll('.tier-cell-line').map((line) => line.text())).toEqual(['每 24 小时最多 400 次', '每 30 天最多 8,000 次'])
    expect(wrapper.find('.tier-card ul:not(.tier-features--compare)').exists()).toBe(false)
  })

  it('tells screen readers which benefit each cell holds and whether it is included', () => {
    const wrapper = mountView()
    const guestTracking = column(wrapper, 0)[1]
    expect(guestTracking?.find('.tier-x').exists()).toBe(true)
    expect(guestTracking?.findAll('.sr-only').map((text) => text.text())).toEqual(['关键词或项目追踪：', '不包含'])

    const freeDigest = column(wrapper, 1)[2]
    expect(freeDigest?.find('.tier-check').exists()).toBe(true)
    expect(freeDigest?.findAll('.sr-only').map((text) => text.text())).toEqual(['每日个人简报：', '包含'])

    const freeTracking = column(wrapper, 1)[1]
    expect(freeTracking?.text()).toBe('关键词或项目追踪：1 条')
  })

  it('runs a highlighter under what a plan gives more of than the plan to its left, and mutes the row all three share', () => {
    const wrapper = mountView()
    const marked = (tier: number) => column(wrapper, tier)
      .filter((cell) => cell.classes('tier-feature--upgrade'))
      .map((cell) => cell.findAll('.tier-cell-text').map((text) => text.text()))
    expect(marked(0)).toEqual([])
    expect(marked(1)).toEqual([['每 24 小时最多 60 次', '每 30 天最多 1,200 次']])
    expect(marked(2)).toEqual([['10 条，支持排除词', 'AI 客户端经 MCP 可读'], ['自选时间与已验证投递渠道', '附关键词热度飙升提醒', '可导出最近 90 天'], ['添加不限量'], ['不限次'], ['每 24 小时最多 400 次', '每 30 天最多 8,000 次']])
    // ✗ 到 ✓ 不划：免费档的追踪比游客多，但游客那格的 ✗ 已经说明了
    expect(column(wrapper, 1)[1]?.classes()).not.toContain('tier-feature--upgrade')

    expect(wrapper.findAll('.tier-row-label--same').map((label) => label.text())).toEqual([ROW_NAMES[0]])
    for (const tier of [0, 1, 2]) {
      expect(column(wrapper, tier).map((cell) => cell.classes('tier-feature--same'))).toEqual([true, false, false, false, false, false, false, false])
    }
  })

  it('keeps the buy button and its hint in the vip column', async () => {
    const wrapper = mountView()
    await flushPromises()
    const member = wrapper.get('.tier-card--member')
    expect(member.get('a.tier-cta').text()).toBe('联系开通')
    expect(member.get('.tier-cta-hint').text()).toBe('在线支付接入中：先联系我们开通，确认后立即生效。')

    authBox.isMember = true
    const memberView = mountView()
    expect(memberView.find('.tier-cta').exists()).toBe(false)
    expect(memberView.get('.tier-member-note').text()).toBe('感谢支持！vip 权益已生效。')
  })

  it('goes back to the three plan cards on the desktop when the masthead asks for the comfortable layout', async () => {
    setAppDensity('comfortable')
    const wrapper = mountView()
    expect(wrapper.get('.membership-card').classes()).not.toContain('membership-card--compare')
    expect(wrapper.get('.membership-card').attributes('style')).toBeUndefined()
    expect(wrapper.find('.tier-rows').exists()).toBe(false)
    expect(wrapper.find('.tier-features--compare').exists()).toBe(false)
    expect(wrapper.findAll('.tier-card')[0]?.findAll('.tier-features li')).toHaveLength(6)

    setAppDensity('compact')
    await nextTick()
    expect(wrapper.get('.membership-card').classes()).toContain('membership-card--compare')
    expect(wrapper.find('.tier-rows').exists()).toBe(true)
    for (const tier of [0, 1, 2]) expect(column(wrapper, tier)).toHaveLength(ROW_NAMES.length)
  })

  it('keeps phones and tablets on the three plan cards', () => {
    viewport.desktop = false
    const wrapper = mountView()
    expect(wrapper.get('.membership-card').classes()).not.toContain('membership-card--compare')
    expect(wrapper.get('.membership-card').attributes('style')).toBeUndefined()
    expect(wrapper.find('.tier-rows').exists()).toBe(false)
    expect(wrapper.find('.tier-features--compare').exists()).toBe(false)
    const guest = wrapper.findAll('.tier-card')[0]
    expect(guest?.findAll('.tier-features li')).toHaveLength(6)
    expect(guest?.findAll('.tier-feature--excluded')).toHaveLength(4)
    expect(guest?.text()).toContain('MCP 匿名额度：每 24 小时 30 次')
  })
})
