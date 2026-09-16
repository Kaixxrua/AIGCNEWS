import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorSectionNav from './MonitorSectionNav.vue'
import i18n, { setAppLocale } from '@/i18n'
import { MONITOR_NAV, type MonitorSectionKey } from '@/features/monitor/monitorViewModel'

const mountNav = (props: { active?: MonitorSectionKey; alertKeys?: MonitorSectionKey[]; sections?: typeof MONITOR_NAV; onSelect?: (key: MonitorSectionKey) => void } = {}) =>
  mount(MonitorSectionNav, {
    global: { plugins: [i18n] },
    props: { sections: MONITOR_NAV, active: 'tasks', alertKeys: [], ...props },
  })

describe('MonitorSectionNav', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('renders 5 categories and all leaves in MONITOR_NAV order with localized labels', () => {
    const wrapper = mountNav()
    expect(wrapper.find('nav.monitor-nav').attributes('aria-label')).toBe('监控分区')
    const headers = wrapper.findAll('.monitor-nav-group-header')
    expect(headers.map(header => header.find('.monitor-nav-group-label').text())).toEqual([
      '监控', '采集', '账号源', '配置', '站点',
    ])
    expect(headers.every(header => header.find('.monitor-nav-icon').exists())).toBe(true)
    const leaves = wrapper.findAll('button.monitor-nav-leaf')
    expect(leaves.map(leaf => leaf.find('.monitor-nav-label').text())).toEqual([
      '任务历史', 'MCP 调用', '错误日志', '访问统计',
      '采集控制', 'GitHub 爬取', 'GitHub 富化', 'UI 素材来源',
      'X 关注账号', 'X 凭证', '微信公众号',
      '模型服务', '定时任务', 'SMTP 邮件', 'MCP 服务', 'OAuth 登录', 'Telegram 推送',
      '联系合作页', '用户组', '用户统计', '收入统计', '支付配置', '支付订单',
    ])
  })

  it('marks only the active leaf with the active class and aria-current', () => {
    const wrapper = mountNav({ active: 'crawl' })
    const leaves = wrapper.findAll('button.monitor-nav-leaf')
    expect(leaves.filter(leaf => leaf.classes().includes('active'))).toHaveLength(1)
    expect(leaves[5]!.classes()).toContain('active')
    expect(leaves[5]!.attributes('aria-current')).toBe('true')
    expect(leaves[4]!.attributes('aria-current')).toBeUndefined()
  })

  it('renders the alert dot on the flagged leaf while its category is expanded', () => {
    const wrapper = mountNav({ alertKeys: ['enrichment'] })
    const dots = wrapper.findAll('.monitor-nav-alert')
    expect(dots).toHaveLength(1)
    const leaves = wrapper.findAll('button.monitor-nav-leaf')
    expect(leaves[6]!.find('.monitor-nav-alert').exists()).toBe(true)
    expect(dots[0]!.attributes('title')).toBe('GitHub 项目库存在富化失败，请到监控页处理')
  })

  it('emits select on leaf click without moving the active state itself', async () => {
    const onSelect = vi.fn()
    const wrapper = mountNav({ active: 'tasks', onSelect })
    const leaves = wrapper.findAll('button.monitor-nav-leaf')
    await leaves[14]!.trigger('click')
    // 监听 prop 断言替代 emitted()：本环境 VTU 的 emitted 追踪不记录模板内 emit
    expect(onSelect).toHaveBeenCalledWith('mcp-server')
    // 哑组件契约：激活态由父级持有，点击后不自动迁移
    expect(leaves[0]!.classes()).toContain('active')
    expect(leaves[14]!.classes()).not.toContain('active')
  })

  it('collapses a category on header click and hands the alert dot to the header', async () => {
    const wrapper = mountNav({ alertKeys: ['enrichment'] })
    const ingestionHeader = wrapper.findAll('.monitor-nav-group-header')[1]!
    const leavesContainer = wrapper.findAll('.monitor-nav-leaves')[1]!
    expect(ingestionHeader.attributes('aria-expanded')).toBe('true')
    expect(leavesContainer.attributes('style') ?? '').not.toContain('display: none')

    await ingestionHeader.trigger('click')
    expect(ingestionHeader.attributes('aria-expanded')).toBe('false')
    expect(ingestionHeader.find('.monitor-nav-chevron').classes()).toContain('collapsed')
    expect(leavesContainer.attributes('style')).toContain('display: none')
    // 折叠后红点移到大类头，避免告警被藏进折叠区
    expect(ingestionHeader.find('.monitor-nav-alert-inline').exists()).toBe(true)

    await ingestionHeader.trigger('click')
    expect(ingestionHeader.attributes('aria-expanded')).toBe('true')
    expect(leavesContainer.attributes('style') ?? '').not.toContain('display: none')
    expect(ingestionHeader.find('.monitor-nav-alert-inline').exists()).toBe(false)
  })

  it('renders only the leaves passed in by the parent admin filter', () => {
    const wrapper = mountNav({
      sections: MONITOR_NAV
        .map(category => ({ ...category, children: category.children.filter(leaf => !leaf.adminOnly) }))
        .filter(category => category.children.length > 0),
    })
    expect(wrapper.findAll('.monitor-nav-group-header')).toHaveLength(1)
    const leaves = wrapper.findAll('button.monitor-nav-leaf')
    expect(leaves.map(leaf => leaf.find('.monitor-nav-label').text())).toEqual(['任务历史', 'MCP 调用'])
  })
})
