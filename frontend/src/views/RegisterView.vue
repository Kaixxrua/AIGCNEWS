<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import OtpEmailField from '@/components/auth/OtpEmailField.vue'
import PasswordConfirmationFields from '@/components/auth/PasswordConfirmationFields.vue'
import { useRegisterForm } from '@/composables/useRegisterForm'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { api } from '@/services/http/apiClient'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const redirect = computed(() => getSafeInternalRedirect(route.query.redirect))
const redirectQuery = computed(() => ({ redirect: redirect.value }))

const {
  email,
  otp,
  password,
  confirmPwd,
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
  login: (email, password) => authStore.login(email, password),
  onSuccess: () => router.replace(redirect.value),
})
</script>

<template>
  <div class="flex h-full items-center justify-center overflow-y-auto p-3 sm:p-6">
    <div class="w-full max-w-sm py-4">

      <!-- 标题区 -->
      <AuthPageHeader :title="t('auth.registerTitle')" :description="t('auth.registerDescription')">
        <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
      </AuthPageHeader>

      <!-- 表单卡片 -->
      <div class="glass-card p-4 sm:p-6 space-y-4 stagger-enter" style="animation-delay: 0.1s">

        <!-- 邮箱 + 发送验证码 -->
        <OtpEmailField
          v-model:email="email"
          :email-valid="emailValid"
          :loading="loading"
          :otp-loading="otpLoading"
          :otp-btn-disabled="otpBtnDisabled"
          :countdown="countdown"
          @send-otp="sendOtp"
        />

        <!-- 邮箱验证码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">{{ t('auth.otp') }}</label>
          <input
            v-model="otp"
            type="text"
            inputmode="numeric"
            maxlength="6"
            class="input tracking-widest"
            :placeholder="t('auth.otpPlaceholder')"
            autocomplete="one-time-code"
            :disabled="loading"
          />
        </div>

        <PasswordConfirmationFields
          v-model:password="password"
          v-model:confirm-password="confirmPwd"
          :password-label="t('auth.password')"
          :confirm-password-label="t('auth.confirmPassword')"
          :confirm-password-placeholder="t('auth.confirmPasswordPlaceholder')"
          :disabled="loading"
        />

        <!-- 错误提示 -->
        <AuthFeedback :message="errorMsg" type="error" />

        <!-- 成功提示 -->
        <AuthFeedback :message="successMsg" type="success" />

        <!-- 用户协议勾选 -->
        <div class="flex items-start gap-2.5 pt-1">
          <button
            type="button"
            class="mt-0.5 shrink-0 w-4 h-4 rounded border transition-all duration-150 flex items-center justify-center"
            :class="agreedToTerms
              ? 'bg-accent border-ink'
              : 'bg-card border-stone-300 hover:border-ink hover:bg-accent-soft'"
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
            <RouterLink to="/privacy" target="_blank" class="text-stone-700 underline underline-offset-2 hover:text-stone-900" @click.stop>{{ t('footer.privacy') }}</RouterLink>
            {{ t('auth.termsSuffix') }}
          </label>
        </div>

        <!-- 注册按钮 -->
        <button
          class="btn-primary w-full justify-center py-3"
          :disabled="loading || !agreedToTerms"
          @click="handleRegister"
        >
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

      <!-- 底部登录链接 -->
      <p class="mt-5 text-center text-sm text-stone-400 stagger-enter" style="animation-delay: 0.2s">
        {{ t('auth.hasAccount') }}
        <RouterLink :to="{ path: '/login', query: redirectQuery }" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">
          {{ t('auth.goLogin') }}
        </RouterLink>
      </p>

    </div>
  </div>
</template>
