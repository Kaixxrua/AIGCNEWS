import { nextTick } from 'vue'
import { prefersReducedMotion } from './motion'

interface ViewTransitionLike {
  ready: Promise<void>
  finished: Promise<void>
}
type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => Promise<void> | void) => ViewTransitionLike
}

const REVEAL_MS = 580
// 起始即是一枚按钮大小的爆炸框，点下去当帧就看得见。
const START_RADIUS = 18
const SPIKES = 16
const INNER = 0.78

/** 漫画爆炸框：内外半径交替的星形多边形，外圈半径为 radius。 */
export function burstPolygon(cx: number, cy: number, radius: number, rotation = 0): string {
  const points: string[] = []
  for (let i = 0; i < SPIKES * 2; i += 1) {
    const r = i % 2 ? radius * INNER : radius
    const angle = rotation + (Math.PI * i) / SPIKES
    points.push(`${(cx + Math.cos(angle) * r).toFixed(1)}px ${(cy + Math.sin(angle) * r).toFixed(1)}px`)
  }
  return `polygon(${points.join(', ')})`
}

/**
 * 切换主题：新主题的整页快照以按钮为中心炸开一枚爆炸框覆盖旧页面。
 * 浏览器不支持 View Transitions、用户偏好减少动态或拿不到按钮位置时直接切换。
 */
export function revealTheme(origin: { x: number; y: number } | null, apply: () => void): void {
  const doc = document as ViewTransitionDocument
  if (!origin || typeof doc.startViewTransition !== 'function' || prefersReducedMotion()) {
    apply()
    return
  }
  const root = document.documentElement
  root.classList.add('theme-transitioning')
  const transition = doc.startViewTransition.call(doc, async () => {
    apply()
    await nextTick()
  })
  const { x, y } = origin
  // 内圈也要盖住离按钮最远的视口角。
  const far = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y)) / INNER + 24
  transition.ready.then(() => {
    root.animate(
      { clipPath: [burstPolygon(x, y, START_RADIUS), burstPolygon(x, y, far * 0.3, 0.08), burstPolygon(x, y, far, 0.22)] },
      { duration: REVEAL_MS, easing: 'cubic-bezier(.3, .1, .25, 1)', pseudoElement: '::view-transition-new(root)' },
    )
  }).catch(() => undefined)
  transition.finished.catch(() => undefined).finally(() => root.classList.remove('theme-transitioning'))
}
