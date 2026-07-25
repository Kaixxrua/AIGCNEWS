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
