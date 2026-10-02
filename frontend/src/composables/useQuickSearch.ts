import { readonly, ref } from 'vue'

/**
 * 站内速查（⌘K）面板开没开：报眉上的放大镜、快捷键与面板本身共用这一份。
 */
const open = ref(false)

export function useQuickSearch() {
  return {
    open: readonly(open),
    show: () => { open.value = true },
    hide: () => { open.value = false },
    toggle: () => { open.value = !open.value },
  }
}
