import { registerSW } from 'virtual:pwa-register'

/**
 * Service Worker 注册。仅生产环境使用：main.ts 以
 * import.meta.env.PROD 守卫动态导入本模块，开发态不注册（预缓存会污染
 * HMR 调试）。registerType: 'autoUpdate' 配合 skipWaiting + clientsClaim，
 * 新 SW 安装后会立即接管并刷新页面，无需用户确认。
 */

export function registerPwa(): void {
  const register = () => registerSW({
    immediate: true,
    onOfflineReady() {
      console.info('[pwa] 应用外壳已预缓存，可离线访问')
    },
  })
  // Full offline precaching competes with route chunks and first-page data.
  // Let initial navigation settle, then register during idle time (bounded).
  const schedule = () => window.setTimeout(() => {
    if (window.requestIdleCallback) window.requestIdleCallback(register, { timeout: 5000 })
    else register()
  }, 10_000)
  if (document.readyState === 'complete') schedule()
  else window.addEventListener('load', schedule, { once: true })
}
