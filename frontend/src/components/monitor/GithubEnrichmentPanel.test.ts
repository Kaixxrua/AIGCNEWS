import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import i18n from '@/i18n'
import type { GithubEnrichmentStatus } from '@/features/monitor/monitorModel'
import GithubEnrichmentPanel from './GithubEnrichmentPanel.vue'

const status: GithubEnrichmentStatus = {
  eligible: 10,
  succeeded: 5,
  failed: 1,
  pending: 4,
}

const mountPanel = (enrichmentStatus: GithubEnrichmentStatus) => mount(GithubEnrichmentPanel, {
  global: { plugins: [i18n] },
  props: {
    status: enrichmentStatus,
    loading: false,
    retrying: false,
    backfilling: false,
    cancelling: false,
    cancelWatching: false,
    polling: false,
    concurrency: 3,
    reasoningEffort: '',
    effectiveReasoningEffort: 'medium',
    savingReasoningEffort: false,
  },
})

// 从 style 属性提取 width 百分比；缺失即测试失败
const widthPctOf = (style: string | undefined): number => {
  const match = /width:\s*([\d.]+)%/.exec(style ?? '')
  if (!match || match[1] === undefined) throw new Error(`width style missing: ${style ?? '<none>'}`)
  return parseFloat(match[1])
}

describe('GithubEnrichmentPanel', () => {
  it('renders retained buckets as separate chips, not merged into progress totals', () => {
    // 在库但退出队列的项目单独成组：已富化 x/y 文案计数不并入，
    // 桶按溯源优先级排序，零计数桶不渲染
    const wrapper = mountPanel({
      eligible: 18_580,
      succeeded: 18_580,
      failed: 0,
      pending: 0,
      retained_total: 76,
      retained_buckets: {
        tombstone: 1,
        not_found: 13,
        snapshot_below_threshold: 51,
        lost_input: 11,
      },
    })

    const text = wrapper.text()
    expect(text).toContain('已富化 18580/18580')
    expect(text).toContain('另保留在库 76 个（不再处理）')
    const chips = wrapper.findAll('.enrichment-retained-chip')
    expect(chips).toHaveLength(4)
    expect(chips.map((chip) => chip.text())).toEqual([
      '已下架 13',
      '星数回落 51',
      '简介被删 11',
      '改名旧名 1',
    ])
  })

  it('omits zero-count retained buckets and hides the line when nothing is retained', () => {
    const wrapper = mountPanel({
      ...status,
      retained_total: 13,
      retained_buckets: { not_found: 13, snapshot_below_threshold: 0 },
    })
    expect(wrapper.findAll('.enrichment-retained-chip')).toHaveLength(1)
    expect(wrapper.text()).toContain('已下架 13')
    expect(wrapper.text()).not.toContain('星数回落')

    expect(mountPanel(status).text()).not.toContain('另保留在库')
  })

  it('renders the retained difference as a gray segment pinned to the progress bar end', () => {
    // 进度条分母 = eligible + retained：绿色成功段按 18612/18688 缩窄，
    // 灰色保留段钉在条尾，tooltip 标注数量；完成率标签仍按队列口径 100%。
    const wrapper = mountPanel({
      eligible: 18_612,
      succeeded: 18_612,
      failed: 0,
      pending: 0,
      retained_total: 76,
      retained_buckets: { not_found: 14, snapshot_below_threshold: 51, lost_input: 10, tombstone: 1 },
    })

    const segment = wrapper.find('.enrichment-progress-retained')
    expect(segment.exists()).toBe(true)
    expect(widthPctOf(segment.attributes('style'))).toBeCloseTo((76 / 18_688) * 100, 5)
    expect(segment.attributes('title')).toContain('76')

    const succeededWidth = widthPctOf(wrapper.find('.enrichment-progress-succeeded').attributes('style'))
    expect(succeededWidth).toBeCloseTo((18_612 / 18_688) * 100, 5)
    // 完成率标签保持队列口径（eligible 内百分比），不被灰色段拉低
    expect(wrapper.text()).toContain('100%')
  })

  it('omits the gray segment when nothing is retained', () => {
    const wrapper = mountPanel(status)
    expect(wrapper.find('.enrichment-progress-retained').exists()).toBe(false)
  })

  it('still renders the progress bar when the queue is empty but retained projects exist', () => {
    const wrapper = mountPanel({
      eligible: 0,
      succeeded: 0,
      failed: 0,
      pending: 0,
      retained_total: 5,
      retained_buckets: { not_found: 5 },
    })
    expect(wrapper.find('.enrichment-progress').exists()).toBe(true)
    const segment = wrapper.find('.enrichment-progress-retained')
    expect(segment.exists()).toBe(true)
    expect(widthPctOf(segment.attributes('style'))).toBeCloseTo(100, 5)
  })
})
