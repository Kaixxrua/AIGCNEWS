/**
 * 一次性安装码：提示词里只放它，不放 Token。Agent 先把占位符写进客户端配置，再在一条命令里向兑换端点换 Token、
 * 原地替换占位符——Token 只出现在那一次 HTTP 响应里，不经过 Agent 的输出与聊天记录。
 *
 * 兑换路径与 backend routes_auth.redeem_mcp_install_code 同值，backend/tests/test_mcp_install_code_contract.py 钉住。
 * 地址跟当前入口走（备用入口打开就兑换到备用入口），与手动配置的 MCP 地址同口径。
 */
export const MCP_INSTALL_CODE_REDEEM_PATH = '/api/auth/mcp-install-codes/redeem'

/** 先写进配置、兑换后被替换成 Token 的占位符；只含字母和下划线，JSON、YAML、Shell 都不用转义。 */
export const MCP_TOKEN_PLACEHOLDER = '__AIGC_RADAR_TOKEN__'

export const installCodeRedeemUrl = (origin: string) =>
  `${origin.replace(/\/+$/, '')}${MCP_INSTALL_CODE_REDEEM_PATH}`
