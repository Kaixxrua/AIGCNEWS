import { ref } from 'vue'
import { i18n } from '@/i18n'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubEnrichmentStatus } from '@/features/monitor/monitorModel'

export const ENRICHMENT_POLL_INTERVAL = 4000
const ENRICHMENT_POLL_STALE_LIMIT = 3
// 补跑单条富化耗时 15-25s（低并发时指纹变化慢），停滞阈值放宽到 15 次（约 60s）避免误判批次结束
const ENRICHMENT_BACKFILL_STALE_LIMIT = 15
const ENRICHMENT_POLL_MAX = 75 // 75 × 4s ≈ 5 分钟上限，防止后台任务挂起时无限轮询

export type EnrichmentPollMode = 'retry' | 'backfill'

interface UseEnrichmentPollingOptions {
  api: MonitorApi
  schedule: (callback: () => void, delay: number) => unknown
  setSuccess: (message: string) => void
}

export const useEnrichmentPolling = ({ api, schedule, setSuccess }: UseEnrichmentPollingOptions) => {
  const enrichmentStatus = ref<GithubEnrichmentStatus | null>(null)
  const enrichmentPolling = ref(false)
  let pollCount = 0
  let stalePolls = 0
  let lastFingerprint = ''
  let pollMode: EnrichmentPollMode = 'retry'

  const enrichmentFingerprint = (status: GithubEnrichmentStatus | null) =>
    status ? `${status.succeeded}:${status.failed}:${status.pending}` : ''

  const stopEnrichmentPolling = (message: string) => {
    enrichmentPolling.value = false
    setSuccess(message)
  }

  const pollGithubEnrichmentStatus = async () => {
    if (!enrichmentPolling.value) return
    pollCount += 1
    try {
      // 直接调 api 而非 fetchGithubEnrichmentStatus，避免轮询反复触发面板 loading 闪烁
      enrichmentStatus.value = await api.fetchGithubEnrichmentStatus()
    } catch (error) {
      // 轮询错误容忍：容器重启等瞬态故障不断链
      console.error('Failed to poll GitHub enrichment status', error)
    }
    const failed = enrichmentStatus.value?.failed ?? 0
    const pending = enrichmentStatus.value?.pending ?? 0
    if (pollMode === 'retry' && failed <= 0) {
      stopEnrichmentPolling(i18n.global.t('monitor.enrichment.retryDone'))
      return
    }
    if (pollMode === 'backfill' && pending <= 0 && failed <= 0) {
      stopEnrichmentPolling(i18n.global.t('monitor.enrichment.backfillDone'))
      return
    }
    const fingerprint = enrichmentFingerprint(enrichmentStatus.value)
    if (fingerprint === lastFingerprint) stalePolls += 1
    else { stalePolls = 0; lastFingerprint = fingerprint }
    const staleLimit = pollMode === 'backfill' ? ENRICHMENT_BACKFILL_STALE_LIMIT : ENRICHMENT_POLL_STALE_LIMIT
    if (stalePolls >= staleLimit) {
      stopEnrichmentPolling(pollMode === 'backfill'
        ? i18n.global.t('monitor.enrichment.backfillSettled', { count: pending + failed })
        : i18n.global.t('monitor.enrichment.retryPartial', { count: failed }))
      return
    }
    if (pollCount >= ENRICHMENT_POLL_MAX) {
      stopEnrichmentPolling(pollMode === 'backfill'
        ? i18n.global.t('monitor.enrichment.backfillStillRunning')
        : i18n.global.t('monitor.enrichment.retryPartial', { count: failed }))
      return
    }
    schedule(() => { void pollGithubEnrichmentStatus() }, ENRICHMENT_POLL_INTERVAL)
  }

  const beginEnrichmentPolling = (mode: EnrichmentPollMode = 'retry') => {
    if (enrichmentPolling.value) return
    pollCount = 0
    stalePolls = 0
    lastFingerprint = enrichmentFingerprint(enrichmentStatus.value)
    pollMode = mode
    enrichmentPolling.value = true
    schedule(() => { void pollGithubEnrichmentStatus() }, ENRICHMENT_POLL_INTERVAL)
  }

  return { enrichmentStatus, enrichmentPolling, beginEnrichmentPolling, stopEnrichmentPolling }
}
