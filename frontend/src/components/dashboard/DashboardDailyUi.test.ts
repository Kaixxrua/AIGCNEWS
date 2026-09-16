import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardDailyUi from './DashboardDailyUi.vue'

const now = new Date('2026-09-16T12:00:00Z')
const template = (id: string, addedAt: string, previewKind: 'html' | undefined = 'html') => ({
  id,
  added_at: addedAt,
  preview_kind: previewKind,
  preview_width: 640,
  name: { zh: `组件 ${id}`, en: `Component ${id}` },
  provider: 'Acme UI',
  preview_url: `/ui-library/previews/${id}.html`,
  clip_url: `/ui-library/clips/${id}.webm`,
  poster_url: `/ui-library/posters/${id}.webp`,
})

const messages = {
  dashboard: {
    dailyUi: {
      title: '今日新入库 UI', subtitle: '直接预览', viewAll: '查看全部', loading: '加载中',
      loadFailed: '加载失败', empty: '暂无新增', open: '查看 UI 组件：{name}',
    },
  },
}

const mountShowcase = () => mount(DashboardDailyUi, {
  global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })],
    stubs: {
      RouterLink: {
        props: ['to'],
        template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
      },
      UiCardFrame: { props: ['src', 'id'], template: '<span class="frame-stub" :data-id="id" :data-src="src" />' },
      UiCardVideo: { props: ['src'], template: '<span class="video-stub" :data-src="src" />' },
    },
  },
})

describe('DashboardDailyUi', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(now)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('renders live previews for only the newest 24-hour catalog entries', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        version: 1,
        items: [
          template('new-html', '2026-09-16T11:00:00Z'),
          template('old', '2026-09-14T11:00:00Z'),
          { ...template('new-video', '2026-09-16T10:00:00Z'), preview_kind: undefined },
        ],
      }),
    }))

    const wrapper = mountShowcase()
    await flushPromises()

    expect(wrapper.findAll('.daily-ui__item')).toHaveLength(2)
    expect(wrapper.get('.frame-stub').attributes('data-id')).toBe('new-html')
    expect(wrapper.get('.video-stub').attributes('data-src')).toContain('new-video.webm')
    expect(wrapper.text()).not.toContain('组件 old')
    expect(wrapper.get('.daily-ui__item').attributes('data-to')).toContain('new-html')
  })

  it('keeps the library entry point visible when today has no additions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: 1, items: [] }) }))

    const wrapper = mountShowcase()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无新增')
    expect(wrapper.get('.daily-ui__all').attributes('data-to')).toContain('"rank":"new"')
  })
})
