import type { AuthStatus } from '@/stores/authStore'

/** 试用天数，与后端 services/membership/trial.TRIAL_DAYS 一致；游客还没有试用状态可读时按它报天数。 */
export const TRIAL_DAYS = 7

/** 会员试用（每个账号一次、7 天）：GET/POST /api/membership/trial 的响应形状，与后端 trial_status 一致。 */
export interface MembershipTrialStatus {
  days: number
  available: boolean
  active: boolean
  started_at: string | null
  expires_at: string | null
}

/**
 * 会员卡上试用入口的样子：guest 游客（点了先登录）；available 能领；
 * active 试用中（报到期时间，开通按钮照常在）；none 不显示（登录状态没定、读不到、用过了、已是会员）。
 */
export type TrialOffer = 'none' | 'guest' | 'available' | 'active'

export const trialOffer = (authStatus: AuthStatus, status: MembershipTrialStatus | null): TrialOffer => {
  if (authStatus === 'anonymous') return 'guest'
  if (authStatus !== 'authenticated' || !status) return 'none'
  if (status.active) return 'active'
  return status.available ? 'available' : 'none'
}

/** 409 的 detail 码对应的文案键；其余失败一律「没开通成功，稍后再试」。 */
const CONFLICT_KEYS: Record<string, string> = {
  trial_already_used: 'membership.trial.alreadyUsed',
  already_member: 'membership.trial.alreadyMember',
}

export const trialErrorKey = (error: unknown): string => {
  const response = (error as { response?: { status?: unknown; data?: { detail?: unknown } } } | null)?.response
  const detail = response?.status === 409 ? response.data?.detail : undefined
  return (typeof detail === 'string' && CONFLICT_KEYS[detail]) || 'membership.trial.failed'
}

/** 试用到期时刻：试用只有 7 天，精确到分钟（「10月12日 20:05」）；解析不了时返回空串。 */
export const formatTrialEnd = (value: string | null | undefined, locale: string): string => {
  const timestamp = value ? Date.parse(value) : Number.NaN
  if (Number.isNaN(timestamp)) return ''
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp)
}
