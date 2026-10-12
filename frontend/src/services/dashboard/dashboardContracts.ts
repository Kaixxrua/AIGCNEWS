import type { PeriodKey, Stats, TabKey, TopDoc } from '@/features/dashboard/dashboardViewModel'

export interface DashboardSummaryWireResponse {
  stats?: Stats | null
  is_finalized?: boolean | null
  is_embargoed?: boolean | null
}

export interface DashboardStaticSummaryWireResponse {
  top_list?: TopDoc[] | null
  radar?: unknown[] | null
  period?: string | null
  snapshot_date?: string | null
  requested_date?: string | null
  resolved_date?: string | null
  stale?: boolean | null
  is_finalized?: boolean | null
  is_embargoed?: boolean | null
}

export interface DashboardStaticSummary {
  isFinalized: boolean
  isEmbargoed: boolean
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
  is_finalized?: boolean | null
  resolved_date?: string | null
  stale?: boolean | null
  is_embargoed?: boolean | null
  source_status?: SourceStatusMap | null
}

export interface DashboardSnapshotDatesWireResponse {
  dates?: string[] | null
}

export interface DashboardRecentXWireResponse {
  accounts?: { handle: string; displayName: string }[] | null
  items?: TopDoc[] | null
  total?: number | null
  window_hours?: number | null
  window_extended?: boolean | null
  days_back?: number | null
  /** 满页时为 true，配合 next_cursor 续查（旧后端缺省视为无下一页） */
  has_more?: boolean | null
  /** keyset 续页游标；只编码公开排序位置，不含凭据 */
  next_cursor?: string | null
}

export interface DashboardVisitorCountWireResponse {
  registered_users?: number | null
  today_registered_users?: number | null
  user_count?: number | null
  today_visits?: number | null
  total_visits?: number | null
}

export interface DashboardSummary {
  stats: Stats
  isFinalized: boolean
  isEmbargoed: boolean
}

export interface DashboardTop {
  items: TopDoc[]
  isFinalized?: boolean
  resolvedDate?: string
  stale?: boolean
  /** 兼容旧服务端；新服务端的未定稿快照也持续可读。 */
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
  accounts?: { handle: string; displayName: string }[]
  items: TopDoc[]
  total: number
  windowHours: number
  windowExtended?: boolean
  /** 满页且有可续查游标时为 true（旧后端缺省为 false，即单页语义） */
  hasMore: boolean
  /** 续页游标；hasMore=false 或无下一页时为 null */
  nextCursor: string | null
}

export interface DashboardVisitorCount {
  registeredUsers: number
  todayRegisteredUsers: number
  userCount: number
  todayVisits: number
  totalVisits: number
}

export interface DashboardSummaryParams {
  /** 榜单周期；缺省后端按默认周期解析（undefined 不入查询串） */
  period?: PeriodKey
  /** 今天省略日期以启用后端的可展示日期回溯；历史日期显式传入。 */
  date?: string
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
  /** 当前窗口不足时按关注账号补入更早推文；历史日期与续页不补。 */
  minItems?: number
  accountMode?: 'include' | 'exclude'
  accountHandles?: string[]
  /** 整数天位移：0 = 最近 hours 小时；1 = 昨天此刻往前 hours 小时（滑窗按天回移） */
  daysBack?: number
  limit?: number
  /** keyset 续页游标（上一页的 nextCursor）；不传 = 第一页 */
  cursor?: string
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
  fetchSummaryStatic?(params: DashboardSummaryParams): Promise<DashboardStaticSummary>
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
