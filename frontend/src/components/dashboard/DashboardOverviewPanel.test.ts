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
        sourceRanking: '查看 {source} 排行榜',
        stats: {
          total: '全部', github: 'GitHub', papers: '论文', news: '新闻', products: '产品', hn: 'HN', x: 'X',
          todayVisitors: '今日访客', totalVisitors: '总访客', newDocuments: '本日新增', todayUiMaterials: '今日入库 UI',
        },
      },
    },
  },
})

const mountPanel = (loading = false) => mount(DashboardOverviewPanel, {
  props: {
    loading: false,
    activeTab: 'github',
    statValues: [100, 20, 15, 10, 8, 6, 4],
    visitorValues: [30, 500, 12],
    todayUiCount: 7,
    todayUiCountLoading: loading,
  },
  global: {
    plugins: [i18n],
    stubs: {
      RouterLink: { props: ['to'], template: '<a class="router-link" :data-to="JSON.stringify(to)"><slot /></a>' },
      RollingNumber: { props: ['value'], template: '<span class="rolling-number">{{ value }}</span>' },
    },
  },
})

describe('DashboardOverviewPanel', () => {
  it('shows today UI imports as a compact linked statistic', () => {
    const wrapper = mountPanel()
    const card = wrapper.get('.stat-cell--ui')

    expect(card.text()).toContain('今日入库 UI')
    expect(card.text()).toContain('7')
    expect(card.attributes('data-to')).toContain('ui-library')
    expect(wrapper.find('.daily-ui').exists()).toBe(false)
  })

  it('uses a compact loading placeholder while the catalog loads', () => {
    const wrapper = mountPanel(true)
    expect(wrapper.find('.stat-cell-num--loading').exists()).toBe(true)
  })
})
