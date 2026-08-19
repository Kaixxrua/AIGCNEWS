<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import PasswordConfirmationFields from '@/components/auth/PasswordConfirmationFields.vue'
import { useChangePasswordForm } from '@/composables/useChangePasswordForm'
import { useDockSuppression } from '@/composables/useDockSuppression'
import { useAuthStore } from '@/stores/authStore'
import { changePassword, sendChangePasswordOtp } from '@/services/auth/authApi'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const { t } = useI18n()
const authStore = useAuthStore()

// 弹窗打开期间隐藏底部 dock 浮岛，避免其透出在遮罩后方
useDockSuppression(() => props.modelValue)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const {
  otp,
  password,
  confirmPwd,
  loading,
  otpLoading,
  errorMsg,
  successMsg,
  changeDone,
  countdown,
  otpBtnDisabled,
  reset,
  handleSendOtp,
  handleSubmit,
} = useChangePasswordForm({
  submit: (code, next) => changePassword(code, next),
  sendOtp: () => sendChangePasswordOtp(),
  // 改密成功后刷新用户信息：默认密码提醒（password_change_required）随哈希轮换消失
  onChanged: () => authStore.fetchMe(),
})

const onClose = () => {
  visible.value = false
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        @click.self="onClose"
      >
        <div class="glass-card w-full max-w-sm overflow-hidden">
          <div class="monitor-divider flex items-center justify-between border-b p-4">
            <h3 class="text-sm font-semibold">{{ t('auth.changeTitle') }}</h3>
            <button
              class="text-lg leading-none opacity-70 hover:opacity-100"
              :aria-label="t('common.close')"
              @click="onClose"
            >✕</button>
          </div>

          <div class="p-5 space-y-4">
            <p class="text-xs leading-5 monitor-caption">{{ t('auth.changeDescription') }}</p>

            <div class="space-y-1.5">
              <label class="text-xs font-medium text-stone-500">{{ t('auth.changeOtpLabel') }}</label>
              <div class="flex flex-col gap-2 sm:flex-row">
                <input
                  v-model="otp"
                  type="text"
                  inputmode="numeric"
                  class="input flex-1"
                  :placeholder="t('auth.otpPlaceholder')"
                  autocomplete="one-time-code"
                  :disabled="loading || changeDone"
                />
                <button
                  class="shrink-0 inline-flex w-full items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-xs font-medium sm:w-auto transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
                  style="background: rgb(var(--card-rgb) / 0.8); border: 1px solid rgb(var(--stone-400-rgb) / 0.25); color: rgb(var(--stone-600-rgb)); backdrop-filter: blur(10px); white-space: nowrap"
                  :disabled="otpBtnDisabled || loading"
                  @click="handleSendOtp"
                >
                  <span v-if="otpLoading" class="h-3.5 w-3.5 rounded-full border-2 border-stone-300 border-t-stone-600 animate-spin" />
                  <span v-else-if="countdown > 0">{{ t('auth.resendOtp', { countdown }) }}</span>
                  <span v-else>{{ t('auth.getOtp') }}</span>
                </button>
              </div>
            </div>

            <PasswordConfirmationFields
              v-model:password="password"
              v-model:confirm-password="confirmPwd"
              :password-label="t('auth.newPassword')"
              :confirm-password-label="t('auth.confirmPassword')"
              :confirm-password-placeholder="t('auth.confirmPasswordPlaceholder')"
              :disabled="loading || changeDone"
              submit-on-enter
              @submit="handleSubmit"
            />

            <AuthFeedback :message="errorMsg" type="error" />
            <AuthFeedback :message="successMsg" type="success" />

            <button
              class="btn-primary w-full justify-center py-2.5"
              :disabled="loading || changeDone"
              @click="handleSubmit"
            >
              <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
              {{ loading ? t('auth.changing') : t('auth.changeSubmit') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
