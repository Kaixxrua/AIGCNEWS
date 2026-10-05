import i18n from '@/i18n'

/**
 * 监控页「MCP 每日用量」面板的文案独立成文件，沿用 notFound.ts 的注入方式：
 * 主 locale 表的 monitor 段是一整行，由其他工作流维护，这里在面板初始化时经
 * mergeLocaleMessage 注入顶层 mcpUsage.*。
 */

type McpUsageMessages = {
  mcpUsage: {
    title: string
    description: string
    range: string
    since: string
    unavailable: string
    empty: string
    loadFailed: string
    windowLabel: string
    window: { d7: string; d14: string; d30: string }
    audience: { anonymous: string; free: string; member: string; total: string }
    metric: { clients: string; connections: string; calls: string; limited: string }
    metricHint: { clients: string; connections: string; calls: string; limited: string }
    metricColumn: string
    summaryTitle: string
    dailyTitle: string
    dailyMetricLabel: string
    date: string
    toolsTitle: string
    tool: string
    unknownTool: string
    noTools: string
    clientsTitle: string
    clientName: string
    unnamedClient: string
    otherClients: string
    clientsCount: string
    connectionsCount: string
    audienceSplit: string
    clientNamesTruncated: string
    noClients: string
    limitedTitle: string
    kind: string
    limitKind: { burst: string; daily: string; monthly: string }
  }
}

const enUS: McpUsageMessages = {
  mcpUsage: {
    title: 'MCP daily usage',
    description:
      'Days follow Beijing time, split into anonymous, free and member traffic. Admin and load-test traffic is left out; anonymous clients are de-duplicated by a hashed IP and no IP is stored. Client names come from the clientInfo sent on connect.',
    range: '{start} to {end}',
    since: 'Tracking started on {date}; earlier days have no data.',
    unavailable: 'Usage data is unavailable right now (Redis is not connected). Refresh later.',
    empty: 'No MCP usage recorded in this window yet.',
    loadFailed: 'Failed to load MCP usage',
    windowLabel: 'Time window',
    window: { d7: 'Last 7 days', d14: 'Last 14 days', d30: 'Last 30 days' },
    audience: { anonymous: 'Anonymous', free: 'Free', member: 'Member', total: 'Total' },
    metric: { clients: 'Unique clients', connections: 'Connections', calls: 'Tool calls', limited: '429s' },
    metricHint: {
      clients:
        'Signed-in users count once per account, anonymous ones once per IP. Multi-day totals are a union, not a sum of days.',
      connections: 'initialize requests; a client opening a new session counts once.',
      calls: 'tools/call requests that were let through; rate-limited ones are not counted.',
      limited: 'Requests rejected with 429 by the rate limiter.',
    },
    metricColumn: 'Metric',
    summaryTitle: 'Window summary',
    dailyTitle: 'By day',
    dailyMetricLabel: 'Metric shown by day',
    date: 'Date',
    toolsTitle: 'Calls by tool',
    tool: 'Tool',
    unknownTool: 'Unknown tool name',
    noTools: 'No tool calls yet',
    clientsTitle: 'Clients',
    clientName: 'Client name',
    unnamedClient: 'No name reported',
    otherClients: 'Other (invalid names, or new names past 64 a day)',
    clientsCount: 'Unique clients',
    connectionsCount: 'Connections',
    audienceSplit: 'Unique clients split into anonymous, free and member',
    clientNamesTruncated: 'Showing the 50 clients with the most connections.',
    noClients: 'No client connections yet',
    limitedTitle: 'Where 429s come from',
    kind: 'Limit',
    limitKind: { burst: 'Per-minute burst', daily: '24-hour quota', monthly: '30-day allowance' },
  },
}

const zhCN: McpUsageMessages = {
  mcpUsage: {
    title: 'MCP 每日用量',
    description:
      '按北京时间计日，分匿名、免费、会员三类。不含管理员和压测流量；匿名按 IP 摘要去重，不保存 IP；客户端名取自连接时上报的 clientInfo。',
    range: '{start} 至 {end}',
    since: '自 {date} 起统计，更早的日子没有数据。',
    unavailable: '暂时读不到用量数据（Redis 未连接），稍后刷新再看。',
    empty: '这段时间还没有 MCP 用量记录。',
    loadFailed: '加载 MCP 用量失败',
    windowLabel: '时间范围',
    window: { d7: '近 7 天', d14: '近 14 天', d30: '近 30 天' },
    audience: { anonymous: '匿名', free: '免费', member: '会员', total: '合计' },
    metric: { clients: '去重客户端', connections: '连接次数', calls: '工具调用', limited: '429 次数' },
    metricHint: {
      clients: '登录用户按账号、匿名按 IP 去重；多天合计取并集，不是逐日相加。',
      connections: 'initialize 次数，客户端每新开一次会话算一次。',
      calls: '放行的 tools/call 次数，被限流的不算。',
      limited: '被限流器拒绝、返回 429 的请求数。',
    },
    metricColumn: '指标',
    summaryTitle: '窗口汇总',
    dailyTitle: '每日明细',
    dailyMetricLabel: '每日明细显示的指标',
    date: '日期',
    toolsTitle: '各工具调用',
    tool: '工具',
    unknownTool: '未知工具名',
    noTools: '暂无工具调用',
    clientsTitle: '客户端',
    clientName: '客户端名',
    unnamedClient: '未上报名称',
    otherClients: '其他（名字不合规，或当天超过 64 个后的新名字）',
    clientsCount: '去重客户端',
    connectionsCount: '连接次数',
    audienceSplit: '去重客户端按匿名、免费、会员拆开',
    clientNamesTruncated: '只列连接次数最多的前 50 个客户端。',
    noClients: '暂无客户端连接记录',
    limitedTitle: '429 来源',
    kind: '类别',
    limitKind: { burst: '分钟突发', daily: '24 小时配额', monthly: '30 天额度' },
  },
}

let installed = false

export function installMcpUsageMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
