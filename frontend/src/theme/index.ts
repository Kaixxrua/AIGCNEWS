import { readonly, ref } from 'vue'
import {
  applyDocumentTheme,
  DEFAULT_THEME,
  persistAppTheme,
  resolveAppTheme,
  type AppTheme,
} from './theme'
import {
  applyDocumentStyle,
  consumeStyleParam,
  DEFAULT_STYLE,
  persistAppStyle,
  resolveAppStyle,
  type AppStyle,
} from './appStyle'
import { ensureSimpleStyles } from './simpleStyles'

export { APP_THEMES, DEFAULT_THEME, THEME_ATTRIBUTE, THEME_STORAGE_KEY, applyDocumentTheme, isAppTheme, persistAppTheme, resolveAppTheme } from './theme'
export type { AppTheme } from './theme'
export { APP_STYLES, DEFAULT_STYLE, STYLE_ATTRIBUTE, STYLE_QUERY_PARAM, STYLE_STORAGE_KEY, applyDocumentStyle, isAppStyle, persistAppStyle, resolveAppStyle } from './appStyle'
export type { AppStyle } from './appStyle'
export { ensureSimpleStyles } from './simpleStyles'

const currentTheme = ref<AppTheme>(DEFAULT_THEME)
const currentStyle = ref<AppStyle>(DEFAULT_STYLE)

export function installAppTheme(): AppTheme {
  const theme = resolveAppTheme()
  currentTheme.value = theme
  applyDocumentTheme(theme)
  return theme
}

export function setAppTheme(theme: AppTheme): void {
  currentTheme.value = theme
  persistAppTheme(theme)
  applyDocumentTheme(theme)
}

export function toggleAppTheme(): AppTheme {
  const nextTheme: AppTheme = currentTheme.value === 'dark' ? 'light' : 'dark'
  setAppTheme(nextTheme)
  return nextTheme
}

export function useAppTheme() {
  return {
    theme: readonly(currentTheme),
    setAppTheme,
    toggleAppTheme,
  }
}

/**
 * 启动时决定以哪一版打开：分享链接的 ?style= 优先（记下并从地址里拿掉），其次是本机记下的选择，默认漫画版。
 * 返回的 Promise 在可以挂载应用时兑现：简洁版等样式表加载完，漫画版立即兑现。参数得在路由模块创建 history
 * 之前读走，所以 main.ts 传入 styleLink.ts 先读到的值；不传就在这里读。
 */
export function installAppStyle(
  fromLink: AppStyle | null = typeof window === 'undefined' ? null : consumeStyleParam(),
): Promise<void> {
  if (fromLink) persistAppStyle(fromLink)
  const style = fromLink ?? resolveAppStyle({ search: '' })
  currentStyle.value = style
  applyDocumentStyle(style)
  return style === 'simple' ? ensureSimpleStyles() : Promise.resolve()
}

/** 立即换版并记下；换到简洁版之前须先等 ensureSimpleStyles()，否则会先露出没有简洁样式的一帧。 */
export function applyAppStyle(style: AppStyle): void {
  currentStyle.value = style
  persistAppStyle(style)
  applyDocumentStyle(style)
}

export async function setAppStyle(style: AppStyle): Promise<void> {
  if (style === 'simple') await ensureSimpleStyles()
  applyAppStyle(style)
}

export function useAppStyle() {
  return {
    style: readonly(currentStyle),
    setAppStyle,
  }
}
