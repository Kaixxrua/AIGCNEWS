import i18n from '@/i18n'

/**
 * 备用入口提示文案独立成文件，沿用 pwa.ts 的注入方式：主 locale 表由其他
 * 工作流维护，这里在组件初始化时经 mergeLocaleMessage 注入 fallbackEntry.*。
 */

type FallbackEntryMessages = {
  fallbackEntry: {
    message: string
    open: string
    dismiss: string
  }
}

const enUS: FallbackEntryMessages = {
  fallbackEntry: {
    message: 'Your network can’t reach the AIGC NEWS main site right now. The backup entry serves the same content.',
    open: 'Open backup entry aigcradar.online',
    dismiss: 'Dismiss',
  },
}

const zhCN: FallbackEntryMessages = {
  fallbackEntry: {
    message: '当前网络连不上 AIGC NEWS 主站，可以切换到内容相同的备用入口继续浏览。',
    open: '打开备用入口 aigcradar.online',
    dismiss: '关闭',
  },
}

let installed = false

export function installFallbackEntryMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
