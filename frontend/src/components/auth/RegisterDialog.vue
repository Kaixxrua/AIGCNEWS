<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useDockSuppression } from '@/composables/useDockSuppression'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import OtpEmailField from '@/components/auth/OtpEmailField.vue'
import PasswordConfirmationFields from '@/components/auth/PasswordConfirmationFields.vue'
import { useRegisterForm } from '@/composables/useRegisterForm'
import { api } from '@/services/http/apiClient'
import { useAuthStore } from '@/stores/authStore'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'success'): void
  (event: 'switch-to-login'): void
}>()
const { t } = useI18n()
useDockSuppression(() => props.modelValue)
const authStore = useAuthStore()

const close = () => emit('update:modelValue', false)
// 注册成功即已登录：关弹窗并把 redirect 目标交给根级 AuthPromptHost 处理。
const success = () => { emit('success'); close() }

const {
  email,
  otp,
  password,
  confirmPwd,
  username,
  loading,
  otpLoading,
  errorMsg,
  successMsg,
  agreedToTerms,
  countdown,
  emailValid,
  otpBtnDisabled,
  sendOtp,
  handleRegister,
} = useRegisterForm({
  post: (url, payload) => api.post(url, payload),
  login: (mail, pwd) => authStore.login(mail, pwd),
  onSuccess: () => { success() },
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="modelValue" class="comic-auth fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" @click.self="close">
        <div class="relative max-h-[calc(100dvh-2rem)] w-full max-w-sm overflow-y-auto">
          <div class="auth-card glass-card p-4 sm:p-6">
            <AuthPageHeader :title="t('auth.registerTitle')" :description="t('auth.registerDescription')">
              <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
              <template #actions>
                <button type="button" class="rounded p-1 text-lg leading-none text-stone-400 transition-colors hover:text-stone-800" :aria-label="t('common.close')" @click="close">✕</button>
              </template>
            </AuthPageHeader>

            <div class="space-y-4">
              <OtpEmailField
                v-model:email="email"
                :email-valid="emailValid"
                :loading="loading"
                :otp-loading="otpLoading"
                :otp-btn-disabled="otpBtnDisabled"
                :countdown="countdown"
                @send-otp="sendOtp"
              />
              <div class="space-y-1.5">
                <label class="text-xs font-medium text-stone-500">{{ t('auth.otp') }}</label>
                <input v-model="otp" type="text" inputmode="numeric" maxlength="6" class="input tracking-widest" :placeholder="t('auth.otpPlaceholder')" autocomplete="one-time-code" :disabled="loading" />
              </div>
              <div class="space-y-1.5">
                <label class="text-xs font-medium text-stone-500">{{ t('auth.username') }}</label>
                <input v-model="username" type="text" maxlength="64" class="input" :placeholder="t('auth.usernamePlaceholder')" autocomplete="username" :disabled="loading" />
              </div>
              <PasswordConfirmationFields
                v-model:password="password"
                v-model:confirm-password="confirmPwd"
                :password-label="t('auth.password')"
                :confirm-password-label="t('auth.confirmPassword')"
                :confirm-password-placeholder="t('auth.confirmPasswordPlaceholder')"
                :disabled="loading"
              />
              <AuthFeedback :message="errorMsg" type="error" />
              <AuthFeedback :message="successMsg" type="success" />
              <div class="auth-terms flex items-start gap-2.5 pt-1">
                <button
                  type="button"
                  class="mt-0.5 shrink-0 w-4 h-4 rounded border transition-all duration-150 flex items-center justify-center"
                  :class="agreedToTerms ? 'bg-accent border-ink' : 'bg-card border-stone-300 hover:border-ink hover:bg-accent-soft'"
                  :aria-pressed="agreedToTerms"
                  :aria-label="t('auth.agreeAria')"
                  @click="agreedToTerms = !agreedToTerms"
                >
                  <svg v-if="agreedToTerms" viewBox="0 0 12 12" fill="none" style="stroke: var(--acid-ink)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-2.5 h-2.5">
                    <polyline points="2,6 5,9 10,3"/>
                  </svg>
                </button>
                <label class="text-xs text-stone-500 leading-relaxed cursor-pointer select-none" @click="agreedToTerms = !agreedToTerms">
                  {{ t('auth.agreeTerms') }}
                  <RouterLink to="/disclaimer" target="_blank" class="text-stone-700 underline underline-offset-2 hover:text-stone-900" @click.stop>{{ t('auth.terms') }}</RouterLink>
                  {{ t('auth.and') }}
                  <RouterLink to="/privacy" target="_blank" class="text-stone-700 underline underline-offset-2 hover:text-stone-900" @click.stop>{{ t('footer.privacy') }}</RouterLink>{{ t('auth.termsSuffix') }}
                </label>
              </div>
              <button class="btn-primary w-full justify-center py-3" :disabled="loading || !agreedToTerms" @click="handleRegister">
                <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
                <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/>
                  <circle cx="9" cy="7" r="4"/>
                  <line x1="19" y1="8" x2="19" y2="14"/>
                  <line x1="22" y1="11" x2="16" y2="11"/>
                </svg>
                {{ loading ? t('auth.registering') : t('auth.register') }}
              </button>
            </div>

            <p class="auth-switch mt-5 text-center text-sm text-stone-400">
              {{ t('auth.hasAccount') }}
              <button type="button" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors" @click="emit('switch-to-login')">{{ t('auth.goLogin') }}</button>
            </p>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
