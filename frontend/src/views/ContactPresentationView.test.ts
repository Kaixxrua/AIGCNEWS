import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { messages, DEFAULT_LOCALE } from '@/i18n'
import type { SiteContactPage } from '@/services/site/contactPageApi'
import ContactPresentationView from './ContactPresentationView.vue'

const configBox = vi.hoisted(() => ({ current: null as null | { value: SiteContactPage } }))
vi.mock('@/composables/useContactPageConfig', async () => {
  const { ref } = await import('vue')
  configBox.current = ref({} as SiteContactPage)
  return { useContactPageConfig: () => ({ contactPageConfig: configBox.current }) }
})
vi.mock('./ContactPageView.vue', () => ({ __esModule: true, default: { template: '<div class="original-contact-scene" />' } }))

const i18n = createI18n({ legacy: false, locale: DEFAULT_LOCALE, fallbackLocale: DEFAULT_LOCALE, messages })
const mountView = () => mount(ContactPresentationView, { global: { plugins: [i18n] } })

beforeEach(() => {
  i18n.global.locale.value = DEFAULT_LOCALE
  configBox.current!.value = {
    enabled: true, navLabel: '合作', title: '联系与合作', subtitle: '一起聊聊 AI',
    serviceCards: [], bodyMarkdown: '', updatedAt: null,
    contactEntries: [
      { label: '交流群', value: '加入群聊', href: 'https://qm.qq.com/q/example', qrImageUrl: '/qr.png' },
      { label: '邮箱', value: 'hi@example.com', href: 'mailto:hi@example.com', qrImageUrl: '' },
    ],
  }
})

describe('contact concept video', () => {
  it('opens the requested video muted with autoplay and accessible native player controls', () => {
    const wrapper = mountView()
    const player = wrapper.get('iframe')
    const url = new URL(player.attributes('src')!)
    expect(url.origin).toBe('https://player.bilibili.com')
    expect(url.searchParams.get('bvid')).toBe('BV12Dpj6QEoi')
    expect(url.searchParams.get('autoplay')).toBe('1')
    expect(url.searchParams.get('muted')).toBe('1')
    expect(player.attributes('allow')).toContain('autoplay')
    expect(player.attributes('title')).toBe('概念视频')
    expect(player.attributes('allowfullscreen')).toBeDefined()
    expect(wrapper.find('.original-contact-scene').exists()).toBe(false)
    expect(wrapper.get('.video-caption a').attributes('href')).toBe('https://www.bilibili.com/video/BV12Dpj6QEoi/')
  })

  it('unmounts the video when switching to the original scene and restores it when switching back', async () => {
    const wrapper = mountView()
    const buttons = wrapper.findAll('.presentation-modes button')
    await buttons[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('.original-contact-scene').exists()).toBe(true)
    expect(buttons[1]!.attributes('aria-pressed')).toBe('true')
    await buttons[0]!.trigger('click')
    expect(wrapper.find('.original-contact-scene').exists()).toBe(false)
    expect(wrapper.find('iframe').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps configured contact links beside the player and recovers from broken QR images', async () => {
    const wrapper = mountView()
    const contacts = wrapper.get('.presentation-contacts')
    const links = contacts.findAll('a')
    expect(links[0]!.attributes('rel')).toBe('noopener noreferrer')
    expect(links[1]!.attributes('href')).toBe('mailto:hi@example.com')
    expect(links[1]!.attributes('target')).toBeUndefined()
    expect(wrapper.get('.concept-video').find('.presentation-contacts').exists()).toBe(false)
    await contacts.get('img').trigger('error')
    expect(contacts.find('img').exists()).toBe(false)
    expect(contacts.get('[role="img"]').text()).toBe(i18n.global.t('contact.qrUnavailable'))
    expect(contacts.find('.qr-hint').exists()).toBe(false)
  })

  it('does not load the third-party player or contacts when the page is disabled', () => {
    configBox.current!.value.enabled = false
    const wrapper = mountView()
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('localizes video controls and known admin text while preserving custom content', async () => {
    const wrapper = mountView()
    i18n.global.locale.value = 'en-US'
    await wrapper.vm.$nextTick()
    expect(wrapper.get('iframe').attributes('title')).toBe('Concept video')
    expect(wrapper.get('h1').text()).toBe('Contact & Collaboration')
    expect(wrapper.get('.presentation-heading > p').text()).toBe('一起聊聊 AI')
    expect(wrapper.get('.video-caption a').text()).toBe('Watch on Bilibili ↗')
  })
})
