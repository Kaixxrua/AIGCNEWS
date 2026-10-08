import type { McpClientOption, McpSetupScope, McpShellId } from './mcpClientCatalog'
import type { McpFeedbackTranslator } from './mcpFeedback'
import type { McpAuthMode } from './mcpOAuth'

/* 接入命令写到哪、写完怎么验证：手机上的三步向导与桌面上的接入命令台共用这几句说明。
   浏览器授权版（mode 'oauth'）的说明在 mcpOAuthSetup.*，由 installMcpOAuthSetupMessages 注入。 */

const SETUP_SCOPE_KEYS: Record<McpSetupScope, string> = {
  user: 'user',
  'conditional-user': 'conditionalUser',
  'user-with-session-secret': 'sessionSecret',
  'import-file': 'importFile',
}

export const setupScopeLabel = (option: McpClientOption, t: McpFeedbackTranslator, mode: McpAuthMode = 'token') => {
  // 浏览器授权版的 Codex 不在终端里放密钥，Token 由 Codex 自己保存：就是普通的用户级配置
  const scope = mode === 'oauth' && option.setupScope === 'user-with-session-secret' ? 'user' : option.setupScope
  return t(`mcp.scope.${SETUP_SCOPE_KEYS[scope]}`)
}

/** 客户端标签上的一句说明：Codex、OpenCode 的 Token 版说明讲的是密钥和 Header，浏览器授权版换一句。 */
export const clientDescription = (option: McpClientOption, t: McpFeedbackTranslator, mode: McpAuthMode = 'token') => (
  mode === 'oauth' && (option.id === 'codex' || option.id === 'opencode')
    ? t(`mcpOAuthSetup.clients.${option.id}`)
    : t(option.descriptionKey)
)

export const clientConfigTarget = (option: McpClientOption, t: McpFeedbackTranslator) => (option.configPathKey ? t(option.configPathKey) : option.configPath)

export const setupTargetDescription = (option: McpClientOption, shell: McpShellId, t: McpFeedbackTranslator, mode: McpAuthMode = 'token') => {
  if (mode === 'oauth' && (option.id === 'claude-code' || option.id === 'codex')) return t(`mcpOAuthSetup.result.${option.id}`)
  if (option.id === 'claude-code') return t('mcp.resultClaudeCode')
  if (option.id === 'continue') return t('mcp.resultContinue', { path: clientConfigTarget(option, t) })
  if (option.id === 'vscode') return t('mcp.resultVsCode')
  if (option.id === 'codex') return shell === 'bash'
    ? t('mcp.codexResult')
    : t('mcp.resultCodexWindows')
  return t('mcp.resultImport', { path: clientConfigTarget(option, t) })
}

export const setupResultDescription = (option: McpClientOption, t: McpFeedbackTranslator, mode: McpAuthMode = 'token') => {
  if (mode === 'oauth' && option.oauth) return t(`mcpOAuthSetup.hint.${option.id}`, { path: clientConfigTarget(option, t) })
  if (option.id === 'claude-code') return t('mcp.hintClaudeCode')
  if (option.id === 'continue') return t('mcp.hintContinue')
  if (option.id === 'vscode') return t('mcp.hintVsCode')
  if (option.id === 'codex') return t('mcp.hintCodex')
  return t('mcp.hintImport', { path: clientConfigTarget(option, t) })
}
