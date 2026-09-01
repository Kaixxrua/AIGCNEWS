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
      { label: '官网', value: '', href: 'https://example.com', qrImageUrl: '' },
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

  it('renders hero, service cards, contact entries and markdown body when enabled', () => {
    const wrapper = mountView()

    expect(wrapper.find('.contact-title').text()).toBe('联系合作')
    expect(wrapper.find('.contact-subtitle').text()).toBe('外包 · 商务合作')
    expect(wrapper.find('.contact-kicker').text()).toBe('联系合作')

    const cards = wrapper.findAll('.service-card')
    expect(cards).toHaveLength(2)
    expect(cards[0]!.find('.service-title').text()).toBe('外包开发')
    expect(cards[0]!.find('.service-desc').text()).toBe('AI 应用定制')
    // 每张卡都渲染图标（未知 key 回退 default SVG）
    expect(cards[1]!.find('.service-icon svg').exists()).toBe(true)
    // 空描述不渲染占位元素
    expect(cards[1]!.find('.service-desc').exists()).toBe(false)

    const entries = wrapper.findAll('.entry-item')
    expect(entries).toHaveLength(3)

    const markdown = wrapper.find('.contact-markdown')
    expect(markdown.html()).toContain('<h1>欢迎</h1>')
    expect(markdown.html()).toContain('<strong>加粗</strong>')
  })

  it('renders section headings from i18n', () => {
    const wrapper = mountView()

    expect(wrapper.find('#contact-services-title').text()).toBe('我们可以一起做什么')
    expect(wrapper.find('#contact-entry-title').text()).toBe('选择联系入口')
    expect(wrapper.find('#contact-notes-title').text()).toBe('更多信息')
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

  it('links http(s) hrefs externally and other schemes in-place', () => {
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
    expect(entries[2]!.classes()).not.toContain('entry-item--primary')
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

  it('sanitizes the admin-authored markdown body', () => {
    setConfig({ bodyMarkdown: '正常段落 <script>alert(1)</script>' })
    const wrapper = mountView()
    const markdown = wrapper.find('.contact-markdown')

    expect(markdown.html()).toContain('正常段落')
    expect(markdown.html()).not.toMatch(/<script\b/i)
  })

  it('hides empty sections', () => {
    setConfig({ serviceCards: [], contactEntries: [], bodyMarkdown: '', subtitle: '' })
    const wrapper = mountView()

    expect(wrapper.find('.contact-title').exists()).toBe(true)
    expect(wrapper.find('.service-grid').exists()).toBe(false)
    expect(wrapper.find('.entry-list').exists()).toBe(false)
    expect(wrapper.find('.contact-markdown').exists()).toBe(false)
    expect(wrapper.find('.contact-subtitle').exists()).toBe(false)
    expect(wrapper.find('.contact-hero-note').exists()).toBe(false)
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

  it('numbers visible sections in order and renumbers when a section is hidden', () => {
    const wrapper = mountView()
    const kickers = wrapper.findAll('.section-kicker')
    expect(kickers.map((k) => k.text())).toEqual(['[01] 合作方向', '[02] 从这里开始', '[03] 补充说明'])

    setConfig({ serviceCards: [] })
    const shrunk = mountView()
    const shrunkKickers = shrunk.findAll('.section-kicker')
    expect(shrunkKickers.map((k) => k.text())).toEqual(['[01] 从这里开始', '[02] 补充说明'])
  })

  it('marks tree branches with ├── for rows and └── for the last row', () => {
    const wrapper = mountView()

    const serviceBranches = wrapper.findAll('.service-card .tree-branch').map((b) => b.text())
    expect(serviceBranches).toEqual(['├──', '└──'])

    const entryBranches = wrapper.findAll('.entry-item .tree-branch').map((b) => b.text())
    expect(entryBranches).toEqual(['├──', '├──', '└──'])
  })

  it('renders the WebGL hero layer with static fallback and inert legacy nodes', () => {
    const wrapper = mountView()

    const field = wrapper.find('.hero-field')
    expect(field.exists()).toBe(true)
    expect(field.attributes('aria-hidden')).toBe('true')
    // 三层合成：shader 视觉层（无 WebGL2 的 jsdom 下停在静态兜底）→ 遮罩 → 内容
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
