export type NavigationFeatureKey = 'xSource' | 'wechatSource'
export type NavigationSitePageKey = 'contactPage'

export interface NavigationItem {
  to: string
  labelKey: `navigation.${string}`
  /** 管理员自定义的导航文案（站点页面），优先于 labelKey */
  labelText?: string
  exact: boolean
  requiresAdmin?: boolean
  requiresAuth?: boolean
  /** 可插拔源导航项：对应特性开关被明确关闭时从导航隐藏 */
  featureKey?: NavigationFeatureKey
  /** 站点自定义页面导航项：对应页面未启用时从导航隐藏 */
  sitePageKey?: NavigationSitePageKey
  icon: string
}

/** 特性门控：未声明 featureKey 的项不受开关影响；仅显式 false 才隐藏。 */
export const isNavigationItemFeatureEnabled = (
  item: Pick<NavigationItem, 'featureKey'>,
  features: Record<NavigationFeatureKey, boolean>,
): boolean => !item.featureKey || features[item.featureKey] !== false

/**
 * 站点页面门控：与特性门控的默认值相反——未声明 sitePageKey 的项不受影响；
 * 声明了的项须配置显式启用才显示（fail-closed，开源默认无此页）。
 */
export const isNavigationItemSitePageEnabled = (
  item: Pick<NavigationItem, 'sitePageKey'>,
  sitePages: Record<NavigationSitePageKey, boolean>,
): boolean => !item.sitePageKey || sitePages[item.sitePageKey] === true

export const NAV_ITEMS: readonly NavigationItem[] = [
  {
    to: '/',
    labelKey: 'navigation.dashboard',
    exact: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  },
  {
    to: '/projects',
    labelKey: 'navigation.projects',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M8 7h8"/><path d="M8 11h6"/></svg>`,
  },
  {
    to: '/chat',
    labelKey: 'navigation.chat',
    exact: false,
    requiresAdmin: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
  {
    to: '/report',
    labelKey: 'navigation.report',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    to: '/x',
    labelKey: 'navigation.xboard',
    exact: false,
    featureKey: 'xSource',
    icon: `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>`,
  },
  {
    to: '/wechat',
    labelKey: 'navigation.wechat',
    exact: false,
    requiresAdmin: true,
    featureKey: 'wechatSource',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 4C5.36 4 2 6.91 2 10.5c0 1.96 1.13 3.72 2.94 4.96L4 19l3.85-1.93c.67.18 1.38.28 2.12.28.23 0 .46-.01.68-.03"/><path d="M14.5 9c3.87 0 7 2.69 7 6s-3.13 6-7 6c-.63 0-1.24-.06-1.83-.18L11 21.5l.5-2.5c-1.5-1.1-2.5-2.77-2.5-4.62 0-3.31 3.13-6 7-6z"/><circle cx="8" cy="10.5" r=".8" fill="currentColor" stroke="none"/><circle cx="13" cy="10.5" r=".8" fill="currentColor" stroke="none"/><circle cx="16.5" cy="14" r=".6" fill="currentColor" stroke="none"/><circle cx="20.5" cy="14" r=".6" fill="currentColor" stroke="none"/></svg>`,
  },
  {
    to: '/mcp',
    labelKey: 'navigation.mcp',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8a3 3 0 100 6h3"/><path d="M17 8a3 3 0 110 6h-3"/><path d="M8 12h8"/><path d="M12 4v3"/><path d="M12 17v3"/></svg>`,
  },
  {
    to: '/dsh',
    labelKey: 'navigation.dsh',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><path d="M23.748 4.651c-.254-.124-.364.113-.512.233-.051.04-.094.09-.137.137-.372.397-.806.657-1.373.626-.829-.046-1.537.214-2.163.848-.133-.782-.575-1.248-1.247-1.548-.352-.155-.708-.311-.955-.65-.172-.24-.219-.509-.305-.774-.055-.16-.11-.323-.293-.35-.2-.031-.278.136-.356.276-.313.572-.434 1.202-.422 1.84.027 1.436.633 2.58 1.838 3.393.137.094.172.187.129.323-.082.28-.18.553-.266.833-.055.179-.137.218-.328.14a5.5 5.5 0 0 1-1.737-1.179c-.857-.828-1.631-1.743-2.597-2.46a12 12 0 0 0-.689-.47c-.985-.957.13-1.743.387-1.836.27-.098.094-.433-.778-.428-.872.003-1.67.295-2.687.685a3 3 0 0 1-.465.136 9.6 9.6 0 0 0-2.883-.101c-1.885.21-3.39 1.1-4.497 2.622C.082 8.776-.231 10.854.152 13.02c.403 2.284 1.568 4.175 3.36 5.653 1.857 1.533 3.997 2.284 6.438 2.14 1.482-.085 3.132-.284 4.994-1.86.47.234.962.328 1.78.398.629.058 1.235-.031 1.705-.129.735-.155.684-.836.418-.961-2.155-1.004-1.682-.595-2.112-.926 1.095-1.295 2.768-3.598 3.284-6.733.05-.346.115-.834.108-1.114-.004-.171.035-.238.23-.257a4.2 4.2 0 0 0 1.545-.475c1.397-.763 1.96-2.016 2.093-3.517.02-.23-.004-.467-.247-.588M11.58 18.168c-2.088-1.642-3.101-2.183-3.52-2.16-.39.024-.32.472-.234.763.09.288.207.487.371.74.114.167.192.416-.113.603-.673.416-1.842-.14-1.897-.168-1.361-.801-2.5-1.86-3.301-3.306-.775-1.393-1.225-2.888-1.299-4.482-.02-.385.094-.522.477-.592a4.7 4.7 0 0 1 1.53-.038c2.131.311 3.946 1.264 5.467 2.774.868.86 1.525 1.887 2.202 2.89.72 1.066 1.494 2.082 2.48 2.915.348.291.626.513.892.677-.802.09-2.14.109-3.055-.615zm1.001-6.44a.306.306 0 0 1 .415-.287.3.3 0 0 1 .113.074.3.3 0 0 1 .086.214c0 .17-.136.307-.308.307a.303.303 0 0 1-.306-.307m3.11 1.596c-.2.081-.4.151-.591.16a1.25 1.25 0 0 1-.798-.254c-.274-.23-.47-.358-.551-.758a1.7 1.7 0 0 1 .015-.588c.07-.327-.007-.537-.238-.727-.188-.156-.426-.199-.689-.199a.6.6 0 0 1-.254-.078.253.253 0 0 1-.114-.358 1 1 0 0 1 .192-.21c.356-.202.767-.136 1.146.016.352.144.618.408 1.001.782.392.451.462.576.685.915.176.264.336.536.446.848.066.194-.02.353-.25.45"/></svg>`,
  },
  {
    to: '/membership',
    labelKey: 'navigation.membership',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11.562 3.266a.5.5 0 01.876 0L15.39 8.87a1 1 0 001.516.294L21.183 5.5a.5.5 0 01.798.519l-2.834 10.246a1 1 0 01-.956.735H5.81a1 1 0 01-.957-.735L2.02 6.02a.5.5 0 01.798-.519l4.276 3.664a1 1 0 001.516-.294z"/><path d="M5 21h14"/></svg>`,
  },
  {
    to: '/contact',
    labelKey: 'navigation.contact',
    exact: false,
    sitePageKey: 'contactPage',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16a2 2 0 012 2v12a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
  },
  {
    to: '/monitor',
    labelKey: 'navigation.monitor',
    exact: false,
    requiresAdmin: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>`,
  },
]

export const KEEP_ALIVE_VIEW_NAMES: string[] = ['DashboardView', 'GitHubProjectsView']
export const KEEP_ALIVE_MAX = 2

export const isNavigationItemActive = (
  item: Pick<NavigationItem, 'to' | 'exact'>,
  currentPath: string,
): boolean => {
  if (item.exact) return currentPath === item.to
  return currentPath.startsWith(item.to)
}
