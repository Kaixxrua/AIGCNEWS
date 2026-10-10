import { describe, expect, it } from 'vitest'
import { COMMAND_TOKEN_SLOT, splitCommandPreview } from './commandPreview'
import { buildManualMcpConfig, manualMcpEndpoint } from './manualMcpConfig'

describe('manual MCP configuration', () => {
  it('points at the entry the page was opened from', () => {
    expect(manualMcpEndpoint('https://aigcnews.cn')).toBe('https://aigcnews.cn/api/mcp')
    expect(manualMcpEndpoint('https://aigcradar.online/')).toBe('https://aigcradar.online/api/mcp')
  })

  it('writes one aigc-news server with the token as a bearer header', () => {
    const config = JSON.parse(buildManualMcpConfig('https://aigcnews.cn/api/mcp', 'aigc_mcp_example'))

    expect(config).toEqual({
      mcpServers: {
        'aigc-news': {
          type: 'http',
          url: 'https://aigcnews.cn/api/mcp',
          headers: { Authorization: 'Bearer aigc_mcp_example' },
        },
      },
    })
  })

  it('previews with a single slot where the token goes', () => {
    const segments = splitCommandPreview(buildManualMcpConfig('https://aigcnews.cn/api/mcp', COMMAND_TOKEN_SLOT))

    expect(segments.filter((segment) => segment.kind === 'token')).toHaveLength(1)
  })
})
