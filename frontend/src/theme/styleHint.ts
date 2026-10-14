import { STYLE_STORAGE_KEY } from './appStyle'

/**
 * 一次性提示：报头的风格开关可以换成简洁版。本机没选过风格（没记下 app_style）、也没看过这条提示的人，
 * 在漫画版下看到一次；不管怎么关掉的都记下，不再出现。存储读不了时不提示，免得每次打开都冒出来。
 */
export const STYLE_HINT_KEY = 'aigcnews:style-hint:v1'
/** 页面安静下来再出，和列表快捷键提示一样等 1.5 秒。 */
export const STYLE_HINT_DELAY_MS = 1500

function localStorageOrNull(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

export function styleHintPending(storage: Pick<Storage, 'getItem'> | null = localStorageOrNull()): boolean {
  if (!storage) return false
  try {
    return storage.getItem(STYLE_HINT_KEY) === null && storage.getItem(STYLE_STORAGE_KEY) === null
  } catch {
    return false
  }
}

export function markStyleHintSeen(storage: Pick<Storage, 'setItem'> | null = localStorageOrNull()): void {
  if (!storage) return
  try {
    storage.setItem(STYLE_HINT_KEY, '1')
  } catch {
    // 记不下就只在这次打开里不再出现。
  }
}
