<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useDockSuppression } from '@/composables/useDockSuppression'
import LoginForm from '@/components/auth/LoginForm.vue'

const props = defineProps<{ modelValue: boolean; redirect?: unknown }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'success'): void }>()
const { t } = useI18n()
useDockSuppression(() => props.modelValue)
const close = () => emit('update:modelValue', false)
const success = () => { emit('success'); close() }
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="modelValue" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" @click.self="close">
        <div class="relative max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto">
          <button type="button" class="absolute right-3 top-3 z-10 text-lg leading-none opacity-70 hover:opacity-100" :aria-label="t('common.close')" @click="close">✕</button>
          <LoginForm :redirect="redirect" dialog @success="success" />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
