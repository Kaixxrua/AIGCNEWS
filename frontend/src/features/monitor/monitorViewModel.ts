import { FileText, GitBranch, Newspaper, Rocket, Triangle, Twitter } from 'lucide-vue-next'
import { formatLocaleDate } from '@/i18n/formatters'

export type {
  McpServerConfig,
  McpServerForm,
  McpToolCallEntry,
  McpToolCallMetricsSnapshot,
  ProviderConfig,
  ProviderForm,
  SchedulerStatus,
  SourceKey,
  Task,
} from './monitorModel'

import type { McpServerConfig, McpToolCallMetricsSnapshot, SourceKey } from './monitorModel'

export interface SourceItem {
  key: SourceKey
  labelKey: string
  icon: typeof FileText
  color: string
  textColor: string
}

export const MCP_TEST_SCOPE = [
  { title: 'initialize', descriptionKey: 'initialize' },
  { title: 'initialized', descriptionKey: 'initialized' },
  { title: 'tools/list', descriptionKey: 'tools' },
]

export const SOURCE_LIST: SourceItem[] = [
  { key: 'arxiv', labelKey: 'arxiv', icon: FileText, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'github', labelKey: 'github', icon: GitBranch, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'hackernews', labelKey: 'hackernews', icon: Triangle, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'producthunt', labelKey: 'producthunt', icon: Rocket, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'news', labelKey: 'news', icon: Newspaper, color: 'bg-white', textColor: 'text-stone-600' },
  { key: 'x', labelKey: 'x', icon: Twitter, color: 'bg-white', textColor: 'text-stone-600' },
]

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
  success: { labelKey: 'success', rawLabel: '', dot: 'bg-brand-green', bg: 'bg-green-50', text: 'text-green-700' },
  succeeded: { labelKey: 'success', rawLabel: '', dot: 'bg-brand-green', bg: 'bg-green-50', text: 'text-green-700' },
  failed: { labelKey: 'failed', rawLabel: '', dot: 'bg-brand-rose', bg: 'bg-rose-50', text: 'text-rose-600' },
  running: { labelKey: 'running', rawLabel: '', dot: 'bg-brand-blue', bg: 'bg-blue-50', text: 'text-blue-600' },
  unknown: { labelKey: 'unknownStatus', rawLabel: '', dot: 'bg-stone-300', bg: 'bg-stone-50', text: 'text-stone-500' },
}

export const getStatusConfig = (status: string) => (
  STATUS_CONFIG[(status || 'unknown').toLowerCase()]
  ?? { labelKey: '', rawLabel: status, dot: 'bg-stone-400', bg: 'bg-stone-50', text: 'text-stone-500' }
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
