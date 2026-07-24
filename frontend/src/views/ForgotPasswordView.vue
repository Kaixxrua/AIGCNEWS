<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useOtpCountdown } from '../composables/useOtpCountdown'
import { api } from '../services/api'
import {
  getErrorDetail,
  getSafeInternalRedirect,
  isRateLimited,
  isValidEmail,
  isValidOtp,
  isValidPassword,
  PASSWORD_RESET_REDIRECT_DELAY_MS,
  passwordsMatch,
} from '../features/auth/authViewModel'

const router = useRouter()
const route = useRoute()

const redirect = computed(() => getSafeInternalRedirect(route.query.redirect))
const redirectQuery = computed(() => ({ redirect: redirect.value }))

const email      = ref('')
const otp        = ref('')
const password   = ref('')
const confirmPwd = ref('')
const loading    = ref(false)
const otpLoading = ref(false)
const errorMsg   = ref('')
const successMsg = ref('')
const resetDone  = ref(false)

const {
  countdown,
  start: startCountdown,
  reset: resetCountdown,
} = useOtpCountdown({ clearBeforeStart: true })
let redirectTimer: ReturnType<typeof setTimeout> | null = null

const emailValid = computed(() => isValidEmail(email.value))

const otpBtnDisabled = computed(
  () => !emailValid.value || countdown.value > 0 || otpLoading.value || resetDone.value
)

onUnmounted(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
})

const sendOtp = async () => {
  errorMsg.value = ''
  successMsg.value = ''
  if (!emailValid.value) {
    errorMsg.value = '请输入有效的邮箱地址'
    return
  }
  if (countdown.value > 0 || resetDone.value) return

  otpLoading.value = true
  try {
    await api.post('/auth/send-password-reset-otp', { email: email.value.trim() })
    startCountdown()
    successMsg.value = '如果该邮箱已注册，验证码将发送至该邮箱'
  } catch (e: unknown) {
    errorMsg.value = isRateLimited(e)
      ? '请 60 秒后再试'
      : getErrorDetail(e, '发送验证码失败，请稍后再试')
  } finally {
    otpLoading.value = false
  }
}

const handleReset = async () => {
  errorMsg.value = ''
  successMsg.value = ''
  if (!emailValid.value) { errorMsg.value = '请输入有效的邮箱地址'; return }
  if (!isValidOtp(otp.value)) { errorMsg.value = '验证码应为 6 位数字'; return }
  if (!isValidPassword(password.value)) { errorMsg.value = '密码至少需要 6 个字符'; return }
  if (!passwordsMatch(password.value, confirmPwd.value)) { errorMsg.value = '两次密码输入不一致'; return }

  loading.value = true
  try {
    await api.post('/auth/reset-password', {
      email: email.value.trim(),
      email_code: otp.value.trim(),
      new_password: password.value,
    })
    resetDone.value = true
    successMsg.value = '密码重置成功，即将返回登录页…'
    resetCountdown()
    redirectTimer = setTimeout(() => {
      router.replace({ path: '/login', query: redirectQuery.value })
    }, PASSWORD_RESET_REDIRECT_DELAY_MS)
  } catch (e: unknown) {
    errorMsg.value = isRateLimited(e)
      ? '请 60 秒后再试'
      : getErrorDetail(e, '密码重置失败，请稍后再试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex h-full items-center justify-center overflow-y-auto p-3 sm:p-6">
    <div class="w-full max-w-sm py-4">

      <!-- 标题区 -->
      <div class="mb-8 text-center stagger-enter">
        <div class="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-3xl bg-stone-100">
          <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M7 11V8a5 5 0 0110 0v3"/>
            <rect x="5" y="11" width="14" height="10" rx="2"/>
            <path d="M12 15v2"/>
          </svg>
        </div>
        <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">AIGC 资讯 · 重置密码</h1>
        <p class="mt-1 text-sm text-stone-400">通过邮箱验证码设置新密码</p>
      </div>

      <!-- 表单卡片 -->
      <div class="glass-card p-4 sm:p-6 space-y-4 stagger-enter" style="animation-delay: 0.1s">

        <!-- 邮箱 + 发送验证码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">邮箱</label>
          <div class="flex flex-col gap-2 sm:flex-row">
            <input
              v-model="email"
              type="email"
              class="input flex-1"
              placeholder="you@example.com"
              autocomplete="email"
              :disabled="loading || resetDone"
            />
            <button
              class="shrink-0 inline-flex w-full items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-xs font-medium sm:w-auto transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
              style="background: rgba(255,255,255,0.80); border: 1px solid rgba(168,162,158,0.25); color: #57534e; backdrop-filter: blur(10px); white-space: nowrap"
              :disabled="otpBtnDisabled || loading"
              @click="sendOtp"
            >
              <span v-if="otpLoading" class="h-3.5 w-3.5 rounded-full border-2 border-stone-300 border-t-stone-600 animate-spin" />
              <span v-else-if="countdown > 0">重新获取({{ countdown }}s)</span>
              <span v-else>获取验证码</span>
            </button>
          </div>
          <Transition name="fade-msg">
            <p v-if="email && !emailValid" class="text-2xs text-rose-500 pl-1">请输入正确格式的邮箱地址</p>
          </Transition>
        </div>

        <!-- 邮箱验证码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">验证码</label>
          <input
            v-model="otp"
            type="text"
            inputmode="numeric"
            maxlength="6"
            class="input tracking-widest"
            placeholder="6 位数字验证码"
            autocomplete="one-time-code"
            :disabled="loading || resetDone"
          />
        </div>

        <!-- 新密码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">新密码</label>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="至少 6 个字符"
            autocomplete="new-password"
            :disabled="loading || resetDone"
          />
          <Transition name="fade-msg">
            <p v-if="password && password.length < 6" class="text-2xs text-rose-500 pl-1">密码至少需要 6 个字符</p>
          </Transition>
        </div>

        <!-- 确认新密码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">确认新密码</label>
          <input
            v-model="confirmPwd"
            type="password"
            class="input"
            placeholder="再次输入新密码"
            autocomplete="new-password"
            :disabled="loading || resetDone"
            @keydown.enter="handleReset"
          />
          <Transition name="fade-msg">
            <p v-if="confirmPwd && password !== confirmPwd" class="text-2xs text-rose-500 pl-1">两次密码输入不一致</p>
          </Transition>
        </div>

        <!-- 错误提示 -->
        <Transition name="fade-msg">
          <div
            v-if="errorMsg"
            class="flex items-center gap-2 rounded-2xl bg-rose-50 px-4 py-2.5 text-sm text-rose-600 border border-rose-200"
          >
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {{ errorMsg }}
          </div>
        </Transition>

        <!-- 成功提示 -->
        <Transition name="fade-msg">
          <div
            v-if="successMsg"
            class="flex items-center gap-2 rounded-2xl bg-green-50 px-4 py-2.5 text-sm text-green-700 border border-green-200"
          >
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            {{ successMsg }}
          </div>
        </Transition>

        <!-- 重置按钮 -->
        <button
          class="btn-primary w-full justify-center py-3"
          :disabled="loading || resetDone"
          @click="handleReset"
        >
          <span v-if="loading" class="h-4 w-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
          <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 101.6-5.1"/>
            <polyline points="3 4 3 10 9 10"/>
          </svg>
          {{ loading ? '重置中…' : '重置密码' }}
        </button>
      </div>

      <!-- 返回登录链接 -->
      <p class="mt-5 text-center text-sm text-stone-400 stagger-enter" style="animation-delay: 0.2s">
        想起密码了？
        <RouterLink :to="{ path: '/login', query: redirectQuery }" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">
          返回登录
        </RouterLink>
      </p>

    </div>
  </div>
</template>

<style scoped>
.fade-msg-enter-active,
.fade-msg-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-msg-enter-from,
.fade-msg-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
