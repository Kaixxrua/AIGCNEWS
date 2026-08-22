import { createApp } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import AppDock from '@/components/layout/AppDock.vue'
import i18n, { setAppLocale } from '@/i18n'
import { NAV_ITEMS } from '@/features/navigation/navigationModel'
import {
  __resetInstallPromptForTests,
  initializeInstallPrompt,
  showInstallEntry,
  usePwaInstall,
} from './installPrompt'

/**
 * 安装提示状态机契约：
 * - 未初始化（开发态）时 Dock 永远不出安装入口；
 * - beforeinstallprompt 捕获后入口出现，prompt() 消费后入口隐藏；
 * - accepted → 已安装态永久隐藏；dismissed → 入口保持隐藏（尊重用户拒绝）；
 * - appinstalled → 已安装态；
 * - iOS 无系统弹窗：入口点击改为展示指引卡片；
 * - standalone（已装）与 iPadOS MacIntel+touch 判定。
 */

const ORIGINAL_UA = window.navigator.userAgent
const ORIGINAL_PLATFORM = window.navigator.platform
const ORIGINAL_MAX_TOUCH = window.navigator.maxTouchPoints

const setDevice = (ua: string, platform: string, maxTouchPoints: number) => {
  Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true })
  Object.defineProperty(window.navigator, 'platform', { value: platform, configurable: true })
  Object.defineProperty(window.navigator, 'maxTouchPoints', { value: maxTouchPoints, configurable: true })
}

const restoreDevice = () => setDevice(ORIGINAL_UA, ORIGINAL_PLATFORM, ORIGINAL_MAX_TOUCH)

const dispatchBeforeInstallPrompt = (outcome: 'accepted' | 'dismissed' = 'accepted') => {
  let prompted = false
  const event = Object.assign(new Event('beforeinstallprompt', { cancelable: true }), {
    prompt: () => {
      prompted = true
      return Promise.resolve()
    },
    userChoice: Promise.resolve({ outcome, platform: 'web' }),
  })
  window.dispatchEvent(event)
  return { wasPrompted: () => prompted, event }
}

describe('installPrompt 状态机', () => {
  beforeEach(() => {
    __resetInstallPromptForTests()
    restoreDevice()
  })

  afterEach(() => {
    __resetInstallPromptForTests()
    restoreDevice()
  })

  it('未初始化时不显示安装入口（开发态守卫）', () => {
    expect(showInstallEntry.value).toBe(false)
  })

  it('捕获 beforeinstallprompt 后显示入口，prompt 消费后隐藏', async () => {
    initializeInstallPrompt()
    expect(showInstallEntry.value).toBe(false)

    const { wasPrompted } = dispatchBeforeInstallPrompt()
    expect(showInstallEntry.value).toBe(true)

    await usePwaInstall().promptInstall()
    expect(wasPrompted()).toBe(true)
    expect(showInstallEntry.value).toBe(false)
  })

  it('beforeinstallprompt 事件被 preventDefault（抑制浏览器默认迷你信息条）', () => {
    initializeInstallPrompt()
    const { event } = dispatchBeforeInstallPrompt()
    expect(event.defaultPrevented).toBe(true)
  })

  it('prompt 接受后进入已安装态，入口永久隐藏', async () => {
    initializeInstallPrompt()
    dispatchBeforeInstallPrompt('accepted')

    await usePwaInstall().promptInstall()
    expect(usePwaInstall().isInstalled.value).toBe(true)

    // 再次触发原生事件也不应复活入口（已安装后浏览器理论上不再发，防御兜底）。
    dispatchBeforeInstallPrompt()
    expect(showInstallEntry.value).toBe(false)
  })

  it('prompt 被拒绝后入口保持隐藏', async () => {
    initializeInstallPrompt()
    dispatchBeforeInstallPrompt('dismissed')
    expect(showInstallEntry.value).toBe(true)

    await usePwaInstall().promptInstall()
    expect(usePwaInstall().isInstalled.value).toBe(false)
    expect(showInstallEntry.value).toBe(false)
  })

  it('appinstalled 事件进入已安装态并隐藏入口', () => {
    initializeInstallPrompt()
    dispatchBeforeInstallPrompt()

    window.dispatchEvent(new Event('appinstalled'))
    const state = usePwaInstall()
    expect(state.isInstalled.value).toBe(true)
    expect(state.canInstall.value).toBe(false)
    expect(showInstallEntry.value).toBe(false)
  })

  it('standalone 显示模式下初始化即为已安装态', () => {
    const originalMatchMedia = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: query === '(display-mode: standalone)',
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    })) as typeof window.matchMedia

    try {
      initializeInstallPrompt()
      expect(usePwaInstall().isInstalled.value).toBe(true)
      expect(showInstallEntry.value).toBe(false)
    } finally {
      window.matchMedia = originalMatchMedia
    }
  })

  it('iOS 设备显示入口，点击改为展示指引卡片而非系统弹窗', async () => {
    setDevice(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
      'iPhone',
      5,
    )
    initializeInstallPrompt()

    const state = usePwaInstall()
    expect(state.isIOS.value).toBe(true)
    expect(showInstallEntry.value).toBe(true)

    await state.promptInstall()
    expect(state.showIOSGuide.value).toBe(true)

    state.closeIOSGuide()
    expect(state.showIOSGuide.value).toBe(false)
    // iOS 指引关闭后入口仍可再次打开（用户可能没装完就关了）。
    expect(showInstallEntry.value).toBe(true)
  })

  it('iPadOS（MacIntel + 多点触控）按 iOS 分支处理', () => {
    setDevice(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
      'MacIntel',
      5,
    )
    initializeInstallPrompt()
    expect(usePwaInstall().isIOS.value).toBe(true)
    expect(showInstallEntry.value).toBe(true)
  })

  it('桌面非 iOS 且无 beforeinstallprompt 时入口不出现', () => {
    initializeInstallPrompt()
    expect(usePwaInstall().isIOS.value).toBe(false)
    expect(showInstallEntry.value).toBe(false)
  })

  it('重复初始化幂等，事件监听不叠加', () => {
    initializeInstallPrompt()
    initializeInstallPrompt()

    dispatchBeforeInstallPrompt()
    expect(showInstallEntry.value).toBe(true)
  })
})

describe('AppDock 安装入口', () => {
  let unmount: (() => void) | undefined

  beforeEach(() => {
    __resetInstallPromptForTests()
    restoreDevice()
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    __resetInstallPromptForTests()
    restoreDevice()
    setAppLocale('zh-CN')
  })

  const mountDock = () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(AppDock, {
      items: NAV_ITEMS,
      currentPath: '/',
      isAdmin: false,
      isLoggedIn: false,
    })
    app.use(i18n)
    app.component('RouterLink', {
      inheritAttrs: true,
      props: ['to'],
      template: '<a :href="to"><slot /></a>',
    })
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }
    return host
  }

  it('入口出现时渲染安装按钮并携带中文 aria-label', () => {
    setAppLocale('zh-CN')
    initializeInstallPrompt()
    dispatchBeforeInstallPrompt()

    const host = mountDock()
    const button = host.querySelector('.dock-item--install')
    expect(button).not.toBeNull()
    expect(button?.getAttribute('aria-label')).toBe('安装应用')
  })

  it('未初始化时不渲染安装按钮', () => {
    expect(showInstallEntry.value).toBe(false)
    const host = mountDock()
    expect(host.querySelector('.dock-item--install')).toBeNull()
  })

  it('英文界面使用英文 aria-label', () => {
    setAppLocale('en-US')
    initializeInstallPrompt()
    dispatchBeforeInstallPrompt()

    const host = mountDock()
    expect(host.querySelector('.dock-item--install')?.getAttribute('aria-label')).toBe('Install app')
  })
})
