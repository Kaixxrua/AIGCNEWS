// 脚本侧动效共用的开关与缓动；数值与 src/motion.css 中的同名 token 保持一致。

export const EASE_OUT = 'cubic-bezier(.22, 1, .36, 1)'
export const EASE_IN = 'cubic-bezier(.55, 0, 1, .45)'

const SPRING_LINEAR = 'linear(0, .041 .7%, .113 2%, .204 3.5%, .307 5.4%, .419 7.4%, .533 9.7%, .643 12.1%, .744 14.7%, .833 17.4%, .908 20.3%, .967 23.3%, 1.011 26.5%, 1.039 29.7%, 1.056 33.1%, 1.062 36.6%, 1.06 40.2%, 1.054 43.9%, 1.044 47.7%, 1.034 51.6%, 1.024 55.5%, 1.015 59.6%, 1.009 63.8%, 1.004 68%, 1 72.4%, .998 76.8%, .997 81.3%, .997 85.8%, .997 90.5%, .998 95.2%, 1)'
// 阻尼 0.85、初速与 SPRING_LINEAR 相同：起步一样快，回弹不到 1%。
const GLIDE_LINEAR = 'linear(0, .039 .7%, .113 2%, .197 3.5%, .301 5.4%, .402 7.4%, .509 9.7%, .607 12.1%, .697 14.7%, .775 17.4%, .841 20.3%, .893 23.3%, .934 26.5%, .963 29.7%, .983 33.1%, .996 36.6%, 1.004 40.2%, 1.007 43.9%, 1.008 47.7%, 1.008 51.6%, 1.007 55.5%, 1.005 59.6%, 1.004 63.8%, 1.003 68%, 1.002 72.4%, 1.001 76.8%, 1.001 81.3%, 1)'
const POP_LINEAR = 'linear(0, .062 .7%, .169 2%, .301 3.5%, .446 5.4%, .595 7.4%, .738 9.7%, .867 12.1%, .975 14.7%, 1.057 17.4%, 1.113 20.3%, 1.144 23.3%, 1.152 26.5%, 1.143 29.7%, 1.122 33.1%, 1.095 36.6%, 1.066 40.2%, 1.039 43.9%, 1.018 47.7%, 1.002 51.6%, .991 55.5%, .987 59.6%, .986 63.8%, .987 68%, .99 72.4%, .994 76.8%, .997 81.3%, .999 85.8%, 1 90.5%, 1.001 95.2%, 1)'

let linearSupported: boolean | undefined

// WAAPI 遇到不认识的缓动会直接抛错，不支持 linear() 的浏览器退回贝塞尔。
function linearOr(curve: string, fallback: string): string {
  if (linearSupported === undefined) {
    linearSupported = typeof CSS !== 'undefined' && typeof CSS.supports === 'function'
      && CSS.supports('transition-timing-function', 'linear(0, 1)')
  }
  return linearSupported ? curve : fallback
}

/** 阻尼 0.7 的弹簧缓动：约 6% 回弹，用于位移。 */
export const spring = (): string => linearOr(SPRING_LINEAR, 'cubic-bezier(.34, 1.3, .64, 1)')

/** 阻尼 0.85 的弹簧缓动：几乎不回弹，用于成片内容长距离重排——跨列滑几百像素也只轻轻落定，不冲出版面。 */
export const glideSpring = (): string => linearOr(GLIDE_LINEAR, EASE_OUT)

/** 阻尼 0.6 的弹簧缓动：约 15% 回弹，用于盖章、按下回弹一类的强调。 */
export const popSpring = (): string => linearOr(POP_LINEAR, 'cubic-bezier(.34, 1.56, .64, 1)')

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 当前环境能否播放 Web Animations（jsdom 等测试环境没有 Element.animate）。 */
export function canAnimate(el: Element): boolean {
  return typeof (el as HTMLElement).animate === 'function' && !prefersReducedMotion()
}
