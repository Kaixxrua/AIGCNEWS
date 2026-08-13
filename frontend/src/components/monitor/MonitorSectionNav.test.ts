import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import MonitorSectionNav from './MonitorSectionNav.vue'
import i18n, { setAppLocale } from '@/i18n'
import { MONITOR_SECTIONS, type MonitorSectionKey } from '@/features/monitor/monitorViewModel'

const mountNav = (props: { active?: MonitorSectionKey; alertKeys?: MonitorSectionKey[]; sections?: typeof MONITOR_SECTIONS } = {}) =>
  mount(MonitorSectionNav, {
    global: { plugins: [i18n] },
    props: { sections: MONITOR_SECTIONS, active: 'status', alertKeys: [], ...props },
  })

describe('MonitorSectionNav', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('renders sections in MONITOR_SECTIONS order with localized labels', () => {
    const wrapper = mountNav()
    const buttons = wrapper.findAll('button.monitor-nav-item')
    expect(buttons).toHaveLength(4)
    expect(buttons.map(button => button.find('.monitor-nav-label').text())).toEqual([
      '运行状态', '采集与源', 'GitHub 项目库', '系统配置',
    ])
    expect(wrapper.find('nav.monitor-nav').attributes('aria-label')).toBe('监控分区')
    expect(buttons.every(button => button.find('.monitor-nav-icon').exists())).toBe(true)
  })

  it('marks only the active section with the active class and aria-current', () => {
    const wrapper = mountNav({ active: 'ingestion' })
    const buttons = wrapper.findAll('button.monitor-nav-item')
    expect(buttons.map(button => button.classes())).toEqual([
      expect.not.arrayContaining(['active']),
      expect.arrayContaining(['active']),
      expect.not.arrayContaining(['active']),
      expect.not.arrayContaining(['active']),
    ])
    expect(buttons[1]!.attributes('aria-current')).toBe('true')
    expect(buttons[0]!.attributes('aria-current')).toBeUndefined()
  })

  it('renders a single alert dot inside the flagged section button', () => {
    const wrapper = mountNav({ alertKeys: ['github'] })
    const dots = wrapper.findAll('.monitor-nav-alert')
    expect(dots).toHaveLength(1)
    const buttons = wrapper.findAll('button.monitor-nav-item')
    expect(buttons[2]!.find('.monitor-nav-alert').exists()).toBe(true)
    expect(dots[0]!.attributes('title')).toBe('GitHub 项目库存在富化失败，请到监控页处理')
  })

  it('emits select on click without moving the active state itself', async () => {
    const wrapper = mountNav({ active: 'status' })
    const buttons = wrapper.findAll('button.monitor-nav-item')
    await buttons[3]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([['settings']])
    // 哑组件契约：激活态由父级持有，点击后不自动迁移
    expect(buttons[0]!.classes()).toContain('active')
    expect(buttons[3]!.classes()).not.toContain('active')
  })

  it('renders only the sections passed in by the parent filter', () => {
    const wrapper = mountNav({ sections: MONITOR_SECTIONS.filter(section => !section.adminOnly) })
    const buttons = wrapper.findAll('button.monitor-nav-item')
    expect(buttons).toHaveLength(1)
    expect(buttons[0]!.find('.monitor-nav-label').text()).toBe('运行状态')
  })
})
