import { describe, expect, it } from 'vitest'
import { buildDshAgentPrompt } from './agentSetupPrompt'
import { COMMAND_TOKEN_SLOT, splitCommandPreview, type CommandSegment } from './commandPreview'
import { DSH_PLUGIN_INSTALL_METHODS, buildDshInstallLine } from './dshPlugin'
import { buildManualMcpConfig } from './manualMcpConfig'

const visibleText = (segments: CommandSegment[]) => segments.map((segment) => (segment.kind === 'text' ? segment.text : '')).join('')

describe('splitCommandPreview', () => {
  it('cuts every occurrence of the slot into a token segment', () => {
    expect(splitCommandPreview('a SLOT b SLOT', 'SLOT')).toEqual([
      { kind: 'text', text: 'a ' },
      { kind: 'token' },
      { kind: 'text', text: ' b ' },
      { kind: 'token' },
    ])
  })

  it('leaves a command without a slot as one text segment', () => {
    expect(splitCommandPreview('dsh plugin add dsh-aigc-radar')).toEqual([{ kind: 'text', text: 'dsh plugin add dsh-aigc-radar' }])
  })

  // 页面上的三种预览：带 Token 的地方只剩占位，占位串本身不会漏成页面上的文字。
  const previews = [
    ...DSH_PLUGIN_INSTALL_METHODS.map((method) => [`dsh install (${method.id})`, buildDshInstallLine(method.command, COMMAND_TOKEN_SLOT)] as const),
    ['manual MCP config', buildManualMcpConfig('https://aigcnews.cn/api/mcp', COMMAND_TOKEN_SLOT)] as const,
    ['dsh agent prompt (zh)', buildDshAgentPrompt('zh-CN', COMMAND_TOKEN_SLOT)] as const,
    ['dsh agent prompt (en)', buildDshAgentPrompt('en-US', COMMAND_TOKEN_SLOT)] as const,
  ]

  it.each(previews)('%s shows the token only as one slot', (_name, text) => {
    const segments = splitCommandPreview(text)

    expect(segments.filter((segment) => segment.kind === 'token')).toHaveLength(1)
    expect(visibleText(segments)).not.toContain(COMMAND_TOKEN_SLOT)
  })
})
