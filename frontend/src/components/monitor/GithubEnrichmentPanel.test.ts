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
  it('locks retry and backfill when the server reports a running batch after refresh', async () => {
    const wrapper = mountPanel({ ...status, running: true })
    const retry = wrapper.find('button.monitor-btn-secondary.relative')
    const backfill = wrapper.find('button.monitor-btn-primary')

    expect(retry.attributes('disabled')).toBeDefined()
    expect(backfill.attributes('disabled')).toBeDefined()
    expect(wrapper.find('button.enrichment-cancel-btn').exists()).toBe(true)

    await wrapper.setProps({ status: { ...status, running: false } })

    expect(retry.attributes('disabled')).toBeUndefined()
    expect(backfill.attributes('disabled')).toBeUndefined()
  })

  it('renders public-library catalog totals for display while keeping actionable queue for buttons', () => {
    // 展示口径 = 公共项目库宇宙；按钮禁用仍看可执行队列（actionable failed/pending）
    const wrapper = mountPanel({
      eligible: 17_800,
      succeeded: 17_799,
      failed: 1,
      pending: 0,
      catalog_total: 18_632,
      catalog_succeeded: 18_631,
      catalog_failed: 1,
      catalog_pending: 0,
    })

    const text = wrapper.text()
    expect(text).toContain('已富化 18631/18632')
    expect(text).toContain('待处理 0')
    expect(text).toContain('失败 1')
    expect(wrapper.find('.enrichment-alert-dot').exists()).toBe(true)

    const progressbar = wrapper.find('[role="progressbar"]')
    expect(progressbar.exists()).toBe(true)
    // 18,631 / 18,632 ≈ 99.99% → 显示 100%
    expect(progressbar.attributes('aria-valuenow')).toBe('100')

    // 可执行队列：failed=1 → retry 可用；pending=0 → backfill 禁用
    const retry = wrapper.find('button.monitor-btn-secondary.relative')
    const backfill = wrapper.find('button.monitor-btn-primary')
    expect(retry.attributes('disabled')).toBeUndefined()
    expect(backfill.attributes('disabled')).toBeDefined()
  })

  it('excludes unprocessable projects from the active progress denominator', () => {
    const wrapper = mountPanel({
      eligible: 19_087,
      succeeded: 19_087,
      failed: 0,
      pending: 0,
      catalog_total: 19_099,
      catalog_succeeded: 19_087,
      catalog_failed: 0,
      catalog_pending: 0,
      catalog_unprocessable: 12,
      unprocessable: 12,
    })

    const text = wrapper.text()
    expect(text).toContain('已富化 19087/19087')
    expect(text).toContain('无法处理 12 个')
    expect(text).toContain('待处理 0')
    expect(wrapper.find('.enrichment-progress-unprocessable').exists()).toBe(false)
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('100')
  })

  it('falls back to actionable fields for legacy responses without catalog counters', () => {
    // 滚动发布期间旧响应没有 catalog_*：展示回退到 eligible/succeeded/failed/pending
    const wrapper = mountPanel({ eligible: 10, succeeded: 9, failed: 1, pending: 0 })

    const text = wrapper.text()
    expect(text).toContain('9/10')
    expect(text).toContain('待处理 0')
    expect(text).toContain('失败 1')
  })

  it('renders retained buckets as separate chips, not merged into progress totals', () => {
    // 在库但退出队列的项目单独成组：进度分母不变，桶按溯源优先级排序，零计数桶不渲染
    const wrapper = mountPanel({
      eligible: 18_580,
      succeeded: 18_580,
      failed: 0,
      pending: 0,
      catalog_total: 18_658,
      catalog_succeeded: 18_656,
      catalog_failed: 0,
      catalog_pending: 2,
      retained_total: 76,
      retained_buckets: {
        tombstone: 1,
        not_found: 13,
        snapshot_below_threshold: 51,
        lost_input: 11,
      },
    })

    const text = wrapper.text()
    expect(text).toContain('已富化 18656/18658')
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

  it('drives retry/backfill buttons from queue counters, not catalog display math', () => {
    // catalog 口径有 pending（展示 5），但可执行队列 queue_pending=0
    // （例如 pending 项目正在跑或不在队列）：backfill 必须禁用。
    // 反之 catalog failed=0 但 queue_failed>0（队列里还有可重试失败）：retry 可用。
    const wrapper = mountPanel({
      eligible: 100,
      succeeded: 95,
      failed: 0,
      pending: 5,
      catalog_total: 100,
      catalog_succeeded: 95,
      catalog_failed: 0,
      catalog_unprocessable: 0,
      queue_failed: 2,
      queue_pending: 0,
    })

    const text = wrapper.text()
    expect(text).toContain('95/100')
    expect(text).toContain('5 pending')

    const retry = wrapper.find('button.monitor-btn-secondary.relative')
    const backfill = wrapper.find('button.monitor-btn-primary')
    expect(retry.attributes('disabled')).toBeUndefined()
    expect(backfill.attributes('disabled')).toBeDefined()
  })

  it('falls back to legacy failed/pending for buttons when queue counters are absent', () => {
    // 滚动发布期间旧响应没有 queue_*：按钮回退到 actionable failed/pending
    const wrapper = mountPanel({ eligible: 10, succeeded: 5, failed: 1, pending: 4 })

    const retry = wrapper.find('button.monitor-btn-secondary.relative')
    const backfill = wrapper.find('button.monitor-btn-primary')
    expect(retry.attributes('disabled')).toBeUndefined()
    expect(backfill.attributes('disabled')).toBeUndefined()
  })
})
