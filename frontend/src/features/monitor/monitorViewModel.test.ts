import { describe, expect, it } from 'vitest'
import {
  DEFAULT_MONITOR_SECTION,
  MCP_TEST_SCOPE,
  MONITOR_SECTIONS,
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

  it('exposes stable section metadata for the monitor secondary nav', () => {
    expect(MONITOR_SECTIONS.map(section => [section.key, section.labelKey, section.adminOnly])).toEqual([
      ['status', 'monitor.nav.status', false],
      ['ingestion', 'monitor.nav.ingestion', true],
      ['github', 'monitor.nav.github', true],
      ['settings', 'monitor.nav.settings', true],
    ])
    expect(DEFAULT_MONITOR_SECTION).toBe('status')
    expect(MONITOR_SECTIONS.every(section => Boolean(section.icon))).toBe(true)
  })

  it('normalizes unknown or malformed section query values to the default', () => {
    expect(normalizeMonitorSection('github')).toBe('github')
    expect(normalizeMonitorSection('ingestion')).toBe('ingestion')
    expect(normalizeMonitorSection('')).toBe('status')
    expect(normalizeMonitorSection(undefined)).toBe('status')
    expect(normalizeMonitorSection(null)).toBe('status')
    expect(normalizeMonitorSection('bogus')).toBe('status')
    // 大小写敏感，白名单精确匹配
    expect(normalizeMonitorSection(' GitHub ')).toBe('status')
    // vue-router 重复参数（string[]）取第一个
    expect(normalizeMonitorSection(['settings'])).toBe('settings')
    expect(normalizeMonitorSection(['bogus'])).toBe('status')
  })
})
