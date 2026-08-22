import { createApp, ref } from 'vue'
import { registerSW } from 'virtual:pwa-register'

import PwaUpdateToast from '@/components/pwa/PwaUpdateToast.vue'
import i18n from '@/i18n'
import { installPwaMessages } from '@/i18n/locales/pwa'

/**
 * Service Worker 注册与更新提示。仅生产环境使用：main.ts 以
 * import.meta.env.PROD 守卫动态导入本模块，开发态不注册（预缓存会污染
 * HMR 调试）。registerType: 'prompt' 下新 SW 安装后停在 waiting 态，由
 * 用户点「立即更新」才触发 skipWaiting + 刷新，避免活动会话被强制 reload。
 * 模块级状态仿 useToast 先例：SW 回调与 PwaUpdateToast 渲染方共享。
 */

const needRefresh = ref(false)

let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null

export function usePwaUpdate() {
  return {
    needRefresh,
    reload() {
      // skipWaiting + clientsClaim，新 SW 接管后自动刷新页面。
      void updateSW?.(true)
    },
    dismiss() {
      // 「稍后」：waiting SW 保留，下次导航/刷新自然生效。
      needRefresh.value = false
    },
  }
}

export function registerPwa(): void {
  installPwaMessages()

  updateSW = registerSW({
    immediate: true,
    onNeedRefresh() {
      needRefresh.value = true
    },
    onOfflineReady() {
      console.info('[pwa] 应用外壳已预缓存，可离线访问')
    },
  })

  // App.vue 模板不改动：更新提示卡片挂到独立宿主节点，与主应用共享同一
  // i18n 实例（语言切换即时生效）。
  const host = document.createElement('div')
  host.id = 'pwa-update-toast-host'
  document.body.appendChild(host)
  createApp(PwaUpdateToast).use(i18n).mount(host)
}
