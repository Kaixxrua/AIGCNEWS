import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './fonts.css'
import './style.css'
import './mobile-reading.css'
import './comic-theme.css'
import App from './App.vue'
import router from './router/index'
import i18n, { installI18n } from './i18n'
import { installAppTheme } from './theme'

const app = createApp(App)
installI18n()
installAppTheme()
const pinia = createPinia()

app.use(pinia)
app.use(i18n)
app.use(router)

app.mount('#app')

// 站点访问 beacon：进来一次计一次（sessionStorage 守卫，异步不打断首屏）。
void import('./services/visit/visitBeacon').then(({ sendVisitBeacon }) => {
  sendVisitBeacon()
})

// 页面先可用，再异步确认已保存的登录状态。
void import('./stores/authStore').then(({ useAuthStore }) => {
  return useAuthStore(pinia).ensureInitialized()
})

// PWA Service Worker：仅生产环境注册（开发态预缓存会污染 HMR 调试）。
// 动态导入与 beacon/authStore 同款风格，注册逻辑不进首屏关键路径；
// 检测到新版本后由新 Service Worker 自动接管并刷新页面。
if (import.meta.env.PROD) {
  void import('./pwa/registerPwa').then(({ registerPwa }) => {
    registerPwa()
  })
}

// 安装入口也用于本地预览；没有原生安装事件时展示浏览器操作指引。
// 这只监听安装事件，不在开发环境注册 Service Worker。
void Promise.all([
  import('./pwa/installPrompt'),
  import('./components/pwa/PwaInstallGuide.vue'),
]).then(([{ initializeInstallPrompt }, { default: PwaInstallGuide }]) => {
  initializeInstallPrompt()
  const host = document.createElement('div')
  host.id = 'pwa-install-guide-host'
  document.body.appendChild(host)
  createApp(PwaInstallGuide).use(i18n).mount(host)
})
