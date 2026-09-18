import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import PersonalTrackingSection from '@/components/tracking/PersonalTrackingSection.vue'
import { useSubscriptionsController } from '@/composables/useSubscriptionsController'
import { trackingZh } from '@/i18n/locales/tracking'
import SubscriptionsView from './SubscriptionsView.vue'

vi.mock('@/composables/useSubscriptionsController')

const channels = ref([
  {
    id: 1,
    channel_type: 'email' as const,
    target: 'me@example.com',
    verified: true,
    status: 'active' as const,
    created_at: '2026-08-01T00:00:00Z',
  },
])
const loading = ref(false)
const error = ref('')
const loadAll = vi.fn()
const mountView = async () => {
  const wrapper = mount(SubscriptionsView, {
    global: {
      plugins: [
        createI18n({
          legacy: false,
          locale: 'zh-CN',
          messages: {
            'zh-CN': {
              tracking: trackingZh,
              subscriptions: {
                title: '我的订阅',
                refresh: '刷新',
                channels: { title: '推送渠道' },
                errors: { 'load-failed': '加载失败，请稍后重试' },
              },
            },
          },
        }),
      ],
      stubs: { PersonalTrackingSection: true },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  error.value = ''
  loading.value = false
  vi.mocked(useSubscriptionsController).mockReturnValue({
    channels,
    loading,
    error,
    loadAll,
  } as unknown as ReturnType<typeof useSubscriptionsController>)
})

describe('SubscriptionsView', () => {
  it('preserves existing delivery channels for personal tracking', async () => {
    const wrapper = await mountView()
    expect(loadAll).toHaveBeenCalledOnce()
    expect(wrapper.getComponent(PersonalTrackingSection).props('channels')).toEqual(channels.value)
  })

  it('presents personal intelligence without a dead-end push-channel card', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('个人情报中心')
    expect(wrapper.text()).toContain('把分散的 AI 动态变成你的专属情报流')
    expect(wrapper.find('section[aria-labelledby="push-channels-title"]').exists()).toBe(false)
    for (const label of ['RSS 简报订阅', '创建订阅', '重置 RSS 链接', '发送验证码']) {
      expect(wrapper.text()).not.toContain(label)
    }
  })

  it('allows retrying channel loading and prevents duplicate refreshes', async () => {
    error.value = 'load-failed'
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('加载失败，请稍后重试')
    await wrapper.get('button').trigger('click')
    expect(loadAll).toHaveBeenCalledTimes(2)
    loading.value = true
    await flushPromises()
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })
})
