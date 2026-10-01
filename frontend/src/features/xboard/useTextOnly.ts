import { computed, ref, watch, type Ref } from 'vue'

export const TEXT_ONLY_KEY = 'xboard_text_only'

function readStoredTextOnly(): boolean {
  try {
    return localStorage.getItem(TEXT_ONLY_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * 纯文字：桌面推文墙一键收起所有配图、链接卡与引用配图，只读字。选择只记在本机；
 * 手机与平板没有这一档，记下的选择在那里不生效。
 */
export function useTextOnly(desktop: Readonly<Ref<boolean>>) {
  const preferred = ref(readStoredTextOnly())
  watch(preferred, value => {
    try {
      localStorage.setItem(TEXT_ONLY_KEY, value ? '1' : '0')
    } catch {
      // 存不了就不存
    }
  })
  const textOnly = computed(() => preferred.value && desktop.value)
  const toggle = () => {
    preferred.value = !preferred.value
  }
  return { preferred, textOnly, toggle }
}
