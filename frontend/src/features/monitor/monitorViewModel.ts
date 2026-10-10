import { Activity, Box, Clock, CloudDownload, CreditCard, FileText, Flame, GitBranch, Globe, Newspaper, Rocket, Send, Settings, Triangle, Users } from 'lucide-vue-next'
import { formatLocaleDate } from '@/i18n/formatters'
import { GithubMarkIcon } from '@/components/icons/GithubMarkIcon'
import { HuggingFaceIcon } from '@/components/icons/HuggingFaceIcon'
import { XLogoIcon } from '@/components/icons/XLogoIcon'
import type { Component } from 'vue'

export type {
  ErrorLogEntry,
  McpServerConfig,
  McpServerForm,
  McpToolCallEntry,
  McpToolCallMetricsSnapshot,
  OAuthConfig,
  OAuthConfigForm,
  OAuthProviderKey,
  TelegramConfig,
  TelegramConfigForm,
  TelegramWebhookStatus,
  PaymentConfig,
  PaymentConfigForm,
  ProviderConfig,
  ProviderForm,
  SchedulerStatus,
  SmtpConfig,
  SmtpForm,
  SourceKey,
  Task,
  UserStatsResponse,
  RevenueStatsResponse,
  VisitPlatformKey,
  VisitPlatformShare,
  VisitPlatformStatsResponse,
  VisitStatsWindow,
} from './monitorModel'

import type { McpServerConfig, McpToolCallMetricsSnapshot, SourceKey } from './monitorModel'

export interface SourceItem {
  key: SourceKey
  labelKey: string
  icon: Component
  color: string
  textColor: string
}

export const MCP_TEST_SCOPE = [
  { title: 'initialize', descriptionKey: 'initialize' },
  { title: 'initialized', descriptionKey: 'initialized' },
  { title: 'tools/list', descriptionKey: 'tools' },
]

export const SOURCE_LIST: SourceItem[] = [
  { key: 'arxiv', labelKey: 'arxiv', icon: FileText, color: '', textColor: '' },
  { key: 'github', labelKey: 'github', icon: GitBranch, color: '', textColor: '' },
  { key: 'hackernews', labelKey: 'hackernews', icon: Triangle, color: '', textColor: '' },
  { key: 'producthunt', labelKey: 'producthunt', icon: Rocket, color: '', textColor: '' },
  { key: 'news', labelKey: 'news', icon: Newspaper, color: '', textColor: '' },
  { key: 'x', labelKey: 'x', icon: XLogoIcon, color: '', textColor: '' },
]

export type MonitorSectionKey =
  | 'tasks' | 'mcp-calls' | 'errors' | 'visit-stats' | 'ai-ops' | 'email-monitor'
  | 'collect' | 'crawl' | 'enrichment' | 'ui-sources'
  | 'x-watch' | 'x-credentials'
  | 'provider' | 'scheduler' | 'smtp' | 'mcp-server' | 'oauth-config' | 'telegram-push'
  | 'contact-page' | 'membership' | 'user-stats' | 'revenue' | 'payment-config' | 'payment-orders'

export interface MonitorNavLeaf {
  key: MonitorSectionKey
  labelKey: string
  adminOnly: boolean
}

export interface MonitorNavCategory {
  key: string
  labelKey: string
  icon: Component
  children: MonitorNavLeaf[]
}

// 监控页左侧两级导航：大类 → 叶子（一叶一面板）。叶子 key 即 URL ?section= 契约，测试锁定
export const MONITOR_NAV: MonitorNavCategory[] = [
  { key: 'monitor', labelKey: 'monitor.nav.group.monitor', icon: Activity, children: [
    { key: 'tasks', labelKey: 'monitor.nav.tasks', adminOnly: false },
    { key: 'mcp-calls', labelKey: 'monitor.nav.mcpCalls', adminOnly: false },
    { key: 'errors', labelKey: 'monitor.nav.errors', adminOnly: true },
    { key: 'ai-ops', labelKey: 'aiOpsTitle', adminOnly: true },
    { key: 'visit-stats', labelKey: 'monitor.nav.visitStats', adminOnly: true },
    { key: 'email-monitor', labelKey: 'monitorActivity.email', adminOnly: true },
  ] },
  { key: 'ingestion', labelKey: 'monitor.nav.group.ingestion', icon: CloudDownload, children: [
    { key: 'collect', labelKey: 'monitor.nav.collect', adminOnly: true },
    { key: 'crawl', labelKey: 'monitor.nav.crawl', adminOnly: true },
    { key: 'enrichment', labelKey: 'monitor.nav.enrichment', adminOnly: true },
    { key: 'ui-sources', labelKey: 'monitor.nav.uiSources', adminOnly: true },
  ] },
  { key: 'accounts', labelKey: 'monitor.nav.group.accounts', icon: Users, children: [
    { key: 'x-watch', labelKey: 'monitor.nav.xWatch', adminOnly: true },
    { key: 'x-credentials', labelKey: 'monitor.nav.xCredentials', adminOnly: true },
  ] },
  { key: 'config', labelKey: 'monitor.nav.group.config', icon: Settings, children: [
    { key: 'provider', labelKey: 'monitor.nav.provider', adminOnly: true },
    { key: 'scheduler', labelKey: 'monitor.nav.scheduler', adminOnly: true },
    { key: 'smtp', labelKey: 'monitor.nav.smtp', adminOnly: true },
    { key: 'mcp-server', labelKey: 'monitor.nav.mcpServer', adminOnly: true },
    { key: 'oauth-config', labelKey: 'monitor.nav.oauthConfig', adminOnly: true },
    { key: 'telegram-push', labelKey: 'monitor.nav.telegramPush', adminOnly: true },
  ] },
  { key: 'site', labelKey: 'monitor.nav.group.site', icon: Globe, children: [
    { key: 'contact-page', labelKey: 'monitor.nav.contactPage', adminOnly: true },
    { key: 'membership', labelKey: 'monitor.nav.membership', adminOnly: true },
    { key: 'user-stats', labelKey: 'monitor.nav.userStats', adminOnly: true },
    { key: 'revenue', labelKey: 'monitor.nav.revenue', adminOnly: true },
    { key: 'payment-config', labelKey: 'monitor.nav.paymentConfig', adminOnly: true },
    { key: 'payment-orders', labelKey: 'monitor.nav.paymentOrders', adminOnly: true },
  ] },
]

export const DEFAULT_MONITOR_SECTION: MonitorSectionKey = 'tasks'

const MONITOR_SECTION_KEY_SET = new Set<string>(
  MONITOR_NAV.flatMap(category => category.children.map(leaf => leaf.key)),
)

// ?section= 白名单校验：LocationQueryValue 可能为 null，重复参数（string[]）取第一个
export const normalizeMonitorSection = (value: unknown): MonitorSectionKey => {
  const raw = Array.isArray(value) ? value[0] : value
  const key = String(raw ?? '').trim()
  return MONITOR_SECTION_KEY_SET.has(key)
    ? key as MonitorSectionKey
    : DEFAULT_MONITOR_SECTION
}

export const formatDate = (value: string | null | undefined): string => (
  value
    ? formatLocaleDate(value, {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      })
    : '—'
)

export const formatTime = (value: string | null | undefined): string => (
  value
    ? formatLocaleDate(value, {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      })
    : '—'
)

const STATUS_CONFIG: Record<string, { labelKey: string; rawLabel: string; dot: string; bg: string; text: string }> = {
  success: { labelKey: 'success', rawLabel: '', dot: 'monitor-status-dot-success', bg: 'monitor-status-success', text: '' },
  succeeded: { labelKey: 'success', rawLabel: '', dot: 'monitor-status-dot-success', bg: 'monitor-status-success', text: '' },
  failed: { labelKey: 'failed', rawLabel: '', dot: 'monitor-status-dot-error', bg: 'monitor-status-error', text: '' },
  running: { labelKey: 'running', rawLabel: '', dot: 'monitor-status-dot-running', bg: 'monitor-status-running', text: '' },
  unknown: { labelKey: 'unknownStatus', rawLabel: '', dot: 'monitor-status-dot-unknown', bg: 'monitor-status-unknown', text: '' },
}

export const getStatusConfig = (status: string) => (
  STATUS_CONFIG[(status || 'unknown').toLowerCase()]
  ?? { labelKey: '', rawLabel: status, dot: 'monitor-status-dot-unknown', bg: 'monitor-status-unknown', text: '' }
)

// 调度任务卡片的来源图标：按任务 id 的来源前缀/关键词匹配，先到先得；未知任务用时钟。
// tone 决定图标的底：brand 用标志自己的颜色、mark 是实心墨色标志、badge 是黑底方章、accent 是蓝色实心，
// 其余放在浅蓝方块上（样式见 comic-pages.css）。
export type SchedulerJobIconTone = 'brand' | 'mark' | 'badge' | 'accent' | 'tile'

const SCHEDULER_JOB_ICONS: [RegExp, Component, SchedulerJobIconTone][] = [
  [/^ui_library/, Box, 'tile'],
  [/^x_/, XLogoIcon, 'badge'],
  [/^github_/, GithubMarkIcon, 'mark'],
  [/arxiv|paper/, HuggingFaceIcon, 'brand'],
  [/^hackernews/, Triangle, 'tile'],
  [/^producthunt/, Rocket, 'tile'],
  [/^dailyhot/, Flame, 'tile'],
  [/^news_/, Newspaper, 'tile'],
  [/briefing/, FileText, 'tile'],
  [/subscription|tracking|digest/, Send, 'accent'],
  [/payment/, CreditCard, 'tile'],
]

const findSchedulerJobIcon = (jobId: string) => SCHEDULER_JOB_ICONS.find(([pattern]) => pattern.test(jobId))

export const getSchedulerJobIcon = (jobId: string): Component => findSchedulerJobIcon(jobId)?.[1] ?? Clock

export const getSchedulerJobIconTone = (jobId: string): SchedulerJobIconTone => findSchedulerJobIcon(jobId)?.[2] ?? 'tile'

export const getMcpTransportPresentation = (transport: string) => (
  (transport || '').toLowerCase() === 'streamable_http'
    ? { label: 'Streamable HTTP', labelKey: '' }
    : transport ? { label: transport, labelKey: '' } : { label: '', labelKey: 'unknownTransport' }
)

export const getMcpAuthPresentation = (authType: string) => (
  (authType || '').toLowerCase() === 'bearer'
    ? { label: 'Bearer Token', labelKey: '' }
    : (authType || '').toLowerCase() === 'none'
      ? { label: '', labelKey: 'noAuth' }
      : { label: authType, labelKey: '' }
)

export const getMcpServerInitial = (server: McpServerConfig) => {
  const value = (server.display_name || server.server_key || 'M').trim()
  return value.slice(0, 1).toUpperCase()
}

export interface McpToolCallRow {
  name: string
  calls: number
  lastCalledAt: string | null
}

export const toMcpToolCallRows = (
  snapshot: Pick<McpToolCallMetricsSnapshot, 'tools'> | null | undefined,
): McpToolCallRow[] => (
  Object.entries(snapshot?.tools ?? {})
    .map(([name, entry]) => ({
      name,
      calls: Number(entry?.calls) || 0,
      lastCalledAt: entry?.last_called_at || null,
    }))
    .sort((a, b) => b.calls - a.calls || a.name.localeCompare(b.name))
)
