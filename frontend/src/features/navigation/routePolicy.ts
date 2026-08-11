import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

export interface RouteAuthState {
  status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'
  isAdmin: boolean
}

export interface FeatureGateState {
  xSource: boolean
  wechatSource: boolean
}

declare module 'vue-router' {
  interface RouteMeta {
    guestOnly?: boolean
    requiresAuth?: boolean
    requiresAdmin?: boolean
    /** 可插拔源路由：对应特性开关关闭时重定向回首页 */
    feature?: 'xSource' | 'wechatSource'
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

/** 特性门控：开关关闭的源路由一律回首页（对外不暴露该源的存在性差异）。 */
export const getFeatureGateRedirect = (
  to: RouteLocationNormalized,
  features: FeatureGateState,
): RouteLocationRaw | null => {
  const key = to.meta.feature
  if (key && !features[key]) return { path: '/' }
  return null
}
