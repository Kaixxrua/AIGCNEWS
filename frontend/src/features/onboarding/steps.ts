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

// Keep the current section on resize/resume, or advance past desktop-only steps.
export function resumeStepIndex(steps: readonly TourStep[], id?: string): number {
  const position = TOUR_STEPS.findIndex(step => step.id === id)
  return Math.max(0, steps.findIndex(step => TOUR_STEPS.findIndex(item => item.id === step.id) >= position))
}
