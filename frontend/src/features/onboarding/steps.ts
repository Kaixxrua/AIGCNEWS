export interface TourStep {
  id: string
  route: string
  targets: readonly string[]
  feature?: 'x' | 'contact'
  desktopOnly?: boolean
  copy?: string
  compact?: Partial<Pick<TourStep, 'route' | 'targets' | 'copy'>>
}

// Prefer the actual control, then a stable region on the same page. Empty data
// must not turn a tour into a wait for a particular project or paper to exist.
export const TOUR_STEPS: readonly TourStep[] = [
  { id: 'navigation', route: '/', targets: ['.dock'], compact: { targets: ['.mobile-nav', '.dock'], copy: 'mobileNavigation' } },
  { id: 'home', route: '/', targets: ['.ranking-toolbar', '.dashboard-heading'], compact: { targets: ['.ranking-tabs', '.dashboard-heading'] } },
  { id: 'projects', route: '/projects', targets: ['.projects-search', '.projects-toolbar'] },
  { id: 'projectDetails', route: '/projects', targets: ['.project-chart__rows > :first-child', '.projects-grid > :first-child', '.projects-hero'], compact: { targets: ['.project-card__header', '.project-chart__rows > :first-child', '.projects-hero'] } },
  { id: 'ui', route: '/ui-library', targets: ['.ui-library__command', '.ui-library__header'], compact: { targets: ['.ui-library__search', '.ui-library__header'] } },
  { id: 'uiPreview', route: '/ui-library', targets: ['.ui-library__grid > :first-child', '.ui-library__main'], compact: { targets: ['.ui-library__card-title', '.ui-library__header'] } },
  { id: 'websites', route: '/websites', targets: ['.website-content .website-header', '.recommended-websites-page'] },
  { id: 'myWebsites', route: '/projects?source=website', targets: ['.website-tabs a[href="/projects?source=website"]', '.projects-login-prompt', '.projects-website-add', '.projects-hero'] },
  { id: 'report', route: '/report', targets: ['.report-shell > .comic-panel', '.report-shell'], compact: { targets: ['.report-controls__head', '.report-shell > .comic-panel'] } },
  { id: 'papers', route: '/report', targets: ['.report-reading'], compact: { route: '/report?type=arxiv', targets: ['.report-reading a[href*="arxiv.org/abs/"]', '.report-reading .prose-content h2', '.report-reading [role="status"] p', '.report-reading'] } },
  { id: 'subscribe', route: '/report', targets: ['[data-tour="subscribe"]', '.report-shell > .comic-panel'] },
  { id: 'x', route: '/x', targets: ['.xboard-follow-group[data-group="openai"]', '.xboard-follow-panel', '.xboard-follow-toggle', '.xboard-header', '.xboard-page'], feature: 'x' },
  { id: 'mcp', route: '/mcp', targets: ['.mcp-desk-clients', '.mcp-connect-page .connection-intro'], desktopOnly: true },
  { id: 'mcpExamples', route: '/mcp', targets: ['.mcp-desk-verify', '.mcp-desk'], desktopOnly: true },
  { id: 'dsh', route: '/dsh', targets: ['.dsh-desk-head', '.dsh-page .connection-intro'], desktopOnly: true },
  { id: 'tracking', route: '/dsh', targets: ['[data-tour-nav="/subscriptions"]', '.dock'], compact: { route: '/' } },
  { id: 'membership', route: '/membership', targets: ['.tier-grid', '.membership-hero'], compact: { targets: ['.membership-title'] } },
  { id: 'account', route: '/membership', targets: ['.dock-item--account'], compact: { targets: ['[data-tour="more"]', '.dock-item--account'], copy: 'mobileAccount' } },
  { id: 'search', route: '/membership', targets: ['.quick-search-button'], desktopOnly: true },
  { id: 'tools', route: '/membership', targets: ['.app-masthead__actions'], compact: { copy: 'mobileTools' } },
  { id: 'contact', route: '/contact', targets: ['.app-content .view-container'], feature: 'contact', compact: { targets: ['.app-content h1', '[data-tour="more"]'] } },
  { id: 'footer', route: '/', targets: ['.footer-right', '.dock-footer'], compact: { targets: ['[data-tour="more"]'], copy: 'mobileFooter' } },
  { id: 'bookmark', route: '/', targets: ['[data-tour="bookmark"]'], compact: { targets: ['[data-tour="bookmark"]', '[data-tour="more"]'], copy: 'mobileBookmark' } },
  { id: 'help', route: '/', targets: ['[data-tour="help"]'] },
]

export function availableSteps(flags: { x: boolean; contact: boolean }, compact = false): TourStep[] {
  return TOUR_STEPS.filter(step => (!step.feature || flags[step.feature]) && (!compact || !step.desktopOnly))
    .map(step => compact ? { ...step, ...step.compact } : step)
}

const PAGE_ONLY_STEPS: Record<string, TourStep> = {
  '/subscriptions': { id: 'subscriptionsPage', route: '/subscriptions', targets: ['.subs-heading', '.subs-page'] },
  '/monitor': { id: 'monitorPage', route: '/monitor', targets: ['.monitor-heading', '.monitor-page'] },
  '/membership/checkout': { id: 'checkoutPage', route: '/membership/checkout', targets: ['.checkout-hero', '.checkout-card'] },
  '/privacy': { id: 'privacyPage', route: '/privacy', targets: ['.legal-page .legal-head', '.legal-page'] },
  '/disclaimer': { id: 'disclaimerPage', route: '/disclaimer', targets: ['.legal-page .legal-head', '.legal-page'] },
}

// The Help button describes only the view already on screen. Query variants of
// /projects are different collections, even though they share a route component.
export function pageSteps(steps: readonly TourStep[], path: string, source?: unknown, compact = false): TourStep[] {
  if (/^\/papers\/[^/]+\/read$/.test(path)) {
    return [{ id: 'paperReadPage', route: path, targets: ['.paper-read-heading', '.paper-read-shell'] }]
  }
  const local = PAGE_ONLY_STEPS[path]
  if (local) return [local]
  const ids: Record<string, readonly string[]> = {
    '/': ['home'],
    '/projects': source === 'website' ? ['myWebsites'] : ['projects', 'projectDetails'],
    '/websites': ['websites'],
    '/ui-library': ['ui', 'uiPreview'],
    '/report': ['report', 'papers', 'subscribe'],
    '/x': ['x'],
    '/mcp': compact ? ['mcp'] : ['mcp', 'mcpExamples'],
    '/dsh': ['dsh'],
    '/membership': ['membership'],
    '/contact': ['contact'],
  }
  const selected = ids[path.startsWith('/ui-library/') ? '/ui-library' : path] ?? []
  return selected.flatMap(id => {
    const step = steps.find(item => item.id === id)
      // Desktop-only integrations are skipped in the full mobile tour, but a
      // visitor already on one of those pages can still ask for its help.
      ?? (compact && (id === 'mcp' || id === 'dsh') ? TOUR_STEPS.find(item => item.id === id) : undefined)
    if (!step) return []
    if (id === 'contact') return [{ ...step, targets: ['.contact-title', '.contact-page'] }]
    return [compact ? { ...step, ...step.compact } : step]
  })
}

// Keep the current section on resize/resume, or advance past desktop-only steps.
export function resumeStepIndex(steps: readonly TourStep[], id?: string): number {
  const exact = steps.findIndex(step => step.id === id)
  if (exact >= 0) return exact
  const position = TOUR_STEPS.findIndex(step => step.id === id)
  return Math.max(0, steps.findIndex(step => TOUR_STEPS.findIndex(item => item.id === step.id) >= position))
}
