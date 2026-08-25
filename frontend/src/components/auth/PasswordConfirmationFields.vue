<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { PASSWORD_MIN_LENGTH } from '@/features/auth/authViewModel'
const { t } = useI18n()
defineProps<{
  password: string
  confirmPassword: string
  passwordLabel: string
  confirmPasswordLabel: string
  confirmPasswordPlaceholder: string
  disabled: boolean
  submitOnEnter?: boolean
}>()

const emit = defineEmits<{
  'update:password': [value: string]
  'update:confirmPassword': [value: string]
  submit: []
}>()
</script>

<template>
  <div class="space-y-1.5">
    <label class="text-xs font-medium text-stone-500">{{ passwordLabel }}</label>
    <input
      :value="password"
      type="password"
      class="input"
      :placeholder="t('auth.newPasswordPlaceholder')"
      autocomplete="new-password"
      :disabled="disabled"
      @input="emit('update:password', ($event.target as HTMLInputElement).value)"
    />
    <Transition name="fade-msg">
      <p v-if="password && password.length < PASSWORD_MIN_LENGTH" class="text-2xs text-rose-500 pl-1">{{ t('auth.passwordMin') }}</p>
    </Transition>
  </div>

  <div class="space-y-1.5">
    <label class="text-xs font-medium text-stone-500">{{ confirmPasswordLabel }}</label>
    <input
      :value="confirmPassword"
      type="password"
      class="input"
      :placeholder="confirmPasswordPlaceholder"
      autocomplete="new-password"
      :disabled="disabled"
      @input="emit('update:confirmPassword', ($event.target as HTMLInputElement).value)"
      @keydown.enter="submitOnEnter && emit('submit')"
    />
    <Transition name="fade-msg">
      <p v-if="confirmPassword && password !== confirmPassword" class="text-2xs text-rose-500 pl-1">{{ t('auth.passwordMismatch') }}</p>
    </Transition>
  </div>
</template>

<style scoped>
.fade-msg-enter-active,
.fade-msg-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-msg-enter-from,
.fade-msg-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
