import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ContactPageView from './ContactPageView.vue'
import type { SiteContactPage } from '@/services/site/contactPageApi'
import { messages, DEFAULT_LOCALE } from '@/i18n'

const configBox = vi.hoisted(() => ({ current: null as null | { value: SiteContactPage } }))

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
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  messages,
})

/** 默认夹具对齐生产形态：交流群（QR）+ 邮箱（mailto）两条联系方式 */
const setConfig = (overrides: Partial<SiteContactPage> = {}) => {
  configBox.current!.value = {
    enabled: true,
    navLabel: '合作',
    title: '联系合作',
    subtitle: '外包 · 商务合作',
    serviceCards: [
      { title: '外包开发', description: 'AI 应用定制', icon: 'code' },
      { title: '商务合作', description: '', icon: 'unknown-icon-key' },
    ],
    contactEntries: [
      { label: 'QQ 群', value: '123456', href: '', qrImageUrl: '/qr.png' },
      { label: '邮箱', value: 'hi@example.com', href: 'mailto:hi@example.com', qrImageUrl: '' },
    ],
    bodyMarkdown: '# 欢迎\n\n**加粗**段落',
    updatedAt: null,
    ...overrides,
  }
}

const mountView = () =>
  mount(ContactPageView, {
    global: { plugins: [i18n] },
  })

describe('ContactPageView', () => {
  beforeEach(() => {
    setConfig()
  })

  it('renders the heading and contact entries, but never service cards or the markdown body', () => {
    const wrapper = mountView()

    expect(wrapper.find('.contact-title').text()).toBe('联系合作')
    expect(wrapper.find('.contact-subtitle').text()).toBe('外包 · 商务合作')
    expect(wrapper.find('.contact-kicker').text()).toBe('联系合作')

    const entries = wrapper.findAll('.entry-item')
    expect(entries).toHaveLength(2)

    // 展示层取舍：后台仍配置了服务卡/Markdown，但页面不渲染这些区块
    expect(wrapper.find('.service-card').exists()).toBe(false)
    expect(wrapper.find('.service-grid').exists()).toBe(false)
    expect(wrapper.find('.contact-markdown').exists()).toBe(false)
    expect(wrapper.find('.section-heading').exists()).toBe(false)
  })

  it('docks the entry list inside the full-bleed hero', () => {
    const wrapper = mountView()

    const hero = wrapper.find('.contact-hero')
    expect(hero.exists()).toBe(true)
    const dock = hero.find('.hero-dock')
    expect(dock.exists()).toBe(true)
    expect(dock.find('.entry-list').exists()).toBe(true)
    expect(dock.find('.contact-hero-note').text()).toBe('按你的需求，选择合适的联系入口。')
  })

  it('renders QR image only for entries with qrImageUrl', () => {
    const wrapper = mountView()
    const entries = wrapper.findAll('.entry-item')

    const qr = entries[0]!.find('img.entry-qr')
    expect(qr.exists()).toBe(true)
    expect(qr.attributes('src')).toBe('/qr.png')
    expect(qr.attributes('alt')).toBe('QQ 群')
    expect(entries[1]!.find('img.entry-qr').exists()).toBe(false)
  })

  it('shows QR only on the primary entry when more than two entries are configured', () => {
    setConfig({
      contactEntries: [
        { label: 'QQ 群', value: '123456', href: '', qrImageUrl: '/qr.png' },
        { label: '邮箱', value: 'hi@example.com', href: 'mailto:hi@example.com', qrImageUrl: '/mail-qr.png' },
        { label: '官网', value: '', href: 'https://example.com', qrImageUrl: '/web-qr.png' },
      ],
    })
    const wrapper = mountView()
    const entries = wrapper.findAll('.entry-item')

    // 邮箱是第一个带 href 的条目（primary），仅它显示 QR
    expect(entries[0]!.find('.entry-qr-frame').exists()).toBe(false)
    expect(entries[1]!.find('img.entry-qr').attributes('src')).toBe('/mail-qr.png')
    expect(entries[2]!.find('.entry-qr-frame').exists()).toBe(false)
  })

  it('links http(s) hrefs externally and other schemes in-place', () => {
    setConfig({
      contactEntries: [
        { label: 'QQ 群', value: '123456', href: '', qrImageUrl: '/qr.png' },
        { label: '邮箱', value: 'hi@example.com', href: 'mailto:hi@example.com', qrImageUrl: '' },
        { label: '官网', value: '', href: 'https://example.com', qrImageUrl: '' },
      ],
    })
    const wrapper = mountView()
    const entries = wrapper.findAll('.entry-item')

    const mailLink = entries[1]!.find('a.entry-value--link')
    expect(mailLink.attributes('href')).toBe('mailto:hi@example.com')
    expect(mailLink.attributes('target')).toBeUndefined()

    const webLink = entries[2]!.find('a.entry-value--link')
    expect(webLink.attributes('href')).toBe('https://example.com')
    expect(webLink.attributes('target')).toBe('_blank')
    expect(webLink.attributes('rel')).toBe('noopener noreferrer')
    // value 为空时以 href 作为链接文案
    expect(webLink.find('.entry-link-text').text()).toBe('https://example.com')

    // 无 href 的条目渲染纯文本值
    expect(entries[0]!.find('a').exists()).toBe(false)
    expect(entries[0]!.find('.entry-value').text()).toBe('123456')
  })

  it('highlights the first actionable entry as primary', () => {
    const wrapper = mountView()
    const entries = wrapper.findAll('.entry-item')

    // 第一个带 href 的联系方式是邮箱（索引 1），优先作为主动作
    expect(entries[1]!.classes()).toContain('entry-item--primary')
    expect(entries[1]!.find('.entry-badge').text()).toBe('优先入口')
    expect(entries[0]!.classes()).not.toContain('entry-item--primary')
  })

  it('falls back to the first QR-only entry when no href is available', () => {
    setConfig({
      contactEntries: [
        { label: 'QQ 群', value: '123456', href: '', qrImageUrl: '/qr.png' },
        { label: '微信群', value: '', href: '', qrImageUrl: '/wechat.png' },
      ],
    })
    const wrapper = mountView()
    const entries = wrapper.findAll('.entry-item')

    expect(entries[0]!.classes()).toContain('entry-item--primary')
    expect(entries[0]!.find('.entry-badge').text()).toBe('优先入口')
    expect(entries[1]!.classes()).not.toContain('entry-item--primary')
  })

  it('renders QR fallback when the image fails to load', async () => {
    const wrapper = mountView()
    const qr = wrapper.find('img.entry-qr')

    await qr.trigger('error')

    expect(wrapper.find('img.entry-qr').exists()).toBe(false)
    expect(wrapper.find('.entry-qr-fallback').text()).toBe('二维码暂时无法显示')
  })

  it('hides the dock and hero note when no contact entries are configured', () => {
    setConfig({ contactEntries: [], subtitle: '' })
    const wrapper = mountView()

    expect(wrapper.find('.contact-title').exists()).toBe(true)
    expect(wrapper.find('.hero-dock').exists()).toBe(false)
    expect(wrapper.find('.entry-list').exists()).toBe(false)
    expect(wrapper.find('.contact-hero-note').exists()).toBe(false)
    expect(wrapper.find('.contact-subtitle').exists()).toBe(false)
  })

  it('renders nothing when the page is disabled (defensive root guard)', () => {
    setConfig({ enabled: false })
    const wrapper = mountView()

    expect(wrapper.find('.contact-page').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('shows the typed command line with the caret hidden from assistive tech', () => {
    const wrapper = mountView()

    const command = wrapper.find('.contact-command')
    expect(command.exists()).toBe(true)
    expect(command.attributes('aria-hidden')).toBe('true')
    expect(command.text()).toContain('aigcnews contact --list')
    // 唯一的动效元素必须位于命令行内部（hallmark 终端纪律）
    expect(command.find('.term-caret').exists()).toBe(true)
    expect(wrapper.findAll('.term-line').every((line) => line.attributes('aria-hidden') === 'true')).toBe(true)
  })

  it('marks tree branches with ├── for rows and └── for the last row', () => {
    const wrapper = mountView()

    const entryBranches = wrapper.findAll('.entry-item .tree-branch').map((b) => b.text())
    expect(entryBranches).toEqual(['├──', '└──'])
  })

  it('renders the WebGL hero layer with static fallback and inert legacy nodes', () => {
    const wrapper = mountView()

    const field = wrapper.find('.hero-field')
    expect(field.exists()).toBe(true)
    expect(field.attributes('aria-hidden')).toBe('true')
    // 三层合成：场景视觉层（无 WebGL2 的 jsdom 下停在静态兜底）→ 遮罩 → 内容
    const visual = field.find('.hero-visual')
    expect(visual.exists()).toBe(true)
    expect(visual.attributes('aria-hidden')).toBe('true')
    expect(visual.find('canvas.hero-canvas').exists()).toBe(true)
    expect(visual.find('.hero-fallback').exists()).toBe(true)
    expect(field.find('.hero-overlay').exists()).toBe(true)
    // 旧 beam/scanline 契约节点保留但不可见、无动画职责
    const beams = field.findAll('.hero-beam')
    expect(beams).toHaveLength(4)
    expect(beams.every((beam) => beam.attributes('hidden') !== undefined)).toBe(true)
    expect(field.find('.hero-scanline').attributes('hidden')).toBeDefined()
  })

  it('does not render the hero visual when the page is disabled', () => {
    setConfig({ enabled: false })
    const wrapper = mountView()

    expect(wrapper.find('.hero-visual').exists()).toBe(false)
    expect(wrapper.find('.hero-field').exists()).toBe(false)
  })
})
