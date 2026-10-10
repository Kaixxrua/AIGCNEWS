import { getSafeInternalRedirect } from './authViewModel'

/** Explain the destination without changing the sign-in or redirect contract. */
export function getLoginContextKey(target?: unknown): string {
  const url = new URL(getSafeInternalRedirect(target), 'https://aigcnews.invalid')
  if (url.origin !== 'https://aigcnews.invalid') return 'auth.loginDescription'
  const { pathname: path, searchParams: query } = url
  if (query.get('quickSearch') === '1') return 'loginContext.search'
  if (path === '/projects') {
    if (query.get('source') === 'website') return 'loginContext.websites'
    if (query.get('source') === 'favorites') return 'loginContext.favorites'
    if (query.get('q')?.trim()) return 'loginContext.search'
    if (Number(query.get('page')) > 1) return 'loginContext.moreProjects'
    return 'loginContext.projects'
  }
  if (/^\/papers\/[^/]+\/read$/.test(path)) return 'loginContext.paper'
  const contexts: Record<string, string> = {
    '/report': 'report', '/subscriptions': 'subscriptions',
    '/mcp': 'mcp', '/oauth/authorize': 'mcp', '/dsh': 'dsh',
    '/membership/checkout': 'checkout', '/monitor': 'protected',
  }
  return contexts[path] ? `loginContext.${contexts[path]}` : 'auth.loginDescription'
}
