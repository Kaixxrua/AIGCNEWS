import { describe, expect, it } from 'vitest'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import {
  FAST_POLL_MS,
  FAST_POLL_WINDOW_MS,
  SLOW_POLL_MS,
  formatUsedAgo,
  parseTimestampMs,
  pollDelayMs,
  sightToken,
  usedSinceBaseline,
} from './tokenConnectionModel'

const NOW = Date.parse('2026-10-05T12:00:00Z')

const token = (patch: Partial<McpTokenMetadata> = {}): McpTokenMetadata => ({
  id: 7,
  token_hint: 'aigc_mcp_abc...wxyz',
  scopes: ['projects:favorites:read'],
  client_type: 'claude',
  client_label: 'Claude Code',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
  ...patch,
})

describe('tokenConnectionModel', () => {
  it('polls quickly for the first minute, then slows down', () => {
    expect(pollDelayMs(0)).toBe(FAST_POLL_MS)
    expect(pollDelayMs(FAST_POLL_WINDOW_MS - 1)).toBe(FAST_POLL_MS)
    expect(pollDelayMs(FAST_POLL_WINDOW_MS)).toBe(SLOW_POLL_MS)
  })

  it('reads API timestamps, treating a missing zone as UTC', () => {
    expect(parseTimestampMs('2026-10-05T11:59:00Z')).toBe(NOW - 60_000)
    expect(parseTimestampMs('2026-10-05T11:59:00+00:00')).toBe(NOW - 60_000)
    expect(parseTimestampMs('2026-10-05T11:59:00')).toBe(NOW - 60_000)
    expect(parseTimestampMs(null)).toBeNull()
    expect(parseTimestampMs('not a date')).toBeNull()
  })

  it('finds the token by id and reports whether it was ever used', () => {
    expect(sightToken([token({ id: 3 }), token()], 7, NOW)).toEqual({ kind: 'unused' })
    expect(sightToken([token({ last_used_at: '2026-10-05T11:59:00Z' })], 7, NOW)).toEqual({
      kind: 'used',
      lastUsedAt: '2026-10-05T11:59:00Z',
      lastUsedMs: NOW - 60_000,
    })
  })

  it('treats a missing, revoked, deleted or expired token as gone', () => {
    expect(sightToken([token({ id: 3 })], 7, NOW)).toEqual({ kind: 'gone' })
    expect(sightToken([token({ revoked_at: '2026-10-05T11:00:00Z' })], 7, NOW)).toEqual({ kind: 'gone' })
    expect(sightToken([token({ deleted_at: '2026-10-05T11:00:00Z' })], 7, NOW)).toEqual({ kind: 'gone' })
    expect(sightToken([token({ expires_at: '2026-10-05T12:00:00Z' })], 7, NOW)).toEqual({ kind: 'gone' })
    expect(sightToken([token({ expires_at: '2026-10-06T12:00:00Z' })], 7, NOW)).toEqual({ kind: 'unused' })
  })

  it('counts a use as new only when it differs from the baseline', () => {
    const used = sightToken([token({ last_used_at: '2026-10-05T11:59:00Z' })], 7, NOW)
    expect(usedSinceBaseline(used, null)).toBe(true)
    expect(usedSinceBaseline(used, NOW - 60_000)).toBe(false)
    expect(usedSinceBaseline(used, NOW - 3_600_000)).toBe(true)
    expect(usedSinceBaseline({ kind: 'unused' }, null)).toBe(false)
    expect(usedSinceBaseline({ kind: 'gone' }, null)).toBe(false)
  })

  it('writes the last use as time ago, never in the future', () => {
    expect(formatUsedAgo(NOW + 30_000, NOW, 'en-US', 'just now')).toBe('just now')
    expect(formatUsedAgo(NOW - 59_000, NOW, 'en-US', 'just now')).toBe('just now')
    expect(formatUsedAgo(NOW - 5 * 60_000, NOW, 'en-US', 'just now')).toBe('5 minutes ago')
    expect(formatUsedAgo(NOW - 3 * 3_600_000, NOW, 'en-US', 'just now')).toBe('3 hours ago')
    expect(formatUsedAgo(NOW - 3 * 86_400_000, NOW, 'en-US', 'just now')).toBe('3 days ago')
    expect(formatUsedAgo(NOW - 86_400_000, NOW, 'zh-CN', '刚刚')).toBe('昨天')
  })
})
