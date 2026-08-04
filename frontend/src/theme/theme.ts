export const APP_THEMES = ['light', 'dark'] as const
export type AppTheme = typeof APP_THEMES[number]

export const DEFAULT_THEME: AppTheme = 'light'
export const THEME_STORAGE_KEY = 'app_theme'
export const THEME_ATTRIBUTE = 'data-theme'
export const THEME_DARK_VALUE = 'dark'

export function isAppTheme(value: unknown): value is AppTheme {
  return typeof value === 'string' && (APP_THEMES as readonly string[]).includes(value)
}

function readSavedTheme(storage?: Pick<Storage, 'getItem'> | null): AppTheme | null {
  if (!storage) return null
  try {
    const savedTheme = storage.getItem(THEME_STORAGE_KEY)
    return isAppTheme(savedTheme) ? savedTheme : null
  } catch {
    return null
  }
}

export interface ThemeResolutionOptions {
  storage?: Pick<Storage, 'getItem'> | null
  prefersDark?: boolean | null
}

// 解析顺序必须与 index.html 内联脚本保持一致：存储值 → 系统偏好 → 默认浅色。
export function resolveAppTheme(options: ThemeResolutionOptions = {}): AppTheme {
  const storage = options.storage === undefined
    ? (typeof window === 'undefined' ? null : window.localStorage)
    : options.storage
  const savedTheme = readSavedTheme(storage)
  if (savedTheme) return savedTheme

  const prefersDark = options.prefersDark === undefined
    ? (typeof window === 'undefined' || typeof window.matchMedia !== 'function'
        ? null
        : window.matchMedia('(prefers-color-scheme: dark)').matches)
    : options.prefersDark
  return prefersDark ? 'dark' : DEFAULT_THEME
}

export function persistAppTheme(
  theme: AppTheme,
  storage: Pick<Storage, 'setItem'> | null = typeof window === 'undefined' ? null : window.localStorage,
): void {
  if (!storage) return
  try {
    storage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Theme changes still apply when storage is blocked or unavailable.
  }
}

export function applyDocumentTheme(
  theme: AppTheme,
  documentElement: Pick<HTMLElement, 'setAttribute' | 'removeAttribute'> | null = typeof document === 'undefined' ? null : document.documentElement,
): void {
  if (!documentElement) return
  if (theme === 'dark') {
    documentElement.setAttribute(THEME_ATTRIBUTE, THEME_DARK_VALUE)
  } else {
    documentElement.removeAttribute(THEME_ATTRIBUTE)
  }
}
