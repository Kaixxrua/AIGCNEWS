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

/** 「我的网页收藏」：项目库的网页视图（/projects?source=website）。 */
export const isPersonalWebsiteRoute = (to: Pick<RouteLocationNormalized, 'name' | 'query'>): boolean =>
  to.name === 'github-projects' && to.query.source === 'website'

/**
 * 网页栏目：确认未登录（或登录态暂时无法确认）的访客点「我的网页收藏」时，站长推荐有内容就先看站长推荐
 * ——个人收藏要登录后才有。站长推荐为空或还没拿到（null）时留在原地，收藏页照常请他登录。
 */
export const getWebsiteCollectionRedirect = (
  to: Pick<RouteLocationNormalized, 'name' | 'query'>,
  auth: Pick<RouteAuthState, 'status'>,
  recommendedCount: number | null,
): RouteLocationRaw | null => {
  if (!isPersonalWebsiteRoute(to)) return null
  if (auth.status !== 'anonymous' && auth.status !== 'degraded') return null
  return recommendedCount ? { path: '/websites' } : null
}

/** 守卫等站长推荐的上限：等不到按「还没拿到」处理，留在收藏页，不让导航卡住。 */
export const WEBSITE_PICKS_WAIT_MS = 2500

/** 守卫用：先等登录态确认，只有访客才去拿站长推荐（进程内只拉一次），再按 getWebsiteCollectionRedirect 定去向。 */
export const resolveWebsiteCollectionRedirect = async (
  to: Pick<RouteLocationNormalized, 'name' | 'query'>,
  auth: Pick<RouteAuthState, 'status'> & { ensureInitialized: () => Promise<unknown> },
  loadRecommended: () => Promise<readonly unknown[] | null>,
  waitMs = WEBSITE_PICKS_WAIT_MS,
): Promise<RouteLocationRaw | null> => {
  if (!isPersonalWebsiteRoute(to)) return null
  if (auth.status === 'initializing') await auth.ensureInitialized()
  if (auth.status === 'authenticated') return null
  let timer: ReturnType<typeof setTimeout> | undefined
  const recommended = await Promise.race([
    loadRecommended().catch(() => null),
    new Promise<null>((resolve) => { timer = setTimeout(resolve, waitMs, null) }),
  ]).finally(() => clearTimeout(timer))
  return getWebsiteCollectionRedirect(to, auth, recommended?.length ?? null)
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
