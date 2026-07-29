import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

export interface RouteAuthState {
  status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'
  isAdmin: boolean
}

declare module 'vue-router' {
  interface RouteMeta {
    guestOnly?: boolean
    requiresAuth?: boolean
    requiresAdmin?: boolean
  }
}

export const getRoutePolicyRedirect = (
  to: RouteLocationNormalized,
  auth: RouteAuthState,
): RouteLocationRaw | null => {
  if (auth.status === 'anonymous' && (to.meta.requiresAuth || to.meta.requiresAdmin)) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (auth.status === 'authenticated' && to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/' }
  }

  if (to.meta.guestOnly && auth.status === 'authenticated') {
    return { path: '/' }
  }

  return null
}
