export interface NavigationItem {
  to: string
  label: string
  exact: boolean
  requiresAdmin?: boolean
  icon: string
}

export const NAV_ITEMS: readonly NavigationItem[] = [
  {
    to: '/',
    label: 'Dashboard',
    exact: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  },
  {
    to: '/projects',
    label: 'Projects',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M8 7h8"/><path d="M8 11h6"/></svg>`,
  },
  {
    to: '/chat',
    label: 'Chat',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
  {
    to: '/report',
    label: 'Report',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    to: '/mcp',
    label: 'MCP',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 8a3 3 0 100 6h3"/><path d="M17 8a3 3 0 110 6h-3"/><path d="M8 12h8"/><path d="M12 4v3"/><path d="M12 17v3"/></svg>`,
  },
  {
    to: '/monitor',
    label: 'Monitor',
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
