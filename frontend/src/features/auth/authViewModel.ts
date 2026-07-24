const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const OTP_PATTERN = /^\d{6}$/

interface AuthError {
  response?: {
    status?: number
    data?: { detail?: string }
  }
  message?: string
}

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

export const isValidPassword = (value: string): boolean => value.length >= 6

export const passwordsMatch = (password: string, confirmation: string): boolean =>
  password === confirmation

export const getErrorDetail = (error: unknown, fallback: string): string => {
  const authError = error as AuthError
  return authError?.response?.data?.detail || authError?.message || fallback
}

export const isRateLimited = (error: unknown): boolean =>
  (error as AuthError)?.response?.status === 429
