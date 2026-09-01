<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import {
  confirmEmailChange,
  sendEmailChangeCurrentOtp,
  sendEmailChangeNewOtp,
  startOAuthBinding,
  updateProfile,
  type AuthUserDTO,
} from '@/services/auth/authApi'
import ChangePasswordDialog from '@/components/auth/ChangePasswordDialog.vue'
import OAuthProviderIcon from '@/components/auth/OAuthProviderIcon.vue'
import AuthFeedback from '@/components/auth/AuthFeedback.vue'
import { getErrorDetail } from '@/features/auth/authViewModel'
import { useDockSuppression } from '@/composables/useDockSuppression'
import { useEmailChangeForm } from '@/composables/useEmailChangeForm'

const props = defineProps<{
  modelValue: boolean
}>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const { t, locale } = useI18n()
const authStore = useAuthStore()
const route = useRoute()
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
useDockSuppression(() => props.modelValue)

const dialogRef = ref<HTMLElement | null>(null)
const username = ref('')
const saving = ref(false)
const error = ref('')
const success = ref('')
const passwordOpen = ref(false)
const emailChangeOpen = ref(false)
let previouslyFocused: HTMLElement | null = null

const currentUser = computed(() => authStore.user)
const usernameValue = computed(() => currentUser.value?.username ?? '')
const registeredAt = computed(() => {
  const value = currentUser.value?.created_at
  if (!value) return t('auth.notAvailable')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return t('auth.notAvailable')
  return new Intl.DateTimeFormat(locale.value, { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
})
const providerLabel = (provider: string) => provider === 'github' ? 'GitHub' : provider === 'google' ? 'Google' : provider === 'wechat' ? '微信' : provider
const providers = ['github', 'google', 'wechat']
const connectedProviders = computed(() => new Set((currentUser.value?.oauth_identities ?? []).map(identity => identity.provider)))

// 换绑邮箱：双验证码表单（当前邮箱 + 新邮箱）；成功后安装服务端权威投影
const {
  newEmail,
  currentCode,
  newCode,
  loading: emailChanging,
  currentOtpLoading,
  newOtpLoading,
  errorMsg: emailChangeError,
  successMsg: emailChangeSuccess,
  changeDone: emailChangeDone,
  currentOtpCountdown,
  newOtpCountdown,
  currentOtpBtnDisabled,
  newOtpBtnDisabled,
  reset: resetEmailChange,
  handleSendCurrentOtp,
  handleSendNewOtp,
  handleSubmit: submitEmailChange,
} = useEmailChangeForm({
  submit: (nextEmail, curCode, nextCode) => confirmEmailChange(nextEmail, curCode, nextCode),
  sendCurrentOtp: () => sendEmailChangeCurrentOtp(),
  sendNewOtp: (nextEmail) => sendEmailChangeNewOtp(nextEmail),
  onChanged: (result) => { authStore.user = result as AuthUserDTO },
})

const toggleEmailChange = () => {
  emailChangeOpen.value = !emailChangeOpen.value
  if (emailChangeOpen.value) resetEmailChange()
}
const closeEmailChange = () => { emailChangeOpen.value = false; resetEmailChange() }

// 未连接渠道点击发起「已认证绑定」：整页跳转后端 bind/start，目标账户只存服务端 state
const bindProvider = (provider: string) => {
  if (connectedProviders.value.has(provider)) return
  void startOAuthBinding(provider, route.fullPath)
}

const close = () => { passwordOpen.value = false; visible.value = false }
const onKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Escape' || !visible.value) return
  if (passwordOpen.value) return
  if (emailChangeOpen.value) { closeEmailChange(); return }
  close()
}
const saveUsername = async () => {
  const next = username.value.trim()
  error.value = ''; success.value = ''
  if (!next) { error.value = t('auth.usernameRequired'); return }
  if (next.length > 64) { error.value = t('auth.usernameTooLong'); return }
  saving.value = true
  try {
    const updated = await updateProfile(next)
    authStore.user = updated
    username.value = updated.username ?? next
    success.value = t('auth.usernameSaved')
  } catch (reason: unknown) {
    error.value = getErrorDetail(reason, t('auth.usernameSaveFailed'))
  } finally { saving.value = false }
}

watch(() => props.modelValue, async open => {
  if (open) {
    previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    username.value = usernameValue.value
    error.value = ''; success.value = ''
    passwordOpen.value = false
    closeEmailChange()
    window.addEventListener('keydown', onKeydown)
    await nextTick(); dialogRef.value?.focus()
  } else {
    window.removeEventListener('keydown', onKeydown)
    passwordOpen.value = false
    closeEmailChange()
    await nextTick(); previouslyFocused?.focus(); previouslyFocused = null
  }
}, { immediate: true })
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="account-settings-dialog-title" @click.self="close">
        <div ref="dialogRef" class="glass-card max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto" tabindex="-1">
          <div class="monitor-divider flex items-center justify-between border-b p-4">
            <div>
              <h3 id="account-settings-dialog-title" class="text-sm font-semibold">{{ t('auth.accountSettings') }}</h3>
              <p class="mt-1 text-xs monitor-caption">{{ t('auth.accountOverviewDescription') }}</p>
            </div>
            <button type="button" class="text-lg leading-none opacity-70 hover:opacity-100" :aria-label="t('auth.closeAccountSettings')" @click="close">✕</button>
          </div>

          <div class="space-y-5 p-5">
            <section aria-labelledby="account-overview-title" class="space-y-3">
              <h4 id="account-overview-title" class="text-xs font-semibold uppercase tracking-wider text-stone-500">{{ t('auth.accountOverview') }}</h4>
              <dl class="grid gap-3 text-sm sm:grid-cols-2">
                <div><dt class="text-xs text-stone-500">{{ t('auth.username') }}</dt><dd class="mt-1 font-medium">{{ usernameValue || t('auth.notSet') }}</dd></div>
                <div>
                  <dt class="text-xs text-stone-500">{{ t('auth.email') }}</dt>
                  <dd class="mt-1 flex items-center gap-2 font-medium">
                    <span class="min-w-0 break-all">{{ currentUser?.email || t('auth.notSet') }}</span>
                    <button
                      v-if="currentUser?.email"
                      type="button"
                      class="shrink-0 text-xs font-normal text-stone-500 underline-offset-2 hover:text-stone-800 hover:underline"
                      @click="toggleEmailChange"
                    >{{ t('auth.changeEmailAction') }}</button>
                  </dd>
                </div>
                <div><dt class="text-xs text-stone-500">{{ t('auth.emailVerified') }}</dt><dd class="mt-1">{{ currentUser?.email_verified === true ? t('auth.verified') : t('auth.unverified') }}</dd></div>
                <div><dt class="text-xs text-stone-500">{{ t('auth.registeredAt') }}</dt><dd class="mt-1">{{ registeredAt }}</dd></div>
                <div><dt class="text-xs text-stone-500">{{ t('auth.role') }}</dt><dd class="mt-1">{{ currentUser?.role || t('auth.notAvailable') }}</dd></div>
                <div><dt class="text-xs text-stone-500">{{ t('auth.membership') }}</dt><dd class="mt-1">{{ currentUser?.membership_tier === 'member' ? t('auth.memberMembership') : t('auth.freeMembership') }}</dd></div>
              </dl>
            </section>

            <section v-if="emailChangeOpen" aria-labelledby="email-change-title" class="space-y-3 border-t border-stone-200/70 pt-4">
              <h4 id="email-change-title" class="text-xs font-semibold text-stone-500">{{ t('auth.emailChangeTitle') }}</h4>
              <p class="text-xs leading-5 monitor-caption">{{ t('auth.emailChangeHint') }}</p>

              <div class="space-y-1.5">
                <label for="account-settings-new-email" class="text-xs font-medium text-stone-500">{{ t('auth.newEmailLabel') }}</label>
                <div class="flex flex-col gap-2 sm:flex-row">
                  <input
                    id="account-settings-new-email"
                    v-model="newEmail"
                    type="email"
                    class="input flex-1"
                    :placeholder="t('auth.newEmailPlaceholder')"
                    autocomplete="email"
                    :disabled="emailChanging || emailChangeDone"
                  />
                  <button
                    type="button"
                    class="inline-flex w-full shrink-0 items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-xs font-medium transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
                    style="background: rgb(var(--card-rgb) / 0.8); border: 1px solid rgb(var(--stone-400-rgb) / 0.25); color: rgb(var(--stone-600-rgb)); backdrop-filter: blur(10px); white-space: nowrap"
                    :disabled="newOtpBtnDisabled"
                    @click="handleSendNewOtp"
                  >
                    <span v-if="newOtpLoading" class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-stone-600" />
                    <span v-else-if="newOtpCountdown > 0">{{ t('auth.resendOtp', { countdown: newOtpCountdown }) }}</span>
                    <span v-else>{{ t('auth.getOtp') }}</span>
                  </button>
                </div>
              </div>

              <div class="space-y-1.5">
                <label for="account-settings-current-code" class="text-xs font-medium text-stone-500">{{ t('auth.currentEmailOtpLabel') }}</label>
                <div class="flex flex-col gap-2 sm:flex-row">
                  <input
                    id="account-settings-current-code"
                    v-model="currentCode"
                    type="text"
                    inputmode="numeric"
                    class="input flex-1"
                    :placeholder="t('auth.otpPlaceholder')"
                    autocomplete="one-time-code"
                    :disabled="emailChanging || emailChangeDone"
                  />
                  <button
                    type="button"
                    class="inline-flex w-full shrink-0 items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-xs font-medium transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
                    style="background: rgb(var(--card-rgb) / 0.8); border: 1px solid rgb(var(--stone-400-rgb) / 0.25); color: rgb(var(--stone-600-rgb)); backdrop-filter: blur(10px); white-space: nowrap"
                    :disabled="currentOtpBtnDisabled"
                    @click="handleSendCurrentOtp"
                  >
                    <span v-if="currentOtpLoading" class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-stone-600" />
                    <span v-else-if="currentOtpCountdown > 0">{{ t('auth.resendOtp', { countdown: currentOtpCountdown }) }}</span>
                    <span v-else>{{ t('auth.getOtp') }}</span>
                  </button>
                </div>
              </div>

              <div class="space-y-1.5">
                <label for="account-settings-new-code" class="text-xs font-medium text-stone-500">{{ t('auth.newEmailOtpLabel') }}</label>
                <input
                  id="account-settings-new-code"
                  v-model="newCode"
                  type="text"
                  inputmode="numeric"
                  class="input flex-1"
                  :placeholder="t('auth.otpPlaceholder')"
                  autocomplete="one-time-code"
                  :disabled="emailChanging || emailChangeDone"
                />
              </div>

              <AuthFeedback :message="emailChangeError" type="error" />
              <AuthFeedback :message="emailChangeSuccess" type="success" />

              <div class="grid grid-cols-2 gap-2">
                <button type="button" class="btn-secondary w-full justify-center py-2.5" @click="closeEmailChange">{{ t('common.cancel') }}</button>
                <button
                  type="button"
                  class="btn-primary w-full justify-center py-2.5"
                  :disabled="emailChanging || emailChangeDone"
                  @click="submitEmailChange"
                >
                  <span v-if="emailChanging" class="h-4 w-4 animate-spin rounded-full border-2" style="border-color: color-mix(in srgb, currentColor 40%, transparent); border-top-color: currentColor" />
                  {{ emailChanging ? t('auth.emailChanging') : t('auth.emailChangeSubmit') }}
                </button>
              </div>
            </section>

            <section class="space-y-3 border-t border-stone-200/70 pt-4">
              <label for="account-settings-username" class="text-xs font-semibold text-stone-500">{{ t('auth.editUsername') }}</label>
              <div class="flex gap-2">
                <input id="account-settings-username" v-model="username" class="input min-w-0 flex-1" maxlength="64" autocomplete="username" :disabled="saving" />
                <button type="button" class="btn-primary shrink-0" :disabled="saving" @click="saveUsername">{{ saving ? t('auth.savingUsername') : t('auth.saveUsername') }}</button>
              </div>
              <AuthFeedback :message="error" type="error" /><AuthFeedback :message="success" type="success" />
            </section>

            <section class="space-y-3 border-t border-stone-200/70 pt-4">
              <div class="flex items-center justify-between"><h4 class="text-xs font-semibold text-stone-500">{{ t('auth.connectedLoginMethods') }}</h4><span class="text-xs monitor-caption">{{ (currentUser?.oauth_identities ?? []).length }}</span></div>
              <div class="grid grid-cols-3 gap-2">
                <button
                  v-for="provider in providers"
                  :key="provider"
                  type="button"
                  class="oauth-provider-btn"
                  :class="{ 'is-connected': connectedProviders.has(provider) }"
                  :disabled="connectedProviders.has(provider)"
                  :aria-label="connectedProviders.has(provider) ? `${providerLabel(provider)} ${t('auth.connected')}` : `${providerLabel(provider)} ${t('auth.notConnected')}`"
                  @click="bindProvider(provider)"
                >
                  <span class="flex min-w-0 w-full items-center gap-1.5">
                    <OAuthProviderIcon :provider="provider" class="oauth-provider-icon" />
                    <span class="oauth-provider-name">{{ providerLabel(provider) }}</span>
                    <span
                      class="oauth-provider-status"
                      :class="connectedProviders.has(provider) ? 'status-connected' : 'status-disconnected'"
                    >{{ connectedProviders.has(provider) ? t('auth.connected') : t('auth.notConnected') }}</span>
                  </span>
                </button>
              </div>
            </section>

            <section class="space-y-3 border-t border-stone-200/70 pt-4">
              <div class="flex items-center justify-between">
                <div><h4 class="text-xs font-semibold text-stone-500">{{ t('auth.passwordLogin') }}</h4><p class="mt-1 text-xs monitor-caption">{{ currentUser?.password_login_enabled === true ? t('auth.passwordEnabled') : t('auth.passwordDisabled') }}</p></div>
                <button v-if="currentUser?.password_login_enabled === true" type="button" class="btn-primary" @click="passwordOpen = true">{{ t('auth.changePasswordAction') }}</button>
              </div>
            </section>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
  <ChangePasswordDialog v-model="passwordOpen" />
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* 渠道按钮：图标 + 渠道名 + 连接状态同一行，保留触感交互 */
.oauth-provider-btn {
  @apply w-full rounded-lg border-2 px-2 py-2.5 text-xs font-semibold transition-all duration-150;
  background: var(--paper-raised);
  border-color: var(--rule-strong);
  color: var(--ink);
  box-shadow: var(--shadow-low);
}
.oauth-provider-btn:hover:not(:disabled) {
  background: var(--acid-soft);
  transform: translate(-1.5px, -1.5px);
  box-shadow: 3px 3px 0 var(--shadow-ink-soft);
}
.oauth-provider-btn:active:not(:disabled) {
  transform: translate(0, 1px);
  box-shadow: none;
}
.oauth-provider-btn.is-connected {
  cursor: default;
  background: transparent;
  opacity: 0.7;
  box-shadow: none;
  transform: none !important;
}
.oauth-provider-icon {
  width: 1.25rem;
  height: 1.25rem;
  flex-shrink: 0;
}
.oauth-provider-name {
  @apply truncate leading-tight;
  min-width: 0;
}
.oauth-provider-status {
  @apply ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-none;
}
.oauth-provider-status.status-connected {
  background: var(--success-surface, #dcfce7);
  color: var(--success-ink, #166534);
}
.oauth-provider-status.status-disconnected {
  background: var(--paper-muted, #f5f5f4);
  color: var(--ink-muted);
}
@media (max-width: 639px) {
  .oauth-provider-btn {
    padding: 0.5rem 0.375rem;
  }
  .oauth-provider-icon {
    width: 1rem;
    height: 1rem;
  }
}
</style>
