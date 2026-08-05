export interface NavigationItem {
  to: string
  labelKey: `navigation.${string}`
  exact: boolean
  requiresAdmin?: boolean
  icon: string
}

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
    icon: `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>`,
  },
  {
    to: '/wechat',
    labelKey: 'navigation.wechat',
    exact: false,
    requiresAdmin: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 4C5.36 4 2 6.91 2 10.5c0 1.96 1.13 3.72 2.94 4.96L4 19l3.85-1.93c.67.18 1.38.28 2.12.28.23 0 .46-.01.68-.03"/><path d="M14.5 9c3.87 0 7 2.69 7 6s-3.13 6-7 6c-.63 0-1.24-.06-1.83-.18L11 21.5l.5-2.5c-1.5-1.1-2.5-2.77-2.5-4.62 0-3.31 3.13-6 7-6z"/><circle cx="8" cy="10.5" r=".8" fill="currentColor" stroke="none"/><circle cx="13" cy="10.5" r=".8" fill="currentColor" stroke="none"/><circle cx="16.5" cy="14" r=".6" fill="currentColor" stroke="none"/><circle cx="20.5" cy="14" r=".6" fill="currentColor" stroke="none"/></svg>`,
  },
  {
    to: '/mcp',
    labelKey: 'navigation.mcp',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8a3 3 0 100 6h3"/><path d="M17 8a3 3 0 110 6h-3"/><path d="M8 12h8"/><path d="M12 4v3"/><path d="M12 17v3"/></svg>`,
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
