import i18n from '@/i18n'

/**
 * PWA 更新提示文案独立成文件：主 locale 表（en-US.ts / zh-CN.ts）由其他
 * 工作流维护，本文件在 PWA 模块初始化时经 mergeLocaleMessage 注入 pwa.*
 * 命名空间。沿用仓库约定：zh 深合并 en，缺失键回退英文。
 */

// 用 type 而非 interface：对象字面量类型带隐式索引签名，才能与
// MessageTree（Record<string, unknown>）双向比较并作为 deepMerge 参数。
type PwaMessages = {
  pwa: {
    updateAvailable: string
    reload: string
    later: string
    installApp: string
    iosGuideTitle: string
    iosGuideStepShare: string
    iosGuideStepAdd: string
    iosGuideNote: string
    browserGuideTitle: string
    browserGuideStepOpen: string
    browserGuideStepInstall: string
    browserGuideNote: string
    gotIt: string
  }
}

const enUS: PwaMessages = {
  pwa: {
    updateAvailable: 'A new version is available.',
    reload: 'Reload now',
    later: 'Later',
    installApp: 'Install app',
    iosGuideTitle: 'Add to Home Screen',
    iosGuideStepShare: 'Tap the Share button in Safari’s toolbar.',
    iosGuideStepAdd: 'Choose “Add to Home Screen” from the share sheet.',
    iosGuideNote: 'iOS installs this site from Safari; there is no native prompt.',
    browserGuideTitle: 'Install AIGCNEWS',
    browserGuideStepOpen: 'Open this site in Chrome or Edge.',
    browserGuideStepInstall: 'In the browser menu, choose “Install app” or “Add to Home Screen”.',
    browserGuideNote: 'If installation is unavailable, bookmark this page to return anytime.',
    gotIt: 'Got it',
  },
}

type MessageTree = Record<string, unknown>

// 与 locales/zh-CN.ts 同款深合并：对象递归、叶子以 patch 覆盖 base。
const deepMerge = (base: MessageTree, patch: MessageTree): MessageTree => Object.fromEntries(
  Object.entries(base).map(([key, value]) => [
    key,
    value && typeof value === 'object' && !Array.isArray(value)
      ? deepMerge(value as MessageTree, (patch?.[key] ?? {}) as MessageTree)
      : patch?.[key] ?? value,
  ]),
)

const zhCN = deepMerge(enUS, {
  pwa: {
    updateAvailable: '发现新版本。',
    reload: '立即更新',
    later: '稍后',
    installApp: '安装应用',
    iosGuideTitle: '添加到主屏幕',
    iosGuideStepShare: '在 Safari 工具栏中点击「分享」按钮。',
    iosGuideStepAdd: '在分享菜单中选择「添加到主屏幕」。',
    iosGuideNote: 'iOS 需要通过 Safari 手动安装本站点，没有系统弹窗。',
    browserGuideTitle: '安装 AIGCNEWS',
    browserGuideStepOpen: '使用 Chrome 或 Edge 浏览器打开本站。',
    browserGuideStepInstall: '在浏览器菜单中选择「安装应用」或「添加到主屏幕」。',
    browserGuideNote: '如果没有安装选项，可以先收藏网页，随时回来访问。',
    gotIt: '知道了',
  },
}) as PwaMessages

let installed = false

export function installPwaMessages(): void {
  // 幂等：registerPwa 只调用一次，这里仍防御重复注入。
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
