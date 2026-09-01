<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import { getErrorDetail, getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'

const router = useRouter()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
const { t } = useI18n()
const errorMsg = ref('')

onMounted(async () => {
  try {
    // 与 main.ts 共用单飞恢复，避免启动恢复在 OAuth consume 中途推进认证 revision。
    await authStore.ensureInitialized()
    const redirectTo = await authStore.loginWithOAuthHandoff()
    await router.replace(getSafeInternalRedirect(redirectTo))
  } catch (error: unknown) {
    errorMsg.value = getErrorDetail(error, t('auth.oauthFailed'))
  }
})
</script>

<template>
  <main class="flex min-h-screen items-center justify-center p-6">
    <div class="glass-card w-full max-w-sm space-y-4 p-6 text-center">
      <p v-if="!errorMsg" class="text-sm text-stone-500">{{ t('auth.oauthSigningIn') }}</p>
      <AuthFeedback v-else :message="errorMsg" type="error" />
      <button v-if="errorMsg" type="button" class="btn-primary inline-flex justify-center" @click="requestLogin('/')">{{ t('auth.login') }}</button>
    </div>
  </main>
</template>
