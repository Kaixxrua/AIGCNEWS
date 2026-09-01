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
    await authStore.ensureInitialized()
    // consumeOAuthBinding 内部先消费一次性 handoff，再刷新权威账户投影（fetchMe）
    const redirectTo = await authStore.consumeOAuthBinding()
    await router.replace(getSafeInternalRedirect(redirectTo))
  } catch (error: unknown) {
    errorMsg.value = getErrorDetail(error, t('auth.oauthBindingFailed'))
  }
})

const backHome = () => { void router.replace('/') }
</script>

<template>
  <main class="flex min-h-screen items-center justify-center p-6">
    <div class="glass-card w-full max-w-sm space-y-4 p-6 text-center">
      <p v-if="!errorMsg" class="text-sm text-stone-500">{{ t('auth.oauthBindingInProgress') }}</p>
      <template v-else>
        <AuthFeedback :message="errorMsg" type="error" />
        <button type="button" class="btn-primary inline-flex justify-center" @click="backHome">{{ t('auth.backHome') }}</button>
      </template>
    </div>
  </main>
</template>
