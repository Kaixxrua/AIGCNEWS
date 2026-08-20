<script setup lang="ts">
import { useDockSuppression } from '@/composables/useDockSuppression'
import LoginForm from '@/components/auth/LoginForm.vue'

const props = defineProps<{ modelValue: boolean; redirect?: unknown }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'success'): void }>()
useDockSuppression(() => props.modelValue)
const close = () => emit('update:modelValue', false)
const success = () => { emit('success'); close() }
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="modelValue" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" @click.self="close">
        <!-- 卡片本体由 LoginForm 的 dialog 模式渲染（含右上角 ✕ 与文A切换），这里只管遮罩与滚动容器 -->
        <div class="relative max-h-[calc(100dvh-2rem)] w-full max-w-sm overflow-y-auto">
          <LoginForm :redirect="redirect" dialog @success="success" @close="close" />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
