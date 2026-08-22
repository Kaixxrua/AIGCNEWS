import { computed, ref } from 'vue'

import { installPwaMessages } from '@/i18n/locales/pwa'

/**
 * 浏览器原生安装提示的最小类型。BeforeInstallPromptEvent 目前仍未进入
 * TypeScript DOM 标准库，所以只声明本模块实际消费的字段。
 */
export type BeforeInstallPromptEventLike = Event & {
  prompt: () => Promise<void> | void
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

const initialized = ref(false)
const canInstall = ref(false)
const isInstalled = ref(false)
const isIOS = ref(false)
const showIOSGuide = ref(false)

let deferredPrompt: BeforeInstallPromptEventLike | null = null

const isStandaloneDisplayMode = (): boolean => {
  if (typeof window === 'undefined') return false
  const standaloneNavigator = window.navigator as Navigator & { standalone?: boolean }
  return Boolean(
    standaloneNavigator.standalone === true
      || window.matchMedia?.('(display-mode: standalone)').matches,
  )
}

const isIOSDevice = (): boolean => {
  if (typeof window === 'undefined') return false
  const { navigator } = window
  // iPadOS 13+ reports itself as Macintosh while exposing touch points.
  return /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

/**
 * 可观察的入口状态。入口只有在生产初始化完成后才会出现，避免开发环境
 * 的 AppDock 因浏览器能力检测而显示不可用的安装按钮。
 */
export const showInstallEntry = computed(
  () => initialized.value && !isInstalled.value && (canInstall.value || isIOS.value),
)

export function usePwaInstall() {
  return {
    canInstall,
    isInstalled,
    isIOS,
    showIOSGuide,
    showInstallEntry,
    promptInstall,
    closeIOSGuide,
  }
}

/**
 * 注册浏览器安装事件。调用幂等，main.ts 仅在生产环境触发；独立导出也
 * 方便契约测试在 jsdom 中验证 Android/桌面与 iOS 两条分支。
 */
export function initializeInstallPrompt(): void {
  if (initialized.value || typeof window === 'undefined') return

  installPwaMessages()
  isInstalled.value = isStandaloneDisplayMode()
  isIOS.value = isIOSDevice()
  initialized.value = true

  window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt)
  window.addEventListener('appinstalled', handleAppInstalled)
}

function handleBeforeInstallPrompt(event: Event): void {
  const installEvent = event as BeforeInstallPromptEventLike
  if (typeof installEvent.prompt !== 'function' || !installEvent.userChoice) return

  event.preventDefault()
  deferredPrompt = installEvent
  canInstall.value = true
}

function handleAppInstalled(): void {
  deferredPrompt = null
  canInstall.value = false
  isInstalled.value = true
  showIOSGuide.value = false
}

export async function promptInstall(): Promise<void> {
  if (isInstalled.value) return

  if (isIOS.value) {
    showIOSGuide.value = true
    return
  }

  const installEvent = deferredPrompt
  if (!installEvent) return

  // The browser permits prompt() only once per event. Hide the entry before
  // opening the native dialog so a second click cannot race the same event.
  deferredPrompt = null
  canInstall.value = false
  await installEvent.prompt()

  const choice = await installEvent.userChoice
  if (choice.outcome === 'accepted') {
    isInstalled.value = true
  }
}

export function closeIOSGuide(): void {
  showIOSGuide.value = false
}

/**
 * 仅供测试：恢复模块到未初始化态并摘掉事件监听。生产代码不调用——
 * 安装状态机在一次会话内只允许单向推进。
 */
export function __resetInstallPromptForTests(): void {
  if (typeof window !== 'undefined' && initialized.value) {
    window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt)
    window.removeEventListener('appinstalled', handleAppInstalled)
  }
  deferredPrompt = null
  initialized.value = false
  canInstall.value = false
  isInstalled.value = false
  isIOS.value = false
  showIOSGuide.value = false
}
