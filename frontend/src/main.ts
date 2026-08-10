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

// 启动动画保留到初始导航（路由守卫 + 懒加载 chunk）完成，消除挂载后的白屏空窗；
// 初始导航失败也要照常挂载，避免永远停在启动画面。
void router.isReady()
  .catch(() => { /* 由 router.onError 与页面内错误态承接 */ })
  .then(() => {
    app.mount('#app')
    // 页面先可用，再异步确认已保存的登录状态。
    void import('./stores/authStore').then(({ useAuthStore }) => {
      return useAuthStore(pinia).initFromStorage()
    })
  })
