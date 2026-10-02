import { computed, ref, watch, type Ref } from 'vue'
import type { PeekContent, PeekCurveState, ProjectPeekData } from './useProjectPeek'

/** 详情栏打开的那一行：行的 key 和它查的仓库（owner/repo） */
export interface PaneTarget {
  key: string
  repoId: string
}

export interface ProjectPaneOptions {
  /** 宽屏（1600px 以上）的榜单才有详情栏；没了就收起 */
  available: Ref<boolean>
  /** 这一页各行的 key，按阅读顺序 */
  keys: Ref<readonly string[]>
  /** 这一页还在取（换页、换筛选时）：取到之前详情栏不动 */
  pending: Ref<boolean>
  /** 行的 key 换成仓库；没有仓库的行给 ''，不开详情栏 */
  repoOf: (key: string) => string
  /** 和悬停速览共用的 README、提交与星标曲线 */
  data: ProjectPeekData
}

/**
 * 宽屏项目库的详情栏：点项目不跳页，详情在右侧打开，列表留在左边。
 * 上一个、下一个（或 j、k）接着看别的项目，走到这一页的头尾时翻页（expectFlip），新的一页取到后接着看它的第一个（往前翻是最后一个）；
 * 换项目时记下是往下（1）还是往上（-1）换的，详情从那个方向浮进来。打开时顺手把前后两行的 README 和提交先取来。
 * 列表换了（搜索、换分类）而打开的项目不在里面了，或者窗口窄到放不下，就收起。
 */
export function useProjectPane({ available, keys, pending, repoOf, data }: ProjectPaneOptions) {
  const target = ref<PaneTarget | null>(null)
  const direction = ref<1 | -1 | 0>(0)
  let flip: 1 | -1 | 0 = 0
  const index = computed(() => (target.value ? keys.value.indexOf(target.value.key) : -1))

  /** 打开这一行；已经开着它算打开了，开不了（窗口窄、没有仓库）返回 false */
  const open = (key: string): boolean => {
    if (target.value?.key === key) return true
    const repoId = available.value ? repoOf(key) : ''
    if (!repoId) return false
    const from = index.value
    const to = keys.value.indexOf(key)
    direction.value = flip || (from < 0 || to < 0 ? 0 : to > from ? 1 : -1)
    flip = 0
    target.value = { key, repoId }
    data.fetch(repoId)
    if (to >= 0) for (const near of [keys.value[to + 1], keys.value[to - 1]]) if (near) data.fetchPeek(repoOf(near))
    return true
  }

  /** 收起；本来开着返回 true */
  const close = (): boolean => {
    flip = 0
    if (!target.value) return false
    target.value = null
    direction.value = 0
    return true
  }

  /** 换到下一个（1）或上一个（-1）有仓库的行；已经是这一页的头尾返回 false，翻不翻页由外面定 */
  const step = (dir: 1 | -1): boolean => {
    const list = keys.value
    if (index.value < 0) return false
    for (let at = index.value + dir; at >= 0 && at < list.length; at += dir) if (open(list[at]!)) return true
    return false
  }

  /** 要往后（1）或往前（-1）翻页了：新的一页取到后打开它的第一个或最后一个 */
  const expectFlip = (dir: 1 | -1) => {
    if (target.value) flip = dir
  }

  /** 没取到的（取失败、读不到 GitHub、曲线没取到）马上再取 */
  const retry = () => {
    if (target.value) data.retry(target.value.repoId)
  }

  watch([keys, pending], () => {
    const current = target.value
    if (!current || pending.value) return
    const dir = flip
    if (dir) {
      const list = dir > 0 ? keys.value : [...keys.value].reverse()
      if (!list.some((key) => open(key))) close()
      return
    }
    if (!keys.value.includes(current.key)) close()
  })
  watch(available, (on) => {
    if (!on) close()
  })

  const content = computed<PeekContent | null>(() => (target.value ? data.contentOf(target.value.repoId) : null))
  const curve = computed<PeekCurveState | null>(() => (target.value ? data.curveOf(target.value.repoId) : null))

  return { target, direction, index, content, curve, open, close, step, expectFlip, retry }
}

export type ProjectPane = ReturnType<typeof useProjectPane>
