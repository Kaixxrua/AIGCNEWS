<script setup lang="ts">
import axios from 'axios'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthPageHeader from '@/components/auth/AuthPageHeader.vue'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import {
  MCP_OAUTH_SCOPE_GRANT_KEYS,
  isFramed,
  isSafeClientRedirect,
  parseAuthorizationQuery,
} from '@/features/mcp/mcpOAuthConsent'
import { installMcpOAuthMessages } from '@/i18n/locales/mcpOAuth'
import { vSwap } from '@/motion/swap'
import {
  decideMcpOAuthAuthorization,
  mcpOAuthErrorCode,
  navigateToMcpClient,
  previewMcpOAuthAuthorization,
  type McpOAuthDecision,
  type McpOAuthPreviewReady,
  type McpOAuthRedirectableError,
} from '@/services/mcp/mcpOAuthApi'
import { useAuthStore, type AuthStatus } from '@/stores/authStore'

/**
 * MCP OAuth 授权端点（RFC 6749 §3.1）：MCP 客户端把浏览器带到这里，用户登录后看清是谁要什么权限，
 * 再决定同意或拒绝；后端给出回跳地址，页面跳回客户端。路由不设 requiresAuth：守卫的登录流程会把
 * 首次打开的页面换成首页，授权请求就丢了，所以登录在页内处理。
 */

installMcpOAuthMessages()

type Phase = 'checking' | 'degraded' | 'login' | 'loading' | 'ready' | 'returning' | 'error' | 'framed'
type ReturnOutcome = 'approved' | 'denied' | 'error'

/** 有专门文案的错误码（mcpOAuth.errors.*）；其余错误码与网络失败都按 unknown 说，并可重试。 */
const DESCRIBED_ERRORS = new Set([
  'invalid_client',
  'invalid_redirect_uri',
  'invalid_request',
  'unsupported_response_type',
  'invalid_target',
  'temporarily_unavailable',
])

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()

const framed = isFramed()
const parsed = computed(() => parseAuthorizationQuery(route.query))
const requestKey = computed(() => JSON.stringify(parsed.value))
/**
 * 本页按 vue-router 的编码重拼的地址：查询值里的 / 和 : 不转义。第三方登录的 redirect_to
 * 校验拒收 %2F，客户端拼出的原始地址（redirect_uri=http%3A%2F%2F…）登录后回不来。
 */
const pageTarget = computed(() => router.resolve({ path: route.path, query: parsed.value.request }).fullPath)

const phase = ref<Phase>('checking')
const preview = ref<McpOAuthPreviewReady | null>(null)
const pending = ref<McpOAuthDecision | null>(null)
/** 后端给的 OAuth 错误码；网络失败等没有错误码时为空串。 */
const errorCode = ref('')
/** 能把错误带回客户端时的回跳地址。 */
const errorRedirect = ref<string | null>(null)
const returnUrl = ref('')
const returnOutcome = ref<ReturnOutcome>('approved')
let sequence = 0
let loginPrompted = false

const clientName = computed(() => preview.value?.client.client_name || t('mcpOAuth.unnamedClient'))
const accountName = computed(() => {
  const user = authStore.user
  return user?.username || user?.email || (user ? `#${user.user_id}` : '')
})
const returnTo = computed(() => {
  const redirect = preview.value?.redirect
  return redirect ? t(`mcpOAuth.returnTo.${redirect.kind}`, { host: redirect.host }) : ''
})
const grants = computed(() => [
  'tools',
  ...(preview.value?.scopes ?? []).flatMap((scope) => {
    const key = MCP_OAUTH_SCOPE_GRANT_KEYS[scope]
    return key ? [key] : []
  }),
])
const errorMessage = computed(() => t(`mcpOAuth.errors.${DESCRIBED_ERRORS.has(errorCode.value) ? errorCode.value : 'unknown'}`))
const canRetry = computed(() => !errorRedirect.value && (errorCode.value === 'temporarily_unavailable' || !DESCRIBED_ERRORS.has(errorCode.value)))

function showError(code: string | null, redirect: string | null = null): void {
  sequence += 1
  errorCode.value = code ?? ''
  errorRedirect.value = redirect
  phase.value = 'error'
}

function showClientError(result: McpOAuthRedirectableError): void {
  const redirect = isSafeClientRedirect(result.redirect_to, parsed.value.request.redirect_uri) ? result.redirect_to : null
  showError(result.error, redirect)
}

function handleFailure(error: unknown): void {
  if (axios.isAxiosError(error) && error.response?.status === 401) {
    // 会话失效：响应拦截器已清掉会话并弹出登录窗，重新登录后由下面的监听重新读取。
    phase.value = 'login'
    return
  }
  showError(mcpOAuthErrorCode(error))
}

function promptLogin(): void {
  requestLogin(pageTarget.value)
}

async function loadPreview(): Promise<void> {
  const current = ++sequence
  phase.value = 'loading'
  preview.value = null
  try {
    const result = await previewMcpOAuthAuthorization(parsed.value.request)
    if (current !== sequence) return
    if (result.status === 'ready') {
      preview.value = result
      phase.value = 'ready'
    } else {
      showClientError(result)
    }
  } catch (error: unknown) {
    if (current === sequence) handleFailure(error)
  }
}

function sync(status: AuthStatus): void {
  if (framed) {
    phase.value = 'framed'
    return
  }
  const { request, duplicated } = parsed.value
  // 不知道该回跳到哪里（RFC 6749 §4.1.2.1）：不登录也能直接告诉用户请求无效。
  if (duplicated || !request.client_id || !request.redirect_uri) {
    showError('invalid_request')
    return
  }
  if (route.fullPath !== pageTarget.value) {
    // 同一份参数换成 vue-router 编码，会话过期时拦截器按当前地址弹登录窗也能回到这里。
    void router.replace({ path: route.path, query: request, force: true })
  }
  sequence += 1
  pending.value = null
  if (status === 'initializing') {
    phase.value = 'checking'
    void authStore.ensureInitialized()
  } else if (status === 'degraded') {
    phase.value = 'degraded'
  } else if (status === 'anonymous') {
    phase.value = 'login'
    if (!loginPrompted) {
      loginPrompted = true
      promptLogin()
    }
  } else {
    void loadPreview()
  }
}

watch(
  [() => authStore.status, () => authStore.token, requestKey],
  ([status], previous) => {
    // 已经在跳回客户端：同一个授权请求不再重来，换了请求才重新开始。
    if (phase.value === 'returning' && previous?.[2] === requestKey.value) return
    sync(status)
  },
  { immediate: true },
)

function retry(): void {
  sync(authStore.status)
}

function retryAuth(): void {
  void authStore.ensureInitialized()
}

function switchAccount(): void {
  loginPrompted = true
  authStore.invalidateSession()
  promptLogin()
}

function returnToClient(url: string, outcome: ReturnOutcome): void {
  if (!isSafeClientRedirect(url, parsed.value.request.redirect_uri)) {
    showError('invalid_redirect_uri')
    return
  }
  sequence += 1
  returnUrl.value = url
  returnOutcome.value = outcome
  phase.value = 'returning'
  navigateToMcpClient(url)
}

function backToClient(): void {
  if (errorRedirect.value) returnToClient(errorRedirect.value, 'error')
}

async function decide(decision: McpOAuthDecision): Promise<void> {
  if (phase.value !== 'ready' || pending.value) return
  const current = ++sequence
  pending.value = decision
  try {
    const result = await decideMcpOAuthAuthorization(parsed.value.request, decision)
    if (current !== sequence) return
    if (result.status === 'error') showClientError(result)
    else returnToClient(result.redirect_to, result.status)
  } catch (error: unknown) {
    if (current === sequence) handleFailure(error)
  } finally {
    pending.value = null
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center p-3 sm:p-6">
    <div class="w-full max-w-md py-4">
      <AuthPageHeader :title="t('mcpOAuth.title')" :description="t('mcpOAuth.description')">
        <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="7.5" cy="15.5" r="4.5" />
          <path d="M10.7 12.3 20 3" />
          <path d="m16 7 3 3" />
          <path d="m14 9 2 2" />
        </svg>
      </AuthPageHeader>

      <section v-swap="{ key: phase }" class="glass-card space-y-4 p-4 sm:p-6" aria-live="polite" data-testid="mcp-oauth-card">
        <p v-if="phase === 'checking' || phase === 'loading'" class="text-center text-sm text-stone-500">
          {{ t(phase === 'checking' ? 'mcpOAuth.checking' : 'mcpOAuth.loading') }}
        </p>

        <template v-else-if="phase === 'degraded'">
          <p class="text-center text-sm text-stone-600">{{ t('mcpOAuth.degraded') }}</p>
          <button type="button" class="btn-primary w-full justify-center" @click="retryAuth">{{ t('mcpOAuth.retry') }}</button>
        </template>

        <template v-else-if="phase === 'login'">
          <h2 class="text-base font-semibold text-stone-800">{{ t('mcpOAuth.loginTitle') }}</h2>
          <p class="text-sm leading-6 text-stone-600">{{ t('mcpOAuth.loginBody') }}</p>
          <button type="button" class="btn-primary w-full justify-center" data-testid="mcp-oauth-login" @click="promptLogin">{{ t('mcpOAuth.login') }}</button>
        </template>

        <template v-else-if="phase === 'ready' && preview">
          <div>
            <h2 class="mcp-oauth-client text-lg font-semibold text-stone-800" data-testid="mcp-oauth-client">{{ clientName }}</h2>
            <p class="text-sm text-stone-500">{{ t('mcpOAuth.requesting') }}</p>
          </div>
          <p class="mcp-oauth-note mcp-oauth-note--warn">{{ t('mcpOAuth.unverifiedName') }}</p>
          <div class="space-y-1 text-sm text-stone-600">
            <p class="flex flex-wrap items-baseline gap-x-2">
              <span class="mcp-oauth-client">{{ t('mcpOAuth.account', { account: accountName }) }}</span>
              <button type="button" class="text-xs font-medium text-stone-500 underline underline-offset-2" :disabled="pending !== null" @click="switchAccount">
                {{ t('mcpOAuth.switchAccount') }}
              </button>
            </p>
            <p class="mcp-oauth-client" data-testid="mcp-oauth-return">{{ returnTo }}</p>
          </div>
          <div>
            <p class="text-sm font-medium text-stone-700">{{ t('mcpOAuth.grantsTitle') }}</p>
            <ul class="mt-2 list-disc space-y-1.5 pl-5 text-sm text-stone-600" data-testid="mcp-oauth-grants">
              <li v-for="key in grants" :key="key">{{ t(`mcpOAuth.grants.${key}`) }}</li>
            </ul>
          </div>
          <p class="text-xs leading-5 text-stone-500">{{ t('mcpOAuth.tokenNote') }}</p>
          <div class="grid grid-cols-2 gap-3">
            <button type="button" class="btn-secondary justify-center" :disabled="pending !== null" data-testid="mcp-oauth-deny" @click="decide('deny')">
              {{ t('mcpOAuth.deny') }}
            </button>
            <button type="button" class="btn-primary justify-center" :disabled="pending !== null" data-testid="mcp-oauth-approve" @click="decide('approve')">
              {{ t('mcpOAuth.approve') }}
            </button>
          </div>
        </template>

        <template v-else-if="phase === 'returning'">
          <p class="text-center text-sm font-medium text-stone-700">{{ t(`mcpOAuth.returning.${returnOutcome}`) }}</p>
          <p class="text-center text-xs leading-5 text-stone-500">{{ t('mcpOAuth.returningHint') }}</p>
          <a :href="returnUrl" class="btn-secondary w-full justify-center" data-testid="mcp-oauth-open-client">{{ t('mcpOAuth.openClient') }}</a>
        </template>

        <template v-else-if="phase === 'framed'">
          <h2 class="text-base font-semibold text-stone-800">{{ t('mcpOAuth.errorTitle') }}</h2>
          <p class="mcp-oauth-note mcp-oauth-note--error" role="alert">{{ t('mcpOAuth.errors.framed') }}</p>
        </template>

        <template v-else>
          <h2 class="text-base font-semibold text-stone-800">{{ t('mcpOAuth.errorTitle') }}</h2>
          <p class="mcp-oauth-note mcp-oauth-note--error" role="alert" data-testid="mcp-oauth-error">{{ errorMessage }}</p>
          <p v-if="errorCode" class="text-xs text-stone-400">{{ t('mcpOAuth.errorCode', { code: errorCode }) }}</p>
          <button v-if="errorRedirect" type="button" class="btn-primary w-full justify-center" data-testid="mcp-oauth-back" @click="backToClient">
            {{ t('mcpOAuth.backToClient') }}
          </button>
          <button v-else-if="canRetry" type="button" class="btn-primary w-full justify-center" @click="retry">{{ t('mcpOAuth.retry') }}</button>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
/* 客户端名、账号与回跳地址都由外部决定，长串不换行会撑破卡片 */
.mcp-oauth-client {
  overflow-wrap: anywhere;
}

.mcp-oauth-note {
  border-radius: var(--control-radius);
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.mcp-oauth-note--warn {
  color: var(--tone-amber);
  background: var(--tone-amber-soft);
}

.mcp-oauth-note--error {
  color: var(--tone-coral);
  background: var(--tone-coral-soft);
}
</style>
