const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const OTP_PATTERN = /^\d{6}$/

interface AuthErrorDetail {
  msg?: string
  message?: string
  detail?: string
}

interface AuthError {
  response?: {
    status?: number
    data?: { detail?: string | AuthErrorDetail | Array<string | AuthErrorDetail> }
  }
  message?: string
}

export const PASSWORD_MIN_LENGTH = 8

export const OTP_COUNTDOWN_SECONDS = 60
export const OTP_COUNTDOWN_INTERVAL_MS = 1000
export const REGISTER_SUCCESS_MESSAGE_DURATION_MS = 4000
export const REGISTER_REDIRECT_DELAY_MS = 800
export const PASSWORD_RESET_REDIRECT_DELAY_MS = 1000

export const getSafeInternalRedirect = (value: unknown): string =>
  typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/'

export const hasTrimmedValue = (value: string): boolean => Boolean(value.trim())

export const isValidEmail = (value: string): boolean => EMAIL_PATTERN.test(value.trim())

export const isValidOtp = (value: string): boolean => OTP_PATTERN.test(value.trim())

export const isValidPassword = (value: string): boolean => value.length >= PASSWORD_MIN_LENGTH

export const passwordsMatch = (password: string, confirmation: string): boolean =>
  password === confirmation

export const getErrorDetail = (error: unknown, fallback: string): string => {
  const authError = error as AuthError
  const detail = authError?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item === 'string' ? item : item.msg || item.message || item.detail || ''))
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  } else if (detail && typeof detail === 'object') {
    const message = detail.msg || detail.message || detail.detail
    if (message) return message
  }
  return authError?.message || fallback
}

export const isRateLimited = (error: unknown): boolean =>
  (error as AuthError)?.response?.status === 429
