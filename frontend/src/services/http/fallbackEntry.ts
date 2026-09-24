import { computed, ref } from 'vue'

/**
 * 备用入口回退。主站 aigcnews.cn 按 GeoDNS 分线路，境内解析到国内边缘；
 * 开着「禁止回国流量」代理的访客在国内解析、从海外出口连接会被代理掐断，
 * 页面壳来自 Service Worker 缓存，接口全部 Network Error。
 * aigcradar.online 全线路指向日本边缘，是同源完整镜像。
 *
 * 只有主站接口从未加载成功（本页生命周期内没有任何 HTTP 响应）时才自动
 * 整页跳转；曾经加载成功后才断开多半是临时网络问题，只给可关闭的提示。
 * 跳转前用图片探测镜像可达（CSP connect-src 'self' 不允许跨域请求，
 * img-src 放行 https:），探测失败则不跳，避免把访客送到同样打不开的页面。
 */
export const FALLBACK_ENTRY_ORIGIN = 'https://aigcradar.online'

const PRIMARY_ENTRY_HOSTNAMES = new Set(['aigcnews.cn', 'www.aigcnews.cn'])

// 单次抖动不打扰访客；连续两次拿不到任何响应才处理。
const FAILURE_THRESHOLD = 2
const PROBE_TIMEOUT_MS = 5000

export function isPrimaryEntryHost(hostname: string): boolean {
  return PRIMARY_ENTRY_HOSTNAMES.has(hostname)
}

// 只认没有 HTTP 响应的连接层失败；取消（ERR_CANCELED）与超时（ECONNABORTED）
// 说明链路可达或请求被主动放弃，换入口无济于事。
export function isNetworkLevelFailure(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const candidate = error as { response?: unknown; code?: unknown }
  return candidate.response === undefined && candidate.code === 'ERR_NETWORK'
}

export function buildFallbackEntryUrl(fullPath: string): string {
  const path = fullPath.startsWith('/') ? fullPath : `/${fullPath}`
  return `${FALLBACK_ENTRY_ORIGIN}${path}`
}

function probeImage(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const image = new Image()
    const timer = setTimeout(() => settle(false), PROBE_TIMEOUT_MS)
    function settle(reachable: boolean) {
      clearTimeout(timer)
      image.onload = null
      image.onerror = null
      resolve(reachable)
    }
    image.onload = () => settle(true)
    image.onerror = () => settle(false)
    image.src = url
  })
}

type FallbackEntryEnvironment = {
  hostname: () => string
  online: () => boolean
  currentPath: () => string
  probe: (url: string) => Promise<boolean>
  redirect: (url: string) => void
}

const browserEnvironment: FallbackEntryEnvironment = {
  hostname: () => (typeof window === 'undefined' ? '' : window.location.hostname),
  online: () => (typeof navigator === 'undefined' ? true : navigator.onLine !== false),
  currentPath: () => `${window.location.pathname}${window.location.search}${window.location.hash}`,
  probe: probeImage,
  redirect: (url) => window.location.replace(url),
}

export function createFallbackEntryState(environment: FallbackEntryEnvironment = browserEnvironment) {
  const consecutiveFailures = ref(0)
  const loadedOnce = ref(false)
  const mirrorReachable = ref(false)
  const dismissed = ref(false)
  let probing = false

  const eligible = () =>
    consecutiveFailures.value >= FAILURE_THRESHOLD
    && isPrimaryEntryHost(environment.hostname())
    && environment.online()

  // 每段失败只探测一次；探测期间主站恢复则放弃跳转。
  const checkMirror = () => {
    if (probing || mirrorReachable.value || !eligible()) return
    probing = true
    void environment.probe(`${FALLBACK_ENTRY_ORIGIN}/favicon.svg?probe=${Date.now()}`).then((reachable) => {
      probing = false
      if (!reachable || !eligible()) return
      mirrorReachable.value = true
      if (!loadedOnce.value) environment.redirect(buildFallbackEntryUrl(environment.currentPath()))
    })
  }

  // 任何 HTTP 响应（含 4xx/5xx）都证明主站可达。
  const recordResponse = () => {
    consecutiveFailures.value = 0
    loadedOnce.value = true
    mirrorReachable.value = false
  }
  const recordFailure = (error: unknown) => {
    if (isNetworkLevelFailure(error)) {
      consecutiveFailures.value += 1
      checkMirror()
    } else if ((error as { response?: unknown } | null)?.response !== undefined) {
      recordResponse()
    }
  }
  const dismiss = () => {
    dismissed.value = true
  }
  // 自动跳转之外的兜底：页面曾加载成功后断开时，给一个可关闭的手动入口。
  const shouldOffer = computed(() =>
    !dismissed.value
    && loadedOnce.value
    && mirrorReachable.value
    && eligible(),
  )

  return { recordResponse, recordFailure, dismiss, shouldOffer }
}

export const fallbackEntryState = createFallbackEntryState()
