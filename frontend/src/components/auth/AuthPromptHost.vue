<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import LoginDialog from '@/components/auth/LoginDialog.vue'
import RegisterDialog from '@/components/auth/RegisterDialog.vue'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useAuthStore } from '@/stores/authStore'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const {
  isOpen: loginOpen,
  redirectTarget,
  requestLogin,
  closeLoginPrompt,
  consumeLoginRedirect,
} = useLoginPrompt()

const registerOpen = ref(false)

// 任何新的登录请求（路由守卫、401 或页面入口）都以登录窗为准，避免双层弹窗。
watch(loginOpen, (isOpen) => {
  if (isOpen) registerOpen.value = false
})

const switchToRegister = () => {
  closeLoginPrompt()
  if (route.path === '/register') return
  registerOpen.value = true
}

const switchToLogin = () => {
  registerOpen.value = false
  requestLogin(redirectTarget.value)
}

const afterAuthSuccess = async () => {
  const target = consumeLoginRedirect()
  closeLoginPrompt()
  registerOpen.value = false
  if (target !== route.fullPath) await router.push(target)
}

const retryAuth = () => {
  void authStore.ensureInitialized().then(async () => {
    if (authStore.status === 'authenticated') {
      await afterAuthSuccess()
    } else if (authStore.status === 'anonymous') {
      requestLogin(redirectTarget.value)
    }
  })
}

// 非主动退出导致的会话失效：先卸载受保护内容，再在安全页面上请求重新登录。
watch(
  () => [authStore.status, route.fullPath, route.meta.requiresAuth, route.meta.requiresAdmin, authStore.logoutInProgress] as const,
  ([status, fullPath, requiresAuth, requiresAdmin, logoutInProgress]) => {
    if (status !== 'anonymous' || logoutInProgress || (!requiresAuth && !requiresAdmin)) return
    requestLogin(fullPath)
    void router.replace('/')
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="authStore.status === 'degraded'"
      class="fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border border-rose-200 bg-white p-4 text-sm text-stone-700 shadow-xl"
      role="alert"
    >
      <p>{{ t('auth.verificationFailed') }}</p>
      <button type="button" class="mt-2 font-medium text-stone-900 underline underline-offset-2" @click="retryAuth">
        {{ t('auth.retryVerification') }}
      </button>
    </div>
  </Teleport>
  <LoginDialog
    v-model="loginOpen"
    :redirect="redirectTarget"
    @success="afterAuthSuccess"
    @switch-to-register="switchToRegister"
  />
  <RegisterDialog
    v-model="registerOpen"
    @success="afterAuthSuccess"
    @switch-to-login="switchToLogin"
  />
</template>
