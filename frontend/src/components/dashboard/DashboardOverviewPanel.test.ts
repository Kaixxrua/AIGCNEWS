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
    uiCount: 157,
    uiLoading: loading,
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
  it('shows total UI templates and both visitor metrics as six core statistics', () => {
    const wrapper = mountPanel()
    const card = wrapper.get('.stat-cell--ui')

    expect(card.text()).toContain('UI 库总量')
    expect(card.text()).toContain('157')
    expect(wrapper.findAll('.stat-cell')).toHaveLength(6)
    expect(wrapper.get('.stat-cell--total-visitors').text()).toContain('500')
    expect(wrapper.get('.stat-cell--visitors').text()).toContain('30')
    expect(card.attributes('data-to')).toContain('ui-library')
    expect(wrapper.find('.daily-ui').exists()).toBe(false)
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
