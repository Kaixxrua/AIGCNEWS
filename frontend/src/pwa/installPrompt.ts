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
const showInstallGuide = ref(false)
let prompting = false

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
 * 普通网页中的下载入口保持可见；没有原生安装事件时提供手动指引。
 * 尚未初始化、或已经作为独立应用运行时不显示。
 */
export const showInstallEntry = computed(
  () => initialized.value && !isInstalled.value,
)

export function usePwaInstall() {
  return {
    canInstall,
    isInstalled,
    isIOS,
    showInstallGuide,
    showInstallEntry,
    promptInstall,
    closeInstallGuide,
  }
}

/**
 * 注册浏览器安装事件。调用幂等，main.ts 在页面挂载后触发；独立导出也
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
  showInstallGuide.value = false
}

export async function promptInstall(): Promise<void> {
  if (!initialized.value || isInstalled.value || prompting) return

  if (isIOS.value || !deferredPrompt) {
    showInstallGuide.value = true
    return
  }

  const installEvent = deferredPrompt

  // 原生事件只能消费一次；保留入口，同时防止重复点击同一安装弹窗。
  prompting = true
  deferredPrompt = null
  canInstall.value = false
  showInstallGuide.value = false
  try {
    await installEvent.prompt()
    const choice = await installEvent.userChoice
    if (choice.outcome === 'accepted') isInstalled.value = true
  } catch {
    showInstallGuide.value = !isInstalled.value
  } finally {
    prompting = false
  }
}

export function closeInstallGuide(): void {
  showInstallGuide.value = false
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
  showInstallGuide.value = false
  prompting = false
}
