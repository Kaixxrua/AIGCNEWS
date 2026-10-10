import axios from 'axios'
import { ref } from 'vue'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import {
  TIPS_AFTER_MS,
  WATCH_LIMIT_MS,
  captureTokenBaseline,
  parseTimestampMs,
  pollDelayMs,
  sightNewConnection,
  sightToken,
  usedSinceBaseline,
  type TokenBaseline,
} from '@/features/mcp/tokenConnectionModel'

/**
 * 看用户电脑上的客户端连没连上（判据见 tokenConnectionModel）。两种盯法：
 * - start(令牌)：盯一枚刚交给用户的令牌（手动配置、dsh）；
 * - startNew()：盯「复制给 Agent」之后新出现的连接（OAuth 授权时服务端才发令牌，事先不知道是哪枚）。
 * 状态：
 * - waiting：在等第一次连接；paused：等满十分钟（或登录失效）停了，用户点「再检查」或复制命令再接着等；
 * - authorized：只在 startNew 里出现，新令牌已发出但客户端还没用它连过来；等满十分钟也停在这里，可以再检查；
 * - connected：fresh 为真是这次亲眼看到连上，为假是 dsh 复用的令牌以前连过（此时只在用户复制命令或点「再检查」后才轮询，
 *   打开页面看看的老用户不发请求）；gone：令牌已被删除、重新生成或过期。
 * 只在页面可见时轮询；用户从终端切回来时立刻查一次并重新计时。令牌明文从不经过这里，只用 id 对列表。
 */
export type TokenConnectionStatus = 'idle' | 'waiting' | 'authorized' | 'paused' | 'connected' | 'gone'

export interface NewConnectionWatchOptions {
  /** 页面晚于复制才开始盯时，复制的时刻（往前留些余量）；此后创建的令牌不算旧的。 */
  sinceMs?: number | null
  /** 有自己检测的令牌（dsh 专用、手动配置），按标签排除。 */
  ignoreLabels?: readonly string[]
}

type WatchTarget =
  | { kind: 'token'; id: number }
  | { kind: 'new'; sinceMs: number | null; ignoreLabels: readonly string[]; baseline: TokenBaseline | null }

export interface PageVisibility {
  hidden: () => boolean
  subscribe: (listener: () => void) => () => void
}

export interface TokenConnectionWatchOptions {
  fetchTokens: () => Promise<McpTokenMetadata[]>
  now?: () => number
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void
  visibility?: PageVisibility
}

export const documentVisibility: PageVisibility = {
  hidden: () => typeof document !== 'undefined' && document.visibilityState === 'hidden',
  subscribe: (listener) => {
    if (typeof document === 'undefined') return () => {}
    document.addEventListener('visibilitychange', listener)
    return () => document.removeEventListener('visibilitychange', listener)
  },
}

export const useTokenConnectionWatch = (options: TokenConnectionWatchOptions) => {
  const now = options.now ?? Date.now
  const schedule = options.schedule ?? setTimeout
  const cancelSchedule = options.cancelSchedule ?? clearTimeout
  const visibility = options.visibility ?? documentVisibility

  const status = ref<TokenConnectionStatus>('idle')
  /** 服务端记下的最近一次使用时间（ISO）；以前连过的复用令牌一开始就有值。 */
  const lastUsedAt = ref<string | null>(null)
  /** 这次检测期间亲眼看到连上，而不是以前连过。 */
  const fresh = ref(false)
  /** 等了 TIPS_AFTER_MS 还没连上：界面据此展开排障提示；置位后直到换令牌都不收回。 */
  const slow = ref(false)
  /** 用户点「再检查」后的那一次查询还没回来；自动轮询不动它，免得按钮文案每几秒闪一下。 */
  const checking = ref(false)
  /** startNew 看到的客户端名（OAuth 注册时客户端报的名字）。 */
  const clientLabel = ref<string | null>(null)

  let target: WatchTarget | null = null
  let baselineMs: number | null = null
  let watchStartMs = 0
  let windowStartMs = 0
  let windowOpen = false
  /** 在等一次新的连接：新令牌一开始就是；以前连过的复用令牌要等用户复制命令或点「再检查」。 */
  let armed = false
  let generation = 0
  let inflightGeneration = -1
  let timer: ReturnType<typeof setTimeout> | undefined
  let unsubscribe: (() => void) | null = null
  let disposed = false

  const clearTimer = () => {
    if (timer !== undefined) cancelSchedule(timer)
    timer = undefined
  }

  const closeWindow = () => {
    clearTimer()
    windowOpen = false
  }

  const scheduleNext = () => {
    clearTimer()
    if (!windowOpen || target == null || visibility.hidden()) return
    const elapsed = now() - windowStartMs
    if (elapsed >= WATCH_LIMIT_MS) {
      windowOpen = false
      if (status.value === 'waiting') status.value = 'paused'
      return
    }
    timer = schedule(() => {
      timer = undefined
      void poll()
    }, pollDelayMs(elapsed))
  }

  const markConnected = () => {
    closeWindow()
    armed = false
    fresh.value = true
    status.value = 'connected'
  }

  /** 对照一枚令牌；返回 false 表示不用再查了。 */
  const sightTarget = (tokens: McpTokenMetadata[], id: number): boolean => {
    const sighting = sightToken(tokens, id, now())
    if (sighting.kind === 'gone') {
      closeWindow()
      armed = false
      status.value = 'gone'
      return false
    }
    if (sighting.kind === 'used') lastUsedAt.value = sighting.lastUsedAt
    if (usedSinceBaseline(sighting, baselineMs)) {
      markConnected()
      return false
    }
    return true
  }

  /** 对照基线找新连接；第一次查到列表时先记基线。 */
  const sightNew = (tokens: McpTokenMetadata[], watched: Extract<WatchTarget, { kind: 'new' }>): boolean => {
    watched.baseline ??= captureTokenBaseline(tokens, watched.sinceMs)
    const sighting = sightNewConnection(tokens, watched.baseline, now(), watched.ignoreLabels)
    if (sighting.kind === 'connected') {
      clientLabel.value = sighting.label
      lastUsedAt.value = sighting.lastUsedAt
      markConnected()
      return false
    }
    if (sighting.kind === 'authorized') {
      clientLabel.value = sighting.label
      if (status.value === 'waiting' || status.value === 'paused') status.value = 'authorized'
    } else if (status.value === 'authorized') {
      // 刚发的令牌又没了（用户撤销或客户端重新授权）：接着等下一枚。
      clientLabel.value = null
      status.value = 'waiting'
    }
    return true
  }

  const poll = async () => {
    if (disposed || target == null || inflightGeneration === generation) return
    const current = generation
    const watched = target
    inflightGeneration = current
    let keepGoing = true
    try {
      const tokens = await options.fetchTokens()
      if (current !== generation) return
      keepGoing = watched.kind === 'token' ? sightTarget(tokens, watched.id) : sightNew(tokens, watched)
      if (!keepGoing) return
      const pending = status.value === 'waiting' || status.value === 'authorized'
      if (pending && now() - watchStartMs >= TIPS_AFTER_MS) slow.value = true
    } catch (error) {
      if (current !== generation) return
      // 登录失效就别空转了，视图的认证监听会接着清掉令牌；其余失败（重启、网络闪断）下一拍再试。
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        closeWindow()
        armed = false
        if (status.value === 'waiting') status.value = 'paused'
        keepGoing = false
      }
    } finally {
      if (inflightGeneration === current) inflightGeneration = -1
      if (current === generation) checking.value = false
    }
    if (keepGoing && current === generation) scheduleNext()
  }

  /** 重新开始计时窗口：前一分钟勤快地查，满十分钟停下。 */
  const openWindow = () => {
    windowStartMs = now()
    windowOpen = true
  }

  const canWaitForMore = () => (
    !disposed && target != null && status.value !== 'gone' && !(status.value === 'connected' && fresh.value)
  )

  const onVisibilityChange = () => {
    if (visibility.hidden()) {
      clearTimer()
      return
    }
    // 用户从终端切回来，多半刚装好：立刻看一眼，并重新计时。
    if (!armed || !canWaitForMore()) return
    if (status.value === 'paused') status.value = 'waiting'
    openWindow()
    clearTimer()
    void poll()
  }

  const stop = () => {
    generation += 1
    closeWindow()
    armed = false
    target = null
    baselineMs = null
    status.value = 'idle'
    lastUsedAt.value = null
    fresh.value = false
    slow.value = false
    checking.value = false
    clientLabel.value = null
    unsubscribe?.()
    unsubscribe = null
  }

  const start = (metadata: McpTokenMetadata) => {
    if (disposed) return
    stop()
    target = { kind: 'token', id: metadata.id }
    baselineMs = parseTimestampMs(metadata.last_used_at)
    lastUsedAt.value = baselineMs == null ? null : metadata.last_used_at ?? null
    watchStartMs = now()
    unsubscribe = visibility.subscribe(onVisibilityChange)
    if (baselineMs != null) {
      status.value = 'connected'
      return
    }
    status.value = 'waiting'
    armed = true
    openWindow()
    scheduleNext()
  }

  /** 用户刚复制了给 Agent 的提示词：马上查一次记下现有令牌，之后等新连接。 */
  const startNew = (watchOptions: NewConnectionWatchOptions = {}) => {
    if (disposed) return
    stop()
    target = { kind: 'new', sinceMs: watchOptions.sinceMs ?? null, ignoreLabels: watchOptions.ignoreLabels ?? [], baseline: null }
    watchStartMs = now()
    unsubscribe = visibility.subscribe(onVisibilityChange)
    status.value = 'waiting'
    armed = true
    openWindow()
    void poll()
  }

  /** 用户刚复制了命令：接下来几分钟最可能连上，重新开始勤快地查。 */
  const nudge = () => {
    if (!canWaitForMore()) return
    armed = true
    if (status.value === 'paused') status.value = 'waiting'
    openWindow()
    if (inflightGeneration !== generation) scheduleNext()
  }

  const checkNow = () => {
    if (!canWaitForMore()) return
    armed = true
    if (status.value === 'paused') status.value = 'waiting'
    openWindow()
    clearTimer()
    checking.value = true
    void poll()
  }

  const dispose = () => {
    stop()
    disposed = true
  }

  return { status, lastUsedAt, fresh, slow, checking, clientLabel, start, startNew, nudge, checkNow, stop, dispose }
}

export type TokenConnectionWatch = ReturnType<typeof useTokenConnectionWatch>
