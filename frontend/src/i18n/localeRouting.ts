import { watch } from 'vue'
import type { Router } from 'vue-router'
import i18n, { isAppLocale, setAppLocale } from '@/i18n'

/** Explicit language URLs override saved/browser preferences, including history navigation. */
export function installLocaleRouting(router: Router): () => void {
  const removeHook = router.afterEach((to, _from, failure) => {
    if (!failure && isAppLocale(to.query.lang)) setAppLocale(to.query.lang)
  })
  // Keep a language-specific URL truthful after using the existing language toggle.
  const stop = watch(i18n.global.locale, locale => {
    const route = router.currentRoute.value
    if (isAppLocale(route.query.lang) && route.query.lang !== locale) {
      void router.replace({ query: { ...route.query, lang: locale }, hash: route.hash })
    }
  })
  return () => { removeHook(); stop() }
}
