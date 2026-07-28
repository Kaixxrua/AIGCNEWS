export const APP_LOCALES = ['zh-CN', 'en-US'] as const
export type AppLocale = typeof APP_LOCALES[number]

export const DEFAULT_LOCALE: AppLocale = 'zh-CN'
export const LOCALE_STORAGE_KEY = 'app_locale'

export function isAppLocale(value: unknown): value is AppLocale {
  return typeof value === 'string' && APP_LOCALES.includes(value as AppLocale)
}

function readSavedLocale(storage?: Pick<Storage, 'getItem'> | null): AppLocale | null {
  if (!storage) return null
  try {
    const savedLocale = storage.getItem(LOCALE_STORAGE_KEY)
    return isAppLocale(savedLocale) ? savedLocale : null
  } catch {
    return null
  }
}

function resolveBrowserLocale(languages?: readonly string[] | null): AppLocale | null {
  const browserLocale = languages?.find((language) => language.trim().length > 0)
  if (!browserLocale) return null
  return browserLocale.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
}

export interface LocaleResolutionOptions {
  storage?: Pick<Storage, 'getItem'> | null
  browserLanguages?: readonly string[] | null
}

export function resolveAppLocale(options: LocaleResolutionOptions = {}): AppLocale {
  const storage = options.storage === undefined
    ? (typeof window === 'undefined' ? null : window.localStorage)
    : options.storage
  const savedLocale = readSavedLocale(storage)
  if (savedLocale) return savedLocale

  const browserLanguages = options.browserLanguages === undefined
    ? (typeof navigator === 'undefined' ? null : (navigator.languages?.length ? navigator.languages : [navigator.language]))
    : options.browserLanguages
  return resolveBrowserLocale(browserLanguages) ?? DEFAULT_LOCALE
}

export function persistAppLocale(
  locale: AppLocale,
  storage: Pick<Storage, 'setItem'> | null = typeof window === 'undefined' ? null : window.localStorage,
): void {
  if (!storage) return
  try {
    storage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // Locale changes still apply when storage is blocked or unavailable.
  }
}

export function updateDocumentLocale(
  locale: AppLocale,
  documentElement: Pick<HTMLElement, 'lang'> | null = typeof document === 'undefined' ? null : document.documentElement,
): void {
  if (documentElement) documentElement.lang = locale
}
