import { computed, onUnmounted, ref } from 'vue'
import {
  getErrorDetail,
  isRateLimited,
  isValidEmail,
  isValidOtp,
  isValidPassword,
  PASSWORD_RESET_REDIRECT_DELAY_MS,
  passwordsMatch,
} from '../features/auth/authViewModel'
import { useOtpCountdown } from './useOtpCountdown'

interface PasswordResetFormDependencies {
  post: (url: string, payload: Record<string, string>) => Promise<unknown>
  replaceLogin: () => void | Promise<unknown>
}

export const usePasswordResetForm = ({
  post,
  replaceLogin,
}: PasswordResetFormDependencies) => {
  const email = ref('')
  const otp = ref('')
  const password = ref('')
  const confirmPwd = ref('')
  const loading = ref(false)
  const otpLoading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const resetDone = ref(false)

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
      await post('/auth/send-password-reset-otp', { email: email.value.trim() })
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
      await post('/auth/reset-password', {
        email: email.value.trim(),
        email_code: otp.value.trim(),
        new_password: password.value,
      })
      resetDone.value = true
      successMsg.value = '密码重置成功，即将返回登录页…'
      resetCountdown()
      redirectTimer = setTimeout(() => {
        void replaceLogin()
      }, PASSWORD_RESET_REDIRECT_DELAY_MS)
    } catch (e: unknown) {
      errorMsg.value = isRateLimited(e)
        ? '请 60 秒后再试'
        : getErrorDetail(e, '密码重置失败，请稍后再试')
    } finally {
      loading.value = false
    }
  }

  onUnmounted(() => {
    if (redirectTimer) clearTimeout(redirectTimer)
  })

  return {
    email,
    otp,
    password,
    confirmPwd,
    loading,
    otpLoading,
    errorMsg,
    successMsg,
    resetDone,
    countdown,
    emailValid,
    otpBtnDisabled,
    sendOtp,
    handleReset,
  }
}
