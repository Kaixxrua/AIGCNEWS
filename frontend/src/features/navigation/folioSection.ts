import { NAV_ITEMS, isNavigationItemActive } from './navigationModel'

/** 内页报眉的版名：`key` 对应 `masthead.sections.*` 文案，`edition` 是版次字母（dock 外的页面没有）。 */
export interface FolioSection {
  key: string
  edition: string | null
}

// dock 上的栏目按 dock 顺序编版：首页是 A 版，往右依次 B、C……；用静态顺序，某个入口被开关隐藏时
// 其余各版的字母不跟着挪。
const NAV_SECTION_KEYS: Readonly<Record<string, string>> = {
  '/projects': 'projects',
  '/ui-library': 'uiLibrary',
  '/projects?source=website': 'websites',
  '/report': 'report',
  '/x': 'xboard',
  '/mcp': 'mcp',
  '/dsh': 'dsh',
  '/subscriptions': 'subscriptions',
  '/membership': 'membership',
  '/contact': 'contact',
  '/monitor': 'monitor',
}

// dock 外的内页只给版名。
const PAGE_SECTION_KEYS: Readonly<Record<string, string>> = {
  'paper-read': 'paper',
  disclaimer: 'disclaimer',
  privacy: 'privacy',
}

export function folioSection(
  path: string,
  query: Readonly<Record<string, unknown>>,
  routeName: string,
): FolioSection | null {
  const index = NAV_ITEMS.findIndex((item) => item.to !== '/' && isNavigationItemActive(item, path, query))
  const key = index >= 0 ? NAV_SECTION_KEYS[NAV_ITEMS[index]!.to] : undefined
  if (key) return { key, edition: String.fromCharCode(65 + index) }
  const pageKey = PAGE_SECTION_KEYS[routeName]
  return pageKey ? { key: pageKey, edition: null } : null
}
