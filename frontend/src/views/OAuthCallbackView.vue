<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import { getErrorDetail, getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()
const errorMsg = ref('')

onMounted(async () => {
  try {
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
      <RouterLink v-if="errorMsg" to="/login" class="btn-primary inline-flex justify-center">{{ t('auth.login') }}</RouterLink>
    </div>
  </main>
</template>
