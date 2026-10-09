import { computed, ref, type Ref } from 'vue'
import type { AppLocale } from '@/i18n'
import type { GitHubProjectItem, GitHubProjectSort, ProjectScope } from '@/services/projects/projectApi'
import { estimateProjectCardHeight, isWebsite } from '@/features/projects/projectPresentation'
import { distributeColumns } from '@/utils/masonry'

interface ProjectMasonryOptions {
  pageEl: Ref<HTMLElement | null>
  projects: Ref<GitHubProjectItem[]>
  locale: Ref<string>
  isPersonalView: Readonly<Ref<boolean>>
  sort: Ref<GitHubProjectSort>
  selectedScope: Ref<ProjectScope>
  t: (key: string) => string
}

/** Keeps measurement ownership explicit for KeepAlive pause/resume. */
export function useProjectMasonry({ pageEl, projects, locale, isPersonalView, sort, selectedScope, t }: ProjectMasonryOptions) {
  // 瀑布流：估高贪心分列（与 X 页同一套 distributeColumns）。列数由容器
  // 内容宽驱动，镜像旧 auto-fill minmax(260px,1fr) 的断档；列内保持服务端
  // 排序（stars/hot 等），左上角仍是当前页第一项。
  const MASONRY_MIN_CARD_PX = 260
  const MASONRY_GAP_PX = 12
  const gridContentWidth = ref(0)
  // 漫画皮肤经页面上的 --projects-masonry-min / --projects-masonry-gap 改写列宽下限与列距；
  // 轨道是显式像素宽，CSS 列距须取同一个变量，否则整行溢出。
  const masonryMinCardPx = ref(MASONRY_MIN_CARD_PX)
  const masonryGapPx = ref(MASONRY_GAP_PX)
  const cssPx = (style: CSSStyleDeclaration, name: string, fallback: number) => {
    const value = parseFloat(style.getPropertyValue(name))
    return Number.isFinite(value) && value > 0 ? value : fallback
  }
  let pageResizeObserver: ResizeObserver | null = null
  // 实测页面滚动容器的水平 padding 得出内容宽：720/639px 断点会收窄
  // padding，写死常量会让瀑布流分列在窄屏失真。
  const measureGridContentWidth = () => {
    const el = pageEl.value
    if (!el) return
    const style = window.getComputedStyle(el)
    gridContentWidth.value = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
    masonryMinCardPx.value = cssPx(style, '--projects-masonry-min', MASONRY_MIN_CARD_PX)
    masonryGapPx.value = cssPx(style, '--projects-masonry-gap', MASONRY_GAP_PX)
  }
  const startGridMeasure = () => {
    measureGridContentWidth()
    if (pageResizeObserver || !pageEl.value || typeof ResizeObserver === 'undefined') return
    // jsdom 等无 ResizeObserver 环境跳过观测，回退单列渲染
    pageResizeObserver = new ResizeObserver(measureGridContentWidth)
    pageResizeObserver.observe(pageEl.value)
  }
  const stopGridMeasure = () => {
    pageResizeObserver?.disconnect()
    pageResizeObserver = null
  }
  const masonryColumnCount = computed(() => {
    const width = gridContentWidth.value
    if (width <= 0) return 1
    return Math.max(1, Math.floor((width + masonryGapPx.value) / (masonryMinCardPx.value + masonryGapPx.value)))
  })
  // 结果不足以填满容器容量时不渲染空轨道；空结果仍保留单列作为首帧
  // 与空状态的稳定回退。列宽始终按容器满列容量计算，稀疏行左侧对齐、
  // 右侧留白，避免把一两张卡拉伸到整行宽度。
  const effectiveMasonryColumnCount = computed(() => (
    projects.value.length > 0
      ? Math.min(masonryColumnCount.value, projects.value.length)
      : 1
  ))
  // 列宽取整并按列分配余数：1fr 均分在 DPR=1 屏幕上会让第 2/4 列落在
  // 半像素上，1px 边框被抗锯齿成虚边（用户反馈"二四列边框绘制异常"）。
  // 显式整数轨道 + 整数 gap ⇒ 每列左右边缘都落在物理像素上。
  const masonryColumnWidths = computed(() => {
    const count = masonryColumnCount.value
    const total = Math.floor(gridContentWidth.value) - masonryGapPx.value * (count - 1)
    const base = Math.floor(total / count)
    let remainder = total - base * count
    return Array.from({ length: count }, () => base + (remainder-- > 0 ? 1 : 0))
  })
  const masonryGridTemplate = computed(() => {
    const widths = masonryColumnWidths.value.slice(0, effectiveMasonryColumnCount.value)
    return widths.every((w) => w > 0) ? widths.map((w) => `${w}px`).join(' ') : 'minmax(0, 1fr)'
  })
  const masonryColumnWidth = computed(() => {
    const width = Math.min(...masonryColumnWidths.value)
    return width > 0 ? width : masonryMinCardPx.value // 首帧未测量时的回退列宽
  })
  const masonryColumns = computed(() => distributeColumns(
    projects.value,
    effectiveMasonryColumnCount.value,
    (repo) => estimateProjectCardHeight(repo, masonryColumnWidth.value, locale.value as AppLocale, {
      isPersonalView: isPersonalView.value,
      descriptionFallback: t(isWebsite(repo) ? 'projects.fallbackWebsite' : 'projects.fallbackProject'),
      genericTagLabels: { project: t('projects.genericProjectTag'), website: t('projects.genericWebsiteTag') },
      sort: sort.value,
      scope: selectedScope.value,
    }),
  ))
  return { masonryColumns, masonryGridTemplate, measureGridContentWidth, startGridMeasure, stopGridMeasure }
}
