import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MembershipGrantPanel from './MembershipGrantPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import { createMembershipGrantForm, type MembershipGrantResult } from '@/features/monitor/monitorModel'

const mountPanel = (props: { granting?: boolean; lastResult?: MembershipGrantResult | null } = {}) => {
  const form = createMembershipGrantForm()
  const wrapper = mount(MembershipGrantPanel, {
    global: { plugins: [i18n] },
    props: { form, granting: false, lastResult: null, ...props },
  })
  return { wrapper, form }
}

describe('MembershipGrantPanel', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('renders email, tier and expiry inputs with localized labels', () => {
    const { wrapper } = mountPanel()
    expect(wrapper.find('h3').text()).toBe('用户组设置')
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    const options = wrapper.findAll('select option')
    expect(options.map(option => option.text())).toEqual(['vip · 会员', 'free · 免费用户（吊销会员）'])
    const expiry = wrapper.find('input[type="date"]')
    expect(expiry.exists()).toBe(true)
    expect(expiry.attributes('disabled')).toBeUndefined()
  })

  it('writes email, tier and expiry back into the form draft', async () => {
    const { wrapper, form } = mountPanel()
    await wrapper.find('input[type="email"]').setValue('  Member@Example.com ')
    await wrapper.find('select').setValue('free')
    expect(form.email).toBe('Member@Example.com')
    expect(form.tier).toBe('free')
    // free（吊销）档到期日期禁用，由后端强制清空
    expect(wrapper.find('input[type="date"]').attributes('disabled')).toBeDefined()

    await wrapper.find('select').setValue('member')
    await wrapper.find('input[type="date"]').setValue('2027-01-01')
    expect(form.expires_on).toBe('2027-01-01')
  })

  it('emits save on submit and locks inputs while granting', async () => {
    const onSave = vi.fn()
    const form = createMembershipGrantForm()
    const wrapper = mount(MembershipGrantPanel, {
      global: { plugins: [i18n] },
      props: { form, granting: false, lastResult: null, onSave },
    })
    await wrapper.find('button.monitor-btn-primary').trigger('click')
    expect(onSave).toHaveBeenCalledTimes(1)

    const { wrapper: locking } = mountPanel({ granting: true })
    expect(locking.find('input[type="email"]').attributes('disabled')).toBeDefined()
    expect(locking.find('button.monitor-btn-primary').attributes('disabled')).toBeDefined()
    expect(locking.find('button.monitor-btn-primary').text()).toBe('保存中…')
  })

  it('shows the last operation result with vip label and expiry badge', () => {
    const { wrapper } = mountPanel({
      lastResult: {
        user_id: 7,
        email: 'member@example.com',
        membership_tier: 'member',
        membership_expires_at: '2027-01-01T15:59:59+00:00',
        revoked: false,
      },
    })
    const text = wrapper.text()
    expect(text).toContain('最近操作：')
    expect(text).toContain('member@example.com')
    // 与 MastheadUser 口径一致：member 对外展示为 vip
    expect(text).toContain('用户组：vip')
    expect(text).toContain('到期')
  })

  it('omits the expiry badge for permanent grants', () => {
    const { wrapper } = mountPanel({
      lastResult: {
        user_id: 7,
        email: 'member@example.com',
        membership_tier: 'member',
        membership_expires_at: null,
        revoked: false,
      },
    })
    const badges = wrapper.findAll('.monitor-status-success .badge')
    expect(badges.map(badge => badge.text())).toEqual(['member@example.com', '用户组：vip'])
  })
})
