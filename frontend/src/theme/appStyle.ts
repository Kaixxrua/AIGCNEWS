/**
 * 页面风格：漫画（默认）与简洁两版。简洁版去掉贴纸、网点、荧光笔和硬投影，配色、字重和间距收成办公软件的样子，
 * 和浅色/深色主题互相独立，两两组合都可用。选择只记在本机。
 */
export const APP_STYLES = ['comic', 'simple'] as const
export type AppStyle = typeof APP_STYLES[number]

export const DEFAULT_STYLE: AppStyle = 'comic'
export const STYLE_STORAGE_KEY = 'app_style'
export const STYLE_ATTRIBUTE = 'data-style'
export const STYLE_SIMPLE_VALUE = 'simple'
/** 分享链接带上 ?style=simple（或 comic）就以那一版打开，并记作这台设备的选择。 */
export const STYLE_QUERY_PARAM = 'style'

export function isAppStyle(value: unknown): value is AppStyle {
  return typeof value === 'string' && (APP_STYLES as readonly string[]).includes(value)
}

function readSavedStyle(storage?: Pick<Storage, 'getItem'> | null): AppStyle | null {
  if (!storage) return null
  try {
    const saved = storage.getItem(STYLE_STORAGE_KEY)
    return isAppStyle(saved) ? saved : null
  } catch {
    return null
  }
}

/** 地址里的 ?style=：合法值才算数，别的值当作没写。 */
export function readStyleParam(search: string): AppStyle | null {
  const value = new URLSearchParams(search).get(STYLE_QUERY_PARAM)
  return isAppStyle(value) ? value : null
}

export interface StyleResolutionOptions {
  storage?: Pick<Storage, 'getItem'> | null
  search?: string
}

// 解析顺序：地址参数 → 存储值 → 默认漫画版。
export function resolveAppStyle(options: StyleResolutionOptions = {}): AppStyle {
  const search = options.search ?? (typeof window === 'undefined' ? '' : window.location.search)
  const fromLink = readStyleParam(search)
  if (fromLink) return fromLink
  const storage = options.storage === undefined
    ? (typeof window === 'undefined' ? null : window.localStorage)
    : options.storage
  return readSavedStyle(storage) ?? DEFAULT_STYLE
}

export function persistAppStyle(
  style: AppStyle,
  storage: Pick<Storage, 'setItem'> | null = typeof window === 'undefined' ? null : window.localStorage,
): void {
  if (!storage) return
  try {
    storage.setItem(STYLE_STORAGE_KEY, style)
  } catch {
    // 存不了就只在这次打开时有效。
  }
}

export function applyDocumentStyle(
  style: AppStyle,
  documentElement: Pick<HTMLElement, 'setAttribute' | 'removeAttribute'> | null = typeof document === 'undefined' ? null : document.documentElement,
): void {
  if (!documentElement) return
  if (style === 'simple') documentElement.setAttribute(STYLE_ATTRIBUTE, STYLE_SIMPLE_VALUE)
  else documentElement.removeAttribute(STYLE_ATTRIBUTE)
}

/**
 * 记下地址参数选的那一版之后把参数从地址里拿掉，其余参数原样保留：路由不会把它带进各页的查询条件，
 * 刷新和复制出去的链接也都干净。要在路由接管地址之前调用。
 */
export function consumeStyleParam(
  location: Pick<Location, 'pathname' | 'search' | 'hash'> = window.location,
  history: Pick<History, 'replaceState' | 'state'> = window.history,
): AppStyle | null {
  const style = readStyleParam(location.search)
  if (!style) return null
  const params = new URLSearchParams(location.search)
  params.delete(STYLE_QUERY_PARAM)
  const query = params.toString()
  try {
    history.replaceState(history.state, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`)
  } catch {
    // 改不了地址也不影响这次以哪一版打开。
  }
  return style
}
