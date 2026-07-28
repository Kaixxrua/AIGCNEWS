import { describe, expect, it } from 'vitest'
import {
  feedbackKey,
  feedbackLiteral,
  resolveMcpFeedback,
} from './mcpFeedback'

describe('MCP feedback localization boundary', () => {
  it('resolves semantic feedback with the current translator', () => {
    const feedback = feedbackKey('mcp.toolCount', { count: 2 })
    expect(resolveMcpFeedback(feedback, (key, params) => `EN:${key}:${params?.count}`))
      .toBe('EN:mcp.toolCount:2')
    expect(resolveMcpFeedback(feedback, (key, params) => `ZH:${key}:${params?.count}`))
      .toBe('ZH:mcp.toolCount:2')
  })

  it('preserves unknown backend details verbatim', () => {
    const feedback = feedbackLiteral('upstream diagnostic: E_CONN_RESET')
    expect(resolveMcpFeedback(feedback, () => 'translated'))
      .toBe('upstream diagnostic: E_CONN_RESET')
  })
})
