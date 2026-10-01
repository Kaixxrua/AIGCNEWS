import { computed, ref, watch, type Ref } from 'vue'

export type LibraryDensity = 'cards' | 'sheet'
export const DENSITY_KEY = 'ui_library_density'

function readStoredDensity(): LibraryDensity {
  try {
    return localStorage.getItem(DENSITY_KEY) === 'sheet' ? 'sheet' : 'cards'
  } catch {
    return 'cards'
  }
}

/**
 * 联系表：桌面上把作品缩成小图、一排放更多列，适合快速扫图。选择只记在本机；
 * 手机与平板没有这一档，记下的选择在那里不生效。
 */
export function useLibraryDensity(desktop: Readonly<Ref<boolean>>) {
  const density = ref<LibraryDensity>(readStoredDensity())
  watch(density, value => {
    try {
      localStorage.setItem(DENSITY_KEY, value)
    } catch {
      // 存不了就不存
    }
  })
  const contactSheet = computed(() => density.value === 'sheet' && desktop.value)
  const toggle = () => {
    density.value = density.value === 'sheet' ? 'cards' : 'sheet'
  }
  return { density, contactSheet, toggle }
}
