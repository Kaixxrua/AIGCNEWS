import { describe, expect, it } from 'vitest'
import { messages } from '@/i18n'
import {
  MCP_EMPTY_STATE_EXAMPLE_IDS,
  MCP_EXAMPLE_PROMPTS,
  MCP_PAGE_EXAMPLE_IDS,
  MCP_PROMO_DISMISSED_STORAGE_KEY,
  MCP_PROMO_EXAMPLE_IDS,
  mcpExamplesByIds,
} from './mcpExamplePrompts'
import { PUBLIC_TOOLS } from './publicToolsModel'

const publicToolNames = new Set(PUBLIC_TOOLS.map((tool) => tool.name))

const resolveMessage = (catalog: unknown, path: string): unknown =>
  path.split('.').reduce<unknown>((node, key) => (
    node && typeof node === 'object' ? (node as Record<string, unknown>)[key] : undefined
  ), catalog)

describe('mcpExamplePrompts catalog', () => {
  it('defines a unique id for every example', () => {
    const ids = MCP_EXAMPLE_PROMPTS.map((example) => example.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('tags every example with a real public MCP tool', () => {
    for (const example of MCP_EXAMPLE_PROMPTS) {
      expect(example.toolTag, example.id).toBeDefined()
      expect(publicToolNames.has(example.toolTag as string), example.id).toBe(true)
    }
  })

  it('resolves every promptKey to a string in both locales', () => {
    for (const example of MCP_EXAMPLE_PROMPTS) {
      expect(typeof resolveMessage(messages['en-US'], example.promptKey), `en-US ${example.promptKey}`).toBe('string')
      expect(typeof resolveMessage(messages['zh-CN'], example.promptKey), `zh-CN ${example.promptKey}`).toBe('string')
    }
  })

  it('keeps every placement subset within the catalog', () => {
    const ids = new Set(MCP_EXAMPLE_PROMPTS.map((example) => example.id))
    for (const subset of [MCP_PROMO_EXAMPLE_IDS, MCP_EMPTY_STATE_EXAMPLE_IDS, MCP_PAGE_EXAMPLE_IDS]) {
      for (const id of subset) expect(ids.has(id), id).toBe(true)
    }
  })

  it('guarantees every empty-state example can run an in-site demo', () => {
    for (const example of mcpExamplesByIds(MCP_EMPTY_STATE_EXAMPLE_IDS)) {
      expect(example.demoQuery, example.id).toBeTruthy()
    }
  })

  it('lists every example on the /mcp page', () => {
    expect(MCP_PAGE_EXAMPLE_IDS).toEqual(MCP_EXAMPLE_PROMPTS.map((example) => example.id))
  })

  it('resolves ids in the requested order and drops unknown ids', () => {
    const resolved = mcpExamplesByIds(['agent-frameworks', 'missing-id', 'rag-frameworks'])
    expect(resolved.map((example) => example.id)).toEqual(['agent-frameworks', 'rag-frameworks'])
  })

  it('exposes a stable dismissed storage key', () => {
    expect(MCP_PROMO_DISMISSED_STORAGE_KEY).toBe('aigcnews:mcp-promo-dismissed')
  })
})
