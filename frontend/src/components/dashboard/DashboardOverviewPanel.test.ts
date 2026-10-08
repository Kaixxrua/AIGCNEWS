import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import DashboardOverviewPanel from './DashboardOverviewPanel.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      dashboard: {
        editorial: { uiTotal: 'UI 库总量', total: '内容总量', github: 'GitHub 项目' },
        sourceRanking: '查看 {source} 排行榜',
        stats: {
          total: '全部', github: 'GitHub', papers: '论文', news: '新闻', products: '产品', hn: 'HN', x: 'X',
          todayVisitors: '今日访客', totalVisitors: '总访客', newDocuments: '今日新增', todayUiMaterials: '今日入库 UI',
        },
      },
    },
  },
})

const global = {
  plugins: [i18n],
  stubs: {
    RouterLink: { props: ['to'], template: '<a class="router-link" :data-to="JSON.stringify(to)"><slot /></a>' },
    RollingNumber: { props: ['value'], template: '<span class="rolling-number">{{ value }}</span>' },
  },
}
const mountPanel = (loading = false) => mount(DashboardOverviewPanel, {
  props: {
    loading: false,
    activeTab: 'github',
    statValues: [100, 20, 15, 10, 8, 6, 4],
    visitorValues: [30, 500, 12],
    uiCount: 157,
    uiLoading: loading,
  },
  global,
})

describe('DashboardOverviewPanel', () => {
  it('shows the six core statistics, including today\'s count and both visitor metrics', () => {
    const wrapper = mountPanel()
    const card = wrapper.get('.stat-cell--ui')

    expect(card.text()).toContain('UI 库总量')
    expect(card.text()).toContain('157')
    expect(wrapper.findAll('.stat-cell').map(cell => cell.find('.stat-cell-label').text())).toEqual(['内容总量', 'GitHub 项目', '今日新增', '今日访客', '总访客', 'UI 库总量'])
    expect(wrapper.get('.stat-cell--new').text()).toContain('12')
    expect(wrapper.get('.stat-cell--visitors').text()).toContain('30')
    expect(wrapper.get('.stat-cell--total-visitors').text()).toContain('500')
    expect(card.attributes('data-to')).toContain('ui-library')
    expect(wrapper.find('.daily-ui').exists()).toBe(false)
  })

  it('keeps all six cells in place with placeholders while the dashboard loads', async () => {
    const wrapper = mount(DashboardOverviewPanel, {
      props: { loading: true, activeTab: 'github', statValues: [0, 0], visitorValues: [0, 0, 0], uiCount: null, uiLoading: true },
      global,
    })
    expect(wrapper.findAll('.stat-cell')).toHaveLength(6)
    expect(wrapper.findAll('.stat-cell-num--loading')).toHaveLength(6)
    expect(wrapper.find('.rolling-number').exists()).toBe(false)
    await wrapper.setProps({ loading: false, statValues: [100, 20], visitorValues: [30, 500, 12], uiCount: 157, uiLoading: false })
    expect(wrapper.find('.stat-cell-num--loading').exists()).toBe(false)
    expect(wrapper.get('.stat-cell--total').text()).toContain('100')
  })

  it('uses a compact loading placeholder while the catalog loads', () => {
    const wrapper = mountPanel(true)
    expect(wrapper.find('.stat-cell-num--loading').exists()).toBe(true)
  })

  it('distinguishes an unavailable catalog from an empty catalog and preserves source navigation', async () => {
    const wrapper = mountPanel()
    await wrapper.setProps({ uiCount: null })
    expect(wrapper.get('.stat-cell--ui').text()).toContain('—')
    await wrapper.setProps({ uiCount: 0 })
    expect(wrapper.get('.stat-cell--ui').text()).toContain('0')
    await wrapper.get('button.stat-cell--github').trigger('click')
    expect(wrapper.emitted('selectSource')).toEqual([['github']])
  })
})
