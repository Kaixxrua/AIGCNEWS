import { computed, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
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

export const usePasswordResetForm = ({ post, replaceLogin }: PasswordResetFormDependencies) => {
  const { t } = useI18n()
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
      errorMsg.value = t('auth.invalidEmailGeneric')
      return
    }
    if (countdown.value > 0 || resetDone.value) return

    otpLoading.value = true
    try {
      await post('/auth/send-password-reset-otp', { email: email.value.trim() })
      startCountdown()
      successMsg.value = t('auth.otpSentIfRegistered')
    } catch (e: unknown) {
      errorMsg.value = isRateLimited(e)
        ? t('auth.rateLimited')
        : getErrorDetail(e, t('auth.sendOtpFailed'))
    } finally {
      otpLoading.value = false
    }
  }

  const handleReset = async () => {
    errorMsg.value = ''
    successMsg.value = ''
    if (!emailValid.value) { errorMsg.value = t('auth.invalidEmailGeneric'); return }
    if (!isValidOtp(otp.value)) { errorMsg.value = t('auth.invalidOtp'); return }
    if (!isValidPassword(password.value)) { errorMsg.value = t('auth.passwordMin'); return }
    if (!passwordsMatch(password.value, confirmPwd.value)) { errorMsg.value = t('auth.passwordMismatch'); return }

    loading.value = true
    try {
      await post('/auth/reset-password', {
        email: email.value.trim(),
        email_code: otp.value.trim(),
        new_password: password.value,
      })
      resetDone.value = true
      successMsg.value = t('auth.resetSuccess')
      resetCountdown()
      redirectTimer = setTimeout(() => {
        void replaceLogin()
      }, PASSWORD_RESET_REDIRECT_DELAY_MS)
    } catch (e: unknown) {
      errorMsg.value = isRateLimited(e)
        ? t('auth.rateLimited')
        : getErrorDetail(e, t('auth.resetFailed'))
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
