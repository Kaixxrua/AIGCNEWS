<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import { useAuthStore } from '@/stores/authStore'
import { ensureFeatureFlags } from '@/composables/useFeatureFlags'
import { startOAuth } from '@/services/auth/authApi'
import { getErrorDetail, getSafeInternalRedirect, hasTrimmedValue } from '@/features/auth/authViewModel'

const props = defineProps<{ redirect?: unknown }>()
const emit = defineEmits<{ (event: 'success'): void; (event: 'close'): void; (event: 'switch-to-register'): void; (event: 'switch-to-forgot-password'): void }>()
const authStore = useAuthStore()
const { t } = useI18n()
const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')
const oauthProviders = ref<string[]>([])
const oauthLoading = ref(false)
const redirectTarget = computed(() => getSafeInternalRedirect(props.redirect))

onMounted(async () => {
  oauthProviders.value = (await ensureFeatureFlags()).oauthProviders
})

const handleOAuth = async (provider: string) => {
  oauthLoading.value = true
  errorMsg.value = ''
  try {
    await startOAuth(provider, redirectTarget.value)
  } catch (error: unknown) {
    oauthLoading.value = false
    errorMsg.value = getErrorDetail(error, t('auth.loginFailed'))
  }
}

const handleLogin = async () => {
  errorMsg.value = ''
  if (!hasTrimmedValue(email.value) || !hasTrimmedValue(password.value)) {
    errorMsg.value = t('auth.fillEmailPassword')
    return
  }
  loading.value = true
  try {
    await authStore.login(email.value.trim(), password.value)
    emit('success')
  } catch (error: unknown) {
    errorMsg.value = getErrorDetail(error, t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-card glass-card w-full max-w-sm p-6">
    <AuthPageHeader :title="t('auth.loginTitle')" :description="t('auth.loginDescription')">
      <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2 3-2.5 4"/><circle cx="12" cy="17" r=".5" fill="currentColor"/>
      </svg>
      <template #actions>
        <button type="button" class="rounded p-1 text-lg leading-none text-stone-400 transition-colors hover:text-stone-800" :aria-label="t('common.close')" @click="emit('close')">✕</button>
      </template>
    </AuthPageHeader>
    <div class="space-y-4">
      <div class="space-y-1.5"><label class="text-xs font-medium text-stone-500">{{ t('auth.email') }}</label><input v-model="email" type="email" class="input" :placeholder="t('auth.emailPlaceholder')" autocomplete="email" :disabled="loading" @keydown.enter="handleLogin" /></div>
      <div class="space-y-1.5"><label class="text-xs font-medium text-stone-500">{{ t('auth.password') }}</label><input v-model="password" type="password" class="input" :placeholder="t('auth.passwordPlaceholder')" autocomplete="current-password" :disabled="loading" @keydown.enter="handleLogin" /></div>
      <AuthFeedback :message="errorMsg" type="error" />
      <div class="auth-forgot text-right"><button type="button" class="text-xs font-medium text-stone-500 underline underline-offset-2 hover:text-stone-800 transition-colors" @click="emit('switch-to-forgot-password')">{{ t('auth.forgotPassword') }}</button></div>
      <div v-if="oauthProviders.length" class="auth-oauth space-y-2 border-t border-stone-200 pt-4">
        <p class="text-center text-xs text-stone-400">{{ t('auth.oauthOr') }}</p>
        <button v-for="provider in oauthProviders" :key="provider" type="button" class="btn-secondary w-full justify-center gap-2 py-2.5" :disabled="loading || oauthLoading" @click="handleOAuth(provider)">
          <!-- 品牌图标仅作识别用途，按钮语义由文字标签承载 -->
          <svg v-if="provider === 'github'" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>
          <svg v-else-if="provider === 'google'" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.3 7.31 24 12 24z"/><path fill="#FBBC05" d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z"/></svg>
          <svg v-else-if="provider === 'wechat'" class="h-4 w-4 shrink-0 text-[#07C160]" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.01.804-.055a5.94 5.94 0 0 1-.203-1.57c0-3.474 3.198-6.289 7.152-6.289.227 0 .45.015.67.033C16.42 5.3 13.056 2.188 8.691 2.188zm-2.61 3.76c.659 0 1.198.54 1.198 1.198 0 .658-.54 1.198-1.198 1.198-.66 0-1.198-.54-1.198-1.198 0-.659.54-1.198 1.198-1.198zm5.218 0c.66 0 1.198.54 1.198 1.198 0 .658-.54 1.198-1.198 1.198-.659 0-1.198-.54-1.198-1.198 0-.659.54-1.198 1.198-1.198zm6.882 2.369c-3.533 0-6.404 2.366-6.404 5.282 0 2.916 2.87 5.282 6.404 5.282.828 0 1.616-.144 2.355-.384a.714.714 0 0 1 .59.08l1.56.91a.267.267 0 0 0 .137.045c.134 0 .24-.108.24-.24 0-.06-.023-.117-.04-.174l-.32-1.211a.482.482 0 0 1 .174-.543C22.61 16.578 23.6 15.174 23.6 13.6c0-2.917-2.87-5.283-6.418-5.283zm-4.303 2.368c.55 0 .994.444.994.993a.994.994 0 1 1-1.988 0c0-.55.444-.993.994-.993zm6.805 0c.55 0 .993.444.993.993a.993.993 0 1 1-.993.994.993.993 0 0 1-.993-.994c0-.55.443-.993.993-.993z"/></svg>
          {{ t(`auth.oauth.${provider}`) }}
        </button>
      </div>
      <button class="btn-primary w-full justify-center py-3" :disabled="loading || oauthLoading" @click="handleLogin">
        <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
        <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
        {{ loading ? t('auth.loggingIn') : t('auth.login') }}
      </button>
    </div>
    <p class="auth-switch mt-5 text-center text-sm text-stone-400">
      {{ t('auth.noAccount') }}
      <button type="button" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors" @click="emit('switch-to-register')">{{ t('auth.registerNow') }}</button>
    </p>
  </div>
</template>
