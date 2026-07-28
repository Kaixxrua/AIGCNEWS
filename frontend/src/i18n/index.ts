import { createI18n } from 'vue-i18n'
import enUS from './locales/en-US'
import zhCN from './locales/zh-CN'
import {
  DEFAULT_LOCALE,
  persistAppLocale,
  resolveAppLocale,
  updateDocumentLocale,
  type AppLocale,
} from './locale'

export { APP_LOCALES, DEFAULT_LOCALE, LOCALE_STORAGE_KEY, isAppLocale, persistAppLocale, resolveAppLocale, updateDocumentLocale } from './locale'
export type { AppLocale } from './locale'

export const messages = { 'zh-CN': zhCN, 'en-US': enUS } as const

export const i18n = createI18n({
  legacy: false,
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  messages,
})

export function installI18n(): AppLocale {
  const locale = resolveAppLocale()
  i18n.global.locale.value = locale
  updateDocumentLocale(locale)
  return locale
}

export function setAppLocale(locale: AppLocale): void {
  i18n.global.locale.value = locale
  persistAppLocale(locale)
  updateDocumentLocale(locale)
}

export default i18n
