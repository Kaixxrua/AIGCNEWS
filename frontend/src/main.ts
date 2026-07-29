import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router/index'
import i18n, { installI18n } from './i18n'

const app = createApp(App)
installI18n()
const pinia = createPinia()

app.use(pinia)
app.use(i18n)
app.use(router)

app.mount('#app')

// 页面先可用，再异步确认已保存的登录状态。
void import('./stores/authStore').then(({ useAuthStore }) => {
  return useAuthStore(pinia).initFromStorage()
})
