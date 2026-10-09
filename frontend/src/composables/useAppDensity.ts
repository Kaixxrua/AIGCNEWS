import { computed, readonly, ref } from 'vue'

export type AppDensity = 'compact' | 'comfortable'
export const APP_DENSITY_KEY = 'app_density'

/** 有舒适版面的页（路由名）：报眉只在这几页放密度开关，在别的页按下去不会有变化。 */
export const DENSITY_ROUTES: ReadonlySet<string> = new Set(['membership', 'report', 'x-board'])

/** 这一页有没有两版可选；项目榜单与 UI 紧凑网格固定版式，不显示密度开关。 */
export function routeHasDensityChoice(route: { name?: unknown; query?: Record<string, unknown> }): boolean {
  return DENSITY_ROUTES.has(String(route.name ?? ''))
}

function readStoredDensity(): AppDensity {
  try {
    return localStorage.getItem(APP_DENSITY_KEY) === 'comfortable' ? 'comfortable' : 'compact'
  } catch {
    return 'compact'
  }
}

// 全站一份：报眉的开关和各页读的是同一个值。
const density = ref<AppDensity>(readStoredDensity())

export function setAppDensity(value: AppDensity): void {
  density.value = value
  try {
    localStorage.setItem(APP_DENSITY_KEY, value)
  } catch {
    // 存不了就不存，只在这次打开时有效
  }
}

/**
 * 版面密度：紧凑（默认）是桌面各页提密度之后的版面，舒适保留改版前的卡片（简报一节一张卡、推文墙不折叠不限高、
 * 会员三张卡）。报眉右侧一枚开关切换，选择只记在本机；手机与平板没有这一档，记下的选择在那里不生效，
 * 各页用「桌面且不是舒适」决定排哪一版。
 */
export function useAppDensity() {
  const comfortable = computed(() => density.value === 'comfortable')
  const toggle = () => setAppDensity(comfortable.value ? 'compact' : 'comfortable')
  return { density: readonly(density), comfortable, toggle }
}
