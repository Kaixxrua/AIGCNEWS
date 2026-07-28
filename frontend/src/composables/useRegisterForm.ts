import { computed, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getErrorDetail,
  hasTrimmedValue,
  isRateLimited,
  isValidEmail,
  isValidOtp,
  isValidPassword,
  passwordsMatch,
  REGISTER_REDIRECT_DELAY_MS,
  REGISTER_SUCCESS_MESSAGE_DURATION_MS,
} from '../features/auth/authViewModel'
import { useOtpCountdown } from './useOtpCountdown'

interface RegisterFormDependencies {
  post: (url: string, payload: Record<string, string>) => Promise<unknown>
  login: (email: string, password: string) => Promise<unknown>
  replace: () => void | Promise<unknown>
}

export const useRegisterForm = ({ post, login, replace }: RegisterFormDependencies) => {
  const { t } = useI18n()
  const email = ref('')
  const otp = ref('')
  const password = ref('')
  const confirmPwd = ref('')
  const loading = ref(false)
  const otpLoading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const agreedToTerms = ref(false)

  const { countdown, start: startCountdown } = useOtpCountdown()
  const successTimers = new Set<ReturnType<typeof setTimeout>>()
  let redirectTimer: ReturnType<typeof setTimeout> | null = null

  const emailValid = computed(() => isValidEmail(email.value))
  const otpBtnDisabled = computed(
    () => !emailValid.value || countdown.value > 0 || otpLoading.value
  )

  const sendOtp = async () => {
    errorMsg.value = ''
    if (!emailValid.value) {
      errorMsg.value = t('auth.invalidEmailGeneric')
      return
    }
    if (countdown.value > 0) return
    otpLoading.value = true
    try {
      await post('/auth/send-email-otp', { email: email.value.trim() })
      startCountdown()
      successMsg.value = t('auth.otpSent')
      const timer = setTimeout(() => {
        successMsg.value = ''
        successTimers.delete(timer)
      }, REGISTER_SUCCESS_MESSAGE_DURATION_MS)
      successTimers.add(timer)
    } catch (e: unknown) {
      if (isRateLimited(e)) {
        errorMsg.value = t('auth.rateLimited')
      } else {
        errorMsg.value = getErrorDetail(e, t('auth.sendOtpFailed'))
      }
    } finally {
      otpLoading.value = false
    }
  }

  const handleRegister = async () => {
    errorMsg.value = ''
    if (!emailValid.value) { errorMsg.value = t('auth.invalidEmailGeneric'); return }
    if (!hasTrimmedValue(otp.value) || !isValidOtp(otp.value)) { errorMsg.value = t('auth.invalidOtp'); return }
    if (!isValidPassword(password.value)) { errorMsg.value = t('auth.passwordMin'); return }
    if (!passwordsMatch(password.value, confirmPwd.value)) { errorMsg.value = t('auth.passwordMismatch'); return }
    if (!agreedToTerms.value) { errorMsg.value = t('auth.mustAgree'); return }

    loading.value = true
    try {
      const normalizedEmail = email.value.trim()
      await post('/auth/register', {
        email: normalizedEmail,
        email_code: otp.value.trim(),
        password: password.value,
      })
      await login(normalizedEmail, password.value)
      successMsg.value = t('auth.registerSuccess')
      redirectTimer = setTimeout(() => {
        void replace()
      }, REGISTER_REDIRECT_DELAY_MS)
    } catch (e: unknown) {
      errorMsg.value = getErrorDetail(e, t('auth.registerFailed'))
    } finally {
      loading.value = false
    }
  }

  onUnmounted(() => {
    successTimers.forEach(clearTimeout)
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
    agreedToTerms,
    countdown,
    emailValid,
    otpBtnDisabled,
    sendOtp,
    handleRegister,
  }
}
