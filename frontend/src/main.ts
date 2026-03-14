import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router/index'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// 在挂载前从 localStorage 恢复登录状态
import('./stores/authStore').then(({ useAuthStore }) => {
  const authStore = useAuthStore()
  authStore.initFromStorage().finally(() => {
    app.mount('#app')
  })
})
