/**
 * dsh 插件（dsh-aigc-radar）安装信息。
 *
 * 插件可直接从 npm 或 GitHub 安装，无需先登录网站；不配置 mcpToken 时，
 * 仍可通过 AIGC Radar 公共 MCP runtime 使用公开工具。网站 `/dsh` 页游客也能看，
 * 登录后复制的提示词（或手动安装命令）会把账号绑定的 DSH 专用 Token 写入 dsh web profile。
 */
export type DshPluginInstallMethodId = 'npm' | 'github'

export interface DshPluginInstallMethod {
  id: DshPluginInstallMethodId
  command: string
  titleKey: string
  descriptionKey: string
  recommended?: boolean
  sourceInstall?: boolean
}

export const DSH_PLUGIN_INSTALL_COMMAND = 'dsh plugin --profile web add dsh-aigc-radar'

export const DSH_PLUGIN_INSTALL_METHODS: readonly DshPluginInstallMethod[] = [
  {
    id: 'npm',
    command: DSH_PLUGIN_INSTALL_COMMAND,
    titleKey: 'mcp.dshPlugin.methods.npm.title',
    descriptionKey: 'mcp.dshPlugin.methods.npm.description',
    recommended: true,
  },
  {
    id: 'github',
    command: 'dsh plugin --profile web add github:Kaixxrua/dsh-aigc-radar',
    titleKey: 'mcp.dshPlugin.methods.github.title',
    descriptionKey: 'mcp.dshPlugin.methods.github.description',
    sourceInstall: true,
  },
]

/** MCP/API 共用额度（每 24 小时 / 每 30 天，窗口从其中第一次调用起算），与 mcp-go ratelimit.go 的 defaultLimits
 * 及 dsh.wizard.vipHint、mcp.quota.free 文案同值；改额度时几处一起改。 */
export const MCP_MEMBER_QUOTA = { rolling24h: 200, rolling30d: 8000 } as const
export const MCP_FREE_QUOTA = { rolling24h: 10, rolling30d: 400 } as const

export const DSH_PLUGIN_REPOSITORY_URL =
  'https://github.com/Kaixxrua/dsh-aigc-radar'

/** 账号的 DSH 专用 Token 的标签，与后端 routes_auth._DSH_MCP_TOKEN_CLIENT_LABEL 同值。 */
export const DSH_MCP_TOKEN_LABEL = 'dsh-aigc-radar'

/** dsh web profile 的补丁层：插件配置（含 mcpToken）写在这里。 */
export const DSH_PATCH_PATH = '~/.dsh/profiles/web/cordis.patch.yml'

const yamlQuote = (value: string) => `'${value.replace(/'/g, "''")}'`

// 后端签发的 token 是 urlsafe 字符集（[A-Za-z0-9_-] 加 aigc_mcp_ 前缀），
// 不含双引号、$、反引号或反斜杠，因此可以安全地置于 shell 双引号内；
// YAML 侧的单引号由 yamlQuote 负责折转。
const shellDoubleQuote = (value: string) => `"${value}"`

/** 写进 cordis.patch.yml 的那一项：整体替换 aigc-radar 这一行的 config，只带 mcpToken。 */
export const dshPatchLines = (token: string) => [
  '- replace:',
  '    - id: aigc-radar',
  '      name: dsh-aigc-radar',
  '      config:',
  `        mcpToken: ${yamlQuote(token)}`,
]

// 一条命令完成安装与 Token 落盘：安装插件后把 mcpToken 补丁写进 profile 补丁层。
// cordis.patch.yml 默认只有注释与空数组，追加会破坏 YAML 结构，因此整文件覆盖。
// /dsh 手动安装用占位串代替 Token 调它，拼出命令预览。
export const buildDshInstallLine = (command: string, token: string) => {
  const args = dshPatchLines(token).map(shellDoubleQuote).join(' ')
  return `${command} && printf '%s\\n' ${args} > ${DSH_PATCH_PATH}`
}
