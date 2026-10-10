/**
 * /mcp「手动配置」：给不支持浏览器授权的客户端，签一枚 Token，写成通用的 mcpServers JSON，用户自己合并进客户端配置。
 * 地址跟当前入口走（备用入口打开就连备用入口），Token 只进剪贴板；页面预览用 COMMAND_TOKEN_SLOT 代替。
 */
export const MANUAL_MCP_SERVER_NAME = 'aigc-news'

/** 手动配置签发的 Token 的标签：「复制给 Agent」之后的回显按它排除，免得把手动配置当成 Agent 刚接好的客户端。 */
export const MANUAL_MCP_TOKEN_LABEL = 'Manual MCP config'

export const manualMcpEndpoint = (origin: string) => `${origin.replace(/\/+$/, '')}/api/mcp`

export const buildManualMcpConfig = (endpoint: string, token: string) => JSON.stringify({
  mcpServers: {
    [MANUAL_MCP_SERVER_NAME]: {
      type: 'http',
      url: endpoint,
      headers: { Authorization: `Bearer ${token}` },
    },
  },
}, null, 2)
