import { ref, type ComputedRef } from 'vue'
import { i18n } from '@/i18n'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubCrawlStatus } from '@/features/monitor/monitorModel'

export const CRAWL_POLL_INTERVAL = 3000

const isCrawlTerminal = (status: string) => status === 'success' || status === 'failed'

interface UseGithubCrawlPollingOptions {
  api: MonitorApi
  isAdmin: ComputedRef<boolean>
  schedule: (callback: () => void, delay: number) => unknown
  setSuccess: (message: string) => void
  setError: (message: string) => void
  refreshTasks: () => Promise<void>
}

export const useGithubCrawlPolling = ({
  api,
  isAdmin,
  schedule,
  setSuccess,
  setError,
  refreshTasks,
}: UseGithubCrawlPollingOptions) => {
  const crawlPolling = ref(false)
  const crawlStatus = ref<GithubCrawlStatus | null>(null)
  const activeCrawlRun = ref<{ channel: string; first_seen_after: string } | null>(null)

  const pollGithubCrawlStatus = async () => {
    if (!crawlPolling.value) return
    try {
      const status = await api.fetchGithubCrawlStatus(activeCrawlRun.value || undefined)
      crawlStatus.value = status
      if (isCrawlTerminal(status.task_status)) {
        crawlPolling.value = false
        activeCrawlRun.value = null
        if (status.task_status === 'success') setSuccess(i18n.global.t('monitor.crawl.runFinished'))
        else setError(i18n.global.t('monitor.crawl.runFailed', { error: status.error_msg || '' }))
        await refreshTasks()
        return
      }
    } catch (error) {
      // 轮询错误容忍：容器重启等瞬态故障不断链
      console.error('Failed to poll GitHub crawl status', error)
    }
    if (crawlPolling.value) schedule(() => { void pollGithubCrawlStatus() }, CRAWL_POLL_INTERVAL)
  }

  const beginCrawlPolling = (run: { channel: string; first_seen_after: string }) => {
    activeCrawlRun.value = run
    crawlPolling.value = true
    schedule(() => { void pollGithubCrawlStatus() }, CRAWL_POLL_INTERVAL)
  }

  const resumeGithubCrawlPolling = async () => {
    if (!isAdmin.value || crawlPolling.value) return
    try {
      const status = await api.fetchGithubCrawlStatus()
      if (!status.task_id) return
      crawlStatus.value = status
      if (status.task_status === 'running') {
        beginCrawlPolling({ channel: status.channel, first_seen_after: status.first_seen_after })
      }
    } catch (error) { console.error('Failed to fetch GitHub crawl status', error) }
  }

  return { crawlPolling, crawlStatus, beginCrawlPolling, resumeGithubCrawlPolling }
}
