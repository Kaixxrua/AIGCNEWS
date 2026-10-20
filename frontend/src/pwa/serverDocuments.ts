// Server-owned SEO documents must not become the offline application shell.
// Workbox matches pathname + search, so query strings must also be excluded.
export const serverDocumentNavigationDenylist = [
  /^\/(?:sitemap\.xml|robots\.txt)(?:\?|$)/,
]
