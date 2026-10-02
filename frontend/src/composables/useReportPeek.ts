import { computed, reactive, ref, shallowRef, watch, type Ref } from 'vue'
import type { PaperLink } from '@/features/report/reportPaperLinks'
import { fetchPaperByArxiv, type PaperItem } from '@/services/papers/paperApi'

/**
 * 宽屏（≥1600px）简报的论文详情栏：点条目里的论文（标题或论文链接）不离开简报，详情在右侧打开，列表留在左边；
 * j / k 或栏里的上一条、下一条接着看别的条目讲的论文。这里管开着哪条的哪篇和取数：同一篇只取一次（没取到的
 * 下次再取），打开一条时顺手预取前后两条的第一篇。版面上讲到论文的条目由大报登记进来，按阅读顺序。
 */
export interface PeekEntry {
  /** 条目在大报里的 key（data-list-key）。 */
  key: string
  papers: PaperLink[]
}

export interface PeekTarget {
  key: string
  arxivId: string
}

export type PeekPaper =
  | { status: 'loading' }
  | { status: 'ready'; paper: PaperItem }
  /** 站内没有收这篇。 */
  | { status: 'missing' }
  | { status: 'error' }

/** 交给大报的一面：开着哪条的哪篇、打开与收起、登记版面上讲到论文的条目。 */
export interface BroadsheetPeek {
  readonly target: PeekTarget | null
  open(target: PeekTarget): boolean
  close(): void
  setEntries(entries: PeekEntry[]): void
  /** 大报撤下时交还登记；已被新版面的登记换掉时不动。 */
  releaseEntries(entries: PeekEntry[]): void
}

export interface ReportPeekOptions {
  /** 宽屏、且不在生成中才开得了；变成开不了时收起。 */
  available: Ref<boolean>
  load?: (arxivId: string) => Promise<PaperItem | null>
}

export function useReportPeek({ available, load = fetchPaperByArxiv }: ReportPeekOptions) {
  const entries = shallowRef<PeekEntry[]>([])
  const target = ref<PeekTarget | null>(null)
  /** 换篇的方向：往后 1、往前 -1，刚打开为 0；withinItem 为同一条里换一篇。详情栏换内容时据此从哪边浮进来。 */
  const direction = ref<1 | -1 | 0>(0)
  const withinItem = ref(false)
  const papers = reactive(new Map<string, PeekPaper>())

  const fetchPaper = (arxivId: string) => {
    const known = papers.get(arxivId)
    if (known && known.status !== 'error') return
    papers.set(arxivId, { status: 'loading' })
    load(arxivId).then(
      (paper) => { papers.set(arxivId, paper ? { status: 'ready', paper } : { status: 'missing' }) },
      () => { papers.set(arxivId, { status: 'error' }) },
    )
  }

  const indexOf = (key: string) => entries.value.findIndex((entry) => entry.key === key)
  const index = computed(() => (target.value ? indexOf(target.value.key) : -1))
  const entry = computed(() => entries.value[index.value] ?? null)
  const current = computed<PeekPaper | null>(() => (target.value ? papers.get(target.value.arxivId) ?? { status: 'loading' } : null))

  const open = (next: PeekTarget): boolean => {
    if (!available.value) return false
    const previous = target.value
    const from = index.value
    const to = indexOf(next.key)
    withinItem.value = !!previous && from === to && to >= 0
    if (withinItem.value) {
      // 同一条里换一篇：按这条列出论文的先后定方向
      const order = entries.value[to]!.papers.map((paper) => paper.arxivId)
      const delta = order.indexOf(next.arxivId) - order.indexOf(previous!.arxivId)
      direction.value = delta > 0 ? 1 : delta < 0 ? -1 : 0
    } else direction.value = previous && from >= 0 && to >= 0 ? (to > from ? 1 : -1) : 0
    target.value = { key: next.key, arxivId: next.arxivId }
    fetchPaper(next.arxivId)
    if (to >= 0) {
      for (const near of [to + 1, to - 1]) {
        const first = entries.value[near]?.papers[0]
        if (first) fetchPaper(first.arxivId)
      }
    }
    return true
  }

  const close = () => {
    target.value = null
    direction.value = 0
    withinItem.value = false
  }

  /** 换到后一条（1）或前一条（-1）讲的第一篇；到头了返回 null。 */
  const step = (dir: 1 | -1): PeekTarget | null => {
    if (index.value < 0) return null
    const next = entries.value[index.value + dir]
    const first = next?.papers[0]
    if (!next || !first) return null
    const reached = { key: next.key, arxivId: first.arxivId }
    return open(reached) ? reached : null
  }

  const retry = () => {
    const arxivId = target.value?.arxivId
    if (arxivId && papers.get(arxivId)?.status === 'error') fetchPaper(arxivId)
  }

  const setEntries = (list: PeekEntry[]) => {
    entries.value = list
    // 开着的那条不在版面上了
    if (target.value && indexOf(target.value.key) < 0) close()
  }
  const releaseEntries = (list: PeekEntry[]) => {
    if (entries.value === list) setEntries([])
  }

  watch(available, (on) => {
    if (!on) close()
  })

  const broadsheet: BroadsheetPeek = {
    get target() {
      return target.value
    },
    open,
    close,
    setEntries,
    releaseEntries,
  }

  return { entries, target, direction, withinItem, index, entry, current, open, close, step, retry, broadsheet }
}

export type ReportPeek = ReturnType<typeof useReportPeek>
