import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { i18n, setAppLocale } from '@/i18n'
import MembershipUserListPanel from './MembershipUserListPanel.vue'

const user = {
  user_id: 7,
  email: 'member@example.com',
  phone: '13800000000',
  username: 'member',
  role: 'user',
  disabled: false,
  membership_tier: 'member' as const,
  membership_expires_at: null,
  created_at: '2026-08-01T00:00:00Z',
  effective_tier: 'member' as const,
}

beforeEach(() => setAppLocale('zh-CN'))

describe('MembershipUserListPanel', () => {
  it('renders users and emits search and edit actions', async () => {
    const wrapper = mount(MembershipUserListPanel, {
      global: { plugins: [i18n] },
      props: { items: [user], total: 1, page: 1, totalPages: 1, loading: false, query: '', error: '' },
    })
    expect(wrapper.classes()).toContain('shrink-0')
    expect(wrapper.text()).toContain('member@example.com')
    expect(wrapper.text()).toContain('13800000000')
    await wrapper.find('input[type="search"]').setValue('member')
    const queryEvents = wrapper.emitted('update:query') ?? []
    expect(queryEvents[queryEvents.length - 1]).toEqual(['member'])
    await wrapper.find('button.monitor-btn-secondary').trigger('click')
    expect(wrapper.emitted('edit')?.[0]).toEqual([user])
  })

  it('emits pagination changes', async () => {
    const wrapper = mount(MembershipUserListPanel, {
      global: { plugins: [i18n] },
      props: { items: [user], total: 40, page: 1, totalPages: 2, loading: false, query: '', error: '' },
    })
    const buttons = wrapper.findAll('button.monitor-pagination-btn')
    await buttons[buttons.length - 1]!.trigger('click')
    const pageEvents = wrapper.emitted('go-page') ?? []
    expect(pageEvents[pageEvents.length - 1]).toEqual([2])
  })
})
