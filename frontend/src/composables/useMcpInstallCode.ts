import { readonly, shallowRef, watch, type Ref } from 'vue'
import {
  issueMcpInstallCode as defaultIssueMcpInstallCode,
  type McpInstallCode,
  type McpInstallCodePurpose,
} from '@/services/mcp/mcpTokenApi'
import { documentVisibility, type PageVisibility } from '@/composables/useTokenConnectionWatch'

/**
 * 「复制给 Agent」提示词里的一次性安装码：登录后预取一枚，只放内存，复制时同步拼进提示词——Safari 要求剪贴板写入
 * 留在点击的同一调用栈里，不能先等网络。码 10 分钟过期，只在前一半时间里写进提示词，给 Agent 留足兑换时间；
 * 快到期时提前换新，换的那一下旧码仍可复制。每复制一次就换一枚给下一次，已复制出去的那枚留在有效期里等 Agent 兑换。
 * 后台标签页里不签新码，回到前台再补。拿不到码（网络或服务故障）时 status 为 error，由调用方退回不带码的提示词或给重试。
 */
export type InstallCodeStatus = 'idle' | 'loading' | 'ready' | 'error'

/** 剩不到这么久的码不再写进提示词。 */
export const INSTALL_CODE_MIN_REMAINING_MS = 5 * 60_000
/** 可用期结束前这么久开始换新码。 */
export const INSTALL_CODE_REFRESH_LEAD_MS = 30_000

export interface McpInstallCodeOptions {
  purpose: McpInstallCodePurpose
  /** 为真时预取（已登录、页面需要码）；转假时丢掉内存里的码。 */
  enabled: Readonly<Ref<boolean>>
  issue?: ((purpose: McpInstallCodePurpose) => Promise<McpInstallCode>) | undefined
  now?: (() => number) | undefined
  schedule?: ((callback: () => void, delay: number) => ReturnType<typeof setTimeout>) | undefined
  cancelSchedule?: ((timer: ReturnType<typeof setTimeout>) => void) | undefined
  visibility?: PageVisibility | undefined
}

export const useMcpInstallCode = (options: McpInstallCodeOptions) => {
  const issue = options.issue ?? defaultIssueMcpInstallCode
  const now = options.now ?? Date.now
  const schedule = options.schedule ?? setTimeout
  const cancelSchedule = options.cancelSchedule ?? clearTimeout
  const visibility = options.visibility ?? documentVisibility
  const code = shallowRef<string | null>(null)
  const status = shallowRef<InstallCodeStatus>('idle')
  /** 码可以写进提示词的截止时刻。 */
  let freshUntil = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let inFlight = false
  let disposed = false

  const clearTimer = () => {
    if (timer !== undefined) cancelSchedule(timer)
    timer = undefined
  }
  const scheduleAt = (at: number) => {
    clearTimer()
    timer = schedule(tick, Math.max(0, at - now()))
  }

  const usable = () => code.value !== null && now() < freshUntil
  /** 该换新码了：没有码，或者已进入提前换新的那段时间。 */
  const due = () => code.value === null || now() >= freshUntil - INSTALL_CODE_REFRESH_LEAD_MS

  /** 当前能写进提示词的码；没有或剩余时间不够时为 null。 */
  const current = (): string | null => (usable() ? code.value : null)

  const reset = () => {
    generation += 1
    inFlight = false
    clearTimer()
    code.value = null
    freshUntil = 0
    status.value = 'idle'
  }

  /** 签一枚新码，在途的旧请求作废；新码到手前，还没过可用期的旧码照常可用。返回是否拿到了新码。 */
  const refresh = async (): Promise<boolean> => {
    if (disposed || !options.enabled.value) return false
    const mine = ++generation
    clearTimer()
    inFlight = true
    if (!usable()) status.value = 'loading'
    try {
      const issued = await issue(options.purpose)
      if (disposed || mine !== generation) return false
      const issuedAt = now()
      const until = issuedAt + issued.expires_in * 1000 - INSTALL_CODE_MIN_REMAINING_MS
      // 有效期短到留不出兑换时间就当没拿到：不然会一直重签。
      if (!issued.code || !(until > issuedAt)) throw new Error('install code expires too soon')
      code.value = issued.code
      freshUntil = until
      status.value = 'ready'
      scheduleAt(freshUntil - INSTALL_CODE_REFRESH_LEAD_MS)
      return true
    } catch {
      if (disposed || mine !== generation) return false
      if (usable()) {
        // 旧码还能用一阵：到它的可用期结束时再试一次。
        scheduleAt(freshUntil)
      } else {
        code.value = null
        freshUntil = 0
        status.value = 'error'
      }
      return false
    } finally {
      if (mine === generation) inFlight = false
    }
  }

  function tick() {
    timer = undefined
    if (!visibility.hidden()) {
      void refresh()
      return
    }
    // 后台标签页不签新码：旧码过了可用期就丢掉，回到前台再补。
    if (usable()) {
      scheduleAt(freshUntil)
      return
    }
    code.value = null
    freshUntil = 0
    status.value = 'idle'
  }

  const onVisibilityChange = () => {
    if (visibility.hidden() || disposed || !options.enabled.value || inFlight || !due()) return
    void refresh()
  }
  const unsubscribe = visibility.subscribe(onVisibilityChange)

  /** 这枚码已经复制出去：换一枚新的留给下一次复制（没拿到码的，也借这次重试）。 */
  const rotate = () => {
    void refresh()
  }

  const stopWatch = watch(
    () => options.enabled.value,
    (enabled) => {
      if (enabled) void refresh()
      else reset()
    },
    { immediate: true },
  )

  const dispose = () => {
    if (disposed) return
    stopWatch()
    unsubscribe()
    reset()
    disposed = true
  }

  return { code: readonly(code), status: readonly(status), current, refresh, rotate, dispose }
}

export type McpInstallCodeController = ReturnType<typeof useMcpInstallCode>
