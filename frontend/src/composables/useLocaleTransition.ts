import { nextTick, readonly, ref } from 'vue'
import { setAppLocale, type AppLocale } from '@/i18n'

const COVER_DELAY_MS = 90
const REVEAL_DELAY_MS = 180
const isLocaleTransitioning = ref(false)

const wait = (duration: number) => new Promise<void>((resolve) => {
  window.setTimeout(resolve, duration)
})

const prefersReducedMotion = () => (
  typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches
)

export function useLocaleTransition() {
  const switchLocale = async (nextLocale: AppLocale) => {
    if (isLocaleTransitioning.value) return
    if (prefersReducedMotion()) {
      setAppLocale(nextLocale)
      return
    }

    isLocaleTransitioning.value = true
    try {
      await wait(COVER_DELAY_MS)
      setAppLocale(nextLocale)
      await nextTick()
      await wait(REVEAL_DELAY_MS)
    } finally {
      isLocaleTransitioning.value = false
    }
  }

  return {
    isLocaleTransitioning: readonly(isLocaleTransitioning),
    switchLocale,
  }
}
