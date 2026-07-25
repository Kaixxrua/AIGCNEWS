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

export type McpClientFormat = 'claude-cli' | 'codex-cli' | 'continue-yaml' | 'mcp-servers' | 'opencode-remote' | 'vscode-cli'
export type McpSetupScope = 'user' | 'conditional-user' | 'user-with-session-secret' | 'import-file'

export interface McpClientOption {
  id: McpClientId
  label: string
  apiType: 'claude' | 'cursor' | 'vscode' | 'other'
  description: string
  configPath: string
  format: McpClientFormat
  setupScope: McpSetupScope
}

export const mcpClientOptions: McpClientOption[] = [
  { id: 'claude-code', label: 'Claude Code', apiType: 'claude', description: '注册到 Claude Code 用户级 MCP 配置。', configPath: 'Claude Code 用户配置', format: 'claude-cli', setupScope: 'user' },
  { id: 'cursor', label: 'Cursor', apiType: 'cursor', description: '生成独立导入文件，不覆盖已有 .cursor/mcp.json。', configPath: '.cursor/aigc-news.mcp.import.json', format: 'mcp-servers', setupScope: 'import-file' },
  { id: 'codex', label: 'Codex', apiType: 'other', description: '注册到用户配置；Bash / zsh 密钥仅当前终端有效。', configPath: '~/.codex/config.toml', format: 'codex-cli', setupScope: 'user-with-session-secret' },
  { id: 'opencode', label: 'OpenCode', apiType: 'other', description: '生成带 Bearer Header 的 remote MCP 导入文件。', configPath: 'aigc-news.opencode.import.json', format: 'opencode-remote', setupScope: 'import-file' },
  { id: 'cline-roo', label: 'Cline / Roo Code', apiType: 'other', description: '生成兼容 mcpServers 的安全导入文件。', configPath: 'aigc-news.cline-roo.mcp.json', format: 'mcp-servers', setupScope: 'import-file' },
  { id: 'continue', label: 'Continue', apiType: 'other', description: '创建用户级独立 MCP 文件；已有同名文件时拒绝覆盖。', configPath: '~/.continue/mcpServers/aigc-news.yaml', format: 'continue-yaml', setupScope: 'user' },
  { id: 'windsurf', label: 'Windsurf', apiType: 'other', description: '生成带认证 Header 的 MCP 导入文件。', configPath: 'aigc-news.windsurf.mcp.json', format: 'mcp-servers', setupScope: 'import-file' },
  { id: 'vscode', label: 'VS Code', apiType: 'vscode', description: '支持时注册到 VS Code 默认用户 Profile；同名配置需确认替换。', configPath: 'VS Code 默认用户 Profile', format: 'vscode-cli', setupScope: 'conditional-user' },
  { id: 'generic-json', label: '其他客户端', apiType: 'other', description: '生成带 headers 的标准 mcpServers JSON。', configPath: 'aigc-news.mcp.json', format: 'mcp-servers', setupScope: 'import-file' },
]
