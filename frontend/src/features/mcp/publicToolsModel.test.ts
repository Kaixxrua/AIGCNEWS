import { describe, expect, it } from 'vitest'
import {
  displayedPublicTools,
  isActivePublicToolDiscovery,
  normalizePublicTools,
  PUBLIC_TOOLS,
  type PublicToolDiscoveryState,
} from './publicToolsModel'

const endpoint = 'https://example.test/api/mcp'

describe('public MCP tool display model', () => {
  it('provides the eight public tools with Chinese descriptions by default', () => {
    const tools = displayedPublicTools(endpoint, { status: 'idle', endpoint })

    expect(tools).toHaveLength(8)
    expect(tools.map((tool) => tool.name)).toEqual(PUBLIC_TOOLS.map((tool) => tool.name))
    expect(tools.every((tool) => /[㐀-鿿]/u.test(tool.description))).toBe(true)
  })

  it('replaces server descriptions for known tools with local Chinese copy', () => {
    const tools = normalizePublicTools([
      { name: 'search_papers', description: 'English server description' },
    ])

    expect(tools).toEqual([
      { name: 'search_papers', description: '检索公开 arXiv 论文与学术文献。' },
    ])
    expect(JSON.stringify(tools)).not.toContain('English server description')
  })

  it('uses a Chinese fallback for unknown tools without exposing server copy', () => {
    const tools = normalizePublicTools([
      { name: 'future_public_tool', description: 'English future tool' },
    ])

    expect(tools).toEqual([
      { name: 'future_public_tool', description: '该端点提供的公开 MCP 工具。' },
    ])
    expect(JSON.stringify(tools)).not.toContain('English future tool')
  })

  it('ignores invalid and duplicate tool names while preserving first-seen order', () => {
    const tools = normalizePublicTools([
      null,
      {},
      { name: 42 },
      { name: '   ' },
      { name: ' search_papers ', description: 'English' },
      { name: 'future_tool', description: 'English' },
      { name: 'search_papers', description: 'Duplicate' },
    ])

    expect(tools.map((tool) => tool.name)).toEqual(['search_papers', 'future_tool'])
  })

  it('preserves a successful empty tools list instead of restoring defaults', () => {
    const state: PublicToolDiscoveryState = { status: 'success', endpoint, runId: 1, tools: [] }

    expect(displayedPublicTools(endpoint, state)).toEqual([])
  })

  it('does not display results belonging to another endpoint', () => {
    const state: PublicToolDiscoveryState = {
      status: 'success',
      endpoint: 'https://old.example/api/mcp',
      runId: 1,
      tools: [{ name: 'old_tool', description: '旧工具' }],
    }

    expect(displayedPublicTools(endpoint, state)).toEqual(PUBLIC_TOOLS)
  })

  it('accepts writes only from the active endpoint and run', () => {
    const state: PublicToolDiscoveryState = { status: 'running', endpoint, runId: 2 }

    expect(isActivePublicToolDiscovery(endpoint, 2, state)).toBe(true)
    expect(isActivePublicToolDiscovery(endpoint, 1, state)).toBe(false)
    expect(isActivePublicToolDiscovery('https://other.example/api/mcp', 2, state)).toBe(false)
    expect(isActivePublicToolDiscovery(endpoint, 2, { status: 'error', endpoint, runId: 2 })).toBe(false)
  })
})
