/**
 * dsh 插件（dsh-aigc-radar）安装信息。
 *
 * dsh 终端用户的原生接入方式：插件内置项目库搜索卡片与检索路由提示，
 * 走 AIGC Radar 公共 MCP 端点且免 Token，一条命令装入 dsh web profile。
 */
export type DshPluginInstallMethodId = 'npm' | 'npm-pinned' | 'github'

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
    id: 'npm-pinned',
    command: 'dsh plugin --profile web add dsh-aigc-radar@0.2.0',
    titleKey: 'mcp.dshPlugin.methods.npmPinned.title',
    descriptionKey: 'mcp.dshPlugin.methods.npmPinned.description',
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
