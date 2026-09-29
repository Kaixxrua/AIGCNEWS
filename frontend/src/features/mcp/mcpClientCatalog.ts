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
  labelKey?: string
  apiType: 'claude' | 'cursor' | 'vscode' | 'other'
  descriptionKey: string
  configPath: string
  configPathKey?: string
  format: McpClientFormat
  setupScope: McpSetupScope
}

export const mcpClientOptions: McpClientOption[] = [
  { id: 'claude-code', label: 'Claude Code', apiType: 'claude', descriptionKey: 'mcp.clients.claude-code.description', configPath: 'Claude Code 用户配置', configPathKey: 'mcp.clients.claude-code.target', format: 'claude-cli', setupScope: 'user' },
  { id: 'cursor', label: 'Cursor', apiType: 'cursor', descriptionKey: 'mcp.clients.cursor.description', configPath: '.cursor/aigc-news.mcp.import.json', format: 'mcp-servers', setupScope: 'import-file' },
  { id: 'codex', label: 'Codex', apiType: 'other', descriptionKey: 'mcp.clients.codex.description', configPath: '~/.codex/config.toml', format: 'codex-cli', setupScope: 'user-with-session-secret' },
  { id: 'opencode', label: 'OpenCode', apiType: 'other', descriptionKey: 'mcp.clients.opencode.description', configPath: 'aigc-news.opencode.import.json', format: 'opencode-remote', setupScope: 'import-file' },
  { id: 'cline-roo', label: 'Cline / Roo Code', apiType: 'other', descriptionKey: 'mcp.clients.cline-roo.description', configPath: 'aigc-news.cline-roo.mcp.json', format: 'mcp-servers', setupScope: 'import-file' },
  { id: 'continue', label: 'Continue', apiType: 'other', descriptionKey: 'mcp.clients.continue.description', configPath: '~/.continue/mcpServers/aigc-news.yaml', format: 'continue-yaml', setupScope: 'user' },
  { id: 'windsurf', label: 'Windsurf', apiType: 'other', descriptionKey: 'mcp.clients.windsurf.description', configPath: 'aigc-news.windsurf.mcp.json', format: 'mcp-servers', setupScope: 'import-file' },
  { id: 'vscode', label: 'VS Code', apiType: 'vscode', descriptionKey: 'mcp.clients.vscode.description', configPath: 'VS Code 默认用户 Profile', configPathKey: 'mcp.clients.vscode.target', format: 'vscode-cli', setupScope: 'conditional-user' },
  { id: 'generic-json', label: '其他客户端', labelKey: 'mcp.clients.generic-json.label', apiType: 'other', descriptionKey: 'mcp.clients.generic-json.description', configPath: 'aigc-news.mcp.json', format: 'mcp-servers', setupScope: 'import-file' },
]

/* 执行命令的终端与接入向导的三步：向导按它渲染，/mcp 桌面版的统计按它计数。 */
export const mcpShellOptions: { id: McpShellId; label: string; labelKey: string }[] = [
  { id: 'powershell', label: 'PowerShell', labelKey: '' },
  { id: 'cmd', label: '', labelKey: 'mcp.commandPrompt' },
  { id: 'bash', label: 'Bash / zsh', labelKey: '' },
]

export const mcpWizardStepTitleKeys = [
  'mcp.wizard.stepClient',
  'mcp.wizard.stepCommand',
  'mcp.wizard.stepVerify',
] as const
