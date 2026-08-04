import { ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
}

const TOAST_DURATION_MS = 3200
const toasts = ref<ToastItem[]>([])
let nextId = 1

/**
 * 轻量全局 toast：模块级状态，组件内外（apiClient、composables）都可直接调用。
 * App.vue 中的 <AppToast /> 负责渲染；消息自动在 3.2s 后消失。
 */
export function showToast(message: string): void {
  const id = nextId++
  toasts.value = [...toasts.value, { id, message }]
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((item) => item.id !== id)
  }, TOAST_DURATION_MS)
}

export function useToasts() {
  return { toasts }
}
