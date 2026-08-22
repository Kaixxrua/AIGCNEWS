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
  }
}

const enUS: PwaMessages = {
  pwa: {
    updateAvailable: 'A new version is available.',
    reload: 'Reload now',
    later: 'Later',
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
