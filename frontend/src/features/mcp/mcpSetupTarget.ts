import type { McpClientOption, McpSetupScope, McpShellId } from './mcpClientCatalog'
import type { McpFeedbackTranslator } from './mcpFeedback'

/* 接入命令写到哪、写完怎么验证：手机上的三步向导与桌面上的接入命令台共用这几句说明。 */

const SETUP_SCOPE_KEYS: Record<McpSetupScope, string> = {
  user: 'user',
  'conditional-user': 'conditionalUser',
  'user-with-session-secret': 'sessionSecret',
  'import-file': 'importFile',
}

export const setupScopeLabel = (option: McpClientOption, t: McpFeedbackTranslator) => t(`mcp.scope.${SETUP_SCOPE_KEYS[option.setupScope]}`)

export const clientConfigTarget = (option: McpClientOption, t: McpFeedbackTranslator) => (option.configPathKey ? t(option.configPathKey) : option.configPath)

export const setupTargetDescription = (option: McpClientOption, shell: McpShellId, t: McpFeedbackTranslator) => {
  if (option.id === 'claude-code') return t('mcp.resultClaudeCode')
  if (option.id === 'continue') return t('mcp.resultContinue', { path: clientConfigTarget(option, t) })
  if (option.id === 'vscode') return t('mcp.resultVsCode')
  if (option.id === 'codex') return shell === 'bash'
    ? t('mcp.codexResult')
    : t('mcp.resultCodexWindows')
  return t('mcp.resultImport', { path: clientConfigTarget(option, t) })
}

export const setupResultDescription = (option: McpClientOption, t: McpFeedbackTranslator) => {
  if (option.id === 'claude-code') return t('mcp.hintClaudeCode')
  if (option.id === 'continue') return t('mcp.hintContinue')
  if (option.id === 'vscode') return t('mcp.hintVsCode')
  if (option.id === 'codex') return t('mcp.hintCodex')
  return t('mcp.hintImport', { path: clientConfigTarget(option, t) })
}
