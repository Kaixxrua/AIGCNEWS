export type McpShellId = 'powershell' | 'cmd' | 'bash'
export type McpClientId =
  | 'claude-code'
  | 'cursor'
  | 'codex'
  | 'opencode'
  | 'cline-roo'
  | 'continue'
  | 'windsurf'
  | 'vscode'
  | 'generic-json'

export type McpClientFormat = 'claude-cli' | 'codex-cli' | 'mcp-servers' | 'opencode-remote' | 'vscode-servers'

export interface McpClientOption {
  id: McpClientId
  label: string
  apiType: 'claude' | 'cursor' | 'vscode' | 'other'
  description: string
  configPath: string
  format: McpClientFormat
}

const MCP_SERVER_KEY = 'aigc-news'
const CODEX_TOKEN_ENV = 'AIGC_NEWS_MCP_TOKEN'

export const mcpClientOptions: McpClientOption[] = [
  { id: 'claude-code', label: 'Claude Code', apiType: 'claude', description: '使用 HTTP MCP 和 Authorization Header 一键接入。', configPath: 'Terminal', format: 'claude-cli' },
  { id: 'cursor', label: 'Cursor', apiType: 'cursor', description: '生成独立导入文件，不覆盖已有 .cursor/mcp.json。', configPath: '.cursor/aigc-news.mcp.import.json', format: 'mcp-servers' },
  { id: 'codex', label: 'Codex', apiType: 'other', description: '通过 bearer_token_env_var 连接，Token 不写入 Codex TOML。', configPath: '~/.codex/config.toml', format: 'codex-cli' },
  { id: 'opencode', label: 'OpenCode', apiType: 'other', description: '生成带 Bearer Header 的 remote MCP 导入文件。', configPath: 'aigc-news.opencode.import.json', format: 'opencode-remote' },
  { id: 'cline-roo', label: 'Cline / Roo Code', apiType: 'other', description: '生成兼容 mcpServers 的安全导入文件。', configPath: 'aigc-news.cline-roo.mcp.json', format: 'mcp-servers' },
  { id: 'continue', label: 'Continue', apiType: 'other', description: '生成独立 MCP 导入文件，避免覆盖现有 Continue 配置。', configPath: 'aigc-news.continue.mcp.json', format: 'mcp-servers' },
  { id: 'windsurf', label: 'Windsurf', apiType: 'other', description: '生成带认证 Header 的 MCP 导入文件。', configPath: 'aigc-news.windsurf.mcp.json', format: 'mcp-servers' },
  { id: 'vscode', label: 'VS Code', apiType: 'vscode', description: '生成 VS Code 使用的顶层 servers JSON。', configPath: 'aigc-news.vscode.mcp.json', format: 'vscode-servers' },
  { id: 'generic-json', label: '其他客户端', apiType: 'other', description: '生成带 headers 的标准 mcpServers JSON。', configPath: 'aigc-news.mcp.json', format: 'mcp-servers' },
]

function quote(value: string, shell: McpShellId): string {
  if (shell === 'bash') return `'${value.replace(/'/g, `'\\''`)}'`
  if (shell === 'powershell') return `"${value.replace(/`/g, '``').replace(/"/g, '`"')}"`
  return `"${value.replace(/"/g, '""')}"`
}

function quotePowerShellLiteral(value: string): string {
  return `'${value.replace(/'/g, "''")}'`
}

function encodePowerShellCommand(command: string): string {
  const bytes = new Uint8Array(command.length * 2)
  for (let index = 0; index < command.length; index += 1) {
    const code = command.charCodeAt(index)
    bytes[index * 2] = code & 0xff
    bytes[index * 2 + 1] = code >> 8
  }
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary)
}

function join(shell: McpShellId): string {
  return shell === 'cmd' ? ' & ' : '; '
}

function ignored(shell: McpShellId): string {
  if (shell === 'powershell') return '2>$null'
  return shell === 'cmd' ? '2>nul' : '2>/dev/null'
}

function parentDirectory(path: string): string {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
}

function powerShellWriteJsonScript(path: string, data: unknown): string {
  const directory = parentDirectory(path)
  const json = JSON.stringify(data)
  const mkdir = directory ? `New-Item -ItemType Directory -Force -Path ${quotePowerShellLiteral(directory)} | Out-Null` : ''
  const write = `Set-Content -Encoding UTF8 -Path ${quotePowerShellLiteral(path)} -Value ${quotePowerShellLiteral(json)}`
  return [mkdir, write].filter(Boolean).join('; ')
}

function writeJsonCommand(path: string, data: unknown, shell: McpShellId): string {
  const script = powerShellWriteJsonScript(path, data)
  if (shell === 'powershell') return script
  if (shell === 'cmd') return `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encodePowerShellCommand(script)}`

  const directory = parentDirectory(path)
  const mkdir = directory ? `mkdir -p ${quote(directory, shell)}` : ''
  const write = `printf '%s\\n' ${quote(JSON.stringify(data), shell)} > ${quote(path, shell)}`
  return [mkdir, write].filter(Boolean).join(join(shell))
}

function authenticatedServer(url: string, token: string) {
  return { type: 'http', url, headers: { Authorization: `Bearer ${token}` } }
}

function configFor(option: McpClientOption, url: string, token: string): unknown {
  if (option.format === 'vscode-servers') {
    return { servers: { [MCP_SERVER_KEY]: authenticatedServer(url, token) } }
  }
  if (option.format === 'opencode-remote') {
    return {
      $schema: 'https://opencode.ai/config.json',
      mcp: {
        [MCP_SERVER_KEY]: {
          type: 'remote',
          url,
          enabled: true,
          oauth: false,
          headers: { Authorization: `Bearer ${token}` },
        },
      },
    }
  }
  return { mcpServers: { [MCP_SERVER_KEY]: authenticatedServer(url, token) } }
}

function codexCommand(url: string, token: string, shell: McpShellId): string {
  const setToken = shell === 'powershell'
    ? `$env:${CODEX_TOKEN_ENV}=${quote(token, shell)}; [Environment]::SetEnvironmentVariable(${quotePowerShellLiteral(CODEX_TOKEN_ENV)}, ${quotePowerShellLiteral(token)}, 'User')`
    : shell === 'cmd'
      ? `set "${CODEX_TOKEN_ENV}=${token}" & setx ${CODEX_TOKEN_ENV} ${quote(token, shell)} >nul`
      : `export ${CODEX_TOKEN_ENV}=${quote(token, shell)}`
  const remove = `codex mcp remove ${MCP_SERVER_KEY} ${ignored(shell)}`
  const add = `codex mcp add ${MCP_SERVER_KEY} --url ${quote(url, shell)} --bearer-token-env-var ${CODEX_TOKEN_ENV}`
  return [setToken, remove, add].join(join(shell))
}

export function generateMcpClientCommand(option: McpClientOption, url: string, token: string, shell: McpShellId): string {
  if (option.format === 'claude-cli') {
    const executable = shell === 'bash' ? 'claude' : 'claude.cmd'
    return [
      `${executable} mcp remove ${MCP_SERVER_KEY} ${ignored(shell)}`,
      `${executable} mcp add --transport http ${MCP_SERVER_KEY} ${quote(url, shell)} --header ${quote(`Authorization: Bearer ${token}`, shell)}`,
    ].join(join(shell))
  }
  if (option.format === 'codex-cli') return codexCommand(url, token, shell)
  return writeJsonCommand(option.configPath, configFor(option, url, token), shell)
}
