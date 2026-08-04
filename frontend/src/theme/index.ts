import { readonly, ref } from 'vue'
import {
  applyDocumentTheme,
  DEFAULT_THEME,
  persistAppTheme,
  resolveAppTheme,
  type AppTheme,
} from './theme'

export { APP_THEMES, DEFAULT_THEME, THEME_ATTRIBUTE, THEME_STORAGE_KEY, applyDocumentTheme, isAppTheme, persistAppTheme, resolveAppTheme } from './theme'
export type { AppTheme } from './theme'

const currentTheme = ref<AppTheme>(DEFAULT_THEME)

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
