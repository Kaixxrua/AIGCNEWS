import type { LocationQuery } from 'vue-router'
import { MCP_OAUTH_REQUEST_FIELDS, type McpOAuthRequest } from '@/services/mcp/mcpOAuthApi'

/**
 * MCP OAuth 同意页的纯逻辑：从查询串取授权请求、跳回客户端前复核回跳地址、识别被嵌进别的页面。
 */

export interface ParsedAuthorizationQuery {
  request: McpOAuthRequest
  /** 有参数出现了不止一次（RFC 6749 §3.1 不允许）：分不清哪个才是真的，整个请求作废。 */
  duplicated: boolean
}

export function parseAuthorizationQuery(query: LocationQuery): ParsedAuthorizationQuery {
  const request: McpOAuthRequest = {}
  let duplicated = false
  for (const field of MCP_OAUTH_REQUEST_FIELDS) {
    const value = query[field]
    if (Array.isArray(value)) duplicated = true
    else if (typeof value === 'string') request[field] = value
  }
  return { request, duplicated }
}

/** 会在本站上下文里执行或读取本地内容的协议：回跳地址绝不能是这些。 */
const BLOCKED_PROTOCOLS = new Set(['javascript:', 'data:', 'vbscript:', 'file:', 'blob:', 'about:', 'filesystem:'])

/**
 * 跳回客户端前再核一次后端给的地址：必须以页面转出去的 redirect_uri 开头（后端只在其后追加参数），
 * 协议也不能是能在本站执行脚本的那几种。后端已校验过回调地址，这里防的是响应被篡改或后端出错。
 */
export function isSafeClientRedirect(redirectTo: unknown, redirectUri: string | undefined): redirectTo is string {
  if (typeof redirectTo !== 'string' || !redirectUri || !redirectTo.startsWith(redirectUri)) return false
  let url: URL
  try {
    url = new URL(redirectTo)
  } catch {
    return false
  }
  return !BLOCKED_PROTOCOLS.has(url.protocol)
}

/** 页面被嵌进 iframe（点击劫持）时不展示同意按钮；跨源访问 top 抛错也按被嵌入处理。 */
export function isFramed(win: Window = window): boolean {
  try {
    return win.self !== win.top
  } catch {
    return true
  }
}

/** scope → 同意页文案键（mcpOAuth.grants.*）；不认识的 scope 后端不会授予，这里也不展示。 */
export const MCP_OAUTH_SCOPE_GRANT_KEYS: Readonly<Record<string, string>> = {
  'projects:favorites:read': 'favorites',
  'tracking:read': 'tracking',
}
