import { computed, watch, type Ref } from 'vue'
import { buildMcpAgentPrompt } from '@/features/mcp/agentSetupPrompt'
import { DSH_MCP_TOKEN_LABEL } from '@/features/mcp/dshPlugin'
import { MANUAL_MCP_TOKEN_LABEL } from '@/features/mcp/manualMcpConfig'
import { fetchMcpTokens as defaultFetchMcpTokens } from '@/services/mcp/mcpTokenApi'
import { copyToClipboard } from '@/composables/useClipboard'
import { useCopyNotice, type CopyNoticeOptions } from '@/composables/useCopyNotice'
import { useTokenConnectionWatch, type TokenConnectionWatchOptions } from '@/composables/useTokenConnectionWatch'

/**
 * /mcp 的主按钮「复制给 Agent 的配置提示词」。提示词不带 Token，游客也能复制；Agent 让客户端连 OAuth 入口，
 * 用户在浏览器里登录、点「同意」，服务端这时才发令牌，所以回显盯的是「复制之后新出现的连接」（startNew）。
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
  fetchMcpTokens?: typeof defaultFetchMcpTokens
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
  const fetchTokensApi = options.fetchMcpTokens ?? defaultFetchMcpTokens
  const connection = useTokenConnectionWatch({ now, ...options.connectionWatch, fetchTokens: () => fetchTokensApi() })
  const notice = useCopyNotice(options.copyNotice)
  const prompt = computed(() => buildMcpAgentPrompt(options.locale(), options.manualPageUrl()))
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
    const copied = await notice.copy('agent-prompt', () => write(prompt.value))
    if (!copied) return false
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
    connection.dispose()
  }

  return { prompt, copiedKey: notice.copiedKey, connection, copyPrompt, dispose }
}
