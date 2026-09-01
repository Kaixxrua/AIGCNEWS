<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import LoginDialog from '@/components/auth/LoginDialog.vue'
import RegisterDialog from '@/components/auth/RegisterDialog.vue'
import ForgotPasswordDialog from '@/components/auth/ForgotPasswordDialog.vue'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useAuthStore } from '@/stores/authStore'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const prompt = useLoginPrompt()
const { isOpen: loginOpen, redirectTarget, requestLogin, closeLoginPrompt, consumeLoginRedirect, requestPasswordReset, closePasswordReset } = prompt
const forgotPasswordOpen = prompt.isResetOpen ?? ref(false)
const registerOpen = ref(false)
const switching = ref(false)

watch(loginOpen, isOpen => { if (switching.value || !isOpen) return; registerOpen.value = false; forgotPasswordOpen.value = false })
watch(registerOpen, isOpen => { if (switching.value || !isOpen) return; closeLoginPrompt(); forgotPasswordOpen.value = false })
watch(forgotPasswordOpen, isOpen => { if (switching.value || !isOpen) return; closeLoginPrompt(); registerOpen.value = false })

const switchToRegister = async () => {
  if (route.path === '/register') return
  switching.value = true
  forgotPasswordOpen.value = false
  registerOpen.value = true
  await nextTick()
  closeLoginPrompt()
  switching.value = false
}
const switchToForgotPassword = async () => {
  switching.value = true
  registerOpen.value = false
  requestPasswordReset(redirectTarget.value)
  await nextTick()
  closeLoginPrompt()
  switching.value = false
}
const switchToLogin = async () => {
  switching.value = true
  forgotPasswordOpen.value = false
  registerOpen.value = false
  requestLogin(redirectTarget.value)
  await nextTick()
  closePasswordReset()
  switching.value = false
}
const afterAuthSuccess = async () => { const target = consumeLoginRedirect(); closeLoginPrompt(); closePasswordReset(); registerOpen.value = false; forgotPasswordOpen.value = false; if (target !== route.fullPath) await router.push(target) }
const afterPasswordReset = () => { closePasswordReset(); requestLogin(redirectTarget.value) }
const retryAuth = () => { void authStore.ensureInitialized().then(async () => { if (authStore.status === 'authenticated') await afterAuthSuccess(); else if (authStore.status === 'anonymous') requestLogin(redirectTarget.value) }) }

watch(() => [authStore.status, route.fullPath, route.meta.requiresAuth, route.meta.requiresAdmin, authStore.logoutInProgress] as const, ([status, fullPath, requiresAuth, requiresAdmin, logoutInProgress]) => {
  if (status !== 'anonymous' || logoutInProgress || (!requiresAuth && !requiresAdmin)) return
  requestLogin(fullPath)
  void router.replace('/')
}, { immediate: true })
</script>

<template>
  <Teleport to="body">
    <div v-if="authStore.status === 'degraded'" class="fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border border-rose-200 bg-white p-4 text-sm text-stone-700 shadow-xl" role="alert">
      <p>{{ t('auth.verificationFailed') }}</p>
      <button type="button" class="mt-2 font-medium text-stone-900 underline underline-offset-2" @click="retryAuth">{{ t('auth.retryVerification') }}</button>
    </div>
  </Teleport>
  <LoginDialog v-model="loginOpen" :redirect="redirectTarget" @success="afterAuthSuccess" @switch-to-register="switchToRegister" @switch-to-forgot-password="switchToForgotPassword" />
  <RegisterDialog v-model="registerOpen" @success="afterAuthSuccess" @switch-to-login="switchToLogin" />
  <ForgotPasswordDialog v-if="forgotPasswordOpen" v-model="forgotPasswordOpen" :redirect="redirectTarget" @success="afterPasswordReset" @switch-to-login="switchToLogin" />
</template>
