import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './fonts.css'
import './style.css'
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
  return useAuthStore(pinia).initFromStorage()
})
