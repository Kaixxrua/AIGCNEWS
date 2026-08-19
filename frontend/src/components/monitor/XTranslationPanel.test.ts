import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import XTranslationPanel from './XTranslationPanel.vue'

const status = {
  pending: 2, running: 1, succeeded: 3, failed: 1, skipped: 1,
  retryable: 3, stale_running: 0, batch_running: 1,
  latest_failure_error: '503 unavailable',
  latest_failure_model_provider: 'openai',
  latest_failure_model_name: 'model',
}

describe('XTranslationPanel', () => {
  it('renders queue counts, failure details, and emits actions', async () => {
    const wrapper = mount(XTranslationPanel, {
      props: { status, loading: false, retrying: false },
      global: { mocks: { $t: (key: string) => key } },
    })

    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('503 unavailable')
    expect(wrapper.text()).toContain('openai / model')

    await wrapper.findAll('button')[0]!.trigger('click')
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('disables retry when no work is available or while running', () => {
    const wrapper = mount(XTranslationPanel, {
      props: { status: { ...status, retryable: 0 }, loading: false, retrying: false },
      global: { mocks: { $t: (key: string) => key } },
    })
    expect(wrapper.findAll('button')[1]!.attributes('disabled')).toBeDefined()

    const running = mount(XTranslationPanel, {
      props: { status, loading: false, retrying: true },
      global: { mocks: { $t: (key: string) => key } },
    })
    expect(running.findAll('button')[1]!.attributes('disabled')).toBeDefined()
  })
})
