import { describe, expect, it } from 'vitest'
import {
  MCP_TEST_SCOPE,
  SOURCE_LIST,
  getMcpAuthPresentation,
  getMcpTransportPresentation,
  getStatusConfig,
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
})
