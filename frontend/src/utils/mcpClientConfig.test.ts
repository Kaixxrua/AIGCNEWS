import { describe, expect, it } from 'vitest'
import {
  mcpClientOptions,
  type McpShellId,
} from '../features/mcp/mcpClientCatalog'
import { generateMcpClientCommand } from '../features/mcp/mcpCommandGenerator'

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
    expect(mcpClientOptions.map(({ id, format, configPath, setupScope }) => ({ id, format, configPath, setupScope }))).toEqual([
      { id: 'claude-code', format: 'claude-cli', configPath: 'Claude Code 用户配置', setupScope: 'user' },
      { id: 'cursor', format: 'mcp-servers', configPath: '.cursor/aigc-news.mcp.import.json', setupScope: 'import-file' },
      { id: 'codex', format: 'codex-cli', configPath: '~/.codex/config.toml', setupScope: 'user-with-session-secret' },
      { id: 'opencode', format: 'opencode-remote', configPath: 'aigc-news.opencode.import.json', setupScope: 'import-file' },
      { id: 'cline-roo', format: 'mcp-servers', configPath: 'aigc-news.cline-roo.mcp.json', setupScope: 'import-file' },
      { id: 'continue', format: 'continue-yaml', configPath: '~/.continue/mcpServers/aigc-news.yaml', setupScope: 'user' },
      { id: 'windsurf', format: 'mcp-servers', configPath: 'aigc-news.windsurf.mcp.json', setupScope: 'import-file' },
      { id: 'vscode', format: 'vscode-cli', configPath: 'VS Code 默认用户 Profile', setupScope: 'conditional-user' },
      { id: 'generic-json', format: 'mcp-servers', configPath: 'aigc-news.mcp.json', setupScope: 'import-file' },
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

      if (client.setupScope === 'import-file') {
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

  it('creates Continue user configuration without overwriting an existing file', () => {
    const option = mcpClientOptions.find((client) => client.id === 'continue')!
    for (const shell of shells) {
      const command = generateMcpClientCommand(option, endpoint, sentinelToken, shell)
      const inspectable = shell === 'cmd' ? decodePowerShellCommand(command) : command
      expect(inspectable).toContain('.continue/mcpServers/aigc-news.yaml')
      expect(inspectable).toContain('schema: v1')
      expect(inspectable).toContain('type: streamable-http')
      expect(inspectable).toContain(endpoint)
      expect(inspectable).toContain(sentinelToken)
      if (shell === 'bash') {
        expect(inspectable).toContain('$HOME/.continue/mcpServers')
        expect(inspectable).toContain('umask 077')
        expect(inspectable).toContain('mktemp')
        expect(inspectable).toContain('ln "$tmp" "$HOME/.continue/mcpServers/aigc-news.yaml"')
      } else {
        expect(inspectable).toContain('Join-Path $HOME')
        expect(inspectable).toContain('[System.IO.File]::WriteAllText($temporaryPath')
        expect(inspectable).toContain('[System.IO.File]::Move($temporaryPath, $outputPath)')
        expect(inspectable).toContain('System.Text.UTF8Encoding($false)')
      }
    }
  })

  it('registers VS Code only after checking user-profile CLI support', () => {
    const option = mcpClientOptions.find((client) => client.id === 'vscode')!
    for (const shell of shells) {
      const command = generateMcpClientCommand(option, endpoint, sentinelToken, shell)
      const inspectable = shell === 'cmd' ? decodePowerShellCommand(command) : command
      if (shell === 'bash') {
        expect(inspectable.startsWith('( ')).toBe(true)
        expect(inspectable.endsWith(' )')).toBe(true)
      }
      const capabilityCheck = shell === 'bash' ? inspectable.indexOf('code --help') : inspectable.indexOf('--help 2>&1')
      const registration = inspectable.lastIndexOf('--add-mcp')
      expect(capabilityCheck).toBeGreaterThanOrEqual(0)
      expect(registration).toBeGreaterThan(capabilityCheck)
      expect(inspectable).toContain('VS Code CLI does not support --add-mcp')
      expect(inspectable).toContain('This replaces an existing server with the same name')
      expect(inspectable).toContain(endpoint)
      expect(inspectable).toContain(sentinelToken)
      expect(inspectable).not.toContain('aigc-news.vscode.mcp.json')
      expect(inspectable).not.toContain('.vscode/mcp.json')
      expect(inspectable).not.toContain('WriteAllText')
    }
  })

  it('keeps Codex Bash authentication scoped to the current shell', () => {
    const option = mcpClientOptions.find((client) => client.id === 'codex')!
    const command = generateMcpClientCommand(option, endpoint, sentinelToken, 'bash')
    expect(command).toContain(`export AIGC_NEWS_MCP_TOKEN='${sentinelToken}'`)
    expect(command).toContain('--bearer-token-env-var AIGC_NEWS_MCP_TOKEN')
    expect(command).not.toContain('.bashrc')
    expect(command).not.toContain('.zshrc')
    expect(command).not.toContain('profile')
  })

  it('does not overwrite shared user config for import-file clients', () => {
    const forbiddenPaths = ['~/.cursor/mcp.json', '~/.config/opencode/opencode.json']
    for (const client of mcpClientOptions.filter((option) => option.setupScope === 'import-file')) {
      const command = generateMcpClientCommand(client, endpoint, sentinelToken, 'bash')
      expect(command).toContain(client.configPath)
      for (const path of forbiddenPaths) expect(command).not.toContain(path)
    }
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
