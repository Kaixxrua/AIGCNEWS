<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import OtpEmailField from '@/components/auth/OtpEmailField.vue'
import PasswordConfirmationFields from '@/components/auth/PasswordConfirmationFields.vue'
import { usePasswordResetForm } from '@/composables/usePasswordResetForm'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { api } from '@/services/http/apiClient'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()

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
  resetDone,
  countdown,
  emailValid,
  otpBtnDisabled,
  sendOtp,
  handleReset,
} = usePasswordResetForm({
  post: (url, payload) => api.post(url, payload),
  replaceLogin: () => router.replace({ path: '/login', query: redirectQuery.value }),
})
</script>

<template>
  <div class="flex h-full items-center justify-center overflow-y-auto p-3 sm:p-6">
    <div class="w-full max-w-sm py-4">

      <!-- 标题区 -->
      <AuthPageHeader :title="t('auth.forgotTitle')" :description="t('auth.forgotDescription')">
        <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M7 11V8a5 5 0 0110 0v3"/>
          <rect x="5" y="11" width="14" height="10" rx="2"/>
          <path d="M12 15v2"/>
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
          :disabled="resetDone"
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
            :disabled="loading || resetDone"
          />
        </div>

        <PasswordConfirmationFields
          v-model:password="password"
          v-model:confirm-password="confirmPwd"
          :password-label="t('auth.newPassword')"
          :confirm-password-label="t('auth.confirmPassword')"
          :confirm-password-placeholder="t('auth.confirmPasswordPlaceholder')"
          :disabled="loading || resetDone"
          submit-on-enter
          @submit="handleReset"
        />

        <!-- 错误提示 -->
        <AuthFeedback :message="errorMsg" type="error" />

        <!-- 成功提示 -->
        <AuthFeedback :message="successMsg" type="success" />

        <!-- 重置按钮 -->
        <button
          class="btn-primary w-full justify-center py-3"
          :disabled="loading || resetDone"
          @click="handleReset"
        >
          <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
          <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 101.6-5.1"/>
            <polyline points="3 4 3 10 9 10"/>
          </svg>
          {{ loading ? t('auth.resetting') : t('auth.reset') }}
        </button>
      </div>

      <!-- 返回登录链接 -->
      <p class="mt-5 text-center text-sm text-stone-400 stagger-enter" style="animation-delay: 0.2s">
        {{ t('auth.rememberPassword') }}
        <RouterLink :to="{ path: '/login', query: redirectQuery }" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">
          {{ t('auth.backToLogin') }}
        </RouterLink>
      </p>

    </div>
  </div>
</template>
