<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import { getErrorDetail, getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { consumeOAuthBindHandoff } from '@/services/auth/authApi'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()
const errorMsg = ref('')

onMounted(async () => {
  try {
    // 绑定流程不签发会话令牌：当前会话即绑定目标（服务端 state 亦已钉死 user_id）。
    await authStore.ensureInitialized()
    const result = await consumeOAuthBindHandoff()
    // 绑定成功后拉取权威投影，让账户设置中的渠道状态立即反映数据库真实绑定关系。
    await authStore.fetchMe()
    await router.replace(getSafeInternalRedirect(result.redirect_to))
  } catch (error: unknown) {
    errorMsg.value = getErrorDetail(error, t('auth.oauthBindFailed'))
  }
})
</script>

<template>
  <main class="flex min-h-screen items-center justify-center p-6">
    <div class="glass-card w-full max-w-sm space-y-4 p-6 text-center">
      <p v-if="!errorMsg" class="text-sm text-stone-500">{{ t('auth.oauthBinding') }}</p>
      <AuthFeedback v-else :message="errorMsg" type="error" />
      <button v-if="errorMsg" type="button" class="btn-primary inline-flex justify-center" @click="router.replace('/')">{{ t('auth.backHome') }}</button>
    </div>
  </main>
</template>
