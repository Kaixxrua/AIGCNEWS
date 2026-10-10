import { computed, watch, type Ref } from 'vue'
import { buildMcpAgentPrompt } from '@/features/mcp/agentSetupPrompt'
import { COMMAND_TOKEN_SLOT } from '@/features/mcp/commandPreview'
import { DSH_MCP_TOKEN_LABEL } from '@/features/mcp/dshPlugin'
import { MANUAL_MCP_TOKEN_LABEL } from '@/features/mcp/manualMcpConfig'
import { fetchMcpTokens as defaultFetchMcpTokens, issueMcpInstallCode } from '@/services/mcp/mcpTokenApi'
import { copySensitiveToClipboard, copyToClipboard } from '@/composables/useClipboard'
import { useCopyNotice, type CopyNoticeOptions } from '@/composables/useCopyNotice'
import { useMcpInstallCode, type McpInstallCodeOptions } from '@/composables/useMcpInstallCode'
import { useTokenConnectionWatch, type TokenConnectionWatchOptions } from '@/composables/useTokenConnectionWatch'

/**
 * /mcp 的主按钮「复制给 Agent 的配置提示词」。提示词不带 Token，游客也能复制；Agent 让客户端连 OAuth 入口，
 * 用户在浏览器里登录、点「同意」，服务端这时才发令牌，所以回显盯的是「复制之后新出现的连接」（startNew）。
 * 登录了还会附一枚预取的一次性安装码，给不支持浏览器授权的客户端在本机换 Token（新令牌同样被 startNew 盯到）；
 * 带码的提示词只走安全剪贴板，复制后换一枚新码留给下一次。拿不到码时预览与复制都退回不带码的版本。
 * 只有登录了才盯得到（要读自己的令牌列表）：游客复制后在这页登录，或复制后刷新了页面，按记下的复制时刻接着等。
 * 复制时刻只记在本标签页的 sessionStorage，半小时作废，登出即清。
 */
export const AGENT_COPIED_AT_KEY = 'aigcnews:mcp-agent-copied-at'
const COPIED_AT_TTL_MS = 30 * 60_000
/** 浏览器与服务器的时钟可能差一点：往前留一分钟，免得复制后才授权的令牌被当成旧的。 */
const CLOCK_MARGIN_MS = 60_000
/** dsh 与手动配置的令牌各有自己的回显，这里不算。 */
const IGNORE_LABELS = [DSH_MCP_TOKEN_LABEL, MANUAL_MCP_TOKEN_LABEL]

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

export interface McpAgentSetupOptions {
  /** 已登录（auth status 为 authenticated）。 */
  signedIn: Readonly<Ref<boolean>>
  locale: () => string
  /** 当前入口的 /mcp 页，提示词里让不支持 OAuth 的客户端回到这里的「手动配置」。 */
  manualPageUrl: () => string
  write?: (text: string) => Promise<void>
  /** 带安装码的提示词走它：缺省 copySensitiveToClipboard，不退回把明文写进 DOM 的 textarea。 */
  writeSensitive?: (text: string) => Promise<void>
  fetchMcpTokens?: typeof defaultFetchMcpTokens
  issueInstallCode?: typeof issueMcpInstallCode
  /** 测试注入安装码的时钟、定时器与页面可见性。 */
  installCode?: Pick<McpInstallCodeOptions, 'now' | 'schedule' | 'cancelSchedule' | 'visibility'>
  /** 缺省用 sessionStorage；传 null 只记在内存里。 */
  storage?: StorageLike | null
  now?: () => number
  connectionWatch?: Omit<TokenConnectionWatchOptions, 'fetchTokens'>
  copyNotice?: CopyNoticeOptions
}

const sessionStorageOrNull = (): StorageLike | null => {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

export const useMcpAgentSetup = (options: McpAgentSetupOptions) => {
  const now = options.now ?? Date.now
  const storage = options.storage === undefined ? sessionStorageOrNull() : options.storage
  const write = options.write ?? copyToClipboard
  const writeSensitive = options.writeSensitive ?? copySensitiveToClipboard
  const fetchTokensApi = options.fetchMcpTokens ?? defaultFetchMcpTokens
  const connection = useTokenConnectionWatch({ now, ...options.connectionWatch, fetchTokens: () => fetchTokensApi() })
  const notice = useCopyNotice(options.copyNotice)
  const installCode = useMcpInstallCode({
    visibility: options.connectionWatch?.visibility,
    ...options.installCode,
    purpose: 'mcp',
    enabled: options.signedIn,
    issue: options.issueInstallCode,
  })
  /** 提示词会带安装码那一步：登录了且没有拿码失败。 */
  const installCodeAvailable = computed(() => options.signedIn.value && installCode.status.value !== 'error')
  /** 页面上展示的提示词：在安装码处放占位，真码只在复制出去的文本里；拿不到码时与复制出去的一样不带这一步。 */
  const prompt = computed(() =>
    buildMcpAgentPrompt(options.locale(), options.manualPageUrl(), installCodeAvailable.value ? COMMAND_TOKEN_SLOT : null),
  )
  /** 安装码已备好：预览里的占位显示「已填入」。 */
  const installCodeReady = computed(() => options.signedIn.value && installCode.status.value === 'ready')
  let copiedAtInMemory: number | null = null

  const readCopiedAt = (): number | null => {
    let stored: string | null = null
    try { stored = storage?.getItem(AGENT_COPIED_AT_KEY) ?? null } catch { /* 读不到就用内存里的 */ }
    const at = stored == null ? copiedAtInMemory : Number(stored)
    if (at == null || !Number.isFinite(at) || now() - at > COPIED_AT_TTL_MS || at > now() + CLOCK_MARGIN_MS) return null
    return at
  }
  const rememberCopy = (at: number) => {
    copiedAtInMemory = at
    try { storage?.setItem(AGENT_COPIED_AT_KEY, String(at)) } catch { /* 存不下就只记在内存里 */ }
  }
  const forgetCopy = () => {
    copiedAtInMemory = null
    try { storage?.removeItem(AGENT_COPIED_AT_KEY) } catch { /* 无事可做 */ }
  }

  const watchNewConnections = (sinceMs: number | null) => connection.startNew({ sinceMs, ignoreLabels: IGNORE_LABELS })

  /** 复制提示词；登录了就开始（或重新勤快地）等新连接。返回是否复制成功。 */
  const copyPrompt = async (): Promise<boolean> => {
    // 码在点击前已备好，同步拼进提示词：剪贴板写入不能先等网络（Safari 会拒绝）。
    const code = options.signedIn.value ? installCode.current() : null
    const text = buildMcpAgentPrompt(options.locale(), options.manualPageUrl(), code)
    const copied = await notice.copy('agent-prompt', () => (code ? writeSensitive(text) : write(text)))
    if (!copied) return false
    // 复制出去的码留给 Agent，换一枚新的给下一次；没拿到码的也借这次重试。游客不签码。
    installCode.rotate()
    rememberCopy(now())
    if (!options.signedIn.value) return true
    const status = connection.status.value
    // 刚复制的这次马上记下现有令牌；已经接入过的再复制一次，就是要接下一个客户端，重新开始等。
    if (status === 'idle' || status === 'connected') watchNewConnections(null)
    else connection.nudge()
    return true
  }

  const stopWatch = watch(options.signedIn, (signedIn, wasSignedIn) => {
    if (!signedIn) {
      connection.stop()
      // 登出：这个标签页的复制记录不带给下一个账号。
      if (wasSignedIn) forgetCopy()
      return
    }
    const copiedAt = readCopiedAt()
    if (copiedAt != null && connection.status.value === 'idle') watchNewConnections(copiedAt - CLOCK_MARGIN_MS)
  }, { immediate: true })

  const dispose = () => {
    stopWatch()
    notice.dispose()
    installCode.dispose()
    connection.dispose()
  }

  return { prompt, installCodeAvailable, installCodeReady, copiedKey: notice.copiedKey, connection, copyPrompt, dispose }
}
