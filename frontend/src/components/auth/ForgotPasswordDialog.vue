<script setup lang="ts">
import AuthDialogTransition from '@/components/auth/AuthDialogTransition.vue'
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import OtpEmailField from '@/components/auth/OtpEmailField.vue'
import PasswordConfirmationFields from '@/components/auth/PasswordConfirmationFields.vue'
import { usePasswordResetForm } from '@/composables/usePasswordResetForm'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { api } from '@/services/http/apiClient'
import { useDialogFocus } from '@/composables/useDialogFocus'
import { useDockSuppression } from '@/composables/useDockSuppression'

const props = defineProps<{ modelValue: boolean; redirect?: unknown }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'switch-to-login'): void
  (event: 'success', redirect: string): void
}>()
const { t } = useI18n()
const redirect = computed(() => getSafeInternalRedirect(props.redirect))
useDockSuppression(() => props.modelValue)

const {
  email, otp, password, confirmPwd, loading, otpLoading, errorMsg, successMsg,
  resetDone, countdown, emailValid, otpBtnDisabled, sendOtp, handleReset,
} = usePasswordResetForm({
  post: (url, payload) => api.post(url, payload),
  openLogin: () => emit('success', redirect.value),
})

const close = () => emit('update:modelValue', false)
const titleId = `forgot-password-dialog-title-${useId()}`
const dialogRef = ref<HTMLElement | null>(null)
useDialogFocus(() => props.modelValue, dialogRef, close)
</script>

<template>
  <Teleport to="body">
    <AuthDialogTransition>
      <div v-if="modelValue" class="comic-auth fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" :aria-labelledby="titleId" @click.self="close">
        <div ref="dialogRef" class="auth-dialog__panel relative max-h-[calc(100dvh-2rem)] w-full max-w-sm overflow-y-auto outline-none" tabindex="-1">
          <div class="auth-card glass-card w-full p-4 sm:p-6">
            <AuthPageHeader :title="t('auth.forgotTitle')" :description="t('auth.forgotDescription')" :title-id="titleId">
              <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 11V8a5 5 0 0110 0v3"/><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M12 15v2"/></svg>
              <template #actions>
                <button type="button" class="rounded p-1 text-lg leading-none text-stone-400 transition-colors hover:text-stone-800" :aria-label="t('common.close')" @click="close">✕</button>
              </template>
            </AuthPageHeader>
            <div class="space-y-4">
              <OtpEmailField v-model:email="email" :email-valid="emailValid" :loading="loading" :otp-loading="otpLoading" :otp-btn-disabled="otpBtnDisabled" :countdown="countdown" :disabled="resetDone" @send-otp="sendOtp" />
              <div class="space-y-1.5"><label class="text-xs font-medium text-stone-500">{{ t('auth.otp') }}</label><input v-model="otp" type="text" inputmode="numeric" maxlength="6" class="input tracking-widest" :placeholder="t('auth.otpPlaceholder')" autocomplete="one-time-code" :disabled="loading || resetDone" /></div>
              <PasswordConfirmationFields v-model:password="password" v-model:confirm-password="confirmPwd" :password-label="t('auth.newPassword')" :confirm-password-label="t('auth.confirmPassword')" :confirm-password-placeholder="t('auth.confirmPasswordPlaceholder')" :disabled="loading || resetDone" submit-on-enter @submit="handleReset" />
              <AuthFeedback :message="errorMsg" type="error" />
              <AuthFeedback :message="successMsg" type="success" />
              <button class="btn-primary w-full justify-center py-3" :disabled="loading || resetDone" @click="handleReset">
                <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
                <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 101.6-5.1"/><polyline points="3 4 3 10 9 10"/></svg>
                {{ loading ? t('auth.resetting') : t('auth.reset') }}
              </button>
            </div>
            <p class="auth-switch mt-5 text-center text-sm text-stone-600">{{ t('auth.rememberPassword') }} <button type="button" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors" @click="emit('switch-to-login')">{{ t('auth.backToLogin') }}</button></p>
          </div>
        </div>
      </div>
    </AuthDialogTransition>
  </Teleport>
</template>
