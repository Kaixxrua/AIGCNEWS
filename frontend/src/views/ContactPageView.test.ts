import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ContactPageView from './ContactPageView.vue'
import type { SiteContactPage } from '@/services/site/contactPageApi'

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

const mountView = () => mount(ContactPageView)

describe('ContactPageView', () => {
  beforeEach(() => {
    setConfig()
  })

  it('renders hero, service cards, contact entries and markdown body when enabled', () => {
    const wrapper = mountView()

    expect(wrapper.find('.contact-title').text()).toBe('联系合作')
    expect(wrapper.find('.contact-subtitle').text()).toBe('外包 · 商务合作')

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
    expect(webLink.text()).toBe('https://example.com')

    // 无 href 的条目渲染纯文本值
    expect(entries[0]!.find('a').exists()).toBe(false)
    expect(entries[0]!.find('.entry-value').text()).toBe('123456')
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
  })

  it('renders nothing when the page is disabled (defensive root guard)', () => {
    setConfig({ enabled: false })
    const wrapper = mountView()

    expect(wrapper.find('.contact-page').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })
})
