import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DashboardEmptyState from './DashboardEmptyState.vue'
import { i18n } from '@/i18n'

const mountState = (props: Record<string, unknown>) => mount(DashboardEmptyState, {
  props: { variant: 'error', ...props },
  global: { plugins: [i18n] },
})

describe('DashboardEmptyState failure', () => {
  it('tells an offline visitor to check the connection and offers a retry', async () => {
    const wrapper = mountState({ error: 'network' })
    const alert = wrapper.get('[role="alert"]')

    expect(alert.text()).toContain('连不上服务器，榜单没加载出来')
    expect(alert.text()).toContain('检查一下网络，再点重试。')
    expect(alert.text()).not.toContain('该日期暂无数据')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('blames the server rather than the visitor for other failures', () => {
    const wrapper = mountState({ error: 'server' })

    expect(wrapper.text()).toContain('榜单暂时没加载出来')
    expect(wrapper.text()).toContain('服务器那边出了点问题，稍后点重试。')
  })

  it('keeps the retry button busy while the request is on its way', () => {
    const button = mountState({ error: 'server', retrying: true }).get('button')

    expect(button.attributes('disabled')).toBeDefined()
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.text()).toBe('加载中…')
  })

  it('still says “no data” only for a day without rankings', () => {
    const wrapper = mountState({ variant: 'no-data' })

    expect(wrapper.text()).toContain('该日期暂无数据。')
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
