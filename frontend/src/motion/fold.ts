import { EASE_OUT, canAnimate } from './motion'

/**
 * 折叠区的展开与收起：高度在 0 与内容实际高度之间过渡，内容同时淡入淡出，
 * 给 <Transition @enter="unfold" @leave="fold"> 用（v-show、v-if 都行）。
 * 中途反向点击时从此刻的高度接着走；元素自己的上下外边距一并收到 0，父级是纵向 flex/grid 时
 * 连同它与相邻项之间的 gap 一起收掉，收到底不跳。
 * 动画期间用 clip-path 裁掉溢出，结束即撤，不改元素自己的样式。
 */
const UNFOLD_MS = 300
const FOLD_MS = 240

interface FoldBox { height: string; paddingTop: string; paddingBottom: string; marginTop: string; marginBottom: string; opacity: string }

const boxOf = (style: CSSStyleDeclaration): FoldBox => ({
  height: style.height,
  paddingTop: style.paddingTop,
  paddingBottom: style.paddingBottom,
  marginTop: style.marginTop,
  marginBottom: style.marginBottom,
  opacity: style.opacity,
})

/** 收起时要一并吃掉的父级行距：只有纵向排布时才有；前面有兄弟时吃掉前面的，排在最前时吃掉后面的。 */
function gapAround(el: HTMLElement): { before: number; after: number } {
  const parent = el.parentElement
  if (!parent) return { before: 0, after: 0 }
  const style = getComputedStyle(parent)
  const vertical = style.display.includes('grid')
    || (style.display.includes('flex') && style.flexDirection.startsWith('column'))
  const gap = vertical ? parseFloat(style.rowGap) || 0 : 0
  if (el.previousElementSibling) return { before: gap, after: 0 }
  return { before: 0, after: el.nextElementSibling ? gap : 0 }
}

function animateFold(el: Element, open: boolean, done: () => void) {
  const node = el as HTMLElement
  if (!canAnimate(node) || getComputedStyle(node).display === 'contents') {
    done()
    return
  }
  const previous = node.getAnimations().filter((animation) => animation.id === 'fold')
  const current = previous.length ? boxOf(getComputedStyle(node)) : null
  previous.forEach((animation) => animation.cancel())
  const natural = boxOf(getComputedStyle(node))
  const gap = gapAround(node)
  const closed: FoldBox = {
    height: '0px',
    paddingTop: '0px',
    paddingBottom: '0px',
    marginTop: `${-gap.before}px`,
    marginBottom: `${-gap.after}px`,
    opacity: '0',
  }
  const from = current ?? (open ? closed : natural)
  const to = open ? natural : closed
  // 收起停在 0 高度直到 Vue 把元素藏掉，免得 finish 事件前闪回一帧原高。
  const animation = node.animate(
    [{ ...from, clipPath: 'inset(0)' }, { ...to, clipPath: 'inset(0)' }],
    { duration: open ? UNFOLD_MS : FOLD_MS, easing: EASE_OUT, fill: open ? 'none' : 'forwards' },
  )
  animation.id = 'fold'
  // 被反向点击打断时由 Vue 自己结算这次过渡，这里只在正常播完时交还。
  animation.addEventListener('finish', () => {
    done()
    if (!open) animation.cancel()
  })
}

export const unfold = (el: Element, done: () => void): void => animateFold(el, true, done)
export const fold = (el: Element, done: () => void): void => animateFold(el, false, done)
