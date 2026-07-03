<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '../services/api'
import { useAuthStore } from '../stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const email         = ref('')
const otp           = ref('')
const password      = ref('')
const confirmPwd    = ref('')
const loading       = ref(false)
const otpLoading    = ref(false)
const errorMsg      = ref('')
const successMsg    = ref('')
const agreedToTerms = ref(false)

// OTP 倒计时
const countdown     = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null

// 邮箱格式校验
const emailValid = computed(() =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())
)

const otpBtnDisabled = computed(
  () => !emailValid.value || countdown.value > 0 || otpLoading.value
)

const startCountdown = () => {
  countdown.value = 60
  countdownTimer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      clearInterval(countdownTimer!)
      countdownTimer = null
      countdown.value = 0
    }
  }, 1000)
}

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

const sendOtp = async () => {
  errorMsg.value = ''
  if (!emailValid.value) {
    errorMsg.value = '请输入有效的邮箱地址'
    return
  }
  if (countdown.value > 0) return
  otpLoading.value = true
  try {
    await api.post('/auth/send-email-otp', { email: email.value.trim() })
    startCountdown()
    successMsg.value = '验证码已发送，请查收邮件'
    setTimeout(() => { successMsg.value = '' }, 4000)
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { detail?: string } }; message?: string }
    if (err?.response?.status === 429) {
      errorMsg.value = '请 60 秒后再试'
    } else {
      errorMsg.value = err?.response?.data?.detail || err?.message || '发送验证码失败，请稍后再试'
    }
  } finally {
    otpLoading.value = false
  }
}

const handleRegister = async () => {
  errorMsg.value = ''
  if (!emailValid.value) { errorMsg.value = '请输入有效的邮箱地址'; return }
  if (!otp.value.trim() || !/^\d{6}$/.test(otp.value.trim())) { errorMsg.value = '验证码应为 6 位数字'; return }
  if (!password.value) { errorMsg.value = '请设置密码'; return }
  if (password.value !== confirmPwd.value) { errorMsg.value = '两次密码输入不一致'; return }
  if (!agreedToTerms.value) { errorMsg.value = '请阅读并同意《用户协议与免责声明》后再注册'; return }

  loading.value = true
  try {
    await api.post('/auth/register', {
      email: email.value.trim(),
      email_code: otp.value.trim(),
      password: password.value,
    })
    // 注册成功后自动登录
    await authStore.login(email.value.trim(), password.value)
    successMsg.value = '注册成功！正在为您自动登录…'
    const redirect = (route.query.redirect as string) || '/'
    setTimeout(() => router.replace(redirect), 800)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    errorMsg.value = err?.response?.data?.detail || err?.message || '注册失败，请稍后再试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex h-full items-center justify-center overflow-y-auto p-6">
    <div class="w-full max-w-sm py-4">

      <!-- 标题区 -->
      <div class="mb-8 text-center stagger-enter">
        <div class="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-3xl bg-stone-100">
          <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
        </div>
        <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">AIGC 资讯 · 注册</h1>
        <p class="mt-1 text-sm text-stone-400">创建您的账号，开启 AI 资讯之旅</p>
      </div>

      <!-- 表单卡片 -->
      <div class="glass-card p-6 space-y-4 stagger-enter" style="animation-delay: 0.1s">

        <!-- 邮箱 + 发送验证码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">邮箱</label>
          <div class="flex gap-2">
            <input
              v-model="email"
              type="email"
              class="input flex-1"
              placeholder="you@example.com"
              autocomplete="email"
              :disabled="loading"
            />
            <button
              class="shrink-0 inline-flex items-center gap-1.5 rounded-full px-4 py-2.5 text-xs font-medium transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
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
            :disabled="loading"
          />
        </div>

        <!-- 密码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">密码</label>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="请设置密码"
            autocomplete="new-password"
            :disabled="loading"
          />
        </div>

        <!-- 确认密码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">确认密码</label>
          <input
            v-model="confirmPwd"
            type="password"
            class="input"
            placeholder="再次输入密码"
            autocomplete="new-password"
            :disabled="loading"
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

        <!-- 用户协议勾选 -->
        <div class="flex items-start gap-2.5 pt-1">
          <button
            type="button"
            class="mt-0.5 shrink-0 w-4 h-4 rounded border transition-all duration-150 flex items-center justify-center"
            :class="agreedToTerms
              ? 'bg-stone-800 border-stone-800'
              : 'bg-white border-stone-300 hover:border-stone-500'"
            @click="agreedToTerms = !agreedToTerms"
          >
            <svg v-if="agreedToTerms" viewBox="0 0 12 12" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-2.5 h-2.5">
              <polyline points="2,6 5,9 10,3"/>
            </svg>
          </button>
          <label class="text-xs text-stone-500 leading-relaxed cursor-pointer select-none" @click="agreedToTerms = !agreedToTerms">
            我已阅读并同意
            <RouterLink to="/disclaimer" target="_blank" class="text-stone-700 underline underline-offset-2 hover:text-stone-900" @click.stop>《用户协议与免责声明》</RouterLink>
            及
            <RouterLink to="/privacy" target="_blank" class="text-stone-700 underline underline-offset-2 hover:text-stone-900" @click.stop>《隐私政策》</RouterLink>
            ，包括但不限于 AI 内容免责、禁止违法输入等条款
          </label>
        </div>

        <!-- 注册按钮 -->
        <button
          class="btn-primary w-full justify-center py-3"
          :disabled="loading || !agreedToTerms"
          @click="handleRegister"
        >
          <span v-if="loading" class="h-4 w-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
          <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <line x1="19" y1="8" x2="19" y2="14"/>
            <line x1="22" y1="11" x2="16" y2="11"/>
          </svg>
          {{ loading ? '注册中…' : '注册' }}
        </button>
      </div>

      <!-- 底部登录链接 -->
      <p class="mt-5 text-center text-sm text-stone-400 stagger-enter" style="animation-delay: 0.2s">
        已有账号？
        <RouterLink to="/login" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">
          去登录
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
