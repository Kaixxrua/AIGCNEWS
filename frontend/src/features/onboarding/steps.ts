export interface TourStep {
  id: string
  route: string
  targets: readonly string[]
  feature?: 'x' | 'contact'
}

// Prefer the actual control, then a stable region on the same page. Empty data
// must not turn a tour into a wait for a particular project or paper to exist.
export const TOUR_STEPS: readonly TourStep[] = [
  { id: 'navigation', route: '/', targets: ['.dock'] },
  { id: 'home', route: '/', targets: ['.ranking-toolbar', '.dashboard-heading'] },
  { id: 'projects', route: '/projects', targets: ['.projects-search', '.projects-toolbar'] },
  { id: 'projectDetails', route: '/projects', targets: ['.project-chart__rows > :first-child', '.projects-grid > :first-child', '.projects-hero'] },
  { id: 'ui', route: '/ui-library', targets: ['.ui-library__command', '.ui-library__header'] },
  { id: 'uiPreview', route: '/ui-library', targets: ['.ui-library__grid > :first-child', '.ui-library__main'] },
  { id: 'websites', route: '/websites', targets: ['.website-content .website-header', '.recommended-websites-page'] },
  { id: 'myWebsites', route: '/projects?source=website', targets: ['.website-tabs a[href="/projects?source=website"]', '.projects-login-prompt', '.projects-website-add', '.projects-hero'] },
  { id: 'report', route: '/report', targets: ['.report-shell > .comic-panel', '.report-shell'] },
  { id: 'papers', route: '/report', targets: ['.report-reading'] },
  { id: 'subscribe', route: '/report', targets: ['[data-tour="subscribe"]', '.report-shell > .comic-panel'] },
  { id: 'x', route: '/x', targets: ['.xboard-header', '.xboard-page'], feature: 'x' },
  { id: 'mcp', route: '/mcp', targets: ['.mcp-desk-clients', '.mcp-connect-page .connection-intro'] },
  { id: 'mcpExamples', route: '/mcp', targets: ['.mcp-desk-verify', '.mcp-desk'] },
  { id: 'dsh', route: '/dsh', targets: ['.dsh-desk-head', '.dsh-page .connection-intro'] },
  { id: 'tracking', route: '/dsh', targets: ['[data-tour-nav="/subscriptions"]', '.dock'] },
  { id: 'membership', route: '/membership', targets: ['.tier-grid', '.membership-hero'] },
  { id: 'account', route: '/membership', targets: ['.dock-item--account'] },
  { id: 'search', route: '/membership', targets: ['.quick-search-button'] },
  { id: 'tools', route: '/membership', targets: ['.app-masthead__actions'] },
  { id: 'contact', route: '/contact', targets: ['.app-content .view-container'], feature: 'contact' },
  { id: 'footer', route: '/', targets: ['.footer-right', '.dock-footer'] },
  { id: 'help', route: '/', targets: ['[data-tour="help"]'] },
]

export function availableSteps(flags: { x: boolean; contact: boolean }): TourStep[] {
  return TOUR_STEPS.filter(step => !step.feature || flags[step.feature])
}
