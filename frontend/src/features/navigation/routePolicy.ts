import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

export interface RouteAuthState {
  isLoggedIn: boolean
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
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/' }
  }

  if (to.meta.guestOnly && auth.isLoggedIn) {
    return { path: '/' }
  }

  return null
}
