import { describe, expect, it } from 'vitest'
import { COMMAND_TOKEN_SLOT, splitCommandPreview } from './commandPreview'
import { MCP_FREE_QUOTA, MCP_MEMBER_QUOTA, buildDshInstallLine, dshPatchLines } from './dshPlugin'

describe('dshPlugin', () => {
  it('matches the mcp-go quota defaults', () => {
    expect(MCP_MEMBER_QUOTA).toEqual({ rolling24h: 200, rolling30d: 8000 })
    expect(MCP_FREE_QUOTA).toEqual({ rolling24h: 10, rolling30d: 400 })
  })

  it('writes one patch item that replaces the plugin config with the token', () => {
    expect(dshPatchLines("aigc_mcp_ab'cd")).toEqual([
      '- replace:',
      '    - id: aigc-radar',
      '      name: dsh-aigc-radar',
      '      config:',
      "        mcpToken: 'aigc_mcp_ab''cd'",
    ])
  })

  it('folds the token patch into the install command with safe quoting', () => {
    const line = buildDshInstallLine('dsh plugin --profile web add dsh-aigc-radar', "aigc_mcp_ab'cd")

    expect(line.startsWith('dsh plugin --profile web add dsh-aigc-radar && printf ')).toBe(true)
    expect(line).toContain('"        mcpToken: \'aigc_mcp_ab\'\'cd\'"')
    expect(line.endsWith('> ~/.dsh/profiles/web/cordis.patch.yml')).toBe(true)
  })

  it('keeps the preview slot whole so the page can draw it as one placeholder', () => {
    const segments = splitCommandPreview(buildDshInstallLine('dsh plugin --profile web add dsh-aigc-radar', COMMAND_TOKEN_SLOT))

    expect(segments.filter((segment) => segment.kind === 'token')).toHaveLength(1)
    expect(segments.map((segment) => (segment.kind === 'text' ? segment.text : '')).join('')).not.toContain(COMMAND_TOKEN_SLOT)
  })
})
