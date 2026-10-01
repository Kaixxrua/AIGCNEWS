import { ref, watch, type Ref } from 'vue'

/**
 * 桌面简报控制条三段（分区标签、日期行、操作按钮）的排法：
 * - one-row：三段并排放得下，排一行；
 * - actions-up：标签与按钮一行，日期行另起一行（两种两行排法都放得下或都放不下时也用它，后者自然折成三行）；
 * - actions-down：标签与按钮挤不下一行（登录后订阅状态、发送到邮箱等按钮多了），标签独占一行，按钮挪到日期行右侧。
 */
export type ReportBarLayout = 'one-row' | 'actions-up' | 'actions-down'

// 宽度按布局取整（不受入场缩放影响），三段各差不到半像素，留 2px 宁可多排一行也不挤。
const ROUNDING_SLACK = 2

/**
 * 三段宽度随语言、登录与订阅状态、字体加载而变，写死断点总有放不下的时候，所以量出来再定：临时给控制条加
 * is-measuring-row，让三段各按内容宽度排开，读完立刻撤掉，同步完成，不会闪。
 *
 * 只观察控制条所在容器的尺寸（控制条换行数时自身高度会变，观察它会在同一帧里循环触发）、控制条里的增删改字，
 * 以及字体加载完成。不启用时为 null。
 */
export const useReportBarLayout = (barRef: Ref<HTMLElement | null>, enabled: Ref<boolean>) => {
  const layout = ref<ReportBarLayout | null>(null)

  const measure = (bar: HTMLElement) => {
    bar.classList.add('is-measuring-row')
    const width = (selector: string) => bar.querySelector<HTMLElement>(selector)?.offsetWidth ?? 0
    const tabs = width('.report-controls__tabs')
    const dateline = width('.report-controls__head > :first-child')
    const actions = width('.report-controls__actions')
    const style = getComputedStyle(bar)
    const gap = parseFloat(style.columnGap) || 0
    const room = bar.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0)
    bar.classList.remove('is-measuring-row')
    const fit = (...parts: number[]) => parts.reduce((sum, part) => sum + part, 0) + gap * (parts.length - 1) + ROUNDING_SLACK <= room
    if (tabs && fit(tabs, dateline, actions)) layout.value = 'one-row'
    else if (fit(tabs, actions) || !fit(dateline, actions)) layout.value = 'actions-up'
    else layout.value = 'actions-down'
  }

  watch([barRef, enabled], ([bar, on], _previous, onCleanup) => {
    layout.value = null
    if (!bar || !on) return
    const update = () => measure(bar)
    const resize = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(update)
    if (bar.parentElement) resize?.observe(bar.parentElement)
    const mutation = typeof MutationObserver === 'undefined' ? undefined : new MutationObserver(update)
    mutation?.observe(bar, { childList: true, subtree: true, characterData: true })
    let live = true
    void document.fonts?.ready.then(() => {
      if (live) update()
    })
    update()
    onCleanup(() => {
      live = false
      resize?.disconnect()
      mutation?.disconnect()
    })
  }, { immediate: true, flush: 'post' })

  return layout
}
