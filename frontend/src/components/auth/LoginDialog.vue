<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'
import { useDockSuppression } from '@/composables/useDockSuppression'
import { ensureFeatureFlags } from '@/composables/useFeatureFlags'
import LoginForm from '@/components/auth/LoginForm.vue'

const props = defineProps<{ modelValue: boolean; redirect?: unknown }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'success'): void; (event: 'switch-to-register'): void; (event: 'switch-to-forgot-password'): void }>()

// 第三方登录按钮要等 /api/features 才知道有哪几个。游客打开要登录的页面时，登录框在开站那一刻就弹出，
// 按钮后到会把居中的卡片撑高、整张往上跳（手机上布局偏移约 0.2）。所以随应用一起去取，取到再弹；
// 最多等 FLAGS_WAIT_MS，取不到就先开，按钮到了再补上。
const FLAGS_WAIT_MS = 1500
const flagsSettled = ref(false)
const flagsTimer = setTimeout(() => { flagsSettled.value = true }, FLAGS_WAIT_MS)
void ensureFeatureFlags().finally(() => {
  clearTimeout(flagsTimer)
  flagsSettled.value = true
})
onBeforeUnmount(() => clearTimeout(flagsTimer))
const visible = computed(() => props.modelValue && flagsSettled.value)

useDockSuppression(() => visible.value)
const close = () => emit('update:modelValue', false)
const success = () => { emit('success'); close() }
const titleId = `login-dialog-title-${useId()}`
const dialogRef = ref<HTMLElement | null>(null)
useDialogFocus(() => visible.value, dialogRef, close)
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="comic-auth fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" :aria-labelledby="titleId" @click.self="close">
        <!-- 卡片本体由 LoginForm 渲染（含右上角关闭与注册切换），这里只管遮罩与滚动容器。 -->
        <div ref="dialogRef" class="relative max-h-[calc(100dvh-2rem)] w-full max-w-sm overflow-y-auto outline-none" tabindex="-1">
          <LoginForm :redirect="redirect" :title-id="titleId" @success="success" @close="close" @switch-to-register="emit('switch-to-register')" @switch-to-forgot-password="emit('switch-to-forgot-password')" />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
