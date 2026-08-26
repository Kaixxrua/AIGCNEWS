import { describe, expect, it } from 'vitest'
import {
  DEFAULT_MONITOR_SECTION,
  MONITOR_NAV,
  MCP_TEST_SCOPE,
  SOURCE_LIST,
  getMcpAuthPresentation,
  getMcpTransportPresentation,
  getStatusConfig,
  normalizeMonitorSection,
  toMcpToolCallRows,
} from './monitorViewModel'

describe('monitor presentation localization boundary', () => {
  it('exposes stable translation keys for frontend-owned labels', () => {
    expect(MCP_TEST_SCOPE.map(item => item.descriptionKey)).toEqual([
      'initialize', 'initialized', 'tools',
    ])
    expect(getStatusConfig('success')).toMatchObject({ labelKey: 'success', rawLabel: '' })
    expect(getStatusConfig('unexpected')).toMatchObject({ labelKey: '', rawLabel: 'unexpected' })
    expect(SOURCE_LIST.map(source => [source.key, source.labelKey])).toEqual([
      ['arxiv', 'arxiv'],
      ['github', 'github'],
      ['hackernews', 'hackernews'],
      ['producthunt', 'producthunt'],
      ['news', 'news'],
      ['x', 'x'],
    ])
  })

  it('preserves known protocol labels and unknown backend codes', () => {
    expect(getMcpTransportPresentation('streamable_http')).toEqual({ label: 'Streamable HTTP', labelKey: '' })
    expect(getMcpTransportPresentation('custom')).toEqual({ label: 'custom', labelKey: '' })
    expect(getMcpTransportPresentation('')).toEqual({ label: '', labelKey: 'unknownTransport' })
    expect(getMcpAuthPresentation('bearer')).toEqual({ label: 'Bearer Token', labelKey: '' })
    expect(getMcpAuthPresentation('none')).toEqual({ label: '', labelKey: 'noAuth' })
    expect(getMcpAuthPresentation('custom')).toEqual({ label: 'custom', labelKey: '' })
  })

  it('maps tool-call snapshots to rows sorted by calls desc then name', () => {
    expect(toMcpToolCallRows(null)).toEqual([])
    expect(toMcpToolCallRows({ tools: {} })).toEqual([])
    expect(toMcpToolCallRows({
      tools: {
        search_papers: { calls: 2, last_called_at: '2026-08-04T02:00:00+00:00' },
        get_project_categories: { calls: 5, last_called_at: '2026-08-04T01:00:00+00:00' },
        get_top_items: { calls: 5, last_called_at: '' },
      },
    })).toEqual([
      { name: 'get_project_categories', calls: 5, lastCalledAt: '2026-08-04T01:00:00+00:00' },
      { name: 'get_top_items', calls: 5, lastCalledAt: null },
      { name: 'search_papers', calls: 2, lastCalledAt: '2026-08-04T02:00:00+00:00' },
    ])
  })

  it('exposes stable two-level nav metadata for the monitor secondary nav', () => {
    expect(MONITOR_NAV.map(category => [category.key, category.labelKey])).toEqual([
      ['monitor', 'monitor.nav.group.monitor'],
      ['ingestion', 'monitor.nav.group.ingestion'],
      ['accounts', 'monitor.nav.group.accounts'],
      ['config', 'monitor.nav.group.config'],
      ['site', 'monitor.nav.group.site'],
    ])
    expect(MONITOR_NAV.flatMap(category => category.children.map(leaf => [leaf.key, leaf.labelKey, leaf.adminOnly]))).toEqual([
      ['tasks', 'monitor.nav.tasks', false],
      ['mcp-calls', 'monitor.nav.mcpCalls', false],
      ['errors', 'monitor.nav.errors', true],
      ['visit-stats', 'monitor.nav.visitStats', true],
      ['collect', 'monitor.nav.collect', true],
      ['crawl', 'monitor.nav.crawl', true],
      ['enrichment', 'monitor.nav.enrichment', true],
      ['x-watch', 'monitor.nav.xWatch', true],
      ['x-credentials', 'monitor.nav.xCredentials', true],
      ['wechat', 'monitor.nav.wechat', true],
      ['provider', 'monitor.nav.provider', true],
      ['scheduler', 'monitor.nav.scheduler', true],
      ['smtp', 'monitor.nav.smtp', true],
      ['mcp-server', 'monitor.nav.mcpServer', true],
      ['oauth-config', 'monitor.nav.oauthConfig', true],
      ['telegram-push', 'monitor.nav.telegramPush', true],
      ['contact-page', 'monitor.nav.contactPage', true],
      ['membership', 'monitor.nav.membership', true],
      ['user-stats', 'monitor.nav.userStats', true],
      ['payment-config', 'monitor.nav.paymentConfig', true],
      ['payment-orders', 'monitor.nav.paymentOrders', true],
    ])
    expect(DEFAULT_MONITOR_SECTION).toBe('tasks')
    expect(MONITOR_NAV.every(category => Boolean(category.icon))).toBe(true)
  })

  it('normalizes unknown or malformed section query values to the default', () => {
    expect(normalizeMonitorSection('enrichment')).toBe('enrichment')
    expect(normalizeMonitorSection('mcp-server')).toBe('mcp-server')
    expect(normalizeMonitorSection('oauth-config')).toBe('oauth-config')
    expect(normalizeMonitorSection('telegram-push')).toBe('telegram-push')
    expect(normalizeMonitorSection('')).toBe('tasks')
    expect(normalizeMonitorSection(undefined)).toBe('tasks')
    expect(normalizeMonitorSection(null)).toBe('tasks')
    expect(normalizeMonitorSection('bogus')).toBe('tasks')
    // 扁平分组时代的旧 key 已失效，回落默认
    expect(normalizeMonitorSection('status')).toBe('tasks')
    // 大小写敏感，白名单精确匹配
    expect(normalizeMonitorSection(' Enrichment ')).toBe('tasks')
    // vue-router 重复参数（string[]）取第一个
    expect(normalizeMonitorSection(['scheduler'])).toBe('scheduler')
    expect(normalizeMonitorSection(['bogus'])).toBe('tasks')
  })
})
