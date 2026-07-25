import { describe, expect, it } from 'vitest'
import {
  generateMcpClientCommand,
  mcpClientOptions,
  type McpShellId,
} from './mcpClientConfig'

const shells: McpShellId[] = ['powershell', 'cmd', 'bash']
const endpoint = 'https://example.test/a path/符号?value=$&|;'
const sentinelToken = 'sentinel token-$&|;令牌'

function decodePowerShellCommand(command: string): string {
  const parts = command.split(' ')
  const encoded = parts[parts.length - 1]!
  const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0))
  return new TextDecoder('utf-16le').decode(bytes)
}

describe('MCP client configuration security contract', () => {
  it('keeps the nine-client catalog stable', () => {
    expect(mcpClientOptions.map(({ id, format, configPath }) => ({ id, format, configPath }))).toEqual([
      { id: 'claude-code', format: 'claude-cli', configPath: 'Terminal' },
      { id: 'cursor', format: 'mcp-servers', configPath: '.cursor/aigc-news.mcp.import.json' },
      { id: 'codex', format: 'codex-cli', configPath: '~/.codex/config.toml' },
      { id: 'opencode', format: 'opencode-remote', configPath: 'aigc-news.opencode.import.json' },
      { id: 'cline-roo', format: 'mcp-servers', configPath: 'aigc-news.cline-roo.mcp.json' },
      { id: 'continue', format: 'mcp-servers', configPath: 'aigc-news.continue.mcp.json' },
      { id: 'windsurf', format: 'mcp-servers', configPath: 'aigc-news.windsurf.mcp.json' },
      { id: 'vscode', format: 'vscode-servers', configPath: 'aigc-news.vscode.mcp.json' },
      { id: 'generic-json', format: 'mcp-servers', configPath: 'aigc-news.mcp.json' },
    ])
  })

  it.each(mcpClientOptions.flatMap((client) => shells.map((shell) => [client, shell] as const)))(
    'generates an authenticated, one-shot %s command for %s',
    (client, shell) => {
      const command = generateMcpClientCommand(client, endpoint, sentinelToken, shell)
      const inspectable = shell === 'cmd' && client.id !== 'codex'
        ? decodePowerShellCommand(command)
        : command

      expect(inspectable).toContain('aigc-news')
      expect(inspectable).toContain(endpoint)
      if (client.id === 'codex') {
        expect(inspectable).toContain('AIGC_NEWS_MCP_TOKEN')
        expect(inspectable).toContain('--bearer-token-env-var AIGC_NEWS_MCP_TOKEN')
      } else {
        expect(inspectable).toContain(sentinelToken)
        expect(inspectable).toContain('Authorization')
        expect(inspectable).toContain('Bearer')
      }

      if (!['claude-code', 'codex'].includes(client.id)) {
        expect(inspectable).toContain(client.configPath)
        expect(inspectable).toContain(JSON.stringify(endpoint).slice(1, -1))
        expect(inspectable).toContain(JSON.stringify(sentinelToken).slice(1, -1))
        if (shell !== 'bash') {
          expect(inspectable).toContain('System.Text.UTF8Encoding($false)')
        }
      }
    },
  )

  it('preserves exact Claude Code quoting for all three shells', () => {
    const option = mcpClientOptions[0]!
    expect(generateMcpClientCommand(option, 'https://mcp.test/api', 'tok en', 'bash')).toBe(
      "claude mcp remove --scope user aigc-news 2>/dev/null; claude mcp add --scope user --transport http aigc-news 'https://mcp.test/api' --header 'Authorization: Bearer tok en'",
    )
    expect(generateMcpClientCommand(option, 'https://mcp.test/api', "tok'en", 'powershell')).toBe(
      "$claudeCommand = Get-Command claude.exe, claude.cmd -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $claudeCommand) { throw 'Claude Code executable not found. Install Claude Code and reopen the terminal.' }; & $claudeCommand.Source mcp remove --scope user aigc-news 2>$null; & $claudeCommand.Source mcp add --scope user --transport http aigc-news 'https://mcp.test/api' --header 'Authorization: Bearer tok''en'",
    )
    expect(decodePowerShellCommand(generateMcpClientCommand(option, 'https://mcp.test/api', '令牌', 'cmd'))).toBe(
      "$claudeCommand = Get-Command claude.exe, claude.cmd -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $claudeCommand) { throw 'Claude Code executable not found. Install Claude Code and reopen the terminal.' }; & $claudeCommand.Source mcp remove --scope user aigc-news 2>$null; & $claudeCommand.Source mcp add --scope user --transport http aigc-news 'https://mcp.test/api' --header 'Authorization: Bearer 令牌'",
    )
  })

  it('does not expose the token outside the returned transient command', () => {
    const consoleCalls: unknown[][] = []
    const storageWrites: unknown[][] = []
    const originalLog = console.log
    const originalLocalSet = Storage.prototype.setItem
    console.log = (...args: unknown[]) => { consoleCalls.push(args) }
    Storage.prototype.setItem = function (...args: [string, string]) { storageWrites.push(args) }
    try {
      generateMcpClientCommand(mcpClientOptions[0]!, endpoint, sentinelToken, 'bash')
      expect(JSON.stringify(consoleCalls)).not.toContain(sentinelToken)
      expect(JSON.stringify(storageWrites)).not.toContain(sentinelToken)
      expect(document.body.textContent).not.toContain(sentinelToken)
    } finally {
      console.log = originalLog
      Storage.prototype.setItem = originalLocalSet
    }
  })
})
