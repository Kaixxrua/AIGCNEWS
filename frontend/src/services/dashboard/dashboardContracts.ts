import type { PeriodKey, Stats, TabKey, TopDoc } from '@/features/dashboard/dashboardViewModel'

export interface DashboardSummaryWireResponse {
  stats?: Stats | null
  is_finalized?: boolean | null
  is_embargoed?: boolean | null
}

/** 单源榜单状态（/dashboard/top 的 source_status wire 契约） */
export interface SourceBoardStatus {
  is_finalized?: boolean | null
  is_embargoed?: boolean | null
  /** 源自然日界：PT（美国日界）或 CST */
  day_boundary?: string | null
  /** 次日 CST 定稿整点 */
  finalize_hour?: number | null
  /** 可插拔源被特性开关关闭（wire 只增字段；缺省视为启用） */
  is_disabled?: boolean | null
}

export type SourceStatusMap = Partial<Record<TabKey, SourceBoardStatus>>

export interface DashboardTopWireResponse {
  items?: TopDoc[] | null
  is_embargoed?: boolean | null
  source_status?: SourceStatusMap | null
}

export interface DashboardSnapshotDatesWireResponse {
  dates?: string[] | null
}

export interface DashboardRecentXWireResponse {
  items?: TopDoc[] | null
  total?: number | null
  window_hours?: number | null
}

export interface DashboardVisitorCountWireResponse {
  registered_users?: number | null
  today_registered_users?: number | null
  user_count?: number | null
}

export interface DashboardSummary {
  stats: Stats
  isFinalized: boolean
  isEmbargoed: boolean
}

export interface DashboardTop {
  items: TopDoc[]
  /** 昨日榜单在 CST 15:00 定稿前处于静默期（后端直接放空 items） */
  isEmbargoed: boolean
  /** 分源定稿状态（tab 级徽章数据源）；后端旧版本缺省时为空对象 */
  sourceStatus: SourceStatusMap
}

export interface XSnapshotRebuildResultItem {
  date: string
  upserted: number
}

export interface XSnapshotRebuildResponse {
  status: string
  message: string
  results?: XSnapshotRebuildResultItem[] | null
  skipped_no_date?: number | null
}

export interface DashboardRecentX {
  items: TopDoc[]
  total: number
  windowHours: number
}

export interface DashboardVisitorCount {
  registeredUsers: number
  todayRegisteredUsers: number
  userCount: number
}

export interface DashboardSummaryParams {
  /** 榜单周期；缺省后端按默认周期解析（undefined 不入查询串） */
  period?: PeriodKey
  date: string
  signal?: AbortSignal
}

export interface DashboardTopParams extends DashboardSummaryParams {
  source: TabKey
  limit?: number
  cacheBuster?: number
}

export interface DashboardSnapshotDatesParams {
  limit?: number
  source?: TabKey
  period?: PeriodKey
  signal?: AbortSignal
  cacheBuster?: number
}

export interface DashboardRecentXParams {
  hours?: number
  limit?: number
  signal?: AbortSignal
  cacheBuster?: number
}

export type GitHubHotPeriod = 'daily' | 'weekly' | 'monthly'

export interface GitHubHotRepo {
  repo_id?: string | number
  full_name?: string
  title?: string
  url?: string
  description?: string | null
  language?: string | null
  topics_json?: string | string[] | null
  stars?: number | string | null
  forks?: number | string | null
}

export interface GitHubHotWireResponse {
  period?: GitHubHotPeriod | string | null
  window_days?: number
  items?: GitHubHotRepo[] | null
  total?: number
  snapshot_count?: number
}

export interface GitHubHotResponse {
  period: GitHubHotPeriod | string
  window_days?: number
  items: GitHubHotRepo[]
  total?: number
  snapshot_count?: number
}

export interface DashboardApi {
  fetchSummary(params: DashboardSummaryParams): Promise<DashboardSummary>
  fetchTop(params: DashboardTopParams): Promise<DashboardTop>
  fetchRecentX(params: DashboardRecentXParams): Promise<DashboardRecentX>
  fetchSnapshotDates(params: DashboardSnapshotDatesParams): Promise<string[]>
  fetchVisitorCount(signal?: AbortSignal): Promise<DashboardVisitorCount>
  fetchGitHubHotRepos(period?: GitHubHotPeriod, limit?: number): Promise<GitHubHotResponse>
  deleteDocument(docId: string): Promise<{ status: string; message: string; doc_id: string; deleted: boolean }>
  bulkDeleteDocuments(docIds: string[]): Promise<{ status: string; message: string; doc_ids: string[]; deleted_count: number; not_found_count: number }>
  /** 管理员补拉：从已入库推文按发布日（CST）重建 X 日榜快照；targetDate 缺省 = 全部历史日期 */
  rebuildXSnapshot(targetDate?: string): Promise<XSnapshotRebuildResponse>
}
