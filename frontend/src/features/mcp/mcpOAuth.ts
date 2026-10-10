/**
 * MCP 浏览器授权（OAuth）入口：客户端连这个地址，被 401 质询后按 RFC 9728 找到本站的授权服务，在浏览器里登录、
 * 点「同意」，换到一枚只属于它的 Token，用户不用复制 Token。
 *
 * 资源地址在后端（mcp_oauth.py 的 MCP_OAUTH_RESOURCE）和发布的元数据里都钉在 aigcnews.cn，签出的 Token 只认它，
 * 所以从备用入口打开 /mcp 也给这个地址，不跟页面的 origin 走；连不上 aigcnews.cn 的用户改用手动 Token。
 * backend/tests/test_mcp_oauth_metadata_contract.py 钉住两边一致。
 */
export const MCP_OAUTH_ENDPOINT = 'https://aigcnews.cn/api/mcp/oauth'
