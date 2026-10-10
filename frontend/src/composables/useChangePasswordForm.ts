import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getErrorDetail,
  isRateLimited,
  isValidOtp,
  isValidPassword,
  passwordsMatch,
} from '@/features/auth/authViewModel'
import { useOtpCountdown } from './useOtpCountdown'

interface ChangePasswordFormOptions {
  submit: (emailCode: string, newPassword: string) => Promise<unknown>
  /** 发送改密验证码到当前账号邮箱 */
  sendOtp: () => Promise<unknown>
  /** 改密成功后回调；调用方可先安装服务端返回的新令牌，再刷新账户资料。 */
  onChanged?: (result?: unknown) => Promise<void> | void
  successMessage?: () => string
  otpSentMessage?: () => string
}

/** 已登录改密表单状态：邮箱验证码 + 新密码确认（验证码替代当前密码） */
export function useChangePasswordForm({ submit, sendOtp, onChanged, successMessage, otpSentMessage }: ChangePasswordFormOptions) {
  const { t } = useI18n()

  const otp = ref('')
  const password = ref('')
  const confirmPwd = ref('')
  const loading = ref(false)
  const otpLoading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const changeDone = ref(false)

  const {
    countdown,
    start: startCountdown,
    reset: resetCountdown,
  } = useOtpCountdown({ clearBeforeStart: true })

  const otpBtnDisabled = computed(
    () => countdown.value > 0 || otpLoading.value || changeDone.value
  )

  const reset = () => {
    otp.value = ''
    password.value = ''
    confirmPwd.value = ''
    loading.value = false
    otpLoading.value = false
    errorMsg.value = ''
    successMsg.value = ''
    changeDone.value = false
    resetCountdown()
  }

  const handleSendOtp = async () => {
    errorMsg.value = ''
    successMsg.value = ''
    if (otpBtnDisabled.value) return

    otpLoading.value = true
    try {
      await sendOtp()
      startCountdown()
      successMsg.value = otpSentMessage?.() ?? t('auth.changeOtpSent')
    } catch (e: unknown) {
      errorMsg.value = isRateLimited(e)
        ? t('auth.rateLimited')
        : getErrorDetail(e, t('auth.sendOtpFailed'))
    } finally {
      otpLoading.value = false
    }
  }

  const handleSubmit = async () => {
    if (loading.value || changeDone.value) return
    errorMsg.value = ''
    successMsg.value = ''
    if (!isValidOtp(otp.value)) {
      errorMsg.value = t('auth.invalidOtp')
      return
    }
    if (!isValidPassword(password.value)) {
      errorMsg.value = t('auth.passwordMin')
      return
    }
    if (!passwordsMatch(password.value, confirmPwd.value)) {
      errorMsg.value = t('auth.passwordMismatch')
      return
    }

    loading.value = true
    try {
      const result = await submit(otp.value.trim(), password.value)
      await onChanged?.(result)
      changeDone.value = true
      successMsg.value = successMessage?.() ?? t('auth.changeSuccess')
      resetCountdown()
    } catch (e: unknown) {
      errorMsg.value = isRateLimited(e)
        ? t('auth.rateLimited')
        : getErrorDetail(e, t('auth.changeFailed'))
    } finally {
      loading.value = false
    }
  }

  return {
    otp,
    password,
    confirmPwd,
    loading,
    otpLoading,
    errorMsg,
    successMsg,
    changeDone,
    countdown,
    otpBtnDisabled,
    reset,
    handleSendOtp,
    handleSubmit,
  }
}
