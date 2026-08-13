import { Activity, CloudDownload, FileText, GitBranch, Newspaper, Rocket, Settings, Triangle } from 'lucide-vue-next'
import { formatLocaleDate } from '@/i18n/formatters'
import { XLogoIcon } from '@/components/icons/XLogoIcon'
import type { Component } from 'vue'

export type {
  McpServerConfig,
  McpServerForm,
  McpToolCallEntry,
  McpToolCallMetricsSnapshot,
  ProviderConfig,
  ProviderForm,
  SchedulerStatus,
  SmtpConfig,
  SmtpForm,
  SourceKey,
  Task,
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

export type MonitorSectionKey = 'status' | 'ingestion' | 'github' | 'settings'

export interface MonitorSectionItem {
  key: MonitorSectionKey
  labelKey: string
  icon: Component
  adminOnly: boolean
}

// 监控页左侧二级导航分组：顺序即导航展示与 URL ?section= 的契约，测试锁定
export const MONITOR_SECTIONS: MonitorSectionItem[] = [
  { key: 'status', labelKey: 'monitor.nav.status', icon: Activity, adminOnly: false },
  { key: 'ingestion', labelKey: 'monitor.nav.ingestion', icon: CloudDownload, adminOnly: true },
  { key: 'github', labelKey: 'monitor.nav.github', icon: GitBranch, adminOnly: true },
  { key: 'settings', labelKey: 'monitor.nav.settings', icon: Settings, adminOnly: true },
]

export const DEFAULT_MONITOR_SECTION: MonitorSectionKey = 'status'

// ?section= 白名单校验：LocationQueryValue 可能为 null，重复参数（string[]）取第一个
export const normalizeMonitorSection = (value: unknown): MonitorSectionKey => {
  const raw = Array.isArray(value) ? value[0] : value
  const key = String(raw ?? '').trim()
  return MONITOR_SECTIONS.some(section => section.key === key)
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
