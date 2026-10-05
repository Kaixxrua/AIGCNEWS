import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'

/**
 * 令牌连没连上：网页看不到用户电脑上的客户端，只能看服务端记下的「这枚令牌最近一次被用」（last_used_at）。
 * MCP 服务收到带令牌的请求就记一笔（空值立即写，之后 5 分钟内只写一次），所以：
 * - 新令牌：last_used_at 从空变成有值，就是客户端连上了（多数客户端启动时就握手；dsh 插件第一次搜索时才连）；
 * - dsh 复用的旧令牌：开始检测时的值作基线，值变了才算这次装好后又连上了；基线本身有值说明以前连过。
 * 令牌不在列表里了（被删除、被重新生成、超出 20 枚被淘汰）或已过期，就不必再等。
 */

/** 刚生成或刚复制命令的头一分钟用户正在终端里操作，勤快些；之后放慢，十分钟后停下等用户点「再检查」。 */
export const FAST_POLL_MS = 3_000
export const SLOW_POLL_MS = 10_000
export const FAST_POLL_WINDOW_MS = 60_000
export const WATCH_LIMIT_MS = 600_000
/** 等了两分钟还没连上，自动展开排障提示。 */
export const TIPS_AFTER_MS = 120_000

export const pollDelayMs = (elapsedMs: number): number => (elapsedMs < FAST_POLL_WINDOW_MS ? FAST_POLL_MS : SLOW_POLL_MS)

const EXPLICIT_ZONE = /(?:[zZ]|[+-]\d{2}:?\d{2})$/

/** 接口给的时间带时区（…Z）；万一缺了时区按 UTC 读，与 i18n/formatters 的 parseImplicitUtc 同一口径。 */
export const parseTimestampMs = (value: string | null | undefined): number | null => {
  if (!value) return null
  const ms = Date.parse(EXPLICIT_ZONE.test(value) ? value : `${value}Z`)
  return Number.isNaN(ms) ? null : ms
}

export type TokenSighting =
  | { kind: 'gone' }
  | { kind: 'unused' }
  | { kind: 'used'; lastUsedAt: string; lastUsedMs: number }

/** 在令牌列表里找这枚令牌，看它还在不在、用没用过。 */
export const sightToken = (tokens: readonly McpTokenMetadata[], tokenId: number, nowMs: number): TokenSighting => {
  const token = tokens.find((item) => item.id === tokenId)
  if (!token || token.revoked_at || token.deleted_at) return { kind: 'gone' }
  const expiresMs = parseTimestampMs(token.expires_at)
  if (expiresMs != null && expiresMs <= nowMs) return { kind: 'gone' }
  const lastUsedMs = parseTimestampMs(token.last_used_at)
  return lastUsedMs == null ? { kind: 'unused' } : { kind: 'used', lastUsedAt: token.last_used_at!, lastUsedMs }
}

/** 基线之后有没有新的使用记录：基线为空时任何使用都算，否则时间要变（比较服务端的时间，不掺浏览器时钟）。 */
export const usedSinceBaseline = (sighting: TokenSighting, baselineMs: number | null): boolean => (
  sighting.kind === 'used' && (baselineMs == null || sighting.lastUsedMs !== baselineMs)
)

/** 「最近一次使用」写成多久以前：一分钟内是「刚刚」，再往后按分钟、小时、天；浏览器时钟比服务端慢时不会写出「几分钟后」。 */
export const formatUsedAgo = (lastUsedMs: number, nowMs: number, locale: string, justNow: string): string => {
  const seconds = Math.max(0, Math.floor((nowMs - lastUsedMs) / 1000))
  if (seconds < 60) return justNow
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  if (seconds < 3600) return rtf.format(-Math.floor(seconds / 60), 'minute')
  if (seconds < 86_400) return rtf.format(-Math.floor(seconds / 3600), 'hour')
  return rtf.format(-Math.floor(seconds / 86_400), 'day')
}
