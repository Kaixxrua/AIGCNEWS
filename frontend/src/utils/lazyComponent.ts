import { defineAsyncComponent, watch, type Component, type WatchSource } from 'vue'

/**
 * 只在桌面（或更宽）才出现的组件：单独成包，手机不下载。
 *
 * 到了用得上的宽度就调 preload() 把包先取回来，重复调用不会重复请求。之后组件头一回渲染时拿到的是已经兑现的 Promise，
 * 在浏览器下一次绘制前就画出来，不会先空一帧再冒出来。取包失败的话，下回预取或渲染时再试。
 */
export function lazyComponent<T extends Component>(loader: () => Promise<{ default: T }>) {
  let pending: Promise<{ default: T }> | null = null
  const load = () => (pending ??= loader().catch((error: unknown) => {
    pending = null
    throw error
  }))
  return {
    component: defineAsyncComponent(load),
    preload: () => {
      load().catch(() => {})
    },
  }
}

/** 条件成立时预取（立即检查一次，之后每次变成成立时再调）。要在 setup 里调用，随组件卸载停止。 */
export function preloadWhen(when: WatchSource<boolean>, ...preloads: Array<() => void>): void {
  watch(when, (on) => {
    if (on) for (const preload of preloads) preload()
  }, { immediate: true })
}
