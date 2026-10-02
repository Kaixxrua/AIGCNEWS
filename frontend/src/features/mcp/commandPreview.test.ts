import { describe, expect, it } from 'vitest'
import { COMMAND_TOKEN_SLOT, splitCommandPreview, type CommandSegment } from './commandPreview'
import { mcpClientOptions, mcpShellOptions } from './mcpClientCatalog'
import { generateMcpClientCommand } from './mcpCommandGenerator'

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

  it('replaces the base64 payload of -EncodedCommand with one encoded segment', () => {
    expect(splitCommandPreview('powershell -NoProfile -EncodedCommand QQBCAEMA= & echo done')).toEqual([
      { kind: 'text', text: 'powershell -NoProfile -EncodedCommand ' },
      { kind: 'encoded' },
      { kind: 'text', text: ' & echo done' },
    ])
  })

  it('leaves a command without a slot as one text segment', () => {
    expect(splitCommandPreview('dsh plugin add dsh-aigc-radar')).toEqual([{ kind: 'text', text: 'dsh plugin add dsh-aigc-radar' }])
  })

  // 每个客户端 × 每种终端：命令里总有 Token 占位或编码脚本占位，占位串和 base64 都不会漏成页面上的文字。
  const combinations = mcpClientOptions.flatMap((client) => mcpShellOptions.map((shell) => [client.id, shell.id] as const))

  it.each(combinations)('%s in %s shows the token only as a slot', (clientId, shellId) => {
    const client = mcpClientOptions.find((option) => option.id === clientId)!
    const segments = splitCommandPreview(generateMcpClientCommand(client, 'https://aigcnews.cn/api/mcp', COMMAND_TOKEN_SLOT, shellId))

    expect(segments.some((segment) => segment.kind !== 'text')).toBe(true)
    expect(visibleText(segments)).not.toContain(COMMAND_TOKEN_SLOT)
    expect(visibleText(segments)).not.toMatch(/-EncodedCommand\s+[A-Za-z0-9+/]/)
  })
})
