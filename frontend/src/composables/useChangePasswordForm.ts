import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getErrorDetail,
  hasTrimmedValue,
  isRateLimited,
  isValidPassword,
  passwordsMatch,
} from '@/features/auth/authViewModel'

interface ChangePasswordFormOptions {
  submit: (currentPassword: string, newPassword: string) => Promise<unknown>
  /** 改密成功后回调（如刷新 /auth/me 以清除默认密码提醒） */
  onChanged?: () => Promise<void> | void
}

/** 已登录改密表单状态：当前密码 + 新密码确认（无需邮箱验证码） */
export function useChangePasswordForm({ submit, onChanged }: ChangePasswordFormOptions) {
  const { t } = useI18n()

  const currentPwd = ref('')
  const password = ref('')
  const confirmPwd = ref('')
  const loading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const changeDone = ref(false)

  const reset = () => {
    currentPwd.value = ''
    password.value = ''
    confirmPwd.value = ''
    loading.value = false
    errorMsg.value = ''
    successMsg.value = ''
    changeDone.value = false
  }

  const handleSubmit = async () => {
    errorMsg.value = ''
    successMsg.value = ''
    if (!hasTrimmedValue(currentPwd.value)) {
      errorMsg.value = t('auth.currentPasswordRequired')
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
      await submit(currentPwd.value, password.value)
      changeDone.value = true
      successMsg.value = t('auth.changeSuccess')
      await onChanged?.()
    } catch (e: unknown) {
      errorMsg.value = isRateLimited(e)
        ? t('auth.rateLimited')
        : getErrorDetail(e, t('auth.changeFailed'))
    } finally {
      loading.value = false
    }
  }

  return {
    currentPwd,
    password,
    confirmPwd,
    loading,
    errorMsg,
    successMsg,
    changeDone,
    reset,
    handleSubmit,
  }
}
