<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute, RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import { useAuthStore } from '@/stores/authStore'
import { getErrorDetail, getSafeInternalRedirect, hasTrimmedValue } from '@/features/auth/authViewModel'

const props = withDefaults(defineProps<{ redirect?: unknown; dialog?: boolean }>(), { dialog: false })
const emit = defineEmits<{ (event: 'success'): void; (event: 'close'): void; (event: 'switch-to-register'): void }>()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()
const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')
const redirectTarget = computed(() => getSafeInternalRedirect(props.redirect ?? route.query.redirect))
const redirectQuery = computed(() => ({ redirect: redirectTarget.value }))

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
    if (!props.dialog) await router.push(redirectTarget.value)
  } catch (error: unknown) {
    errorMsg.value = getErrorDetail(error, t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <!-- dialog 模式由外层 glass-card 兜住整个登录内容（遮罩半透明，透明背景看不清）；
       standalone /login 保持「透明头部 + 独立表单卡」原样，两种形态共用同一份模板。 -->
  <div class="w-full max-w-sm" :class="{ 'glass-card p-6': dialog }">
    <AuthPageHeader :title="t('auth.loginTitle')" :description="t('auth.loginDescription')">
      <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2 3-2.5 4"/><circle cx="12" cy="17" r=".5" fill="currentColor"/>
      </svg>
      <template v-if="dialog" #actions>
        <button type="button" class="rounded p-1 text-lg leading-none text-stone-400 transition-colors hover:text-stone-800" :aria-label="t('common.close')" @click="emit('close')">✕</button>
      </template>
    </AuthPageHeader>
    <div :class="dialog ? 'space-y-4' : 'glass-card mt-4 space-y-4 p-6 stagger-enter'" :style="dialog ? undefined : 'animation-delay: 0.1s'">
      <div class="space-y-1.5"><label class="text-xs font-medium text-stone-500">{{ t('auth.email') }}</label><input v-model="email" type="email" class="input" :placeholder="t('auth.emailPlaceholder')" autocomplete="email" :disabled="loading" @keydown.enter="handleLogin" /></div>
      <div class="space-y-1.5"><label class="text-xs font-medium text-stone-500">{{ t('auth.password') }}</label><input v-model="password" type="password" class="input" :placeholder="t('auth.passwordPlaceholder')" autocomplete="current-password" :disabled="loading" @keydown.enter="handleLogin" /></div>
      <AuthFeedback :message="errorMsg" type="error" />
      <div class="text-right"><RouterLink :to="{ path: '/forgot-password', query: redirectQuery }" class="text-xs font-medium text-stone-500 underline underline-offset-2 hover:text-stone-800 transition-colors">{{ t('auth.forgotPassword') }}</RouterLink></div>
      <button class="btn-primary w-full justify-center py-3" :disabled="loading" @click="handleLogin">
        <span v-if="loading" class="h-4 w-4 rounded-full border-2 animate-spin" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
        <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
        {{ loading ? t('auth.loggingIn') : t('auth.login') }}
      </button>
    </div>
    <p class="mt-5 text-center text-sm text-stone-400" :class="{ 'stagger-enter': !dialog }" :style="dialog ? undefined : 'animation-delay: 0.2s'">
      {{ t('auth.noAccount') }}
      <!-- dialog 模式在弹窗内直接切注册卡；standalone /login 保留路由跳转 -->
      <button v-if="dialog" type="button" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors" @click="emit('switch-to-register')">{{ t('auth.registerNow') }}</button>
      <RouterLink v-else :to="{ path: '/register', query: redirectQuery }" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">{{ t('auth.registerNow') }}</RouterLink>
    </p>
  </div>
</template>
