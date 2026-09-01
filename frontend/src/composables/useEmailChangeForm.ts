import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getErrorDetail,
  isRateLimited,
  isValidEmail,
  isValidOtp,
} from '@/features/auth/authViewModel'
import { useOtpCountdown } from './useOtpCountdown'

interface EmailChangeFormOptions {
  /** 双验证码确认换绑；返回服务端权威账户投影 */
  submit: (newEmail: string, currentCode: string, newCode: string) => Promise<unknown>
  /** 向数据库当前邮箱发码 */
  sendCurrentOtp: () => Promise<unknown>
  /** 向新邮箱发码 */
  sendNewOtp: (newEmail: string) => Promise<unknown>
  /** 换绑成功后回调：调用方应安装返回的权威投影（authStore.user = result） */
  onChanged?: (result?: unknown) => Promise<void> | void
}

/** 换绑邮箱表单状态：新邮箱 + 当前/新邮箱双验证码（两个独立倒计时） */
export function useEmailChangeForm({ submit, sendCurrentOtp, sendNewOtp, onChanged }: EmailChangeFormOptions) {
  const { t } = useI18n()

  const newEmail = ref('')
  const currentCode = ref('')
  const newCode = ref('')
  const loading = ref(false)
  const currentOtpLoading = ref(false)
  const newOtpLoading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const changeDone = ref(false)

  const currentCountdown = useOtpCountdown({ clearBeforeStart: true })
  const newCountdown = useOtpCountdown({ clearBeforeStart: true })

  const currentOtpBtnDisabled = computed(
    () => currentCountdown.countdown.value > 0 || currentOtpLoading.value || loading.value || changeDone.value
  )
  const newOtpBtnDisabled = computed(
    () =>
      newCountdown.countdown.value > 0 ||
      newOtpLoading.value ||
      loading.value ||
      changeDone.value ||
      !isValidEmail(newEmail.value.trim())
  )

  const mapError = (e: unknown, fallback: string) =>
    isRateLimited(e) ? t('auth.rateLimited') : getErrorDetail(e, fallback)

  const reset = () => {
    newEmail.value = ''
    currentCode.value = ''
    newCode.value = ''
    loading.value = false
    currentOtpLoading.value = false
    newOtpLoading.value = false
    errorMsg.value = ''
    successMsg.value = ''
    changeDone.value = false
    currentCountdown.reset()
    newCountdown.reset()
  }

  const handleSendCurrentOtp = async () => {
    errorMsg.value = ''
    successMsg.value = ''
    if (currentOtpBtnDisabled.value) return
    currentOtpLoading.value = true
    try {
      await sendCurrentOtp()
      currentCountdown.start()
      successMsg.value = t('auth.emailChangeCurrentOtpSent')
    } catch (e: unknown) {
      errorMsg.value = mapError(e, t('auth.sendOtpFailed'))
    } finally {
      currentOtpLoading.value = false
    }
  }

  const handleSendNewOtp = async () => {
    errorMsg.value = ''
    successMsg.value = ''
    const target = newEmail.value.trim()
    if (!isValidEmail(target)) {
      errorMsg.value = t('auth.invalidEmail')
      return
    }
    if (newOtpBtnDisabled.value) return
    newOtpLoading.value = true
    try {
      await sendNewOtp(target)
      newCountdown.start()
      successMsg.value = t('auth.emailChangeNewOtpSent')
    } catch (e: unknown) {
      errorMsg.value = mapError(e, t('auth.sendOtpFailed'))
    } finally {
      newOtpLoading.value = false
    }
  }

  const handleSubmit = async () => {
    errorMsg.value = ''
    successMsg.value = ''
    const target = newEmail.value.trim()
    if (!isValidEmail(target)) {
      errorMsg.value = t('auth.invalidEmail')
      return
    }
    if (!isValidOtp(currentCode.value) || !isValidOtp(newCode.value)) {
      errorMsg.value = t('auth.invalidOtp')
      return
    }
    loading.value = true
    try {
      const result = await submit(target, currentCode.value.trim(), newCode.value.trim())
      await onChanged?.(result)
      changeDone.value = true
      successMsg.value = t('auth.emailChangeSuccess')
      currentCountdown.reset()
      newCountdown.reset()
    } catch (e: unknown) {
      errorMsg.value = mapError(e, t('auth.emailChangeFailed'))
    } finally {
      loading.value = false
    }
  }

  return {
    newEmail,
    currentCode,
    newCode,
    loading,
    currentOtpLoading,
    newOtpLoading,
    errorMsg,
    successMsg,
    changeDone,
    currentOtpCountdown: currentCountdown.countdown,
    newOtpCountdown: newCountdown.countdown,
    currentOtpBtnDisabled,
    newOtpBtnDisabled,
    reset,
    handleSendCurrentOtp,
    handleSendNewOtp,
    handleSubmit,
  }
}
