/**
 * 站内速查（⌘K）的快捷键判断。报眉的放大镜、快捷键表随每一页加载，只用得上这两个函数；
 * 结果分组、排行这些逻辑在 quickSearch.ts，跟着面板只在桌面宽度按需加载。
 */

/** 苹果设备用 ⌘，其余用 Ctrl（Mac 上 Ctrl+K 是删到行尾，不抢）。iPadOS 自报 MacIntel，同样用 ⌘。 */
export function isApplePlatform(nav: Pick<Navigator, 'platform' | 'userAgent'> | undefined = typeof navigator === 'undefined' ? undefined : navigator): boolean {
  return Boolean(nav) && /Mac|iPhone|iPad|iPod/i.test(nav?.platform || nav?.userAgent || '')
}

/** ⌘K / Ctrl+K：只认这一个修饰键加 K；非拉丁键盘布局看物理键位；输入法组字中、别处已经接手的不接。 */
export function isQuickSearchHotkey(event: KeyboardEvent, apple: boolean): boolean {
  if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return false
  if (event.altKey || event.shiftKey) return false
  if (apple ? !event.metaKey || event.ctrlKey : !event.ctrlKey || event.metaKey) return false
  return event.key.toLowerCase() === 'k' || (event.code === 'KeyK' && !/^[\x20-\x7e]$/.test(event.key))
}
