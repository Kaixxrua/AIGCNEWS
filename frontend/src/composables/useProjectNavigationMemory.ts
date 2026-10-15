import { ref, watch } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

type PageRoute = Pick<RouteLocationNormalizedLoaded, 'name' | 'path' | 'query'>

const projectSource = (route: PageRoute) => {
  const source = Array.isArray(route.query.source) ? route.query.source[0] : route.query.source
  return source === 'website' || source === 'favorites' ? source : 'all'
}

// The three project collections share a component, but retain separate browsing sessions.
export const pageViewKey = (route: PageRoute) => {
  if (route.name === 'github-projects') return `/projects:${projectSource(route)}`
  return route.name === 'ui-library' ? 'ui-library' : route.path
}

/** Only navigation entries resume a visit; explicit links and browser history keep their URLs. */
export const useProjectNavigationMemory = (route: RouteLocationNormalizedLoaded) => {
  const targets = ref<Record<string, string>>({})
  watch(() => route.fullPath, () => {
    if (route.name !== 'github-projects') return
    const source = projectSource(route)
    if (source === 'favorites') return
    const entry = source === 'website' ? '/projects?source=website' : '/projects'
    targets.value = { ...targets.value, [entry]: route.fullPath }
  }, { immediate: true, flush: 'sync' })
  return targets
}
