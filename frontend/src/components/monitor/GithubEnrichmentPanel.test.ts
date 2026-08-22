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

describe('GithubEnrichmentPanel', () => {
  it('renders retained buckets as separate chips, not merged into progress totals', () => {
    // 在库但退出队列的项目单独成组：进度分母不变，桶按溯源优先级排序，零计数桶不渲染
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
})
