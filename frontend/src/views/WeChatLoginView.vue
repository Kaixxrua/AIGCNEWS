<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useElementSize } from '@vueuse/core'
import { useRoute } from 'vue-router'
import { RefreshCw, ScanLine } from 'lucide-vue-next'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import { WeChatIcon } from '@/components/icons/WeChatIcon'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'
import { prepareWeChatLogin } from '@/services/auth/authApi'

const route = useRoute()
const { t } = useI18n()
const { requestLogin } = useLoginPrompt()
const redirect = computed(() => getSafeInternalRedirect(route.query.redirect))
const status = ref<'loading' | 'ready' | 'expired' | 'unavailable' | 'error'>('loading')
const authorizationUrl = ref('')
const frameUrl = ref('')
const frameContainer = ref<HTMLElement | null>(null)
const { width: frameWidth } = useElementSize(frameContainer, { width: 300, height: 400 })
const frameScale = computed(() => Math.min(1, (frameWidth.value || 300) / 300))
let controller: AbortController | undefined
let loadTimer: ReturnType<typeof setTimeout> | undefined
let expiryTimer: ReturnType<typeof setTimeout> | undefined

const clearTimers = () => { clearTimeout(loadTimer); clearTimeout(expiryTimer) }
const frameLoaded = () => {
  clearTimeout(loadTimer)
  if (status.value === 'loading') status.value = 'ready'
}
const frameFailed = () => {
  clearTimeout(loadTimer)
  if (status.value === 'loading' || status.value === 'ready') status.value = 'error'
}

const refresh = async () => {
  controller?.abort()
  const request = new AbortController()
  controller = request
  clearTimers()
  status.value = 'loading'
  frameUrl.value = ''
  authorizationUrl.value = ''
  try {
    const prepared = await prepareWeChatLogin(redirect.value, request.signal)
    if (request.signal.aborted) return
    const url = new URL(prepared.authorization_url)
    // Only embed the fixed official endpoint, never a redirect supplied by the page URL.
    if (url.origin !== 'https://open.weixin.qq.com' || url.pathname !== '/connect/qrconnect'
      || url.username || url.password || !Number.isInteger(prepared.expires_in)
      || prepared.expires_in < 1 || prepared.expires_in > 900) throw new Error('invalid_wechat_login')
    authorizationUrl.value = url.href
    url.searchParams.set('login_type', 'jssdk')
    url.searchParams.set('self_redirect', 'false')
    url.searchParams.set('style', 'black')
    frameUrl.value = url.href
    loadTimer = setTimeout(frameFailed, 15_000)
    expiryTimer = setTimeout(() => {
      clearTimeout(loadTimer)
      status.value = 'expired'
      frameUrl.value = ''
      authorizationUrl.value = ''
    }, prepared.expires_in * 1000)
  } catch (error: unknown) {
    if (request.signal.aborted) return
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    status.value = detail === 'oauth_provider_unavailable' ? 'unavailable' : 'error'
  }
}

watch(redirect, () => { void refresh() }, { immediate: true })
onBeforeUnmount(() => { controller?.abort(); clearTimers() })
</script>

<template>
  <main class="wechat-login-page flex min-h-dvh items-center justify-center overflow-y-auto px-3 py-8 sm:p-8">
    <section class="w-full max-w-sm" aria-labelledby="wechat-login-title">
      <RouterLink to="/" class="mb-6 block text-center text-xs font-semibold tracking-[0.2em] text-stone-500" :aria-label="t('auth.backHome')">AIGCNEWS</RouterLink>
      <div class="glass-card p-4 sm:p-6">
        <AuthPageHeader :title="t('auth.wechatLogin.title')" :description="t('auth.wechatLogin.description')" title-id="wechat-login-title">
          <WeChatIcon class="h-7 w-7" />
        </AuthPageHeader>
        <div ref="frameContainer" class="wechat-login-frame relative mx-auto overflow-hidden rounded-xl border border-stone-200 bg-white" :style="{ height: `${400 * frameScale + 2}px` }" :aria-busy="status === 'loading'">
          <iframe
            v-if="frameUrl && (status === 'loading' || status === 'ready')"
            :key="frameUrl" :src="frameUrl" :title="t('auth.wechatLogin.frameTitle')"
            class="origin-top-left border-0" :style="{ transform: `scale(${frameScale})` }" referrerpolicy="no-referrer"
            @load="frameLoaded" @error="frameFailed"
          />
          <div v-if="status !== 'ready'" class="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-white px-5 text-center text-stone-700" role="status" aria-live="polite">
            <RefreshCw v-if="status === 'loading'" class="h-7 w-7 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            <ScanLine v-else class="h-9 w-9 text-stone-400" aria-hidden="true" />
            <p class="text-sm leading-relaxed">{{ t(`auth.wechatLogin.${status}`) }}</p>
            <button v-if="status !== 'loading'" type="button" class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium hover:bg-stone-100" @click="refresh">{{ t('auth.wechatLogin.retry') }}</button>
          </div>
        </div>
        <div class="mt-4 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-stone-500">
          <button v-if="status === 'ready'" type="button" class="inline-flex items-center gap-1.5 underline underline-offset-4" @click="refresh"><RefreshCw class="h-3.5 w-3.5" aria-hidden="true" />{{ t('auth.wechatLogin.refresh') }}</button>
          <a v-if="authorizationUrl" :href="authorizationUrl" class="underline underline-offset-4" referrerpolicy="no-referrer">{{ t('auth.wechatLogin.openOfficial') }}</a>
        </div>
        <p class="mt-5 text-center text-xs leading-relaxed text-stone-500">{{ t('auth.wechatLogin.accountHint') }}</p>
        <button type="button" class="btn-secondary mt-4 w-full justify-center py-2.5" @click="requestLogin(redirect)">{{ t('auth.wechatLogin.otherMethods') }}</button>
      </div>
      <RouterLink to="/" class="mt-6 block text-center text-xs text-stone-500 underline underline-offset-4">{{ t('auth.backHome') }}</RouterLink>
    </section>
  </main>
</template>

<style scoped>
/* Keep the official QR canvas white in both themes and within narrow viewports. */
.wechat-login-frame { width: 100%; max-width: 300px; color-scheme: light; }
.wechat-login-frame iframe { display: block; width: 300px; height: 400px; }
</style>
