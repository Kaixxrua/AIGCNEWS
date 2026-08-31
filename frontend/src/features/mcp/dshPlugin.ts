/**
 * dsh 插件（dsh-aigc-radar）安装信息。
 *
 * 插件可直接从 npm 或 GitHub 安装，无需先登录网站；不配置 mcpToken 时，
 * 仍可通过 AIGC Radar 公共 MCP runtime 使用公开工具。网站 `/dsh` 配置页必须登录，
 * 登录后生成的命令会把账号绑定的 DSH 专用 Token 写入 dsh web profile。
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

export const DSH_PLUGIN_REPOSITORY_URL =
  'https://github.com/Kaixxrua/dsh-aigc-radar'
