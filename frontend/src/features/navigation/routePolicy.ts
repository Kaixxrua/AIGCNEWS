import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

export interface RouteAuthState {
  status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'
  isAdmin: boolean
}

export interface FeatureGateState {
  xSource: boolean
}

export interface SitePageGateState {
  contactPage: boolean
}

declare module 'vue-router' {
  interface RouteMeta {
    guestOnly?: boolean
    requiresAuth?: boolean
    requiresAdmin?: boolean
    /** 可插拔源路由：对应特性开关关闭时重定向回首页 */
    feature?: 'xSource'
    /** 站点自定义页面路由：对应页面未启用时重定向回首页 */
    sitePage?: 'contactPage'
  }
}

export type RoutePolicyDecision =
  | { kind: 'login'; target: string }
  | { kind: 'redirect'; to: RouteLocationRaw }
  | { kind: 'block' }
  | null

export const getRoutePolicyDecision = (
  to: RouteLocationNormalized,
  auth: RouteAuthState,
): RoutePolicyDecision => {
  const protectedRoute = to.meta.requiresAuth || to.meta.requiresAdmin
  if (protectedRoute && auth.status === 'anonymous') {
    return { kind: 'login', target: to.fullPath }
  }

  if (protectedRoute && (auth.status === 'initializing' || auth.status === 'degraded')) {
    return { kind: 'block' }
  }

  if (auth.status === 'authenticated' && to.meta.requiresAdmin && !auth.isAdmin) {
    return { kind: 'redirect', to: { path: '/' } }
  }

  if (to.meta.guestOnly && auth.status === 'authenticated') {
    return { kind: 'redirect', to: { path: '/' } }
  }

  return null
}

/** 特性门控：开关关闭的源路由一律回首页（对外不暴露该源的存在性差异）。 */
export const getFeatureGateRedirect = (
  to: RouteLocationNormalized,
  features: FeatureGateState,
): RouteLocationRaw | null => {
  const key = to.meta.feature
  if (key && !features[key]) return { path: '/' }
  return null
}

/** 站点页面门控：未启用的站点页面一律回首页（同特性门控的存在性语义）。 */
export const getSitePageGateRedirect = (
  to: RouteLocationNormalized,
  sitePages: SitePageGateState,
): RouteLocationRaw | null => {
  const key = to.meta.sitePage
  if (key && !sitePages[key]) return { path: '/' }
  return null
}
