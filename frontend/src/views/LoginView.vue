<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import { useAuthStore } from '@/stores/authStore'
import { getErrorDetail, getSafeInternalRedirect, hasTrimmedValue } from '@/features/auth/authViewModel'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()

const email    = ref('')
const password = ref('')
const loading  = ref(false)
const errorMsg = ref('')

const redirect = computed(() => getSafeInternalRedirect(route.query.redirect))
const redirectQuery = computed(() => ({ redirect: redirect.value }))

const handleLogin = async () => {
  errorMsg.value = ''
  if (!hasTrimmedValue(email.value) || !hasTrimmedValue(password.value)) {
    errorMsg.value = t('auth.fillEmailPassword')
    return
  }
  loading.value = true
  try {
    await authStore.login(email.value.trim(), password.value)
    // 登录成功后跳转到安全的站内页面，或默认跳 /
    await router.push(redirect.value)
  } catch (e: unknown) {
    errorMsg.value = getErrorDetail(e, t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex h-full items-center justify-center p-6">
    <div class="w-full max-w-sm">

      <!-- 标题区 -->
      <AuthPageHeader :title="t('auth.loginTitle')" :description="t('auth.loginDescription')">
        <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/>
          <path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2 3-2.5 4"/>
          <circle cx="12" cy="17" r=".5" fill="currentColor"/>
        </svg>
      </AuthPageHeader>

      <!-- 表单卡片 -->
      <div class="glass-card p-6 space-y-4 stagger-enter" style="animation-delay: 0.1s">

        <!-- 邮箱 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">{{ t('auth.email') }}</label>
          <input
            v-model="email"
            type="email"
            class="input"
            :placeholder="t('auth.emailPlaceholder')"
            autocomplete="email"
            :disabled="loading"
            @keydown.enter="handleLogin"
          />
        </div>

        <!-- 密码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">{{ t('auth.password') }}</label>
          <input
            v-model="password"
            type="password"
            class="input"
            :placeholder="t('auth.passwordPlaceholder')"
            autocomplete="current-password"
            :disabled="loading"
            @keydown.enter="handleLogin"
          />
        </div>

        <!-- 错误提示 -->
        <AuthFeedback :message="errorMsg" type="error" />

        <div class="text-right">
          <RouterLink
            :to="{ path: '/forgot-password', query: redirectQuery }"
            class="text-xs font-medium text-stone-500 underline underline-offset-2 hover:text-stone-800 transition-colors"
          >
            {{ t('auth.forgotPassword') }}
          </RouterLink>
        </div>

        <!-- 登录按钮 -->
        <button
          class="btn-primary w-full justify-center py-3"
          :disabled="loading"
          @click="handleLogin"
        >
          <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
          <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
            <polyline points="10 17 15 12 10 7"/>
            <line x1="15" y1="12" x2="3" y2="12"/>
          </svg>
          {{ loading ? t('auth.loggingIn') : t('auth.login') }}
        </button>
      </div>

      <!-- 底部注册链接 -->
      <p class="mt-5 text-center text-sm text-stone-400 stagger-enter" style="animation-delay: 0.2s">
        {{ t('auth.noAccount') }}
        <RouterLink :to="{ path: '/register', query: redirectQuery }" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">
          {{ t('auth.registerNow') }}
        </RouterLink>
      </p>

    </div>
  </div>
</template>
